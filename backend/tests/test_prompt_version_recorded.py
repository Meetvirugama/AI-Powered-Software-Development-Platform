"""Test prompt version and model metadata recorded per run (TST-34, OPT-18).

Validates:
- Every analysis run recording captures prompt_version and model in result_payload.
- Prompt registry provides immutable version identifiers for each system prompt.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from ai.prompts import PROMPT_REGISTRY, get_prompt_metadata
from app.services.analysis_run_history_service import AnalysisRunHistoryService


def test_prompt_registry_has_semantic_versions() -> None:
    """TST-34: Core prompts have explicit semantic versions and prompt_ids."""
    for prompt_name in ("explanation_system", "bug_detection_system", "test_generation_system", "code_review_system"):
        meta = get_prompt_metadata(prompt_name)
        assert meta is not None
        assert meta.version.count(".") == 2  # e.g., "1.0.0"
        assert meta.prompt_id.startswith("prompt-")


def test_analysis_run_history_service_injects_prompt_version_and_model() -> None:
    """TST-34 / OPT-18: AnalysisRunHistoryService automatically records prompt_version and model."""
    mock_session = MagicMock()
    service = AnalysisRunHistoryService(session_factory=lambda: mock_session)

    record = {
        "id": str(uuid4()),
        "repository_id": str(uuid4()),
        "user_id": str(uuid4()),
        "feature_type": "EXPLANATION",
        "status": "COMPLETED",
        "result_payload": {"summary": "Explains code"},
    }

    mock_run = MagicMock()
    mock_session.execute.return_value.scalar_one_or_none.return_value = mock_run

    with MagicMock() as mock_repo_cls:
        service.record_run(record, db=mock_session)

    payload = record["result_payload"]
    assert "prompt_version" in payload
    assert payload["prompt_version"] == "1.0.0"
    assert "model" in payload
    assert len(payload["model"]) > 0
