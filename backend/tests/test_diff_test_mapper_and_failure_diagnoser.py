"""backend/tests/test_diff_test_mapper_and_failure_diagnoser.py

Unit and integration tests for Phase 4:
- DiffTestMapper (diff-to-test mapping, evidence confidence, 120s ceiling)
- FailureDiagnoser (pytest and vitest traceback parsing, root-cause localization)
"""

from pathlib import Path
import pytest

from scanner.diff_test_mapper import DiffTestMapper, DiffTestMappingResult
from ai.services.failure_diagnoser import FailureDiagnoser, FailureDiagnosis


@pytest.fixture
def mock_repo_tree(tmp_path: Path) -> Path:
    """Create a temporary repository filesystem with source and test files."""
    repo = tmp_path / "repo"
    repo.mkdir()

    # Backend files
    (repo / "backend" / "app" / "api").mkdir(parents=True)
    (repo / "backend" / "app" / "api" / "tasks.py").write_text("def get_tasks(): pass\n")
    (repo / "backend" / "app" / "api" / "users.py").write_text("def get_users(): pass\n")

    # Backend test files
    (repo / "backend" / "tests").mkdir(parents=True)
    (repo / "backend" / "tests" / "test_tasks.py").write_text("from backend.app.api.tasks import get_tasks\ndef test_get_tasks(): pass\n")
    (repo / "backend" / "tests" / "test_users_advanced.py").write_text("from backend.app.api.users import get_users\ndef test_users(): pass\n")

    # Frontend files
    (repo / "frontend" / "src" / "pages").mkdir(parents=True)
    (repo / "frontend" / "src" / "pages" / "TaskStudio.tsx").write_text("export const TaskStudio = () => null;\n")

    # Frontend test files
    (repo / "frontend" / "src" / "test").mkdir(parents=True)
    (repo / "frontend" / "src" / "test" / "TaskStudio.test.tsx").write_text("describe('TaskStudio', () => {});\n")

    return repo


class TestDiffTestMapper:
    """Tests certifying diff-to-test mapping and evidence collection."""

    def test_empty_diff_returns_no_tests(self, mock_repo_tree: Path):
        mapper = DiffTestMapper(mock_repo_tree)
        res = mapper.map_changed_files([])
        assert res.mapped_tests == []
        assert res.test_framework == "none"
        assert res.test_command == ""

    def test_maps_exact_python_test(self, mock_repo_tree: Path):
        mapper = DiffTestMapper(mock_repo_tree)
        res = mapper.map_changed_files(["backend/app/api/tasks.py"])
        assert "backend/tests/test_tasks.py" in res.mapped_tests
        assert res.test_framework == "pytest"
        assert "pytest backend/tests/test_tasks.py" in res.test_command
        assert res.timeout_seconds == 120

        ev = next(e for e in res.evidence if e.test_file == "backend/tests/test_tasks.py")
        assert ev.confidence == "STRONG"
        assert ev.evidence_type == "exact_name_match"

    def test_maps_stem_match_python_test(self, mock_repo_tree: Path):
        mapper = DiffTestMapper(mock_repo_tree)
        res = mapper.map_changed_files(["backend/app/api/users.py"])
        assert "backend/tests/test_users_advanced.py" in res.mapped_tests
        assert res.test_framework == "pytest"

        ev = next(e for e in res.evidence if e.test_file == "backend/tests/test_users_advanced.py")
        assert ev.confidence == "STRONG"
        assert ev.evidence_type == "stem_match"

    def test_maps_modified_test_file_to_itself(self, mock_repo_tree: Path):
        mapper = DiffTestMapper(mock_repo_tree)
        res = mapper.map_changed_files(["backend/tests/test_tasks.py"])
        assert "backend/tests/test_tasks.py" in res.mapped_tests
        ev = next(e for e in res.evidence if e.test_file == "backend/tests/test_tasks.py")
        assert ev.confidence == "PROVEN"
        assert ev.evidence_type == "direct_test_file"

    def test_maps_frontend_component_to_vitest(self, mock_repo_tree: Path):
        mapper = DiffTestMapper(mock_repo_tree)
        res = mapper.map_changed_files(["frontend/src/pages/TaskStudio.tsx"])
        assert "frontend/src/test/TaskStudio.test.tsx" in res.mapped_tests
        assert res.test_framework == "vitest"
        assert "npx vitest run frontend/src/test/TaskStudio.test.tsx" in res.test_command

    def test_mixed_diff_detected(self, mock_repo_tree: Path):
        mapper = DiffTestMapper(mock_repo_tree)
        res = mapper.map_changed_files([
            "backend/app/api/tasks.py",
            "frontend/src/pages/TaskStudio.tsx",
        ])
        assert res.test_framework == "mixed"
        assert "backend/tests/test_tasks.py" in res.mapped_tests
        assert "frontend/src/test/TaskStudio.test.tsx" in res.mapped_tests


