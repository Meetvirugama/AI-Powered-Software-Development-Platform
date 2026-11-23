"""
Week 2 Day 6 — Cross-feature security audit tests.
Owner: Sukun — W2, Day 6 (Security Audit)

Docs/week2.md, Day 6 — Sukun. Runs the same abuse cases against ALL FOUR
analysis features (Explain, Find Bugs, Generate Tests, Code Review):

    - Unauthorized repository access        -> 403/404, service never called
    - Path traversal on the target          -> 400/422, service never called
    - Oversized inputs / bounded processing -> 413 / 422, service never called
    - Malformed model output                -> 500 ANALYSIS_FAILED (never a fake success)
    - Cross-repository / cross-user history -> another user's run is not readable
    - Secret exposure in prompts            -> the shared prompt fence redacts secrets
                                               (covers repository chat too)
    - Rate limits exist for every analysis endpoint

Feature-specific prompt-injection tests live in test_security_explain.py,
test_security_bugs.py, test_security_testgen.py and test_security_review.py.

Run with:
    python -m pytest backend/tests/test_security_week2_audit.py -v --no-cov
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.core.security import create_access_token
from app.main import app
from app.models.code_chunk import CodeChunk
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.repository_file import RepositoryFile
from app.models.user import User

TARGET_PATH = "src/pricing.py"
TARGET_CODE = "def apply_discount(price, percent):\n    return price * (1 - percent / 100)\n"

# (endpoint suffix, app.state attribute, service method name)
FEATURES = [
    ("explain", "explanation_service", "explain"),
    ("detect-bugs", "bug_detection_service", "detect_bugs"),
    ("generate-tests", "test_generation_service", "generate_tests"),
    ("review", "code_review_service", "review"),
]
FEATURE_IDS = [f[0] for f in FEATURES]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_repo(db_session, owner_user, *, size_override: int | None = None) -> Repository:
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
        name="day6-audit-repo",
        default_branch="main",
        language="Python",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo)
    db_session.commit()

    files = {
        "pyproject.toml": '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
        TARGET_PATH: TARGET_CODE,
    }
    for path, content in files.items():
        line_count = content.count("\n") + 1
        size = size_override if (size_override and path == TARGET_PATH) else len(content.encode())
        file_row = RepositoryFile(
            id=uuid.uuid4(),
            repository_id=repo.id,
            path=path,
            language="TOML" if path.endswith(".toml") else "Python",
            size_bytes=size,
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


class _SpyService:
    """Records calls; returns whatever `reply` is (used for malformed-output tests)."""

    def __init__(self, method: str, reply=None) -> None:
        self.calls = 0
        self.reply = reply if reply is not None else {"nonsense": True}

        async def _call(repository_id, payload, **kwargs):
            self.calls += 1
            return self.reply

        setattr(self, method, _call)


@pytest.fixture()
def restore_app_state():
    names = [f[1] for f in FEATURES]
    saved = {name: getattr(app.state, name, None) for name in names}
    yield
    for name, value in saved.items():
        if value is None:
            if hasattr(app.state, name):
                delattr(app.state, name)
        else:
            setattr(app.state, name, value)


@pytest.fixture()
def other_user(db_session):
    user = User(id=uuid.uuid4(), github_id=f"gh-{uuid.uuid4().hex[:6]}", login="audit_other_user",
                email="audit_other@example.com")
    db_session.add(user)
    db_session.commit()
    return user


def _post(client, headers, repo_id, endpoint, path=TARGET_PATH):
    return client.post(
        f"/api/v1/repositories/{repo_id}/{endpoint}",
        headers=headers,
        json={"target": {"type": "file", "path": path}},
    )


# ===========================================================================
# 1. Unauthorized / cross-repository access
# ===========================================================================

@pytest.mark.parametrize("endpoint, attr, method", FEATURES, ids=FEATURE_IDS)
def test_other_users_repository_is_denied_for_every_feature(
    client, db_session, test_user, auth_headers, restore_app_state, other_user, endpoint, attr, method
):
    their_repo = _seed_repo(db_session, other_user)
    spy = _SpyService(method)
    setattr(app.state, attr, spy)

    res = _post(client, auth_headers, their_repo.id, endpoint)

    assert res.status_code in (403, 404), f"{endpoint}: {res.status_code}"
    assert "apply_discount" not in res.text
    assert spy.calls == 0, f"{endpoint} called the AI service for another user's repository"


@pytest.mark.parametrize("endpoint, attr, method", FEATURES, ids=FEATURE_IDS)
def test_no_token_is_rejected_for_every_feature(client, db_session, test_user, restore_app_state,
                                                endpoint, attr, method):
    repo = _seed_repo(db_session, test_user)
    spy = _SpyService(method)
    setattr(app.state, attr, spy)

    res = _post(client, {}, repo.id, endpoint)

    assert res.status_code == 401
    assert spy.calls == 0


def test_another_users_analysis_run_cannot_be_read(
    client, db_session, test_user, auth_headers, restore_app_state, other_user
):
    """User B's explanation run must not be readable by User A, even with the run id."""
    their_repo = _seed_repo(db_session, other_user)
    other_headers = {"Authorization": f"Bearer {create_access_token(str(other_user.id))[0]}"}

    async def explain(repository_id, payload, **kwargs):
        return {
            "purpose": "Private explanation for user B.",
            "logic_flow": ["step"],
            "inputs_and_outputs": "n/a",
            "confidence": "medium",
        }

    app.state.explanation_service = SimpleNamespace(explain=explain)
    created = _post(client, other_headers, their_repo.id, "explain")
    assert created.status_code == 200, created.text
    run_id = created.json()["run_id"]

    stolen = client.get(f"/api/v1/analysis-runs/{run_id}", headers=auth_headers)
    assert stolen.status_code in (403, 404)
    assert "Private explanation" not in stolen.text

    listing = client.get(f"/api/v1/repositories/{their_repo.id}/analysis-runs", headers=auth_headers)
    assert listing.status_code in (403, 404)


