"""Task Impact Analyzer — Repository Impact & Blast Radius for Task Planning.

Owner: Meet & Prit (task.md §5 A, §7, Phase 7).
Analyzes code change blast radius across symbols, callers, callees, API endpoints,
database models, and determines the 3-tiered test execution scope (step, impact, final).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.schemas.planner_context import AffectedSymbol, RiskLevel
from scanner.symbol_blast_radius import SymbolBlastRadiusEngine
from scanner.symbols import Symbol, SymbolEdge

logger = logging.getLogger(__name__)


@dataclass
class TaskImpactReport:
    """Comprehensive analysis of task implementation impact and test requirements."""

    target_files: list[str] = field(default_factory=list)
    directly_modified_symbols: list[str] = field(default_factory=list)
    direct_callers: list[str] = field(default_factory=list)
    indirect_callers: list[str] = field(default_factory=list)
    affected_files: list[str] = field(default_factory=list)
    affected_api_routes: list[str] = field(default_factory=list)
    affected_models: list[str] = field(default_factory=list)
    step_level_tests: list[str] = field(default_factory=list)
    impact_level_tests: list[str] = field(default_factory=list)
    final_level_tests: list[str] = field(default_factory=list)
    overall_risk: str = "low"
    risk_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_files": self.target_files,
            "directly_modified_symbols": self.directly_modified_symbols,
            "direct_callers": self.direct_callers,
            "indirect_callers": self.indirect_callers,
            "affected_files": self.affected_files,
            "affected_api_routes": self.affected_api_routes,
            "affected_models": self.affected_models,
            "step_level_tests": self.step_level_tests,
            "impact_level_tests": self.impact_level_tests,
            "final_level_tests": self.final_level_tests,
            "overall_risk": self.overall_risk,
            "risk_reasons": self.risk_reasons,
        }


class TaskImpactAnalyzer:
    """Computes code impact radius and multi-level test requirements for task planning."""

    def __init__(self, blast_engine: SymbolBlastRadiusEngine | None = None) -> None:
        self.blast_engine = blast_engine or SymbolBlastRadiusEngine()

    def analyze_impact(
        self,
        target_files: Sequence[str],
        symbols: Sequence[Symbol] | None = None,
        edges: Sequence[SymbolEdge] | None = None,
        existing_tests: Sequence[str] | None = None,
    ) -> TaskImpactReport:
        """Calculate blast radius and multi-tiered validation scopes."""
        norm_targets = [f.replace("\\", "/").lstrip("/") for f in target_files]
        symbols_list = list(symbols or [])
        edges_list = list(edges or [])
        tests_list = list(existing_tests or [])

        # 1. Directly modified symbols
        direct_symbols: list[str] = []
        for s in symbols_list:
            sf = getattr(s, "file_path", "").replace("\\", "/").lstrip("/")
            if sf in norm_targets:
                direct_symbols.append(getattr(s, "name", ""))

        # 2. Call graph traversal for callers and callees
        caller_map: dict[str, list[str]] = {}
        for edge in edges_list:
            caller_name = getattr(edge, "caller_symbol", "")
            callee_name = getattr(edge, "callee_symbol", "")
            if callee_name and caller_name:
                caller_map.setdefault(callee_name, []).append(caller_name)

        direct_callers: set[str] = set()
        for sym_name in direct_symbols:
            for c in caller_map.get(sym_name, []):
                direct_callers.add(c)

        indirect_callers: set[str] = set()
        for c in direct_callers:
            for ind in caller_map.get(c, []):
                if ind not in direct_callers and ind not in direct_symbols:
                    indirect_callers.add(ind)

        # 3. Identify affected API routes and models
        affected_routes: list[str] = []
        affected_models: list[str] = []
        for f in norm_targets:
            f_lower = f.lower()
            if "api" in f_lower or "router" in f_lower or "endpoint" in f_lower:
                affected_routes.append(f)
            if "model" in f_lower or "schema" in f_lower or "entity" in f_lower:
                affected_models.append(f)

        # 4. Determine 3-tiered test execution scopes (task.md §7)
        step_tests: list[str] = []
        impact_tests: list[str] = []
        final_tests: list[str] = []

        for t in tests_list:
            t_lower = t.lower()
            # Step-level: tests directly matching target files
            target_bases = [f.rsplit("/", 1)[-1].split(".")[0] for f in norm_targets]
            if any(b in t_lower for b in target_bases):
                step_tests.append(t)
            elif any(c.lower() in t_lower for c in direct_callers):
                impact_tests.append(t)
            else:
                final_tests.append(t)

        # If no tests match step-level directly, include available unit tests
        if not step_tests and tests_list:
            step_tests = [t for t in tests_list if "unit" in t.lower()][:3] or [tests_list[0]]

        # 5. Risk Assessment
        risk = "low"
        risk_reasons: list[str] = []
        if len(direct_callers) > 5 or len(norm_targets) > 3:
            risk = "high"
            risk_reasons.append(f"High fan-out: {len(direct_callers)} callers and {len(norm_targets)} target files")
        elif len(direct_callers) > 0 or len(affected_routes) > 0 or len(affected_models) > 0:
            risk = "medium"
            if direct_callers:
                risk_reasons.append(f"Downstream callers affected: {len(direct_callers)}")
            if affected_routes:
                risk_reasons.append(f"Public API routes affected: {len(affected_routes)}")
            if affected_models:
                risk_reasons.append(f"Persistence models affected: {len(affected_models)}")

        return TaskImpactReport(
            target_files=norm_targets,
            directly_modified_symbols=sorted(direct_symbols),
            direct_callers=sorted(direct_callers),
            indirect_callers=sorted(indirect_callers),
            affected_files=sorted(set(norm_targets)),
            affected_api_routes=affected_routes,
            affected_models=affected_models,
            step_level_tests=step_tests,
            impact_level_tests=impact_tests,
            final_level_tests=final_tests,
            overall_risk=risk,
            risk_reasons=risk_reasons,
        )


__all__ = ["TaskImpactAnalyzer", "TaskImpactReport"]

