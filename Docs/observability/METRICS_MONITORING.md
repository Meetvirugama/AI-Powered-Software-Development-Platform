# Metrics and Monitoring

> **Project:** AI-Powered Software Development Platform  
> **Feature:** F31 — Logging, telemetry, health: Distributed Tracing, LLM Observability & Agent Execution Monitoring  
> **Status:** Active / Production-Ready  
> **Related Issue:** [#212](https://github.com/Meetvirugama/AI-Powered-Software-Development-Platform/issues/212)

---

## 1. Overview

The platform implements a multi-tier metrics architecture:
1. **OpenTelemetry System & GenAI Metrics:** Aggregated, time-series metrics exported via OTLP to Prometheus, Datadog, or Grafana Mimir.
2. **In-App Stage-Level Telemetry:** Historical execution metrics stored within `AnalysisRun.result_payload["stage_metrics"]` to power frontend progress cards and historical analysis comparisons.

---

## 2. OpenTelemetry Metric Instruments

Defined in `app.observability.metrics`, all instruments adhere strictly to OpenTelemetry semantic naming:

| Instrument Name | Type | Unit | Description | Bound Attribute Dimensions |
|---|---|---|---|---|
| `llm_requests_total` | Counter | `{requests}` | Total count of LLM requests dispatched | `system`, `model`, `status`, `fallback` |
| `llm_request_duration_seconds` | Histogram | `s` | Distribution of LLM latency | `system`, `model`, `status` |
| `agent_executions_total` | Counter | `{executions}` | Total count of autonomous agent loops | `status` |
| `agent_execution_duration_seconds`| Histogram | `s` | Distribution of total agent loop time | `status` |
| `tool_invocations_total` | Counter | `{invocations}`| Total count of tool invocations | `tool`, `status` |
| `tool_invocation_duration_seconds` | Histogram | `s` | Latency distribution of tool execution | `tool`, `status` |

---

## 3. Strict Cardinality Management

High cardinality is the primary cause of telemetry system performance degradation and storage bloat. To maintain bounded resource utilization:

### 3.1 Allowed Low-Cardinality Labels
Only dimensions with a finite, predictable set of values are permitted as metric attributes:
- `system`: `gemini`, `groq` (cardinality: 2)
- `model`: Standard model identifiers, e.g. `gemini-2.5-pro`, `llama-3.3-70b-versatile` (cardinality: < 10)
- `status`: `success`, `error`, `fallback`, `completed`, `failed` (cardinality: < 5)
- `tool`: Registered tool names, e.g. `workspace.read_file`, `git.commit` (cardinality: < 30)

### 3.2 Strictly Forbidden High-Cardinality Labels
The following variables must **NEVER** be attached to OpenTelemetry metric dimensions:
- `trace_id` or `span_id` (unbounded UUIDs)
- `request_id` or `analysis_run_id` (unbounded UUIDs)
- `task_id` or `repository_id` (unbounded IDs)
- Usernames, file paths, or commit hashes

*(Note: These high-cardinality IDs are attached to **Traces** and **Structured Logs**, where they belong for exact single-event lookup).*

---

## 4. Preservation of In-App `stage_metrics`

The application persists granular stage-by-stage timings and token statistics inside `AnalysisRun.result_payload["stage_metrics"]`:

```json
{
  "stage_metrics": {
    "ast_parsing": {
      "duration_ms": 320.5,
      "symbols_indexed": 48
    },
    "context_retrieval": {
      "duration_ms": 540.2,
      "chunks_retrieved": 12
    },
    "llm_reasoning": {
      "duration_ms": 1420.0,
      "model": "gemini-2.5-pro",
      "tokens_in": 1250,
      "tokens_out": 340,
      "estimated_cost_usd": 0.0018
    }
  }
}
```

This in-app mechanism is strictly preserved and complemented by OpenTelemetry:
- Frontend analysis cards consume `stage_metrics` directly from the REST API without requiring access to an external telemetry backend.
- `StageExecutionTimer` continues to record timings and token counts per stage.

---

## 5. Dashboard Recommendations

For operations teams monitoring production clusters via Grafana or Datadog, the following panels are recommended:

1. **LLM Request Volume & Error Rate (Top Panel):**  
   `sum(rate(llm_requests_total[5m])) by (model, status)`
2. **LLM Provider Fallback Rate:**  
   `sum(rate(llm_requests_total{fallback="true"}[5m])) / sum(rate(llm_requests_total[5m])) * 100`
3. **P95 & P99 LLM Latency by Model:**  
   `histogram_quantile(0.95, sum(rate(llm_request_duration_seconds_bucket[5m])) by (le, model))`
4. **Agent Tool Execution Breakdown:**  
   `sum(rate(tool_invocations_total[5m])) by (tool, status)`
5. **Slowest Tools (P95 Latency):**  
   `histogram_quantile(0.95, sum(rate(tool_invocation_duration_seconds_bucket[5m])) by (le, tool))`