# ===========================================================================
# 2. Path traversal on every feature
# ===========================================================================

@pytest.mark.parametrize("endpoint, attr, method", FEATURES, ids=FEATURE_IDS)
@pytest.mark.parametrize("path", ["../../etc/passwd", "/etc/passwd", "src/../../../root/.ssh/id_rsa"])
def test_path_traversal_is_rejected_for_every_feature(
    client, db_session, test_user, auth_headers, restore_app_state, endpoint, attr, method, path
):
    repo = _seed_repo(db_session, test_user)
    spy = _SpyService(method)
    setattr(app.state, attr, spy)

    res = _post(client, auth_headers, repo.id, endpoint, path=path)

    assert res.status_code in (400, 422), f"{endpoint}: {res.status_code} {res.text}"
    assert spy.calls == 0


# ===========================================================================
# 3. Oversized input and bounded processing
# ===========================================================================

@pytest.mark.parametrize("endpoint, attr, method", FEATURES, ids=FEATURE_IDS)
def test_oversized_target_file_is_rejected_for_every_feature(
    client, db_session, test_user, auth_headers, restore_app_state, endpoint, attr, method
):
    repo = _seed_repo(db_session, test_user, size_override=5 * 1024 * 1024)  # 5 MB indexed file
    spy = _SpyService(method)
    setattr(app.state, attr, spy)

    res = _post(client, auth_headers, repo.id, endpoint)

    assert res.status_code in (400, 413, 422), f"{endpoint}: {res.status_code}"
    assert spy.calls == 0, f"{endpoint} sent an oversized file to the AI"


@pytest.mark.parametrize("bad_options", [
    {"max_context_tokens": 10_000_000},
    {"max_context_tokens": 1},
])
def test_context_budget_is_bounded(client, db_session, test_user, auth_headers, restore_app_state, bad_options):
    repo = _seed_repo(db_session, test_user)
    spy = _SpyService("explain")
    app.state.explanation_service = spy

    res = client.post(
        f"/api/v1/repositories/{repo.id}/explain",
        headers=auth_headers,
        json={"target": {"type": "file", "path": TARGET_PATH}, "options": bad_options},
    )
    assert res.status_code in (400, 422)
    assert spy.calls == 0


