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
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROMPTS_DIR: Path = Path(__file__).parent.resolve()


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


__all__ = [
    "PROMPTS_DIR",
    "PromptNotFoundError",
    "PromptRenderError",
    "clear_prompt_cache",
    "list_available_prompts",
    "load_prompt",
    "render_prompt",
]
