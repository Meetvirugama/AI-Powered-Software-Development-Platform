"""Module 10 (AI Code Review) audit fixes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from app.api.v1.analysis.common import assign_persistent_finding_ids
from app.schemas.analysis import ReviewPublicationRequest
from app.services.review_feedback_service import ReviewFeedbackService


# ---------------------------------------------------------------------------
# Persistent finding ids (feedback / lifecycle / issue linking need DB ids)
# ---------------------------------------------------------------------------

class _F:
    def __init__(self, fid: str) -> None:
        self.id = fid

    def model_copy(self, update):
        return _F(update["id"])


def test_non_uuid_finding_ids_become_stable_uuids_per_run() -> None:
    run_a, run_b = str(uuid4()), str(uuid4())
    keep = str(uuid4())
    first = assign_persistent_finding_ids([_F("rev-finding-1"), _F(keep)], run_a)
    again = assign_persistent_finding_ids([_F("rev-finding-1")], run_a)
    other = assign_persistent_finding_ids([_F("rev-finding-1")], run_b)

    UUID(first[0].id)  # valid UUID
    assert first[1].id == keep  # already-UUID ids are untouched
    assert first[0].id == again[0].id  # deterministic within a run
    assert first[0].id != other[0].id  # distinct across runs


# ---------------------------------------------------------------------------
# Finding lifecycle driven by feedback
# ---------------------------------------------------------------------------

def _record(meta: dict | None, feedback: str) -> tuple[str, dict]:
    finding = SimpleNamespace(id=uuid4(), finding_metadata=meta)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = finding
    entry = ReviewFeedbackService().record_feedback(db, finding_id=finding.id, feedback_type=feedback)
    return entry["lifecycle_status"], finding.finding_metadata


def test_false_positive_dismisses() -> None:
    status, meta = _record(None, "false_positive")
    assert status == "DISMISSED"
    assert meta["lifecycle"]["dismissed_reason"] == "false_positive"


def test_already_fixed_marks_fixed() -> None:
    status, _ = _record(None, "already_fixed")
    assert status == "FIXED"


def test_useful_after_dismissal_reopens() -> None:
    status, meta = _record({"lifecycle": {"status": "DISMISSED", "dismissed_reason": "false_positive"}}, "useful")
    assert status == "REOPENED"
    assert "dismissed_reason" not in meta["lifecycle"]


def test_useful_on_new_finding_keeps_it_new() -> None:
    status, meta = _record(None, "useful")
    assert status == "NEW"
    assert "lifecycle" not in meta


# ---------------------------------------------------------------------------
# Publication request defaults
# ---------------------------------------------------------------------------

def test_publication_does_not_force_by_default_and_defers_to_repo_settings() -> None:
    req = ReviewPublicationRequest(pr_number=7)
    assert req.force_publish is False
    assert req.max_comments is None
    assert req.min_confidence is None
    assert req.changed_lines_only is None


def test_review_run_pr_number_matching() -> None:
    from app.api.v1.analysis.review import _review_run_pr_number

    assert _review_run_pr_number(SimpleNamespace(result_payload={"target": {"type": "pr", "pr_number": 7}})) == 7
    assert _review_run_pr_number(SimpleNamespace(result_payload={"target": {"type": "file"}})) is None
    assert _review_run_pr_number(SimpleNamespace(result_payload=None)) is None


# ---------------------------------------------------------------------------
# Finding -> issue/task: local-only fallback is labelled
# ---------------------------------------------------------------------------

def test_issue_response_marks_local_only_issues() -> None:
    from app.schemas.plan import GitHubIssueResponse

    issue = GitHubIssueResponse(
        id=str(uuid4()), repository_id=str(uuid4()), issue_number=3, title="t", html_url="https://github.com/o/r/issues/3"
    )
    assert issue.published_to_github is True
    assert issue.model_copy(update={"published_to_github": False}).published_to_github is False


@pytest.mark.parametrize("bad", ["INVALID_PARAMETER"])
def test_review_routes_only_use_defined_error_codes(bad: str) -> None:
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app/api/v1/analysis/review.py").read_text()
    assert f"ErrorCode.{bad}" not in src
