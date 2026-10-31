## 1. AI audit scope and production objective

The AI phase covers the intelligence layer of the platform:

- LLM provider integration and model selection.
- Central LLM gateway and fallback.
- Embedding generation.
- Repository-aware RAG chat.
- Vector and lexical retrieval.
- Hybrid search and reranking.
- Context construction and token budgeting.
- Prompt templates and prompt construction.
- Grounding and hallucination control.
- Explain, Bug Detection, Test Generation and Code Review engines.
- AI output validation, errors, retries and observability.

The target is not simply to connect an LLM and get a response. The target is reliable, repository-grounded intelligence that does not invent source files, line numbers, bugs or test results.

I inspected the AI-related source tree in the uploaded ZIP. It contains approximately 9,049 Python lines across `backend/ai`, `backend/agent` and `backend/review`. Two important findings should guide the work:

1. There are two separate classes named `RAGPipeline`: one in `backend/ai/pipeline.py` and another in `backend/ai/retrieval/pipeline.py`. Their responsibilities overlap and must be clarified before further feature development.
2. `backend/ai/context/builder.py` is approximately 967 lines, while the main RAG pipeline is approximately 672 lines. These are major candidates for responsibility-based refactoring.

We should preserve working AI functionality and tests while consolidating the architecture.

## 2. AI production scope — what must work by Week 2

| AI feature           | Required production behaviour                                             |
| -------------------- | ------------------------------------------------------------------------- |
| LLM gateway          | One controlled entry point for all model inference                        |
| Provider integration | Correct authentication, timeouts, rate-limit handling and retries         |
| Model configuration  | One source of truth for provider and model selection                      |
| Fallback             | Safe fallback without invalid model names or incompatible requests        |
| Embeddings           | Consistent model, dimensions and normalization                            |
| Repository RAG       | Retrieve only relevant content from the authorized repository             |
| Hybrid retrieval     | Combine lexical and vector retrieval correctly                            |
| Reranking            | Improve candidate relevance without excessive latency                     |
| Context building     | Fit useful code and history within a bounded token budget                 |
| Prompt construction  | Separate system instructions from untrusted repository content            |
| Grounding            | Verify source references against authoritative repository data            |
| Explain              | Generate accurate code explanations with source references                |
| Bug detection        | Return actionable findings with evidence and severity                     |
| Test generation      | Generate framework-appropriate tests without claiming they were executed  |
| Code review          | Produce actionable, evidence-backed findings                              |
| Structured output    | Validate model output and recover safely from invalid responses           |
| AI failure handling  | Distinguish empty retrieval, provider failure, invalid output and timeout |
| Cost control         | Bound tokens, retries, retrieval size and expensive operations            |
| Evaluation           | Measure retrieval relevance, grounding, correctness and latency           |

Production requirement: Every AI feature must have a reliable fallback or a clear unavailable state. It must never silently replace missing evidence with invented answers.

## 3. P0 — Critical AI production issues

### A. Consolidate the two RAG pipelines

Critical architecture issue

Files:

- `backend/ai/pipeline.py`
- `backend/ai/retrieval/pipeline.py`
- `backend/ai/retrieval/__init__.py`
- `backend/ai/__init__.py`
- `backend/app/api/v1/chat.py`

There are two classes named `RAGPipeline`.

`ai.pipeline.RAGPipeline` handles:

- Retrieval.
- Context building.
- Prompt construction.
- LLM generation.
- JSON repair.
- Grounding validation.
- Final repository answer.

`ai.retrieval.pipeline.RAGPipeline` handles a retrieval-oriented workflow involving vector search, lexical search, fusion and reranking, but also has chat-answer orchestration responsibilities.

This creates two competing places for RAG behaviour.

Change this:

1. Make `backend/ai/pipeline.py` the canonical end-to-end RAG orchestration layer.
2. Keep `backend/ai/retrieval/` responsible only for retrieving and ranking relevant code chunks.
3. Move vector + lexical + fusion + reranking coordination into one clearly named retrieval component, such as `HybridRetriever`.
4. Remove chat answer generation and LLM orchestration from `retrieval/pipeline.py`.
5. Keep one canonical `RAGPipeline.chat()` entry point.
6. Update imports and dependency injection to use the canonical implementation.
7. Preserve the public chat API response contract.
8. Update tests that import the old retrieval pipeline.
9. Remove the old duplicate class only after all imports and tests have been migrated.

Final architecture:

```
Chat API
   |
   v
RAGPipeline
   |
   +--> HybridRetriever
   |       |
   |       +--> VectorRetriever
   |       +--> LexicalRetriever
   |       +--> Fusion
   |       +--> Reranker
   |
   +--> ContextBuilder
   |
   +--> PromptBuilder
   |
   +--> LLMGateway
   |
   +--> OutputValidator
   |
   +--> GroundingValidator
   |
   v
RepositoryAnswer
```

Do not allow the API, retrieval module and feature orchestrators to each implement their own RAG chat pipeline.

### B. Establish one central LLM gateway

Critical

Files:

- `backend/ai/llm/client.py`
- `backend/ai/llm/provider.py`
- `backend/ai/llm/gemini_provider.py`
- `backend/ai/llm/groq_provider.py`
- `backend/ai/llm/schemas.py`
- `backend/ai/interfaces.py`

The project already has a central `LLMGateway`. Preserve it as the only entry point for model inference.

Change this:

- Every AI feature must call the gateway rather than calling Gemini or Groq directly.
- Do not create provider clients inside individual feature engines.
- Do not duplicate API key rotation in each engine.
- Do not implement separate retry loops in the feature services.
- Keep provider-specific request formatting inside provider adapters.
- Keep common request/response types inside `llm/schemas.py`.
- Keep token usage and latency telemetry in the gateway.
- Ensure provider failures are translated into consistent typed errors.
- Ensure provider clients are closed correctly at application shutdown.
- Do not log prompts or full source code as routine telemetry.

Important fallback issue:

`LLMGateway.generate()` currently has logic for switching provider-specific model names when falling back between Gemini and Groq.

Make this explicit and reliable:

- Each provider must have a supported default model.
- Provider-specific model identifiers must not be passed to an incompatible provider.
- A fallback must preserve the response format requirements.
- If structured output is not supported by the fallback provider, use an explicit safe parsing/validation path.
- Authentication errors should not automatically trigger endless retries.
- Rate-limit and transient errors should have bounded retry behaviour.
- Record which provider and model actually generated the response.

Final rule: Feature engines should not know how provider key rotation or fallback works.

### C. Make provider configuration centralized

Files:

- `backend/app/core/config.py`
- `backend/ai/llm/client.py`
- `backend/ai/llm/groq_provider.py`
- `backend/ai/llm/gemini_provider.py`
- `backend/ai/embeddings/client.py`
- `backend/ai/embeddings/gemini_provider.py`

There are model defaults inside individual engines:

- `explanation_service.py`
- `bug_detection_engine.py`
- `test_generation_service.py`
- `code_review_engine.py`

The same default model is repeated in several files.

Change this:

Create one central AI settings configuration with explicit values for:

- Chat provider.
- Chat model.
- Fallback provider.
- Fallback model.
- Embedding provider.
- Embedding model.
- Request timeout.
- Maximum output tokens.
- Temperature defaults.
- Retry count.
- Maximum concurrent model calls.
- Maximum context budget.

