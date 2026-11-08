"""Unit tests for ReviewFeedbackService and ReviewLifecycleService (Phase 4)."""

import pytest
from unittest.mock import MagicMock
from uuid import uuid4
from app.services.review_lifecycle_service import ReviewLifecycleService
from app.services.review_feedback_service import ReviewFeedbackService


@pytest.fixture
def lifecycle_service():
    return ReviewLifecycleService()


@pytest.fixture
def feedback_service():
    return ReviewFeedbackService()


def test_validate_lifecycle_transitions(lifecycle_service):
    # Allowed transitions
    assert lifecycle_service.validate_transition("NEW", "ACTIVE") is True
    assert lifecycle_service.validate_transition("ACTIVE", "FIXED") is True
    assert lifecycle_service.validate_transition("FIXED", "REOPENED") is True
    assert lifecycle_service.validate_transition("ACTIVE", "DISMISSED") is True

    # Same state is valid
    assert lifecycle_service.validate_transition("ACTIVE", "ACTIVE") is True

    # Disallowed transitions
    assert lifecycle_service.validate_transition("FIXED", "ACTIVE") is False


def test_update_lifecycle_for_finding(lifecycle_service):
    finding = {"title": "SQL Bug", "finding_metadata": {}}
    updated = lifecycle_service.update_lifecycle_for_finding(
        finding,
        "NEW",
        commit_sha="commit_1",
        reason="Initial detection",
    )
    meta = updated["finding_metadata"]["lifecycle"]
    assert meta["status"] == "NEW"
    assert meta["first_detected_commit"] == "commit_1"
    assert meta["last_detected_commit"] == "commit_1"
    assert len(meta["history"]) == 1

    # Transition to ACTIVE on next commit
    updated2 = lifecycle_service.update_lifecycle_for_finding(
        updated,
        "ACTIVE",
        commit_sha="commit_2",
        reason="Persisted",
    )
    meta2 = updated2["finding_metadata"]["lifecycle"]
    assert meta2["status"] == "ACTIVE"
    assert meta2["last_detected_commit"] == "commit_2"
    assert len(meta2["history"]) == 2


def test_track_findings_across_commits_lifecycle(lifecycle_service):
    commit_1_findings = [
        {"deduplication_key": "fp_bug_1", "title": "Bug 1", "finding_metadata": {}},
        {"deduplication_key": "fp_bug_2", "title": "Bug 2", "finding_metadata": {}},
    ]

    # Run 1: First commit -> both are NEW
    curr_1, resolved_1 = lifecycle_service.track_findings_across_commits(
        current_findings=commit_1_findings,
        previous_findings=[],
        current_commit_sha="c1",
    )
    assert len(curr_1) == 2
    assert curr_1[0]["finding_metadata"]["lifecycle"]["status"] == "NEW"
    assert curr_1[1]["finding_metadata"]["lifecycle"]["status"] == "NEW"
    assert len(resolved_1) == 0

    # Run 2: Second commit -> Bug 1 persists, Bug 2 is absent (fixed)
    commit_2_findings = [
        {"deduplication_key": "fp_bug_1", "title": "Bug 1", "finding_metadata": {}},
    ]
    curr_2, resolved_2 = lifecycle_service.track_findings_across_commits(
        current_findings=commit_2_findings,
        previous_findings=curr_1,
        current_commit_sha="c2",
    )
    assert len(curr_2) == 1
    assert curr_2[0]["finding_metadata"]["lifecycle"]["status"] == "ACTIVE"
    assert len(resolved_2) == 1
    assert resolved_2[0]["deduplication_key"] == "fp_bug_2"
    assert resolved_2[0]["finding_metadata"]["lifecycle"]["status"] == "FIXED"

    # Run 3: Third commit -> Bug 2 is accidentally re-introduced
    commit_3_findings = [
        {"deduplication_key": "fp_bug_2", "title": "Bug 2", "finding_metadata": {}},
    ]
    curr_3, _ = lifecycle_service.track_findings_across_commits(
        current_findings=commit_3_findings,
        previous_findings=[*curr_2, *resolved_2],
        current_commit_sha="c3",
    )
    assert len(curr_3) == 1
    assert curr_3[0]["finding_metadata"]["lifecycle"]["status"] == "REOPENED"


def test_record_feedback_updates_finding_metadata(feedback_service):
    mock_db = MagicMock()
    mock_finding = MagicMock()
    mock_finding.finding_metadata = {}
    mock_db.query.return_value.filter.return_value.first.return_value = mock_finding

    f_id = uuid4()
    entry = feedback_service.record_feedback(
        mock_db,
        finding_id=f_id,
        feedback_type="useful",
        user_id="user_123",
        comment="Great catch!",
    )

    assert entry["feedback_type"] == "useful"
    assert entry["comment"] == "Great catch!"
    assert mock_finding.finding_metadata["feedback"]["feedback_type"] == "useful"
    mock_db.commit.assert_called_once()


def test_record_feedback_rejects_invalid_type(feedback_service):
    mock_db = MagicMock()
    with pytest.raises(ValueError, match="Invalid feedback_type"):
        feedback_service.record_feedback(
            mock_db,
            finding_id=uuid4(),
            feedback_type="invalid_vote_type",
        )


def test_compute_repository_feedback_stats(feedback_service):
    mock_db = MagicMock()
    f1 = MagicMock()
    f1.finding_metadata = {"feedback": {"feedback_type": "useful"}}
    f2 = MagicMock()
    f2.finding_metadata = {"feedback": {"feedback_type": "useful"}}
    f3 = MagicMock()
    f3.finding_metadata = {"feedback": {"feedback_type": "false_positive"}}
    f4 = MagicMock()
    f4.finding_metadata = {}  # no feedback

    mock_db.query.return_value.filter.return_value.all.return_value = [f1, f2, f3, f4]

    stats = feedback_service.compute_repository_feedback_stats(mock_db, uuid4())
    assert stats.total_feedback == 3
    assert stats.useful_count == 2
    assert stats.false_positive_count == 1
    assert stats.acceptance_rate == pytest.approx(2 / 3, 0.01)
    assert stats.false_positive_rate == pytest.approx(1 / 3, 0.01)
