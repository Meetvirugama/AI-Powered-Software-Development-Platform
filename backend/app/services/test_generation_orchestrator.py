"""End-to-end orchestration for Week 2 Day 4 Framework-Aware Test Generation (`POST /repositories/{id}/generate-tests`).

Owner: Yug (API & Orchestration), Dev (TestGenerationService), Devu (Validation), Sukun (Security), Om (History)

Implements the complete Day 4 & Scenario C / E requirements from `Docs/week2.md` §8 & §12:
1. Target & Symbol Resolution (reuses `resolve_target_and_build_context` from `explanation_orchestrator.py`
   so file/symbol/range targets, caller edges, and project rules are resolved identically).
2. Repository-Aware Framework & Convention Detection (`detect_repository_test_framework`):
   - Inspects indexed repository manifests (`pytest.ini`, `pyproject.toml`, `requirements.txt`,
     `package.json`, `jest.config.*`, `conftest.py`) and existing test files.
   - Supports `pytest`, `unittest`, and `jest`.
   - Rejects unsupported runners (e.g. `vitest`, `mocha`, `go test`, `junit`) with explicit
     `400 UNSUPPORTED_TARGET` rather than silently generating incompatible tests.
   - Prevents silently generating Jest tests when a JS/TS repository has no Jest configuration
     or when the user requests a framework mismatching the target language.
3. Test Context Assembly (`build_repository_test_context`):
   - Uses Meet's `TestContextBuilder` with detected framework, `conftest.py` fixtures,
     mockable external calls (`db.query`, `httpx.post`, `redis.set`), and sample existing test code.
4. Generated Test Validation & Security (`validate_and_sanitize_generated_tests`):
   - Validates proposed test file path via `validate_repo_relative_path` (blocks `../` and absolute paths).
   - Warns explicitly in `assumptions_and_warnings` if `proposed_test_path` already exists in the
     indexed repository; never writes to disk or executes arbitrary code automatically.
   - Redacts any raw secrets (`[REDACTED]`) from `test_content`, `covered_scenarios`, and warnings.
   - Performs AST / structural syntax validation (`ast.parse` for Python, balanced delimiter and
     `test(`/`it(` assertion checks for Jest) and populates `syntax_valid` and `validation_errors`.
5. Grounding & History Persistence:
   - Grounds `sources` against indexed `repository_files`.
   - Persists `COMPLETED` (with `test_output` stored in dedicated `Text` column) and `FAILED` runs
     separately via `record_analysis_run` and Om's `AnalysisRunRepository`.
"""

from __future__ import annotations

import ast
import configparser
import json
import logging
import os
from pathlib import Path
import re
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from ai.context.builder import (
    ContextBuilder,
    IntelligenceContext,
    RepositoryFile as ContextRepoFile,
    SymbolContext,
    TargetSnippet,
)
from ai.context.test_context import TestContextBuilder
from ai.llm.schemas import (
    LLMRequest,
    LLMValidationError,
    Message,
)
from ai.schemas.prompt_builder import _fence
from app.core.errors import APIError, ErrorCode
from app.core.input_security import UnsafePathError, validate_repo_relative_path
from app.models.code_chunk import CodeChunk
from app.models.repository import Repository
from app.models.repository_file import RepositoryFile
from app.schemas.analysis import (
    AnalysisSourceReference,
    ExplainCodeRequest,
    SupportedTestFramework,
    TestGenerationRequest,
    TestGenerationResult,
    TestScenario,
)
from app.services.bug_detection_orchestrator import redact_secrets_in_text
from app.services.explanation_orchestrator import (
    ResolvedExplanationTarget,
    resolve_target_and_build_context,
)
from scanner.framework_detector import FrameworkDetectionResult, FrameworkDetector

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Database-Backed Framework & Convention Detection
# ---------------------------------------------------------------------------

def _reconstruct_file_text(
    db: Session,
    repository_id: UUID,
    file_record: RepositoryFile | None,
) -> str:
    """Reconstruct indexed file content from `code_chunks` ordered by `start_line`."""
    if file_record is None or not hasattr(db, "query"):
        return ""
    try:
        chunks: list[CodeChunk] = (
            db.query(CodeChunk)
            .filter(
                CodeChunk.repository_id == repository_id,
                CodeChunk.file_id == file_record.id,
            )
            .order_by(CodeChunk.start_line)
            .all()
        )
        return "\n".join(c.content for c in chunks if c.content)
    except Exception:
        return ""


