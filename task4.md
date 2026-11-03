# AI Layer Audit & File-by-File Implementation Plan

**Repository:** `AI-Powered-Software-Development-Platform`  
**Scope:** `backend/ai/` plus its integration boundaries in `backend/app/`, `backend/indexer/`, and AI-related tests.  
**Purpose:** Make the AI layer reliable, secure, cost-aware, measurable, maintainable, and production-ready without rewriting working components unnecessarily.

---

## 1. Executive assessment

The repository already has a substantial AI architecture rather than a minimal LLM wrapper. It contains:

- A central LLM gateway with Gemini and Groq providers and fallback support.
- An embedding abstraction and Gemini embedding provider.
- Hybrid retrieval built from vector search, PostgreSQL full-text search, fusion, and optional reranking.
- A RAG pipeline with context assembly, prompt construction, output validation, and grounding checks.
- Dedicated services for code review, bug detection, explanation, test generation, task planning, agent execution, bounded repair, and requirement verification.
- Specialized context builders and prompt templates for each capability.

The main improvement is **not** to replace this architecture with another framework. The priority is to reduce overlapping orchestration, enforce end-to-end contracts, improve retrieval/grounding quality, make provider behavior deterministic, and put hard safety/cost limits around agentic code changes.

### Highest-priority risks to address

1. **One canonical execution path per capability.** The `backend/ai/services/*` engines coexist with large `backend/app/services/*_orchestrator.py` implementations. Confirm which layer owns business orchestration and which owns reusable AI logic. Avoid maintaining two implementations of the same workflow.
2. **LLM provider fallback correctness.** `LLMGateway` retries on authentication errors as well as transient errors. A bad key/configuration should normally be surfaced rather than silently routed to another provider. Cross-provider model-name translation must be explicit and tested.
3. **Provider lifecycle and concurrency.** Ensure HTTP clients, key rotation, rate-limit handling, retry budgets, timeouts, cancellation, and shutdown are consistent across Gemini/Groq and embeddings.
4. **RAG evidence quality.** Vector and lexical results must be fused with stable scores, deduplicated, filtered to the authorized repository, and converted into source references that can be checked against actual indexed content.
5. **Grounded output validation.** Schema-valid JSON is not necessarily correct. Every code finding, explanation, test, and answer needs source/evidence validation appropriate to the task.
6. **Agent write safety.** Planning, tool calls, patch application, repair loops, test execution, and requirement verification need explicit budgets, path boundaries, approvals, and rollback behavior.
7. **Cost and latency controls.** Enforce per-operation token ceilings, context budgets, model routing, request concurrency, provider quotas, caching, and telemetry at the gateway—not independently in every endpoint.
8. **Evaluation before prompt/model changes.** Establish a versioned regression dataset and quality metrics before changing prompts, retrieval weights, chunking, model defaults, or repair behavior.

---

## 2. Scope and verified inventory

Static source inspection found **64 files under `backend/ai/`**, including **52 Python files** and **12 prompt/documentation text files**. The Python files contain approximately **11,971 lines**.

Largest AI Python modules by line count:

| File | Lines | Recommendation |
|---|---:|---|
| `backend/ai/pipeline.py` | 672 | Split by responsibility after tests and contracts are in place. |
| `backend/ai/context/service.py` | 540 | Split by responsibility after tests and contracts are in place. |
| `backend/ai/services/agent_execution_loop.py` | 533 | Split by responsibility after tests and contracts are in place. |
| `backend/ai/services/bounded_repair_loop.py` | 498 | Split by responsibility after tests and contracts are in place. |
| `backend/ai/services/task_planner.py` | 457 | Split by responsibility after tests and contracts are in place. |
| `backend/ai/services/issue_task_adapter.py` | 400 | Split by responsibility after tests and contracts are in place. |
| `backend/ai/services/ai_quality_evaluator.py` | 388 | Split by responsibility after tests and contracts are in place. |
| `backend/ai/context/models.py` | 384 | Split by responsibility after tests and contracts are in place. |
| `backend/ai/schemas/grounding.py` | 366 | Split by responsibility after tests and contracts are in place. |
| `backend/ai/llm/groq_provider.py` | 343 | Split by responsibility after tests and contracts are in place. |
| `backend/ai/services/retrieval_optimizer.py` | 310 | Split by responsibility after tests and contracts are in place. |
| `backend/ai/services/requirement_verifier.py` | 307 | Split by responsibility after tests and contracts are in place. |
| `backend/ai/context/review_context.py` | 280 | Split by responsibility after tests and contracts are in place. |
| `backend/ai/llm/gemini_provider.py` | 279 | Split by responsibility after tests and contracts are in place. |
| `backend/ai/llm/schemas.py` | 276 | Split by responsibility after tests and contracts are in place. |


This is a source audit, not a claim that the full application has passed runtime tests. No live provider calls, database integration run, load test, or end-to-end agent execution was performed as part of this static inspection.

---

## 3. Target architecture

Keep the existing package boundaries, but make ownership explicit:

```text
API / application orchestrators
        |
        v
Capability services
  - chat / repository Q&A
  - code review
  - bug detection
  - explanation
  - test generation
  - task planning / code modification
        |
        +-------------------------------+
        |                               |
        v                               v
Context & retrieval                 Agent safety layer
  - context builder                   - tool policy
  - token budget                      - workspace boundary
  - hybrid retriever                  - patch validation
  - reranker                          - test runner limits
  - source references                 - approval / rollback
        |                               |
        v                               v
Grounding + output validation      Sandbox execution
        |
        v
LLM Gateway / Embedding Gateway
        |
        +--> Gemini
        +--> Groq
        +--> future local / OpenAI-compatible provider
        |
        v
Telemetry, budgets, cache, evaluation
```

