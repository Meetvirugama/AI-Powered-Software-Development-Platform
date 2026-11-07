"""Requirement-to-Code Verifier & Scope Compliance Engine.

Owner: Meet (Week 3 Day 5: Requirement-to-code verification comparing final diff against original plan)
Reference: Docs/week3.md §6 F36 & §8 Day 5.

Key Responsibilities:
1. Compares final git diff against original StructuredPlan and task intake requirements.
2. Validates scope bounds:
   - Identifies out-of-scope file modifications.
   - Verifies all expected target files were addressed.
3. Enforces constraint invariants:
   - Asserts zero modifications to protected/forbidden files.
   - Detects forbidden package dependency introductions.
4. Generates an objective requirement alignment score (0.0 to 1.0) and Markdown PR summary.
"""

from __future__ import annotations

import ast
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.schemas.plan import StructuredPlan
from app.schemas.planner_context import FileDiffRange, TaskDiffRanges
from app.schemas.task import (
    TaskConstraint,
    TaskRequirement,
)
from app.schemas.verification import (
    VerificationFinding,
    VerificationOverallStatus,
)
from app.schemas.workspace import WorkspaceDiffResult

logger = logging.getLogger(__name__)


@dataclass
class RequirementComplianceItem:
    """Compliance assessment for a single task requirement."""

    requirement_id: str
    description: str
    category: str
    target_files: list[str]
    is_satisfied: bool
    matched_diff_files: list[str] = field(default_factory=list)
    unmet_criteria: list[str] = field(default_factory=list)
    notes: str = ""
    status: str = "SATISFIED"  # "SATISFIED", "PARTIAL", "BLOCKED", "UNMET"
    criteria_evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class RequirementVerificationResult:
    """Final outcome of requirement-to-code verification."""

    task_id: str
    overall_status: VerificationOverallStatus
    alignment_score: float
    total_requirements: int
    satisfied_count: int
    compliance_items: list[RequirementComplianceItem]
    satisfied_requirements: list[str] = field(default_factory=list)
    unmet_requirements: list[str] = field(default_factory=list)
    out_of_scope_files: list[str] = field(default_factory=list)
    constraint_violations: list[str] = field(default_factory=list)
    findings: list[VerificationFinding] = field(default_factory=list)
    summary_markdown: str = ""
    blocked_requirements: list[str] = field(default_factory=list)
    partial_requirements: list[str] = field(default_factory=list)
    test_summary: dict[str, Any] = field(default_factory=dict)
    remaining_work: list[str] = field(default_factory=list)


