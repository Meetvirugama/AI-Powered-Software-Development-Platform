"""backend/ai/services/plan_critic.py

Adversarial Plan Critic for Universal AI Prompt-to-PR System.
Independently verifies and evaluates implementation plans before execution,
identifying missing tests, unaddressed requirements, database migration gaps,
forbidden file targets, and dependency anomalies.
Reference: task.md Part 5 & 17 / TASK_PLANNER_IMPLEMENTATION_PLAN.md Phase 2.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Sequence
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.plan import PlanDependencyGraph, PlanStep, StructuredPlan
from ai.services.task_requirement_discovery import DiscoveredTaskRequirement


class CriticSeverity(str, Enum):
    """Severity of an issue flagged by the Plan Critic."""

    BLOCKING = "BLOCKING"
    WARNING = "WARNING"
    INFO = "INFO"


class CriticIssue(BaseModel):
    """Specific flaw or risk detected in an implementation plan."""

    model_config = ConfigDict(extra="ignore")

    issue_id: str
    category: str = Field(..., description="Issue type: requirement_coverage, missing_tests, invalid_targets, security_risk, database_migration, dependency_cycle")
    severity: CriticSeverity
    message: str
    suggested_remedy: str


class CriticReview(BaseModel):
    """Complete evaluation outcome produced by the Plan Critic."""

    model_config = ConfigDict(extra="ignore")

    is_approved: bool = Field(..., description="Whether plan is certified safe and complete for execution.")
    score: float = Field(default=1.0, ge=0.0, le=1.0, description="Plan quality score in [0.0, 1.0].")
    summary: str
    issues: list[CriticIssue] = Field(default_factory=list)
    blocking_count: int = 0
    warning_count: int = 0


class PlanCritic:
    """Independent adversarial evaluator that challenges draft implementation plans."""

    _FORBIDDEN_FILES = {
        ".env", ".git", "id_rsa", "credentials.json",
        ".github/workflows/deploy.yml", "azure-env-production.json",
    }

    def review_plan(
        self,
        plan: StructuredPlan,
        requirements: Sequence[DiscoveredTaskRequirement] | None = None,
        repository_context: dict[str, Any] | None = None,
    ) -> CriticReview:
        """Thoroughly audit a draft plan against requirements, safety boundaries, and tests."""
        issues: list[CriticIssue] = []
        steps = getattr(plan, "steps", []) or []
        expected_files = getattr(plan, "expected_files", []) or []
        tests_to_run = getattr(plan, "tests_to_run", []) or []

        # 1. Plan must not be completely empty
        if not steps:
            issues.append(
                CriticIssue(
                    issue_id="crit-empty-plan",
                    category="invalid_targets",
                    severity=CriticSeverity.BLOCKING,
                    message="Plan has zero implementation steps.",
                    suggested_remedy="Generate at least one implementation step.",
                )
            )

        # 2. Check for unresolved localization
        has_unresolved = any(
            f == "UNRESOLVED" or getattr(s, "expected_files", []) == ["UNRESOLVED"]
            for s in steps
            for f in getattr(s, "expected_files", [])
        ) or any(f == "UNRESOLVED" for f in expected_files)

        if has_unresolved:
            issues.append(
                CriticIssue(
                    issue_id="crit-unresolved-targets",
                    category="invalid_targets",
                    severity=CriticSeverity.BLOCKING,
                    message="Plan contains UNRESOLVED localization targets. Clarification or exploratory localization required.",
                    suggested_remedy="Investigate repository files to ground specific target paths before execution.",
                )
            )

        # 3. Check for forbidden file access
        targets = set(expected_files).union(*(step.expected_files for step in steps))
        for index, path in enumerate(sorted(targets)):
            normalized = path.lower().strip()
            parts = normalized.split("/")
            if normalized in self._FORBIDDEN_FILES or any(part in self._FORBIDDEN_FILES for part in parts):
                issues.append(
                    CriticIssue(
                        issue_id=f"crit-forbidden-{index}",
                        category="security_risk",
                        severity=CriticSeverity.BLOCKING,
                        message=f"Plan targets forbidden file or secret path '{path}'.",
                        suggested_remedy="Remove protected infrastructure and credential files from plan targets.",
                    )
                )

        indexed_paths = (repository_context or {}).get("indexed_paths")
        if indexed_paths is not None:
            creation_paths = {
                path
                for step in steps if step.action_type in {"create", "create_file", "new_file", "add_file", "add_test", "create_test"}
                for path in step.expected_files
            }
            for index, path in enumerate(sorted(targets - set(indexed_paths) - creation_paths - {"UNRESOLVED"})):
                issues.append(CriticIssue(
                    issue_id=f"crit-missing-path-{index}",
                    category="invalid_targets",
                    severity=CriticSeverity.BLOCKING,
                    message=f"'{path}' is missing from the indexed revision and has no creation step.",
                    suggested_remedy="Use an indexed path or specify a file creation step.",
                ))

        # 4. Check DAG dependencies
        if steps:
            try:
                graph = PlanDependencyGraph(steps)
                graph.validate()
                graph.get_execution_order()
            except ValueError as dag_err:
                issues.append(
                    CriticIssue(
                        issue_id="crit-dag-cycle",
                        category="dependency_cycle",
                        severity=CriticSeverity.BLOCKING,
                        message=f"Dependency graph error in plan steps: {dag_err}",
                        suggested_remedy="Ensure all step dependencies form an acyclic directed graph with valid references.",
                    )
                )

        # 5. Check test verification presence
        has_test_step = any(
            getattr(s, "action_type", "") in ("test", "verify")
            or getattr(s, "step_type", "") in ("test", "verify")
            for s in steps
        )
        if not tests_to_run and not has_test_step:
            issues.append(
                CriticIssue(
                    issue_id="crit-missing-tests",
                    category="missing_tests",
                    severity=CriticSeverity.WARNING,
                    message="Plan specifies no test verification steps and tests_to_run is empty.",
                    suggested_remedy="Include test execution commands to independently verify changes.",
                )
            )

        # 6. Check database migration alignment
        modifies_models = any(
            "model" in (getattr(s, "description", "") or "").lower()
            or any("models" in f.lower() for f in (getattr(s, "expected_files", []) or []))
            for s in steps
        )
        has_migration_step = any(
            "migration" in (getattr(s, "description", "") or "").lower()
            or any("alembic" in f.lower() or "migration" in f.lower() for f in (getattr(s, "expected_files", []) or []))
            for s in steps
        )
        if modifies_models and not has_migration_step:
            issues.append(
                CriticIssue(
                    issue_id="crit-db-migration-missing",
                    category="database_migration",
                    severity=CriticSeverity.WARNING,
                    message="Plan modifies database models but includes no database migration step.",
                    suggested_remedy="Add an Alembic or schema migration step to preserve database integrity.",
                )
            )

        # 7. Check requirement coverage if requirements are provided
        if requirements:
            covered_req_ids: set[str] = set()
            for s in steps:
                for rid in getattr(s, "requirement_ids", []) or []:
                    covered_req_ids.add(rid)

            for req in requirements:
                if req.requirement_id not in covered_req_ids:
                    # Check fallback coverage via affected files
                    file_match = any(
                        af.lower() in [f.lower() for f in getattr(s, "expected_files", [])]
                        for s in steps
                        for af in req.affected_files
                    )
                    if not file_match:
                        sev = CriticSeverity.BLOCKING if req.priority == "CRITICAL" else CriticSeverity.WARNING
                        issues.append(
                            CriticIssue(
                                issue_id=f"crit-uncovered-req-{req.requirement_id}",
                                category="requirement_coverage",
                                severity=sev,
                                message=f"Requirement '{req.requirement_id}' ({req.description}) is not covered by any plan step.",
                                suggested_remedy=f"Add an implementation or verification step addressing {req.requirement_id}.",
                            )
                        )

        blocking_count = sum(1 for i in issues if i.severity == CriticSeverity.BLOCKING)
        warning_count = sum(1 for i in issues if i.severity == CriticSeverity.WARNING)

        score = max(0.0, 1.0 - (blocking_count * 0.4) - (warning_count * 0.1))
        is_approved = (blocking_count == 0)

        summary = (
            f"Plan Critic certified: {len(issues)} finding(s) "
            f"({blocking_count} blocking, {warning_count} warnings). Score: {score:.2f}."
        )

        return CriticReview(
            is_approved=is_approved,
            score=round(score, 2),
            summary=summary,
            issues=issues,
            blocking_count=blocking_count,
            warning_count=warning_count,
        )
