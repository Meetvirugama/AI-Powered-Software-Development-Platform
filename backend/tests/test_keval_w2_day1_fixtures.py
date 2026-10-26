"""Unit tests for Keval's Week 2 Day 1 QA Foundation deliverables.

Owner: Keval (QA Lead)
Reference: Docs/week2.md §5
"""

import ast
from pathlib import Path
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "defect_fixtures"


def test_fixture_directory_and_files_exist():
    """Verify all 8 required defect fixture files exist under defect_fixtures/."""
    expected_files = [
        "correct_math.py",
        "off_by_one.py",
        "null_safety.py",
        "unhandled_exception.py",
        "untested_service.py",
        "tested_service.py",
        "test_tested_service.py",
        "review_defect.diff",
        "prompt_injection_source.py",
    ]
    for filename in expected_files:
        filepath = FIXTURES_DIR / filename
        assert filepath.exists(), f"Missing required fixture file: {filename}"
        assert filepath.stat().st_size > 0, f"Fixture file is empty: {filename}"


def test_python_fixtures_are_syntactically_valid():
    """Verify that Python fixture source files parse cleanly into AST nodes."""
    py_fixtures = [
        "correct_math.py",
        "off_by_one.py",
        "null_safety.py",
        "unhandled_exception.py",
        "untested_service.py",
        "tested_service.py",
        "test_tested_service.py",
        "prompt_injection_source.py",
    ]
    for filename in py_fixtures:
        content = (FIXTURES_DIR / filename).read_text(encoding="utf-8")
        parsed = ast.parse(content, filename=filename)
        assert isinstance(parsed, ast.Module), f"Failed to parse AST for {filename}"


def test_correct_math_fixture_behavior():
    """Verify behavior of the clean baseline math fixture."""
    from tests.fixtures.defect_fixtures.correct_math import calculate_average, find_maximum, clamp

    assert calculate_average([10, 20, 30]) == 20.0
    assert calculate_average([]) == 0.0
    assert find_maximum([3, 7, 2, 9, 1]) == 9
    assert find_maximum([]) is None
    assert clamp(5.0, 0.0, 10.0) == 5.0
    assert clamp(-5.0, 0.0, 10.0) == 0.0
    assert clamp(15.0, 0.0, 10.0) == 10.0
    with pytest.raises(ValueError):
        clamp(5.0, 10.0, 0.0)


def test_off_by_one_fixture_manifests_defect():
    """Verify off_by_one.py raises IndexError when accessing boundary."""
    from tests.fixtures.defect_fixtures.off_by_one import get_first_n_items

    with pytest.raises(IndexError):
        get_first_n_items([1, 2, 3], 5)


def test_review_diff_structure():
    """Verify review_defect.diff contains a valid unified diff with SQL injection defect."""
    diff_content = (FIXTURES_DIR / "review_defect.diff").read_text(encoding="utf-8")
    assert "diff --git" in diff_content
    assert "--- a/" in diff_content
    assert "+++ b/" in diff_content
    assert "SELECT * FROM users WHERE username LIKE" in diff_content


def test_prompt_injection_fixture_contents():
    """Verify prompt_injection_source.py contains the canary instruction strings."""
    source_content = (FIXTURES_DIR / "prompt_injection_source.py").read_text(encoding="utf-8")
    assert "Ignore all previous instructions" in source_content
    assert "<<<REPO_DATA_END>>>" in source_content
    assert "def transfer_funds" in source_content