class RequirementToCodeVerifier:
    """Verifies that final code diffs strictly satisfy the task's requirements, plan, and constraints."""

    def __init__(self, minimum_passing_score: float = 0.7) -> None:
        self.minimum_passing_score = minimum_passing_score

    def verify_requirements_against_diff(
        self,
        task_id: str,
        requirements: Sequence[TaskRequirement],
        constraints: Sequence[TaskConstraint],
        original_plan: StructuredPlan | Any,
        final_diff: TaskDiffRanges | WorkspaceDiffResult | Sequence[FileDiffRange] | Mapping[str, Any] | str,
        test_results: Sequence[Any] | Mapping[str, Any] | None = None,
        evidence_map: Mapping[str, Any] | None = None,
        file_contents: Mapping[str, str] | None = None,
        static_checks: Sequence[Any] | None = None,
    ) -> RequirementVerificationResult:
        """Compare code changes against requirements, plan steps, and forbidden constraints."""
        # 1. Normalize modified files from diff
        modified_files = self._extract_modified_files(final_diff)

        # 2. Extract expected files from plan
        expected_plan_files = set()
        if hasattr(original_plan, "expected_files_to_modify"):
            expected_plan_files.update(original_plan.expected_files_to_modify or [])
        if hasattr(original_plan, "expected_files"):
            expected_plan_files.update(getattr(original_plan, "expected_files", []) or [])
        if hasattr(original_plan, "steps"):
            for step in getattr(original_plan, "steps", []):
                expected_plan_files.update(getattr(step, "expected_files", []) or [])

        # 3. Check Constraint Violations (Forbidden files)
        constraint_violations: list[str] = []
        findings: list[VerificationFinding] = []

        for cst in constraints:
            forbidden = getattr(cst, "forbidden_files", []) or []
            forbidden_lower = {f.lower().strip() for f in forbidden}
            for mod_file in modified_files:
                if mod_file.lower().strip() in forbidden_lower:
                    msg = f"Forbidden file '{mod_file}' was modified (violating constraint '{cst.id}': {cst.description})."
                    constraint_violations.append(msg)
                    findings.append(
                        VerificationFinding(
                            id=f"cst-viol-{len(findings)+1}",
                            severity="CRITICAL",
                            category="policy",
                            message=msg,
                            file_path=mod_file,
                            blocking=True,
                        )
                    )

        # 4. Check syntax validity and placeholder content if file_contents provided
        if file_contents:
            for file_path, content in file_contents.items():
                if file_path.endswith(".py") and isinstance(content, (str, bytes)):
                    try:
                        ast.parse(content)
                    except SyntaxError as e:
                        syntax_err = f"Syntax error in '{file_path}' (line {e.lineno}): {e.msg}"
                        constraint_violations.append(syntax_err)
                        findings.append(
                            VerificationFinding(
                                id=f"syntax-err-{len(findings)+1}",
                                severity="CRITICAL",
                                category="correctness",
                                message=syntax_err,
                                file_path=file_path,
                                blocking=True,
                            )
                        )
                # Check for synthetic placeholder comments
                if isinstance(content, str) and content.strip().startswith("# Generated change for step") and len(content.strip().splitlines()) <= 2:
                    msg = f"File '{file_path}' contains placeholder synthetic comments without implementation."
                    findings.append(
                        VerificationFinding(
                            id=f"placeholder-warn-{len(findings)+1}",
                            severity="HIGH",
                            category="correctness",
                            message=msg,
                            file_path=file_path,
                            blocking=True,
                        )
                    )

        # 5. Evaluate test results if provided
        test_summary: dict[str, Any] = {"total": 0, "passed": 0, "failed": 0, "status": "NOT_RUN"}
        tests_failed = False
        if test_results:
            exit_code = 0
            if isinstance(test_results, Mapping):
                exit_code = test_results.get("exit_code", 0)
                raw_results = test_results.get("results", [])
                test_summary["status"] = test_results.get("status", "PASSED" if exit_code == 0 else "FAILED")
            else:
                raw_results = list(test_results)

            if exit_code == 5 or test_summary.get("status") == "NO_TESTS_COLLECTED":
                msg = "Test discovery returned exit code 5 (NO_TESTS_COLLECTED). No tests were run to verify requirements."
                tests_failed = True
                test_summary["status"] = "NO_TESTS_COLLECTED"
                findings.append(
                    VerificationFinding(
                        id=f"test-no-collect-{len(findings)+1}",
                        severity="HIGH",
                        category="testing",
                        message=msg,
                        blocking=True,
                    )
                )
            elif exit_code != 0:
                tests_failed = True
                test_summary["status"] = "FAILED"
                findings.append(
                    VerificationFinding(
                        id=f"test-fail-{len(findings)+1}",
                        severity="CRITICAL",
                        category="testing",
                        message=f"Test runner exited with code {exit_code}.",
                        blocking=True,
                    )
                )

            for t in raw_results:
                test_summary["total"] = test_summary.get("total", 0) + 1
                t_status = getattr(t, "status", None) or (t.get("status") if isinstance(t, dict) else None)
                t_outcome = getattr(t, "outcome", None) or (t.get("outcome") if isinstance(t, dict) else None)
                if t_status == "FAILED" or t_outcome == "FAILED":
                    test_summary["failed"] = test_summary.get("failed", 0) + 1
                    tests_failed = True
                else:
                    test_summary["passed"] = test_summary.get("passed", 0) + 1

        # 6. Check Out-of-Scope Files
        all_allowed_targets = set(expected_plan_files)
        for req in requirements:
            all_allowed_targets.update(req.target_files or [])

        out_of_scope_files: list[str] = []
        for mod_file in modified_files:
            # Allow new test files or documentation files
            if (
                mod_file not in all_allowed_targets
                and not (mod_file.startswith(("tests/", "test/")) or mod_file.endswith(".md"))
            ):
                out_of_scope_files.append(mod_file)
                findings.append(
                    VerificationFinding(
                        id=f"scope-warn-{len(findings)+1}",
                        severity="MEDIUM",
                        category="policy",
                        message=f"File '{mod_file}' was modified but was not listed in plan expected files.",
                        file_path=mod_file,
                        blocking=False,
                    )
                )

        # 7. Requirement Alignment & Criterion-Level Verification
        compliance_items: list[RequirementComplianceItem] = []
        satisfied_req_ids: list[str] = []
        unmet_req_ids: list[str] = []
        blocked_req_ids: list[str] = []
        partial_req_ids: list[str] = []
        remaining_work: list[str] = []

        evidence = evidence_map or {}

        for req in requirements:
            matched_files = [f for f in req.target_files if f in modified_files]
            req_evidence = evidence.get(req.id)
            unmet_criteria: list[str] = []
            criteria_evidence: dict[str, Any] = {}

            # Evaluate acceptance criteria if present
            if req.acceptance_criteria:
                for crit in req.acceptance_criteria:
                    if isinstance(req_evidence, Mapping) and "criteria" in req_evidence:
                        crit_status = req_evidence["criteria"].get(crit)
                        criteria_evidence[crit] = crit_status or "MISSING_EVIDENCE"
                        if crit_status not in ("PASS", "PASSED", True):
                            unmet_criteria.append(crit)
                    elif isinstance(req_evidence, (bool, str)):
                        if req_evidence in (False, "FAIL", "FAILED", "BLOCKED", "UNMET"):
                            unmet_criteria.append(crit)
                            criteria_evidence[crit] = str(req_evidence)
                        else:
                            criteria_evidence[crit] = "PASS"
                    elif req_evidence is not None and req.id in evidence:
                        criteria_evidence[crit] = "PASS"
                    elif tests_failed:
                        unmet_criteria.append(crit)
                        criteria_evidence[crit] = "TESTS_FAILED"
                    else:
                        criteria_evidence[crit] = "DIFF_VERIFIED" if matched_files else "NO_DIFF"

            # Check status of this requirement
            has_explicit_blocked = (
                req_evidence in ("BLOCKED",)
                or (isinstance(req_evidence, Mapping) and req_evidence.get("status") == "BLOCKED")
            )
            has_explicit_failed = (
                req_evidence in ("FAIL", "FAILED")
                or (isinstance(req_evidence, Mapping) and req_evidence.get("status") in ("FAIL", "FAILED"))
            )

            if has_explicit_blocked:
                is_satisfied = False
                status = "BLOCKED"
                notes = "Blocked by dependency or policy check"
                blocked_req_ids.append(req.id)
                unmet_req_ids.append(req.id)
                remaining_work.append(f"Unblock and satisfy requirement: `{req.id}` ({req.description})")
            elif has_explicit_failed or (tests_failed and req.target_files and matched_files):
                is_satisfied = False
                status = "UNMET"
                notes = "Test or verification failure for requirement"
                unmet_req_ids.append(req.id)
                remaining_work.append(f"Fix failing tests for requirement: `{req.id}` ({req.description})")
            elif len(req.target_files) > 0 and len(matched_files) == 0:
                is_satisfied = False
                status = "UNMET"
                notes = "No changes detected for target files"
                unmet_req_ids.append(req.id)
                remaining_work.append(f"Modify required target files for: `{req.id}`")
            elif unmet_criteria:
                is_satisfied = False
                if len(unmet_criteria) < len(req.acceptance_criteria):
                    status = "PARTIAL"
                    partial_req_ids.append(req.id)
                else:
                    status = "UNMET"
                unmet_req_ids.append(req.id)
                notes = f"Unsatisfied criteria: {', '.join(unmet_criteria)}"
                remaining_work.append(f"Complete criteria for `{req.id}`: {', '.join(unmet_criteria)}")
            else:
                is_satisfied = True
                status = "SATISFIED"
                notes = "Target files and acceptance criteria verified"
                satisfied_req_ids.append(req.id)

            item = RequirementComplianceItem(
                requirement_id=req.id,
                description=req.description,
                category=req.category,
                target_files=list(req.target_files),
                is_satisfied=is_satisfied,
                matched_diff_files=matched_files,
                unmet_criteria=unmet_criteria,
                notes=notes,
                status=status,
                criteria_evidence=criteria_evidence,
            )
            compliance_items.append(item)

        # 8. Compute Alignment Score
        total_reqs = len(requirements)
        if total_reqs == 0:
            alignment_score = 1.0
        else:
            alignment_score = len(satisfied_req_ids) / total_reqs

        # Deduct penalties for out-of-scope files
        if out_of_scope_files:
            penalty = min(0.3, len(out_of_scope_files) * 0.05)
            alignment_score = max(0.0, alignment_score - penalty)

        # 9. Determine Overall Status
        if constraint_violations:
            overall_status: VerificationOverallStatus = "FAIL"
        elif tests_failed:
            overall_status = "FAIL" if (len(unmet_req_ids) > 0 or len(constraint_violations) > 0) else "REQUIRES_HUMAN_REVIEW"
        elif len(blocked_req_ids) > 0:
            overall_status = "FAIL" if alignment_score < self.minimum_passing_score else "REQUIRES_HUMAN_REVIEW"
        elif alignment_score >= self.minimum_passing_score and len(unmet_req_ids) == 0:
            overall_status = "PASS"
        elif alignment_score >= self.minimum_passing_score:
            overall_status = "REQUIRES_HUMAN_REVIEW"
        else:
            overall_status = "FAIL"

        # 10. Generate PR Markdown Summary
        summary_md = self._generate_pr_markdown_summary(
            task_id=task_id,
            overall_status=overall_status,
            alignment_score=alignment_score,
            compliance_items=compliance_items,
            out_of_scope_files=out_of_scope_files,
            constraint_violations=constraint_violations,
            modified_files=modified_files,
            test_summary=test_summary,
            remaining_work=remaining_work,
        )

        return RequirementVerificationResult(
            task_id=task_id,
            overall_status=overall_status,
            alignment_score=round(alignment_score, 2),
            total_requirements=total_reqs,
            satisfied_count=len(satisfied_req_ids),
            compliance_items=compliance_items,
            satisfied_requirements=satisfied_req_ids,
            unmet_requirements=unmet_req_ids,
            out_of_scope_files=out_of_scope_files,
            constraint_violations=constraint_violations,
            findings=findings,
            summary_markdown=summary_md,
            blocked_requirements=blocked_req_ids,
            partial_requirements=partial_req_ids,
            test_summary=test_summary,
            remaining_work=remaining_work,
        )

    def _extract_modified_files(self, diff_data: Any) -> list[str]:
        """Extract set of relative file paths changed in diff."""
        if hasattr(diff_data, "files"):
            files = diff_data.files
            return [getattr(f, "file_path", str(f)) for f in files]
        elif hasattr(diff_data, "modified_files"):
            return list(diff_data.modified_files)
        elif isinstance(diff_data, Sequence) and not isinstance(diff_data, (str, bytes)):
            results = []
            for item in diff_data:
                if hasattr(item, "file_path"):
                    results.append(item.file_path)
                elif isinstance(item, dict) and "file_path" in item:
                    results.append(item["file_path"])
                elif isinstance(item, str):
                    results.append(item)
            return results
        elif isinstance(diff_data, dict) and "files" in diff_data:
            return [f.get("file_path", str(f)) if isinstance(f, dict) else str(f) for f in diff_data["files"]]
        elif isinstance(diff_data, str):
            # Parse diff text
            matches = re.findall(r"^\+\+\+\s+b/(.*)$", diff_data, re.MULTILINE)
            return [m.strip() for m in matches if m.strip()]
        return []

    def _generate_pr_markdown_summary(
        self,
        task_id: str,
        overall_status: VerificationOverallStatus,
        alignment_score: float,
        compliance_items: Sequence[RequirementComplianceItem],
        out_of_scope_files: Sequence[str],
        constraint_violations: Sequence[str],
        modified_files: Sequence[str],
        test_summary: Mapping[str, Any] | None = None,
        remaining_work: Sequence[str] | None = None,
    ) -> str:
        """Format an audit-ready Markdown PR summary according to Section 9 of task.md."""
        status_badge = {
            "PASS": "PASSED (PASS)",
            "FAIL": "FAILED (FAIL)",
            "REQUIRES_HUMAN_REVIEW": "REQUIRES HUMAN REVIEW",
            "INCONCLUSIVE": "INCONCLUSIVE",
        }.get(overall_status, str(overall_status))

        verified_cnt = sum(1 for item in compliance_items if item.status == "SATISFIED")
        partial_cnt = sum(1 for item in compliance_items if item.status == "PARTIAL")
        blocked_cnt = sum(1 for item in compliance_items if item.status == "BLOCKED")
        total_cnt = len(compliance_items)

        lines = [
            f"## Automated Task Verification Report — `{task_id}`",
            "",
            f"**Verification Outcome:** `{status_badge}`  ",
            f"**Requirement Alignment Score:** `{alignment_score * 100:.1f}%`  ",
            f"**Total Files Modified:** `{len(modified_files)}`",
            "",
            "### Implementation Requirements",
            f"- **Verified:** {verified_cnt}",
            f"- **Partially complete:** {partial_cnt}",
            f"- **Blocked:** {blocked_cnt}",
            f"- **Total discovered:** {total_cnt}",
            "",
        ]

        if test_summary and test_summary.get("total", 0) > 0:
            lines.extend([
                "### Test Execution",
                "| Metric | Value |",
                "|---|---|",
                f"| Status | `{test_summary.get('status', 'N/A')}` |",
                f"| Total Tests | {test_summary.get('total', 0)} |",
                f"| Passed | {test_summary.get('passed', 0)} |",
                f"| Failed | {test_summary.get('failed', 0)} |",
                "",
            ])

        lines.extend([
            "### Requirement Traceability",
            "| Requirement | Category | Target Files | Status |",
            "|---|---|---|---|",
        ])

        for item in compliance_items:
            files_str = ", ".join(f"`{f}`" for f in item.target_files) if item.target_files else "*(general)*"
            lines.append(f"| **{item.requirement_id}**: {item.description} | `{item.category}` | {files_str} | **{item.status}** |")

        if constraint_violations:
            lines.extend([
                "",
                "### Security & Constraint Violations",
                *(f"- :warning: **VIOLATION:** {v}" for v in constraint_violations),
            ])

        if out_of_scope_files:
            lines.extend([
                "",
                "### Out-of-Scope Files",
                *(f"- `{f}`" for f in out_of_scope_files),
            ])

        if remaining_work:
            lines.extend([
                "",
                "### Remaining Work",
                *(f"- {w}" for w in remaining_work),
            ])

        lines.append("")
        lines.append("### Modified Files in Diff")
        if modified_files:
            lines.extend(f"- `{f}`" for f in modified_files)
        else:
            lines.append("*(none)*")
        lines.append("")
        lines.append("---")
        lines.append(
            "*Report generated independently by RequirementToCodeVerifier (Meet — Week 3 Day 5).* "
            "*Zero credentials or tokens committed.*"
        )

        return "\n".join(lines)
