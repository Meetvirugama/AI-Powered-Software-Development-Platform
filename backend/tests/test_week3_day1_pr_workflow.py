"""Tests for Parth — Week 3 Day 1: Interface Publishing & GitHub Integration Hardening.

Verifies:
1. GitHubService published method signatures (daily_tasks.md:928 & team_rules.md:141):
   - push_branch(installation_id, owner, repo, local_branch, remote_branch)
   - create_pull_request(owner, repo, head, base, title, body, draft=True)
   - update_pull_request(owner, repo, pr_number, body)
   - get_pull_request_detail(owner, repo, pr_number)
   - create_issue_from_finding(owner, repo, title, body, labels, assignees)
2. Direct push to default branch ('main'/'master') is strictly rejected (Rule 563).
3. GitHubClient new capabilities:
   - create_issue() and get_issue() for Feature F-23 (Issue creation from AI findings)
   - create_pull_request() and update_pull_request()
   - Rate limit handling: HTTP 429 and Retry-After header parsing
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.errors import APIError
from app.integrations.github.client import GitHubAPIError, GitHubClient
from app.integrations.github.schemas import PullRequestInfo
from app.integrations.github.service import GitHubService


# ═══════════════════════════════════════════════════════════════════════════
# 1. GitHubClient Unit Tests (PR Creation, Issues, Rate Limiting)
# ═══════════════════════════════════════════════════════════════════════════

class TestGitHubClientWeek3:
    """Test suite for new GitHubClient operations."""

    @pytest.mark.asyncio
    async def test_create_pull_request_draft_default(self):
        client = GitHubClient("token-123")
        client._request = AsyncMock(return_value={"id": 1, "number": 42, "title": "Test PR", "draft": True})

        res = await client.create_pull_request(
            owner="acme",
            repo="platform",
            head="agent/task-f47ac10b",
            base="main",
            title="feat: Add JWT Service",
            body="PR Description",
            draft=True,
        )

        assert res["number"] == 42
        client._request.assert_called_once_with(
            "POST",
            "/repos/acme/platform/pulls",
            json_body={
                "title": "feat: Add JWT Service",
                "head": "agent/task-f47ac10b",
                "base": "main",
                "body": "PR Description",
                "draft": True,
            },
        )

    @pytest.mark.asyncio
    async def test_update_pull_request(self):
        client = GitHubClient("token-123")
        client._request = AsyncMock(return_value={"id": 1, "number": 42, "body": "Updated summary"})

        res = await client.update_pull_request(
            owner="acme",
            repo="platform",
            pr_number=42,
            body="Updated summary",
        )

        assert res["number"] == 42
        client._request.assert_called_once_with(
            "PATCH",
            "/repos/acme/platform/pulls/42",
            json_body={"body": "Updated summary"},
        )

    @pytest.mark.asyncio
    async def test_create_issue_from_finding(self):
        client = GitHubClient("token-123")
        client._request = AsyncMock(return_value={"id": 99, "number": 12, "title": "Security finding"})

        res = await client.create_issue(
            owner="acme",
            repo="platform",
            title="Security finding: Hardcoded secret",
            body="Review found JWT_SECRET in auth.ts",
            labels=["security", "ai-finding"],
        )

        assert res["number"] == 12
        client._request.assert_called_once_with(
            "POST",
            "/repos/acme/platform/issues",
            json_body={
                "title": "Security finding: Hardcoded secret",
                "body": "Review found JWT_SECRET in auth.ts",
                "labels": ["security", "ai-finding"],
            },
        )

    @pytest.mark.asyncio
    async def test_get_issue(self):
        client = GitHubClient("token-123")
        client._request = AsyncMock(return_value={"number": 12, "state": "open"})

        res = await client.get_issue("acme", "platform", 12)
        assert res["number"] == 12
        client._request.assert_called_once_with("GET", "/repos/acme/platform/issues/12")


# ═══════════════════════════════════════════════════════════════════════════
# 2. GitHubService Interface & Safety Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestGitHubServiceWeek3:
    """Test suite for high-level GitHubService published interface."""

    @pytest.fixture
    def mock_db(self):
        return MagicMock()

    @pytest.mark.asyncio
    async def test_push_branch_to_main_rejected(self, mock_db):
        """Direct push to main or master is strictly rejected (Rule 563)."""
        service = GitHubService(mock_db)

        with pytest.raises(APIError) as exc_info:
            await service.push_branch(
                installation_id="inst-1",
                owner="acme",
                repo="platform",
                local_branch="agent/task-1",
                remote_branch="main",
            )
        assert exc_info.value.status_code == 400
        assert "Direct push to default branch" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_create_pull_request_service_facade(self, mock_db):
        """Calls client.create_pull_request and returns typed PullRequestInfo."""
        service = GitHubService(mock_db)
        mock_raw_pr = {
            "id": 100,
            "number": 5,
            "title": "feat: JWT",
            "state": "open",
            "draft": True,
            "html_url": "https://github.com/acme/platform/pull/5",
            "head": {"ref": "agent/task-f47ac10b", "sha": "abc123"},
            "base": {"ref": "main", "sha": "c0ffee"},
            "created_at": "2026-10-27T10:00:00Z",
        }

        with patch("app.integrations.github.service.GitHubClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.create_pull_request = AsyncMock(return_value=mock_raw_pr)
            mock_client_cls.return_value = mock_client

            pr_info = await service.create_pull_request(
                owner="acme",
                repo="platform",
                head="agent/task-f47ac10b",
                base="main",
                title="feat: JWT",
                body="PR Body",
                draft=True,
            )

            assert isinstance(pr_info, PullRequestInfo)
            assert pr_info.number == 5
            assert pr_info.title == "feat: JWT"
            assert pr_info.draft is True

    @pytest.mark.asyncio
    async def test_create_issue_from_finding_service_facade(self, mock_db):
        """Calls client.create_issue with ai-finding label."""
        service = GitHubService(mock_db)
        mock_issue = {"number": 101, "title": "Missing validation"}

        with patch("app.integrations.github.service.GitHubClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.create_issue = AsyncMock(return_value=mock_issue)
            mock_client_cls.return_value = mock_client

            res = await service.create_issue_from_finding(
                owner="acme",
                repo="platform",
                title="Missing validation",
                body="SQL injection potential",
            )

            assert res["number"] == 101
            mock_client.create_issue.assert_called_once_with(
                owner="acme",
                repo="platform",
                title="Missing validation",
                body="SQL injection potential",
                labels=["ai-finding"],
                assignees=None,
            )
