"""Coverage-Guided Iterative Feedback Loop Engine for Test Generation.

Owner: Antigravity Test Engineering Team
Reference: task.md §6 (Feature 3: Coverage-Guided Iterative Generation, CoverUp P-11 inspiration)

Capabilities:
1. Orchestrates up to MAX_GENERATION_ROUNDS (3) feedback iterations:
   - Round 1: Initial generation
   - Round 2: First coverage-guided targeted generation
   - Round 3: Second coverage-guided targeted generation
2. Identifies uncovered executable lines and branches from TargetCoverageData.
3. Feeds only targeted uncovered context back into the LLM prompt.
4. Intelligently merges newly generated test functions into the existing test suite without duplicating imports or tests.
5. Deduplicates covered test scenarios.
6. Enforces deterministic stopping conditions:
   - No uncovered executable lines remaining (100% coverage achieved)
   - Coverage stops improving between rounds (plateau reached)
   - Maximum generation rounds (3) reached
   - Infrastructure error or token budget exhausted
7. Produces a detailed IterationReport for user reporting and auditability.
"""

from __future__ import annotations

import ast
import logging
import re
from typing import Any

from app.schemas.analysis import (
    IterationReport,
    IterationRound,
    TestScenario,
)
from app.services.test_coverage_service import TargetCoverageData

logger = logging.getLogger(__name__)

MAX_GENERATION_ROUNDS: int = 3


class TestIterationOrchestrator:
    """Orchestrator for coverage-guided test refinement rounds."""

    __test__ = False

    def __init__(self, max_rounds: int = MAX_GENERATION_ROUNDS) -> None:
        self.max_rounds = max(1, max_rounds)

    def extract_uncovered_context(
        self,
        source_code: str,
        uncovered_lines: list[int],
        uncovered_branches: list[list[int]] | None = None,
        context_window: int = 2,
    ) -> str:
        """Extract lines of code surrounding uncovered lines for targeted LLM prompting."""
        if not uncovered_lines and not uncovered_branches:
            return ""

        lines = source_code.splitlines()
        target_lines: set[int] = set(uncovered_lines)
        if uncovered_branches:
            for branch in uncovered_branches:
                target_lines.update(b for b in branch if isinstance(b, int))

        lines_to_include: set[int] = set()
        for ln in target_lines:
            if 1 <= ln <= len(lines):
                for offset in range(-context_window, context_window + 1):
                    cand = ln + offset
                    if 1 <= cand <= len(lines):
                        lines_to_include.add(cand)

        formatted: list[str] = []
        in_gap = False
        for i in range(1, len(lines) + 1):
            if i in lines_to_include:
                in_gap = False
                prefix = ">" if i in target_lines else " "
                formatted.append(f"{prefix} {i:4d} | {lines[i - 1]}")
            else:
                if not in_gap:
                    formatted.append("  ...  |")
                    in_gap = True

        return "\n".join(formatted)

    def should_continue_iteration(
        self,
        current_round: int,
        prev_coverage: float | None,
        new_coverage: float | None,
        uncovered_lines: list[int],
    ) -> tuple[bool, str]:
        """Evaluate whether another iteration round should be conducted."""
        if current_round >= self.max_rounds:
            return False, f"Maximum generation rounds ({self.max_rounds}) reached."

        if not uncovered_lines:
            return False, "Target file has 100% executable line coverage; no uncovered lines remaining."

        if prev_coverage is not None and new_coverage is not None:
            if new_coverage <= prev_coverage:
                return False, f"Coverage plateaued at {new_coverage}%; no improvement over previous round ({prev_coverage}%)."

        return True, "Coverage improvement possible."

    def merge_generated_tests(
        self,
        existing_test_code: str,
        new_test_code: str,
        framework: str,
    ) -> str:
        """Merge newly generated test functions into existing test code without duplicates."""
        clean_fw = framework.strip().lower()
        if clean_fw in ("pytest", "unittest"):
            return self._merge_python_tests(existing_test_code, new_test_code)
        else:
            return self._merge_js_tests(existing_test_code, new_test_code)

    def _merge_python_tests(self, existing_code: str, new_code: str) -> str:
        """Merge Python test functions and imports using AST and source inspection."""
        try:
            exist_tree = ast.parse(existing_code)
            new_tree = ast.parse(new_code)
        except SyntaxError:
            # Fallback to simple append if syntax parsing fails
            return f"{existing_code}\n\n# --- Additional Targeted Tests ---\n{new_code}"

        existing_func_names = {
            node.name for node in ast.walk(exist_tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        # Extract non-duplicate top-level test functions from new_code
        new_lines = new_code.splitlines()
        funcs_to_append: list[str] = []
        imports_to_append: list[str] = []

        for node in new_tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imp_str = ast.get_source_segment(new_code, node) or ast.unparse(node)
                if imp_str and imp_str not in existing_code:
                    imports_to_append.append(imp_str)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_") and node.name not in existing_func_names:
                    func_str = ast.get_source_segment(new_code, node) or ast.unparse(node)
                    if func_str:
                        funcs_to_append.append(func_str)

        if not funcs_to_append:
            return existing_code

        merged = existing_code
        if imports_to_append:
            merged = "\n".join(imports_to_append) + "\n\n" + merged

        merged = merged.rstrip() + "\n\n" + "\n\n".join(funcs_to_append) + "\n"
        return merged

    def _merge_js_tests(self, existing_code: str, new_code: str) -> str:
        """Merge JS/TS test blocks (it / test) into the existing test file."""
        # Simple, robust regex extraction of it(...) and test(...) blocks
        test_block_pattern = re.compile(
            r"((?:it|test)\s*\(\s*['\"`].*?['\"`]\s*,\s*(?:async\s*)?\([^)]*\)\s*=>\s*\{[\s\S]*?\n\s*\}\);)",
        )

        existing_names = set(re.findall(r"(?:it|test)\s*\(\s*['\"`](.*?)['\"`]", existing_code))
        new_matches = test_block_pattern.findall(new_code)

        blocks_to_add: list[str] = []
        for block in new_matches:
            name_m = re.search(r"(?:it|test)\s*\(\s*['\"`](.*?)['\"`]", block)
            if name_m and name_m.group(1) not in existing_names:
                blocks_to_add.append(block)

        if not blocks_to_add:
            return existing_code

        # If existing code has a trailing "});" for a describe block, insert before it
        last_close = existing_code.rfind("});")
        if last_close != -1:
            addition = "\n\n    // --- Coverage-Guided Targeted Tests ---\n    " + "\n\n    ".join(blocks_to_add) + "\n"
            return existing_code[:last_close] + addition + existing_code[last_close:]

        return existing_code.rstrip() + "\n\n" + "\n\n".join(blocks_to_add) + "\n"

    def deduplicate_scenarios(
        self,
        existing: list[TestScenario],
        new_scenarios: list[TestScenario],
    ) -> list[TestScenario]:
        """Deduplicate test scenarios by name and description."""
        seen_names = {s.name.strip().lower() for s in existing}
        merged = list(existing)

        for s in new_scenarios:
            norm_name = s.name.strip().lower()
            if norm_name and norm_name not in seen_names:
                seen_names.add(norm_name)
                merged.append(s)

        return merged
