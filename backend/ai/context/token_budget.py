"""Token budget management, estimation, and allocation routines.
Owner: Meet — W1-12 / Issue #189 Token Budget Calibration
"""

from __future__ import annotations

import collections
from dataclasses import dataclass
from datetime import datetime, timezone
import functools
import json
import logging
import math
import os
import re
import threading
from collections.abc import Callable, Sequence
from typing import Any

try:
    import tiktoken
except ImportError:
    tiktoken = None  # type: ignore

from .models import ChatMessage

logger = logging.getLogger(__name__)

_ENCODING_NAME: str = "cl100k_base"
_OVERHEAD_TOKENS: int = 500
_BPE_WORD_PUNCT_RE = re.compile(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]+")

# Default recommended safety factor for approximate tokenizers (Issue #189)
DEFAULT_SAFETY_FACTOR: float = 1.15

# Mapping of provider names to their standard or closest approximate tiktoken encoding
PROVIDER_ENCODINGS: dict[str, str] = {
    "openai": "cl100k_base",
    "groq": "cl100k_base",
    # Gemini uses a proprietary SentencePiece tokenizer (~256k vocab).
    # Local tiktoken is retained for speed as an explicit approximation with safety factor.
    "gemini": "cl100k_base",
}

# Model-specific encoding mappings
MODEL_ENCODINGS: dict[str, str] = {
    # Modern OpenAI models
    "gpt-4o": "o200k_base",
    "gpt-4o-mini": "o200k_base",
    "o1": "o200k_base",
    "o1-preview": "o200k_base",
    "o1-mini": "o200k_base",
    "o3": "o200k_base",
    "o3-mini": "o200k_base",
    # Legacy / standard OpenAI
    "gpt-4": "cl100k_base",
    "gpt-4-turbo": "cl100k_base",
    "gpt-3.5-turbo": "cl100k_base",
    # Groq models (BPE compatible)
    "openai/gpt-oss-120b": "cl100k_base",
    "llama-3.3-70b-versatile": "cl100k_base",
    "llama-3.1-8b-instant": "cl100k_base",
    "qwen/qwen3.8-27b": "cl100k_base",
    # Gemini models (approximate cl100k_base)
    "gemini-flash-latest": "cl100k_base",
    "gemini-flash-lite-latest": "cl100k_base",
    "gemini-1.5-flash": "cl100k_base",
    "gemini-2.0-flash": "cl100k_base",
    "gemini-1.5-pro": "cl100k_base",
}

# Provider-specific safety factors
PROVIDER_SAFETY_FACTORS: dict[str, float] = {
    "gemini": 1.15,  # ~10-20% tokenizer discrepancy margin for SentencePiece vs cl100k_base
    "groq": 1.05,    # Groq hosts Llama/gpt-oss BPE models, slight variance
    "openai": 1.0,   # Exact tokenization via tiktoken
}


def get_encoding_for_model(model: str | None = None, provider: str | None = None) -> str:
    """Return appropriate tiktoken encoding name for model or provider.

    Falls back safely to 'cl100k_base' if model/provider is unknown or unspecified.
    """
    if model:
        norm_m = model.strip()
        if norm_m in MODEL_ENCODINGS:
            return MODEL_ENCODINGS[norm_m]
        norm_lower = norm_m.lower()
        for k, v in MODEL_ENCODINGS.items():
            if k.lower() == norm_lower:
                return v
    if provider:
        norm_p = provider.strip().lower()
        if norm_p in PROVIDER_ENCODINGS:
            return PROVIDER_ENCODINGS[norm_p]
    return _ENCODING_NAME


def get_safety_factor(
    provider: str | None = None,
    custom_factor: float | None = None,
) -> float:
    """Return the effective token safety factor for the given provider or custom factor.

    Priority:
    1. custom_factor (explicit parameter override)
    2. Environment variable AI_TOKEN_SAFETY_FACTOR
    3. PROVIDER_SAFETY_FACTORS mapping for the given provider
    4. DEFAULT_SAFETY_FACTOR (1.15)
    """
    if custom_factor is not None:
        if not math.isfinite(custom_factor) or custom_factor <= 0:
            raise ValueError(f"Safety factor must be finite and positive, got {custom_factor}")
        return float(custom_factor)

    env_val = os.getenv("AI_TOKEN_SAFETY_FACTOR")
    if env_val:
        try:
            parsed = float(env_val)
            if math.isfinite(parsed) and parsed > 0:
                return parsed
            logger.warning(
                "Invalid non-positive or non-finite AI_TOKEN_SAFETY_FACTOR '%s', ignoring.",
                env_val,
            )
        except ValueError:
            logger.warning(
                "Failed to parse AI_TOKEN_SAFETY_FACTOR '%s', ignoring.",
                env_val,
            )

    if provider:
        norm_p = provider.strip().lower()
        if norm_p in PROVIDER_SAFETY_FACTORS:
            return PROVIDER_SAFETY_FACTORS[norm_p]

    return DEFAULT_SAFETY_FACTOR