def test_oversized_review_diff_is_rejected(client, db_session, test_user, auth_headers, restore_app_state):
    from app.schemas import analysis as schemas

    limit = getattr(schemas, "MAX_DIFF_CHARS", 500_000)
    repo = _seed_repo(db_session, test_user)
    spy = _SpyService("review")
    app.state.code_review_service = spy
    huge = f"--- a/{TARGET_PATH}\n+++ b/{TARGET_PATH}\n@@ -1,1 +1,2 @@\n x\n+" + ("y" * (limit + 10)) + "\n"

    res = client.post(
        f"/api/v1/repositories/{repo.id}/review",
        headers=auth_headers,
        json={"target": {"type": "diff", "diff": huge}},
    )
    assert res.status_code in (400, 413, 422)
    assert spy.calls == 0


def test_history_page_size_is_bounded(client, db_session, test_user, auth_headers):
    repo = _seed_repo(db_session, test_user)
    res = client.get(f"/api/v1/repositories/{repo.id}/analysis-runs?page_size=100000", headers=auth_headers)
    assert res.status_code in (400, 422)


# ===========================================================================
# 4. Malformed model output never becomes a successful result
# ===========================================================================

@pytest.mark.parametrize("endpoint, attr, method", FEATURES, ids=FEATURE_IDS)
@pytest.mark.parametrize("garbage", [{"nonsense": True}, "not even json", 12345], ids=["dict", "str", "int"])
def test_malformed_service_output_fails_explicitly(
    client, db_session, test_user, auth_headers, restore_app_state, endpoint, attr, method, garbage
):
    repo = _seed_repo(db_session, test_user)
    setattr(app.state, attr, _SpyService(method, reply=garbage))

    res = _post(client, auth_headers, repo.id, endpoint)

    assert res.status_code >= 500, f"{endpoint} turned malformed output into {res.status_code}"
    assert res.json()["error"]["code"] in ("ANALYSIS_FAILED", "INTERNAL_SERVER_ERROR")


# ===========================================================================
# 5. Secret exposure — shared prompt fence (covers repository chat as well)
# ===========================================================================

FAKE_OPENAI_KEY = "sk-" + "proj-" + "Au6" * 9
FAKE_GITHUB_TOKEN = "ghp_" + "A" * 36


def test_shared_fence_redacts_secrets():
    from ai.schemas.prompt_builder import _fence

    fenced = _fence(f'OPENAI_API_KEY = "{FAKE_OPENAI_KEY}"\nTOKEN={FAKE_GITHUB_TOKEN}\n')
    assert FAKE_OPENAI_KEY not in fenced and FAKE_GITHUB_TOKEN not in fenced
    assert "[REDACTED]" in fenced


def test_repository_chat_prompt_does_not_carry_secrets():
    """Week 1 repository chat builds its prompt with PromptBuilder — it must not leak keys."""
    from ai.schemas.prompt_builder import PromptBuilder

    builder = PromptBuilder()
    chat = builder.build_chat_prompt(
        context=f'--- config.py (lines 1–2) ---\nAPI_KEY = "{FAKE_OPENAI_KEY}"\n',
        question="Where is the API key configured?",
    )
    summary = builder.build_summary_prompt(
        file_path="config.py", start_line=1, end_line=1,
        code_content=f"GITHUB_TOKEN = '{FAKE_GITHUB_TOKEN}'",
    )
    text = "\n".join(m.content for m in [*chat, *summary])
    assert FAKE_OPENAI_KEY not in text and FAKE_GITHUB_TOKEN not in text
    assert "Where is the API key configured?" in text  # the user's question is untouched


# ===========================================================================
# 6. Rate limits cover every analysis endpoint
# ===========================================================================

@pytest.mark.parametrize("endpoint", ["explain", "detect-bugs", "generate-tests", "review", "chat", "sync"])
def test_every_expensive_endpoint_is_rate_limited(endpoint):
    from app.core.rate_limit import _rules

    path = f"/api/v1/repositories/{uuid.uuid4()}/{endpoint}"
    matching = [r for r in _rules("/api/v1") if "POST" in r.methods and r.path_pattern.match(path)]
    assert matching, f"POST {endpoint} has no rate limit"
    assert all(r.per == "user" and r.limit <= 60 for r in matching)
