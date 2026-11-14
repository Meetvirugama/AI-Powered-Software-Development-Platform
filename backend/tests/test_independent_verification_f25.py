"""Comprehensive Test Suite for F25 — Independent Verification (Issue #206).

Covers:
1. Secondary Secret Engine: GitleaksDiffScanner (native CLI / fallback built-in rules,
   allowlist handling, redaction, and multi-credential detection).
2. P-28 LLM-as-Judge Requirement Verification: Diff hunk extraction, DiffHunkCitation,
   LLMRequirementJudge, and CriterionJudgeEvidence generation.
3. RequirementToCodeVerifier Integration: Verification result criteria evidence and
   Markdown summary generation with diff hunk citations.
4. IndependentVerifier Integration: Dual-engine secret scanning, P-28 requirement check,
   and structured PR summary formatting.
5. WorkspaceDiffVerifier Dual-Engine Integration: Secondary Gitleaks detection across
   workspace diff validations.
"""

from __future__ import annotations

import uuid
from typing import Any
import pytest

from ai.services.requirement_verifier import (
    LLMRequirementJudge,
    RequirementComplianceItem,
    RequirementToCodeVerifier,
    RequirementVerificationResult,
    extract_diff_hunks_from_diff,
)
from app.schemas.plan import PlanStep, StructuredPlan
from app.schemas.planner_context import FileDiffRange, LineRange, TaskDiffRanges
from app.schemas.task import TaskConstraint, TaskRequirement
from app.schemas.verification import (
    CriterionJudgeEvidence,
    DiffHunkCitation,
    VerificationCheckItem,
    VerificationContext,
    VerificationFinding,
    VerificationResult,
)
from app.schemas.workspace import (
    FileDiffHunk,
    FileDiffSummary,
    WorkspaceDiffResult,
)
from app.services.independent_verifier import IndependentVerifier
from sandbox.diff_verifier import WorkspaceDiffVerifier
from sandbox.gitleaks_scanner import (
    GITLEAKS_RULES,
    GitleaksDiffScanner,
    is_gitleaks_cli_available,
)


# ===========================================================================
# 1. GitleaksDiffScanner Tests (Secondary Secret Engine)
# ===========================================================================

