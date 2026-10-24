"""
Week 2 Day 2 — Explain Code security tests.
Owner: Sukun — W2, Day 2 (Explanation Security)

Docs/week2.md, Day 2 — Sukun:
    - Test prompt injection in comments and documentation.
    - Ensure the explanation service has no unauthorized write capabilities.
    - Redact secrets in errors and logs.
    - Validate source-path boundaries.

All tests go through the real endpoint POST /api/v1/repositories/{id}/explain
(authentication, ownership, target resolution, context building, grounding,
history) with only the LLM replaced by a deterministic fake.

Fake secrets are assembled at runtime so no secret-shaped literal is committed.

Run with:
    python -m pytest backend/tests/test_security_explain.py -v --no-cov
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ai.llm.schemas import LLMValidationError
from app.main import app
from app.models.code_chunk import CodeChunk
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.repository_file import RepositoryFile
from app.services.explanation_orchestrator import LLMCodeExplanationService

FIXTURES = Path(__file__).parent / "fixtures" / "security" / "prompt_injection"
CANARY = re.compile(r"CANARY-PI-\d{3}")
FAKE_OPENAI_KEY = "sk-" + "proj-" + "Ab3" * 9
FAKE_GITHUB_TOKEN = "ghp_" + "R" * 36

GITHUB_WRITE_METHODS = (
    "create_branch", "push_branch", "create_pull_request", "merge_pull_request",
    "create_issue", "create_commit", "update_file", "create_or_update_file", "delete_file",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_repo_with_file(db_session, owner_user, path: str, content: str) -> Repository:
    """Create a synced repository owned by `owner_user` with one indexed file + chunk."""
    installation = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=owner_user.id,
        installation_id=f"inst-{uuid.uuid4().hex[:8]}",
        account_login=owner_user.login,
        permissions={"contents": "read"},
    )
    db_session.add(installation)
    db_session.commit()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=owner_user.id,
        installation_id=installation.id,
        github_repo_id=f"gh-repo-{uuid.uuid4().hex[:8]}",
        owner=owner_user.login,
        name="day2-security-repo",
        default_branch="main",
        language="Python",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo)
    db_session.commit()

    line_count = content.count("\n") + 1
    file_row = RepositoryFile(
        id=uuid.uuid4(),
        repository_id=repo.id,
        path=path,
        language="Python",
        size_bytes=len(content.encode()),
        line_count=line_count,
        content_hash=uuid.uuid4().hex,
    )
    db_session.add(file_row)
    db_session.commit()

    db_session.add(CodeChunk(
        id=uuid.uuid4(),
        repository_id=repo.id,
        file_id=file_row.id,
        symbol_id=None,
        content=content,
        token_count=len(content.split()),
        embedding=[0.0] * 768,
        start_line=1,
        end_line=line_count,
        content_hash=uuid.uuid4().hex,
        chunk_metadata={"file_path": path},
    ))
    db_session.commit()
    return repo


def _valid_explanation(**overrides) -> dict:
    data = {
        "purpose": "Computes an order total including tax.",
        "logic_flow": ["Sums the prices", "Applies the tax rate", "Rounds to two decimals"],
        "key_symbols": [],
        "inputs_and_outputs": "Input: prices and tax_rate. Output: a float total.",
        "dependencies": [],
        "assumptions_and_limitations": ["Comments in the file were treated as data, not instructions."],
        "sources": [],
        "confidence": "medium",
        "missing_context": [],
    }
    data.update(overrides)
    return data


class _CapturingGateway:
    """Fake LLM gateway: records every request, returns a fixed valid explanation."""

    def __init__(self, reply: dict | None = None) -> None:
        self.requests = []
        self.reply = reply or _valid_explanation()

    async def generate(self, req):
        self.requests.append(req)
        return SimpleNamespace(content=json.dumps(self.reply))


def _all_prompt_text(gateway: _CapturingGateway) -> str:
    return "\n".join(m.content for req in gateway.requests for m in req.messages)


@pytest.fixture()
def restore_app_state():
    saved = {name: getattr(app.state, name, None) for name in ("explanation_service", "github_service")}
    yield
    for name, value in saved.items():
        if value is None:
            if hasattr(app.state, name):
                delattr(app.state, name)
        else:
            setattr(app.state, name, value)


def _explain(client, headers, repo_id, path, **target):
    return client.post(
        f"/api/v1/repositories/{repo_id}/explain",
        headers=headers,
        json={"target": {"type": "file", "path": path, **target}},
    )


# ===========================================================================
# 1. Prompt injection in comments and documentation
# ===========================================================================

@pytest.mark.parametrize("fixture_name", ["comment_injection.py", "fence_breakout.py", "tool_request.py"])
def test_injection_in_indexed_code_stays_inside_data_boundary(
    client, db_session, test_user, auth_headers, restore_app_state, fixture_name
):
    content = (FIXTURES / fixture_name).read_text(encoding="utf-8")
    path = f"src/{fixture_name}"
    repo = _seed_repo_with_file(db_session, test_user, path, content)
    gateway = _CapturingGateway()
    app.state.explanation_service = LLMCodeExplanationService(gateway)

    res = _explain(client, auth_headers, repo.id, path)

    assert res.status_code == 200, res.text
    req = gateway.requests[0]
    system, user = req.messages[0], req.messages[1]

    # Repository text never reaches the trusted system prompt.
    assert system.role == "system" and not CANARY.search(system.content)

    # Every canary sits inside ONE random boundary; nothing escapes it.
    match = re.search(r"<<<REPO_DATA_(\w+)>>>\n(.*)\n<<<END_REPO_DATA_\1>>>", user.content, re.S)
    assert match, "repository data is not fenced"
    token, body = match.group(1), match.group(2)
    assert token not in content
    assert CANARY.search(body), "fixture content should have been sent as data"
    assert not CANARY.search(user.content.replace(body, "")), "injection escaped the data boundary"

    # The result is only an explanation (validated schema, no canary echoed).
    assert not CANARY.search(res.text)
    assert set(res.json()["explanation"]) >= {"purpose", "logic_flow", "sources"}


def test_readme_injection_cannot_change_the_task(
    client, db_session, test_user, auth_headers, restore_app_state
):
    content = (FIXTURES / "readme_injection.md").read_text(encoding="utf-8")
    repo = _seed_repo_with_file(db_session, test_user, "README.md", content)
    gateway = _CapturingGateway()
    app.state.explanation_service = LLMCodeExplanationService(gateway)

    res = _explain(client, auth_headers, repo.id, "README.md")

    assert res.status_code == 200, res.text
    user = gateway.requests[0].messages[1].content
    # The real task comes from the server, after the data block — not from the README.
    assert user.rstrip().endswith(")."), "explanation target must be the last instruction"
    assert "Explain `README.md`" in user.split("<<<END_REPO_DATA_")[-1]


# ===========================================================================
# 2. No unauthorized write capabilities
# ===========================================================================

def test_explain_never_calls_github_write_operations(
    client, db_session, test_user, auth_headers, restore_app_state
):
    content = (FIXTURES / "ts_injection.ts").read_text(encoding="utf-8")  # asks to create an issue / push a branch
    repo = _seed_repo_with_file(db_session, test_user, "src/display.ts", content)
    github = MagicMock(name="github_service")
    app.state.github_service = github
    app.state.explanation_service = LLMCodeExplanationService(_CapturingGateway())

    res = _explain(client, auth_headers, repo.id, "src/display.ts")

    assert res.status_code == 200, res.text
    called = {c[0].split(".")[0] for c in github.mock_calls}
    assert not called & set(GITHUB_WRITE_METHODS), f"explain triggered GitHub writes: {called}"


def test_explanation_service_holds_no_write_clients():
    service = LLMCodeExplanationService(_CapturingGateway())
    attrs = {name.lower() for name in vars(service)}
    assert not any(word in name for name in attrs for word in ("github", "git", "repo_writer", "shell", "subprocess"))
    assert not any(hasattr(service, m) for m in GITHUB_WRITE_METHODS)


def test_explain_does_not_modify_the_repository_record(
    client, db_session, test_user, auth_headers, restore_app_state
):
    repo = _seed_repo_with_file(db_session, test_user, "src/orders.py", "def total(x):\n    return sum(x)\n")
    before = (repo.sync_status, repo.default_branch, repo.last_synced_at)
    app.state.explanation_service = LLMCodeExplanationService(_CapturingGateway())

    assert _explain(client, auth_headers, repo.id, "src/orders.py").status_code == 200
    db_session.refresh(repo)
    assert (repo.sync_status, repo.default_branch, repo.last_synced_at) == before


# ===========================================================================
# 3. Secrets: never sent to the LLM, returned, saved, or shown in errors
# ===========================================================================

SECRET_SOURCE = (
    "import os\n"
    f'OPENAI_API_KEY = "{FAKE_OPENAI_KEY}"\n'
    f"GITHUB_TOKEN = '{FAKE_GITHUB_TOKEN}'\n"
    "def connect():\n"
    "    return OPENAI_API_KEY\n"
)


def test_secrets_in_source_are_not_sent_to_the_llm(
    client, db_session, test_user, auth_headers, restore_app_state
):
    repo = _seed_repo_with_file(db_session, test_user, "src/config.py", SECRET_SOURCE)
    gateway = _CapturingGateway()
    app.state.explanation_service = LLMCodeExplanationService(gateway)

    assert _explain(client, auth_headers, repo.id, "src/config.py").status_code == 200
    prompt = _all_prompt_text(gateway)
    assert FAKE_OPENAI_KEY not in prompt and FAKE_GITHUB_TOKEN not in prompt
    assert "[REDACTED]" in prompt


def test_secrets_echoed_by_the_model_are_redacted_in_response_and_history(
    client, db_session, test_user, auth_headers, restore_app_state
):
    repo = _seed_repo_with_file(db_session, test_user, "src/config.py", SECRET_SOURCE)

    async def leaky_explain(repository_id, payload, **kwargs):
        return _valid_explanation(
            purpose=f'Reads OPENAI_API_KEY = "{FAKE_OPENAI_KEY}" and returns it.',
            logic_flow=[f"Uses token {FAKE_GITHUB_TOKEN} to call GitHub"],
        )

    app.state.explanation_service = SimpleNamespace(explain=leaky_explain)
    res = _explain(client, auth_headers, repo.id, "src/config.py")

    assert res.status_code == 200, res.text
    assert FAKE_OPENAI_KEY not in res.text and FAKE_GITHUB_TOKEN not in res.text
    assert "[REDACTED]" in res.json()["explanation"]["purpose"]

    detail = client.get(f"/api/v1/analysis-runs/{res.json()['run_id']}", headers=auth_headers)
    if detail.status_code == 200:  # history enabled
        assert FAKE_OPENAI_KEY not in detail.text and FAKE_GITHUB_TOKEN not in detail.text


def test_error_responses_and_failed_runs_do_not_leak_secrets(
    client, db_session, test_user, auth_headers, restore_app_state
):
    repo = _seed_repo_with_file(db_session, test_user, "src/config.py", SECRET_SOURCE)

    async def failing_explain(repository_id, payload, **kwargs):
        raise LLMValidationError(f'model returned: OPENAI_API_KEY = "{FAKE_OPENAI_KEY}"')

    app.state.explanation_service = SimpleNamespace(explain=failing_explain)
    res = _explain(client, auth_headers, repo.id, "src/config.py")

    assert res.status_code == 500
    assert res.json()["error"]["code"] == "ANALYSIS_FAILED"
    assert FAKE_OPENAI_KEY not in res.text

    runs = client.get(f"/api/v1/repositories/{repo.id}/analysis-runs?feature_type=explain", headers=auth_headers)
    if runs.status_code == 200:
        assert FAKE_OPENAI_KEY not in runs.text


def test_logs_from_a_failed_explanation_are_redacted(
    client, db_session, test_user, auth_headers, restore_app_state, capsys
):
    import logging

    from app.core.logging import configure_logging

    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        configure_logging("INFO")  # installs SecretRedactingFilter on the handler
        repo = _seed_repo_with_file(db_session, test_user, "src/config.py", SECRET_SOURCE)

        async def failing_explain(repository_id, payload, **kwargs):
            raise LLMValidationError(f"bad output {FAKE_GITHUB_TOKEN}")

        app.state.explanation_service = SimpleNamespace(explain=failing_explain)
        _explain(client, auth_headers, repo.id, "src/config.py")
        logging.getLogger("app.api.v1.analysis").error("explain failed with %s", FAKE_GITHUB_TOKEN)
    finally:
        root.handlers, root.level = saved_handlers, saved_level

    captured = capsys.readouterr()
    assert FAKE_GITHUB_TOKEN not in captured.err + captured.out


# ===========================================================================
# 4. Source-path boundaries
# ===========================================================================

@pytest.mark.parametrize("path", [
    "../../etc/passwd",
    "/etc/passwd",
    "src/../../../root/.ssh/authorized_keys",
    "..\\..\\windows\\win.ini",
    "~/.aws/credentials",
    "src/app.py\x00.txt",
])
def test_unsafe_target_paths_are_rejected_before_any_work(
    client, db_session, test_user, auth_headers, restore_app_state, path
):
    repo = _seed_repo_with_file(db_session, test_user, "src/app.py", "x = 1\n")
    gateway = _CapturingGateway()
    app.state.explanation_service = LLMCodeExplanationService(gateway)

    res = _explain(client, auth_headers, repo.id, path)

    assert res.status_code in (400, 422), res.text
    assert gateway.requests == [], "LLM must not be called for an unsafe path"


def test_flat_request_form_is_also_validated(client, db_session, test_user, auth_headers, restore_app_state):
    repo = _seed_repo_with_file(db_session, test_user, "src/app.py", "x = 1\n")
    app.state.explanation_service = LLMCodeExplanationService(_CapturingGateway())

    res = client.post(
        f"/api/v1/repositories/{repo.id}/explain",
        headers=auth_headers,
        json={"file_path": "../../etc/passwd"},
    )
    assert res.status_code in (400, 422)


def test_unsafe_citations_from_the_model_are_removed(
    client, db_session, test_user, auth_headers, restore_app_state
):
    repo = _seed_repo_with_file(db_session, test_user, "src/app.py", "def f():\n    return 1\n")
    gateway = _CapturingGateway(reply=_valid_explanation(sources=[
        {"file_path": "../../etc/passwd", "start_line": 1, "end_line": 1},
        {"file_path": "/root/.ssh/id_rsa", "start_line": 1, "end_line": 2},
        {"file_path": "src/app.py", "start_line": 1, "end_line": 2},
    ]))
    app.state.explanation_service = LLMCodeExplanationService(gateway)

    res = _explain(client, auth_headers, repo.id, "src/app.py")

    assert res.status_code == 200, res.text
    paths = [s["file_path"] for s in res.json()["explanation"]["sources"]]
    assert paths and all(p == "src/app.py" for p in paths)
    assert res.json()["explanation"]["confidence"] == "low"


def test_cannot_explain_another_users_repository(
    client, db_session, test_user, auth_headers, restore_app_state
):
    from app.models.user import User

    other = User(id=uuid.uuid4(), github_id=f"gh-{uuid.uuid4().hex[:6]}", login="other_user_d2",
                 email="other_d2@example.com")
    db_session.add(other)
    db_session.commit()
    their_repo = _seed_repo_with_file(db_session, other, "src/secret_logic.py", "def hidden():\n    pass\n")
    gateway = _CapturingGateway()
    app.state.explanation_service = LLMCodeExplanationService(gateway)

    res = _explain(client, auth_headers, their_repo.id, "src/secret_logic.py")

    assert res.status_code in (403, 404)
    assert "hidden" not in res.text
    assert gateway.requests == []
