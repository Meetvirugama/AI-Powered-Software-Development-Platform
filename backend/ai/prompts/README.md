# Prompt Templates Subsystem
**Owner:** Dev (AI Quality Lead) & Meet (AI/ML Lead)

This directory contains production prompt templates and the caching/rendering engine for the AI layer.

## Architecture Guidelines
1. **Separation of Instructions and Untrusted Data:** Repository code and user input are untrusted and must never be inserted into `system` prompts. They belong strictly in user turns.
2. **Path Traversal Protection:** All template access via `load_prompt()` enforces strict containment within this directory.
3. **Caching:** All templates are cached via `functools.lru_cache(maxsize=64)`. Invalidate during tests with `clear_prompt_cache()`.

## Template Files

| File | Purpose | Interpolation Placeholders |
|------|---------|---------------------------|
| `chat_system.txt` | System prompt enforcing repository boundaries, grounding, and citation format | None |
| `repository_chat.txt` | User prompt template combining retrieved code chunks and user question | `{file_path}`, `{start_line}`, `{end_line}`, `{repository_context}`, `{question}` |
| `bug_detection_system.txt` | System prompt for repository bug detection and hypothesis reporting | None |
| `code_review_system.txt` | System prompt for automated code review findings and duplicate suppression | None |
| `explanation_system.txt` | System prompt for symbol, flow, and architecture code explanation | None |
| `test_generation_system.txt` | System prompt for generating unit and regression test suites | None |
| `test_planning_system.txt` | System prompt for test scenario planning and requirement discovery | None |
| `test_review_system.txt` | System prompt for adversarial test quality review and assertion completeness checking | None |
| `summary_system.txt` | System prompt for summarizing large code chunks during token truncation | None |
| `context_summary.txt` | User prompt template for code chunk summarization | `{file_path}`, `{start_line}`, `{end_line}`, `{code_content}` |
| `grounding_system.txt` | System prompt for citation hallucination detection | None |
| `source_grounding.txt` | User prompt for validating cited sources against repository ground truth | `{verified_file_list}`, `{answer}`, `{claimed_sources}` |
| `repair_system.txt` | System prompt for repairing invalid or malformed JSON responses | `{schema_name}`, `{error_message}`, `{invalid_content}` |

## API (`backend/ai/prompts/__init__.py`)
- `load_prompt(name: str) -> str`: Loads and caches a prompt template file.
- `render_prompt(name: str, **kwargs: Any) -> str`: Interpolates placeholders with validation.
- `list_available_prompts() -> list[str]`: Lists available prompt templates without `.txt`.
- `clear_prompt_cache() -> None`: Clears the LRU cache.