class TestGitleaksDiffScanner:
    """Unit tests for secondary Gitleaks diff scanning engine."""

    def test_gitleaks_cli_availability_flag(self):
        """Verify CLI availability detection is boolean without error."""
        available = is_gitleaks_cli_available()
        assert isinstance(available, bool)

    def test_detects_aws_access_key(self):
        """Verify detection of AWS Access Key ID in added diff lines."""
        key = "AKIA" + "IOSFODNN7EXAMPLE"
        diff_text = f"""--- a/config.py
+++ b/config.py
@@ -1,3 +1,4 @@
 import os
+AWS_ACCESS_KEY_ID = "{key}"
"""
        scanner = GitleaksDiffScanner(force_builtin=True)
        findings = scanner.scan_diff(diff_text)
        assert len(findings) >= 1
        assert any(f.secret_type == "gitleaks:aws-access-key-id" for f in findings)
        assert findings[0].line_number == 2
        assert "[REDACTED]" in findings[0].redacted_preview

    def test_detects_github_pat(self):
        """Verify detection of GitHub Personal Access Token in diff additions."""
        token = "ghp_" + "1234567890abcdefghijklmnopqrstuvwxyz"
        diff_text = f"""--- a/ci.yml
+++ b/ci.yml
@@ -10,3 +10,4 @@
 steps:
+  - run: echo "{token}"
"""
        scanner = GitleaksDiffScanner(force_builtin=True)
        findings = scanner.scan_diff(diff_text)
        assert len(findings) >= 1
        assert any(f.secret_type == "gitleaks:github-pat" for f in findings)
        assert findings[0].line_number == 11
        assert "ghp_" not in findings[0].redacted_preview

    def test_detects_slack_webhook(self):
        """Verify detection of Slack webhook URL in diff additions."""
        webhook_url = "".join(["https://", "hooks.slack.com", "/services/", "T00000000/B00000000/1234567890abcdef12345678"])
        diff_text = f"""--- a/alerts.py
+++ b/alerts.py
@@ -5,1 +5,2 @@
+SLACK_HOOK = "{webhook_url}"
"""
        scanner = GitleaksDiffScanner(force_builtin=True)
        findings = scanner.scan_diff(diff_text)
        assert len(findings) >= 1
        assert any("slack-webhook" in f.secret_type for f in findings)

    def test_detects_private_key(self):
        """Verify detection of embedded private key in diff."""
        diff_text = """--- a/server.key
+++ b/server.key
@@ -0,0 +1,3 @@
+-----BEGIN RSA PRIVATE KEY-----
+MIIEowIBAAKCAQEA0...
+-----END RSA PRIVATE KEY-----
"""
        scanner = GitleaksDiffScanner(force_builtin=True)
        findings = scanner.scan_diff(diff_text)
        assert len(findings) >= 1
        assert any("private-key" in f.secret_type for f in findings)

    def test_detects_openai_key(self):
        """Verify detection of OpenAI secret API key."""
        key = "sk-proj-" + "abc1234567890abcdef1234567890abcdef123456"
        diff_text = f"""--- a/llm.py
+++ b/llm.py
@@ -1,2 +1,3 @@
+OPENAI_KEY = "{key}"
"""
        scanner = GitleaksDiffScanner(force_builtin=True)
        findings = scanner.scan_diff(diff_text)
        assert len(findings) >= 1
        assert any("openai-api-key" in f.secret_type for f in findings)

    def test_ignores_allowlisted_placeholders(self):
        """Verify allowlist patterns (placeholders, dummy examples) are not flagged."""
        clean_diff = """--- a/docs.py
+++ b/docs.py
@@ -1,3 +1,4 @@
+# Example: export API_KEY="your_api_key_here"
+# Dummy: key = "[REDACTED]"
+# Test: secret = "placeholder_secret"
"""
        scanner = GitleaksDiffScanner(force_builtin=True)
        findings = scanner.scan_diff(clean_diff)
        assert len(findings) == 0

    def test_ignores_deleted_lines_with_secrets(self):
        """Verify that deleted secret lines are not flagged as new leaks."""
        deleted_diff = """--- a/secrets.py
+++ b/secrets.py
@@ -1,3 +1,2 @@
-AWS_KEY = "AKIAIOSFODNN7EXAMPLE"
+AWS_KEY = os.environ.get("AWS_KEY")
"""
        scanner = GitleaksDiffScanner(force_builtin=True)
        findings = scanner.scan_diff(deleted_diff)
        assert len(findings) == 0


# ===========================================================================
# 2. Diff Hunk Extraction Tests
# ===========================================================================