def detect_repository_test_framework(
    repository_id: UUID,
    target_path: str,
    requested_framework: SupportedTestFramework | None,
    db: Session | Any,
) -> tuple[FrameworkDetectionResult, dict[str, str], list[RepositoryFile]]:
    """Detect the repository's test framework, fixtures, and conventions from indexed DB files.

    Returns `(detection_result, manifest_contents_by_path, all_repo_files)`.
    """
    all_repo_files: list[RepositoryFile] = []
    if hasattr(db, "query"):
        try:
            all_repo_files = (
                db.query(RepositoryFile)
                .filter(RepositoryFile.repository_id == repository_id)
                .order_by(RepositoryFile.path)
                .all()
            )
        except Exception:
            all_repo_files = []

    file_list = [f.path for f in all_repo_files]
    path_to_record = {f.path: f for f in all_repo_files}

    # Load key manifest and conftest/test files from DB chunks so FrameworkDetector can inspect them
    manifest_contents: dict[str, str] = {}
    interesting_names = {
        "pytest.ini",
        "pyproject.toml",
        "setup.cfg",
        "tox.ini",
        "requirements.txt",
        "Pipfile",
        "package.json",
        "jest.config.js",
        "jest.config.ts",
        "jest.config.mjs",
        "jest.config.json",
        "tsconfig.json",
        "conftest.py",
    }
    test_file_samplesLoaded = 0
    for f_rec in all_repo_files:
        base_name = os.path.basename(f_rec.path)
        is_manifest = base_name in interesting_names
        is_py_test = base_name.endswith(".py") and (
            base_name.startswith("test_") or base_name.endswith("_test.py")
        )
        if is_manifest or (is_py_test and test_file_samplesLoaded < 8):
            text = _reconstruct_file_text(db, repository_id, f_rec)
            if text:
                manifest_contents[f_rec.path] = text
                if is_py_test:
                    test_file_samplesLoaded += 1

    detector = FrameworkDetector(repo_root=None)
    # Monkeypatch _read_file on this detector instance to read from indexed DB chunks
    detector._read_file = lambda _root, rel_path: manifest_contents.get(  # type: ignore[method-assign]
        rel_path.replace("\\", "/").lstrip("/"), ""
    )

    # First detect without preferred_framework so we can check actual project support
    raw_detection = detector.detect(
        repo_root=None,
        target_file=target_path,
        file_list=file_list if file_list else [target_path],
        preferred_framework=None,
    )

    ext = os.path.splitext(target_path)[1].lower()
    is_python_target = ext == ".py" or raw_detection.language == "Python"
    is_js_ts_target = ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs") or raw_detection.language in (
        "TypeScript",
        "JavaScript",
    )

    # Validate explicit framework override against target language and project dependencies
    if requested_framework is not None:
        if is_python_target and requested_framework == "jest":
            raise APIError(
                400,
                ErrorCode.UNSUPPORTED_TARGET,
                f"Cannot generate '{requested_framework}' tests for Python file '{target_path}'. "
                "Supported Python frameworks are 'pytest' and 'unittest'.",
            )
        if is_js_ts_target and requested_framework in ("pytest", "unittest"):
            raise APIError(
                400,
                ErrorCode.UNSUPPORTED_TARGET,
                f"Cannot generate '{requested_framework}' tests for {raw_detection.language} file '{target_path}'.",
            )
        if is_js_ts_target and requested_framework == "jest" and file_list:
            # Docs/week2.md §8: Do not silently generate Jest tests for a repository configured
            # exclusively for a different runner (e.g. Vitest/Mocha).
            if (
                raw_detection.status == "UNSUPPORTED_FRAMEWORK"
                and "jest" not in raw_detection.candidate_frameworks
            ):
                raise APIError(
                    400,
                    ErrorCode.UNSUPPORTED_TARGET,
                    f"Repository is configured for '{raw_detection.framework}', not 'jest'. "
                    + " ".join(raw_detection.warnings),
                )

    detection = detector.detect(
        repo_root=None,
        target_file=target_path,
        file_list=file_list if file_list else [target_path],
        preferred_framework=requested_framework,
    )

    if not detection.is_supported or detection.framework not in ("pytest", "unittest", "jest"):
        reason = (
            "; ".join(detection.warnings)
            or detection.ambiguity_reason
            or f"Unsupported test framework '{detection.framework}' for '{target_path}'."
        )
        raise APIError(
            400,
            ErrorCode.UNSUPPORTED_TARGET,
            reason,
        )

    return detection, manifest_contents, all_repo_files