Feature-specific settings can override common settings where there is a clear reason.

For example:

```
AI Settings
    |
    +-- Chat model configuration
    +-- Embedding model configuration
    +-- Explain configuration
    +-- Bug detection configuration
    +-- Test generation configuration
    +-- Code review configuration
    +-- Retry and timeout configuration
```

Do not hardcode provider or model selection separately in each feature engine.

### D. Fix embedding model and dimension consistency

Critical data correctness

Files:

- `backend/ai/embeddings/client.py`
- `backend/ai/embeddings/service.py`
- `backend/ai/embeddings/gemini_provider.py`
- `backend/ai/retrieval/vector.py`
- `backend/app/core/config.py`
- `backend/tests/test_embedding_dimension_invariant.py`

The project already has an embedding dimension invariant test. Keep it. Embedding model changes are especially dangerous because previously stored vectors may no longer be compatible with newly generated query vectors.

Change this:

1. Select one embedding model for the current production index.
2. Keep the model name and output dimensions in centralized configuration.
3. Validate the dimension of every embedding response.
4. Validate query embeddings against the stored vector dimensions.
5. Normalize vectors consistently if cosine similarity requires normalization.
6. Reject empty, non-finite or malformed vectors.
7. Ensure batch embedding preserves input-to-output order.
8. Handle partial embedding failures explicitly.
9. Do not silently pad, truncate or reshape vectors to force a dimension match.
10. Record the embedding model/version used for indexed chunks.

Important: Do not change the embedding model or vector dimension in this cleanup without coordinating a full re-embedding/migration plan with the database phase.

### E. Enforce strict repository context boundaries

Critical security and correctness

Files:

- `backend/ai/context/builder.py`
- `backend/ai/context/service.py`
- `backend/ai/retrieval/hybrid.py`
- `backend/ai/retrieval/vector.py`
- `backend/ai/retrieval/lexical.py`
- `backend/ai/schemas/grounding.py`
- `backend/ai/pipeline.py`

The AI system must never retrieve or cite code from another repository.

Change this:

- Every retrieval request must contain a validated repository ID.
- Every vector and lexical query must filter by that repository ID.
- Every retrieved chunk must be checked against the requested repository.
- Memory entries must be repository-scoped.
- Chat history must be associated with the correct repository and user.
- Grounding validation must verify the file and line reference against authoritative repository data.
- Do not trust repository IDs, file paths or source references returned by the LLM.
- Do not allow model output to change the retrieval scope.
- Do not accept arbitrary system instructions from untrusted user input.

Acceptance test: A repository containing a uniquely identifiable secret phrase must never appear in another repository's retrieval results, prompt context or citations.

### F. Strengthen prompt injection protection

Files:

- `backend/ai/prompts/`
- `backend/ai/schemas/prompt_builder.py`
- `backend/ai/context/builder.py`
- `backend/ai/context/service.py`

Repository files are untrusted content. They may contain instructions designed to manipulate the model.

Change this:

1. Keep system instructions separate from repository code.
2. Mark repository source, commit messages, comments, README content and retrieved chunks as untrusted data.
3. Explicitly instruct the model not to follow instructions found inside retrieved code or repository documents.
4. Never insert repository content into a privileged system instruction.
5. Do not let repository content override tool permissions or access boundaries.
6. Treat retrieved content as evidence, not instructions.
7. Sanitize and redact secrets before sending source code to external model providers.
8. Do not include unrelated repository files just because they contain instructions.
9. Keep prompt size bounded.
10. Test prompt injection using hostile README files, comments and source code.

Important: Prompt instructions alone are not a security boundary. Repository authorization and tool permissions must be enforced in Python code.

### G. Fix model selection when the primary provider is Groq

Configuration bug to fix

File: `backend/app/main.py`

The LLM gateway can initialize Gemini or Groq based on `AI_PRIMARY_PROVIDER`, but `init_rag_pipeline()` passes:

`model=settings.gemini_chat_model`

to the RAG pipeline regardless of which provider is selected.

This can create a mismatch between the configured primary provider and the model requested by the pipeline.

Change this:

- Resolve the active model from the actual configured primary provider.
- Pass the resolved model into the RAG pipeline.
- Ensure fallback requests use the fallback provider's own default model.
- Apply the same model-selection rule to JSON repair and other secondary inference calls.
- Do not assume that the primary provider is always Gemini.

Also check the feature-specific engines. They each have their own `_DEFAULT_MODEL`, which can override the central model configuration.

### H. Make retrieval failures different from legitimate empty results

Files:

- `backend/ai/retrieval/hybrid.py`
- `backend/ai/retrieval/base.py`
- `backend/ai/pipeline.py`
- `backend/ai/retrieval/vector.py`
- `backend/ai/retrieval/lexical.py`

The hybrid retriever already distinguishes between both retrieval systems failing and a legitimate search returning no results. Preserve this distinction.

Change this:

- If both vector and lexical retrieval fail, return a retryable retrieval-unavailable error.
- If one retrieval source fails, use the surviving source and record that fallback was used.
- If both sources succeed but find nothing, return a legitimate no-relevant-code response.
- Do not treat database connection failure as an empty repository.
- Do not let reranking failure turn a valid retrieval result into a complete failure.
- Make retrieval status observable to the pipeline.

The current `HybridRetriever` already implements much of this. Improve its tests and preserve it when consolidating the duplicate RAG pipeline.

### I. Control reranker loading and resource usage

File: `backend/ai/retrieval/reranker.py`

The cross-encoder is loaded lazily, which is good for startup. However, the model is downloaded/loaded at first use and inference runs in a worker thread.

Change this:

- Make the reranker model configurable.
- Preload it during a controlled AI initialization step if the production environment can support it.
- Otherwise expose a clear warm-up/degraded state.
- Keep lazy loading available for local development.
- Add a maximum number of concurrent reranking jobs.
- Bound the candidate count and content size passed to the cross-encoder.
- Keep lexical/vector results available when reranking fails.
- Record reranking latency and fallback status.
- Do not report cross-encoder scores as calibrated probabilities.

Important for Azure: Measure actual memory, cold-start time and latency before deciding to keep the model loaded in the web API process. Do not assume the documented model size guarantees production performance.

### J. Make structured output validation consistent

Files:

- `backend/ai/schemas/validator.py`
- `backend/ai/schemas/output.py`
- `backend/ai/schemas/errors.py`
- `backend/ai/pipeline.py`
- `backend/ai/llm/schemas.py`

The project has both an `OutputValidator` and JSON repair logic inside the main `RAGPipeline`.

This can create two separate implementations of output validation and repair.

Change this:

1. Use `OutputValidator` as the shared JSON/Pydantic validation component.
2. Keep feature-specific Pydantic schemas in the relevant output schema modules.
3. Remove duplicated JSON cleaning and parsing logic from the RAG pipeline.
4. Keep a bounded repair attempt count.
5. Never pass unbounded raw model output or an excessively detailed validation error back into the repair prompt.
6. Limit repair prompt size and output tokens.
7. Validate the repaired output again before returning it.
8. If repair fails, return a typed AI validation error.
9. Do not convert invalid output into an apparently successful empty result.
10. Keep raw invalid model responses out of normal logs.

