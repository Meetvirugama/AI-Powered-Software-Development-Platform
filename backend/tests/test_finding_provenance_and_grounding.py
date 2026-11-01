"""Tests for B-16: Grounded Line/Revision Mapping, Finding Provenance, and Severity Inflation Guards.

Covers Section 12 Item 11 and B-16 acceptance criteria:
1. Grounding against indexed revision:
   - Drops hallucinated file paths not present in the indexed repository.
   - Drops citations with line numbers exceeding actual file length at that revision.
   - Normalizes inverted line ranges (start_line > end_line) safely.
   - Pins finding revision to the indexed repository revision.
2. Finding source provenance (static_rule, llm, or combined):
   - Preserves rule_id, rule_version, model_version, and confidence.
   - Merging overlapping STATIC + AI produces source_type="COMBINED", provenance="combined".
3. Severity inflation guard:
   - When merging STATIC + AI: an LLM cannot inflate a LOW or INFO static defect to HIGH or CRITICAL.
   - Uncorroborated, uncertain, or low-confidence AI findings cannot claim CRITICAL.
4. Deduplication key and reproducible evidence hash:
   - Computes deterministic deduplication_key across engines and runs.
   - Computes reproducible SHA-256 evidence_hash.
   - Deduplication merges items sharing identical deduplication keys.
5. Database persistence and retrieval:
   - AnalysisFinding stores provenance, deduplication_key, and evidence_hash in JSONB metadata.
   - to_dict() returns full provenance attributes.
6. Code explanation citation grounding:
   - Drops nonexistent files and out-of-bounds lines; pins revision.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.models.analysis_finding import AnalysisFinding
from app.models.analysis_run import AnalysisRun
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.repository_file import RepositoryFile
from app.models.user import User
from app.repositories.analysis_run_repository import AnalysisRunRepository
from app.schemas.analysis import (
    AnalysisSourceReference,
    AnalysisTarget,
    BugFinding,
    CodeExplanation,
    ReviewFinding,
)
from app.services.bug_detection_orchestrator import (
    _merge_two_findings,
    merge_and_deduplicate_findings,
    normalize_and_ground_findings,
)
from app.services.code_review_orchestrator import (
    ResolvedReviewTarget,
    merge_and_rank_review_findings,
    normalize_and_ground_review_findings,
)
from app.services.explanation_orchestrator import (
    ResolvedExplanationTarget,
    ground_explanation_sources,
)
from scanner.source_mapper import ReviewSourceMapResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_resolved_target() -> ResolvedExplanationTarget:
    """A resolved repository target with indexed files and known line counts at revision 'abc1234'."""
    return ResolvedExplanationTarget(
        target=AnalysisTarget(type="file", path="backend/app/service.py"),
        revision="abc1234",
        file_record=None,
        resolved_symbol=None,
        code_content="def compute():\n    return 42\n",
        intelligence_context=MagicMock(),
        missing_context=[],
        indexed_paths={
            "backend/app/service.py": 50,      # 50 lines
            "backend/app/utils.py": 25,        # 25 lines
            "backend/app/config.py": 10,       # 10 lines
        },
    )


@pytest.fixture
def sample_resolved_review_target() -> ResolvedReviewTarget:
    """A resolved review target with indexed and allowed files at revision 'rev-git-99'."""
    return ResolvedReviewTarget(
        target=MagicMock(type="file", path="src/calculator.py", base_revision=None, head_revision="rev-git-99", commit_sha=None, pr_number=None, diff=None),
        target_path_summary="src/calculator.py",
        revision="rev-git-99",
        base_revision=None,
        head_revision="rev-git-99",
        modified_files=[],
        file_contents={"src/calculator.py": "def add(a, b):\n    return a + b\n"},
        source_map=ReviewSourceMapResult(success=True),
        intelligence_context=MagicMock(),
        missing_context=[],
        indexed_paths={
            "src/calculator.py": 30,
            "src/helpers.py": 15,
        },
        allowed_paths={"src/calculator.py", "src/helpers.py"},
    )


# ---------------------------------------------------------------------------
# 1. Grounding Tests: Hallucinated Files, Out-of-Bounds Lines, Inverted Lines
# ---------------------------------------------------------------------------

def test_grounding_drops_hallucinated_files(sample_resolved_target: ResolvedExplanationTarget) -> None:
    """Verify that findings citing files not present in the indexed revision are dropped."""
    repo_id = uuid.uuid4()
    raw_findings = [
        BugFinding(
            id="f-real-1",
            category="logic_error",
            severity="MEDIUM",
            title="Real file finding",
            description="Real file defect",
            source_reference=AnalysisSourceReference(file_path="backend/app/service.py", start_line=10, end_line=15),
            evidence="def compute():",
            source_type="STATIC",
        ),
        BugFinding(
            id="f-hallucinated-1",
            category="security",
            severity="HIGH",
            title="Invented file finding",
            description="LLM hallucinated a non-existent file",
            source_reference=AnalysisSourceReference(file_path="backend/nonexistent/ghost.py", start_line=5, end_line=10),
            evidence="secret_leak()",
            source_type="AI",
        ),
    ]

    grounded, dropped = normalize_and_ground_findings(
        raw_findings,
        repository_id=repo_id,
        resolved=sample_resolved_target,
    )

    assert dropped == 1
    assert len(grounded) == 1
    assert grounded[0].id == "f-real-1"
    assert grounded[0].source_reference.file_path == "backend/app/service.py"
    assert grounded[0].source_reference.revision == "abc1234"


def test_grounding_drops_out_of_bounds_lines(sample_resolved_target: ResolvedExplanationTarget) -> None:
    """Verify that findings citing line numbers beyond the file's line count at that revision are dropped."""
    repo_id = uuid.uuid4()
    # backend/app/config.py has exactly 10 lines in sample_resolved_target
    raw_findings = [
        BugFinding(
            id="f-valid-lines",
            category="logic_error",
            severity="LOW",
            title="Valid line bounds",
            description="Lines within file bounds",
            source_reference=AnalysisSourceReference(file_path="backend/app/config.py", start_line=2, end_line=8),
            evidence="DEBUG = False",
            source_type="STATIC",
        ),
        BugFinding(
            id="f-out-of-bounds",
            category="null_safety",
            severity="MEDIUM",
            title="Hallucinated line 99 in 10-line file",
            description="Cites nonexistent lines",
            source_reference=AnalysisSourceReference(file_path="backend/app/config.py", start_line=85, end_line=99),
            evidence="null pointer dereference",
            source_type="AI",
        ),
    ]

    grounded, dropped = normalize_and_ground_findings(
        raw_findings,
        repository_id=repo_id,
        resolved=sample_resolved_target,
    )

    assert dropped == 1
    assert len(grounded) == 1
    assert grounded[0].id == "f-valid-lines"