def calculate_effective_budget(
    budget: int,
    safety_factor: float | None = None,
    provider: str | None = None,
) -> int:
    """Calculate the effective token budget scaled down by the safety factor margin.

    effective_budget = max(0, int(budget / safety_factor))

    Ensures that when raw tiktoken estimation is performed, the actual provider tokens
    will not exceed the configured budget.
    """
    if budget <= 0:
        return 0
    factor = get_safety_factor(provider=provider, custom_factor=safety_factor)
    return max(0, int(budget / factor))


@functools.lru_cache(maxsize=8)
def _get_encoder(encoding_name: str = _ENCODING_NAME) -> Any:
    """Return the cached tiktoken encoder (thread-safe and reusable), or None if unavailable offline."""
    if tiktoken is None:
        return None
    try:
        return tiktoken.get_encoding(encoding_name)
    except Exception as exc:
        logger.warning(
            "tiktoken_encoder_unavailable_using_fallback",
            extra={"encoding_name": encoding_name, "error": str(exc)},
        )
        return None


def _approximate_bpe_tokens(text: str) -> int:
    """Approximate cl100k_base token count offline when tiktoken blob cache is unreachable."""
    if not text:
        return 0
    return max(1, len(_BPE_WORD_PUNCT_RE.findall(text)))


def count_tokens(
    text: str,
    encoding_name: str = _ENCODING_NAME,
    safety_factor: float = 1.0,
) -> int:
    """
    Return the number of tokens in *text* using cl100k_base (or specified) encoding.

    Safety:
        Uses ``disallowed_special=()`` so untrusted repository code containing
        special tokens (e.g. ``<|endoftext|>``) does not raise a ValueError.

    If safety_factor is specified and != 1.0, scales raw tokens deterministically:
        ceil(raw_tokens * safety_factor)
    """
    if not text:
        return 0
    if tiktoken is None:
        raw = _approximate_bpe_tokens(text)
    else:
        try:
            enc = _get_encoder(encoding_name)
            if enc is None:
                raw = _approximate_bpe_tokens(text)
            else:
                raw = len(enc.encode(text, disallowed_special=()))
        except Exception as exc:
            logger.warning(
                "token_counting_fallback",
                extra={"error": str(exc), "text_len": len(text)},
            )
            raw = _approximate_bpe_tokens(text)

    if safety_factor != 1.0 and safety_factor > 0:
        return int(math.ceil(raw * safety_factor))
    return raw


def estimate_tokens(
    text: str,
    encoding_name: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    safety_factor: float | None = None,
) -> int:
    """
    Return estimated token count for *text*, scaled by provider-aware safety factor.

    Formula:
        ceil(raw_tokens * safety_factor)
    """
    if not text:
        return 0
    enc = encoding_name or get_encoding_for_model(model=model, provider=provider)
    factor = get_safety_factor(provider=provider, custom_factor=safety_factor)
    return count_tokens(text, encoding_name=enc, safety_factor=factor)


def estimate_messages_tokens(
    messages: Sequence[Any],
    provider: str | None = None,
    model: str | None = None,
    safety_factor: float | None = None,
    per_message_overhead: int = 4,
) -> int:
    """
    Estimate total input tokens for a sequence of conversation messages including per-message framing.
    """
    if not messages:
        return 0
    enc = get_encoding_for_model(model=model, provider=provider)
    factor = get_safety_factor(provider=provider, custom_factor=safety_factor)
    total_raw = 0
    for msg in messages:
        content = getattr(msg, "content", "") or ""
        if isinstance(content, dict):
            try:
                content = json.dumps(content)
            except Exception:
                content = str(content)
        total_raw += count_tokens(str(content), encoding_name=enc) + per_message_overhead
    return int(math.ceil(total_raw * factor))


def fit_history(
    history: Sequence[ChatMessage],
    budget: int,
    formatter: Callable[[ChatMessage], str],
    safety_factor: float = 1.0,
) -> tuple[int, list[ChatMessage]]:
    """
    Fit as many history messages as possible within *budget* tokens.

    Iterates from newest to oldest so recent turns take precedence.
    Returns (total_tokens_used, kept_messages) in chronological order.
    """
    if budget <= 0:
        return 0, []

    kept: list[ChatMessage] = []
    used = 0
    for msg in reversed(history):
        tokens = count_tokens(formatter(msg), safety_factor=safety_factor)
        if used + tokens > budget:
            break
        kept.append(msg)
        used += tokens

    kept.reverse()  # Restore original chronological order
    return used, kept


def fit_items(
    items: Sequence[Any],
    budget: int,
    formatter: Callable[[Any], str],
    safety_factor: float = 1.0,
) -> tuple[int, list[Any]]:
    """
    Generic greedy token fitter — preserves items in priority order.

    Args:
        items:         Ordered list of items (highest priority first).
        budget:        Remaining token budget.
        formatter:     Callable(item) -> str for token counting.
        safety_factor: Optional safety multiplier applied during token check.

    Returns:
        (tokens_used, kept_items)
    """
    if budget <= 0:
        return 0, []

    kept: list[Any] = []
    used = 0
    for item in items:
        tokens = count_tokens(formatter(item), safety_factor=safety_factor)
        if used + tokens > budget:
            logger.debug(
                "context_truncation",
                extra={"dropped_item_tokens": tokens, "remaining_budget": budget - used},
            )
            break
        kept.append(item)
        used += tokens
    return used, kept


