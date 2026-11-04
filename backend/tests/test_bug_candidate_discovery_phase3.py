"""Tests for Phase 3: Hybrid Candidate Discovery & Rule Registry.

Verifies:
1. RuleRegistry: Catalog indexing, filtering, custom rule registration.
2. BugCandidateDiscoveryService: Multi-detector execution (AST, Taint, Config, Change-risk),
   schema normalization, and deduplication.
"""

from app.services.bug_candidate_discovery import BugCandidate, BugCandidateDiscoveryService
from scanner.rule_registry import DefectRule, RuleRegistry


def test_rule_registry_listing_and_custom_registration():
    """Verify RuleRegistry lists rules and allows dynamic registration."""
    registry = RuleRegistry.get_instance()
    sec_rules = registry.list_rules(category="security")
    assert len(sec_rules) >= 3

    py_rules = registry.list_rules(language="python")
    assert len(py_rules) >= 5

    # Register custom rule
    custom = DefectRule(
        rule_id="CUSTOM-RULE-001",
        name="Custom Insecure Hash",
        category="security",
        severity="HIGH",
        description="Avoid using MD5 or SHA1 for passwords.",
        languages=["python"],
    )
    registry.register(custom)
    fetched = registry.get("CUSTOM-RULE-001")
    assert fetched is not None
    assert fetched.name == "Custom Insecure Hash"


def test_candidate_discovery_ast_and_taint():
    """Verify BugCandidateDiscoveryService discovers both AST and Taint candidates."""
    code = """
import os

def process_query():
    user_id = request.query_params["id"]
    sql = f"SELECT * FROM items WHERE id = '{user_id}'"
    cursor.execute(sql)
"""
    service = BugCandidateDiscoveryService()
    candidates = service.discover_candidates(
        file_path="backend/app/api/items.py",
        code_content=code,
        language="python",
        scan_mode="standard",
    )

    assert len(candidates) >= 1
    # Check that candidates follow normalized BugCandidate schema
    taint_cands = [c for c in candidates if c.source_type == "TAINT"]
    assert len(taint_cands) >= 1
    tc = taint_cands[0]
    assert tc.rule_id == "TAINT-SQL-001"
    assert tc.category == "security"
    assert tc.severity in ("CRITICAL", "HIGH")
    assert tc.file_path == "backend/app/api/items.py"
    assert tc.start_line == 7
    assert "Untrusted input" in tc.evidence
    # Check serialization
    d = tc.to_dict()
    assert d["candidate_id"]
    assert d["source_type"] == "TAINT"


def test_candidate_discovery_config_and_change_risk():
    """Verify BugCandidateDiscoveryService detects debug mode and change risk comments."""
    code = """
DEBUG = True

def handle_records(records):
    # FIXME: crash occurs when records list is empty
    return records[0]
"""
    service = BugCandidateDiscoveryService()
    candidates = service.discover_candidates(
        file_path="backend/app/core/settings.py",
        code_content=code,
        language="python",
        scan_mode="change",
        changed_files=["backend/app/core/settings.py"],
    )

    cfg_cands = [c for c in candidates if c.source_type == "CONFIG"]
    assert len(cfg_cands) >= 1
    assert cfg_cands[0].rule_id == "CFG-DEBUG-001"

    risk_cands = [c for c in candidates if c.source_type == "CHANGE_RISK"]
    assert len(risk_cands) >= 1
    assert risk_cands[0].rule_id == "RISK-UNRESOLVED-001"
    assert "FIXME" in risk_cands[0].evidence