def test_grounding_normalizes_inverted_line_ranges(sample_resolved_target: ResolvedExplanationTarget) -> None:
    """Verify that inverted line ranges from models (e.g. start_line=30, end_line=10) are normalized."""
    repo_id = uuid.uuid4()
    raw_finding = BugFinding(
        id="f-inverted",
        category="boundary_condition",
        severity="MEDIUM",
        title="Inverted line range",
        description="Model swapped start and end lines",
        source_reference=AnalysisSourceReference(file_path="backend/app/service.py", start_line=25, end_line=12),
        evidence="range check inverted",
        source_type="AI",
    )

    grounded, dropped = normalize_and_ground_findings(
        [raw_finding],
        repository_id=repo_id,
        resolved=sample_resolved_target,
    )

    assert dropped == 0
    assert len(grounded) == 1
    # Swapped cleanly into ascending range
    assert grounded[0].source_reference.start_line == 12
    assert grounded[0].source_reference.end_line == 25


def test_grounding_pins_revision_to_indexed_target(sample_resolved_target: ResolvedExplanationTarget) -> None:
    """Verify that source_reference.revision is firmly grounded to the indexed repository revision."""
    repo_id = uuid.uuid4()
    raw_finding = BugFinding(
        id="f-stale-rev",
        category="security",
        severity="HIGH",
        title="Stale revision",
        description="Finding with unspecified or outdated git commit",
        source_reference=AnalysisSourceReference(file_path="backend/app/service.py", start_line=5, end_line=10, revision="old-sha"),
        evidence="unsafe_call()",
        source_type="STATIC",
    )

    grounded, dropped = normalize_and_ground_findings(
        [raw_finding],
        repository_id=repo_id,
        resolved=sample_resolved_target,
    )

    assert len(grounded) == 1
    assert grounded[0].source_reference.revision == "abc1234"


