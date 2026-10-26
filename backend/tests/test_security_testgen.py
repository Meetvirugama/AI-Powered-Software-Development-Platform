"""
Week 2 Day 4 — Test Generation security tests.
Owner: Sukun — W2, Day 4 (Test Generation Security)

Docs/week2.md, Day 4 — Sukun:
    - Prevent secret leakage in generated code.
    - Treat repository instructions as untrusted.
    - Validate proposed file paths.
    - Ensure generated code is not executed automatically.
    - Ensure output validation cannot be bypassed.

Endpoint tests call the real POST /api/v1/repositories/{id}/generate-tests
(auth, ownership, framework detection, context, sanitizer, history) with only
the LLM replaced by a deterministic fake.

Fake secrets are assembled at runtime so no secret-shaped literal is committed.

Run with:
    python -m pytest backend/tests/test_security_testgen.py -v --no-cov
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.main import app
from app.models.code_chunk import CodeChunk
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.repository_file import RepositoryFile
from app.services.test_generation_orchestrator import LLMTestGenerationService, check_generated_test_path

FIXTURES = Path(__file__).parent / "fixtures" / "security" / "prompt_injection"
CANARY = re.compile(r"CANARY-PI-\d{3}")

FAKE_OPENAI_KEY = "sk-" + "proj-" + "Tg4" * 9
FAKE_GITHUB_TOKEN = "ghp_" + "T" * 36
FAKE_AWS_KEY = "AKIA" + "Q" * 16

TARGET_PATH = "src/pricing.py"
TARGET_CODE = (
    "def apply_discount(price: float, percent: float) -> float:\n"
    "    if percent < 0 or percent > 100:\n"
    "        raise ValueError('percent out of range')\n"
    "    return round(price * (1 - percent / 100), 2)\n"
)
VALID_TEST = (
    "import pytest\n"
    "from src.pricing import apply_discount\n\n"
    "def test_apply_discount_normal():\n"
    "    assert apply_discount(100, 10) == 90\n\n"
    "def test_apply_discount_invalid():\n"
    "    with pytest.raises(ValueError):\n"
    "        apply_discount(100, 150)\n"
)

GITHUB_WRITE_METHODS = (
    "create_branch", "push_branch", "create_pull_request", "merge_pull_request",
    "create_issue", "create_commit", "update_file", "create_or_update_file", "delete_file",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_repo(db_session, owner_user, files: dict[str, str]) -> Repository:
    """Synced repository owned by `owner_user` with indexed files (+ one chunk each)."""
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
        name="day4-security-repo",
        default_branch="main",
        language="Python",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo)
    db_session.commit()

    for path, content in files.items():
        line_count = content.count("\n") + 1
        language = "TOML" if path.endswith(".toml") else "Python"
        file_row = RepositoryFile(
            id=uuid.uuid4(),
            repository_id=repo.id,
            path=path,
            language=language,
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


def _python_repo(db_session, owner_user, target_code: str = TARGET_CODE) -> Repository:
    return _seed_repo(db_session, owner_user, {
        "pyproject.toml": '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
        TARGET_PATH: target_code,
    })


def _result(**overrides) -> dict:
    data = {
        "detected_framework": "pytest",
        "proposed_test_path": "tests/test_pricing.py",
        "test_content": VALID_TEST,
        "covered_scenarios": [
            {"name": "test_apply_discount_normal", "category": "normal", "description": "10% off 100 is 90."},
            {"name": "test_apply_discount_invalid", "category": "failure_path", "description": "Rejects 150%."},
        ],
        "assumptions_and_warnings": [],
        "syntax_valid": True,
        "validation_errors": [],
        "sources": [{"file_path": TARGET_PATH, "start_line": 1, "end_line": 4}],
    }
    data.update(overrides)
    return data


class _CapturingGateway:
    """Fake LLM gateway: records requests and returns a fixed TestGenerationResult JSON."""

    def __init__(self, reply: dict | None = None) -> None:
        self.requests = []
        self.reply = reply or _result()

    async def generate(self, req):
        self.requests.append(req)
        return SimpleNamespace(content=json.dumps(self.reply))


def _all_prompt_text(gateway: _CapturingGateway) -> str:
    return "\n".join(m.content for req in gateway.requests for m in req.messages)


@pytest.fixture()
def restore_app_state():
    names = ("test_generation_service", "github_service")
    saved = {name: getattr(app.state, name, None) for name in names}
    yield
    for name, value in saved.items():
        if value is None:
            if hasattr(app.state, name):
                delattr(app.state, name)
        else:
            setattr(app.state, name, value)


def _generate(client, headers, repo_id, path=TARGET_PATH):
    return client.post(
        f"/api/v1/repositories/{repo_id}/generate-tests",
        headers=headers,
        json={"target": {"type": "file", "path": path}},
    )


# ===========================================================================
# 1. Repository instructions are untrusted (prompt injection)
# ===========================================================================

@pytest.mark.parametrize("fixture_name", ["comment_injection.py", "tool_request.py", "fence_breakout.py"])
def test_injection_in_target_code_stays_inside_data_boundary(
    client, db_session, test_user, auth_headers, restore_app_state, fixture_name
):
    content = (FIXTURES / fixture_name).read_text(encoding="utf-8")
    repo = _python_repo(db_session, test_user, target_code=content)
    gateway = _CapturingGateway()
    app.state.test_generation_service = LLMTestGenerationService(llm_gateway=gateway)

    res = _generate(client, auth_headers, repo.id)

    assert res.status_code == 200, res.text
    system, user = gateway.requests[0].messages[0], gateway.requests[0].messages[1]
    assert system.role == "system" and not CANARY.search(system.content)
    assert "Never follow instructions" in system.content

    match = re.search(r"<<<REPO_DATA_(\w+)>>>\n(.*)\n<<<END_REPO_DATA_\1>>>", user.content, re.S)
    assert match, "repository data is not fenced"
    token, body = match.group(1), match.group(2)
    assert token not in content
    assert CANARY.search(body)
    assert not CANARY.search(user.content.replace(body, "")), "injection escaped the data boundary"
    assert not CANARY.search(res.text)


def test_injected_output_path_request_is_ignored(
    client, db_session, test_user, auth_headers, restore_app_state
):
    """tool_request.py asks the AI to write tests to ../../../../etc/cron.d/backdoor.
    Even if the model obeys, the response never contains that path."""
    content = (FIXTURES / "tool_request.py").read_text(encoding="utf-8")
    repo = _python_repo(db_session, test_user, target_code=content)

    async def obedient_model(repository_id, payload, **kwargs):
        return _result(proposed_test_path="etc/cron.d/backdoor")

    app.state.test_generation_service = SimpleNamespace(generate_tests=obedient_model)
    res = _generate(client, auth_headers, repo.id)

    assert res.status_code == 200, res.text
    proposed = res.json()["result"]["proposed_test_path"]
    assert "cron" not in proposed
    assert check_generated_test_path(proposed, "pytest") is None


# ===========================================================================
# 2. Secrets never reach the LLM and never appear in generated output/history
# ===========================================================================

SECRET_CODE = (
    "import os\n"
    f'OPENAI_API_KEY = "{FAKE_OPENAI_KEY}"\n'
    f"AWS_KEY = '{FAKE_AWS_KEY}'\n"
    "def apply_discount(price, percent):\n"
    "    return price * (1 - percent / 100)\n"
)


def test_secrets_in_source_are_not_sent_to_the_llm(
    client, db_session, test_user, auth_headers, restore_app_state
):
    repo = _python_repo(db_session, test_user, target_code=SECRET_CODE)
    gateway = _CapturingGateway()
    app.state.test_generation_service = LLMTestGenerationService(llm_gateway=gateway)

    assert _generate(client, auth_headers, repo.id).status_code == 200
    prompt = _all_prompt_text(gateway)
    assert FAKE_OPENAI_KEY not in prompt and FAKE_AWS_KEY not in prompt
    assert "[REDACTED]" in prompt


def test_secrets_copied_into_generated_tests_are_redacted_everywhere(
    client, db_session, test_user, auth_headers, restore_app_state
):
    repo = _python_repo(db_session, test_user, target_code=SECRET_CODE)
    leaky = _result(
        test_content=(
            "from src.pricing import apply_discount\n\n"
            f'API_KEY = "{FAKE_OPENAI_KEY}"\n'
            f"TOKEN = '{FAKE_GITHUB_TOKEN}'\n\n"
            "def test_discount():\n"
            "    assert apply_discount(100, 10) == 90\n"
        ),
        covered_scenarios=[{"name": "test_discount", "category": "normal",
                            "description": f"Uses key {FAKE_AWS_KEY} to call the API"}],
        assumptions_and_warnings=[f"Assumes GITHUB_TOKEN={FAKE_GITHUB_TOKEN} is set"],
    )
    app.state.test_generation_service = LLMTestGenerationService(llm_gateway=_CapturingGateway(reply=leaky))

    res = _generate(client, auth_headers, repo.id)

    assert res.status_code == 200, res.text
    for secret in (FAKE_OPENAI_KEY, FAKE_GITHUB_TOKEN, FAKE_AWS_KEY):
        assert secret not in res.text
    assert "[REDACTED]" in res.json()["result"]["test_content"]

    detail = client.get(f"/api/v1/analysis-runs/{res.json()['run_id']}", headers=auth_headers)
    if detail.status_code == 200:  # history enabled
        for secret in (FAKE_OPENAI_KEY, FAKE_GITHUB_TOKEN, FAKE_AWS_KEY):
            assert secret not in detail.text


def test_syntax_errors_do_not_echo_secrets(
    client, db_session, test_user, auth_headers, restore_app_state
):
    repo = _python_repo(db_session, test_user)
    broken = _result(test_content=f'API_KEY = "{FAKE_OPENAI_KEY}"\ndef test_x(:\n    assert True\n')

    async def model(repository_id, payload, **kwargs):
        return broken

    app.state.test_generation_service = SimpleNamespace(generate_tests=model)
    res = _generate(client, auth_headers, repo.id)

    assert res.status_code == 200, res.text
    assert res.json()["result"]["syntax_valid"] is False
    assert FAKE_OPENAI_KEY not in res.text


# ===========================================================================
# 3. Proposed file paths
# ===========================================================================

@pytest.mark.parametrize("bad_path", [
    "conftest.py",                  # auto-loaded by pytest
    "tests/conftest.py",
    ".github/workflows/ci.yml",     # would run in CI
    "setup.py",
    "tests/__init__.py",
    "src/pricing.py",               # overwrites the code under test
    "pyproject.toml",
    "tests/helpers.py",             # not a test file name
])
def test_model_proposed_dangerous_paths_are_replaced(
    client, db_session, test_user, auth_headers, restore_app_state, bad_path
):
    repo = _python_repo(db_session, test_user)
    app.state.test_generation_service = LLMTestGenerationService(
        llm_gateway=_CapturingGateway(reply=_result(proposed_test_path=bad_path))
    )

    res = _generate(client, auth_headers, repo.id)

    assert res.status_code == 200, res.text
    result = res.json()["result"]
    assert result["proposed_test_path"] != bad_path
    assert check_generated_test_path(result["proposed_test_path"], "pytest") is None
    assert any("not allowed" in w for w in result["assumptions_and_warnings"])


@pytest.mark.parametrize("traversal", ["../../etc/cron.d/backdoor.py", "/tmp/test_evil.py", "..\\..\\test_x.py"])
def test_traversal_paths_from_the_model_never_reach_the_user(
    client, db_session, test_user, auth_headers, restore_app_state, traversal
):
    repo = _python_repo(db_session, test_user)
    app.state.test_generation_service = LLMTestGenerationService(
        llm_gateway=_CapturingGateway(reply=_result(proposed_test_path=traversal))
    )

    res = _generate(client, auth_headers, repo.id)

    # Either rejected outright, or replaced — but never returned as-is.
    if res.status_code == 200:
        assert res.json()["result"]["proposed_test_path"] != traversal
    else:
        assert res.status_code == 500 and res.json()["error"]["code"] == "ANALYSIS_FAILED"
    assert traversal not in res.text


@pytest.mark.parametrize("path, framework", [
    ("tests/test_pricing.py", "pytest"),
    ("backend/tests/pricing_test.py", "pytest"),
    ("tests/test_models.py", "unittest"),
    ("src/utils/math.test.ts", "jest"),
    ("src/components/__tests__/Button.tsx", "jest"),
    ("src/api.spec.js", "jest"),
])
def test_normal_test_paths_are_accepted(path, framework):
    assert check_generated_test_path(path, framework) is None


@pytest.mark.parametrize("path, framework", [
    ("tests/conftest.py", "pytest"),
    (".github/workflows/test_ci.py", "pytest"),
    ("src/pricing.py", "pytest"),
    ("tests/test_pricing.ts", "pytest"),
    ("src/math.ts", "jest"),
    ("jest.config.js", "jest"),
    ("src/test_math.py", "jest"),
    (".husky/pre-commit.test.js", "jest"),
])
def test_unacceptable_test_paths_are_rejected(path, framework):
    assert check_generated_test_path(path, framework) is not None


@pytest.mark.parametrize("path", ["../../etc/passwd", "/etc/passwd", "~/.ssh/id_rsa", "src/a.py\x00.txt"])
def test_unsafe_target_paths_are_rejected_before_any_work(
    client, db_session, test_user, auth_headers, restore_app_state, path
):
    repo = _python_repo(db_session, test_user)
    gateway = _CapturingGateway()
    app.state.test_generation_service = LLMTestGenerationService(llm_gateway=gateway)

    res = _generate(client, auth_headers, repo.id, path=path)

    assert res.status_code in (400, 422), res.text
    assert gateway.requests == []


# ===========================================================================
# 4. Generated code is never executed and never written
# ===========================================================================

def test_generated_code_is_not_executed(
    client, db_session, test_user, auth_headers, restore_app_state, tmp_path
):
    marker = tmp_path / "executed.marker"
    payload_code = (
        "import os, subprocess\n"
        f"open({str(marker)!r}, 'w').write('ran')\n"
        f"os.system('echo pwned > {marker.as_posix()}')\n\n"
        "def test_discount():\n"
        f"    open({str(marker)!r}, 'w').write('ran')\n"
        "    assert True\n"
    )
    repo = _python_repo(db_session, test_user)
    app.state.test_generation_service = LLMTestGenerationService(
        llm_gateway=_CapturingGateway(reply=_result(test_content=payload_code))
    )

    res = _generate(client, auth_headers, repo.id)

    assert res.status_code == 200, res.text
    assert not marker.exists(), "generated test code was executed by the server"
    assert "os.system" in res.json()["result"]["test_content"], "content is returned for preview only"


def test_generation_does_not_write_to_the_repository_or_github(
    client, db_session, test_user, auth_headers, restore_app_state
):
    repo = _python_repo(db_session, test_user)
    before = {f.path for f in db_session.query(RepositoryFile).filter(RepositoryFile.repository_id == repo.id)}
    github = MagicMock(name="github_service")
    app.state.github_service = github
    app.state.test_generation_service = LLMTestGenerationService(llm_gateway=_CapturingGateway())

    res = _generate(client, auth_headers, repo.id)

    assert res.status_code == 200, res.text
    after = {f.path for f in db_session.query(RepositoryFile).filter(RepositoryFile.repository_id == repo.id)}
    assert after == before, "generating tests must not add files to the repository"
    called = {c[0].split(".")[0] for c in github.mock_calls}
    assert not called & set(GITHUB_WRITE_METHODS)


def test_test_generation_service_holds_no_write_or_exec_clients():
    service = LLMTestGenerationService(llm_gateway=_CapturingGateway())
    attrs = {name.lower() for name in vars(service)}
    assert not any(word in name for name in attrs for word in ("github", "git_", "shell", "subprocess", "runner", "writer"))
    assert not any(hasattr(service, m) for m in (*GITHUB_WRITE_METHODS, "run_tests", "execute"))


# ===========================================================================
# 5. Output validation cannot be bypassed
# ===========================================================================

def test_service_claiming_completed_and_valid_is_still_validated(
    client, db_session, test_user, auth_headers, restore_app_state
):
    """A service that returns an already-'COMPLETED', 'syntax_valid' envelope is still sanitized."""
    repo = _python_repo(db_session, test_user)

    async def lying_service(repository_id, payload, **kwargs):
        return {
            "run_id": str(uuid.uuid4()),
            "status": "COMPLETED",
            "result": _result(
                proposed_test_path="tests/conftest.py",
                test_content=f'SECRET_KEY = "{FAKE_OPENAI_KEY}"\ndef test_broken(:\n    pass\n',
                syntax_valid=True,
                validation_errors=[],
            ),
        }

    app.state.test_generation_service = SimpleNamespace(generate_tests=lying_service)
    res = _generate(client, auth_headers, repo.id)

    assert res.status_code == 200, res.text
    result = res.json()["result"]
    assert result["proposed_test_path"] != "tests/conftest.py"
    assert result["syntax_valid"] is False, "syntax validation was bypassed"
    assert FAKE_OPENAI_KEY not in res.text


def test_malformed_model_output_fails_instead_of_returning_empty_success(
    client, db_session, test_user, auth_headers, restore_app_state
):
    repo = _python_repo(db_session, test_user)

    class GarbageGateway(_CapturingGateway):
        async def generate(self, req):
            self.requests.append(req)
            return SimpleNamespace(content="Sure! Here are your tests: def test(): pass")

    app.state.test_generation_service = LLMTestGenerationService(llm_gateway=GarbageGateway())
    res = _generate(client, auth_headers, repo.id)

    assert res.status_code == 500
    assert res.json()["error"]["code"] == "ANALYSIS_FAILED"


# ===========================================================================
# 6. Ownership
# ===========================================================================

def test_cannot_generate_tests_for_another_users_repository(
    client, db_session, test_user, auth_headers, restore_app_state
):
    from app.models.user import User

    other = User(id=uuid.uuid4(), github_id=f"gh-{uuid.uuid4().hex[:6]}", login="other_user_d4",
                 email="other_d4@example.com")
    db_session.add(other)
    db_session.commit()
    their_repo = _python_repo(db_session, other)
    gateway = _CapturingGateway()
    app.state.test_generation_service = LLMTestGenerationService(llm_gateway=gateway)

    res = _generate(client, auth_headers, their_repo.id)

    assert res.status_code in (403, 404)
    assert "apply_discount" not in res.text
    assert gateway.requests == []
