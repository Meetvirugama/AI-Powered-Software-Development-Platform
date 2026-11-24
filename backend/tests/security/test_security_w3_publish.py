"""Week 3 Day 5 security tests: branch push and Draft PR publication.

Owner: Sukun (Security). See Docs/security/week3_threat_model.md, section 6 (Day 5) and B2.

What these tests prove:
1. The GitHub installation token never appears in git's argv or in the remote URL.
2. A failed push never returns the token (raw or base64) in the error message.
3. Protected branches (main, master, develop, ...) can never be pushed to, in any spelling.
4. Branch, owner and repo names cannot inject git options or extra refspecs.
5. Pre-push hooks from the workspace are not run, and pushes are never forced.
6. The platform only opens Draft PRs, never from a protected branch, with redacted text.
7. The tool API cannot push or open PRs, even when the caller claims approval (Day 3 policy).
"""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.errors import APIError
from app.integrations.github import service as service_module
from app.integrations.github.service import GitHubService
from app.services.task_execution_orchestrator import DEFAULT_COMMAND_ALLOWLIST

FAKE_TOKEN = "ghs_" + "PushTok3nValue000111222333444555666777"
FAKE_PAT = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
EXEC_TEMPLATES = DEFAULT_COMMAND_ALLOWLIST["execute_command"]


class _FakeProc:
    def __init__(self, returncode: int = 0, stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._stderr = stderr

    async def communicate(self):
        return b"", self._stderr

    def kill(self):
        pass


@pytest.fixture()
def gh(tmp_path: Path):
    service = GitHubService(MagicMock(), workspace_root=tmp_path / "gh_root")
    service._resolve_token = AsyncMock(return_value=FAKE_TOKEN)  # type: ignore[method-assign]
    workspace = tmp_path / "task_ws"
    workspace.mkdir()
    return service, workspace


async def _push(service, workspace, **overrides):
    kwargs = {
        "installation_id": "inst-1",
        "owner": "alice",
        "repo": "payments",
        "local_branch": "agent/task-1234abcd",
        "remote_branch": "agent/task-1234abcd",
        "workspace_path": str(workspace),
    }
    kwargs.update(overrides)
    return await service.push_branch(**kwargs)


# ---------------------------------------------------------------------------
# 1. Token never in argv / URL
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_push_keeps_token_out_of_argv_and_url(gh):
    service, workspace = gh
    fake_exec = AsyncMock(return_value=_FakeProc(0))
    with patch.object(service_module.asyncio, "create_subprocess_exec", fake_exec):
        await _push(service, workspace)

    assert fake_exec.await_count == 1
    args = fake_exec.await_args.args
    kwargs = fake_exec.await_args.kwargs
    argv = " ".join(str(a) for a in args)

    encoded = base64.b64encode(f"x-access-token:{FAKE_TOKEN}".encode()).decode()
    assert FAKE_TOKEN not in argv
    assert encoded not in argv
    assert "x-access-token" not in argv
    assert "@github.com" not in argv, "credentials must not be embedded in the remote URL"
    assert "https://github.com/alice/payments.git" in args

    # Token is handed to git through the process environment only.
    env = kwargs.get("env") or {}
    assert any(encoded in str(v) for v in env.values())
    assert env.get("GIT_TERMINAL_PROMPT") == "0"


@pytest.mark.asyncio
async def test_push_skips_hooks_and_never_forces(gh):
    service, workspace = gh
    fake_exec = AsyncMock(return_value=_FakeProc(0))
    with patch.object(service_module.asyncio, "create_subprocess_exec", fake_exec):
        await _push(service, workspace)

    args = [str(a) for a in fake_exec.await_args.args]
    assert "--no-verify" in args
    assert "--force" not in args and "-f" not in args
    assert not any(a.startswith("+") for a in args), "force refspec ('+branch') used"
    assert args[-1] == "agent/task-1234abcd:refs/heads/agent/task-1234abcd"


# ---------------------------------------------------------------------------
# 2. Errors never leak the token
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_push_failure_error_is_redacted(gh):
    service, workspace = gh
    encoded = base64.b64encode(f"x-access-token:{FAKE_TOKEN}".encode()).decode()
    stderr = (
        f"fatal: unable to access 'https://x-access-token:{FAKE_TOKEN}@github.com/alice/payments.git/': 403\n"
        f"trace: header AUTHORIZATION: basic {encoded}\n"
        f"remote: invalid credentials {FAKE_PAT}\n"
    ).encode()
    fake_exec = AsyncMock(return_value=_FakeProc(128, stderr))

    with patch.object(service_module.asyncio, "create_subprocess_exec", fake_exec):
        with pytest.raises(APIError) as exc_info:
            await _push(service, workspace)

    message = str(exc_info.value) + str(getattr(exc_info.value, "message", ""))
    assert FAKE_TOKEN not in message
    assert encoded not in message
    assert FAKE_PAT not in message
    assert exc_info.value.status_code == 502


# ---------------------------------------------------------------------------
# 3. Protected branches and injection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "remote_branch",
    ["main", "master", "MAIN", " main ", "refs/heads/main", "develop", "production", "release", "staging"],
)
async def test_push_to_protected_branch_is_refused(gh, remote_branch):
    service, workspace = gh
    fake_exec = AsyncMock(return_value=_FakeProc(0))
    with patch.object(service_module.asyncio, "create_subprocess_exec", fake_exec):
        with pytest.raises(APIError) as exc_info:
            await _push(service, workspace, remote_branch=remote_branch)
    assert exc_info.value.status_code == 400
    fake_exec.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("remote_branch", "--receive-pack=touch /tmp/pwned"),
        ("remote_branch", "-f"),
        ("remote_branch", "+agent/task-1"),
        ("remote_branch", "agent/task-1:refs/heads/main"),
        ("remote_branch", "agent/../main"),
        ("remote_branch", "agent/task 1"),
        ("remote_branch", "agent/task;rm -rf /"),
        ("remote_branch", "agent/task-1.lock"),
        ("remote_branch", "agent/@{-1}"),
        ("local_branch", "--upload-pack=evil"),
        ("local_branch", "+HEAD"),
        ("local_branch", "HEAD:refs/heads/main agent"),
        ("owner", "evil.example/x"),
        ("owner", "-oops"),
        ("repo", "payments.git --mirror"),
        ("repo", "../other"),
    ],
)
async def test_push_rejects_injected_names(gh, field, value):
    service, workspace = gh
    fake_exec = AsyncMock(return_value=_FakeProc(0))
    with patch.object(service_module.asyncio, "create_subprocess_exec", fake_exec):
        with pytest.raises(APIError) as exc_info:
            await _push(service, workspace, **{field: value})
    assert exc_info.value.status_code == 400
    fake_exec.assert_not_awaited()


