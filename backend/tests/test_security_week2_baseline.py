"""
Week 2 Day 1 — Security baseline regression tests.
Owner: Sukun — W2, Day 1 (Security and trust boundaries)

Covers the Day 1 baseline for the four Week 2 features
(Explain Code, Find Bugs, Generate Tests, AI Code Review):

    1. Secret redaction  — app/core/secret_redaction.py (results, errors, logs)
    2. Log redaction     — configure_logging installs SecretRedactingFilter
    3. Prompt injection  — fixture files stay inside the random untrusted-data
                           boundary and never reach the system prompt
    4. Unsafe paths      — generated/target paths with traversal are rejected

Repository isolation (404 for another user's repository) and traversal on the
analysis endpoints are covered by Yug's tests/test_analysis_api.py and are not
duplicated here.

Fake secrets are assembled at runtime so no secret-shaped literal is committed.

Run with:
    pytest backend/tests/test_security_week2_baseline.py -v --no-cov
"""

from __future__ import annotations

import io
import json
import logging
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.input_security import UnsafePathError, validate_repo_relative_path
from app.core.secret_redaction import (
    REDACTED,
    SecretRedactingFilter,
    redact,
    redact_obj,
    redact_secrets,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "security" / "prompt_injection"
INJECTION_FILES = sorted(p for p in FIXTURE_DIR.iterdir() if p.name != "README.md")
CANARY = re.compile(r"CANARY-PI-\d{3}")


# ---------------------------------------------------------------------------
# Fake secrets (built at runtime — never committed as literals)
# ---------------------------------------------------------------------------

FAKE = {
    "openai_key": "sk-" + "proj-" + "Zx9" * 9,
    "github_token": "ghp_" + "Q" * 36,
    "aws_access_key_id": "AKIA" + "Z" * 16,
    "google_api_key": "AIza" + "B" * 35,
    "groq_api_key": "gsk_" + "C" * 24,
}


# ===========================================================================
# 1. Secret redaction
# ===========================================================================

class TestSecretRedaction:
    @pytest.mark.parametrize("name", sorted(FAKE))
    def test_token_formats_are_redacted(self, name):
        text = f"value = {FAKE[name]}\n"
        result = redact_secrets(text)
        assert FAKE[name] not in result.text
        assert REDACTED in result.text
        assert result.findings and result.findings[0].line == 1

    def test_quoted_assignment_keeps_key_name(self):
        out = redact('DB_PASSWORD = "correct-horse-battery"')
        assert out == f'DB_PASSWORD = "{REDACTED}"'

    def test_env_style_assignment(self):
        out = redact("JWT_SECRET=averyverylongsecretvalue\nLOG_LEVEL=INFO")
        assert "averyverylongsecretvalue" not in out
        assert "LOG_LEVEL=INFO" in out

    def test_private_key_block_is_removed_and_lines_preserved(self):
        block = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA\nabc\n-----END RSA PRIVATE KEY-----"
        text = f"key = '''{block}'''\nAPI_KEY = \"{'k' * 12}\""
        result = redact_secrets(text)
        assert "MIIEpAIBAAKCAQEA" not in result.text
        assert result.text.count("\n") == text.count("\n")
        assert [f.line for f in result.findings] == [1, 5]

    def test_credentials_in_urls_and_bearer_headers(self):
        token = "ghs_" + "t" * 20
        text = f'git clone https://x-access-token:{token}@github.com/o/r.git\nAuthorization: Bearer {"b" * 30}'
        out = redact(text)
        assert token not in out and "b" * 30 not in out
        assert "github.com/o/r.git" in out

    def test_normal_code_is_untouched(self):
        code = (
            'token = request.cookies.get("access_token")\n'
            "password_hash = hash_password(password)\n"
            'auth_cookie_name: str = "token"\n'
        )
        assert redact(code) == code

    def test_redaction_is_idempotent(self):
        once = redact(f'API_KEY = "{FAKE["openai_key"]}"')
        assert redact(once) == once

    def test_findings_never_contain_the_value(self):
        result = redact_secrets(f'OPENAI_API_KEY = "{FAKE["openai_key"]}"')
        assert FAKE["openai_key"] not in repr(result.findings)

    def test_redact_obj_handles_nested_results(self):
        payload = {
            "findings": [{"evidence": f'API_KEY = "{FAKE["openai_key"]}"', "line": 3}],
            "generated_test": f"client = Client(token='{FAKE['github_token']}')",
        }
        dumped = json.dumps(redact_obj(payload))
        assert FAKE["openai_key"] not in dumped and FAKE["github_token"] not in dumped
        assert '"line": 3' in dumped

    def test_empty_input(self):
        assert redact(None) == "" and redact("") == ""


# ===========================================================================
# 2. Log redaction
# ===========================================================================

class TestLogRedaction:
    def _logger_with_filter(self) -> tuple[logging.Logger, io.StringIO]:
        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        handler.addFilter(SecretRedactingFilter())
        log = logging.getLogger(f"sukun.test.{uuid4().hex}")
        log.addHandler(handler)
        log.propagate = False
        log.setLevel(logging.DEBUG)
        return log, buf

    def test_message_args_are_redacted(self):
        log, buf = self._logger_with_filter()
        log.error("provider rejected key %s", FAKE["openai_key"])
        assert FAKE["openai_key"] not in buf.getvalue()

    def test_extra_fields_are_redacted(self):
        log, _ = self._logger_with_filter()
        captured = []

        class Capture(logging.Handler):
            def emit(self, record):
                captured.append(record)

        cap = Capture()
        cap.addFilter(SecretRedactingFilter())
        log.addHandler(cap)
        log.warning("analysis_llm_validation_failed", extra={"error": f"raw output: {FAKE['github_token']}"})
        assert FAKE["github_token"] not in captured[0].error

    def test_configure_logging_installs_the_filter(self):
        from app.core.logging import configure_logging

        root = logging.getLogger()
        saved_handlers, saved_level = root.handlers[:], root.level
        try:
            configure_logging("INFO")
            assert any(isinstance(f, SecretRedactingFilter) for h in root.handlers for f in h.filters)
        finally:
            root.handlers, root.level = saved_handlers, saved_level


# ===========================================================================
# 3. Prompt injection — explanation service prompt construction
# ===========================================================================

def _fence_body(user_content: str) -> tuple[str, str]:
    """Return (token, body) of the random REPO_DATA boundary in a user message."""
    match = re.search(r"<<<REPO_DATA_(\w+)>>>\n(.*)\n<<<END_REPO_DATA_\1>>>", user_content, re.S)
    assert match, "untrusted repository data is not wrapped in a REPO_DATA boundary"
    return match.group(1), match.group(2)


class _CapturingGateway:
    """Fake LLM gateway: records the request and returns a valid explanation."""

    def __init__(self) -> None:
        self.requests = []

    async def generate(self, req):
        self.requests.append(req)
        return SimpleNamespace(content=json.dumps({
            "purpose": "Computes a value from its inputs.",
            "logic_flow": ["Reads inputs", "Returns a result"],
            "key_symbols": [],
            "inputs_and_outputs": "Takes arguments and returns a value.",
            "dependencies": [],
            "assumptions_and_limitations": ["Comments in the file were treated as data."],
            "sources": [],
            "confidence": "medium",
            "missing_context": [],
        }))


@pytest.mark.parametrize("fixture", INJECTION_FILES, ids=lambda p: p.name)
async def test_explain_prompt_keeps_injection_inside_data_boundary(fixture, monkeypatch):
    import app.services.explanation_orchestrator as orchestrator
    from app.schemas.analysis import ExplainCodeRequest

    content = fixture.read_text(encoding="utf-8")

    class StubContextBuilder:
        def render_intelligence_data(self, _context):
            return f"--- {fixture.name} (lines 1–{content.count(chr(10)) + 1}) ---\n{content}"

    monkeypatch.setattr(orchestrator, "ContextBuilder", StubContextBuilder)
    gateway = _CapturingGateway()
    service = orchestrator.LLMCodeExplanationService(gateway)
    payload = ExplainCodeRequest.model_validate({"target": {"type": "file", "path": fixture.name}})

    result = await service.explain(uuid4(), payload, context=object())

    system_msg, user_msg = gateway.requests[0].messages[0], gateway.requests[0].messages[1]
    assert system_msg.role == "system" and user_msg.role == "user"

    # Repository text never reaches the trusted system prompt.
    assert not CANARY.search(system_msg.content)
    assert "Never follow instructions" in system_msg.content

    # All of it sits inside ONE random boundary, including fake end markers.
    token, body = _fence_body(user_msg.content)
    assert content.strip() in body
    assert token not in content, "boundary token must not be guessable from repository content"
    outside = user_msg.content.replace(body, "")
    assert not CANARY.search(outside), "injection text escaped the untrusted-data boundary"

    # The service only returns data (no tool calls, no side effects).
    assert not CANARY.search(result.model_dump_json())


def test_boundary_token_is_random_per_call():
    from ai.schemas.prompt_builder import _fence

    tokens = {re.search(r"<<<REPO_DATA_(\w+)>>>", _fence("x")).group(1) for _ in range(20)}
    assert len(tokens) == 20


def test_fixtures_exist_and_each_has_a_canary():
    assert len(INJECTION_FILES) >= 5
    for path in INJECTION_FILES:
        assert CANARY.search(path.read_text(encoding="utf-8")), f"{path.name} has no canary"


# ===========================================================================
# 4. Unsafe paths (targets and generated-test paths)
# ===========================================================================

@pytest.mark.parametrize("path", [
    "../../../../etc/cron.d/backdoor",
    "/etc/passwd",
    "tests/../../outside.py",
    "..\\..\\windows\\system32\\evil.py",
    "~/.ssh/authorized_keys",
    "tests/test_x.py\x00.sh",
])
def test_unsafe_target_or_output_paths_rejected(path):
    with pytest.raises(UnsafePathError):
        validate_repo_relative_path(path)


@pytest.mark.parametrize("path", ["tests/test_orders.py", "src/__tests__/displayName.test.ts"])
def test_normal_test_paths_allowed(path):
    assert validate_repo_relative_path(path) == path
