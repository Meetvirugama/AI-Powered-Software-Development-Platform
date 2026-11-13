# 30. Distributed Tracing, LLM Observability & Agent Monitoring

> **Project:** AI-Powered Software Development Platform  
> **Feature:** F31 — Logging, telemetry, health: Distributed Tracing, LLM Observability & Agent Execution Monitoring  
> **Status:** Active / Production-Ready  
> **Author:** Meet  
> **Date:** 2026-11-13  
> **Related Issue:** [#212](https://github.com/Meetvirugama/AI-Powered-Software-Development-Platform/issues/212)

---

## 1. Overview

This document specifies the technical implementation of distributed tracing, GenAI observability, and autonomous agent monitoring in the platform.

For exhaustive specifications and subsystem deep-dives, refer to the dedicated observability documentation suite:
- [Observability Architecture](../observability/OBSERVABILITY_ARCHITECTURE.md)
- [Distributed Tracing Design](../observability/DISTRIBUTED_TRACING_DESIGN.md)
- [GenAI Observability & Semantic Tracing](../observability/GENAI_OBSERVABILITY.md)
- [Langfuse Integration Guide](../observability/LANGFUSE_INTEGRATION.md)
- [Metrics and Monitoring](../observability/METRICS_MONITORING.md)
- [Implementation & Verification Report](../observability/OBSERVABILITY_IMPLEMENTATION_REPORT.md)

---

## 2. Key Architecture Components

```
backend/app/observability/
├── __init__.py                # Package exports
├── telemetry.py               # TelemetryManager, TracerProvider & MeterProvider singleton
├── genai.py                   # GenAI semantic attribute keys & builder
├── agent.py                   # trace_agent_execution & trace_tool_invocation
├── langfuse_adapter.py        # Fail-safe Langfuse adapter with privacy opt-in
├── metrics.py                 # Low-cardinality OTel metrics instruments
└── instrumentation.py         # FastAPI, HTTPX, SQLAlchemy, Redis auto-instrumentation
```

### 2.1 Trace Context Flow

1. Inbound HTTP requests hit FastAPI; `FastAPIInstrumentor` extracts W3C `traceparent` or creates a root server span.
2. `JsonFormatter` dynamically enriches log records with active `trace_id` and `span_id`.
3. Agent loops start an `agent.execution` parent span via `trace_agent_execution`.
4. Tool invocations via `ToolRouter.route()` generate child spans `tool:{tool_name}` via `trace_tool_invocation`.
5. Model requests through `LLMGateway` create `gen_ai.generate` child spans with OpenTelemetry GenAI semantic attributes, latency timing, token cost estimation, and fallback tracking.
6. The `LangfuseAdapter` asynchronously records generation events and tool executions to Langfuse with fail-safe isolation and zero-data-retention defaults.
7. Background spans are batched and exported to the configured OTLP collector endpoint.

---

## 3. Backward Compatibility & Health Verification

1. **In-App `stage_metrics`:** Strictly preserved in `AnalysisRun.result_payload["stage_metrics"]`.
2. **Health Endpoints:** `/health`, `/health/live`, and `/health/ready` check only internal PostgreSQL and Redis connections and never fail due to external telemetry sink outages.
3. **Graceful Fallback:** If OpenTelemetry or Langfuse are disabled or misconfigured, the application runs normally with zero runtime performance penalty.
