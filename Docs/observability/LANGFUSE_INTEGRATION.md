# Langfuse Integration Guide

> **Project:** AI-Powered Software Development Platform  
> **Feature:** F31 — Logging, telemetry, health: Distributed Tracing, LLM Observability & Agent Execution Monitoring  
> **Status:** Active / Production-Ready  
> **Related Issue:** [#212](https://github.com/Meetvirugama/AI-Powered-Software-Development-Platform/issues/212)

---

## 1. Overview

**Langfuse** serves as the dedicated LLM application observability platform. While OpenTelemetry handles platform-wide distributed tracing and system metrics, Langfuse specializes in:
- Model prompt versioning and evaluation.
- Token cost tracking by model, tenant, and feature.
- Multi-turn conversational session tracking.
- Latency percentile monitoring (P50, P95, P99).
- User feedback and scoring loops.

The platform integrates Langfuse via `LangfuseAdapter` located in `app.observability.langfuse_adapter`.

---

## 2. Deployment Options

The platform supports both Langfuse Cloud and self-hosted instances:

### 2.1 Langfuse Cloud (Managed)
- Set `LANGFUSE_HOST=https://cloud.langfuse.com` (or EU endpoint `https://europe-west3.langfuse.com`).
- Provision project keys from the Langfuse Cloud Settings page.

### 2.2 Self-Hosted (Docker Compose / Kubernetes)
For enterprise air-gapped or on-premises installations, deploy the official Langfuse stack:

```yaml
version: '3.8'
services:
  langfuse-server:
    image: langfuse/langfuse:2
    depends_on:
      - langfuse-db
    ports:
      - "3000:3000"
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@langfuse-db:5432/langfuse
      - NEXTAUTH_SECRET=changeme-supersecret
      - SALT=changeme-salt
      - NEXTAUTH_URL=http://localhost:3000
      - TELEMETRY_ENABLED=false

  langfuse-db:
    image: postgres:16-alpine
    environment:
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=postgres
      - POSTGRES_DB=langfuse
    volumes:
      - langfuse_data:/var/lib/postgresql/data

volumes:
  langfuse_data:
```

Configure application settings:
```bash
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

---

## 3. SDK Integration & Adapter Pattern

The platform wraps the official `langfuse` Python SDK in `LangfuseAdapter`, ensuring complete decoupling, clean test mocking, and safe error boundaries.

```python
from app.observability.langfuse_adapter import get_langfuse_adapter

adapter = get_langfuse_adapter()

# Record an LLM generation
adapter.record_generation(
    name="analysis.code_review",
    model="gemini-2.5-pro",
    input_tokens=1420,
    output_tokens=310,
    latency_s=1.24,
    trace_id=trace_id_str,
    cost_usd=0.0018,
    prompt_text=prompt if settings.observability_capture_prompts else None,
    completion_text=completion if settings.observability_capture_responses else None,
    metadata={"analysis_run_id": run_id, "provider": "gemini"},
)
```

---

## 4. Privacy & Data Protection Safeguards

Enterprise source code and user intellectual property require strict privacy boundaries. By default, the adapter implements a **Zero Data Retention for Raw Content** policy:

### 4.1 Opt-in Prompt & Completion Capture
Raw text prompts and completions are **never transmitted** to Langfuse unless explicitly enabled via environment configuration:
- `OBSERVABILITY_CAPTURE_PROMPTS=false` (Default: `false`)
- `OBSERVABILITY_CAPTURE_RESPONSES=false` (Default: `false`)

When disabled, Langfuse receives only metadata:
- Model name and version.
- Token counts (`input_tokens`, `output_tokens`).
- Wall-clock latency and calculated USD cost.
- Success / Error status codes.

### 4.2 Sensitive Information Masking
Even when prompt capture is enabled for debugging environments, `OBSERVABILITY_MASK_SENSITIVE_DATA=true` passes text through `app.core.secret_redaction`, stripping:
- GitHub Personal Access Tokens and App Private Keys.
- Bearer tokens, JWTs, and API credentials (`AIza...`, `gsk_...`).
- Database connection strings and passwords.
- PII (email addresses, private IPs).

---

## 5. Fail-Safe Error Isolation

Under no circumstances may a Langfuse service degradation, timeout, or authentication failure impact user-facing functionality:

1. **Defensive Try/Except:** All methods in `LangfuseAdapter` catch `Exception` and log debug diagnostics without raising.
2. **Graceful Fallback:** If Langfuse credentials are not provided or invalid, the adapter initializes as a no-op null client (`self.is_enabled = False`).
3. **Background Flush:** The client batches calls and dispatches them asynchronously over HTTP. `shutdown()` invokes `client.shutdown()` with an isolated timeout during platform termination.