# ---------------------------------------------------------------------------
# 2. Review Grounding Tests
# ---------------------------------------------------------------------------

def test_code_review_grounding_drops_unallowed_and_out_of_bounds(
    sample_resolved_review_target: ResolvedReviewTarget,
) -> None:
    """Verify code review findings are dropped if unallowed file or line exceeds max known lines."""
    repo_id = uuid.uuid4()
    raw = [
        ReviewFinding(
            id="rev-ok",
            category="correctness",
            severity="HIGH",
            title="Valid finding",
            description="Within calculator.py lines",
            source_reference=AnalysisSourceReference(file_path="src/calculator.py", start_line=5, end_line=10),
            evidence="return a + b",
            source_type="STATIC",
        ),
        ReviewFinding(
            id="rev-unallowed",
            category="security",
            severity="CRITICAL",
            title="Hallucinated file",
            description="Outside reviewed scope",
            source_reference=AnalysisSourceReference(file_path="etc/passwd", start_line=1, end_line=2),
            evidence="root:x:0:0",
            source_type="AI",
        ),
        ReviewFinding(
            id="rev-oob-line",
            category="performance",
            severity="LOW",
            title="Line 99 in 30-line file",
            description="Exceeds file length",
            source_reference=AnalysisSourceReference(file_path="src/calculator.py", start_line=95, end_line=99),
            evidence="slow loop",
            source_type="AI",
        ),
    ]

    grounded = normalize_and_ground_review_findings(
        raw,
        repository_id=repo_id,
        resolved=sample_resolved_review_target,
    )

    assert len(grounded) == 1
    assert grounded[0].id == "rev-ok"
    assert grounded[0].source_reference.revision == "rev-git-99"
    assert grounded[0].provenance == "static_rule"
    assert grounded[0].deduplication_key is not None
    assert grounded[0].evidence_hash is not None


# ---------------------------------------------------------------------------
# 3. Severity Inflation Guard (B-16)
# ---------------------------------------------------------------------------

def test_severity_inflation_guard_static_low_not_inflated_by_ai() -> None:
    """Verify that an LLM cannot inflate a LOW or INFO static finding to HIGH or CRITICAL."""
    ref = AnalysisSourceReference(file_path="backend/app/service.py", start_line=10, end_line=12)

    # Static analyzer detected a minor styling/convention issue (LOW severity)
    static_low = BugFinding(
        id="f-static-style",
        category="logic_error",
        severity="LOW",
        title="Unconventional naming",
        description="Static check flagged local naming convention.",
        source_reference=ref,
        evidence="x_val = 1",
        source_type="STATIC",
        rule_id="STYLE001",
    )

    # AI claimed this is CRITICAL
    ai_critical = BugFinding(
        id="f-ai-panic",
        category="logic_error",
        severity="CRITICAL",
        title="Critical naming risk",
        description="AI model hallucinated extreme risk for variable naming.",
        source_reference=ref,
        evidence="x_val = 1",
        source_type="AI",
    )

    merged = _merge_two_findings(static_low, ai_critical)

    # Must preserve the static rule's calibrated LOW severity and NOT elevate to CRITICAL
    assert merged.severity == "LOW"
    assert merged.source_type == "COMBINED"
    assert merged.provenance == "combined"
    assert merged.rule_id == "STYLE001"


def test_review_severity_inflation_guard_static_info_not_inflated_by_ai() -> None:
    """Verify review finding merge preserves INFO severity when AI claims HIGH."""
    ref = AnalysisSourceReference(file_path="src/calculator.py", start_line=10, end_line=12)

    static_info = ReviewFinding(
        id="rev-static-info",
        category="maintainability",
        severity="INFO",
        title="Docstring formatting",
        description="Static linter recommends Google docstring style.",
        source_reference=ref,
        evidence='"""add two numbers"""',
        source_type="STATIC",
        rule_id="D101",
    )

    ai_high = ReviewFinding(
        id="rev-ai-high",
        category="maintainability",
        severity="HIGH",
        title="Missing complete docs",
        description="AI claims missing docs is HIGH severity risk.",
        source_reference=ref,
        evidence='"""add two numbers"""',
        source_type="AI",
    )

    merged = merge_and_rank_review_findings([static_info, ai_high])
    assert len(merged) == 1
    # Retains static calibrated INFO severity
    assert merged[0].severity == "INFO"
    assert merged[0].source_type == "COMBINED"
    assert merged[0].provenance == "combined"


