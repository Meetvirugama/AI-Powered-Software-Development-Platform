"""Fixture Dataset Loader and Evaluator for AI Quality Benchmarking (Phase 2, task3.md §6).

Loads categorized evaluation fixtures across:
- Clean Code (False-positive evaluation)
- Defect Detection (Functional bugs)
- Security (Vulnerabilities, injections, secrets)
- Performance (Algorithmic & resource inefficiencies)
- Concurrency (Race conditions, shared state)
- Error Handling (Swallowed exceptions, missing cleanup)
- Resource Management (Leaks, unclosed streams)
- False-Positive Traps (Benign code resembling bugs)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ExpectedFinding(BaseModel):
    """Specification of an expected analysis finding in a defect fixture."""

    type: str
    category: str
    severity: str = "medium"
    line_number: Optional[int] = None
    description: Optional[str] = None


class QualityFixture(BaseModel):
    """Structured representation of a single benchmark evaluation fixture."""

    fixture_id: str
    category: str
    subcategory: Optional[str] = None
    description: str
    source_code: str
    language: str = "python"
    has_defect: bool = False
    expected_defects: List[str] = Field(default_factory=list)
    expected_findings: List[ExpectedFinding] = Field(default_factory=list)
    reproduction_instructions: Optional[str] = None

    def to_evaluator_dict(self) -> Dict[str, Any]:
        """Convert to format expected by AIQualityEvaluator."""
        return {
            "sample_id": self.fixture_id,
            "category": self.category,
            "source_code": self.source_code,
            "has_defect": self.has_defect,
            "expected_defects": self.expected_defects,
            "detected_defects": [],  # Populated during evaluation
        }


class QualityFixtureSuite:
    """Manages discovery, loading, and filtering of quality fixtures."""

    def __init__(self, fixtures_dir: Optional[Path] = None) -> None:
        if fixtures_dir is not None:
            self.fixtures_dir = fixtures_dir
        else:
            # Default to backend/tests/evaluation/fixtures
            self.fixtures_dir = Path(__file__).resolve().parent.parent.parent / "tests" / "evaluation" / "fixtures"

        self._fixtures: Dict[str, QualityFixture] = {}
        self.load_all()

    @property
    def fixtures(self) -> List[QualityFixture]:
        return list(self._fixtures.values())

    def load_all(self) -> int:
        """Scan directory and load all JSON fixture files."""
        self._fixtures.clear()
        if not self.fixtures_dir.exists():
            logger.warning("Quality fixtures directory not found: %s", self.fixtures_dir)
            return 0

        for json_file in sorted(self.fixtures_dir.glob("**/*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for item in data:
                        fix = QualityFixture.model_validate(item)
                        self._fixtures[fix.fixture_id] = fix
                elif isinstance(data, dict):
                    fix = QualityFixture.model_validate(data)
                    self._fixtures[fix.fixture_id] = fix
            except Exception as exc:
                logger.error("Failed to load fixture file %s: %s", json_file, exc)

        return len(self._fixtures)

    def get(self, fixture_id: str) -> Optional[QualityFixture]:
        return self._fixtures.get(fixture_id)

    def filter_by_category(self, category: str) -> List[QualityFixture]:
        return [f for f in self._fixtures.values() if f.category.lower() == category.lower()]

    def get_clean_fixtures(self) -> List[QualityFixture]:
        return [f for f in self._fixtures.values() if not f.has_defect]

    def get_defect_fixtures(self) -> List[QualityFixture]:
        return [f for f in self._fixtures.values() if f.has_defect]


__all__ = ["ExpectedFinding", "QualityFixture", "QualityFixtureSuite"]
