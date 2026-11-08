"""Unit tests for IncrementalReviewService (Phase 5)."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.incremental_review_service import IncrementalReviewService


@pytest.fixture
def mock_pub_service():
    service = AsyncMock()
    mock_res = MagicMock()
    mock_res.status = "PUBLISHED"
    mock_res.published_comments_count = 1
    mock_res.to_dict.return_value = {"status": "PUBLISHED", "published_comments_count": 1}
    service.publish_pull_request_review.return_value = mock_res
    return service


@pytest.fixture
def inc_service(mock_pub_service):
    return IncrementalReviewService(publication_service=mock_pub_service)


@pytest.mark.asyncio
async def test_initial_review_publishes_all_findings(inc_service, mock_pub_service):
    mock_repo = MagicMock(owner="test-owner", name="test-repo", pr_review_enabled=True)
    findings = [
        {"deduplication_key": "fp1", "file_path": "a.py", "title": "Issue 1", "finding_metadata": {}},
        {"deduplication_key": "fp2", "file_path": "b.py", "title": "Issue 2", "finding_metadata": {}},
    ]

    result = await inc_service.execute_incremental_review(
        repository=mock_repo,
        pr_number=10,
        new_commit_sha="commit_sha_111",
        previous_commit_sha=None,
        previous_findings=[],
        current_findings=findings,
        github_service=AsyncMock(),
    )

    assert result.is_incremental is False
    assert result.new_findings_count == 2
    assert result.resolved_findings_count == 0
    mock_pub_service.publish_pull_request_review.assert_awaited_once()


@pytest.mark.asyncio
async def test_incremental_review_filters_persisting_and_detects_resolved(inc_service, mock_pub_service):
    mock_repo = MagicMock(owner="test-owner", name="test-repo", pr_review_enabled=True)

    # Previous run had fp1 and fp2
    prev_findings = [
        {
            "deduplication_key": "fp1",
            "file_path": "a.py",
            "title": "Bug 1",
            "finding_metadata": {"lifecycle": {"status": "NEW"}},
        },
        {
            "deduplication_key": "fp2",
            "file_path": "b.py",
            "title": "Bug 2",
            "finding_metadata": {"lifecycle": {"status": "NEW"}},
        },
    ]

    # Current run: fp1 persists, fp2 fixed, fp3 is newly introduced
    curr_findings = [
        {"deduplication_key": "fp1", "file_path": "a.py", "title": "Bug 1", "finding_metadata": {}},
        {"deduplication_key": "fp3", "file_path": "c.py", "title": "Bug 3", "finding_metadata": {}},
    ]

    result = await inc_service.execute_incremental_review(
        repository=mock_repo,
        pr_number=10,
        new_commit_sha="commit_sha_222",
        previous_commit_sha="commit_sha_111",
        previous_findings=prev_findings,
        current_findings=curr_findings,
        github_service=AsyncMock(),
    )

    assert result.is_incremental is True
    assert result.new_findings_count == 1  # Only fp3 is NEW
    assert result.resolved_findings_count == 1  # fp2 was resolved
    assert result.resolved_findings[0]["deduplication_key"] == "fp2"

    # Verify publication was called with only fp3 (not fp1)
    call_args = mock_pub_service.publish_pull_request_review.await_args.kwargs
    pub_findings = call_args["findings"]
    assert len(pub_findings) == 1
    assert pub_findings[0]["deduplication_key"] == "fp3"
    assert "Incremental Review" in call_args["custom_summary"]