class TestFailureDiagnoser:
    """Tests certifying automated failure diagnosis and traceback parsing."""

    def test_diagnose_pytest_simple_assertion_error(self):
        diagnoser = FailureDiagnoser()
        sample_pytest_out = """
=================================== FAILURES ===================================
_________________________________ test_calc __________________________________

    def test_calc():
>       assert calculate_tax(100) == 20
E       AssertionError: assert 15 == 20

backend/tests/test_calc.py:12: AssertionError
=========================== short test summary info ============================
FAILED backend/tests/test_calc.py::test_calc - AssertionError: assert 15 == 20
"""
        diagnoses = diagnoser.diagnose_failure(sample_pytest_out, framework="pytest")
        assert len(diagnoses) == 1
        d = diagnoses[0]
        assert d.error_type == "AssertionError"
        assert "assert 15 == 20" in d.error_message
        assert d.failed_test_name == "test_calc"
        assert d.failing_statement == "assert calculate_tax(100) == 20"
        assert d.root_cause_file == "backend/tests/test_calc.py"
        assert d.root_cause_line == 12

    def test_diagnose_pytest_application_code_error(self):
        diagnoser = FailureDiagnoser()
        sample_pytest_out = """
=================================== FAILURES ===================================
________________________________ test_process _________________________________

    def test_process():
>       service.process_data(None)

backend/tests/test_service.py:25: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
backend/app/services/processor.py:48: in process_data
    return data.strip()
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    def strip():
E   AttributeError: 'NoneType' object has no attribute 'strip'
"""
        diagnoses = diagnoser.diagnose_failure(sample_pytest_out, framework="pytest")
        assert len(diagnoses) == 1
        d = diagnoses[0]
        assert d.error_type == "AttributeError"
        assert "NoneType" in d.error_message
        # Should identify application frame as root cause!
        assert d.root_cause_file == "backend/app/services/processor.py"
        assert d.root_cause_line == 48
        assert "Inspect implementation logic" in d.suggested_action

    def test_diagnose_vitest_failure(self):
        diagnoser = FailureDiagnoser()
        sample_vitest_out = """
FAIL src/test/Button.test.tsx
  Button component
    ✕ renders click counter (15ms)

  ● Button component › renders click counter

    AssertionError: expected 'Clicked 0 times' to be 'Clicked 1 times'

      at src/test/Button.test.tsx:28:18
      at src/components/Button.tsx:14:5
"""
        diagnoses = diagnoser.diagnose_failure(sample_vitest_out, framework="vitest")
        assert len(diagnoses) == 1
        d = diagnoses[0]
        assert d.error_type == "AssertionError"
        assert "expected 'Clicked 0 times' to be 'Clicked 1 times'" in d.error_message
        # Identifies component frame as root cause
        assert d.root_cause_file == "src/components/Button.tsx"
        assert d.root_cause_line == 14
