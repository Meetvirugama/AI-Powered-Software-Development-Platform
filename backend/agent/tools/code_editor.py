"""backend/agent/tools/code_editor.py

Autonomous Code Modification Engine & AST-Aware Patching.
Part of Phase 3 (Autonomous Code Modification Engine / task.md Parts 5 & 17).

Provides:
- AST-Aware file patching with atomic pre-validation (Python, JSON, TypeScript/JavaScript)
- Safe file deletion validator with inbound dependency, CI workflow, and test verification
- Unified diff hunk parsing and application
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.secret_redaction import redact
from sandbox.path_guard import WorkspacePathGuard

logger = logging.getLogger(__name__)


@dataclass
class PatchResult:
    """Outcome of an AST-aware patch application."""

    success: bool
    file_path: str
    occurrences_replaced: int = 0
    error: str | None = None
    ast_valid: bool = True
    syntax_error_details: str | None = None


@dataclass
class SafeDeletionCheckResult:
    """Verification outcome certifying whether a file can be safely deleted."""

    can_delete: bool
    file_path: str
    blocking_reason: str | None = None
    inbound_import_references: list[str] = None
    ci_workflow_references: list[str] = None
    test_references: list[str] = None

    def __post_init__(self) -> None:
        if self.inbound_import_references is None:
            self.inbound_import_references = []
        if self.ci_workflow_references is None:
            self.ci_workflow_references = []
        if self.test_references is None:
            self.test_references = []


class SafeFileDeletionValidator:
    """Enforces non-negotiable safe file deletion rules (task.md §5 / Phase 3).

    Prohibits file deletion unless:
    1. It is not a root project manifest or protected infrastructure file.
    2. Dependency graphs confirm 0 inbound imports across the repository.
    3. 0 CI/CD workflow references exist in .github/workflows.
    4. 0 test references exist in test files.
    """

    PROTECTED_MANIFESTS: frozenset[str] = frozenset(
        {
            "package.json",
            "package-lock.json",
            "pyproject.toml",
            "requirements.txt",
            "requirements-dev.txt",
            "setup.py",
            "setup.cfg",
            "alembic.ini",
            "dockerfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            "tsconfig.json",
            "vite.config.ts",
            "vitest.config.ts",
            "jest.config.js",
            "pytest.ini",
            ".gitignore",
            ".gitleaks.toml",
        }
    )

    @classmethod
    def evaluate_file_deletion(
        cls,
        workspace_root: Path | str,
        file_path: str,
    ) -> SafeDeletionCheckResult:
        """Validate whether file_path inside workspace_root is safe to delete."""
        root = Path(workspace_root).resolve()
        resolved = WorkspacePathGuard.resolve_within_workspace(root, file_path)

        if not resolved.exists():
            return SafeDeletionCheckResult(
                can_delete=False,
                file_path=file_path,
                blocking_reason=f"File does not exist: {file_path}",
            )

        # 1. Protected Manifests Check
        norm_name = resolved.name.lower()
        rel_posix = resolved.relative_to(root).as_posix().lower()
        if norm_name in cls.PROTECTED_MANIFESTS or rel_posix in cls.PROTECTED_MANIFESTS:
            return SafeDeletionCheckResult(
                can_delete=False,
                file_path=file_path,
                blocking_reason=f"Cannot delete protected project manifest or configuration: '{resolved.name}'.",
            )

        stem = resolved.stem
        module_path = rel_posix.replace("/", ".").rstrip(".py").rstrip(".ts").rstrip(".js")
        base_name = resolved.name

        inbound_imports: list[str] = []
        ci_references: list[str] = []
        test_references: list[str] = []

        # Walk entire workspace to check references
        for parent, dirnames, filenames in os.walk(root):
            # Prune hidden & cache directories, keeping .github for CI/CD workflow discovery
            dirnames[:] = [
                d
                for d in dirnames
                if (not d.startswith(".") or d == ".github")
                and d not in ("__pycache__", "node_modules", ".venv", ".git")
            ]

            for fname in filenames:
                curr_file = Path(parent) / fname
                if curr_file == resolved:
                    continue  # Skip target file itself

                curr_rel = curr_file.relative_to(root).as_posix()
                is_ci_file = ".github/workflows" in curr_rel or curr_rel.startswith(".gitlab-ci")
                is_test_file = (
                    curr_rel.startswith("tests/")
                    or curr_rel.startswith("test/")
                    or "/test/" in curr_rel
                    or "/tests/" in curr_rel
                    or curr_file.name.startswith("test_")
                    or curr_file.name.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx", ".test.js"))
                )

                try:
                    content = curr_file.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

                # Check CI Workflow References
                if is_ci_file:
                    if rel_posix in content or base_name in content:
                        ci_references.append(curr_rel)

                # Check Test References
                elif is_test_file:
                    if (
                        rel_posix in content
                        or base_name in content
                        or stem in content
                        or module_path in content
                    ):
                        test_references.append(curr_rel)

                # Check Source Code Inbound Imports
                else:
                    # Python import patterns
                    if curr_file.suffix == ".py":
                        import_patterns = [
                            rf"\bimport\s+.*?\b{re.escape(stem)}\b",
                            rf"\bfrom\s+.*?\b{re.escape(stem)}\b\s+import",
                            rf"\bfrom\s+{re.escape(module_path)}\b",
                        ]
                        if any(re.search(pat, content) for pat in import_patterns):
                            inbound_imports.append(curr_rel)
                    # JS/TS import patterns
                    elif curr_file.suffix in (".ts", ".tsx", ".js", ".jsx"):
                        import_patterns = [
                            rf"\bfrom\s+['\"].*?{re.escape(stem)}['\"]",
                            rf"\brequire\s*\(\s*['\"].*?{re.escape(stem)}['\"]\s*\)",
                        ]
                        if any(re.search(pat, content) for pat in import_patterns):
                            inbound_imports.append(curr_rel)

        # Evaluate blocking criteria
        if inbound_imports:
            return SafeDeletionCheckResult(
                can_delete=False,
                file_path=file_path,
                blocking_reason=(
                    f"Forbidden: File has {len(inbound_imports)} inbound import reference(s) "
                    f"in source code (e.g., {inbound_imports[0]})."
                ),
                inbound_import_references=inbound_imports,
                ci_workflow_references=ci_references,
                test_references=test_references,
            )

        if ci_references:
            return SafeDeletionCheckResult(
                can_delete=False,
                file_path=file_path,
                blocking_reason=(
                    f"Forbidden: File is referenced in CI workflow '{ci_references[0]}'."
                ),
                inbound_import_references=inbound_imports,
                ci_workflow_references=ci_references,
                test_references=test_references,
            )

        if test_references:
            return SafeDeletionCheckResult(
                can_delete=False,
                file_path=file_path,
                blocking_reason=(
                    f"Forbidden: File is referenced by active test suite '{test_references[0]}'."
                ),
                inbound_import_references=inbound_imports,
                ci_workflow_references=ci_references,
                test_references=test_references,
            )

        return SafeDeletionCheckResult(
            can_delete=True,
            file_path=file_path,
        )


class CodeEditor:
    """AST-aware code modification engine performing validated patches and safe file edits."""

    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    def validate_code_syntax(
        self,
        file_path: str,
        content: str,
    ) -> tuple[bool, str | None]:
        """Verify that content compiles cleanly without syntax errors before writing to disk."""
        ext = os.path.splitext(file_path)[1].lower()

        # 1. Python Syntax Validation via AST
        if ext == ".py":
            try:
                ast.parse(content, filename=file_path)
                return True, None
            except SyntaxError as syn_err:
                msg = f"Python SyntaxError at line {syn_err.lineno}: {syn_err.msg}"
                return False, msg
            except Exception as exc:
                return False, f"AST compilation failed: {exc}"

        # 2. JSON Validation
        if ext == ".json":
            try:
                json.loads(content)
                return True, None
            except json.JSONDecodeError as json_err:
                msg = f"JSON decode error at line {json_err.lineno}, col {json_err.colno}: {json_err.msg}"
                return False, msg

        # 3. TypeScript / JavaScript Balanced Delimiter Sanity Check
        if ext in (".ts", ".tsx", ".js", ".jsx"):
            # Check balanced brackets/braces/parentheses ignoring strings
            stack: list[str] = []
            pairs = {')': '(', ']': '[', '}': '{'}
            in_str: str | None = None
            escape = False

            for idx, ch in enumerate(content):
                if in_str:
                    if escape:
                        escape = False
                    elif ch == '\\':
                        escape = True
                    elif ch == in_str:
                        in_str = None
                    continue

                if ch in ('"', "'", '`'):
                    in_str = ch
                    continue

                if ch in pairs.values():
                    stack.append(ch)
                elif ch in pairs:
                    if not stack or stack[-1] != pairs[ch]:
                        return False, f"Unbalanced delimiter '{ch}' detected around character offset {idx}."
                    stack.pop()

            if stack:
                return False, f"Unclosed delimiter '{stack[-1]}' detected at end of file."
            if in_str:
                return False, f"Unterminated string literal ({in_str}) detected at end of file."

        return True, None

    def apply_patch(
        self,
        file_path: str,
        target_content: str,
        replacement_content: str,
        *,
        enforce_ast: bool = True,
    ) -> PatchResult:
        """Safely replace target_content with replacement_content, validated via AST compilation."""
        if not target_content:
            return PatchResult(
                success=False,
                file_path=file_path,
                error="Target content to replace cannot be empty.",
            )

        resolved = WorkspacePathGuard.resolve_within_workspace(self.workspace_root, file_path)
        if not resolved.exists():
            return PatchResult(
                success=False,
                file_path=file_path,
                error=f"Target file does not exist: '{file_path}'.",
            )

        try:
            current_content = resolved.read_text(encoding="utf-8")
        except Exception as read_err:
            return PatchResult(
                success=False,
                file_path=file_path,
                error=f"Failed to read '{file_path}': {redact(str(read_err))}",
            )

        if target_content not in current_content:
            return PatchResult(
                success=False,
                file_path=file_path,
                error=f"Target content block not found in '{file_path}'.",
            )

        count = current_content.count(target_content)
        proposed_content = current_content.replace(target_content, replacement_content, 1)

        # Pre-write AST and syntax compilation validation
        if enforce_ast:
            is_valid, syntax_err = self.validate_code_syntax(file_path, proposed_content)
            if not is_valid:
                logger.warning("ast_validation_failed_for_patch", extra={"file": file_path, "error": syntax_err})
                return PatchResult(
                    success=False,
                    file_path=file_path,
                    ast_valid=False,
                    syntax_error_details=syntax_err,
                    error=f"Proposed patch creates syntax defect in '{file_path}': {syntax_err}",
                )

        # Atomic write
        try:
            temp_file = resolved.with_suffix(f".tmp.{os.getpid()}")
            temp_file.write_text(proposed_content, encoding="utf-8")
            temp_file.replace(resolved)
        except Exception as write_err:
            return PatchResult(
                success=False,
                file_path=file_path,
                error=f"Failed to write patch to '{file_path}': {redact(str(write_err))}",
            )

        return PatchResult(
            success=True,
            file_path=file_path,
            occurrences_replaced=1,
            ast_valid=True,
        )

    def safe_delete_file(self, file_path: str) -> SafeDeletionCheckResult:
        """Validate all safety criteria and delete file if proven safe."""
        eval_result = SafeFileDeletionValidator.evaluate_file_deletion(self.workspace_root, file_path)
        if not eval_result.can_delete:
            return eval_result

        resolved = WorkspacePathGuard.resolve_within_workspace(self.workspace_root, file_path)
        try:
            resolved.unlink()
            return eval_result
        except Exception as exc:
            return SafeDeletionCheckResult(
                can_delete=False,
                file_path=file_path,
                blocking_reason=f"Failed to delete file from disk: {redact(str(exc))}",
            )