The same validation approach should be used by Explain, Bug, Test and Review engines.

### K. Strengthen source grounding

File: `backend/ai/schemas/grounding.py`

Keep the grounding validator as a separate component. It is one of the most important protections against fabricated repository references.

Change:

- Validate repository ID, file path, line range and source existence.
- Validate that line numbers are within the actual file bounds.
- Reject citations to files outside the repository.
- Do not trust a model-provided source path merely because it looks valid.
- Keep grounded and ungrounded claims distinguishable.
- Remove invalid citations instead of silently marking them as valid.
- Preserve the original answer when possible, but make the lack of verified evidence clear.
- Ensure a missing database session does not silently make production citations appear verified.
- Make strict grounding mandatory in production mode.

Important issue to address: `RAGPipeline` can construct a default `GroundingValidator` without a database session. That can be useful for isolated unit tests, but production must not treat this configuration as authoritative citation verification.

## 4. P1 — AI architecture refactoring and exact file decisions

### A. Context construction

Current files:

- `backend/ai/context/builder.py` — approximately 967 lines.
- `backend/ai/context/service.py` — approximately 540 lines.
- `backend/ai/context/explanation.py`
- `backend/ai/context/bug_context.py`
- `backend/ai/context/test_context.py`
- `backend/ai/context/review_context.py`

Problem:

`builder.py` currently handles chat context, intelligence context, dataclasses, token counting, serialization, formatting, truncation and rendering.

The feature-specific context builders also have their own responsibilities.

Change this:

Split the context-building responsibilities into smaller modules:

```
backend/ai/context/
├── __init__.py
├── models.py
├── token_budget.py
├── chat_context.py
├── intelligence_context.py
├── renderers.py
├── service.py
├── explanation.py
├── bug_context.py
├── test_context.py
└── review_context.py
```

Responsibilities:

| New file                  | Responsibility                                                     |
| ------------------------- | ------------------------------------------------------------------ |
| `models.py`               | Shared context dataclasses and context status types                |
| `token_budget.py`         | Token counting, token estimation and budget allocation             |
| `chat_context.py`         | Chat history, repository chunks and memory context assembly        |
| `intelligence_context.py` | Target snippet, symbols, related files and feature context         |
| `renderers.py`            | Render structured contexts into clearly separated prompt data      |
| `service.py`              | Context retrieval, caching, revision checks and cache invalidation |
| `explanation.py`          | Explanation-specific context assembly                              |
| `bug_context.py`          | Bug-detection context assembly                                     |
| `test_context.py`         | Test-generation context assembly                                   |
| `review_context.py`       | Code-review context assembly                                       |

Keep `ContextBuilder` temporarily as a compatibility facade if existing callers depend on it. Migrate callers gradually and remove the facade only when the migration is complete.

Do not move all context code into one new giant `context_service.py`.

### B. Context service

File: `backend/ai/context/service.py`

The service handles context retrieval, caching, provider policy, source revision checks and token budget auditing.

Change:

- Keep repository revision checks.
- Keep cache invalidation by repository revision.
- Keep context budget auditing.
- Keep the existing repository-scoped cache keys.
- Centralize provider policy instead of repeating it in every feature engine.
- Make cache TTL and size configurable.
- Avoid returning cached context from an older source revision.
- Track cache hits, misses and invalidations.
- Avoid caching sensitive source data longer than necessary.
- Add tests for concurrent cache updates and stale revisions.

Do not remove revision consistency checks. A context generated from an older commit can produce incorrect explanations, bug findings and reviews.

### C. LLM gateway and providers

| Existing file               | Decision       | What to change                                                                                    |
| --------------------------- | -------------- | ------------------------------------------------------------------------------------------------- |
| `ai/llm/client.py`          | Keep + improve | One gateway for inference, fallback, telemetry and lifecycle.                                     |
| `ai/llm/provider.py`        | Keep           | Keep the provider interface and common lifecycle contract.                                        |
| `ai/llm/gemini_provider.py` | Keep + improve | Improve timeout, retry, rate-limit, response parsing and key-rotation tests.                      |
| `ai/llm/groq_provider.py`   | Keep + improve | Improve retry policy, response validation, key rotation and provider-specific request mapping.    |
| `ai/llm/schemas.py`         | Keep + clean   | Maintain typed requests, responses and errors.                                                    |
| `ai/interfaces.py`          | Keep + review  | Keep shared service protocols; remove only duplicate protocol definitions after checking imports. |

Do not create `GeminiService`, `GroqService` or a separate LLM gateway inside each AI feature.

### D. Embedding implementation

| Existing file                      | Decision       | What to change                                                |
| ---------------------------------- | -------------- | ------------------------------------------------------------- |
| `ai/embeddings/client.py`          | Keep           | Keep provider abstraction and typed embedding errors.         |
| `ai/embeddings/gemini_provider.py` | Keep + improve | Improve batching, retry, timeout and response validation.     |
| `ai/embeddings/service.py`         | Keep + improve | Keep dimension checks, batch handling and concurrency limits. |
| `ai/embeddings/__init__.py`        | Keep           | Keep exports minimal.                                         |

Do not create a second embedding service inside the indexer. Both repository indexing and query retrieval should use the same embedding configuration and service contract.

### E. Retrieval components

| Existing file              | Decision                          | What to change                                                                                                                 |
| -------------------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `ai/retrieval/base.py`     | Keep                              | Keep shared chunk and retriever interfaces.                                                                                    |
| `ai/retrieval/vector.py`   | Keep + optimize                   | Keep repository-scoped vector search and dimension validation.                                                                 |
| `ai/retrieval/lexical.py`  | Keep + improve                    | Keep lexical search, query sanitization and repository filtering.                                                              |
| `ai/retrieval/fusion.py`   | Keep                              | Keep Reciprocal Rank Fusion as the common fusion algorithm.                                                                    |
| `ai/retrieval/hybrid.py`   | Keep                              | Make this the single hybrid retrieval implementation.                                                                          |
| `ai/retrieval/reranker.py` | Keep + improve                    | Add resource limits, warm-up and degraded status.                                                                              |
| `ai/retrieval/pipeline.py` | Major refactor / retire duplicate | Remove duplicate chat orchestration. Keep only if its useful retrieval behaviour has not been migrated into `HybridRetriever`. |
| `ai/retrieval/__init__.py` | Modify                            | Export the canonical retriever components, not a second `RAGPipeline`.                                                         |

### F. Prompts

| Existing file                           | Decision                    | What to change                                                                                                 |
| --------------------------------------- | --------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `ai/prompts/chat_system.txt`            | Keep                        | Keep chat-specific system instructions.                                                                        |
| `ai/prompts/repository_chat.txt`        | Review + merge if duplicate | Compare with `chat_system.txt`; keep one canonical chat prompt unless they serve genuinely different contexts. |
| `ai/prompts/explanation_system.txt`     | Keep                        | Explanation-specific instructions.                                                                             |
| `ai/prompts/bug_detection_system.txt`   | Keep                        | Bug-detection-specific instructions.                                                                           |
| `ai/prompts/test_generation_system.txt` | Keep                        | Test-generation-specific instructions.                                                                         |
| `ai/prompts/code_review_system.txt`     | Keep                        | Review-specific instructions.                                                                                  |
| `ai/prompts/grounding_system.txt`       | Keep                        | Grounding-specific instructions.                                                                               |
| `ai/prompts/source_grounding.txt`       | Review                      | Consolidate with grounding prompt only if the same task and contract are duplicated.                           |
| `ai/prompts/context_summary.txt`        | Keep if used                | Check consumers before deleting.                                                                               |
| `ai/prompts/summary_system.txt`         | Review                      | Check whether it duplicates context summary behaviour.                                                         |
| `ai/prompts/repair_system.txt`          | Keep + standardize          | Use from the shared output repair flow.                                                                        |
| `ai/prompts/__init__.py`                | Keep + simplify             | Centralize prompt loading and caching.                                                                         |
| `ai/prompts/README.md`                  | Keep                        | Maintain prompt ownership and change notes.                                                                    |