def test_uncertain_ai_finding_cannot_claim_critical(
    sample_resolved_target: ResolvedExplanationTarget,
) -> None:
    """Verify that uncorroborated, uncertain or low-confidence AI findings are capped at MEDIUM."""
    repo_id = uuid.uuid4()
    raw_ai_finding = BugFinding(
        id="f-uncertain-ai",
        category="security",
        severity="CRITICAL",
        title="Unconfirmed potential vulnerability",
        description="AI model is uncertain whether this input can be controlled by an attacker.",
        source_reference=AnalysisSourceReference(file_path="backend/app/service.py", start_line=5, end_line=10),
        evidence="dynamic_dispatch(val)",
        confidence="low",
        is_uncertain=True,
        source_type="AI",
    )

    grounded, _ = normalize_and_ground_findings(
        [raw_ai_finding],
        repository_id=repo_id,
        resolved=sample_resolved_target,
    )

    assert len(grounded) == 1
    # Capped at MEDIUM because of uncertainty/low confidence
    assert grounded[0].severity == "MEDIUM"


# ---------------------------------------------------------------------------
# 4. Provenance, Deduplication Key, and Evidence Hash
# ---------------------------------------------------------------------------

def test_deduplication_key_and_evidence_hash_deterministic(
    sample_resolved_target: ResolvedExplanationTarget,
) -> None:
    """Verify evidence hash is sha256 digest and deduplication key is reproducible across scans."""
    repo_id = uuid.uuid4()
    evidence_text = "range(0, len(items) + 1)"
    expected_hash = hashlib.sha256(evidence_text.encode("utf-8")).hexdigest()[:16]

    finding = BugFinding(
        id="f-b16-1",
        category="off_by_one",
        severity="HIGH",
        title="Off by one overflow",
        description="AST detected off-by-one loop bound",
        source_reference=AnalysisSourceReference(file_path="backend/app/service.py", start_line=15, end_line=18),
        evidence=evidence_text,
        source_type="STATIC",
        rule_id="AST001",
    )

    grounded, _ = normalize_and_ground_findings(
        [finding],
        repository_id=repo_id,
        resolved=sample_resolved_target,
    )

    res = grounded[0]
    assert res.provenance == "static_rule"
    assert res.rule_version == "1.0.0"
    assert res.evidence_hash == expected_hash
    assert res.deduplication_key == "backend/app/service.py:15-18:off_by_one:AST001"


def test_deduplication_by_key_in_bug_detection() -> None:
    """Verify merge_and_deduplicate_findings merges items sharing the same deduplication_key."""
    ref = AnalysisSourceReference(file_path="src/main.py", start_line=20, end_line=22)
    key = "src/main.py:20-22:resource_leak:AST004"

    f1 = BugFinding(
        id="f-run1",
        category="resource_leak",
        severity="MEDIUM",
        title="Unclosed file",
        description="open() called without context manager",
        source_reference=ref,
        evidence="f = open('file.txt')",
        source_type="STATIC",
        rule_id="AST004",
        deduplication_key=key,
    )

    f2 = BugFinding(
        id="f-run2",
        category="resource_leak",
        severity="MEDIUM",
        title="Resource leak detected",
        description="Corroborating AI scan flags descriptor leak",
        source_reference=ref,
        evidence="f = open('file.txt')",
        source_type="AI",
        deduplication_key=key,
    )

    merged = merge_and_deduplicate_findings([f1, f2])
    assert len(merged) == 1
    assert merged[0].source_type == "COMBINED"
    assert merged[0].provenance == "combined"
    assert merged[0].deduplication_key == key


# ---------------------------------------------------------------------------
# 5. Database Persistence of Provenance & Metadata (AnalysisFinding)
# ---------------------------------------------------------------------------

