"""Task Plan Completeness & Gap Checker.

Owner: Meet & Dev (task.md §5 A, Phase 2).
Validates that a generated StructuredPlan covers all mandatory requirements, affected modules,
security rules, migrations, tests, and acceptance criteria before human approval or execution.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

from ai.services.task_requirement_discovery import DiscoveredTaskRequirement
from app.schemas.plan import PlanStep, StructuredPlan

logger = logging.getLogger(__name__)


@dataclass
class CompletenessIssue:
    """A detected gap or defect in plan requirement coverage."""

    requirement_id: str
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    message: str
    suggested_step_type: str = "modify"


@dataclass
class PlanCompletenessReport:
    """Comprehensive audit report on plan requirement coverage."""

    is_complete: bool
    total_requirements: int
    covered_requirements_count: int
    missing_critical_count: int
    covered_requirement_ids: list[str] = field(default_factory=list)
    uncovered_requirement_ids: list[str] = field(default_factory=list)
    issues: list[CompletenessIssue] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_complete": self.is_complete,
            "total_requirements": self.total_requirements,
            "covered_requirements_count": self.covered_requirements_count,
            "missing_critical_count": self.missing_critical_count,
            "covered_requirement_ids": self.covered_requirement_ids,
            "uncovered_requirement_ids": self.uncovered_requirement_ids,
            "issues": [
                {
                    "requirement_id": iss.requirement_id,
                    "severity": iss.severity,
                    "message": iss.message,
                    "suggested_step_type": iss.suggested_step_type,
                }
                for iss in self.issues
            ],
            "summary": self.summary,
        }


class TaskCompletenessChecker:
    """Verifies that a StructuredPlan satisfies all discovered task requirements."""

    def __init__(self) -> None:
        pass

    def check_plan_completeness(
        self,
        plan: StructuredPlan,
        requirements: Sequence[DiscoveredTaskRequirement],
    ) -> PlanCompletenessReport:
        """Compare plan steps and target files against required task behaviors."""
        total_reqs = len(requirements)
        covered_ids: list[str] = []
        uncovered_ids: list[str] = []
        issues: list[CompletenessIssue] = []
        missing_critical = 0

        # Index plan steps by files, target symbols, and description text
        plan_steps = getattr(plan, "steps", []) or []
        plan_files: set[str] = set()
        plan_symbols: set[str] = set()
        step_descriptions: list[str] = []

        for step in plan_steps:
            for f in getattr(step, "expected_files", []) or []:
                plan_files.add(f.lower().strip())
            for s in getattr(step, "target_symbols", []) or []:
                plan_symbols.add(s.lower().strip())
            step_descriptions.append((getattr(step, "description", "") or "").lower())

        for req in requirements:
            # Check if requirement is covered by at least one step
            req_covered = False

            # Check 1: Explicit requirement_ids on step if populated
            for step in plan_steps:
                step_reqs = getattr(step, "requirement_ids", []) or []
                if req.requirement_id in step_reqs:
                    req_covered = True
                    break

            # Check 2: File overlap or category-specific step exists
            if not req_covered:
                req_files = [f.lower().strip() for f in req.affected_files]
                file_overlap = any(rf in plan_files for rf in req_files) if req_files else False

                if req_files:
                    # If specific target files are required, there must be file overlap in plan
                    req_covered = file_overlap
                elif req.category == "testing":
                    # Covered if test action exists or plan has tests_to_run
                    has_test_step = any(
                        getattr(s, "action_type", "") in ("test", "verify") or getattr(s, "step_type", "") in ("test", "verify")
                        for s in plan_steps
                    )
                    has_tests_to_run = bool(getattr(plan, "tests_to_run", None))
                    req_covered = has_test_step or has_tests_to_run
                elif req.category == "database":
                    req_covered = any("migration" in desc or "database" in desc for desc in step_descriptions)
                elif req.category == "security":
                    req_covered = any("security" in desc or "permission" in desc for desc in step_descriptions)
                else:
                    req_covered = any(
                        req.description.lower()[:30] in desc for desc in step_descriptions
                    )

            if req_covered:
                covered_ids.append(req.requirement_id)
            else:
                uncovered_ids.append(req.requirement_id)
                if req.priority == "CRITICAL":
                    missing_critical += 1
                issues.append(
                    CompletenessIssue(
                        requirement_id=req.requirement_id,
                        severity=req.priority,
                        message=f"Requirement '{req.requirement_id}' ({req.description}) has no assigned implementation or verification step.",
                        suggested_step_type="test" if req.category == "testing" else "modify",
                    )
                )

        is_complete = (missing_critical == 0) and (len(uncovered_ids) == 0)
        summary = (
            f"Plan covers {len(covered_ids)} of {total_reqs} requirements. "
            f"Missing critical requirements: {missing_critical}."
        )

        return PlanCompletenessReport(
            is_complete=is_complete,
            total_requirements=total_reqs,
            covered_requirements_count=len(covered_ids),
            missing_critical_count=missing_critical,
            covered_requirement_ids=covered_ids,
            uncovered_requirement_ids=uncovered_ids,
            issues=issues,
            summary=summary,
        )