Do not merge prompts merely because their text looks similar. Explain, Bug, Test and Review need distinct instructions and output expectations.

### G. Output schemas and validation

| Existing file                  | Decision           | What to change                                                  |
| ------------------------------ | ------------------ | --------------------------------------------------------------- |
| `ai/schemas/output.py`         | Keep + review      | Keep public chat answer and source reference models.            |
| `ai/schemas/errors.py`         | Keep               | Keep typed AI errors.                                           |
| `ai/schemas/validator.py`      | Keep + consolidate | Make it the shared output validation and repair component.      |
| `ai/schemas/grounding.py`      | Keep + strengthen  | Strict source verification and repository boundary enforcement. |
| `ai/schemas/prompt_builder.py` | Keep + simplify    | Keep message construction and system/data separation.           |
| `ai/schemas/__init__.py`       | Keep               | Keep exports minimal.                                           |

### H. Feature engines

| Existing file                            | Decision        | What to change                                                                                                     |
| ---------------------------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------ |
| `ai/services/explanation_service.py`     | Keep + refactor | Keep explanation-specific LLM request and response handling. Remove duplicated provider policy and model defaults. |
| `ai/services/bug_detection_engine.py`    | Keep + refactor | Keep bug-specific reasoning and structured findings. Remove duplicated gateway policy and model defaults.          |
| `ai/services/test_generation_service.py` | Keep + refactor | Keep framework-aware test generation. Remove duplicated provider policy and model defaults.                        |
| `ai/services/code_review_engine.py`      | Keep + refactor | Keep review-specific reasoning and findings. Remove duplicated provider policy and model defaults.                 |
| `ai/services/__init__.py`                | Keep            | Keep exports minimal.                                                                                              |

Do not merge all four engines into one generic `AIEngine`. They have different instructions, input requirements, output schemas and validation rules.

### I. Application-level orchestrators

Files:

- `backend/app/services/explanation_orchestrator.py`
- `backend/app/services/bug_detection_orchestrator.py`
- `backend/app/services/test_generation_orchestrator.py`
- `backend/app/services/code_review_orchestrator.py`

Keep these separate from the AI feature engines.

Their responsibility should be:

1. Validate the requested repository and target.
2. Load the correct repository revision.
3. Build the feature-specific context.
4. Invoke the appropriate AI engine.
5. Validate the returned result.
6. Persist the analysis through the history service.
7. Return the expected API response.

The AI engine should be responsible for feature-specific inference and structured result generation.

Do not put repository ownership, database persistence or HTTP request handling inside the AI engines.

## 5. P1 — Feature-specific AI improvements

The four engines should remain separate, but they should follow the same execution and validation lifecycle.

### A. Code explanation

File: `backend/ai/services/explanation_service.py`

Change:

- Keep explanation-specific prompts and output schema.
- Require source context from the correct repository revision.
- Include relevant callers, imports and related symbols only when they are available.
- Distinguish directly observed code behaviour from inferred behaviour.
- Do not invent function callers or dependencies.
- Validate every source reference.
- Use the shared output validator.
- Remove duplicated provider-policy checks and model defaults.
- Return a clear missing-context explanation rather than pretending the code was fully understood.

Expected result: An explanation that describes what the code actually does, how it connects to nearby code and what evidence supports the explanation.

### B. Bug detection

File: `backend/ai/services/bug_detection_engine.py`

Change:

- Keep the existing core bug categories: off-by-one, null safety, unhandled exceptions, boundary conditions, resource leaks, race conditions, logic errors and security.
- Combine static-analysis findings with AI reasoning without treating every static warning as a confirmed bug.
- Require evidence for every finding.
- Require a valid file path and line range when the finding claims to identify a specific location.
- Separate confirmed defects from potential risks.
- Include severity, confidence and a concise remediation suggestion.
- Deduplicate findings that describe the same underlying issue.
- Avoid generating generic warnings just to increase the finding count.
- Use the shared validation and repair mechanism.

Expected result: Fewer but more actionable findings, with evidence and uncertainty clearly represented.

### C. Test generation

File: `backend/ai/services/test_generation_service.py`

Change:

- Keep framework detection and framework-aware generation.
- Preserve the repository's existing testing conventions, imports and fixtures.
- Generate normal, edge-case and failure-path scenarios.
- Check the proposed test file path against repository path rules.
- Validate the generated code syntax.
- Avoid importing arbitrary generated modules during validation.
- Never claim that tests passed merely because test code was generated or parsed.
- Keep actual test execution as a separately controlled operation.
- Use the shared output validator and bounded repair mechanism.
- Avoid generating duplicate tests already present in the repository context.

Expected result: Valid, repository-compatible test files that are clearly labelled as generated and not yet executed.

### D. Code review

File: `backend/ai/services/code_review_engine.py`

Change:

- Keep the five review categories: correctness, security, performance, reliability and maintainability.
- Preserve the distinction between newly introduced and pre-existing defects.
- Compare the changed lines against surrounding context.
- Require evidence for every finding.
- Distinguish actionable defects from suggestions.
- Keep confidence and uncertainty visible.
- Deduplicate findings from AI and static analysis.
- Avoid treating formatting preferences as high-severity problems.
- Verify source paths and line numbers against the correct revision.
- Use the shared output validation mechanism.

Expected result: A focused review of the actual changes, not a generic review of the entire repository.

### E. Static analysis and AI review integration

File: `backend/review/static_reviewer.py`

Keep static tools such as Ruff and Bandit as deterministic evidence sources.

Change:

- Ensure every scanned path is resolved inside the repository workspace.
- Reject paths that escape the repository root, including traversal through symlinks.
- Keep command arguments separate; never use shell string execution.
- Keep timeouts and bounded output.
- Normalize scanner findings into one stable format.
- Preserve the original scanner and rule ID.
- Deduplicate identical findings.
- Keep static findings separate from AI findings in the final result.
- Do not silently hide scanner execution failures; record which scanners failed.
- Ensure scanner output cannot inject arbitrary metadata or secret values into prompts and API responses.

Important: AI should interpret and prioritize static findings. It should not overwrite the underlying scanner evidence.

### F. Feature-specific orchestrators

Keep the four application orchestrators as the workflow boundary:

- `app/services/explanation_orchestrator.py`
- `app/services/bug_detection_orchestrator.py`
- `app/services/test_generation_orchestrator.py`
- `app/services/code_review_orchestrator.py`

Change:

- Build context once per analysis request.
- Avoid rebuilding the same context in multiple layers.
- Pass a single validated source revision through the entire workflow.
- Avoid passing arbitrary extra `kwargs` between layers when explicit typed parameters are possible.
- Keep persistence and history outside the AI engines.
- Keep AI inference outside the database transaction.
- Validate the final result before saving it.
- Ensure retrying an analysis does not accidentally create duplicate history records.

## 6. P1 — Retrieval quality and context optimization

This is where the AI platform's usefulness will be determined. A strong LLM with poor repository context will still produce poor results.

### A. Vector retrieval

File: `backend/ai/retrieval/vector.py`

Change:

- Keep repository-scoped vector search.
- Keep dimension validation.
- Make candidate limits configurable.
- Avoid returning duplicate chunks.
- Preserve file path, line range, language and source revision metadata.
- Ensure stale or deleted chunks are not returned as current evidence.
- Add a sensible similarity threshold only after evaluating it against a representative dataset.
- Record query latency and result counts.
- Avoid loading full source files when chunk-level retrieval is sufficient.

### B. Lexical retrieval

File: `backend/ai/retrieval/lexical.py`

Change:

- Keep query sanitization.
- Preserve repository filtering.
- Improve handling of identifiers, symbols, filenames and exact function names.
- Keep exact-match search useful for code-specific queries.
- Avoid overly aggressive sanitization that removes meaningful symbols.
- Test punctuation, underscores, camelCase, snake_case, paths and language keywords.
- Return consistent chunk metadata with vector retrieval.

### C. Hybrid retrieval

File: `backend/ai/retrieval/hybrid.py`

Change:

- Keep concurrent vector and lexical retrieval.
- Keep Reciprocal Rank Fusion.
- Keep graceful degradation when one retriever fails.
- Make vector and lexical candidate counts configurable.
- Make the final result count configurable by feature.
- Deduplicate by stable chunk identity, not just text similarity.
- Preserve scores and provenance separately.
- Record whether vector, lexical or both sources contributed.
- Do not use the same retrieval configuration for a short explanation and a broad repository question without evaluation.

### D. Reranking

File: `backend/ai/retrieval/reranker.py`

Change:

- Keep the optional cross-encoder.
- Add a bounded inference queue or semaphore.
- Limit the number and size of candidates.
- Record reranker latency.
- Keep the original retrieval order as a safe fallback.
- Do not compare cross-encoder logits directly with vector similarity scores as if they were the same scale.
- Evaluate whether reranking improves code retrieval before enabling it for every request.

### E. Context budget

Files:

- `backend/ai/context/builder.py`
- `backend/ai/context/service.py`
- `backend/app/core/config.py`

The current context builder uses token budgeting and priority-based truncation. Preserve this capability.

Change:

- Set explicit budgets for chat, Explain, Bug, Test and Review.
- Reserve tokens for system instructions and output.
- Include the most relevant target code before secondary related files.
- Keep recent chat history, but do not let it consume the entire budget.
- Remove duplicate chunks and repeated memory entries.
- Truncate long files and comments safely.
- Preserve enough surrounding lines to understand code behaviour.
- Record actual context size and truncation decisions.
- Add an explicit indication when important context was omitted.
- Use model-appropriate token estimation where practical.
- Keep a safe fallback estimator if the tokenizer is unavailable.

Do not use the LLM's maximum context window as your default context budget. Reserve room for the system prompt, user question, history and generated answer.

### F. Context caching

File: `backend/ai/context/service.py`

Change:

- Cache by repository ID, revision, target and feature.
- Invalidate on repository revision changes.
- Do not reuse a cached context across repositories.
- Do not reuse an explanation context for bug detection if their context requirements differ.
- Track hit rate and invalidation count.
- Bound cache size and TTL.
- Avoid caching user-specific conversation history in a shared repository context.
- Keep sensitive source context out of logs.

## 7. P2 — Cost, latency and model efficiency

The platform should not spend unnecessary tokens or run expensive inference when a cheaper deterministic operation is sufficient.

### A. Central inference limits

Files: `app/core/config.py`, `ai/llm/client.py`

Centralize:

- Request timeout.
- Maximum retries.
- Maximum output tokens.
- Maximum concurrent requests.
- Maximum input/context tokens.
- Maximum repair attempts.
- Per-feature model selection.
- Provider fallback policy.

Set conservative defaults and measure actual usage before increasing them.

### B. Avoid duplicate LLM calls

Check every workflow for this sequence:

```
Build context
    ↓
Call LLM
    ↓
Validate output
    ↓
Call LLM again to repair
    ↓
Validate again
```

Change:

- Do not repair valid output.
- Do not retry non-retryable provider errors.
- Do not repeat retrieval if the same result is still valid for the same revision and query.
- Do not summarize context if it already fits the budget.
- Do not call the LLM to classify something a deterministic parser can classify.
- Do not use an LLM to generate a result when required source evidence is missing.
- Keep repair attempts bounded and measured.

### C. Use the correct model for each task

Do not blindly use one model for all four features.

Evaluate:

- Explain: code comprehension and reasoning quality.
- Bug detection: defect precision and evidence quality.
- Test generation: syntax validity and scenario coverage.
- Code review: precision, severity calibration and false-positive rate.
- Chat: repository question-answering quality and citation accuracy.

Use the smallest model that meets the measured quality target for each task. Do not select a model solely because it has a larger context window or more parameters.

### D. Provider key rotation

The code supports multiple Gemini and Groq keys.

Change:

- Keep key rotation centralized inside provider adapters.
- Respect each provider's rate limits and quota policy.
- Do not assume multiple API keys grant unlimited additional quota.
- Do not rotate keys indefinitely for authentication or invalid-request failures.
- Track which provider/key pool was used without logging the actual key.
- Prevent concurrent requests from creating uncontrolled retry storms.
- Do not silently fall back to a different model if its output quality or format is incompatible.

### E. AI telemetry

Record these metrics for each feature:

| Metric                    | Why it matters                        |
| ------------------------- | ------------------------------------- |
| Provider and model        | Know which model generated the result |
| Input tokens              | Monitor context cost                  |
| Output tokens             | Monitor generation cost               |
| Total tokens              | Track overall usage                   |
| Retrieval latency         | Identify search bottlenecks           |
| Reranking latency         | Measure cross-encoder overhead        |
| Context-building latency  | Identify context overhead             |
| LLM latency               | Measure provider performance          |
| Validation failures       | Measure structured-output quality     |
| Repair attempts           | Identify unstable prompts/models      |
| Grounding rejection count | Detect hallucinated references        |
| Fallback usage            | Identify provider reliability         |
| Feature success rate      | Measure real user-facing reliability  |

Do not store complete prompts or repository source code as telemetry.

### F. Degraded operation

Handle these situations explicitly:

| Failure                            | Correct behaviour                                             |
| ---------------------------------- | ------------------------------------------------------------- |
| LLM key missing                    | Feature reports unavailable                                   |
| Primary provider rate-limited      | Use configured compatible fallback, or return retryable error |
| Both providers unavailable         | Return controlled temporary-unavailable response              |
| Embedding provider unavailable     | Do not pretend vector search succeeded                        |
| Vector search unavailable          | Use lexical search if it succeeds                             |
| Both retrieval sources unavailable | Return retrieval-unavailable error                            |
| No relevant chunks                 | Return an honest no-evidence response                         |
| Reranker unavailable               | Use fused retrieval results                                   |
| Invalid model JSON                 | Run bounded validation/repair                                 |
| Invalid repaired output            | Return structured AI validation error                         |
| Grounding fails                    | Remove or reject unverified citations                         |
| Context exceeds budget             | Apply deterministic truncation and report omitted context     |

