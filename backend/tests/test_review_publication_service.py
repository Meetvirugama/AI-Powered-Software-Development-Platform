"""Unit and integration tests for ReviewPublicationService (Phase 1)."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.review_publication_service import (
    ReviewPublicationResult,
    ReviewPublicationService,
)


@pytest.fixture
def pub_service():
    return ReviewPublicationService()


def test_extract_diff_line_ranges(pub_service):
    sample_patch = (
        "@@ -10,6 +10,8 @@ def calculate():\n"
        "     x = 1\n"
        "-    y = 2\n"
        "+    y = 3\n"
        "+    z = 4\n"
        "     return x + y\n"
    )
    changed = pub_service.extract_diff_line_ranges(sample_patch)
    # Line 10: x = 1 (context)
    # Line 11: y = 3 (added/modified)
    # Line 12: z = 4 (added/modified)
    assert 11 in changed
    assert 12 in changed
    assert 10 not in changed


def test_build_inline_comment_body(pub_service):
    finding = {
        "category": "security",
        "severity": "CRITICAL",
        "title": "SQL Injection in User Lookup",
        "description": "Raw string formatting used in SQL query.",
        "evidence": 'cursor.execute(f"SELECT * FROM users WHERE id={user_id}")',
        "suggested_fix": 'cursor.execute("SELECT * FROM users WHERE id=%s", (user_id,))',
    }
    body = pub_service.build_inline_comment_body(finding)
    assert "🚨 **[CRITICAL]**" in body
    assert "SQL Injection in User Lookup" in body
    assert "Raw string formatting used in SQL query." in body
    assert "cursor.execute" in body
    assert "```suggestion" in body


def test_build_review_summary(pub_service):
    findings = [
        {"category": "security", "severity": "HIGH"},
        {"category": "correctness", "severity": "MEDIUM"},
    ]
    summary = pub_service.build_review_summary(
        findings=findings,
        published_count=1,
        commit_sha="abcdef1234567890",
        risk_level="HIGH",
    )
    assert "AI Code Review Summary" in summary
    assert "Total Identified Findings:** 2" in summary
    assert "Inline Comments Published:** 1" in summary
    assert "abcdef12" in summary


@pytest.mark.asyncio
async def test_publish_skips_when_opted_out(pub_service):
    mock_gh = AsyncMock()
    mock_repo = MagicMock()
    mock_repo.pr_review_enabled = False

    result = await pub_service.publish_pull_request_review(
        owner="test-owner",
        repo_name="test-repo",
        pr_number=42,
        commit_sha="c0ffee1234567890",
        findings=[],
        github_service=mock_gh,
        repository=mock_repo,
    )
    assert result.status == "SKIPPED"
    assert "disabled" in result.skipped_reason.lower()
    mock_gh.create_pull_request_review.assert_not_called()


@pytest.mark.asyncio
async def test_publish_skips_when_pr_closed(pub_service):
    mock_gh = AsyncMock()
    mock_gh.get_pull_request_detail.return_value = {"state": "closed", "head": {"sha": "c0ffee"}}
    mock_repo = MagicMock()
    mock_repo.pr_review_enabled = True

    result = await pub_service.publish_pull_request_review(
        owner="test-owner",
        repo_name="test-repo",
        pr_number=42,
        commit_sha="c0ffee",
        findings=[],
        github_service=mock_gh,
        repository=mock_repo,
    )
    assert result.status == "SKIPPED"
    assert "not open" in result.skipped_reason.lower()


@pytest.mark.asyncio
async def test_publish_skips_when_commit_is_stale(pub_service):
    mock_gh = AsyncMock()
    mock_gh.get_pull_request_detail.return_value = {"state": "open", "head": {"sha": "newest_sha_999"}}
    mock_repo = MagicMock()
    mock_repo.pr_review_enabled = True

    result = await pub_service.publish_pull_request_review(
        owner="test-owner",
        repo_name="test-repo",
        pr_number=42,
        commit_sha="old_stale_sha_111",
        findings=[],
        github_service=mock_gh,
        repository=mock_repo,
    )
    assert result.status == "SKIPPED"
    assert "stale" in result.skipped_reason.lower()


@pytest.mark.asyncio
async def test_publish_filters_changed_lines_only(pub_service):
    mock_gh = AsyncMock()
    mock_gh.get_pull_request_detail.return_value = {"state": "open", "head": {"sha": "head_123"}}
    mock_gh.get_pull_request_files.return_value = [
        {
            "filename": "app/main.py",
            "patch": "@@ -1,4 +1,5 @@\n import os\n+import sys\n",
        }
    ]
    mock_gh.create_pull_request_review.return_value = {"id": 9999}
    mock_repo = MagicMock()
    mock_repo.pr_review_enabled = True

    findings = [
        # Finding 1: on line 2 (added sys) -> Should be published
        {
            "category": "maintainability",
            "severity": "LOW",
            "confidence": "high",
            "title": "Unused import sys",
            "description": "sys is not referenced",
            "source_reference": {"file_path": "app/main.py", "start_line": 2},
        },
        # Finding 2: on line 100 (not modified in diff) -> Should NOT be published
        {
            "category": "maintainability",
            "severity": "LOW",
            "confidence": "high",
            "title": "Old function smell",
            "description": "Legacy code",
            "source_reference": {"file_path": "app/main.py", "start_line": 100},
        },
    ]

    result = await pub_service.publish_pull_request_review(
        owner="test-owner",
        repo_name="test-repo",
        pr_number=10,
        commit_sha="head_123",
        findings=findings,
        github_service=mock_gh,
        repository=mock_repo,
    )

    assert result.status == "PUBLISHED"
    assert result.review_id == 9999
    assert result.published_comments_count == 1
    mock_gh.create_pull_request_review.assert_awaited_once()
    _, kwargs = mock_gh.create_pull_request_review.call_args
    assert len(kwargs["comments"]) == 1
    assert kwargs["comments"][0]["path"] == "app/main.py"
    assert kwargs["comments"][0]["line"] == 2


@pytest.mark.asyncio
async def test_publish_reconciles_on_network_timeout(pub_service):
    mock_gh = AsyncMock()
    mock_gh.get_pull_request_detail.return_value = {"state": "open", "head": {"sha": "head_123"}}
    mock_gh.get_pull_request_files.return_value = []
    # simulate network drop
    mock_gh.create_pull_request_review.side_effect = RuntimeError("Network timeout")
    # simulate GitHub review was created before timeout
    mock_gh.list_pull_request_reviews.return_value = [
        {"id": 7777, "body": "## 🤖 AI Code Review Summary\nCommit Evaluated: `head_123`", "commit_id": "head_123"}
    ]

    result = await pub_service.publish_pull_request_review(
        owner="test-owner",
        repo_name="test-repo",
        pr_number=10,
        commit_sha="head_123",
        findings=[],
        github_service=mock_gh,
        force_publish=True,
    )

    assert result.status == "RECONCILED"
    assert result.review_id == 7777
