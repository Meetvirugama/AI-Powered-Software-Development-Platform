"""Test Requirement & Planning Service.

Fulfills task.md §6 (Phase 6 P0):
Converts discovered repository requirements, graph relationships, and gap analysis
into a structured, prioritized test plan and scenario matrix.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
from uuid import UUID

from ai.llm.schemas import LLMRequest, Message
from ai.prompts import load_prompt
from ai.schemas.prompt_builder import _fence
from app.core.errors import APIError, ErrorCode
from app.schemas.analysis import (
    TestRequirement,
    TestRequirementCategory,
    TestScenario,
)
from scanner.test_gap_analyzer import TestGapAnalysisResult

logger = logging.getLogger(__name__)


@dataclass
class PlannedTestScenario:
    """Detailed planned scenario ready for test code generation."""

    name: str
    category: str
    priority: str
    description: str
    expected_outcome: str
    mock_requirements: list[str] = field(default_factory=list)
    requirement_id: str | None = None


@dataclass
class TestPlan:
    """Repository or file-level test plan."""

    plan_id: str
    target_file: str
    framework: str
    scenarios: list[PlannedTestScenario] = field(default_factory=list)
    unsupported_scenarios: list[str] = field(default_factory=list)
    requirements: list[TestRequirement] = field(default_factory=list)


class TestRequirementService:
    """Assembles structured test plans and scenario matrices from repository intelligence."""

    __test__ = False

    def __init__(self, llm_gateway: Any = None) -> None:
        self._llm = llm_gateway

    def create_deterministic_plan(
        self,
        target_file: str,
        gap_result: TestGapAnalysisResult,
        framework: str = "pytest",
    ) -> TestPlan:
        """Create a deterministic test plan directly from prioritized requirement gaps."""
        plan_id = f"plan-{target_file.replace('/', '-').replace('.', '-')}"
        scenarios: list[PlannedTestScenario] = []
        unsupported: list[str] = []

        for req in gap_result.prioritized_gaps:
            cat = str(req.category).lower()
            sym = req.source_symbols[0] if req.source_symbols else "target"

            # Formulate conventional test name
            clean_sym = sym.replace(".", "_")
            test_name = f"test_{clean_sym}_{cat}_{req.requirement_id.lower().replace('-', '_')}"

            # Mock requirements if integration
            mocks: list[str] = []
            if cat in ("integration", "api_contract"):
                mocks.extend(["db_session", "mock_http"])

            scenarios.append(
                PlannedTestScenario(
                    name=test_name,
                    category=cat,
                    priority=str(req.priority),
                    description=f"{req.title}: {req.expected_behavior}",
                    expected_outcome=req.expected_behavior,
                    mock_requirements=mocks,
                    requirement_id=req.requirement_id,
                )
            )

        return TestPlan(
            plan_id=plan_id,
            target_file=target_file,
            framework=framework,
            scenarios=scenarios,
            unsupported_scenarios=unsupported,
            requirements=gap_result.updated_requirements,
        )

    async def plan_tests_with_ai(
        self,
        target_file: str,
        code_content: str,
        gap_result: TestGapAnalysisResult,
        framework: str = "pytest",
    ) -> TestPlan:
        """Enrich test planning using LLM intelligence with fallback to deterministic plan."""
        det_plan = self.create_deterministic_plan(target_file, gap_result, framework)
        if self._llm is None or not code_content:
            return det_plan

        try:
            sys_prompt = load_prompt("test_planning_system")
        except Exception:
            return det_plan

        user_content = (
            f"Framework: {framework}\n"
            f"Target File: {target_file}\n"
            f"Prioritized Missing Requirements:\n"
            + "\n".join(
                f"- [{r.requirement_id}] ({r.category}) {r.title}: {r.expected_behavior}"
                for r in gap_result.prioritized_gaps[:10]
            )
            + "\n\nTarget Code:\n"
            + _fence(code_content[:4000], "TARGET_SOURCE")
        )

        request = LLMRequest(
            messages=[
                Message(role="system", content=sys_prompt),
                Message(role="user", content=user_content),
            ],
            temperature=0.2,
            max_tokens=2000,
        )

        try:
            response = await self._llm.generate(request)
            raw = response.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw
                if raw.endswith("```"):
                    raw = raw[:-3]
                raw = raw.strip()

            parsed = json.loads(raw)
            ai_scenarios: list[PlannedTestScenario] = []
            for item in parsed.get("scenarios", []):
                ai_scenarios.append(
                    PlannedTestScenario(
                        name=item.get("name", "test_scenario"),
                        category=item.get("category", "functional"),
                        priority=item.get("priority", "HIGH"),
                        description=item.get("description", ""),
                        expected_outcome=item.get("expected_outcome", ""),
                        mock_requirements=item.get("mock_requirements", []),
                    )
                )

            if ai_scenarios:
                det_plan.scenarios = ai_scenarios
                det_plan.unsupported_scenarios = parsed.get("unsupported_scenarios", [])

        except Exception as exc:
            logger.warning(f"AI test planning encountered error; using deterministic plan: {exc}")

        return det_plan