### Ownership rules

- `backend/ai/llm/` owns provider-independent LLM request/response contracts and provider adapters.
- `backend/ai/embeddings/` owns embedding contracts, batching, dimensions, and provider adapters.
- `backend/ai/retrieval/` owns retrieval algorithms only. It must not own API response formatting or task lifecycle.
- `backend/ai/context/` owns context extraction/assembly and token budgeting. It must not make provider calls.
- `backend/ai/schemas/` owns structured output contracts, parsing, validation, and grounding rules.
- `backend/ai/services/` owns reusable AI capability logic.
- `backend/app/services/` owns application workflows, authorization, persistence, task state, and orchestration with repositories/sandbox.
- `backend/agent/` and `backend/sandbox/` own tool execution and isolation. AI-generated content is always untrusted input to these packages.

---

## 4. P0 — Fix correctness and safety before refactoring

### P0.1 LLM gateway and provider behavior

**Files**
- `backend/ai/llm/client.py`
- `backend/ai/llm/provider.py`
- `backend/ai/llm/schemas.py`
- `backend/ai/llm/gemini_provider.py`
- `backend/ai/llm/groq_provider.py`
- `backend/app/core/lifespan.py`

**Required changes**

1. Define a provider error taxonomy with clear retryability:
   - Retryable: connection reset, provider 5xx, timeout, temporary overload, rate limit after bounded backoff.
   - Non-retryable: invalid request, unsupported model, malformed schema, invalid credentials, policy rejection.
2. Do not automatically fallback on `LLMAuthenticationError` by default. Make authentication fallback an explicit policy because it can hide broken credentials and complicate incident diagnosis.
3. Make fallback policy configurable per capability and request sensitivity. Do not fallback if the secondary model cannot satisfy the requested structured-output contract.
4. Add explicit model compatibility mapping. Do not infer compatibility from broad string prefixes alone.
5. Preserve the original request semantics during fallback: system/developer instructions, response schema, temperature, max output tokens, safety settings, and tool restrictions.
6. Add one bounded retry policy with exponential backoff and jitter. Avoid retry multiplication across gateway, provider SDK, endpoint, and task worker.
7. Add request timeout, total deadline, max in-flight calls, and cancellation propagation.
8. Ensure `aclose()` closes both provider clients even if closing the primary raises; report cleanup failures without leaking resources.
9. Add a stable request/correlation ID to logs and traces. Never log prompts, source code, secrets, or full model output by default.
10. Normalize provider usage metadata. Distinguish provider-reported token usage from local estimates.

**Acceptance tests**
- Primary success; fallback on timeout; fallback on transient 5xx; no fallback on invalid credentials unless policy explicitly permits it.
- Cross-provider model mapping; structured-output schema preservation.
- Both providers close even if one close operation fails.
- Timeout and cancellation stop the operation within the configured deadline.
- Rate-limit retry respects `Retry-After` where available and never exceeds the request retry budget.

### P0.2 Gemini and Groq adapters

**Files**
- `backend/ai/llm/gemini_provider.py`
- `backend/ai/llm/groq_provider.py`
- `backend/ai/llm/provider.py`
- `backend/ai/llm/schemas.py`

**Required changes**

- Normalize SDK-specific response formats in the provider adapter; no Gemini/Groq response parsing in capability services.
- Validate model names and provider capabilities at startup or configuration validation time.
- Make API-key rotation deterministic and concurrency-safe. Track which key was selected, but never log the key or a reversible fragment.
- Distinguish quota exhaustion from temporary rate limiting and invalid credentials.
- Ensure provider SDK retries are either disabled or included in the gateway's global retry budget.
- Bound response size and reject empty/truncated/malformed responses with typed errors.
- Normalize finish reasons, safety blocks, tool-call responses, usage fields, and provider request IDs.
- Add per-provider concurrency semaphores to prevent one provider from exhausting sockets or quotas.
- Review every broad `except Exception`; translate known provider failures and re-raise unknown programming errors rather than converting all errors into a generic provider outage.
- Inspect the `pass` at `backend/ai/llm/groq_provider.py` near the end of the file. Determine whether it is an intentional abstract/no-op cleanup branch or an unfinished implementation; replace it with explicit behavior or remove it. Do not leave ambiguous silent no-ops.

### P0.3 Embedding correctness and model versioning

**Files**
- `backend/ai/embeddings/client.py`
- `backend/ai/embeddings/service.py`
- `backend/ai/embeddings/gemini_provider.py`
- `backend/app/core/lifespan.py`
- `backend/app/services/sync_worker.py`
- `backend/indexer/` (embedding/index write path)
- `backend/ai/retrieval/vector.py`

**Required changes**

1. Define a single embedding profile: provider, model, dimensions, normalization, distance metric, and profile version.
2. Store the embedding profile/version with each indexed chunk or repository index generation.
3. Reject queries whose embedding profile/dimensions do not match the indexed vectors. Do not silently mix models or dimensions.
4. Make embedding batch size and concurrency configurable, with conservative defaults and provider-specific caps.
5. Retry only retryable failures. Preserve input ordering after concurrent batch execution.
6. Validate vector length, numeric finiteness, and normalization expectations. Reject NaN/Infinity and malformed vectors before database writes.
7. Add idempotent indexing behavior so retries do not create duplicate chunk vectors.
8. Make re-embedding a controlled index migration, not an implicit side effect of a model change.
9. Track embedding latency, batch count, item count, failure count, and provider usage.
10. Test empty batches, one item, exact batch boundary, multi-batch order preservation, partial batch failure, dimension mismatch, and cancellation.

### P0.4 Grounding and structured output