def test_analysis_finding_persists_and_exposes_provenance_and_keys(db_session) -> None:
    """Verify AnalysisRunRepository saves finding provenance, evidence_hash, and deduplication_key."""
    user = User(
        id=uuid.uuid4(),
        github_id=str(uuid.uuid4().int)[:10],
        login=f"b16_user_{uuid.uuid4().hex[:6]}",
        email=f"b16-{uuid.uuid4().hex[:6]}@example.com",
    )
    db_session.add(user)
    db_session.flush()

    inst = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id="inst_b16",
        account_login=user.login,
        permissions={},
    )
    db_session.add(inst)
    db_session.flush()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id=inst.id,
        github_repo_id="10099",
        owner=user.login,
        name=f"b16-repo-{uuid.uuid4().hex[:6]}",
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo)
    db_session.flush()

    repo_layer = AnalysisRunRepository(db_session)

    evidence_str = "eval(malicious_input)"
    ev_hash = hashlib.sha256(evidence_str.encode("utf-8")).hexdigest()[:16]
    dedup = "backend/app/auth.py:40-42:security:B307"

    run = repo_layer.create_run(
        repository_id=repo.id,
        user_id=user.id,
        feature_type="detect_bugs",
        status="COMPLETED",
        target_path="backend/app/auth.py",
        findings=[
            {
                "id": str(uuid.uuid4()),
                "category": "security",
                "severity": "CRITICAL",
                "title": "Arbitrary code execution",
                "description": "Dynamic eval detected",
                "file_path": "backend/app/auth.py",
                "start_line": 40,
                "end_line": 42,
                "evidence": evidence_str,
                "confidence": "high",
                "source_type": "COMBINED",
                "provenance": "combined",
                "rule_id": "B307",
                "rule_version": "1.2.0",
                "model_version": "gemini-2.5-flash",
                "deduplication_key": dedup,
                "evidence_hash": ev_hash,
            }
        ],
    )

    loaded_run = repo_layer.get_by_id(run.id)
    assert loaded_run is not None
    assert len(loaded_run.findings) == 1

    finding_record: AnalysisFinding = loaded_run.findings[0]
    finding_dict = finding_record.to_dict()

    assert finding_dict["source_type"] == "COMBINED"
    assert finding_dict["provenance"] == "combined"
    assert finding_dict["rule_id"] == "B307"
    assert finding_dict["rule_version"] == "1.2.0"
    assert finding_dict["model_version"] == "gemini-2.5-flash"
    assert finding_dict["deduplication_key"] == dedup
    assert finding_dict["evidence_hash"] == ev_hash


# ---------------------------------------------------------------------------
# 6. Explanation Citation Grounding Tests
# ---------------------------------------------------------------------------

def test_explanation_citation_grounding_normalizes_and_drops_hallucinations(
    sample_resolved_target: ResolvedExplanationTarget,
) -> None:
    """Verify Code Explanation citation grounding drops hallucinated files, out-of-bound lines, and fixes inverted lines."""
    explanation = CodeExplanation(
        summary="Explains compute service function",
        purpose="Compute numbers accurately",
        inputs_and_outputs="Returns integer 42",
        confidence="high",
        sources=[
            # Valid citation
            AnalysisSourceReference(file_path="backend/app/service.py", start_line=5, end_line=15),
            # Inverted line range in valid file (30 to 10 in 50-line file)
            AnalysisSourceReference(file_path="backend/app/service.py", start_line=30, end_line=10),
            # Out-of-bounds line in 10-line file (line 99)
            AnalysisSourceReference(file_path="backend/app/config.py", start_line=50, end_line=99),
            # Hallucinated file
            AnalysisSourceReference(file_path="backend/nonexistent/missing.py", start_line=1, end_line=10),
        ],
    )

    grounded_expl = ground_explanation_sources(
        explanation,
        repository_id=uuid.uuid4(),
        resolved=sample_resolved_target,
    )

    # 2 citations should survive (the valid one and the inverted one which got swapped)
    assert len(grounded_expl.sources) == 2
    # Inverted lines normalized to (10, 30)
    assert grounded_expl.sources[1].start_line == 10
    assert grounded_expl.sources[1].end_line == 30
    # Both sources have revision pinned to target revision
    assert all(src.revision == "abc1234" for src in grounded_expl.sources)
    # Confidence downgraded from high because ungrounded citations were dropped
    assert grounded_expl.confidence == "medium"