# ---------------------------------------------------------------------------
# Calibration Telemetry & Ratio Calculation (Issue #189 Phase 3 & 4)
# ---------------------------------------------------------------------------


def calculate_calibration_ratio(
    estimated_tokens: int | None,
    actual_input_tokens: int | None,
) -> float | None:
    """
    Calculate estimated-to-actual ratio: estimated_tokens / actual_input_tokens.

    Direction:
        ratio > 1.0: estimate was conservative / higher than actual usage.
        ratio < 1.0: estimate was under-counting / lower than actual usage.
        ratio == 1.0: exact match.

    Returns:
        float ratio rounded to 4 decimal places, or None if:
        - either value is missing / None / not a number
        - actual_input_tokens <= 0 (safeguard against division by zero)
        - estimated_tokens < 0
    """
    if estimated_tokens is None or actual_input_tokens is None:
        return None
    try:
        est = float(estimated_tokens)
        act = float(actual_input_tokens)
        if act <= 0 or est < 0:
            return None
        return round(est / act, 4)
    except (ValueError, TypeError, ZeroDivisionError):
        return None


@dataclass(frozen=True)
class TokenCalibrationSample:
    """Record of a single prompt token calibration measurement."""

    provider: str
    model: str
    estimated_tokens: int
    actual_input_tokens: int | None
    ratio: float | None
    timestamp: str
    feature: str | None = None


class TokenCalibrationTracker:
    """In-memory thread-safe observational calibration tracker and logger."""

    def __init__(self, max_samples: int = 1000) -> None:
        self._max_samples = max_samples
        self._samples: collections.deque[TokenCalibrationSample] = collections.deque(maxlen=max_samples)
        self._lock = threading.Lock()

    def record_sample(
        self,
        provider: str,
        model: str,
        estimated_tokens: int | None,
        actual_input_tokens: int | None,
        feature: str | None = None,
        timestamp: str | None = None,
    ) -> TokenCalibrationSample | None:
        """
        Record an observational calibration sample and emit structured telemetry.

        Guaranteed never to raise an exception or break calling pipelines.
        Never logs prompt contents, source code, credentials, or keys.
        """
        try:
            ts = timestamp or datetime.now(timezone.utc).isoformat()
            ratio = calculate_calibration_ratio(estimated_tokens, actual_input_tokens)
            sample = TokenCalibrationSample(
                provider=str(provider or "unknown"),
                model=str(model or "unknown"),
                estimated_tokens=int(estimated_tokens) if estimated_tokens is not None else 0,
                actual_input_tokens=int(actual_input_tokens) if actual_input_tokens is not None else None,
                ratio=ratio,
                timestamp=ts,
                feature=feature,
            )
            with self._lock:
                self._samples.append(sample)

            # Emit structured telemetry log without sensitive prompt content
            logger.info(
                "token_budget_calibration",
                extra={
                    "provider": sample.provider,
                    "model": sample.model,
                    "estimated_tokens": sample.estimated_tokens,
                    "actual_input_tokens": sample.actual_input_tokens,
                    "estimated_to_actual_ratio": sample.ratio,
                    "timestamp": sample.timestamp,
                    "feature": sample.feature,
                },
            )
            return sample
        except Exception as exc:
            logger.warning("token_calibration_telemetry_error", extra={"error": str(exc)})
            return None

    def get_samples(
        self,
        provider: str | None = None,
        model: str | None = None,
    ) -> list[TokenCalibrationSample]:
        """Retrieve recorded calibration samples, optionally filtered by provider/model."""
        with self._lock:
            items = list(self._samples)
        if provider:
            norm_p = provider.strip().lower()
            items = [s for s in items if s.provider.lower() == norm_p]
        if model:
            norm_m = model.strip().lower()
            items = [s for s in items if s.model.lower() == norm_m]
        return items

    def get_summary(
        self,
        provider: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Return aggregate calibration telemetry summary."""
        samples = self.get_samples(provider=provider, model=model)
        valid_ratios = [s.ratio for s in samples if s.ratio is not None]
        avg_ratio = round(sum(valid_ratios) / len(valid_ratios), 4) if valid_ratios else None
        return {
            "total_samples": len(samples),
            "valid_ratio_samples": len(valid_ratios),
            "average_ratio": avg_ratio,
            "min_ratio": min(valid_ratios) if valid_ratios else None,
            "max_ratio": max(valid_ratios) if valid_ratios else None,
        }

    def clear(self) -> None:
        """Clear stored calibration samples."""
        with self._lock:
            self._samples.clear()


_GLOBAL_CALIBRATION_TRACKER = TokenCalibrationTracker()


def get_calibration_tracker() -> TokenCalibrationTracker:
    """Return the process-wide TokenCalibrationTracker singleton."""
    return _GLOBAL_CALIBRATION_TRACKER
