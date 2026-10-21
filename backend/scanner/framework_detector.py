"""Framework and convention detector for test generation and repository intelligence.

Owner: Prit — Repository Engine Lead (W2-Day4)
Fulfills Week 2 Day 4: Framework and Convention Detector.
Inspects package manifests, configuration files, and test directories to detect
available test frameworks, configured commands, naming patterns, and fixtures.
Supports pytest, unittest, and jest with explicit handling of ambiguous or unsupported configurations.
"""

from __future__ import annotations

import ast
import configparser
import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

SUPPORTED_FRAMEWORKS = {"pytest", "unittest", "jest"}


@dataclass
class FrameworkDetectionResult:
    """The structured result of detecting repository test frameworks and conventions."""

    framework: Optional[str]  # "pytest" | "unittest" | "jest" | None
    language: str  # "Python" | "TypeScript" | "JavaScript" | "Go" | "Java" | "unknown"
    is_supported: bool  # True if framework is in SUPPORTED_FRAMEWORKS
    status: str  # "CONFIRMED" | "AMBIGUOUS" | "UNSUPPORTED_FRAMEWORK" | "NO_CONFIG_FOUND"
    test_command: Optional[str] = None  # "pytest", "python -m unittest", "npm test"
    test_directory: Optional[str] = None  # "tests", "backend/tests", "__tests__"
    naming_pattern: str = "prefix:test_"  # "prefix:test_" | "suffix:_test" | "suffix:.test.ts"
    config_file: Optional[str] = None  # "pytest.ini", "package.json", "jest.config.js"
    config_details: Dict[str, Any] = field(default_factory=dict)
    fixtures: List[str] = field(default_factory=list)
    fixture_details: List[Dict[str, Any]] = field(default_factory=list)
    setup_files: List[str] = field(default_factory=list)
    candidate_frameworks: List[str] = field(default_factory=list)
    is_ambiguous: bool = False
    ambiguity_reason: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    def propose_test_path(self, source_file: str) -> str:
        """Compute the idiomatic test path matching detected directory layout and naming pattern."""
        if not source_file:
            return ""

        clean_path = source_file.replace("\\", "/").lstrip("/")
        p = Path(clean_path)
        stem = p.stem
        ext = p.suffix

        # Determine target extension based on framework/source language
        target_ext = ext
        if self.framework == "jest":
            if ext in (".ts", ".tsx"):
                target_ext = ".test.ts" if ext == ".ts" else ".test.tsx"
            elif ext in (".js", ".jsx"):
                target_ext = ".test.js" if ext == ".js" else ".test.jsx"
            else:
                target_ext = ".test.ts"
        elif self.framework in ("pytest", "unittest"):
            target_ext = ".py"

        # Determine test filename from naming pattern
        if "suffix:" in self.naming_pattern:
            suffix_val = self.naming_pattern.split("suffix:")[1]
            if suffix_val.startswith("."):
                if ext.endswith("x") and not suffix_val.endswith("x"):
                    test_filename = f"{stem}{suffix_val}x"
                else:
                    test_filename = f"{stem}{suffix_val}"
            else:
                test_filename = f"{stem}{suffix_val}{target_ext}"
        else:
            # Default prefix pattern: test_<name>.py
            prefix_val = "test_"
            if "prefix:" in self.naming_pattern:
                prefix_val = self.naming_pattern.split("prefix:")[1]
            test_filename = f"{prefix_val}{stem}{target_ext}"

        # Determine target directory
        base_test_dir = self.test_directory or "tests"
        base_test_dir = base_test_dir.replace("\\", "/").rstrip("/")

        # If repo uses collocated __tests__ directory (common in React/Jest)
        if base_test_dir in ("__tests__", "src/__tests__") and p.parent.parts:
            # Check if source parent already in src/
            parent_str = str(p.parent).replace("\\", "/")
            return f"{parent_str}/__tests__/{test_filename}"

        # If test directory is nested like backend/tests and source starts with backend/
        parts = list(p.parts)
        if parts:
            first_dir = parts[0]
            if base_test_dir.startswith(f"{first_dir}/"):
                # Source is inside backend/, tests are in backend/tests
                # Strip the root folder e.g. backend/scanner/parser.py -> backend/tests/scanner/test_parser.py
                sub_parts = parts[1:-1]  # subdirectories between first_dir and file
                if sub_parts:
                    sub_path = "/".join(sub_parts)
                    return f"{base_test_dir}/{sub_path}/{test_filename}"
                return f"{base_test_dir}/{test_filename}"

        # If source is in src/, strip src/ for root tests/ directory e.g. src/auth/login.py -> tests/auth/test_login.py
        if parts and parts[0] == "src":
            sub_parts = parts[1:-1]
            if sub_parts:
                return f"{base_test_dir}/{'/'.join(sub_parts)}/{test_filename}"
            return f"{base_test_dir}/{test_filename}"

        # Standard layout: mirror relative directory if multiple parts
        if len(parts) > 1:
            sub_parts = parts[:-1]
            return f"{base_test_dir}/{'/'.join(sub_parts)}/{test_filename}"

        return f"{base_test_dir}/{test_filename}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert detection result to standard dictionary representation."""
        return {
            "framework": self.framework,
            "language": self.language,
            "is_supported": self.is_supported,
            "status": self.status,
            "test_command": self.test_command,
            "test_directory": self.test_directory,
            "naming_pattern": self.naming_pattern,
            "config_file": self.config_file,
            "config_details": self.config_details,
            "fixtures_count": len(self.fixtures),
            "fixtures": self.fixtures,
            "fixture_details": self.fixture_details,
            "setup_files": self.setup_files,
            "candidate_frameworks": self.candidate_frameworks,
            "is_ambiguous": self.is_ambiguous,
            "ambiguity_reason": self.ambiguity_reason,
            "warnings": self.warnings,
        }