@pytest.mark.asyncio
async def test_push_rejects_missing_workspace(gh, tmp_path):
    service, _workspace = gh
    with pytest.raises(APIError) as exc_info:
        await _push(service, tmp_path / "does-not-exist")
    assert exc_info.value.status_code == 400
    assert str(tmp_path) not in str(exc_info.value), "server paths must not leak in errors"


# ---------------------------------------------------------------------------
# 4. Draft PRs only
# ---------------------------------------------------------------------------

_RAW_PR = {
    "id": 900,
    "number": 9,
    "title": "feat: discount",
    "state": "open",
    "draft": True,
    "html_url": "https://github.com/alice/payments/pull/9",
    "head": {"ref": "agent/task-1234abcd", "sha": "abc1234"},
    "base": {"ref": "main", "sha": "def5678"},
    "created_at": "2026-11-02T10:00:00Z",
}


def _pr_client():
    client = MagicMock()
    client.create_pull_request = AsyncMock(return_value=dict(_RAW_PR))
    client.merge_pull_request = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_pull_requests_are_always_drafts_and_redacted(gh):
    service, _ = gh
    client = _pr_client()
    with patch.object(service_module, "GitHubClient", return_value=client):
        info = await service.create_pull_request(
            owner="alice",
            repo="payments",
            head="agent/task-1234abcd",
            base="main",
            title=f"feat: discount {FAKE_PAT}",
            body=f"Summary\n\nDebug token: {FAKE_PAT}\npassword = 'hunter2-hunter2'",
        )

    kwargs = client.create_pull_request.await_args.kwargs
    assert kwargs["draft"] is True
    assert FAKE_PAT not in kwargs["title"]
    assert FAKE_PAT not in kwargs["body"]
    assert "hunter2-hunter2" not in kwargs["body"]
    assert info.draft is True
    client.merge_pull_request.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"draft": False},
        {"head": "main"},
        {"head": "refs/heads/master"},
        {"head": "main", "base": "main"},
        {"head": "agent/task-1", "base": "agent/task-1"},
        {"head": "--force"},
        {"base": "main;rm -rf /"},
        {"owner": "evil.example/x"},
    ],
)
async def test_pull_request_refuses_unsafe_requests(gh, overrides):
    service, _ = gh
    client = _pr_client()
    params = {
        "owner": "alice",
        "repo": "payments",
        "head": "agent/task-1234abcd",
        "base": "main",
        "title": "feat",
        "body": "body",
    }
    params.update(overrides)
    with patch.object(service_module, "GitHubClient", return_value=client):
        with pytest.raises(APIError) as exc_info:
            await service.create_pull_request(**params)
    assert exc_info.value.status_code == 400
    client.create_pull_request.assert_not_called()


def test_github_service_has_no_merge_entry_point():
    """Team rule: the platform never merges. Only humans merge Draft PRs on GitHub."""
    public = {name for name in dir(GitHubService) if not name.startswith("_")}
    assert not any("merge" in name.lower() for name in public), sorted(n for n in public if "merge" in n)


# ---------------------------------------------------------------------------
# 5. Tool API cannot publish (relies on the Day 3 tool policy)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "tool,args",
    [
        ("push_task_branch", {"branch_name": "agent/task-1", "publication_authorized": True}),
        ("push_task_branch", {"branch_name": "agent/task-1", "remote_url": "--receive-pack=touch /tmp/x"}),
        ("create_draft_pr", {"title": "x", "head_branch": "agent/task-1", "publication_authorized": True}),
        ("commit_task_changes", {"message": "x", "publication_authorized": True}),
        ("execute_command", {"command": "git", "arguments": ["push", "origin", "HEAD:main"]}),
        ("execute_command", {"command": "git", "arguments": ["remote", "set-url", "origin", "https://evil.example"]}),
    ],
)
def test_tool_api_cannot_publish(tool, args):
    # Needs the Day 3 tool policy (PR #168); skipped until that is merged.
    policy = pytest.importorskip("app.core.tool_api_policy")
    assert policy.api_tool_policy_violation(tool, args, EXEC_TEMPLATES) is not None
