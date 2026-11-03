"""
Prompt Templates Subsystem — Enterprise Prompt Management and Caching.
Owner: Dev / Meet — W1-12

Provides:
- Thread-safe, cached prompt template loading from disk.
- Path traversal protection.
- String interpolation with validation and helpful error diagnostics.
- Clear separation between instruction prompts and untrusted repository data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROMPTS_DIR: Path = Path(__file__).parent.resolve()


@dataclass(frozen=True)
class PromptMetadata:
    """Enterprise metadata for versioned AI prompt templates."""

    prompt_id: str
    version: str
    owner: str
    capability: str
    expected_output_schema: str | None = None
    last_evaluated: str | None = None
    description: str | None = None
    required_variables: tuple[str, ...] = ()


PROMPT_REGISTRY: dict[str, PromptMetadata] = {
    "chat_system": PromptMetadata(
        prompt_id="prompt-chat-sys-001",
        version="1.0.0",
        owner="AI Team",
        capability="chat",
        expected_output_schema="RepositoryAnswer",
        last_evaluated="2026-10-31",
        description="System prompt enforcing repository boundaries, grounding, and citation format",
    ),
    "repository_chat": PromptMetadata(
        prompt_id="prompt-repo-chat-001",
        version="1.0.0",
        owner="AI Team",
        capability="chat",
        expected_output_schema="RepositoryAnswer",
        last_evaluated="2026-10-31",
        description="User prompt template combining retrieved code chunks and user question",
        required_variables=("context", "question"),
    ),
    "bug_detection_system": PromptMetadata(
        prompt_id="prompt-bug-det-sys-001",
        version="1.0.0",
        owner="AI Team",
        capability="bug_detection",
        expected_output_schema="BugDetectionResult",
        last_evaluated="2026-10-31",
        description="System prompt for repository bug detection and hypothesis reporting",
    ),
    "code_review_system": PromptMetadata(
        prompt_id="prompt-code-rev-sys-001",
        version="1.0.0",
        owner="AI Team",
        capability="code_review",
        expected_output_schema="CodeReviewResult",
        last_evaluated="2026-10-31",
        description="System prompt for code review findings and duplicate suppression",
    ),
    "explanation_system": PromptMetadata(
        prompt_id="prompt-explain-sys-001",
        version="1.0.0",
        owner="AI Team",
        capability="explanation",
        expected_output_schema="ExplanationResult",
        last_evaluated="2026-10-31",
        description="System prompt for symbol/flow code explanation",
    ),
    "test_generation_system": PromptMetadata(
        prompt_id="prompt-test-gen-sys-001",
        version="1.0.0",
        owner="AI Team",
        capability="test_generation",
        expected_output_schema="TestGenerationResult",
        last_evaluated="2026-10-31",
        description="System prompt for generating unit and regression test suites",
    ),
    "repair_system": PromptMetadata(
        prompt_id="prompt-repair-sys-001",
        version="1.0.0",
        owner="AI Team",
        capability="repair",
        expected_output_schema="RepairedJSON",
        last_evaluated="2026-10-31",
        description="System prompt for repairing malformed JSON responses",
        required_variables=("schema_name", "error_message", "invalid_content"),
    ),
    "grounding_system": PromptMetadata(
        prompt_id="prompt-ground-sys-001",
        version="1.0.0",
        owner="AI Team",
        capability="grounding",
        expected_output_schema="GroundingVerification",
        last_evaluated="2026-10-31",
        description="System prompt for citation hallucination detection",
    ),
    "source_grounding": PromptMetadata(
        prompt_id="prompt-src-ground-001",
        version="1.0.0",
        owner="AI Team",
        capability="grounding",
        expected_output_schema="GroundingVerification",
        last_evaluated="2026-10-31",
        description="User prompt for validating cited sources against repository ground truth",
        required_variables=("answer", "sources", "files"),
    ),
    "summary_system": PromptMetadata(
        prompt_id="prompt-sum-sys-001",
        version="1.0.0",
        owner="AI Team",
        capability="summarization",
        expected_output_schema=None,
        last_evaluated="2026-10-31",
        description="System prompt for summarizing large code chunks during truncation",
    ),
    "context_summary": PromptMetadata(
        prompt_id="prompt-ctx-sum-001",
        version="1.0.0",
        owner="AI Team",
        capability="summarization",
        expected_output_schema=None,
        last_evaluated="2026-10-31",
        description="User prompt template for code chunk summarization",
        required_variables=("code_content",),
    ),
}


def get_prompt_metadata(name: str) -> PromptMetadata | None:
    """Return PromptMetadata for the given template name, or None if unregistered."""
    clean_name = name.strip()
    if clean_name.endswith(".txt"):
        clean_name = clean_name[:-4]
    return PROMPT_REGISTRY.get(clean_name)


class PromptNotFoundError(FileNotFoundError):
    """Raised when a requested prompt template file does not exist."""


class PromptRenderError(ValueError):
    """Raised when variable interpolation in a prompt template fails."""


@lru_cache(maxsize=64)
def load_prompt(name: str) -> str:
    """
    Load and cache a raw prompt template by name.

    Args:
        name: Template filename (with or without ``.txt`` extension).

    Returns:
        The stripped contents of the prompt template file.

    Raises:
        PromptNotFoundError: If the file does not exist or attempts path traversal.
    """
    clean_name = name.strip()
    if not clean_name.endswith(".txt"):
        clean_name = f"{clean_name}.txt"

    target_path = (PROMPTS_DIR / clean_name).resolve()

    # Security: Prevent path traversal attacks (e.g. '../../etc/passwd')
    try:
        target_path.relative_to(PROMPTS_DIR)
    except ValueError as exc:
        logger.error("prompt_path_traversal_attempt", extra={"requested": name})
        raise PromptNotFoundError(
            f"Security error: Invalid prompt name '{name}' outside prompts directory."
        ) from exc

    if not target_path.is_file():
        logger.warning("prompt_template_not_found", extra={"path": str(target_path)})
        raise PromptNotFoundError(
            f"Prompt template '{clean_name}' not found in {PROMPTS_DIR}."
        )

    try:
        return target_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.error("prompt_read_error", extra={"path": str(target_path), "error": str(exc)})
        raise PromptNotFoundError(
            f"Failed to read prompt template '{clean_name}': {exc}"
        ) from exc


def render_prompt(name: str, **kwargs: Any) -> str:
    """
    Load and format a prompt template with provided variables.

    Args:
        name: Template filename.
        **kwargs: Template placeholders and replacement values.

    Returns:
        The formatted prompt string.

    Raises:
        PromptRenderError: If required template placeholders are missing.
    """
    template = load_prompt(name)
    try:
        return template.format(**kwargs)
    except KeyError as exc:
        missing_key = str(exc).strip("'\"")
        raise PromptRenderError(
            f"Missing required placeholder '{missing_key}' when rendering prompt '{name}'."
        ) from exc
    except (IndexError, ValueError) as exc:
        raise PromptRenderError(
            f"Failed to format prompt '{name}': {exc}"
        ) from exc


def list_available_prompts() -> list[str]:
    """Return a sorted list of all available prompt template names without extension."""
    if not PROMPTS_DIR.is_dir():
        return []
    return sorted(p.stem for p in PROMPTS_DIR.glob("*.txt"))


def clear_prompt_cache() -> None:
    """Clear in-memory cached prompt templates (useful during testing or hot reloading)."""
    load_prompt.cache_clear()


REQUIRED_PROMPTS: list[str] = [
    "chat_system",
    "explanation_system",
    "bug_detection_system",
    "test_generation_system",
    "code_review_system",
    "repair_system",
    "grounding_system",
]


def validate_required_prompts(required: list[str] | None = None) -> list[str]:
    """Verify that all required prompt template files exist and are non-empty.

    Returns the list of validated prompt names.
    Raises PromptNotFoundError if any required prompt template is missing or unreadable.
    """
    to_check = required or REQUIRED_PROMPTS
    validated: list[str] = []
    for name in to_check:
        content = load_prompt(name)
        if not content or not content.strip():
            raise PromptRenderError(f"Required prompt template '{name}' is empty.")
        validated.append(name)
    return validated


__all__ = [
    "PROMPTS_DIR",
    "PROMPT_REGISTRY",
    "PromptMetadata",
    "PromptNotFoundError",
    "PromptRenderError",
    "REQUIRED_PROMPTS",
    "clear_prompt_cache",
    "get_prompt_metadata",
    "list_available_prompts",
    "load_prompt",
    "render_prompt",
    "validate_required_prompts",
]
