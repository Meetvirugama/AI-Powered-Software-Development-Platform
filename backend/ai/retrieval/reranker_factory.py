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
    configured_backend = (backend or getattr(settings, "reranker_backend", "pytorch")).lower()
    model_path = kwargs.pop("model_path", None) or onnx_model_path or getattr(settings, "reranker_onnx_model_path", None)

    if configured_backend == "onnx" or getattr(settings, "reranker_onnx_enabled", False):
        try:
            return ONNXCrossEncoderReranker(
                model_path=model_path,
                **kwargs,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "onnx_reranker_factory_creation_failed_falling_back_to_pytorch",
                extra={"error": str(exc)},
            )

    return CrossEncoderReranker(**kwargs)
