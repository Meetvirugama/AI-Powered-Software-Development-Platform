"""backend/agent/specialized/dispatcher.py

Intelligent multi-agent dispatcher routing tasks and execution steps
to specialized engineering roles based on intent, file patterns, and action types.
Part of Phase 3 (Specialized Multi-Agent Architecture).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from agent.specialized.base import SpecializedAgentRole, SpecializedAgentSpec
from agent.specialized.backend_agent import create_backend_agent_spec
from agent.specialized.frontend_agent import create_frontend_agent_spec
from agent.specialized.database_agent import create_database_agent_spec
from agent.specialized.testing_agent import create_testing_agent_spec
from ai.services.intent_router import TaskIntent

logger = logging.getLogger(__name__)


class AgentDispatcher:
    """Dispatches execution steps to the most appropriate specialized agent."""

    def __init__(self) -> None:
        self._specs: dict[SpecializedAgentRole, SpecializedAgentSpec] = {
            SpecializedAgentRole.BACKEND: create_backend_agent_spec(),
            SpecializedAgentRole.FRONTEND: create_frontend_agent_spec(),
            SpecializedAgentRole.DATABASE: create_database_agent_spec(),
            SpecializedAgentRole.TESTING: create_testing_agent_spec(),
        }

    def get_agent(self, role: SpecializedAgentRole) -> SpecializedAgentSpec:
        """Retrieve the agent specification for a designated role."""
        if role not in self._specs:
            return self._specs[SpecializedAgentRole.BACKEND]
        return self._specs[role]

    def dispatch_for_files(self, file_paths: list[str]) -> SpecializedAgentSpec:
        """Route to an agent based on targeted file paths."""
        if not file_paths:
            return self._specs[SpecializedAgentRole.BACKEND]

        norm_paths = [f.replace("\\", "/").lower().strip() for f in file_paths]

        # 1. Test files take precedence if explicitly targeting test directories/files
        is_all_tests = all(
            "/test" in p or p.startswith("test") or p.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx", "_test.py"))
            for p in norm_paths
        )
        if is_all_tests:
            return self._specs[SpecializedAgentRole.TESTING]

        # 2. Database models or migrations
        is_db = any(
            "alembic" in p or "/models/" in p or p.startswith("models/") or "database" in p
            for p in norm_paths
        )
        if is_db:
            return self._specs[SpecializedAgentRole.DATABASE]

        # 3. Frontend components / web assets
        is_fe = any(
            p.startswith("frontend/")
            or p.endswith((".tsx", ".jsx", ".vue", ".svelte", ".css", ".scss", ".html"))
            for p in norm_paths
        )
        if is_fe:
            return self._specs[SpecializedAgentRole.FRONTEND]

        # 4. Default to Backend
        return self._specs[SpecializedAgentRole.BACKEND]

    def dispatch_for_step(
        self,
        action_type: str,
        expected_files: list[str] | None = None,
        task_intent: TaskIntent | str | None = None,
    ) -> SpecializedAgentSpec:
        """Select the optimal specialized agent for an execution step.

        Evaluates step action type, target files, and global task intent.
        """
        files = expected_files or []
        act = action_type.lower().strip()

        # Step 1: Explicit test execution actions
        if act in ("test", "run_test", "run_tests", "pytest", "vitest", "add_test", "verify"):
            return self._specs[SpecializedAgentRole.TESTING]

        # Step 2: Database migration actions
        if act in ("migrate", "migration", "upgrade_db", "alembic"):
            return self._specs[SpecializedAgentRole.DATABASE]

        # Step 3: Analyze file paths if present
        if files:
            file_agent = self.dispatch_for_files(files)
            # If files pinpointed a specific non-backend role, respect it
            if file_agent.role != SpecializedAgentRole.BACKEND:
                return file_agent

        # Step 4: Fall back to task intent if provided
        if task_intent is not None:
            intent_val = task_intent.value if isinstance(task_intent, TaskIntent) else str(task_intent).lower()
            if intent_val == TaskIntent.FRONTEND.value:
                return self._specs[SpecializedAgentRole.FRONTEND]
            if intent_val == TaskIntent.DATABASE.value:
                return self._specs[SpecializedAgentRole.DATABASE]
            if intent_val == TaskIntent.TESTING.value:
                return self._specs[SpecializedAgentRole.TESTING]

        # Step 5: Default to backend agent
        return self._specs[SpecializedAgentRole.BACKEND]

    def validate_agent_can_modify(
        self,
        agent: SpecializedAgentSpec,
        file_paths: list[str],
    ) -> tuple[bool, str | None]:
        """Verify whether the designated agent is authorized to modify the specified files."""
        for file_path in file_paths:
            if not agent.can_touch_file(file_path):
                return (
                    False,
                    f"Agent '{agent.name}' (role: {agent.role.value}) is not authorized to touch '{file_path}'.",
                )
        return True, None
