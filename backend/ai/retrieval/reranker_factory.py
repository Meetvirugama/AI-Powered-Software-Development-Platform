"""
Reranker Factory — Instantiates PyTorch or ONNX Cross-Encoder based on configuration (R08).
Owner: Meet — W1-12
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.core.config import get_settings

from .reranker import CrossEncoderReranker
from .reranker_onnx import ONNXCrossEncoderReranker

logger = logging.getLogger(__name__)

__all__ = ["create_reranker", "create_serving_reranker", "resolve_reranker_model_source"]


def resolve_reranker_model_source(settings: Any = None) -> str:
    """Resolve local pre-baked reranker weights when present, else the HuggingFace model ID."""
    if settings is None:
        settings = get_settings()
    model_path = getattr(settings, "reranker_model_path", None)
    if model_path:
        if Path(model_path).is_dir():
            return str(model_path)
        logger.warning(
            "reranker_model_path_missing_falling_back_to_hub",
            extra={"model_path": str(model_path)},
        )
    return getattr(settings, "reranker_model_name", None) or "cross-encoder/ms-marco-MiniLM-L-6-v2"


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
                if "model_name" not in pytorch_kwargs and "model" not in pytorch_kwargs:
                    pytorch_kwargs["model_name"] = resolve_reranker_model_source(settings)
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
    if "model_name" not in pytorch_kwargs and "model" not in pytorch_kwargs:
        pytorch_kwargs["model_name"] = resolve_reranker_model_source(settings)
    return CrossEncoderReranker(**pytorch_kwargs)


def create_serving_reranker(**kwargs: Any) -> CrossEncoderReranker | ONNXCrossEncoderReranker:
    """Prepare the production PyTorch model before the retrieval service becomes ready."""
    reranker = create_reranker(**kwargs)
    if isinstance(reranker, CrossEncoderReranker):
        reranker.warm_up()
    return reranker