# ---------------------------------------------------------------------------
# 2. Test Context Assembly
# ---------------------------------------------------------------------------

def build_repository_test_context(
    repository_id: UUID,
    resolved: ResolvedExplanationTarget,
    detection: FrameworkDetectionResult,
    manifest_contents: dict[str, str],
    all_repo_files: list[RepositoryFile],
    token_budget: int = 10_000,
) -> tuple[IntelligenceContext, str]:
    """Build enriched test generation context using Meet's `TestContextBuilder`."""
    framework = detection.framework or "pytest"
    proposed_path = detection.propose_test_path(resolved.target.path)
    if not proposed_path:
        candidates = TestContextBuilder.infer_candidate_test_paths(resolved.target.path, framework)
        proposed_path = candidates[0] if candidates else f"tests/test_{Path(resolved.target.path).stem}.py"

    existing_test_files: list[ContextRepoFile] = []
    sample_test_code: str | None = None
    target_stem = Path(resolved.target.path).stem.lower()

    for f_rec in all_repo_files:
        p_lower = f_rec.path.lower()
        if "test" in p_lower or "spec" in p_lower:
            ctx_f = ContextRepoFile(
                id=str(f_rec.id),
                path=f_rec.path,
                language=f_rec.language or detection.language,
                size_bytes=f_rec.size_bytes or 0,
                line_count=f_rec.line_count or 0,
                content_hash=f_rec.content_hash or "",
            )
            existing_test_files.append(ctx_f)
            if sample_test_code is None and (
                target_stem in p_lower or f_rec.path in manifest_contents
            ):
                sample_test_code = manifest_contents.get(f_rec.path)

    if sample_test_code is None:
        for path_k, text_v in manifest_contents.items():
            if os.path.basename(path_k).startswith("test_") or ".test." in path_k:
                sample_test_code = text_v
                break

    fixture_defs = [
        f"{fd['name']} (scope={fd.get('scope', 'function')}, file={fd.get('file', 'conftest.py')})"
        for fd in detection.fixture_details
    ] or list(detection.fixtures)

    target_snippet = TargetSnippet(
        file_path=resolved.target.path,
        content=resolved.code_content,
        start_line=resolved.target.start_line or 1,
        end_line=resolved.target.end_line or (
            resolved.file_record.line_count if resolved.file_record and resolved.file_record.line_count else 1
        ),
        symbol_name=resolved.target.symbol or (
            resolved.resolved_symbol.name if resolved.resolved_symbol else None
        ),
        language=detection.language,
        revision=resolved.revision,
    )

    test_ctx = TestContextBuilder().build_context(
        target=target_snippet,
        framework=framework,
        existing_test_files=existing_test_files,
        sample_test_code=sample_test_code,
        mockable_dependencies=resolved.intelligence_context.related_symbols,
        fixture_definitions=fixture_defs,
        repository_files=resolved.intelligence_context.repository_files,
        project_rules=resolved.intelligence_context.project_rules,
        token_budget=token_budget,
        revision=resolved.revision,
    )

    return test_ctx, proposed_path


# ---------------------------------------------------------------------------
# 3. Syntax / Structural Validation & Secret Sanitization
# ---------------------------------------------------------------------------

