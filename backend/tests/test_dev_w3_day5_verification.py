
"""Unit tests for Week 3 Day 5 Independent Verification Engine & PR Summary Generator.

Owner: Dev — Week 3 Day 5 Deliverable (Docs/daily_tasks.md line 644 & Docs/week3.md §6 F36)

What these tests verify in simple terms:
1. Happy path: When all 12 safety checks pass, verify the engine returns 'PASS' and allows PR publication.
2. Plan check: Make sure unapproved plans or changed plan versions are blocked.
3. Git checks: Make sure pushing directly to 'main' or having invalid commit SHAs is blocked.
4. File checks: Make sure forbidden files or out-of-scope files cannot be modified.
5. Test checks: Make sure tests actually ran, passed, and weren't run on an old/stale commit.
6. Secret checks: Make sure passwords or API keys in the code diff are caught and blocked.
7. PR summary: Make sure a clean Markdown summary is generated with all 12 checks listed.
"""

from __future__ import annotations

import pytest

from app.schemas.verification import (
    VerificationCheckItem,
    VerificationContext,
    VerificationFinding,
    VerificationResult,
)
from app.services.independent_verifier import IndependentVerifier


# ---------------------------------------------------------------------------
# Helper: Create a Clean, Valid VerificationContext for Testing
# ---------------------------------------------------------------------------

def _create_clean_context(
    task_id: str = "task_100",
    target_branch: str = "agent/task-100",
    base_revision: str = "abcdef0123456789",
    verified_revision: str = "1234567890abcdef",
    diff: str | None = None,
) -> VerificationContext:
    """Helper function to create a clean context where all 12 checks should pass.

    In simple words: This gives us a 'perfect' task setup so we can test happy path,
    or tweak one specific field to see if that individual check catches the error.
    """
    clean_diff = diff or """
--- a/backend/app/auth.py
+++ b/backend/app/auth.py
@@ -10,3 +10,3 @@
-    if user is None:
+    if not user:
"""
    return VerificationContext(
        task_id=task_id,
        target_branch=target_branch,
        base_revision=base_revision,
        verified_revision=verified_revision,
        diff=clean_diff,
        task_title="Fix user authentication null check",
        task_description="Safely handle empty user record in auth route.",
        plan_approved=True,
        approved_plan_version=1,
        current_plan_version=1,
        allowed_files=["backend/app/auth.py"],
        forbidden_files=["backend/app/config.py", ".env.production"],
        tests_completed=True,
        tests_passed=True,
        test_revision=verified_revision,
        test_count=15,
        failed_test_count=0,
        static_analysis_completed=True,
        static_findings=[],
        ai_review_completed=True,
        ai_review_findings=[],
        tokens_used=1200,
        token_budget=50000,
        execution_time_s=14.5,
        timeout_s=300.0,
    )


# ---------------------------------------------------------------------------
# 1. Happy Path Test: Everything Passes Cleanly
# ---------------------------------------------------------------------------

def test_independent_verifier_happy_path_all_12_checks_pass():
    """Verify that when everything is clean and safe, verification returns PASS.

    Simple explanation:
    If tests pass, no secrets are leaked, files are allowed, and plan is approved,
    the overall verdict must be PASS and publication must be allowed.
    """
    verifier = IndependentVerifier()
    context = _create_clean_context()

    result = verifier.verify(context)

    # Make sure we got exactly 12 checks evaluated
    assert len(result.checks) == 12

    # In simple terms: Every single check should have passed
    for check in result.checks:
        assert check.status in ("PASSED", "COMPLETED"), f"Check {check.name} did not pass: {check.message}"

    # Verify overall verdict and publication eligibility
    assert result.status == "PASS"
    assert result.is_passing is True
    assert result.is_eligible_for_publication is True
    assert len(result.blocking_findings) == 0

    # Ensure PR markdown summary was generated with task details
    assert "## 🤖 Automated Implementation & Verification Report" in result.pr_summary
    assert "Fix user authentication null check" in result.pr_summary
    assert "agent/task-100" in result.pr_summary


# ---------------------------------------------------------------------------
# 2. Check 1: Plan Approval & Version Mismatch Tests
# ---------------------------------------------------------------------------

def test_check_fails_when_plan_is_unapproved():
    """Verify that a task with an unapproved plan is strictly blocked.

    Simple explanation:
    If someone tries to publish code before the plan was approved by a human,
    it must fail verification.
    """
    verifier = IndependentVerifier()
    context = _create_clean_context()
    context.plan_approved = False  # Not approved!

    result = verifier.verify(context)

    assert result.status == "FAIL"
    assert result.is_eligible_for_publication is False
    assert any(c.name == "plan_approval" and c.status == "FAILED" for c in result.checks)
    assert any("has not received mandatory human approval" in f.message for f in result.blocking_findings)


