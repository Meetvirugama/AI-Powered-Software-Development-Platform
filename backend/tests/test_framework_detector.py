"""Unit and integration tests for Framework and Convention Detector.

Owner: Prit — Repository Engine Lead (W2-Day4)
Fulfills Week 2 Day 4: Framework and Convention Detector test coverage and acceptance criteria.
"""

from pathlib import Path
import pytest

from scanner.framework_detector import (
    FrameworkDetectionResult,
    FrameworkDetector,
    SUPPORTED_FRAMEWORKS,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "framework_samples"
WORKSPACE_ROOT = Path(__file__).parent.parent.parent


@pytest.fixture
def detector() -> FrameworkDetector:
    return FrameworkDetector()


class TestPytestFrameworkDetection:
    """Verify detection of pytest configuration, pytest.ini options, and conftest fixtures."""

    def test_detects_pytest_repo_fixture(self, detector: FrameworkDetector):
        repo_dir = FIXTURES_DIR / "pytest_repo"
        result = detector.detect(repo_root=repo_dir)

        assert result.framework == "pytest"
        assert result.language == "Python"
        assert result.is_supported is True
        assert result.status == "CONFIRMED"
        assert result.test_command == "pytest"
        assert result.test_directory == "tests"
        assert result.config_file == "pytest.ini"
        assert result.naming_pattern == "prefix:test_"
        assert "addopts" in result.config_details
        assert "-v" in result.config_details["addopts"]

        # Fixtures extracted from conftest.py
        assert "db_session" in result.fixtures
        assert "configure_environment" in result.fixtures

        # Detailed fixture introspection
        env_fixture = next((f for f in result.fixture_details if f["name"] == "configure_environment"), None)
        assert env_fixture is not None
        assert env_fixture["scope"] == "session"
        assert env_fixture["autouse"] is True

    def test_detects_workspace_self_configuration(self, detector: FrameworkDetector):
        """Verify detector correctly introspects this very platform repository."""
        result = detector.detect(repo_root=WORKSPACE_ROOT)

        assert result.framework == "pytest"
        assert result.language == "Python"
        assert result.is_supported is True
        assert result.status == "CONFIRMED"
        assert result.config_file == "pytest.ini"
        assert result.test_directory == "backend/tests"
        assert "client" in result.fixtures
        assert len(result.fixture_details) > 0


class TestUnittestFrameworkDetection:
    """Verify detection of Python standard library unittest configuration."""

    def test_detects_unittest_repo_fixture(self, detector: FrameworkDetector):
        repo_dir = FIXTURES_DIR / "unittest_repo"
        result = detector.detect(repo_root=repo_dir)

        assert result.framework == "unittest"
        assert result.language == "Python"
        assert result.is_supported is True
        assert result.status == "CONFIRMED"
        assert result.test_command == "python -m unittest"
        assert result.test_directory == "tests"


class TestJestFrameworkDetection:
    """Verify detection of Jest configuration in TypeScript/JavaScript repositories."""

    def test_detects_jest_repo_fixture(self, detector: FrameworkDetector):
        repo_dir = FIXTURES_DIR / "jest_repo"
        result = detector.detect(repo_root=repo_dir)

        assert result.framework == "jest"
        assert result.language in ("TypeScript", "JavaScript")
        assert result.is_supported is True
        assert result.status == "CONFIRMED"
        assert result.test_command == "npm test"
        assert result.config_file in ("jest.config.js", "package.json")
        assert ".test.ts" in result.naming_pattern
        assert "setupTests.ts" in str(result.setup_files) or "jest.config.js" in str(result.config_file)


class TestAmbiguousAndUnsupportedFrameworks:
    """Verify graceful handling and explicit status for unsupported or ambiguous setups."""

    def test_unsupported_vitest_detected(self, detector: FrameworkDetector):
        repo_dir = FIXTURES_DIR / "vitest_repo"
        result = detector.detect(repo_root=repo_dir)

        assert result.framework == "vitest"
        assert result.is_supported is False
        assert result.status == "UNSUPPORTED_FRAMEWORK"
        assert len(result.warnings) > 0
        assert "vitest" in result.warnings[0].lower()

    def test_ambiguous_runners_flagged(self, detector: FrameworkDetector):
        repo_dir = FIXTURES_DIR / "ambiguous_repo"
        result = detector.detect(repo_root=repo_dir)

        assert result.is_ambiguous is True
        assert result.status == "AMBIGUOUS"
        assert "jest" in result.candidate_frameworks
        assert "vitest" in result.candidate_frameworks
        assert result.ambiguity_reason is not None

    def test_preferred_framework_resolves_ambiguity(self, detector: FrameworkDetector):
        repo_dir = FIXTURES_DIR / "ambiguous_repo"
        result = detector.detect(repo_root=repo_dir, preferred_framework="jest")

        assert result.framework == "jest"
        assert result.is_supported is True
        assert result.status == "CONFIRMED"

    def test_empty_repo_returns_no_config(self, detector: FrameworkDetector, tmp_path: Path):
        result = detector.detect(repo_root=tmp_path)

        assert result.status == "NO_CONFIG_FOUND"
        assert result.is_supported is False
        assert len(result.warnings) > 0


class TestTestPathProposals:
    """Verify idiomatic test path generation for various languages and project layouts."""

    def test_python_pytest_path_proposal(self, detector: FrameworkDetector):
        result = FrameworkDetectionResult(
            framework="pytest",
            language="Python",
            is_supported=True,
            status="CONFIRMED",
            test_directory="backend/tests",
            naming_pattern="prefix:test_",
        )
        proposed = result.propose_test_path("backend/scanner/parser.py")
        assert proposed == "backend/tests/scanner/test_parser.py"

    def test_python_root_tests_proposal(self, detector: FrameworkDetector):
        result = FrameworkDetectionResult(
            framework="pytest",
            language="Python",
            is_supported=True,
            status="CONFIRMED",
            test_directory="tests",
            naming_pattern="prefix:test_",
        )
        proposed = result.propose_test_path("app/api/v1/auth.py")
        assert proposed == "tests/app/api/v1/test_auth.py"

    def test_jest_collocated_tests_proposal(self, detector: FrameworkDetector):
        result = FrameworkDetectionResult(
            framework="jest",
            language="TypeScript",
            is_supported=True,
            status="CONFIRMED",
            test_directory="__tests__",
            naming_pattern="suffix:.test.ts",
        )
        proposed = result.propose_test_path("src/components/Button.tsx")
        assert proposed == "src/components/__tests__/Button.test.tsx"

    def test_empty_source_path_returns_empty(self, detector: FrameworkDetector):
        result = FrameworkDetectionResult(
            framework="pytest",
            language="Python",
            is_supported=True,
            status="CONFIRMED",
        )
        assert result.propose_test_path("") == ""


class TestTargetFileScoping:
    """Verify target_file parameter directs language and framework resolution."""

    def test_scoping_to_python_file(self, detector: FrameworkDetector):
        repo_dir = FIXTURES_DIR / "pytest_repo"
        result = detector.detect(repo_root=repo_dir, target_file="services/account.py")
        assert result.language == "Python"
        assert result.framework == "pytest"

    def test_scoping_to_typescript_file(self, detector: FrameworkDetector):
        repo_dir = FIXTURES_DIR / "jest_repo"
        result = detector.detect(repo_root=repo_dir, target_file="src/utils.ts")
        assert result.language == "TypeScript"
        assert result.framework == "jest"


class TestResultSerialization:
    """Verify dictionary serialization for API and service layer integration."""

    def test_to_dict_keys(self, detector: FrameworkDetector):
        repo_dir = FIXTURES_DIR / "pytest_repo"
        result = detector.detect(repo_root=repo_dir)
        d = result.to_dict()

        assert d["framework"] == "pytest"
        assert d["language"] == "Python"
        assert d["is_supported"] is True
        assert d["status"] == "CONFIRMED"
        assert isinstance(d["fixtures"], list)
        assert isinstance(d["fixture_details"], list)
        assert "test_command" in d
        assert "naming_pattern" in d
