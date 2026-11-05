"""Task Requirement Discovery Engine.

Owner: Meet & Dev (task.md §2, §5 A, Phase 2).
Decomposes user tasks, GitHub issues, and bug findings into atomic, traceable,
and verifiable task requirements across architectural, security, database, and testing categories.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.core.secret_redaction import redact
from app.models.task import AgentTask

from ai.context.task_context import TaskContextManifest

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredTaskRequirement:
    """Atomic task requirement with acceptance criteria and test traceability."""

    requirement_id: str
    description: str
    category: str  # implementation, api, authorization, database, migration, frontend, testing, documentation, security, verification
    priority: str  # CRITICAL, HIGH, MEDIUM, LOW
    source_evidence: list[str] = field(default_factory=list)
    affected_files: list[str] = field(default_factory=list)
    affected_symbols: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    required_tests: list[str] = field(default_factory=list)
    status: str = "REQUIRED"  # REQUIRED, CONDITIONAL, NOT_APPLICABLE, BLOCKED, DEFERRED

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "description": self.description,
            "category": self.category,
            "priority": self.priority,
            "source_evidence": self.source_evidence,
            "affected_files": self.affected_files,
            "affected_symbols": self.affected_symbols,
            "dependencies": self.dependencies,
            "acceptance_criteria": self.acceptance_criteria,
            "required_tests": self.required_tests,
            "status": self.status,
        }


class TaskRequirementDiscovery:
    """Discovers verifiable engineering requirements from task metadata and repository context."""

    def __init__(self) -> None:
        pass

    def discover_requirements(
        self,
        task: AgentTask,
        context: TaskContextManifest,
    ) -> list[DiscoveredTaskRequirement]:
        """Produce an atomic, categorized, and verifiable requirement matrix for the task."""
        requirements: list[DiscoveredTaskRequirement] = []
        task_title = getattr(task, "title", "") or ""
        task_desc = getattr(task, "description", "") or ""
        text_corpus = f"{task_title}\n{task_desc}".lower()

        req_counter = 1

        # 1. Ingest explicit user requirements from task intake
        for raw_req in getattr(task, "requirements", []) or []:
            r_id = (raw_req.get("id") or raw_req.get("requirement_id")) if isinstance(raw_req, dict) else (getattr(raw_req, "id", None) or getattr(raw_req, "requirement_id", None))
            r_desc = raw_req.get("description") if isinstance(raw_req, dict) else getattr(raw_req, "description", "")
            r_cat = raw_req.get("category", "implementation") if isinstance(raw_req, dict) else getattr(raw_req, "category", "implementation")
            r_files = raw_req.get("target_files", []) if isinstance(raw_req, dict) else getattr(raw_req, "target_files", [])
            r_criteria = raw_req.get("acceptance_criteria", []) if isinstance(raw_req, dict) else getattr(raw_req, "acceptance_criteria", [])
            r_prio = raw_req.get("priority", "HIGH") if isinstance(raw_req, dict) else getattr(raw_req, "priority", "HIGH")

            if r_desc:
                rid = r_id or f"REQ-TASK-{req_counter:03d}"
                req_counter += 1
                if not r_criteria:
                    r_criteria = [f"Code changes in {', '.join(r_files) or 'target files'} satisfy: {r_desc}"]
                requirements.append(
                    DiscoveredTaskRequirement(
                        requirement_id=rid,
                        description=redact(r_desc),
                        category=r_cat,
                        priority=r_prio.upper() if r_prio else "HIGH",
                        source_evidence=[f"Task intake requirement: '{r_desc[:80]}'"],
                        affected_files=list(r_files) if r_files else list(context.target_files),
                        affected_symbols=list(context.retrieved_symbols[:3]),
                        acceptance_criteria=list(r_criteria),
                        required_tests=[context.test_command],
                        status="REQUIRED",
                    )
                )

        # 2. If no explicit requirements, generate core implementation requirement
        if not requirements:
            rid = f"REQ-CORE-{req_counter:03d}"
            req_counter += 1
            requirements.append(
                DiscoveredTaskRequirement(
                    requirement_id=rid,
                    description=f"Implement requested changes for: {task_title or 'task'}",
                    category="implementation",
                    priority="CRITICAL",
                    source_evidence=[f"Task title: '{task_title}'"],
                    affected_files=list(context.target_files),
                    affected_symbols=list(context.retrieved_symbols[:3]),
                    acceptance_criteria=[
                        f"Modify {', '.join(context.target_files)} to fulfill task specification without regressions"
                    ],
                    required_tests=[context.test_command],
                    status="REQUIRED",
                )
            )

        # 3. Detect Security & Authorization Needs
        has_auth = any(k in text_corpus for k in ("auth", "role", "permission", "rbac", "jwt", "token", "access control"))
        if has_auth:
            rid = f"REQ-SEC-{req_counter:03d}"
            req_counter += 1
            requirements.append(
                DiscoveredTaskRequirement(
                    requirement_id=rid,
                    description="Enforce authorization checks and tenant data isolation",
                    category="security",
                    priority="CRITICAL",
                    source_evidence=["Task mentions authentication/authorization keywords"],
                    affected_files=[f for f in context.target_files if "auth" in f.lower() or "api" in f.lower()] or context.target_files,
                    affected_symbols=["require_auth", "check_permission"],
                    acceptance_criteria=[
                        "Unauthorized and forbidden requests are rejected with appropriate HTTP error codes",
                        "No credentials or private keys leaked in tracebacks or responses",
                    ],
                    required_tests=[f"{context.test_command} -k auth"],
                    status="REQUIRED",
                )
            )

        # 4. Detect Database & Migration Needs
        has_db = any(k in text_corpus for k in ("migration", "schema", "database", "model", "table", "column", "alembic"))
        if has_db:
            rid = f"REQ-DB-{req_counter:03d}"
            req_counter += 1
            requirements.append(
                DiscoveredTaskRequirement(
                    requirement_id=rid,
                    description="Safely apply database schema updates and reversible migrations",
                    category="database",
                    priority="HIGH",
                    source_evidence=["Task mentions database schema or migration updates"],
                    affected_files=[f for f in context.target_files if "model" in f.lower() or "migration" in f.lower()],
                    affected_symbols=["Base", "metadata"],
                    acceptance_criteria=[
                        "Database models match schema migrations with zero drift",
                        "Migrations support clean upgrade and rollback",
                    ],
                    required_tests=["pytest backend/tests/test_migration_smoke.py"],
                    status="CONDITIONAL",
                )
            )

        # 5. Detect Frontend UI Needs
        has_frontend = any(k in text_corpus for k in ("frontend", "ui", "component", "button", "page", "react", "view", "modal"))
        if has_frontend or any(f.startswith("frontend/") for f in context.target_files):
            rid = f"REQ-UI-{req_counter:03d}"
            req_counter += 1
            requirements.append(
                DiscoveredTaskRequirement(
                    requirement_id=rid,
                    description="Update frontend components, validation, and user feedback",
                    category="frontend",
                    priority="HIGH",
                    source_evidence=["Task references frontend/UI components or routes"],
                    affected_files=[f for f in context.target_files if f.startswith("frontend/")],
                    affected_symbols=["Component"],
                    acceptance_criteria=[
                        "UI correctly displays loading, success, and error states",
                        "Oxlint passes with 0 errors and 0 warnings",
                    ],
                    required_tests=["npm run build"],
                    status="REQUIRED",
                )
            )

        # 6. Mandatory Test Verification Requirement (task.md §7)
        rid = f"REQ-TEST-{req_counter:03d}"
        req_counter += 1
        requirements.append(
            DiscoveredTaskRequirement(
                requirement_id=rid,
                description="Comprehensive unit, integration, and regression test validation",
                category="testing",
                priority="CRITICAL",
                source_evidence=[f"Repository test conventions: `{context.test_command}`"],
                affected_files=list(context.existing_tests[:3]),
                affected_symbols=[],
                acceptance_criteria=[
                    "Tests are collected and executed in isolated sandbox",
                    "No test failures or regressions introduced by changes",
                ],
                required_tests=[context.test_command],
                status="REQUIRED",
            )
        )

        return requirements