class FrameworkDetector:
    """Inspects repository manifests, test directories, and configurations to detect

    available test frameworks, conventions, fixtures, and commands.
    """

    TEST_DIR_CANDIDATES = [
        "backend/tests",
        "tests",
        "test",
        "__tests__",
        "src/__tests__",
        "src/tests",
        "spec",
    ]

    def __init__(self, repo_root: Optional[str | Path] = None):
        self.repo_root = Path(repo_root).resolve() if repo_root else None

    def detect(
        self,
        repo_root: Optional[str | Path] = None,
        target_file: Optional[str] = None,
        file_list: Optional[Sequence[str]] = None,
        preferred_framework: Optional[str] = None,
    ) -> FrameworkDetectionResult:
        """Detect the active test framework and conventions for the target repository or file."""
        root = Path(repo_root).resolve() if repo_root else self.repo_root
        if root is None and file_list is None:
            root = Path.cwd().resolve()

        # Build list of available files
        files: List[str] = []
        if file_list is not None:
            files = [f.replace("\\", "/").lstrip("/") for f in file_list]
        elif root and root.exists():
            files = self._collect_repo_files(root)

        # Resolve target language
        target_lang = self._resolve_target_language(target_file, files)

        if target_lang == "Python":
            return self._detect_python_framework(root, files, target_file, preferred_framework)
        elif target_lang in ("TypeScript", "JavaScript"):
            return self._detect_javascript_framework(root, files, target_file, target_lang, preferred_framework)
        elif target_lang == "Go":
            return self._detect_go_framework(root, files)
        elif target_lang == "Java":
            return self._detect_java_framework(root, files)
        else:
            return FrameworkDetectionResult(
                framework=None,
                language="unknown",
                is_supported=False,
                status="NO_CONFIG_FOUND",
                warnings=["Could not determine target language or test configuration from repository"],
            )

    def _collect_repo_files(self, root: Path) -> List[str]:
        """Collect repo-relative file paths while ignoring skip directories."""
        collected: List[str] = []
        skip_dirs = {
            ".git",
            "node_modules",
            "venv",
            ".venv",
            "__pycache__",
            "dist",
            "build",
            ".pytest_cache",
            ".idea",
            ".vscode",
        }
        for current_root, dirs, filenames in os.walk(root):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            rel_dir = os.path.relpath(current_root, root)
            for fname in filenames:
                rel_path = (
                    fname
                    if rel_dir == "."
                    else os.path.join(rel_dir, fname).replace("\\", "/")
                )
                collected.append(rel_path)
        return collected

    def _resolve_target_language(
        self,
        target_file: Optional[str],
        files: Sequence[str],
    ) -> str:
        """Identify language from target file extension or file inventory."""
        if target_file:
            ext = os.path.splitext(target_file)[1].lower()
            if ext == ".py":
                return "Python"
            elif ext in (".ts", ".tsx"):
                return "TypeScript"
            elif ext in (".js", ".jsx", ".mjs", ".cjs"):
                return "JavaScript"
            elif ext == ".go":
                return "Go"
            elif ext in (".java",):
                return "Java"

        # Infer from repository files
        py_count = sum(1 for f in files if f.endswith(".py"))
        ts_count = sum(1 for f in files if f.endswith((".ts", ".tsx")))
        js_count = sum(1 for f in files if f.endswith((".js", ".jsx")))

        if py_count >= ts_count and py_count >= js_count and py_count > 0:
            return "Python"
        elif ts_count >= js_count and ts_count > 0:
            return "TypeScript"
        elif js_count > 0:
            return "JavaScript"

        # Check for manifests
        for f in files:
            if f.endswith(("pytest.ini", "requirements.txt", "pyproject.toml")):
                return "Python"
            if f.endswith(("package.json", "tsconfig.json")):
                return "TypeScript" if any(f.endswith(".ts") for f in files) else "JavaScript"

        return "unknown"

    # -----------------------------------------------------------------------
    # Python Framework Detection
    # -----------------------------------------------------------------------

    def _detect_python_framework(
        self,
        root: Optional[Path],
        files: Sequence[str],
        target_file: Optional[str],
        preferred_framework: Optional[str],
    ) -> FrameworkDetectionResult:
        """Detect pytest vs unittest configuration in Python repositories."""
        pytest_signals: List[str] = []
        unittest_signals: List[str] = []
        config_file: Optional[str] = None
        config_details: Dict[str, Any] = {}
        test_dir: Optional[str] = None
        test_command: Optional[str] = None

        # 1. Inspect pytest.ini
        for fname in ("pytest.ini", "backend/pytest.ini"):
            if fname in files:
                config_file = fname
                pytest_signals.append(f"Config file '{fname}' present")
                details = self._parse_pytest_ini(root, fname)
                config_details.update(details)
                if "testpaths" in details:
                    test_dir = details["testpaths"].split()[0]
                break

        # 2. Inspect pyproject.toml
        if "pyproject.toml" in files:
            content = self._read_file(root, "pyproject.toml")
            if "[tool.pytest" in content or "pytest" in content:
                pytest_signals.append("pyproject.toml contains pytest configuration/dependencies")
                if not config_file:
                    config_file = "pyproject.toml"

        # 3. Inspect setup.cfg / tox.ini
        for fname in ("setup.cfg", "tox.ini"):
            if fname in files:
                content = self._read_file(root, fname)
                if "[tool:pytest]" in content or "[pytest]" in content:
                    pytest_signals.append(f"{fname} contains [pytest] section")
                    if not config_file:
                        config_file = fname

        # 4. Inspect requirements.txt / Pipfile
        for fname in ("requirements.txt", "backend/requirements.txt", "Pipfile"):
            if fname in files:
                content = self._read_file(root, fname)
                if re.search(r"\bpytest\b", content):
                    pytest_signals.append(f"'{fname}' lists pytest as a dependency")

        # 5. Discover test directory and naming convention
        discovered_test_dir, naming_pattern = self._discover_python_test_conventions(files)
        if not test_dir:
            test_dir = discovered_test_dir

        # 6. Inspect test files for imports (pytest vs unittest)
        test_files = [f for f in files if self._is_python_test_file(f)]
        has_pytest_imports = False
        has_unittest_imports = False
        for tf in test_files[:15]:
            code = self._read_file(root, tf)
            if "import pytest" in code or "@pytest." in code or "pytest." in code:
                has_pytest_imports = True
            if "unittest.TestCase" in code or "import unittest" in code:
                has_unittest_imports = True

        if has_pytest_imports:
            pytest_signals.append("Existing test files import and use 'pytest'")
        if has_unittest_imports:
            unittest_signals.append("Existing test files inherit from 'unittest.TestCase'")

        # 7. Identify fixtures from conftest.py
        fixtures, fixture_details, setup_files = self._extract_pytest_fixtures(root, files)

        # 8. Frame resolution
        candidate_frameworks = []
        if pytest_signals:
            candidate_frameworks.append("pytest")
        if unittest_signals:
            candidate_frameworks.append("unittest")

        # Handle user preference override
        if preferred_framework in ("pytest", "unittest"):
            chosen_framework = preferred_framework
            is_ambiguous = False
            ambiguity_reason = None
            status = "CONFIRMED"
        elif pytest_signals:
            chosen_framework = "pytest"
            test_command = "pytest"
            status = "CONFIRMED"
            is_ambiguous = False
            ambiguity_reason = None
            if unittest_signals:
                # Pytest natively runs unittest suites, so this is supported seamlessly
                pass
        elif unittest_signals:
            chosen_framework = "unittest"
            test_command = "python -m unittest"
            status = "CONFIRMED"
            is_ambiguous = False
            ambiguity_reason = None
        else:
            # Fallback: Python standard library unittest is always available
            chosen_framework = "unittest"
            test_command = "python -m unittest"
            status = "CONFIRMED"
            is_ambiguous = False
            ambiguity_reason = None

        return FrameworkDetectionResult(
            framework=chosen_framework,
            language="Python",
            is_supported=True,
            status=status,
            test_command=test_command,
            test_directory=test_dir or "tests",
            naming_pattern=naming_pattern,
            config_file=config_file,
            config_details=config_details,
            fixtures=fixtures,
            fixture_details=fixture_details,
            setup_files=setup_files,
            candidate_frameworks=candidate_frameworks or ["pytest", "unittest"],
            is_ambiguous=is_ambiguous,
            ambiguity_reason=ambiguity_reason,
        )

    def _parse_pytest_ini(self, root: Optional[Path], filename: str) -> Dict[str, Any]:
        """Parse pytest.ini file options safely."""
        details: Dict[str, Any] = {}
        content = self._read_file(root, filename)
        if not content:
            return details

        config = configparser.ConfigParser()
        try:
            config.read_string(content)
            if config.has_section("pytest"):
                for key, val in config.items("pytest"):
                    details[key] = val.strip()
        except Exception:
            # Fallback manual parse for key=value lines
            for line in content.splitlines():
                line = line.strip()
                if "=" in line and not line.startswith(("#", ";", "[")):
                    k, v = line.split("=", 1)
                    details[k.strip()] = v.strip()
        return details

    def _discover_python_test_conventions(self, files: Sequence[str]) -> Tuple[Optional[str], str]:
        """Find existing test directory and file naming pattern for Python."""
        test_dir: Optional[str] = None
        prefix_count = 0
        suffix_count = 0

        # Discover directory
        for cand in self.TEST_DIR_CANDIDATES:
            if any(f.startswith(f"{cand}/") for f in files):
                test_dir = cand
                break

        # Discover naming pattern
        for f in files:
            fname = os.path.basename(f)
            if fname.startswith("test_") and fname.endswith(".py"):
                prefix_count += 1
            elif fname.endswith("_test.py"):
                suffix_count += 1

        pattern = "suffix:_test" if suffix_count > prefix_count else "prefix:test_"
        return test_dir, pattern

    def _is_python_test_file(self, filename: str) -> bool:
        """Return True if filename matches Python test naming convention."""
        fname = os.path.basename(filename)
        return fname.endswith(".py") and (
            fname.startswith("test_") or fname.endswith("_test.py")
        )

    def _extract_pytest_fixtures(
        self,
        root: Optional[Path],
        files: Sequence[str],
    ) -> Tuple[List[str], List[Dict[str, Any]], List[str]]:
        """Extract pytest fixtures from conftest.py files using AST parsing."""
        fixtures: List[str] = []
        fixture_details: List[Dict[str, Any]] = []
        setup_files: List[str] = []

        conftest_files = [f for f in files if os.path.basename(f) == "conftest.py"]
        for cf in conftest_files:
            setup_files.append(cf)
            code = self._read_file(root, cf)
            if not code:
                continue

            try:
                tree = ast.parse(code, filename=cf)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        is_fixture = False
                        scope = "function"
                        autouse = False

                        for decorator in node.decorator_list:
                            # @pytest.fixture or @fixture
                            dec_name = ""
                            if isinstance(decorator, ast.Name):
                                dec_name = decorator.id
                            elif isinstance(decorator, ast.Attribute):
                                dec_name = decorator.attr
                            elif isinstance(decorator, ast.Call):
                                if isinstance(decorator.func, ast.Name):
                                    dec_name = decorator.func.id
                                elif isinstance(decorator.func, ast.Attribute):
                                    dec_name = decorator.func.attr

                                # Extract scope and autouse kwargs
                                for kw in decorator.keywords:
                                    if kw.arg == "scope" and isinstance(kw.value, ast.Constant):
                                        scope = str(kw.value.value)
                                    elif kw.arg == "autouse" and isinstance(kw.value, ast.Constant):
                                        autouse = bool(kw.value.value)

                            if dec_name in ("fixture", "pytest.fixture"):
                                is_fixture = True

                        if is_fixture:
                            doc = ast.get_docstring(node) or ""
                            fixtures.append(node.name)
                            fixture_details.append(
                                {
                                    "name": node.name,
                                    "file": cf,
                                    "line": node.lineno,
                                    "scope": scope,
                                    "autouse": autouse,
                                    "docstring": doc.splitlines()[0] if doc else "",
                                }
                            )
            except Exception as e:
                logger.warning(f"Failed to parse fixtures from {cf}: {e}")

        return fixtures, fixture_details, setup_files

    # -----------------------------------------------------------------------
    # JavaScript / TypeScript Framework Detection
    # -----------------------------------------------------------------------

    def _detect_javascript_framework(
        self,
        root: Optional[Path],
        files: Sequence[str],
        target_file: Optional[str],
        language: str,
        preferred_framework: Optional[str],
    ) -> FrameworkDetectionResult:
        """Detect Jest vs Vitest vs Mocha in JS/TS repositories."""
        pkg_json_file = next(
            (f for f in ("package.json", "frontend/package.json") if f in files),
            None,
        )
        test_dir, naming_pattern = self._discover_js_test_conventions(files, language)

        detected_framework: Optional[str] = None
        test_command: Optional[str] = "npm test"
        is_supported = False
        status = "NO_CONFIG_FOUND"
        candidate_frameworks: List[str] = []
        warnings: List[str] = []
        is_ambiguous = False
        ambiguity_reason: Optional[str] = None
        config_file: Optional[str] = None
        config_details: Dict[str, Any] = {}
        setup_files: List[str] = []

        # Find jest config files
        for jc in (
            "jest.config.js",
            "jest.config.ts",
            "jest.config.mjs",
            "jest.config.json",
        ):
            if jc in files:
                config_file = jc
                candidate_frameworks.append("jest")
                break

        # Find setup files
        for sf in (
            "setupTests.ts",
            "setupTests.js",
            "src/setupTests.ts",
            "src/setupTests.js",
            "jest.setup.js",
            "jest.setup.ts",
        ):
            if sf in files:
                setup_files.append(sf)

        # Inspect package.json
        if pkg_json_file:
            content = self._read_file(root, pkg_json_file)
            try:
                pkg_data = json.loads(content)
                scripts = pkg_data.get("scripts", {})
                deps = pkg_data.get("dependencies", {})
                dev_deps = pkg_data.get("devDependencies", {})
                all_deps = {**deps, **dev_deps}

                test_script = scripts.get("test", "")
                if "jest" in test_script:
                    candidate_frameworks.append("jest")
                elif "vitest" in test_script:
                    candidate_frameworks.append("vitest")
                elif "mocha" in test_script:
                    candidate_frameworks.append("mocha")

                if "jest" in all_deps or "ts-jest" in all_deps:
                    if "jest" not in candidate_frameworks:
                        candidate_frameworks.append("jest")
                if "vitest" in all_deps:
                    if "vitest" not in candidate_frameworks:
                        candidate_frameworks.append("vitest")
                if "mocha" in all_deps:
                    if "mocha" not in candidate_frameworks:
                        candidate_frameworks.append("mocha")

                if "jest" in pkg_data:
                    config_details["jest"] = pkg_data["jest"]
                    if not config_file:
                        config_file = pkg_json_file
                    if "jest" not in candidate_frameworks:
                        candidate_frameworks.append("jest")
            except Exception as e:
                warnings.append(f"Failed to parse {pkg_json_file}: {e}")

        # Resolve ambiguity
        unique_candidates = list(dict.fromkeys(candidate_frameworks))
        if preferred_framework in ("jest",):
            detected_framework = preferred_framework
            is_supported = True
            status = "CONFIRMED"
        elif len(unique_candidates) == 1:
            detected_framework = unique_candidates[0]
            if detected_framework == "jest":
                is_supported = True
                status = "CONFIRMED"
                test_command = "npm test"
            else:
                is_supported = False
                status = "UNSUPPORTED_FRAMEWORK"
                warnings.append(
                    f"Test runner '{detected_framework}' detected, but TestGenerationService "
                    "currently supports Jest for JavaScript/TypeScript repositories."
                )
        elif len(unique_candidates) > 1:
            is_ambiguous = True
            status = "AMBIGUOUS"
            ambiguity_reason = (
                f"Multiple test runners detected ({', '.join(unique_candidates)}). "
                "Specify framework explicitly in generation request."
            )
            detected_framework = "jest" if "jest" in unique_candidates else unique_candidates[0]
            is_supported = (detected_framework == "jest")
        else:
            status = "NO_CONFIG_FOUND"
            warnings.append(
                f"No test configuration or dependencies detected for {language}. "
                "Configure Jest in package.json to enable test generation."
            )

        return FrameworkDetectionResult(
            framework=detected_framework,
            language=language,
            is_supported=is_supported,
            status=status,
            test_command=test_command,
            test_directory=test_dir or "__tests__",
            naming_pattern=naming_pattern,
            config_file=config_file or pkg_json_file,
            config_details=config_details,
            setup_files=setup_files,
            candidate_frameworks=unique_candidates,
            is_ambiguous=is_ambiguous,
            ambiguity_reason=ambiguity_reason,
            warnings=warnings,
        )

    def _discover_js_test_conventions(
        self,
        files: Sequence[str],
        language: str,
    ) -> Tuple[Optional[str], str]:
        """Find existing test directory and naming convention for JS/TS."""
        test_dir: Optional[str] = None
        spec_count = 0
        test_count = 0

        for cand in ("__tests__", "src/__tests__", "tests", "src/tests", "spec"):
            if any(f.startswith(f"{cand}/") for f in files):
                test_dir = cand
                break

        for f in files:
            if ".spec." in f:
                spec_count += 1
            elif ".test." in f:
                test_count += 1

        is_ts = language == "TypeScript"
        if spec_count > test_count:
            naming_pattern = "suffix:.spec.ts" if is_ts else "suffix:.spec.js"
        else:
            naming_pattern = "suffix:.test.ts" if is_ts else "suffix:.test.js"

        return test_dir, naming_pattern

    # -----------------------------------------------------------------------
    # Other Languages (Go, Java)
    # -----------------------------------------------------------------------

    def _detect_go_framework(self, root: Optional[Path], files: Sequence[str]) -> FrameworkDetectionResult:
        """Detect Go test runner conventions."""
        return FrameworkDetectionResult(
            framework="go test",
            language="Go",
            is_supported=False,
            status="UNSUPPORTED_FRAMEWORK",
            test_command="go test ./...",
            naming_pattern="suffix:_test.go",
            warnings=["'go test' detected. Initial TestGenerationService supports pytest, unittest, and jest."],
        )

    def _detect_java_framework(self, root: Optional[Path], files: Sequence[str]) -> FrameworkDetectionResult:
        """Detect Java JUnit / Maven conventions."""
        return FrameworkDetectionResult(
            framework="junit",
            language="Java",
            is_supported=False,
            status="UNSUPPORTED_FRAMEWORK",
            test_command="mvn test",
            naming_pattern="suffix:Test.java",
            warnings=["JUnit detected. Initial TestGenerationService supports pytest, unittest, and jest."],
        )

    # -----------------------------------------------------------------------
    # Safe Helper Methods
    # -----------------------------------------------------------------------

    def _read_file(self, root: Optional[Path], rel_path: str) -> str:
        """Safely read text file from repository root."""
        if not root:
            return ""
        try:
            full_path = (root / rel_path).resolve()
            # Guard against path traversal escaping root
            full_path.relative_to(root)
            if full_path.is_file():
                return full_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
        return ""
