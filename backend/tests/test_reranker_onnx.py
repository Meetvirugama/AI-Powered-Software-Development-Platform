"""
Unit tests for ONNX cross-encoder reranker and factory (R08).
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from backend.ai.retrieval.base import CodeChunk
from backend.ai.retrieval.reranker import CrossEncoderReranker
from backend.ai.retrieval.reranker_factory import create_reranker
from backend.ai.retrieval.reranker_onnx import ONNXCrossEncoderReranker


def _make_chunk(name: str = "chunk", score: float = 0.5) -> CodeChunk:
    return CodeChunk(
        id=uuid4(),
        repository_id=uuid4(),
        file_id=uuid4(),
        symbol_id=uuid4(),
        content=f"def {name}(): pass",
        token_count=10,
        start_line=1,
        end_line=2,
        content_hash="h1",
        score=score,
        file_path=f"src/{name}.py",
    )


def test_reranker_factory_default_pytorch() -> None:
    reranker = create_reranker()
    assert isinstance(reranker, CrossEncoderReranker)


def test_reranker_factory_onnx_selection() -> None:
    reranker = create_reranker(backend="onnx", model_path="dummy.onnx")
    assert isinstance(reranker, ONNXCrossEncoderReranker)


def test_onnx_reranker_ranking_with_mock_session() -> None:
    c1 = _make_chunk("c1", 0.5)
    c2 = _make_chunk("c2", 0.6)

    # Mock session returns logits: c1 -> 2.5, c2 -> 5.0
    mock_session = MagicMock()
    # outputs[0] is ndarray of shape (2, 1)
    mock_session.run.return_value = [[[2.5], [5.0]]]

    mock_tokenizer = MagicMock()
    mock_tokenizer.return_value = {
        "input_ids": [[1, 2], [3, 4]],
        "attention_mask": [[1, 1], [1, 1]],
    }

    reranker = ONNXCrossEncoderReranker(
        onnx_session=mock_session,
        tokenizer=mock_tokenizer,
    )

    reranked = reranker.rerank("query", [c1, c2], top_n=2)
    assert len(reranked) == 2
    # c2 had higher logit (5.0 > 2.5) so it should rank first
    assert reranked[0].id == c2.id
    assert reranked[0].score == 5.0
    assert reranked[1].id == c1.id
    assert reranked[1].score == 2.5


def test_onnx_reranker_fallback_on_uninitialized() -> None:
    # No session and no model_path
    reranker = ONNXCrossEncoderReranker(model_path=None)
    c = _make_chunk("c")

    # Should fall back to candidate list without raising error
    res = reranker.rerank("query", [c])
    assert len(res) == 1
    assert res[0].id == c.id


def test_onnx_reranker_fallback_on_inference_error() -> None:
    c1 = _make_chunk("c1")
    c2 = _make_chunk("c2")

    mock_session = MagicMock()
    mock_session.run.side_effect = RuntimeError("ONNX Execution Error")

    mock_tokenizer = MagicMock()
    mock_tokenizer.return_value = {"input_ids": [1], "attention_mask": [1]}

    reranker = ONNXCrossEncoderReranker(
        onnx_session=mock_session,
        tokenizer=mock_tokenizer,
    )

    # Must not raise error, returns candidates
    res = reranker.rerank("query", [c1, c2], top_n=2)
    assert len(res) == 2