**Files**
- `backend/ai/schemas/grounding.py`
- `backend/ai/schemas/output.py`
- `backend/ai/schemas/validator.py`
- `backend/ai/schemas/prompt_builder.py`
- `backend/ai/schemas/errors.py`
- `backend/ai/prompts/grounding_system.txt`
- `backend/ai/prompts/source_grounding.txt`

**Required changes**

- Treat parsing, schema validation, semantic validation, and evidence validation as separate stages.
- Validate source references against retrieved chunk IDs, repository ID, file path, and line ranges.
- Reject citations to files/chunks not present in the current authorized retrieval result.
- Ensure line ranges are positive, ordered, and within the source file's known line count.
- Validate that generated findings have a severity, category, actionable message, and evidence where required.
- Do not let the model invent file paths, symbols, line numbers, or repository IDs.
- For code review and bug detection, distinguish confirmed issue, possible issue, and informational observation.
- For repository chat, allow an explicit “insufficient evidence” answer when retrieval is weak.
- Add adversarial tests for prompt injection inside repository files, comments, README content, commit messages, and issue descriptions.
- Ensure any fallback parser is strict and bounded. Never use `eval` or permissive parsing that can execute model output.
- Preserve raw model output only in access-controlled, retention-limited diagnostic storage if needed.

### P0.5 Agentic code-change safety

**Files**
- `backend/ai/services/agent_execution_loop.py`
- `backend/ai/services/bounded_repair_loop.py`
- `backend/ai/services/requirement_verifier.py`
- `backend/ai/services/task_planner.py`
- `backend/ai/services/issue_task_adapter.py`
- `backend/app/services/task_execution_orchestrator.py`
- `backend/agent/`
- `backend/sandbox/`

**Required changes**

1. Define a strict task state machine: planned → approved/running → validating → completed/failed/cancelled. Disallow illegal transitions.
2. Separate model planning from tool authorization. The model may propose an action; deterministic policy decides whether it is allowed.
3. Give every task hard limits: wall-clock time, model calls, total tokens, tool calls, changed files, patch size, test duration, process count, and repair iterations.
4. Enforce repository/workspace ownership and path boundaries at the tool boundary, not only in prompts.
5. Require diff validation before tests and again before commit/PR creation.
6. Do not allow generated code to change CI, deployment secrets, permissions, or security policy without explicit approval.
7. Treat repository files and issue text as untrusted instructions. They are data, not system prompts.
8. Make test execution isolated, resource-limited, network-restricted by default, and killable.
9. Require requirement verification to cite concrete diff/test evidence. “The model says it is done” is not completion.
10. Persist an audit trail of plan, approved tools, actions, diffs, test results, and final decision.
11. Make repair loops stop on repeated identical failures, no-progress patches, budget exhaustion, or regression.
12. Add cancellation checks before and after every model call and tool execution.

---

## 5. P1 — Improve RAG and code intelligence quality

### P1.1 Retrieval pipeline

**Files**
- `backend/ai/retrieval/base.py`
- `backend/ai/retrieval/vector.py`
- `backend/ai/retrieval/lexical.py`
- `backend/ai/retrieval/hybrid.py`
- `backend/ai/retrieval/fusion.py`
- `backend/ai/retrieval/reranker.py`
- `backend/ai/retrieval/pipeline.py`
- `backend/ai/services/retrieval_optimizer.py`
- `backend/app/api/v1/repositories.py`
- `backend/indexer/`

**Required changes**

- Keep vector and lexical retrievers independently testable behind the same `Retriever` contract.
- Add repository and tenant authorization filters to every retrieval query. Verify that `repository_id` cannot be swapped to access another user's indexed code.
- Make retrieval `top_k`, candidate pool size, RRF constant, reranker candidate count, and score thresholds configurable per operation.
- Deduplicate by stable chunk ID/content hash before fusion and again after reranking.
- Use reciprocal-rank fusion as a robust baseline; do not combine raw vector cosine scores and lexical scores as if they were calibrated.
- Ensure lexical query sanitization handles stop words, punctuation-only strings, identifiers, snake_case, camelCase, paths, and quoted symbols.
- Consider code-aware tokenization and PostgreSQL text-search configurations for programming identifiers; English stemming alone is insufficient for code.
- Add path, symbol, language, file type, and chunk metadata filters where useful.
- Apply reranking only when candidate count and latency budget justify it. Provide a deterministic no-reranker path.
- Add query rewriting only when it improves retrieval on an evaluation set; keep the original query and rewritten query traceable.
- Return retrieval diagnostics (candidate counts, source retriever, rank, scores, reranker score) internally, without leaking sensitive code to ordinary logs.
- Add explicit empty-index and retrieval-unavailable behavior. Do not present “no evidence” as “repository has no bug.”
- Add query-level caching keyed by repository index generation and embedding profile; invalidate on reindex.
- Review SQL execution and transaction/session ownership for both session instances and session factories. Avoid consuming results after the session is closed.

**Acceptance tests**
- Cross-repository isolation.
- Empty index, no lexical tokens, vector provider unavailable, lexical DB failure, reranker unavailable.
- Duplicate chunks across retrievers.
- Stable ordering for equal scores.
- Code identifiers and file-path queries.
- Index-generation cache invalidation.
- Retrieval latency and result-count budgets.

### P1.2 Context construction and token budgeting

**Files**
- `backend/ai/context/builder.py`
- `backend/ai/context/models.py`
- `backend/ai/context/service.py`
- `backend/ai/context/token_budget.py`
- `backend/ai/context/chat_context.py`
- `backend/ai/context/intelligence_context.py`
- `backend/ai/context/bug_context.py`
- `backend/ai/context/review_context.py`
- `backend/ai/context/explanation.py`
- `backend/ai/context/test_context.py`
- `backend/ai/context/renderers.py`