## 8. P2 — Prompt management and AI output quality

### A. Centralize prompt loading

Files:

- `backend/ai/prompts/__init__.py`
- `backend/ai/prompts/*.txt`
- `backend/ai/schemas/prompt_builder.py`

The four feature engines load prompt files, but each also has an inline fallback prompt when loading fails.

Change this:

- Keep prompts outside Python source files.
- Use one prompt loader.
- Cache loaded prompt text rather than reading files repeatedly.
- Validate that required prompt files exist during AI service initialization.
- Do not silently use a different inline prompt when a production prompt file is missing.
- Version prompts so changes can be correlated with output quality.
- Keep feature-specific prompts separate.
- Keep untrusted repository data in the user/data portion of the request.
- Add prompt tests for missing files, empty files and incorrect prompt versions.

For production, a missing required prompt should make the relevant AI feature unavailable with a clear initialization error, not silently change its behaviour.

### B. Remove prompt duplication carefully

Review these pairs:

- `chat_system.txt` and `repository_chat.txt`
- `context_summary.txt` and `summary_system.txt`
- `grounding_system.txt` and `source_grounding.txt`

Compare their actual consumers and content.

- If two files serve the same purpose, select one canonical prompt and migrate callers.
- If they serve different stages, keep both and document their distinct responsibilities.
- Do not delete prompts simply because their filenames are similar.

### C. Improve prompt quality

For each feature prompt, require:

Explain

- Explain only code supported by the supplied context.
- Separate observed behaviour from inference.
- Do not invent callers or dependencies.
- Return structured output.

Bug Detection

- Identify an actual defect, not merely a style preference.
- Provide source evidence.
- Explain impact and reproduction conditions where possible.
- Distinguish certainty from suspicion.

Test Generation

- Follow repository framework conventions.
- Generate executable-looking test code, but do not claim it was executed.
- Include normal, boundary and failure scenarios.
- Reuse existing fixtures where supplied.

Code Review

- Focus on changed code and relevant surrounding context.
- Report actionable issues.
- Identify whether the issue is new or pre-existing.
- Avoid duplicate or speculative findings.

Repository Chat

- Answer only from authorized repository evidence.
- Cite relevant files and line ranges.
- Say when the answer is not available in the indexed context.
- Do not invent file contents.

### D. Output schemas

File: `backend/ai/schemas/output.py`

Keep the shared chat response schema, but keep feature-specific result schemas in their appropriate schema modules.

Change:

- Make required fields genuinely required.
- Avoid overly permissive default values that turn missing model output into an apparently valid result.
- Validate severity against an allowed set.
- Validate confidence against an allowed set.
- Validate line numbers and file paths.
- Limit finding count and field lengths.
- Ensure optional fields are explicit.
- Prevent unexpected extra model-generated fields from entering the API response.
- Keep schema compatibility with the frontend TypeScript types.

Do not weaken Pydantic validation simply to reduce model errors.

## 9. AI agent and tool execution: what to keep disabled

File: `backend/agent/tools/router.py`

The current `ToolRouter` defines tool metadata and handlers, but deliberately refuses execution until policy checks and argument validation are integrated.

Keep fail-closed

For Week 2:

- Keep tool execution disabled.
- Keep tool registration and discovery separate from execution.
- Do not let model-generated tool requests execute arbitrary Python, shell commands or Git operations.
- Do not expose unrestricted filesystem access.
- Do not allow the LLM to select arbitrary repository paths.
- Do not treat a tool's JSON arguments as trusted input.
- Do not connect an unrestricted agent loop to the production LLM gateway.

Before enabling agent tools in a later phase, implement:

1. Tool allowlist.
2. Per-tool JSON schema validation.
3. User and repository authorization.
4. Permission checks for every operation.
5. Workspace path confinement.
6. Execution timeouts.
7. CPU, memory and output limits.
8. Audit logs.
9. Approval requirements for destructive or externally visible actions.
10. Sandboxed execution for code-running operations.

The agent tool router should not be removed just because it is currently disabled. It is a useful boundary, and fail-closed behaviour is the correct choice until the security controls exist.

Keep `backend/agent/tools/README.MD` and update it when the future execution policy is implemented.

## 10. AI files — final keep, modify, merge and removal checklist

This is the consolidated file-level decision list.

| Path                                             | Decision                                            |
| ------------------------------------------------ | --------------------------------------------------- |
| `backend/ai/pipeline.py`                         | Keep as canonical RAG orchestration                 |
| `backend/ai/retrieval/pipeline.py`               | Remove duplicate chat orchestration after migration |
| `backend/ai/interfaces.py`                       | Keep; consolidate duplicate protocols               |
| `backend/ai/llm/client.py`                       | Keep; central gateway                               |
| `backend/ai/llm/provider.py`                     | Keep; provider contract                             |
| `backend/ai/llm/gemini_provider.py`              | Keep; improve reliability                           |
| `backend/ai/llm/groq_provider.py`                | Keep; improve reliability                           |
| `backend/ai/llm/schemas.py`                      | Keep; improve type safety                           |
| `backend/ai/embeddings/client.py`                | Keep                                                |
| `backend/ai/embeddings/service.py`               | Keep; central embedding service                     |
| `backend/ai/embeddings/gemini_provider.py`       | Keep                                                |
| `backend/ai/retrieval/base.py`                   | Keep                                                |
| `backend/ai/retrieval/vector.py`                 | Keep; optimize and validate                         |
| `backend/ai/retrieval/lexical.py`                | Keep; improve code search                           |
| `backend/ai/retrieval/fusion.py`                 | Keep                                                |
| `backend/ai/retrieval/hybrid.py`                 | Keep as canonical hybrid retriever                  |
| `backend/ai/retrieval/reranker.py`               | Keep; add resource controls                         |
| `backend/ai/context/builder.py`                  | Split by responsibility                             |
| `backend/ai/context/service.py`                  | Keep; improve caching and revision checks           |
| `backend/ai/context/explanation.py`              | Keep                                                |
| `backend/ai/context/bug_context.py`              | Keep                                                |
| `backend/ai/context/test_context.py`             | Keep                                                |
| `backend/ai/context/review_context.py`           | Keep                                                |
| `backend/ai/prompts/__init__.py`                 | Keep; centralize prompt loading                     |
| `backend/ai/prompts/chat_system.txt`             | Keep; compare with repository_chat                  |
| `backend/ai/prompts/repository_chat.txt`         | Review for duplicate purpose                        |
| `backend/ai/prompts/explanation_system.txt`      | Keep                                                |
| `backend/ai/prompts/bug_detection_system.txt`    | Keep                                                |
| `backend/ai/prompts/test_generation_system.txt`  | Keep                                                |
| `backend/ai/prompts/code_review_system.txt`      | Keep                                                |
| `backend/ai/prompts/grounding_system.txt`        | Keep                                                |
| `backend/ai/prompts/source_grounding.txt`        | Review for duplicate purpose                        |
| `backend/ai/prompts/context_summary.txt`         | Review consumers; keep if used                      |
| `backend/ai/prompts/summary_system.txt`          | Review for duplicate purpose                        |
| `backend/ai/prompts/repair_system.txt`           | Keep; integrate into shared repair flow             |
| `backend/ai/schemas/output.py`                   | Keep; strengthen schemas                            |
| `backend/ai/schemas/errors.py`                   | Keep                                                |
| `backend/ai/schemas/validator.py`                | Keep as shared output validator                     |
| `backend/ai/schemas/grounding.py`                | Keep; strict production grounding                   |
| `backend/ai/schemas/prompt_builder.py`           | Keep; simplify and enforce separation               |
| `backend/ai/services/explanation_service.py`     | Keep; refactor                                      |
| `backend/ai/services/bug_detection_engine.py`    | Keep; refactor                                      |
| `backend/ai/services/test_generation_service.py` | Keep; refactor                                      |
| `backend/ai/services/code_review_engine.py`      | Keep; refactor                                      |
| `backend/agent/tools/router.py`                  | Keep disabled until policy and sandboxing exist     |
| `backend/review/static_reviewer.py`              | Keep; strengthen path and scanner safety            |
| `backend/review/blast_radius.py`                 | Keep; evaluate in code-review quality tests         |

