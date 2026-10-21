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
| `repository_chat.txt` | User prompt template combining retrieved code chunks and user question | `{context}`, `{question}` |
| `summary_system.txt` | System prompt for summarizing large code chunks during token truncation | None |
| `context_summary.txt` | User prompt template for code chunk summarization | `{code_content}` |
| `grounding_system.txt` | System prompt for citation hallucination detection | None |
| `source_grounding.txt` | User prompt for validating cited sources against repository ground truth | `{answer}`, `{sources}`, `{files}` |
| `repair_system.txt` | System prompt for repairing invalid or malformed JSON responses | None |

## API (`backend/ai/prompts/__init__.py`)
- `load_prompt(name: str) -> str`: Loads and caches a prompt template file.
- `render_prompt(name: str, **kwargs: Any) -> str`: Interpolates placeholders with validation.
- `list_available_prompts() -> list[str]`: Lists available prompt templates without `.txt`.
- `clear_prompt_cache() -> None`: Clears the LRU cache.
