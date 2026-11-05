"""Task Acceptance Criteria to Test Scenario Mapper.

Owner: Meet & Prit (task.md §5 A, §7, Phase 7).
Translates atomic task requirements and acceptance criteria into concrete
test scenarios across positive, negative, boundary, security, and regression categories.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ai.services.task_requirement_discovery import DiscoveredTaskRequirement

logger = logging.getLogger(__name__)


@dataclass
class TestScenarioSpec:
    """Detailed specification for an individual test scenario."""

    scenario_id: str
    requirement_id: str
    scenario_type: str  # positive, negative, boundary, security, regression
    title: str
    description: str
    inputs: dict[str, Any] = field(default_factory=dict)
    expected_assertions: list[str] = field(default_factory=list)
    suggested_test_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "requirement_id": self.requirement_id,
            "scenario_type": self.scenario_type,
            "title": self.title,
            "description": self.description,
            "inputs": self.inputs,
            "expected_assertions": self.expected_assertions,
            "suggested_test_name": self.suggested_test_name,
        }


@dataclass
class TaskAcceptanceMatrix:
    """Matrix of test scenarios fulfilling task acceptance criteria."""

    scenarios: list[TestScenarioSpec] = field(default_factory=list)
    requirement_scenario_count: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenarios": [s.to_dict() for s in self.scenarios],
            "requirement_scenario_count": self.requirement_scenario_count,
            "total_scenarios": len(self.scenarios),
        }


class TaskAcceptanceMapper:
    """Maps discovered requirements into comprehensive test scenario matrices."""

    def __init__(self) -> None:
        pass

    def map_requirements_to_scenarios(
        self,
        requirements: Sequence[DiscoveredTaskRequirement],
    ) -> TaskAcceptanceMatrix:
        """Derive positive, negative, boundary, security, and regression scenarios."""
        scenarios: list[TestScenarioSpec] = []
        counts: dict[str, int] = {}

        for req in requirements:
            rid = req.requirement_id
            cat = req.category.lower()
            counts[rid] = 0

            # 1. Positive Scenario (Happy Path)
            sc_pos = TestScenarioSpec(
                scenario_id=f"SC-{rid}-POS",
                requirement_id=rid,
                scenario_type="positive",
                title=f"Valid execution for {req.description[:60]}",
                description=f"Asserts expected behavior under valid inputs for: {req.description}",
                expected_assertions=[
                    "Operation succeeds with status 200/OK",
                    "Returned state matches acceptance criteria",
                ] + (req.acceptance_criteria[:2] if req.acceptance_criteria else ["Output matches contract"]),
                suggested_test_name=f"test_{rid.lower().replace('-', '_')}_happy_path",
            )
            scenarios.append(sc_pos)
            counts[rid] += 1

            # 2. Negative Scenario (Error Handling)
            sc_neg = TestScenarioSpec(
                scenario_id=f"SC-{rid}-NEG",
                requirement_id=rid,
                scenario_type="negative",
                title=f"Rejection of invalid input for {req.description[:60]}",
                description="Asserts clean error handling and rejection of malformed requests.",
                expected_assertions=[
                    "Invalid input raises validation error / 400 Bad Request",
                    "No partial or corrupted state is persisted",
                ],
                suggested_test_name=f"test_{rid.lower().replace('-', '_')}_invalid_input",
            )
            scenarios.append(sc_neg)
            counts[rid] += 1

            # 3. Boundary Scenario
            sc_bnd = TestScenarioSpec(
                scenario_id=f"SC-{rid}-BND",
                requirement_id=rid,
                scenario_type="boundary",
                title=f"Boundary limits for {req.description[:60]}",
                description="Tests upper, lower, empty, and zero boundaries.",
                expected_assertions=[
                    "Boundary conditions handled gracefully without unhandled exceptions",
                ],
                suggested_test_name=f"test_{rid.lower().replace('-', '_')}_boundary",
            )
            scenarios.append(sc_bnd)
            counts[rid] += 1

            # 4. Security / Authorization Scenario if applicable
            if cat in ("authorization", "security", "api") or any("auth" in f for f in req.affected_files):
                sc_sec = TestScenarioSpec(
                    scenario_id=f"SC-{rid}-SEC",
                    requirement_id=rid,
                    scenario_type="security",
                    title=f"Access control & privilege boundary for {req.description[:60]}",
                    description="Asserts unauthenticated or unauthorized access is denied.",
                    expected_assertions=[
                        "Unauthorized request blocked with 401/403 status code",
                        "No sensitive details leaked in error payload",
                    ],
                    suggested_test_name=f"test_{rid.lower().replace('-', '_')}_security_forbidden",
                )
                scenarios.append(sc_sec)
                counts[rid] += 1

        return TaskAcceptanceMatrix(scenarios=scenarios, requirement_scenario_count=counts)


__all__ = ["TaskAcceptanceMapper", "TaskAcceptanceMatrix", "TestScenarioSpec"]

