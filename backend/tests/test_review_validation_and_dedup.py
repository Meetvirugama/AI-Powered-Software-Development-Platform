"""Unit and integration tests for ReviewValidationService and ReviewDeduplicationService (Phase 2)."""

import pytest
from app.services.review_validation_service import ReviewValidationService
from app.services.review_deduplication_service import ReviewDeduplicationService


@pytest.fixture
def validator():
    return ReviewValidationService()


@pytest.fixture
def deduplicator():
    return ReviewDeduplicationService()


def test_validate_finding_success(validator):
    finding = {
        "file_path": "src/utils.py",
        "start_line": 42,
        "evidence": "def parse_token(t): return jwt.decode(t)",
    }
    is_valid, err = validator.validate_finding(finding)
    assert is_valid is True
    assert err is None


def test_validate_finding_rejects_path_traversal(validator):
    finding = {
        "file_path": "../../../etc/shadow",
        "start_line": 1,
        "evidence": "root:x:0:0:root:/root:/bin/bash",
    }
    is_valid, err = validator.validate_finding(finding)
    assert is_valid is False
    assert "Unsafe file path" in err


def test_validate_finding_rejects_insufficient_evidence(validator):
    finding = {
        "file_path": "src/app.py",
        "start_line": 10,
        "evidence": "bad",  # < 10 chars
    }
    is_valid, err = validator.validate_finding(finding)
    assert is_valid is False
    assert "Insufficient evidence" in err


def test_assess_evidence_level(validator):
    static_finding = {
        "source_type": "STATIC",
        "confidence": "high",
        "evidence": "cursor.execute(f'SELECT * FROM users WHERE id={uid}')",
    }
    assert validator.assess_evidence_level(static_finding, is_changed_line=True) == "PROVEN"

    ai_high_finding = {
        "source_type": "AI",
        "confidence": "high",
        "evidence": "def risky_func(): pass some large amount of code",
    }
    assert validator.assess_evidence_level(ai_high_finding, is_changed_line=True) == "STRONG"
    assert validator.assess_evidence_level(ai_high_finding, is_changed_line=False) == "SUSPECTED"

    uncertain_finding = {
        "source_type": "AI",
        "is_uncertain": True,
        "evidence": "def maybe_issue(): return None",
    }
    assert validator.assess_evidence_level(uncertain_finding) == "NEEDS_CONTEXT"


def test_evaluate_quality_gate_partitions_correctly(validator):
    findings = [
        # Eligible: changed line, high confidence, valid evidence
        {
            "category": "security",
            "severity": "CRITICAL",
            "confidence": "high",
            "title": "SQL Injection",
            "evidence": "cursor.execute(f'SELECT * FROM {tbl}')",
            "source_reference": {"file_path": "src/db.py", "start_line": 15},
        },
        # Platform-only: unchanged line (line 99 not in changed set)
        {
            "category": "maintainability",
            "severity": "LOW",
            "confidence": "medium",
            "title": "Unused import",
            "evidence": "import unused_module_name_here",
            "source_reference": {"file_path": "src/db.py", "start_line": 99},
        },
        # Rejected: invalid path
        {
            "category": "correctness",
            "severity": "HIGH",
            "confidence": "high",
            "title": "Bug in outside file",
            "evidence": "assert True == False",
            "source_reference": {"file_path": "../../secret.py", "start_line": 1},
        },
    ]

    changed_lines = {"src/db.py": {14, 15, 16}}

    result = validator.evaluate_quality_gate(
        findings=findings,
        changed_lines_by_file=changed_lines,
        changed_lines_only=True,
    )

    assert result.total_analyzed == 3
    assert result.rejected_count == 1
    assert result.publishable_count == 1
    assert len(result.platform_findings) == 2
    assert result.publishable_findings[0]["title"] == "SQL Injection"


def test_compute_fingerprint_deterministic(deduplicator):
    f1 = {
        "file_path": "src/auth.py",
        "category": "security",
        "title": "Hardcoded JWT Secret",
        "evidence": 'SECRET_KEY = "mysecret"',
    }
    f2 = {
        "file_path": "src/auth.py",
        "category": "security",
        "title": "Hardcoded JWT Secret",
        "evidence": 'SECRET_KEY =  "mysecret" \n',
    }
    fp1 = deduplicator.compute_fingerprint(f1, repository_id="repo-1")
    fp2 = deduplicator.compute_fingerprint(f2, repository_id="repo-1")
    assert fp1 == fp2

    # Different category produces different fingerprint
    f3 = {**f1, "category": "maintainability"}
    fp3 = deduplicator.compute_fingerprint(f3, repository_id="repo-1")
    assert fp1 != fp3


def test_deduplicate_intra_run_merges_overlapping(deduplicator):
    static_f = {
        "file_path": "src/auth.py",
        "start_line": 20,
        "category": "security",
        "severity": "MEDIUM",
        "source_type": "STATIC",
        "title": "Bandit B105",
        "evidence": 'token = "hardcoded"',
    }
    ai_f = {
        "file_path": "src/auth.py",
        "start_line": 21,  # within +/- 2 lines
        "category": "security",
        "severity": "HIGH",
        "source_type": "AI",
        "title": "Secret in code",
        "evidence": 'token = "hardcoded"',
        "suggested_fix": 'token = os.getenv("TOKEN")',
    }

    merged = deduplicator.deduplicate_intra_run([static_f, ai_f], repository_id="repo-1")
    assert len(merged) == 1
    item = merged[0]
    assert item["source_type"] == "COMBINED"
    assert item["severity"] == "HIGH"
    assert item["suggested_fix"] == 'token = os.getenv("TOKEN")'


def test_deduplicate_intra_run_distinct_bugs_near_lines_not_merged(deduplicator):
    f1 = {
        "file_path": "src/auth.py",
        "start_line": 20,
        "category": "security",
        "severity": "CRITICAL",
        "rule_id": "SEC-001",
        "title": "SQL Injection vulnerability",
        "evidence": "execute(query)",
    }
    f2 = {
        "file_path": "src/auth.py",
        "start_line": 21,  # within +/- 2 lines, but completely different root cause
        "category": "security",
        "severity": "HIGH",
        "rule_id": "SEC-002",
        "title": "Hardcoded RSA Private Key",
        "evidence": "-----BEGIN RSA PRIVATE KEY-----",
    }

    result = deduplicator.deduplicate_intra_run([f1, f2], repository_id="repo-1")
    # Must preserve both distinct issues without merging!
    assert len(result) == 2


def test_filter_against_existing_pr_comments(deduplicator):
    candidates = [
        {"path": "app/main.py", "line": 10, "body": "Fix this bug"},
        {"path": "app/main.py", "line": 25, "body": "Another issue"},
    ]
    existing = [
        {"path": "app/main.py", "line": 10, "body": "Already discussed"},
    ]

    filtered = deduplicator.filter_against_existing_pr_comments(candidates, existing)
    assert len(filtered) == 1
    assert filtered[0]["line"] == 25