class TestDiffHunkExtraction:
    """Tests for extracting structured DiffHunkCitation from diverse diff sources."""

    def test_extract_hunks_from_unified_diff_string(self):
        """Extract hunks from unified git diff string."""
        raw_diff = """--- a/src/auth.py
+++ b/src/auth.py
@@ -10,5 +10,12 @@ def authenticate():
+    token = secrets.token_hex(32)
+    return token
--- a/src/utils.py
+++ b/src/utils.py
@@ -1,3 +1,6 @@
+def helper():
+    pass
"""
        citations = extract_diff_hunks_from_diff(raw_diff)
        assert len(citations) == 2
        assert citations[0].file_path == "src/auth.py"
        assert citations[0].new_start == 10
        assert citations[0].line_range == "L10-L21"
        assert "token_hex" in citations[0].snippet
        assert citations[1].file_path == "src/utils.py"
        assert citations[1].line_range == "L1-L6"

    def test_extract_hunks_from_workspace_diff_result(self):
        """Extract hunks from WorkspaceDiffResult object with FileDiffHunk items."""
        ws_diff = WorkspaceDiffResult(
            task_id="task-123",
            base_revision="base1234",
            head_revision="head5678",
            total_files_changed=1,
            is_empty=False,
            files=[
                FileDiffSummary(
                    file_path="backend/core.py",
                    insertions=5,
                    deletions=0,
                    hunks=[
                        FileDiffHunk(
                            old_start=20,
                            old_lines=2,
                            new_start=20,
                            new_lines=7,
                            lines=["+ def execute():", "+     return True"],
                        )
                    ],
                )
            ],
        )
        citations = extract_diff_hunks_from_diff(ws_diff)
        assert len(citations) == 1
        assert citations[0].file_path == "backend/core.py"
        assert citations[0].line_range == "L20-L26"
        assert "execute" in citations[0].snippet

    def test_extract_hunks_from_task_diff_ranges(self):
        """Extract hunks from TaskDiffRanges with LineRange objects."""
        diff_ranges = TaskDiffRanges(
            task_id=uuid.uuid4(),
            files=[
                FileDiffRange(
                    file_path="src/service.py",
                    status="modified",
                    diff_ranges=[
                        LineRange(start_line=15, end_line=30, change_type="added")
                    ],
                    additions=16,
                    deletions=0,
                )
            ],
        )
        citations = extract_diff_hunks_from_diff(diff_ranges)
        assert len(citations) == 1
        assert citations[0].file_path == "src/service.py"
        assert citations[0].line_range == "L15-L30"


# ===========================================================================
# 3. LLM-as-Judge Requirement Verifier Tests (P-28)
# ===========================================================================

class TestLLMRequirementJudge:
    """Tests for LLM-as-judge acceptance criterion evaluation and citation generation."""

    def test_judge_evaluates_criterion_matching_hunks(self):
        """Verify PASS verdict and citations when code diff satisfies criterion."""
        judge = LLMRequirementJudge()
        citations = [
            DiffHunkCitation(
                file_path="src/security.py",
                hunk_index=0,
                old_start=1,
                old_lines=1,
                new_start=1,
                new_lines=10,
                line_range="L1-L10",
                hunk_header="@@ -1,1 +1,10 @@",
                snippet="+ def hash_password(pwd):\n+     return bcrypt.hashpw(pwd)",
            )
        ]
        evidence = judge.evaluate_criterion(
            requirement_id="req-auth",
            criterion="Implement secure password hashing",
            citations_pool=citations,
            target_files=["src/security.py"],
        )
        assert isinstance(evidence, CriterionJudgeEvidence)
        assert evidence.verdict == "PASS"
        assert evidence.confidence >= 0.85
        assert len(evidence.citations) == 1
        assert evidence.citations[0].file_path == "src/security.py"
        assert "password" in evidence.reasoning.lower() or "citations" in evidence.reasoning.lower()

    def test_judge_evaluates_unmet_when_no_matching_diff(self):
        """Verify UNMET verdict when no diff changes exist for expected target files."""
        judge = LLMRequirementJudge()
        citations = [
            DiffHunkCitation(
                file_path="src/other.py",
                hunk_index=0,
                old_start=1,
                old_lines=1,
                new_start=1,
                new_lines=2,
                line_range="L1-L2",
                hunk_header="@@ -1,1 +1,2 @@",
                snippet="+ # other changes",
            )
        ]
        evidence = judge.evaluate_criterion(
            requirement_id="req-billing",
            criterion="Add Stripe webhook listener",
            citations_pool=citations,
            target_files=["src/billing.py"],
        )
        assert evidence.verdict == "UNMET"
        assert len(evidence.citations) == 0
        assert "No diff hunks found in target files" in evidence.reasoning

    def test_judge_fails_on_test_failure(self):
        """Verify FAIL verdict when tests fail for criterion."""
        judge = LLMRequirementJudge()
        citations = [
            DiffHunkCitation(
                file_path="src/billing.py",
                hunk_index=0,
                old_start=1,
                old_lines=1,
                new_start=1,
                new_lines=5,
                line_range="L1-L5",
                hunk_header="@@ -1,1 +1,5 @@",
                snippet="+ def stripe_hook(): pass",
            )
        ]
        evidence = judge.evaluate_criterion(
            requirement_id="req-billing",
            criterion="Add Stripe webhook listener",
            citations_pool=citations,
            target_files=["src/billing.py"],
            tests_failed=True,
        )
        assert evidence.verdict == "FAIL"
        assert "test failure" in evidence.reasoning.lower()