Do not delete any feature engine, retriever, context builder or prompt before migrating its consumers and tests.

## 11. AI evaluation — how to measure whether it is actually good

A successful API response does not prove that the AI feature is good.

The project already contains evaluation-oriented tests and scripts:

- `backend/tests/test_feature_quality_benchmarks.py`
- `backend/tests/test_rag.py`
- `backend/tests/test_hybrid_retrieval.py`
- `backend/tests/test_vector_retrieval.py`
- `backend/tests/test_finding_provenance_and_grounding.py`
- `backend/tests/test_context_builder.py`
- `backend/tests/test_prompts.py`
- `backend/tests/test_pipeline_integration.py`
- `backend/tests/test_full_system_integration.py`
- `backend/scripts/benchmark_quality_suite.py`
- `backend/scripts/test_context_real.py`

Keep these. Improve their coverage rather than creating another parallel benchmark suite.

### A. RAG retrieval evaluation

The existing feature benchmark describes these targets:

| Metric               | Existing target |
| -------------------- | --------------- |
| File hit rate        | At least 80%    |
| Mean Reciprocal Rank | At least 0.80   |
| Precision\@1         | At least 70%    |

Use a fixed ground-truth dataset containing:

- Repository question.
- Expected relevant file paths.
- Expected relevant code symbols or chunks.
- Expected answer facts.
- Expected source references.

Test the same questions against vector-only, lexical-only, hybrid and reranked retrieval.

Do not tune retrieval thresholds using the evaluation test set itself. Keep a separate validation set for tuning.

### B. Grounding and hallucination evaluation

Test:

- Valid file citations.
- Invalid file citations.
- Invalid line ranges.
- Nonexistent files.
- Citations to another repository.
- Unsupported claims with plausible-looking source references.
- Answers when retrieval returns no relevant evidence.
- Answers when retrieval infrastructure fails.
- Stale source revisions.

The desired behaviour is zero accepted fabricated citations in the controlled evaluation dataset.

This is a test target, not a guarantee that an LLM can never hallucinate.

### C. Explain evaluation

Measure:

- Correctness of function descriptions.
- Correctness of parameter and return-value explanations.
- Caller and dependency accuracy.
- Source-reference validity.
- Missing-context honesty.
- Unsupported claims.

### D. Bug detection evaluation

Measure:

- Precision of confirmed bug findings.
- Recall against known defects.
- False-positive rate.
- Severity accuracy.
- Evidence and line-location accuracy.
- Duplicate finding rate.

Prioritize precision. A bug scanner that reports many speculative issues is not necessarily better.

### E. Test generation evaluation

Measure:

- Syntax validity.
- Framework compatibility.
- Import and fixture correctness.
- Normal-case coverage.
- Boundary-case coverage.
- Failure-path coverage.
- Duplicate test rate.
- Actual test pass rate when execution is performed in a controlled environment.

Keep generated-test success and executed-test success as separate metrics.

### F. Code review evaluation

Measure:

- Finding precision.
- Finding recall.
- Correct severity.
- New-versus-pre-existing classification.
- Evidence accuracy.
- Actionability.
- Duplicate findings.
- False-positive rate.

### G. Cost and latency evaluation

Measure each feature independently:

| Metric                       | Why                    |
| ---------------------------- | ---------------------- |
| Average input tokens         | Context efficiency     |
| Average output tokens        | Output efficiency      |
| Average total tokens         | Cost control           |
| P50/P95 inference latency    | User experience        |
| P50/P95 retrieval latency    | Retrieval performance  |
| Repair rate                  | Output stability       |
| Provider fallback rate       | Reliability            |
| Cost per successful analysis | Operational efficiency |
| Quality per token            | Model efficiency       |

Do not choose a model only from its benchmark reputation. Choose it using your own representative repository tasks.

## 12. AI tests to add or strengthen

### A. LLM provider and gateway tests

Existing: `test_llm_gateway.py`

Add:

1. Primary provider success.
2. Primary provider timeout.
3. Primary provider rate limit.
4. Fallback provider success.
5. Both providers unavailable.
6. Invalid provider-specific model name.
7. Fallback model mapping.
8. Invalid structured response.
9. Provider authentication failure.
10. Multiple-key rotation.
11. Retry limit enforcement.
12. Client shutdown and resource cleanup.
13. Telemetry does not contain API keys or raw prompts.

### B. Embedding tests

Existing:

- `test_embedding_service.py`
- `test_embedding_dimension_invariant.py`
- `test_embedding_queue.py`

Add:

1. Wrong vector dimension.
2. NaN and infinite values.
3. Empty input.
4. Batch response count mismatch.
5. Batch order preservation.
6. Provider timeout.
7. Rate limit and bounded retry.
8. Concurrent embedding limit.
9. Model/version mismatch.
10. Indexing and query embedding compatibility.

### C. Retrieval tests

Existing:

- `test_vector_retrieval.py`
- `test_hybrid_retrieval.py`
- `test_rag.py`

Add:

1. Vector-only success.
2. Lexical-only success.
3. Both retrieval sources success.
4. Vector source failure with lexical fallback.
5. Lexical source failure with vector fallback.
6. Both sources failing.
7. Both sources succeeding with no results.
8. Duplicate chunk removal.
9. Repository isolation.
10. Stale revision rejection.
11. Invalid repository ID.
12. Reranker failure fallback.
13. Reranker concurrency limit.
14. Candidate count limit.
15. Stable ordering and provenance preservation.

### D. Context and prompt tests

Existing:

- `test_context_builder.py`
- `test_prompts.py`
- `test_meet_day1_intelligence_context.py`
- `test_meet_day2_explanation_context.py`
- `test_meet_day3_bug_context.py`
- `test_meet_day4_test_context.py`
- `test_meet_day5_review_context.py`
- `test_meet_day7_context_verification.py`

Add:

- Strict token-budget enforcement.
- Correct truncation priority.
- No duplicate chunks.
- No cross-repository context.
- No stale revision context.
- No user-controlled system prompt override.
- Prompt injection inside README files.
- Prompt injection inside source comments.
- Prompt injection inside commit messages.
- Secret redaction in retrieved context.
- Missing prompt file behaviour.
- Prompt version tracking.
- Correct handling of special tokens in repository content.

### E. Feature engine tests

Keep and extend the existing Explain, Bug, Test and Review tests.

Every feature should be tested with:

- Valid output.
- Malformed JSON.
- Schema-invalid output.
- Repair success.
- Repair failure.
- Provider timeout.
- Provider rate limit.
- Missing context.
- Stale context.
- Secret-containing source code.
- Invalid source references.
- Empty retrieval.
- Excessively large context.

### F. Grounding tests

Existing: `test_finding_provenance_and_grounding.py`

Add:

- A valid source reference passes.
- A missing source file fails.
- A line range outside file bounds fails.
- A source reference to another repository fails.
- A stale revision fails strict verification.
- A missing production DB session does not count as verified grounding.
- Invalid citations are not silently converted into valid citations.

## 13. Implementation order — AI production plan

The order below minimizes regression risk. Do not tune prompts or models before fixing the pipeline and retrieval architecture.

Phase 1 — AI architecture correctness

P0

1. Make `ai/pipeline.py` the canonical RAG pipeline.
2. Remove duplicate chat orchestration from `ai/retrieval/pipeline.py` after migration.
3. Make `HybridRetriever` the only hybrid retrieval implementation.
4. Fix model selection when Groq is the primary provider.
5. Centralize LLM provider and model configuration.
6. Keep all inference calls behind `LLMGateway`.
7. Unify output validation and JSON repair behaviour.
8. Make strict grounding mandatory in production.
9. Test repository isolation and prompt injection boundaries.

Phase 2 — Retrieval and context reliability

P0

1. Validate embedding model and dimension consistency.
2. Verify vector and lexical repository filters.
3. Preserve hybrid fallback behaviour.
4. Improve chunk identity and deduplication.
5. Control reranker loading, memory and concurrency.
6. Strengthen context revision validation and cache invalidation.
7. Enforce context token budgets for all features.
8. Run retrieval and grounding benchmarks.

Phase 3 — Feature engine cleanup

P1

1. Refactor Explain engine.
2. Refactor Bug Detection engine.
3. Refactor Test Generation engine.
4. Refactor Code Review engine.
5. Remove duplicated provider-policy checks and model defaults.
6. Standardize feature output validation.
7. Preserve separate feature-specific prompts and schemas.
8. Verify static findings and AI findings remain distinguishable.

Phase 4 — Context and prompt refactoring

P1

1. Split the 967-line context builder into responsibility-based modules.
2. Keep a compatibility facade during migration.
3. Simplify context service caching and revision checks.
4. Centralize prompt loading.
5. Remove genuinely duplicate prompt files after checking consumers.
6. Version prompts and add prompt validation tests.
7. Remove duplicated context rendering and token estimation.

Phase 5 — Quality, cost and release validation

Release gate

1. Run Explain, Bug, Test and Review evaluation datasets.
2. Run RAG retrieval and grounding benchmarks.
3. Measure P50/P95 latency and token usage.
4. Test provider outage and fallback scenarios.
5. Test cold-start and reranker memory usage on Azure.
6. Verify all AI tests and integration tests pass.
7. Run complete repository chat and analysis workflows.

## 14. Final priorities

If we have limited time, prioritize these changes in this exact order:

| Priority | Work                                            | Importance                 |
| -------- | ----------------------------------------------- | -------------------------- |
| 1        | One canonical RAG pipeline                      | Critical                   |
| 2        | Correct provider/model selection                | Critical                   |
| 3        | Central LLM gateway and fallback                | Critical                   |
| 4        | Strict repository-scoped retrieval              | Critical                   |
| 5        | Embedding model/dimension consistency           | Critical                   |
| 6        | Prompt injection and secret protection          | Critical                   |
| 7        | Strict source grounding                         | Critical                   |
| 8        | Shared structured-output validation             | Critical                   |
| 9        | Retrieval failure and fallback correctness      | High                       |
| 10       | Context revision and token-budget controls      | High                       |
| 11       | Separate and improve four AI engines            | High                       |
| 12       | Split oversized context builder                 | High                       |
| 13       | Centralize prompt loading and remove duplicates | High                       |
| 14       | Reranker performance and resource limits        | High                       |
| 15       | AI evaluation and quality benchmarks            | Critical release gate      |
| 16       | Cost and latency optimization                   | High                       |
| 17       | Agent tool execution security                   | Later phase; keep disabled |

## 15. Expected AI architecture after Week 2

AI-powered developer intelligence

Feature workflows

Repository Chat · Explain · Bug Detection · Test Generation · Code Review

Feature orchestration and context

Target validation · Revision consistency · ContextBuilder · Token budgets

Hybrid retrieval

Vector · Lexical · RRF · Reranker

Prompt construction

System instructions · Untrusted data · Output contract

LLM Gateway

Gemini · Groq · Model routing · Fallback · Telemetry

Validation and grounding

Pydantic validation · Bounded repair · Source verification · Secret redaction

Verified structured result

Evidence-backed findings · Explanations · Tests · Review · Citations

## 16. What should remain outside this AI phase?

To prevent overlapping changes, keep these separate:

| Area                | What to do                                                                                         |
| ------------------- | -------------------------------------------------------------------------------------------------- |
| Database / pgvector | Preserve current interfaces; later audit indexing, dimensions, SQL, migrations and storage         |
| Redis               | Preserve current cache/queue interfaces; later audit job durability, cache design and key policies |
| Backend API         | Keep current API contracts; coordinate changes through the backend plan                            |
| Frontend            | Keep existing AI request/response contracts while refactoring internal AI logic                    |
| Documentation       | Do not rewrite all architecture documentation during this phase                                    |
| Agent execution     | Keep tools disabled until permissions, policy validation and sandboxing are ready                  |

One important coordination point: The AI phase must agree with the database phase on embedding model, dimensions, chunk identity and source revision. Do not independently change any of these in the AI code.

## 17. Final expected result by the end of Week 2

The AI subsystem should have:

- One canonical RAG pipeline.
- One central LLM gateway.
- Correct Gemini/Groq model routing and fallback.
- One consistent embedding configuration.
- Repository-isolated retrieval.
- Hybrid retrieval with safe degradation.
- Controlled reranking.
- Token-bounded context construction.
- Prompt injection protection.
- Centralized structured-output validation.
- Strict source grounding.
- Four independent, maintainable AI engines.
- Consistent Explain, Bug, Test and Review results.
- Measurable retrieval and generation quality.
- Bounded inference cost and latency.
- No unnecessary duplicate pipeline, prompt or provider-policy code.
- Passing AI unit, integration and evaluation tests.

My recommendation: Do not start fine-tuning a model or adding more agents yet. First make the existing RAG pipeline, retrieval, context, grounding and four AI workflows reliable. That will improve the platform much more than adding another model or another layer of orchestration.

The uploaded ZIP was inspected statically. I have not run the full AI evaluation suite against live Gemini/Groq services or a production repository dataset, so the quality targets still need measured verification.

This completes the AI audit plan. The next separate technical audit should cover the database and pgvector, followed by Redis and queue/cache architecture.