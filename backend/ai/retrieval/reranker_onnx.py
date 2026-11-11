"""
ONNX Runtime Cross-Encoder Reranker (R08).
Owner: Meet — W1-12

Evaluates cross-encoder latency and memory footprint using ONNX Runtime.
Matches PyTorch CrossEncoderReranker interface and scoring semantics.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

from .base import CodeChunk

logger = logging.getLogger(__name__)

__all__ = ["ONNXCrossEncoderReranker"]

_DEFAULT_TOP_N = 8
_DEFAULT_MAX_LENGTH = 512


class ONNXCrossEncoderReranker:
    """
    Reranks candidates using an ONNX-optimized cross-encoder model.
    Falls back gracefully if ONNX runtime is unavailable or execution fails.
    """

    def __init__(
        self,
        model_path: str | None = None,
        onnx_session: Any = None,
        tokenizer: Any = None,
        max_length: int = _DEFAULT_MAX_LENGTH,
        min_logit: float | None = None,
    ) -> None:
        self._model_path = model_path
        self._session = onnx_session
        self._tokenizer = tokenizer
        self._max_length = max_length
        self._min_logit = min_logit
        self.last_status: str = "initialized"

    @property
    def status(self) -> str:
        return self.last_status

    def _ensure_initialized(self) -> bool:
        if self._session is not None and self._tokenizer is not None:
            return True

        if self._session is None:
            if not self._model_path:
                self.last_status = "uninitialized: no model path or session"
                return False
            try:
                import onnxruntime as ort
                self._session = ort.InferenceSession(self._model_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("onnx_session_init_failed", extra={"error": str(exc)})
                self.last_status = f"failed: {exc}"
                return False

        if self._tokenizer is None:
            try:
                from transformers import AutoTokenizer
                try:
                    self._tokenizer = AutoTokenizer.from_pretrained(
                        "cross-encoder/ms-marco-MiniLM-L-6-v2",
                        local_files_only=True,
                    )
                except Exception:
                    self._tokenizer = AutoTokenizer.from_pretrained(
                        "cross-encoder/ms-marco-MiniLM-L-6-v2",
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("onnx_tokenizer_init_failed", extra={"error": str(exc)})
                self.last_status = f"tokenizer_failed: {exc}"
                return False

        if self._session is None or self._tokenizer is None:
            return False

        self.last_status = "ready"
        return True

    def rerank(
        self,
        query: str,
        candidates: list[CodeChunk],
        top_n: int = _DEFAULT_TOP_N,
        min_logit: float | None = None,
    ) -> list[CodeChunk]:
        """
        Rerank candidates using ONNX runtime inference.
        """
        if not candidates or top_n <= 0:
            return []

        if not self._ensure_initialized():
            logger.warning("onnx_reranker_not_ready_fallback_to_candidate_order")
            return candidates[:top_n]

        threshold = min_logit if min_logit is not None else self._min_logit

        try:
            pairs = [(query, c.content) for c in candidates]
            # Tokenize inputs
            if callable(self._tokenizer):
                try:
                    import numpy as np  # type: ignore[import-not-found]
                except ImportError:
                    np = None  # type: ignore[assignment]

                encoded = self._tokenizer(
                    [p[0] for p in pairs],
                    [p[1] for p in pairs],
                    padding=True,
                    truncation=True,
                    max_length=self._max_length,
                    return_tensors="np",
                )
                inputs = {
                    "input_ids": encoded["input_ids"],
                    "attention_mask": encoded["attention_mask"],
                }
                if "token_type_ids" in encoded:
                    inputs["token_type_ids"] = encoded["token_type_ids"]

                outputs = self._session.run(None, inputs)
                out_arr = outputs[0]
                if np is not None and hasattr(np, "array"):
                    if not hasattr(out_arr, "tolist"):
                        out_arr = np.array(out_arr)
                    squeezed = out_arr.squeeze()
                    if hasattr(squeezed, "tolist"):
                        raw_scores = squeezed.tolist()
                    else:
                        raw_scores = [float(squeezed)]
                    if isinstance(raw_scores, (int, float)):
                        raw_scores = [float(raw_scores)]
                else:
                    def _flatten_scores(val: Any) -> list[float]:
                        if isinstance(val, (int, float)):
                            return [float(val)]
                        if hasattr(val, "tolist"):
                            return _flatten_scores(val.tolist())
                        if isinstance(val, (list, tuple)):
                            flat: list[float] = []
                            for item in val:
                                flat.extend(_flatten_scores(item))
                            return flat
                        return [float(val)]

                    raw_scores = _flatten_scores(out_arr)
            else:
                # If mock tokenizer without __call__, fallback
                raw_scores = [c.score for c in candidates]

            scored_candidates = []
            for chunk, score in zip(candidates, raw_scores):
                logit = float(score)
                if threshold is not None and logit < threshold:
                    continue
                scored_candidates.append(
                    dataclasses.replace(
                        chunk,
                        score=round(logit, 6),
                        reranker_logit=round(logit, 6),
                    )
                )

            scored_candidates.sort(key=lambda c: (-c.score, str(c.id)))
            self.last_status = "success"
            return scored_candidates[:top_n]

        except Exception as exc:  # noqa: BLE001
            logger.warning("onnx_rerank_inference_error_fallback", extra={"error": str(exc)})
            self.last_status = f"error: {exc}"
            return candidates[:top_n]