# ===========================================================================
# 4. RequirementToCodeVerifier Integration Tests
# ===========================================================================

class TestRequirementToCodeVerifierIntegration:
    """Integration tests for RequirementToCodeVerifier with P-28 LLM-as-judge evidence."""

    def test_verifier_produces_criteria_evidence_and_markdown_citations(self):
        """Verify end-to-end requirement verification generates structured evidence and PR table."""
        verifier = RequirementToCodeVerifier()
        reqs = [
            TaskRequirement(
                id="req-1",
                description="Implement token auth helper",
                category="functional",
                target_files=["src/auth.py"],
                acceptance_criteria=["Generate secure random token", "Validate bearer header"],
            )
        ]
        plan = StructuredPlan(
            summary="Auth helper plan",
            problem_statement="Need token validation",
            expected_files_to_modify=["src/auth.py"],
            steps=[
                PlanStep(
                    step_id="step_1",
                    title="Add auth helpers",
                    description="Token generation and bearer validation",
                    action_type="modify",
                    expected_files=["src/auth.py"],
                )
            ],
        )
        diff_str = """--- a/src/auth.py
+++ b/src/auth.py
@@ -1,5 +1,15 @@
+import secrets
+def generate_token():
+    return secrets.token_hex(32)
+def validate_bearer_token(header):
+    return header.startswith("Bearer ")
"""
        result = verifier.verify_requirements_against_diff(
            task_id="task-f25-demo",
            requirements=reqs,
            constraints=[],
            original_plan=plan,
            final_diff=diff_str,
        )

        assert result.overall_status == "PASS"
        assert result.alignment_score == 1.0
        assert len(result.criteria_evidence) == 2
        for ev in result.criteria_evidence:
            assert ev.verdict == "PASS"
            assert len(ev.citations) >= 1
            assert ev.citations[0].file_path == "src/auth.py"

        # Check PR Markdown contains the LLM-as-Judge table
        assert "### Acceptance Criteria Verification (LLM-as-Judge P-28)" in result.summary_markdown
        assert "src/auth.py#L1-L15" in result.summary_markdown


# ===========================================================================
# 5. IndependentVerifier Integration Tests (Dual Engine + P-28)
# ===========================================================================