**Required changes**

- Establish one canonical context model and a clear set of operation-specific adapters.
- Keep context extraction deterministic and separate from prompt rendering.
- Define token budgets for system instructions, task instructions, conversation history, repository evidence, and output reserve.
- Use the selected model's tokenizer when available; otherwise use a documented conservative estimate.
- Never truncate source code in a way that removes the relevant line range or breaks a syntax boundary without marking it as partial.
- Deduplicate repeated files/symbols and avoid sending the same code in both conversation history and retrieved context.
- Rank context by task relevance, dependency importance, recency, and evidence quality—not only retrieval score.
- Preserve source metadata (repository, file, symbol, start/end line, chunk ID, content hash).
- Add deterministic overflow behavior: remove low-value context first, retain mandatory instructions and evidence metadata, and return a visible “context limited” state.
- Add token-budget tests for tiny budgets, large files, long histories, duplicated chunks, Unicode, and code-heavy content.

### P1.3 RAG pipeline and repository chat

**Files**
- `backend/ai/pipeline.py`
- `backend/ai/schemas/output.py`
- `backend/ai/schemas/grounding.py`
- `backend/ai/prompts/chat_system.txt`
- `backend/ai/prompts/repository_chat.txt`
- `backend/ai/prompts/context_summary.txt`
- `backend/ai/prompts/summary_system.txt`
- `backend/app/api/v1/chat.py`
- `backend/app/api/v1/repositories.py`

**Required changes**

- Make the RAG pipeline a thin sequence of explicit stages: authorize → retrieve → build context → prompt → generate → parse → validate → ground → format.
- Return a typed internal result with answer, source references, retrieval diagnostics, model/provider metadata, and failure/degraded status.
- Separate “no matching evidence,” “index unavailable,” “provider unavailable,” and “answer generation failed.”
- Require citations for repository-specific factual claims. If evidence is insufficient, answer with uncertainty instead of hallucinating.
- Add conversation memory only when it is relevant and authorized; do not let memory override repository evidence.
- Add context summarization with provenance and expiry/versioning; never treat a summary as equivalent to source code.
- Protect against prompt injection in retrieved code. Explicitly label repository content as untrusted data and prohibit it from changing system instructions or tool permissions.
- Add response caching only for safe, repository-versioned queries. Avoid caching user-specific/private responses across users.
- Stream responses only if partial output can be safely terminated and the final response still passes validation; otherwise return a complete validated response.
- Add tests for prompt injection, conflicting evidence, stale index, empty retrieval, and answer/source mismatch.

---

## 6. P1 — Capability services

### P1.1 Code review

**Files**
- `backend/ai/services/code_review_engine.py`
- `backend/app/services/code_review_orchestrator.py`
- `backend/ai/context/review_context.py`
- `backend/ai/prompts/code_review_system.txt`
- `backend/ai/schemas/validator.py`
- `backend/ai/schemas/grounding.py`

**Required changes**

- Define a canonical finding schema and stable finding identity (file + rule/category + normalized location + fingerprint).
- Deduplicate findings across static scanner and LLM output.
- Make static analysis findings authoritative for deterministic rules; use LLM for reasoning and prioritization, not to overwrite scanner facts.
- Require exact diff/file evidence and line ranges for findings.
- Add confidence and evidence strength separately from severity.
- Suppress speculative style opinions unless requested.
- Add changed-lines-only mode and full-repository mode as explicit configurations.
- Prevent the model from reporting a finding on code not in the analyzed revision.
- Track false-positive feedback and create a regression corpus from accepted/rejected findings.

### P1.2 Bug detection

**Files**
- `backend/ai/services/bug_detection_engine.py`
- `backend/app/services/bug_detection_orchestrator.py`
- `backend/ai/context/bug_context.py`
- `backend/ai/prompts/bug_detection_system.txt`

**Required changes**

- Separate static scanner evidence from LLM hypotheses.
- Require a reproducible failure path or clearly label the result as a hypothesis.
- Validate referenced symbols and line ranges against the exact repository revision.
- Add severity calibration and duplicate suppression.
- Avoid claims that a bug is confirmed solely because the model generated a plausible explanation.
- Add known-bug, no-bug, edge-case, and adversarial test sets.

### P1.3 Explanation

**Files**
- `backend/ai/services/explanation_service.py`
- `backend/app/services/explanation_orchestrator.py`
- `backend/ai/context/explanation.py`
- `backend/ai/prompts/explanation_system.txt`

**Required changes**

- Define explanation modes (file, symbol, flow, dependency, selected lines) explicitly.
- Ground each described function/class/flow in source symbols and file locations.
- Make depth and output length configurable with a bounded default.
- Avoid explaining stale code when repository revision changed during the request.
- Add tests for missing symbols, generated code, very large files, and cross-file call flows.

### P1.4 Test generation

**Files**
- `backend/ai/services/test_generation_service.py`
- `backend/app/services/test_generation_orchestrator.py`
- `backend/ai/context/test_context.py`
- `backend/ai/prompts/test_generation_system.txt`

**Required changes**

- Generate tests from behavior/contracts and existing test conventions, not only source text.
- Detect the project's test framework, package manager, fixture patterns, and import conventions.
- Validate generated tests syntactically before writing them.
- Run generated tests in the sandbox with resource and network limits.
- Distinguish test-generation success from test-execution success.
- Report failing tests and environment assumptions transparently.
- Reject generated tests that contain real secrets or destructive setup.
- Add tests for missing dependencies, async functions, fixtures, parameterized tests, and existing-test conflicts.

