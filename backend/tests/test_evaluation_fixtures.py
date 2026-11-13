"""Unit tests for the Quality Fixture Suite and Loader (Phase 2, task3.md §6 & §11.2).

Verifies:
1. Fixtures load cleanly across all 8 categories (clean_code, defect_detection, security,
   performance, concurrency, error_handling, resource_management, false_positives).
2. All fixture IDs are globally unique (no duplicates).
3. Schema validation succeeds on every fixture.
4. Clean fixtures have has_defect=False and expected_defects=[].
5. Defect fixtures have has_defect=True and len(expected_defects) > 0.
6. Category filtering accurately returns expected subset.
"""

from __future__ import annotations

import pytest

from ai.evaluation.fixture_loader import QualityFixture, QualityFixtureSuite


@pytest.fixture
def suite() -> QualityFixtureSuite:
    return QualityFixtureSuite()


def test_fixture_suite_loads_all_categories(suite: QualityFixtureSuite) -> None:
    """Verify that the fixture suite discovers and loads fixtures from disk."""
    fixtures = suite.fixtures
    assert len(fixtures) >= 20, f"Expected at least 20 fixtures, loaded {len(fixtures)}"

    categories = {f.category for f in fixtures}
    expected_categories = {
        "clean_code",
        "defect_detection",
        "security",
        "performance",
        "concurrency",
        "error_handling",
        "resource_management",
        "false_positives",
    }
    assert expected_categories.issubset(categories), f"Missing categories: {expected_categories - categories}"


def test_fixture_ids_are_globally_unique(suite: QualityFixtureSuite) -> None:
    """Verify that there are no duplicate fixture IDs across categories."""
    fixtures = suite.fixtures
    ids = [f.fixture_id for f in fixtures]
    assert len(ids) == len(set(ids)), f"Duplicate fixture IDs found: {[x for x in ids if ids.count(x) > 1]}"


def test_clean_fixtures_have_no_defects(suite: QualityFixtureSuite) -> None:
    """Verify that clean and false-positive fixtures declare has_defect=False and empty expected defects."""
    clean_fixtures = suite.get_clean_fixtures()
    assert len(clean_fixtures) >= 8

    for f in clean_fixtures:
        assert f.has_defect is False, f"Fixture {f.fixture_id} marked as clean but has_defect is True"
        assert len(f.expected_defects) == 0, f"Fixture {f.fixture_id} has unexpected defects: {f.expected_defects}"
        assert len(f.expected_findings) == 0


def test_defect_fixtures_have_expected_defects(suite: QualityFixtureSuite) -> None:
    """Verify that defect fixtures declare has_defect=True and contain expected defects."""
    defect_fixtures = suite.get_defect_fixtures()
    assert len(defect_fixtures) >= 12

    for f in defect_fixtures:
        assert f.has_defect is True, f"Fixture {f.fixture_id} in defect category but has_defect is False"
        assert len(f.expected_defects) > 0, f"Fixture {f.fixture_id} has empty expected_defects"
        assert len(f.expected_findings) > 0


def test_category_filtering(suite: QualityFixtureSuite) -> None:
    """Verify filtering fixtures by category returns the correct subsets."""
    sec = suite.filter_by_category("security")
    assert len(sec) >= 5
    assert all(f.category == "security" for f in sec)

    perf = suite.filter_by_category("performance")
    assert len(perf) >= 2
    assert all(f.category == "performance" for f in perf)

    conc = suite.filter_by_category("concurrency")
    assert len(conc) >= 2
    assert all(f.category == "concurrency" for f in conc)


def test_fixture_conversion_to_evaluator_dict(suite: QualityFixtureSuite) -> None:
    """Verify to_evaluator_dict matches AIQualityEvaluator input format."""
    f = suite.get("SEC-001")
    assert f is not None
    d = f.to_evaluator_dict()
    assert d["sample_id"] == "SEC-001"
    assert d["category"] == "security"
    assert "SELECT" in d["source_code"]
    assert d["has_defect"] is True
    assert "sql_injection" in d["expected_defects"]