def validate_generated_test_syntax(
    test_content: str,
    framework: SupportedTestFramework,
    proposed_test_path: str = "tests/test_generated.py",
) -> tuple[bool, list[str]]:
    """Perform static syntax and structural assertion validation on generated test code.

    Keeps syntax validity distinct from runtime test execution (`Docs/week2.md` §8 Devu & Keval).
    """
    errors: list[str] = []
    if not test_content or not test_content.strip():
        return False, ["Generated test content is empty."]

    if framework in ("pytest", "unittest") or proposed_test_path.endswith(".py"):
        try:
            tree = ast.parse(test_content, filename=proposed_test_path)
        except SyntaxError as exc:
            line_info = f" at line {exc.lineno}" if exc.lineno else ""
            errors.append(f"Python syntax error{line_info}: {exc.msg}")
            return False, errors

        test_funcs: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        has_assertions = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_"):
                    test_funcs.append(node)
            elif isinstance(node, ast.Assert):
                has_assertions = True
            elif isinstance(node, ast.Call):
                func_name = ""
                if isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                elif isinstance(node.func, ast.Name):
                    func_name = node.func.id
                if (
                    func_name.startswith("assert")
                    or func_name in ("raises", "warns", "fail")
                ):
                    has_assertions = True

        if not test_funcs:
            errors.append("Generated Python test file does not define any `test_*` functions or methods.")
        if not has_assertions:
            errors.append("Generated Python test file does not contain any `assert` or `pytest.raises` statements.")

        return len(errors) == 0, errors

    # Jest / TypeScript / JavaScript structural checks
    if not re.search(r"\b(?:test|it)\s*\(", test_content):
        errors.append("Generated Jest file does not contain any `test(...)` or `it(...)` blocks.")
    if not re.search(r"\bexpect\s*\(", test_content):
        errors.append("Generated Jest file does not contain any `expect(...)` assertions.")

    # Check balanced braces/parentheses outside simple string literals
    stripped_strings = re.sub(r"(['\"`])(?:\\.|(?!\1).)*\1", '""', test_content)
    if stripped_strings.count("{") != stripped_strings.count("}"):
        errors.append("Unbalanced curly braces `{}` in generated Jest test file.")
    if stripped_strings.count("(") != stripped_strings.count(")"):
        errors.append("Unbalanced parentheses `()` in generated Jest test file.")

    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# Generated test-file path policy (W2 Day 4 — Sukun)
# ---------------------------------------------------------------------------

# Files that tools run or load automatically (or that define the project). A
# generated "test" must never be proposed under one of these names, because a
# developer exporting it would silently create auto-executed code.
_RESERVED_TEST_PATH_NAMES = frozenset({
    "conftest.py", "__init__.py", "setup.py", "setup.cfg", "pyproject.toml",
    "pytest.ini", "tox.ini", "noxfile.py", "manage.py", "sitecustomize.py",
    "usercustomize.py", "package.json", "package-lock.json", "tsconfig.json",
    "jest.config.js", "jest.config.ts", "jest.config.mjs", "jest.config.cjs",
    "jest.setup.js", "jest.setup.ts", "babel.config.js", ".babelrc", "makefile",
    "dockerfile", "docker-compose.yml",
})
_PY_TEST_NAME = re.compile(r"^(test_[\w\-]*|[\w\-]+_test)\.py$")
_JS_TEST_NAME = re.compile(r"^[\w.\-]+\.(test|spec)\.(js|jsx|ts|tsx|mjs|cjs)$")
_JS_EXT = re.compile(r"\.(js|jsx|ts|tsx|mjs|cjs)$")


def check_generated_test_path(path: str, framework: str | None) -> str | None:
    """Return a reason string if `path` is not an acceptable generated-test location, else None.

    `path` must already be repo-relative and traversal-free (validate_repo_relative_path).
    Rules: no hidden directories (.github/, .git/, .husky/ ...), no reserved/auto-run file
    names, and the file name must look like a test for the detected framework.
    """
    parts = path.split("/")
    name = parts[-1]
    if any(part.startswith(".") for part in parts):
        return "hidden directories such as .github/ or .git/ are not allowed"
    if name.lower() in _RESERVED_TEST_PATH_NAMES:
        return f"'{name}' is a reserved or automatically executed file"
    fw = (framework or "").lower()
    if fw in ("pytest", "unittest"):
        if not _PY_TEST_NAME.match(name):
            return "Python test files must be named test_<name>.py or <name>_test.py"
    elif fw == "jest":
        if not (_JS_TEST_NAME.match(name) or ("__tests__" in parts[:-1] and _JS_EXT.search(name))):
            return "Jest test files must be named <name>.test.<ext> / <name>.spec.<ext> or live in __tests__/"
    elif not (_PY_TEST_NAME.match(name) or _JS_TEST_NAME.match(name)):
        return "file name does not look like a test file"
    return None