### P1.5 Task planning and issue-to-task adaptation

**Files**
- `backend/ai/services/task_planner.py`
- `backend/ai/services/issue_task_adapter.py`
- `backend/app/api/v1/issues.py`
- `backend/app/api/v1/tasks.py`
- `backend/ai/prompts/repair_system.txt`
- `backend/ai/prompts/summary_system.txt`

**Required changes**

- Use typed plan steps with IDs, dependencies, affected files, expected outcomes, and validation commands.
- Validate dependency graphs for cycles, missing prerequisites, and impossible ordering.
- Separate issue parsing from execution planning.
- Treat GitHub issue bodies/comments as untrusted user content.
- Require plans to cite repository evidence and identify unknowns.
- Add a human-readable preview and explicit approval gate before applying code changes.
- Ensure plan generation cannot directly invoke privileged tools.

---

## 7. P1 — Prompt management

**Files**
- `backend/ai/prompts/__init__.py`
- `backend/ai/prompts/README.md`
- `backend/ai/prompts/bug_detection_system.txt`
- `backend/ai/prompts/chat_system.txt`
- `backend/ai/prompts/code_review_system.txt`
- `backend/ai/prompts/context_summary.txt`
- `backend/ai/prompts/explanation_system.txt`
- `backend/ai/prompts/grounding_system.txt`
- `backend/ai/prompts/repair_system.txt`
- `backend/ai/prompts/repository_chat.txt`
- `backend/ai/prompts/source_grounding.txt`
- `backend/ai/prompts/summary_system.txt`
- `backend/ai/prompts/test_generation_system.txt`

**Required changes**

- Add prompt IDs, semantic versions, owner, capability, expected output schema, and last evaluation date.
- Keep prompts as templates; validate required variables and reject missing/extra variables consistently.
- Add prompt-injection boundaries to every prompt that consumes repository or issue content.
- Keep policy and tool permissions in code, not in prompt text.
- Add prompt unit tests for rendering, escaping/fencing, empty variables, long inputs, and adversarial source text.
- Build a prompt regression suite using representative repositories and expected structured outputs.
- Track prompt version in every AI operation record so regressions can be attributed.
- Avoid maintaining multiple prompts with subtly conflicting definitions of severity, confidence, citations, or completion.

---

## 8. P1 — AI quality evaluation and observability

**Files**
- `backend/ai/services/ai_quality_evaluator.py`
- `backend/ai/llm/client.py`
- `backend/ai/embeddings/service.py`
- `backend/ai/services/retrieval_optimizer.py`
- `backend/app/core/telemetry.py`
- `backend/app/core/lifespan.py`

**Required changes**

### Quality metrics

- Retrieval: Recall@K, MRR, nDCG, source coverage, duplicate rate.
- Grounding: citation precision, citation recall, unsupported-claim rate.
- Code review/bug detection: precision, recall, false-positive rate, severity calibration.
- Test generation: syntax pass rate, collection pass rate, execution pass rate, useful coverage delta.
- Agent: task completion rate, regression rate, repair success rate, human intervention rate.
- Product: latency p50/p95, cost per successful task, provider fallback rate, timeout rate.

### Telemetry requirements

- Record operation ID, repository/index revision, capability, prompt version, provider, model, latency, token usage, retries, fallback, retrieval counts, validation outcome, and error class.
- Do not log source code, full prompts, API keys, access tokens, or unredacted private repository content.
- Distinguish estimated cost from provider-billed cost.
- Add per-user, per-repository, and per-task budget enforcement.
- Add dashboards/alerts for provider error rate, quota exhaustion, rising latency, empty retrieval, grounding failures, and agent repair loops.
- Ensure telemetry failure never breaks the user-facing AI operation, but make telemetry loss observable.

---

## 9. P2 — Maintainability and performance

1. Split large modules only after behavior is protected by tests. Avoid a large-bang rewrite.
2. Remove duplicate prompt construction and provider-specific parsing from application orchestrators.
3. Replace broad `Any` and duck-typed session handling with explicit protocols/types where practical.
4. Standardize async database session ownership in retrievers.
5. Add bounded caches for embeddings, retrieval, and safe deterministic context operations. Cache keys must include model/profile and repository index revision.
6. Add batch ingestion and backpressure for indexing; do not let indexing starve interactive inference.
7. Add graceful degradation: reranker unavailable should not necessarily disable lexical/vector retrieval; provider outage should return typed degraded status.
8. Keep optional model dependencies (e.g., cross-encoder reranker) lazy-loaded and health-checked. Avoid blocking model downloads during API startup.
9. Pin provider SDK versions and test upgrades against adapter contract tests.
10. Add configuration validation for missing API keys, invalid dimensions, unsupported models, impossible token budgets, and conflicting provider settings.

---

## 10. File-by-file change matrix

The table below is the implementation checklist for every Python file under `backend/ai/`. “Keep” means retain the file and its responsibility; it does not mean no changes are needed.