def test_check_fails_when_plan_version_mismatches():
    """Verify that if a plan was changed after approval, approval is invalidated.

    Simple explanation:
    If a human approved Plan Version 1, but the current plan is Version 2,
    the task cannot be published until Version 2 is reviewed and approved.
    """
    verifier = IndependentVerifier()
    context = _create_clean_context()
    context.approved_plan_version = 1
    context.current_plan_version = 2  # Plan changed to version 2!

    result = verifier.verify(context)

    assert result.status == "FAIL"
    assert any(c.name == "plan_approval" and c.status == "FAILED" for c in result.checks)
    assert any("Plan version mismatch" in f.message for f in result.blocking_findings)


# ---------------------------------------------------------------------------
# 3. Check 2 & 12: Git Commit & Branch Protection Tests
# ---------------------------------------------------------------------------

def test_check_fails_on_invalid_base_revision():
    """Verify that an invalid or blank base commit SHA fails verification.

    Simple explanation:
    We must have a real git commit SHA to know where this branch started.
    """
    verifier = IndependentVerifier()
    context = _create_clean_context()
    context.base_revision = "not-a-real-sha!"

    result = verifier.verify(context)

    assert result.status == "FAIL"
    assert any(c.name == "base_revision" and c.status == "FAILED" for c in result.checks)


def test_check_fails_when_target_branch_is_main():
    """Verify that pushing directly to 'main' or 'master' is strictly blocked.

    Simple explanation:
    Never push directly to main! The platform must always push to a feature branch.
    """
    verifier = IndependentVerifier()
    context = _create_clean_context(target_branch="main")

    result = verifier.verify(context)

    assert result.status == "FAIL"
    assert result.is_eligible_for_publication is False
    assert any(c.name == "branch_protection" and c.status == "FAILED" for c in result.checks)
    assert any("Direct push to protected branch" in f.message for f in result.blocking_findings)


# ---------------------------------------------------------------------------
# 4. Check 3 & 4: File Boundary and Constraint Tests
# ---------------------------------------------------------------------------

def test_check_fails_when_out_of_scope_file_is_modified():
    """Verify that modifying files outside the approved plan scope is blocked.

    Simple explanation:
    If the plan said 'edit auth.py', but the diff also edits 'payment.py',
    we block the PR because payment.py was never part of the approved plan.
    """
    bad_diff = """
--- a/backend/app/auth.py
+++ b/backend/app/auth.py
@@ -1 +1 @@
-pass
+return True
--- a/backend/app/unapproved_file.py
+++ b/backend/app/unapproved_file.py
@@ -1 +1 @@
-pass
+hack()
"""
    verifier = IndependentVerifier()
    context = _create_clean_context(diff=bad_diff)
    context.allowed_files = ["backend/app/auth.py"]

    result = verifier.verify(context)

    assert result.status == "FAIL"
    assert any(c.name == "permitted_files" and c.status == "FAILED" for c in result.checks)
    assert any("outside approved plan" in f.message for f in result.blocking_findings)


def test_check_fails_when_forbidden_file_is_modified():
    """Verify that touching protected files (like production configs) is blocked.

    Simple explanation:
    Files like '.env.production' or 'backend/app/config.py' are forbidden.
    If the agent modified one of them, fail with a CRITICAL security blocker!
    """
    forbidden_diff = """
--- a/backend/app/config.py
+++ b/backend/app/config.py
@@ -1 +1 @@
-DEBUG = False
+DEBUG = True
"""
    verifier = IndependentVerifier()
    context = _create_clean_context(diff=forbidden_diff)
    context.forbidden_files = ["backend/app/config.py"]

    result = verifier.verify(context)

    assert result.status == "FAIL"
    assert any(c.name == "no_forbidden_files" and c.status == "FAILED" for c in result.checks)
    assert any("Forbidden file" in f.message for f in result.blocking_findings)


# ---------------------------------------------------------------------------
# 5. Check 5: Diff Traversal & Size Checks
# ---------------------------------------------------------------------------

def test_check_fails_on_empty_diff():
    """Verify that an empty diff cannot be published.

    Simple explanation:
    If there are no code changes, you cannot open a pull request.
    """
    verifier = IndependentVerifier()
    context = _create_clean_context(diff="   ")

    result = verifier.verify(context)

    assert result.status == "FAIL"
    assert any(c.name == "clean_diff" and c.status == "FAILED" for c in result.checks)


