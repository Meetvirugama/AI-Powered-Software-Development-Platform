"""
Reranker Factory — Instantiates PyTorch or ONNX Cross-Encoder based on configuration (R08).
Owner: Meet — W1-12
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import get_settings

from .reranker import CrossEncoderReranker
from .reranker_onnx import ONNXCrossEncoderReranker

logger = logging.getLogger(__name__)

__all__ = ["create_reranker"]


def create_reranker(
    backend: str | None = None,
    onnx_model_path: str | None = None,
    **kwargs: Any,
) -> CrossEncoderReranker | ONNXCrossEncoderReranker:
    """
    Factory function to create a Cross-Encoder reranker.

    Supports:
    - 'pytorch' (default production cross-encoder)
    - 'onnx' (experimental ONNX Runtime cross-encoder)

    Falls back safely to PyTorch if ONNX is requested but fails initialization.
    """
    settings = get_settings()
    if backend:
        chosen_backend = backend.lower()
    elif getattr(settings, "reranker_backend", None):
        chosen_backend = settings.reranker_backend.lower()
    elif getattr(settings, "reranker_onnx_enabled", False):
        chosen_backend = "onnx"
    else:
        chosen_backend = "pytorch"

    model_path = kwargs.pop("model_path", None) or onnx_model_path or getattr(settings, "reranker_onnx_model_path", None)

    if chosen_backend == "onnx":
        onnx_kwargs = {
            k: v for k, v in kwargs.items()
            if k in {"onnx_session", "tokenizer", "max_length", "min_logit"}
        }
        if not backend:
            try:
                import onnxruntime  # noqa: F401
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "onnx_reranker_factory_creation_failed_falling_back_to_pytorch",
                    extra={"error": str(exc)},
                )
                pytorch_kwargs = {
                    k: v for k, v in kwargs.items()
                    if k in {"model_name", "model", "min_logit", "max_chars"}
                }
                return CrossEncoderReranker(**pytorch_kwargs)

        try:
            return ONNXCrossEncoderReranker(
                model_path=model_path,
                **onnx_kwargs,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "onnx_reranker_factory_creation_failed_falling_back_to_pytorch",
                extra={"error": str(exc)},
            )

    pytorch_kwargs = {
        k: v for k, v in kwargs.items()
        if k in {"model_name", "model", "min_logit", "max_chars"}
    }
    return CrossEncoderReranker(**pytorch_kwargs)