| File | Action | Concrete work |
|---|---|---|
| `backend/ai/__init__.py` | Keep; expose only stable public interfaces and avoid eager imports that initialize optional dependencies. |
| `backend/ai/context/__init__.py` | Keep; avoid exporting unstable implementation details. |
| `backend/ai/context/bug_context.py` | Keep/refine; ensure bug evidence includes exact revision, symbol and line ranges. |
| `backend/ai/context/builder.py` | Refactor; canonical context contracts, provenance, repository revision and deterministic ordering. |
| `backend/ai/context/chat_context.py` | Keep/refine; isolate conversation history from repository evidence and prevent stale context. |
| `backend/ai/context/explanation.py` | Keep/refine; symbol/flow context and exact source mapping. |
| `backend/ai/context/intelligence_context.py` | Keep/refine; define shared context fields used by review/bug/explain/test capabilities. |
| `backend/ai/context/models.py` | Keep/refine; typed immutable context models with source provenance and validation. |
| `backend/ai/context/renderers.py` | Keep/refine; centralize rendering/escaping and keep source data separate from prompt text. |
| `backend/ai/context/review_context.py` | Keep/refine; changed-file/diff awareness, source provenance and deterministic prioritization. |
| `backend/ai/context/service.py` | Refactor; make it a facade/composition layer, not a second independent implementation of each context builder. |
| `backend/ai/context/test_context.py` | Keep/refine; test framework conventions, fixtures, dependency mocks and safe test context. |
| `backend/ai/context/token_budget.py` | P0/P1; explicit model-aware budgets, output reserve, overflow priorities and deterministic truncation. |
| `backend/ai/embeddings/__init__.py` | Keep; expose provider-independent embedding interfaces. |
| `backend/ai/embeddings/client.py` | Keep/refine; define typed embedding provider errors and profile metadata. |
| `backend/ai/embeddings/gemini_provider.py` | P0 refactor; normalize provider errors, model/dimension contract, quotas and lifecycle. |
| `backend/ai/embeddings/service.py` | P0 refactor; validate finite vectors/dimensions, configurable batch/concurrency, retry budgets and metrics. |
| `backend/ai/interfaces.py` | Keep; make capability protocols explicit and align signatures with concrete services. |
| `backend/ai/llm/__init__.py` | Keep; export stable provider contracts only. |
| `backend/ai/llm/client.py` | P0 refactor; centralize retry/fallback/deadline/concurrency/telemetry policy and fix error-specific fallback. |
| `backend/ai/llm/gemini_provider.py` | P0 refactor; normalize SDK errors, key rotation, structured output, usage, timeout and client lifecycle. |
| `backend/ai/llm/groq_provider.py` | P0 refactor; same adapter contract as Gemini; investigate silent `pass` branch and remove ambiguous no-op. |
| `backend/ai/llm/provider.py` | Keep; formalize provider protocol, capability declaration, and lifecycle contract. |
| `backend/ai/llm/schemas.py` | Keep; strengthen typed request/response/error contracts and normalized usage/finish metadata. |
| `backend/ai/pipeline.py` | Refactor; keep as canonical RAG orchestration only, split stages into small collaborators and add typed result/degraded states. |
| `backend/ai/prompts/__init__.py` | Inspect; retain if used, otherwise deprecate only after reference and test search. |
| `backend/ai/retrieval/__init__.py` | Keep; stable retrieval exports. |
| `backend/ai/retrieval/base.py` | Keep; define canonical CodeChunk/Retriever contracts and metadata invariants. |
| `backend/ai/retrieval/fusion.py` | P1; document/test RRF formula, stable tie-breaking and duplicate handling. |
| `backend/ai/retrieval/hybrid.py` | P1; define candidate pool, fusion order, deduplication, filters and graceful degradation. |
| `backend/ai/retrieval/lexical.py` | P1; improve code identifier tokenization, safe tsquery handling, repository filtering and SQL/session tests. |
| `backend/ai/retrieval/pipeline.py` | Review/merge; check overlap with top-level `ai/pipeline.py`; retain one canonical pipeline and deprecate duplicate entry points. |
| `backend/ai/retrieval/reranker.py` | P1; bound model loading/candidate count, add timeout/fallback and evaluate whether reranking improves quality. |
| `backend/ai/retrieval/vector.py` | P0/P1; enforce repository scope, embedding profile match, session ownership, query timeout and deterministic mapping. |
| `backend/ai/schemas/__init__.py` | Keep; stable exports. |
| `backend/ai/schemas/errors.py` | Keep; normalize parse/schema/grounding errors and retryability. |
| `backend/ai/schemas/grounding.py` | P0; verify citations against retrieved chunks and exact repository revision; add adversarial tests. |
| `backend/ai/schemas/output.py` | P0; canonical response/finding/test/plan schemas and strict field constraints. |
| `backend/ai/schemas/prompt_builder.py` | P1; centralize safe prompt assembly, fencing and input labels. |
| `backend/ai/schemas/validator.py` | P0/P1; separate parsing, schema, semantic, and evidence validation; avoid permissive fallbacks. |
| `backend/ai/services/__init__.py` | Keep/refine; prevent import-time side effects and expose stable service classes. |
| `backend/ai/services/agent_execution_loop.py` | P0; strict tool policy, hard budgets, cancellation, audit events, approval and stop conditions. |
| `backend/ai/services/ai_quality_evaluator.py` | P1; implement reproducible evaluation datasets, metric definitions and regression reports. |
| `backend/ai/services/bounded_repair_loop.py` | P0; max iterations/time/cost, no-progress detection, diff validation, sandbox isolation and regression stop. |
| `backend/ai/services/bug_detection_engine.py` | P1; separate scanner facts from model hypotheses and require reproducible/evidence-backed reports. |
| `backend/ai/services/code_review_engine.py` | P1; canonical findings, evidence checks, static/LLM deduplication and confidence calibration. |
| `backend/ai/services/explanation_service.py` | P1; typed explanation modes, symbol grounding and revision consistency. |
| `backend/ai/services/issue_task_adapter.py` | P1; treat issue content as untrusted, normalize requirements and preserve issue provenance. |
| `backend/ai/services/requirement_verifier.py` | P0/P1; require evidence from diff/tests and verify acceptance criteria deterministically where possible. |
| `backend/ai/services/retrieval_optimizer.py` | P1; only optimize against evaluation data; make query rewriting and tuning observable/configurable. |
| `backend/ai/services/task_planner.py` | P1; typed dependency graph, evidence-backed plans, cycle detection and approval boundary. |
| `backend/ai/services/test_generation_service.py` | P1; framework-aware test output, syntax validation, sandbox execution and safe fixtures. |