def test_check_fails_on_path_traversal_in_diff():
    """Verify that relative path traversal ('../../') in diff headers is blocked.

    Simple explanation:
    Attackers try to use '../../etc/passwd' to write files outside the workspace.
    This check detects that and blocks the attack.
    """
    traversal_diff = """
--- a/../../etc/shadow
+++ b/../../etc/shadow
@@ -1 +1 @@
-root
+hacked
"""
    verifier = IndependentVerifier()
    context = _create_clean_context(diff=traversal_diff)

    result = verifier.verify(context)

    assert result.status == "FAIL"
    assert any(c.name == "clean_diff" and c.status == "FAILED" for c in result.checks)


# ---------------------------------------------------------------------------
# 6. Check 6 & 7: Test Execution and Stale Test Synchronization Tests
# ---------------------------------------------------------------------------

def test_check_inconclusive_when_tests_were_not_run():
    """Docs/week3.md §6: Never mark an unavailable check as passed.

    Simple explanation:
    If the test runner didn't execute, we cannot claim that verification passed.
    Status must be INCONCLUSIVE or REQUIRES_HUMAN_REVIEW, never PASS.
    """
    verifier = IndependentVerifier()
    context = _create_clean_context()
    context.tests_completed = False  # Tests never ran!

    result = verifier.verify(context)

    assert result.status in ("INCONCLUSIVE", "REQUIRES_HUMAN_REVIEW")
    assert result.is_passing is False
    assert any(c.name == "required_tests" and c.status == "UNAVAILABLE" for c in result.checks)


def test_check_fails_when_tests_have_failures():
    """Verify that if automated tests failed, verification fails.

    Simple explanation:
    If 2 tests failed during test execution, you cannot publish broken code.
    """
    verifier = IndependentVerifier()
    context = _create_clean_context()
    context.tests_passed = False
    context.failed_test_count = 2

    result = verifier.verify(context)

    assert result.status == "FAIL"
    assert any(c.name == "required_tests" and c.status == "FAILED" for c in result.checks)
    assert any("failed with 2 failing test(s)" in f.message for f in result.blocking_findings)


def test_check_fails_when_test_results_are_stale():
    """Docs/week3.md §6: Test results must correspond to the final diff.

    Simple explanation:
    If tests were run on commit 'abc', but the candidate commit is 'def',
    the tests are stale and cannot verify the current code.
    """
    verifier = IndependentVerifier()
    context = _create_clean_context()
    context.test_revision = "1111111111111111"
    context.verified_revision = "2222222222222222"

    result = verifier.verify(context)

    assert result.status == "FAIL"
    assert any(c.name == "test_diff_sync" and c.status == "FAILED" for c in result.checks)
    assert any("does not match verified revision" in f.message for f in result.blocking_findings)


# ---------------------------------------------------------------------------
# 7. Check 11: Secret & Credential Leakage Scan Tests
# ---------------------------------------------------------------------------

def test_check_fails_when_diff_contains_hardcoded_secrets():
    """Verify that candidate code containing real API keys or tokens is blocked.

    Simple explanation:
    If an AI agent accidentally writes an OpenAI or GitHub API key into the code,
    our secret scanner catches it and stops the PR before credentials leak to GitHub!
    """
    secret_diff = """
--- a/backend/app/auth.py
+++ b/backend/app/auth.py
@@ -10,1 +10,1 @@
-api_key = None
+api_key = "sk-proj-abc1234567890abcdef1234567890abcdef123456"
"""
    verifier = IndependentVerifier()
    context = _create_clean_context(diff=secret_diff)

    result = verifier.verify(context)

    assert result.status == "FAIL"
    assert any(c.name == "secret_scan" and c.status == "FAILED" for c in result.checks)
    assert any("Hardcoded secret detected" in f.message for f in result.blocking_findings)


# ---------------------------------------------------------------------------
# 8. Markdown PR Summary Content Tests
# ---------------------------------------------------------------------------

def test_pr_markdown_summary_contains_all_checklist_items():
    """Verify that the generated PR summary has all required sections and tables.

    Simple explanation:
    Check that the generated Markdown contains the title, verification checklist table,
    and the human review reminder.
    """
    verifier = IndependentVerifier()
    context = _create_clean_context()

    result = verifier.verify(context)
    summary = result.pr_summary

    assert "### 📌 Task Overview" in summary
    assert "### 🛡️ Independent Verification Gates (12 Checks)" in summary
    assert "### 📂 Files Modified" in summary
    assert "Human Review Notice" in summary
    assert "`backend/app/auth.py`" in summary