def validate_and_sanitize_generated_tests(
    result: TestGenerationResult,
    *,
    repository_id: UUID,
    resolved: ResolvedExplanationTarget,
    detection: FrameworkDetectionResult,
    default_proposed_path: str,
) -> TestGenerationResult:
    """Enforce path safety, overwrite warnings, secret redaction, syntax validation, and source grounding."""
    # 1. Validate proposed_test_path safety
    raw_path = result.proposed_test_path or default_proposed_path
    try:
        safe_test_path = validate_repo_relative_path(raw_path)
    except UnsafePathError as exc:
        raise APIError(
            500,
            ErrorCode.ANALYSIS_FAILED,
            f"Test generation produced an unsafe file path: {exc}",
            retryable=False,
        ) from exc

    # 1b. Security (W2 Day 4, Sukun): a safe path is not enough — the model must not
    # propose overwriting source/config files or auto-executed files (conftest.py,
    # .github/workflows/...). Fall back to the convention-derived path instead.
    path_policy_warning: str | None = None
    rejection = check_generated_test_path(safe_test_path, result.detected_framework)
    if rejection is not None:
        try:
            fallback = validate_repo_relative_path(default_proposed_path)
        except UnsafePathError:
            fallback = None
        if fallback is None or check_generated_test_path(fallback, result.detected_framework) is not None:
            raise APIError(
                500,
                ErrorCode.ANALYSIS_FAILED,
                "Test generation produced a test file path that is not allowed.",
                retryable=False,
            )
        path_policy_warning = (
            f"The AI proposed '{safe_test_path}', which is not allowed ({rejection}); "
            f"using '{fallback}' instead."
        )
        safe_test_path = fallback

    # 2. Redact secrets from generated test code, scenarios, and warnings
    clean_content = redact_secrets_in_text(result.test_content)
    clean_scenarios = [
        TestScenario(
            name=redact_secrets_in_text(s.name),
            category=s.category,
            description=redact_secrets_in_text(s.description),
        )
        for s in result.covered_scenarios
    ]
    warnings: list[str] = [
        redact_secrets_in_text(w)
        for w in [*detection.warnings, *result.assumptions_and_warnings]
        if w and w.strip()
    ]
    if detection.is_ambiguous and detection.ambiguity_reason:
        warnings.append(detection.ambiguity_reason)
    if path_policy_warning:
        warnings.insert(0, path_policy_warning)

    # 3. Warn if proposed_test_path already exists in indexed repository (never overwrite silently!)
    if safe_test_path in resolved.indexed_paths:
        overwrite_warning = (
            f"Proposed test file '{safe_test_path}' already exists in the repository; "
            "preview and export carefully to avoid overwriting existing tests."
        )
        if overwrite_warning not in warnings:
            warnings.insert(0, overwrite_warning)

    # 4. Syntax & structural validation
    syntax_ok, syntax_errs = validate_generated_test_syntax(
        clean_content,
        result.detected_framework,
        safe_test_path,
    )
    # Syntax errors can quote source lines — redact them too.
    merged_val_errors = list(dict.fromkeys(
        redact_secrets_in_text(e) for e in [*result.validation_errors, *syntax_errs]
    ))
    final_syntax_valid = result.syntax_valid and syntax_ok and (len(merged_val_errors) == 0)

    # 5. Ground source references against indexed repository files
    grounded_sources: list[AnalysisSourceReference] = []
    for src in result.sources:
        try:
            clean_src_path = validate_repo_relative_path(src.file_path)
        except UnsafePathError:
            continue
        if resolved.indexed_paths:
            if clean_src_path not in resolved.indexed_paths:
                continue
            max_lines = resolved.indexed_paths[clean_src_path]
            if max_lines > 0:
                if src.start_line is not None and src.start_line > max_lines:
                    continue
                if src.end_line is not None and src.end_line > max_lines:
                    continue
        grounded_sources.append(
            src.model_copy(
                update={
                    "repository_id": str(repository_id),
                    "file_path": clean_src_path,
                    "revision": src.revision or resolved.revision,
                }
            )
        )

    if not grounded_sources and resolved.file_record is not None:
        grounded_sources.append(
            AnalysisSourceReference(
                repository_id=str(repository_id),
                file_path=resolved.target.path,
                start_line=resolved.target.start_line or 1,
                end_line=resolved.target.end_line or (resolved.file_record.line_count or 1),
                revision=resolved.revision,
                symbol_name=resolved.target.symbol,
            )
        )

    deduped_warnings = list(dict.fromkeys(warnings))
    return result.model_copy(
        update={
            "proposed_test_path": safe_test_path,
            "test_content": clean_content,
            "covered_scenarios": clean_scenarios,
            "assumptions_and_warnings": deduped_warnings,
            "syntax_valid": final_syntax_valid,
            "validation_errors": merged_val_errors,
            "sources": grounded_sources,
        }
    )


