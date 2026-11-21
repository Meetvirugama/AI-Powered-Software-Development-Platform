"""Module 8 (Bug Detection & Security Analysis) audit fixes."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from app.schemas.analysis import AnalysisTarget
from app.services.bug_candidate_discovery import BugCandidateDiscoveryService
from app.services.bug_detection_orchestrator import normalize_and_ground_findings
from app.services.explanation_orchestrator import ResolvedExplanationTarget
from scanner.gitleaks_runner import GitleaksRunner
from scanner.taint_analyzer import TaintAnalyzer


def _flows(code: str) -> dict[int, tuple[str, bool]]:
    return {
        t.start_line: (t.vulnerability_type, t.is_sanitized)
        for t in TaintAnalyzer().analyze_source(code, file_path="app/h.py", language="python")
    }


# ---------------------------------------------------------------------------
# Taint analysis
# ---------------------------------------------------------------------------

def test_inline_source_passed_directly_to_sink_is_detected() -> None:
    flows = _flows(
        "from flask import request\nimport subprocess\n"
        "def h():\n    subprocess.call(request.args['cmd'], shell=True)\n"
    )
    assert flows[4] == ("command_injection", False)


def test_eval_of_untrusted_input_is_code_injection() -> None:
    flows = _flows("from flask import request\ndef h():\n    n = request.args.get('n')\n    return eval(n)\n")
    assert flows[4] == ("code_injection", False)


def test_ssrf_sink_is_checked_and_dict_get_is_not() -> None:
    flows = _flows(
        "import requests\nfrom flask import request\n"
        "def h():\n    url = request.json['url']\n    cfg = {}\n    cfg.get(url)\n    requests.get(url)\n"
    )
    assert flows == {7: ("ssrf", False)}


def test_assignment_nested_in_with_block_flows_to_later_sink() -> None:
    flows = _flows(
        "import os\nfrom flask import request\n"
        "def h():\n    with open('x') as fh:\n        name = request.args['n']\n    os.system('ls ' + name)\n"
    )
    assert flows[6] == ("command_injection", False)


def test_augmented_assignment_propagates_taint_into_sql() -> None:
    flows = _flows(
        "from flask import request\n"
        "def h(cur):\n    q = \"SELECT * FROM t WHERE n = '\"\n    q += request.args['n']\n    cur.execute(q)\n"
    )
    assert flows[5] == ("sql_injection", False)


def test_reassigned_clean_value_and_parameterised_query_are_not_flagged() -> None:
    flows = _flows(
        "import os\nfrom flask import request\n"
        "def h(cur):\n    name = request.args['n']\n    cur.execute('SELECT * FROM t WHERE n = %s', (name,))\n"
        "    name = 'fixed'\n    os.system(name)\n"
    )
    assert flows.get(5, ("sql_injection", True))[1] is True
    assert 7 not in flows


# ---------------------------------------------------------------------------
# Secret scanning
# ---------------------------------------------------------------------------

def test_real_secret_on_a_line_mentioning_placeholder_words_is_detected() -> None:
    g = GitleaksRunner()
    assert g.scan_text('SAMPLE_RATE = 5; key = "AKIAZ3MPLQ7RT2VXK4NB"', "a.py")
    assert g.scan_text('token = os.getenv("GH", "ghp_9aZ8bY7cX6dW5eV4fU3gT2hS1iR0jQ9kP8lO")', "a.py")


def test_placeholder_values_and_env_lookups_are_still_ignored() -> None:
    g = GitleaksRunner()
    assert not g.scan_text('password = os.getenv("DATABASE_PASSWORD")', "a.py")
    assert not g.scan_text('api_key = "${API_KEY_FROM_ENV}"', "a.py")
    assert not g.scan_text('token = "your_token_here_please"', "a.py")


# ---------------------------------------------------------------------------
# Candidate normalisation and grounding
# ---------------------------------------------------------------------------

_CODE = (
    "from flask import request\nimport sqlite3\n"
    "def h():\n    name = request.args.get('n')\n    conn = sqlite3.connect('db')\n"
    "    conn.execute(\"SELECT * FROM u WHERE n = '%s'\" % name)\n    return eval(name)\n"
)


def test_ast_candidates_keep_category_and_confidence_from_metadata() -> None:
    cands = BugCandidateDiscoveryService().discover_candidates(file_path="app/h.py", code_content=_CODE)
    ast_eval = next(c for c in cands if c.rule_id == "AST-SEC-001")
    assert ast_eval.category == "security"
    assert "eval" in ast_eval.evidence


def test_taint_candidates_ground_into_valid_findings_instead_of_crashing() -> None:
    cands = BugCandidateDiscoveryService().discover_candidates(file_path="app/h.py", code_content=_CODE)
    assert any(c.source_type == "TAINT" for c in cands)
    resolved = ResolvedExplanationTarget(
        target=AnalysisTarget(type="file", path="app/h.py"),
        revision="r1",
        file_record=None,
        resolved_symbol=None,
        code_content=_CODE,
        intelligence_context=MagicMock(),
        indexed_paths={"app/h.py": 20},
    )
    findings, dropped = normalize_and_ground_findings(
        [c.to_dict() for c in cands],
        repository_id=uuid.uuid4(),
        resolved=resolved,
        default_source_type="STATIC",
    )
    assert dropped == 0
    sql = next(f for f in findings if f.rule_id == "TAINT-SQL-001")
    assert sql.source_type == "STATIC"
    assert sql.provenance == "static_rule:taint"
    assert sql.title.startswith("SQL injection")
    assert sql.description != sql.title


def test_scanner_availability_notes_explain_skipped_engines() -> None:
    svc = BugCandidateDiscoveryService()
    svc.semgrep_runner = MagicMock(is_available=MagicMock(return_value=False))
    svc.gitleaks_runner = MagicMock(is_available=MagicMock(return_value=False))
    svc.osv_runner = MagicMock(is_available=MagicMock(return_value=False))
    notes = svc.scanner_availability_notes("requirements.txt")
    assert any("Semgrep" in n for n in notes)
    assert any("Gitleaks" in n for n in notes)
    assert any("OSV" in n for n in notes)
    assert not any("OSV" in n for n in svc.scanner_availability_notes("app/h.py"))
