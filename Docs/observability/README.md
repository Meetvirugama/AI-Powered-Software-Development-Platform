# Observability & Distributed Tracing Documentation

> **Feature:** F31 — Logging, telemetry, health: Distributed Tracing, LLM Observability & Agent Execution Monitoring  
> **Related Issue:** [#212](https://github.com/Meetvirugama/AI-Powered-Software-Development-Platform/issues/212)

---

## Documentation Index

1. [Observability Architecture](./OBSERVABILITY_ARCHITECTURE.md)  
   Core architecture, component responsibilities, end-to-end trace lifecycle, and system diagrams.

2. [Distributed Tracing Design](./DISTRIBUTED_TRACING_DESIGN.md)  
   W3C context propagation, span hierarchy, auto-instrumentations (FastAPI, HTTPX, SQLAlchemy, Redis), and sampling.

3. [GenAI Observability & Semantic Tracing](./GENAI_OBSERVABILITY.md)  
   OpenTelemetry GenAI conventions, LLMGateway spans, provider fallback tracing, streaming spans, and tool execution.

4. [Langfuse Integration Guide](./LANGFUSE_INTEGRATION.md)  
   Cloud vs self-hosted deployment, adapter pattern, privacy opt-in controls, and fail-safe isolation.

5. [Metrics and Monitoring](./METRICS_MONITORING.md)  
   OTel metric instruments, cardinality management, in-app `stage_metrics` preservation, and recommended dashboards.

6. [Observability Implementation Report](./OBSERVABILITY_IMPLEMENTATION_REPORT.md)  
   Summary of files created/modified, test verification results, and performance impact.