# ---------------------------------------------------------------------------
# 4. Default LLMTestGenerationService (Day 4 Service Adapter)
# ---------------------------------------------------------------------------

from ai.services.test_generation_service import TestGenerationService

# Maintain backward compatibility with existing tests and routes
LLMTestGenerationService = TestGenerationService


# ---------------------------------------------------------------------------
# Day 4 Union Helpers & Aliases (Compatible with both test_test_generation_day4.py and test_generate_tests_day4.py)
# ---------------------------------------------------------------------------

from dataclasses import dataclass, field
import posixpath
from scanner.test_mapper import FileTestMapper


@dataclass
class DetectedTestConventions:
    """Detected test runner, naming conventions, existing test directory, and overwrite status."""

    framework: SupportedTestFramework
    proposed_test_path: str
    existing_test_files: list[str] = field(default_factory=list)
    fixture_files: list[str] = field(default_factory=list)
    naming_pattern: str = "test_<module>.py"
    path_already_exists: bool = False
    warnings: list[str] = field(default_factory=list)


def propose_test_file_path(
    *,
    target_path: str,
    framework: SupportedTestFramework,
    indexed_paths: list[str],
    existing_py_tests: list[str],
    existing_js_tests: list[str],
) -> tuple[str, str]:
    """Compute a safe, convention-matching repository-relative path for the generated test file.

    Consults Prit's `FileTestMapper` (`backend/scanner/test_mapper.py`) first to see if an
    existing test file in `indexed_paths` already maps to `target_path`.
    """
    from uuid import uuid4

    clean_target = validate_repo_relative_path(target_path)

    if indexed_paths:
        try:
            synthetic_file_map = {
                uuid4(): p for p in indexed_paths if posixpath.basename(p) != "conftest.py"
            }
            mapper = FileTestMapper(symbols=[], edges=[], file_paths=synthetic_file_map)
            test_to_source = mapper.map_tests()
            for t_path, s_path in test_to_source.items():
                if s_path == clean_target:
                    safe_mapped = validate_repo_relative_path(t_path)
                    bname = posixpath.basename(safe_mapped)
                    if bname.endswith("_test.py"):
                        pat = "<module>_test.py"
                    elif bname.startswith("test_"):
                        pat = "test_<module>.py"
                    else:
                        pat = "<module>.test"
                    return safe_mapped, pat
        except Exception:
            pass

    parts = clean_target.split("/")
    filename = parts[-1]
    stem, ext = posixpath.splitext(filename)

    if framework in ("pytest", "unittest"):
        uses_suffix = bool(existing_py_tests) and all(
            posixpath.basename(p).endswith("_test.py") and not posixpath.basename(p).startswith("test_")
            for p in existing_py_tests
        )
        test_filename = f"{stem}_test.py" if uses_suffix else f"test_{stem}.py"
        naming_pattern = "<module>_test.py" if uses_suffix else "test_<module>.py"

        if parts[0] == "backend":
            test_dir = "backend/tests"
        elif any(p.startswith("tests/") for p in existing_py_tests) or "tests" in {
            p.split("/")[0] for p in indexed_paths
        }:
            test_dir = "tests"
        elif len(parts) > 1 and parts[0] not in ("src", "app", "lib"):
            test_dir = f"{parts[0]}/tests"
        else:
            test_dir = "tests"

        proposed = f"{test_dir}/{test_filename}"
        return validate_repo_relative_path(proposed), naming_pattern

    test_ext = ext if ext in (".ts", ".tsx", ".js", ".jsx") else ".ts"
    uses_spec = any(".spec." in posixpath.basename(p) for p in existing_js_tests)
    mid = "spec" if uses_spec else "test"
    test_filename = f"{stem}.{mid}{test_ext}"
    naming_pattern = f"<module>.{mid}{test_ext}"

    uses_dunder_tests = any("/__tests__/" in f"/{p}" for p in existing_js_tests)
    dir_part = "/".join(parts[:-1])
    if uses_dunder_tests:
        proposed = f"{dir_part}/__tests__/{test_filename}" if dir_part else f"__tests__/{test_filename}"
    else:
        proposed = f"{dir_part}/{test_filename}" if dir_part else test_filename

    return validate_repo_relative_path(proposed), naming_pattern