class TestIndependentVerifierIntegration:
    """Tests for IndependentVerifier dual-engine secret scanning and P-28 judge integration."""

    def test_secret_scan_dual_engine_detects_credentials(self):
        """Verify dual-engine secret scanner catches leaked credentials and records details."""
        key = "AKIA" + "IOSFODNN7EXAMPLE"
        diff_with_secret = f"""--- a/api.py
+++ b/api.py
@@ -1,2 +1,3 @@
+AWS_SECRET_KEY = "{key}"
"""
        ctx = VerificationContext(
            task_id="task-sec-test",
            base_revision="abcdef1234567890abcdef1234567890abcdef12",
            verified_revision="bcdefa1234567890abcdef1234567890abcdef12",
            diff=diff_with_secret,
        )
        verifier = IndependentVerifier()
        result = verifier.verify(ctx)

        assert result.status == "FAIL"
        secret_check = next(c for c in result.checks if c.name == "secret_scan")
        assert secret_check.status == "FAILED"
        assert secret_check.details is not None
        assert secret_check.details["primary_engine"] == "regex_redactor"
        assert secret_check.details["secondary_engine"] == "gitleaks"
        assert secret_check.details["secondary_findings_count"] >= 1

    def test_secret_scan_dual_engine_passes_on_clean_diff(self):
        """Verify clean diff passes dual-engine scan with zero findings."""
        clean_diff = """--- a/math_utils.py
+++ b/math_utils.py
@@ -1,2 +1,4 @@
+def add(a: int, b: int) -> int:
+    return a + b
"""
        ctx = VerificationContext(
            task_id="task-clean-test",
            base_revision="abcdef1234567890abcdef1234567890abcdef12",
            verified_revision="bcdefa1234567890abcdef1234567890abcdef12",
            diff=clean_diff,
            allowed_files=["math_utils.py"],
        )
        verifier = IndependentVerifier()
        result = verifier.verify(ctx)

        secret_check = next(c for c in result.checks if c.name == "secret_scan")
        assert secret_check.status == "PASSED"
        assert secret_check.details["primary_findings_count"] == 0
        assert secret_check.details["secondary_findings_count"] == 0

    def test_p28_llm_judge_check_in_independent_verifier(self):
        """Verify P-28 LLM-as-judge acceptance check runs and populates requirement_evidence."""
        diff_code = """--- a/auth_service.py
+++ b/auth_service.py
@@ -1,5 +1,12 @@
+def issue_jwt_token(payload):
+    return jwt.encode(payload, "secret", algorithm="HS256")
"""
        ctx = VerificationContext(
            task_id="task-p28-test",
            base_revision="abcdef1234567890abcdef1234567890abcdef12",
            verified_revision="bcdefa1234567890abcdef1234567890abcdef12",
            diff=diff_code,
            allowed_files=["auth_service.py"],
            requirements=[
                {
                    "id": "req-jwt",
                    "description": "Issue JWT tokens",
                    "acceptance_criteria": ["issue_jwt_token function added"],
                    "target_files": ["auth_service.py"],
                }
            ],
        )
        verifier = IndependentVerifier()
        result = verifier.verify(ctx)

        # Check 13 was evaluated
        judge_check = next((c for c in result.checks if c.name == "requirement_llm_judge"), None)
        assert judge_check is not None
        assert judge_check.status == "PASSED"
        assert len(result.requirement_evidence) == 1
        assert result.requirement_evidence[0].verdict == "PASS"
        assert len(result.requirement_evidence[0].citations) >= 1

        # Check PR summary contains P-28 criteria table
        assert "### 📋 P-28 Acceptance Criteria Citations (LLM-as-Judge)" in result.pr_summary
        assert "req-jwt" in result.pr_summary


# ===========================================================================
# 6. WorkspaceDiffVerifier Secondary Engine Tests
# ===========================================================================

class TestWorkspaceDiffVerifierSecondaryEngine:
    """Tests for secondary Gitleaks scanning inside WorkspaceDiffVerifier."""

    def test_workspace_diff_verifier_detects_secrets_with_gitleaks(self):
        """Verify validate_diff identifies credentials using secondary Gitleaks scanner."""
        verifier = WorkspaceDiffVerifier()
        token = "ghp_" + "1234567890abcdefghijklmnopqrstuvwxyz"
        diff_text = f"""--- a/credentials.json
+++ b/credentials.json
@@ -0,0 +1,3 @@
+{{
+  "api_key": "{token}"
+}}
"""
        diff_obj = WorkspaceDiffResult(
            task_id="t1",
            base_revision="b1",
            raw_diff=diff_text,
            is_empty=False,
            files=[FileDiffSummary(file_path="credentials.json", patch=diff_text)],
        )
        val_res = verifier.validate_diff(
            diff_result=diff_obj,
            allowed_files=["credentials.json"],
        )
        assert val_res.is_valid is False
        assert len(val_res.secret_findings) >= 1
        assert any("github-pat" in sf.secret_type or "github" in sf.secret_type for sf in val_res.secret_findings)