### Prompt-file change matrix

| File | Concrete work |
|---|---|
| `backend/ai/prompts/bug_detection_system.txt` | Require exact evidence, confidence separate from severity, and explicit hypothesis labeling. |
| `backend/ai/prompts/chat_system.txt` | State repository evidence boundaries, uncertainty behavior, and prompt-injection handling. |
| `backend/ai/prompts/code_review_system.txt` | Define finding schema, changed-code scope, duplicate suppression, and evidence requirements. |
| `backend/ai/prompts/context_summary.txt` | Preserve file/symbol/line provenance; mark omissions and stale summaries. |
| `backend/ai/prompts/explanation_system.txt` | Require source-grounded descriptions and distinguish inference from observed behavior. |
| `backend/ai/prompts/grounding_system.txt` | Make citation rules explicit; never fabricate paths, symbols, or line numbers. |
| `backend/ai/prompts/repair_system.txt` | Require minimal diffs, no security-policy bypass, tests, and stop conditions. |
| `backend/ai/prompts/repository_chat.txt` | Treat repository content as untrusted data; answer only from authorized evidence. |
| `backend/ai/prompts/source_grounding.txt` | Align with canonical source-reference schema and exact chunk/revision identity. |
| `backend/ai/prompts/summary_system.txt` | Require concise summaries with provenance and uncertainty. |
| `backend/ai/prompts/test_generation_system.txt` | Keep safe test requirements; add framework conventions, no destructive actions, and executable completeness. |
| `backend/ai/prompts/README.md` | Document prompt ownership, versioning, variables, schema, tests, and release procedure. |
| `backend/ai/prompts/__init__.py` | Keep loader; add prompt version metadata and stronger template validation. |

---

## 11. Application integration files to coordinate

These are not all part of `backend/ai/`, but they determine whether the AI layer is used consistently. Avoid refactoring them independently of the AI contracts.

| File | Required coordination |
|---|---|
| `backend/app/core/lifespan.py` | Construct one configured gateway/embedding/retrieval stack; validate readiness and close resources reliably. |
| `backend/app/api/v1/chat.py` | Keep HTTP validation/auth here; delegate AI logic to canonical chat/RAG service. |
| `backend/app/api/v1/repositories.py` | Enforce repository ownership before retrieval; keep API response formatting out of retrievers. |
| `backend/app/api/v1/analysis/common.py` | Share canonical LLM request/response schemas and validation helpers. |
| `backend/app/api/v1/analysis/*` | Keep endpoints thin; no direct provider SDK calls or duplicate prompt logic. |
| `backend/app/services/code_review_orchestrator.py` | Own persistence/task lifecycle; delegate model reasoning to `CodeReviewEngine`. |
| `backend/app/services/bug_detection_orchestrator.py` | Own scan lifecycle; distinguish scanner evidence from LLM hypotheses. |
| `backend/app/services/explanation_orchestrator.py` | Own request/task lifecycle; delegate explanation generation. |
| `backend/app/services/test_generation_orchestrator.py` | Own persistence and sandbox execution; delegate generation. |
| `backend/app/services/task_execution_orchestrator.py` | Coordinate plan → approval → tools → validation; enforce hard budgets. |
| `backend/app/services/sync_worker.py` | Use the canonical embedding profile and idempotent indexing generation. |
| `backend/app/core/telemetry.py` | Align provider token/cost metrics with gateway metadata; mark estimated costs as estimates. |

**Important:** The AI services and application orchestrators have overlapping responsibilities. Before deleting or merging anything, build a call graph and confirm which classes are instantiated in `lifespan.py`, dependency injection, workers, and tests. Preserve public imports temporarily with compatibility re-exports if necessary.

---

## 12. AI-related test plan

Create/maintain focused test groups. Do not rely only on mocked “happy path” tests.

### Provider contract tests
- Gemini and Groq return the same normalized `LLMResponse` contract.
- Error mapping and retryability.
- Fallback model mapping and structured-output compatibility.
- API-key rotation under concurrent calls.
- Timeout, cancellation, and close behavior.

### Embedding tests
- Dimension/profile validation.
- NaN/Infinity rejection.
- Batch ordering and partial failures.
- Quota and retry handling.
- Re-index idempotency and model migration.

### Retrieval tests
- Tenant/repository isolation.
- Lexical identifier search and query sanitization.
- Vector/lexical fusion and deduplication.
- Reranker degradation.
- Empty/stale index and DB/provider outages.

### Grounding tests
- Valid and invalid chunk references.
- Fabricated file paths/line ranges.
- Cross-repository citation attempt.
- Prompt injection inside source files.
- Contradictory or insufficient evidence.

### Capability tests
- Code review false positives and duplicate findings.
- Bug detection hypothesis vs confirmed issue.
- Explanation symbol/line correctness.
- Test generation syntax and sandbox execution.
- Task plan cycle detection and dependency ordering.

### Agent safety tests
- Path traversal and symlink escape attempts.
- Disallowed shell/tool invocation.
- Excessive tool calls, tokens, runtime, patch size, and repair iterations.
- Repeated no-progress repair.
- Cancellation mid-run.
- Secrets in generated diffs/tests.
- Unauthorized repository/workspace access.
- Regression test failure blocks completion/PR.

### Evaluation suite
Build a small but representative fixed benchmark first:
- 20–50 repository Q&A questions with source references.
- 20–50 code review cases with accepted/rejected findings.
- 20–50 bug cases including no-bug examples.
- 20–50 test-generation targets with expected framework and execution outcome.
- 10–20 agent tasks with acceptance criteria and expected safe stop behavior.