def detect_test_framework_and_conventions(
    repository_id: UUID,
    repo: Repository | Any,
    payload: TestGenerationRequest,
    resolved: ResolvedExplanationTarget,
    db: Session | Any,
) -> DetectedTestConventions:
    """Detect test framework & conventions using both FrameworkDetector and FileTestMapper."""
    detection, _, _ = detect_repository_test_framework(
        repository_id=repository_id,
        target_path=resolved.target.path,
        requested_framework=payload.framework,
        db=db,
    )
    indexed_paths = list(resolved.indexed_paths.keys())
    existing_py_tests = [
        p
        for p in indexed_paths
        if p.endswith(".py")
        and (
            posixpath.basename(p).startswith("test_")
            or posixpath.basename(p).endswith("_test.py")
            or "/tests/" in f"/{p}"
        )
    ]
    existing_js_tests = [
        p
        for p in indexed_paths
        if any(
            p.endswith(s)
            for s in (
                ".test.ts",
                ".spec.ts",
                ".test.tsx",
                ".spec.tsx",
                ".test.js",
                ".spec.js",
                ".test.jsx",
                ".spec.jsx",
            )
        )
        or "/__tests__/" in f"/{p}"
    ]
    fw: SupportedTestFramework = (detection.framework or "pytest")  # type: ignore[assignment]
    proposed_path, naming_pattern = propose_test_file_path(
        target_path=resolved.target.path,
        framework=fw,
        indexed_paths=indexed_paths,
        existing_py_tests=existing_py_tests,
        existing_js_tests=existing_js_tests,
    )
    warnings = list(detection.warnings)
    path_exists = proposed_path in resolved.indexed_paths
    if path_exists:
        warnings.append(
            f"Proposed test file '{proposed_path}' already exists in the repository; preview carefully before overwriting."
        )
    return DetectedTestConventions(
        framework=fw,
        proposed_test_path=proposed_path,
        existing_test_files=existing_py_tests if fw in ("pytest", "unittest") else existing_js_tests,
        fixture_files=list(detection.fixtures),
        naming_pattern=naming_pattern,
        path_already_exists=path_exists,
        warnings=warnings,
    )


def validate_generated_test_code(
    test_content: str,
    framework: SupportedTestFramework,
    proposed_test_path: str = "<generated_test>",
) -> tuple[bool, list[str]]:
    """Validate generated test code syntax and assertions without executing untrusted code."""
    default_ext = ".ts" if framework == "jest" else ".py"
    effective_path = (
        proposed_test_path
        if proposed_test_path != "<generated_test>"
        else f"generated_test{default_ext}"
    )
    return validate_generated_test_syntax(test_content, framework, effective_path)


def sanitize_and_ground_test_result(
    raw_result: TestGenerationResult,
    *,
    repository_id: UUID,
    resolved: ResolvedExplanationTarget,
    conventions: DetectedTestConventions,
) -> TestGenerationResult:
    """Adapter wrapping validate_and_sanitize_generated_tests with DetectedTestConventions."""
    synth_detection = FrameworkDetectionResult(
        language="TypeScript" if conventions.framework == "jest" else "Python",
        framework=conventions.framework,
        confidence="high",
        status="DETECTED",
        is_supported=True,
        fixtures=list(conventions.fixture_files),
        warnings=list(conventions.warnings),
    )
    return validate_and_sanitize_generated_tests(
        raw_result,
        repository_id=repository_id,
        resolved=resolved,
        detection=synth_detection,
        default_proposed_path=conventions.proposed_test_path,
    )