Record dataset version, repository commit, prompt version, provider/model, retrieval configuration, and evaluator version for every run.

---

## 13. Implementation order and dependencies

### Week 1 — Reliability and contracts

1. Map all gateway and provider call sites; remove any direct vendor SDK use outside adapters.
2. Finalize LLM request/response/error contracts.
3. Fix fallback policy, retry budget, deadlines, cancellation, and lifecycle.
4. Finalize embedding profile/version contract and vector validation.
5. Add repository authorization tests to vector and lexical retrieval.
6. Harden grounding and output schema validation.
7. Add prompt version metadata and prompt-injection test cases.

**Exit criteria:** Provider contract tests pass; invalid credentials do not silently hide; embedding mismatch is rejected; citations cannot point outside retrieved authorized evidence.

### Week 2 — Retrieval and capability quality

1. Establish retrieval benchmark and baseline metrics.
2. Tune lexical/vector candidate pools and fusion on the benchmark.
3. Add deduplication and deterministic reranking degradation.
4. Consolidate context model and token budgeting.
5. Align code review, bug detection, explanation, and test generation with canonical output schemas.
6. Add static-vs-LLM finding deduplication and confidence/evidence fields.
7. Make task planning typed and dependency-aware.

**Exit criteria:** Retrieval and grounding metrics are recorded; no cross-repository leakage; capabilities produce schema-valid, evidence-backed outputs on regression cases.

### Week 3 — Agent safety, evaluation, production readiness

1. Add hard limits to agent and repair loops.
2. Enforce approval and diff-validation gates.
3. Add sandbox adversarial tests and cancellation.
4. Add telemetry dashboards and per-task cost/token budgets.
5. Add benchmark execution to CI for prompt/model/retrieval changes.
6. Split oversized modules incrementally, preserving compatibility.
7. Run end-to-end tests with real test repositories and controlled provider credentials.

**Exit criteria:** Agent cannot exceed configured budgets or workspace boundaries; unverified work cannot be marked complete; model/prompt changes have regression evidence.

---

## 14. Refactor rules — what to remove, merge, and preserve

### Remove only after reference checks

- Duplicate RAG pipeline entry points if `backend/ai/retrieval/pipeline.py` and `backend/ai/pipeline.py` implement overlapping flows. Keep one canonical implementation and a temporary compatibility wrapper if imports require it.
- Duplicate prompt assembly/response parsing in `backend/app/services/*_orchestrator.py` when the same logic is already in `backend/ai/services/*`.
- Dead provider-specific branches and unused model aliases after a call-site search and contract tests.
- Unused context adapters only after proving no API, worker, or test imports them.

### Merge

- Provider retry/fallback/error normalization into `LLMGateway`.
- Embedding validation, batching, concurrency, and metrics into `EmbeddingService`.
- Context token allocation into a single `TokenBudget` contract.
- Citation checks into one reusable grounding validator.
- Capability output validation into shared schema + semantic validators.
- Agent budgets and stop conditions into a shared execution policy object.

### Preserve

- The provider abstraction; do not hardwire Gemini/Groq in capability services.
- Separate embedding provider abstraction; embeddings are not interchangeable with chat completions.
- Hybrid retrieval; do not remove lexical retrieval just because vector search exists.
- Prompt templates as versioned assets.
- Specialized context builders where they encode real domain differences.
- Sandbox and deterministic scanner checks; LLM output must not replace these safety layers.
- Existing tests and intentionally adversarial fixtures.

---

## 15. Production acceptance checklist

- [ ] All model calls route through the LLM gateway.
- [ ] Provider SDKs are isolated to adapter modules.
- [ ] Fallback is explicit, observable, and schema-compatible.
- [ ] Retry, timeout, concurrency, and cost budgets are centrally enforced.
- [ ] Embedding profile and dimensions match every indexed repository generation.
- [ ] Retrieval always enforces repository authorization.
- [ ] Hybrid retrieval deduplicates and has stable ordering.
- [ ] Every repository-specific answer/finding has verifiable evidence or an explicit uncertainty state.
- [ ] Prompt injection in repository/issue content cannot alter system policy or tool permissions.
- [ ] Generated tests are syntax-checked and sandbox-executed.
- [ ] Agent changes are bounded, diff-validated, tested, and auditable.
- [ ] No task is completed solely on model self-report.
- [ ] Prompt/model/retrieval changes run the regression benchmark.
- [ ] Telemetry avoids source-code and secret leakage.
- [ ] Provider and embedding clients close cleanly during shutdown.
- [ ] P95 latency, provider failure rate, grounding failure rate, and cost per successful task are monitored.

---

## 16. Audit limitations

This plan is based on static inspection of the supplied repository snapshot. It does not claim that:
- Gemini/Groq credentials or quotas work in the deployed environment.
- Supabase/pgvector indexes and PostgreSQL FTS indexes are correctly provisioned.
- All AI tests pass.
- Retrieval quality is good on real repositories.
- The agent is safe under adversarial execution.
- The deployed provider models match the source defaults.

Before production sign-off, run the existing AI-related pytest suite, database-backed retrieval integration tests, provider contract tests with controlled credentials, sandbox security tests, and a benchmark on representative repositories. Capture the exact commit and configuration used.

**Recommended sequence:** P0 gateway/provider/embedding/grounding/agent safety → P1 retrieval/context/capabilities → P2 evaluation/telemetry/refactoring. Do not refactor the frontend, backend API contracts, and AI service interfaces in parallel without agreeing on shared request/response schemas first.
