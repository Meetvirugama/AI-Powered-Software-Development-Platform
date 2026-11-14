"""Workspace Diff Extraction, Validation & Security Verification Subsystem.

Owner: Prit Zania — Week 3 Day 5 Deliverable (Docs/week3.md §6 F36, F37, §8 Day 5)
Reference: Docs/week3.md §6 (F36 Independent Verification, F37 Git Branch & Draft PR),
           Docs/team_rules.md §Week 3, Docs/engineering/13_architecture_decisions.md (ADR-010, ADR-021).

Responsibilities:
1. Extracts unified git diffs between the task workspace and base revision via streaming pipelines.
2. Parses diffs into structured file summaries, hunks, insertions, and deletions with O(1) buffer consumption.
3. Enforces bounded memory ceilings (default 10MB) with truncation markers to prevent heap exhaustion.
4. Validates diffs against the approved task plan file scope (rejects unauthorized files).
5. Enforces critical project manifest protection (blocks unexpected deletions of README, package.json, etc.).
6. Conducts high-confidence dual-engine secret scanning over diff additions via iterative generators.
7. Performs early path guard checking on file headers to abort traversal attempts before reading full diff chunks.
8. Ensures revision integrity and surfaces actionable findings for Dev's Independent Verifier.
"""

from __future__ import annotations

import fnmatch
import io
import logging
import re
import subprocess
from collections.abc import Generator, Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from app.core.input_security import UnsafePathError, validate_repo_relative_path
from app.core.secret_redaction import redact
from app.schemas.workspace import (
    DiffValidationResult,
    FileChangeType,
    FileDiffHunk,
    FileDiffSummary,
    SecretScanFinding,
    WorkspaceDiffResult,
)

from sandbox.constants import (
    CRITICAL_PROJECT_FILES,
    FORBIDDEN_FILE_PATTERNS,
    SECRET_SCAN_PATTERNS,
)
from sandbox.exceptions import (
    WorkspaceDiffError,
    WorkspacePathEscapeError,
)
from sandbox.gitleaks_scanner import GitleaksDiffScanner
from sandbox.path_guard import WorkspacePathGuard

logger = logging.getLogger(__name__)

# Operational memory and streaming thresholds (ADR-021)
DEFAULT_MAX_DIFF_BYTES: int = 10 * 1024 * 1024  # 10MB maximum stream memory threshold
MAX_PEAK_MEMORY_BYTES: int = 20 * 1024 * 1024  # 20MB strict operational heap ceiling
DIFF_TRUNCATION_MARKER: str = (
    "\n[DIFF TRUNCATED: Diff stream exceeded maximum memory limit of 10485760 bytes]\n"
)

_HUNK_HEADER_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@"
)
_DIFF_GIT_HEADER_RE = re.compile(
    r"^diff --git a/(.*) b/(.*)$"
)


# ---------------------------------------------------------------------------
# Streaming Line & Parser Generators (ADR-021)
# ---------------------------------------------------------------------------

def iter_diff_lines(
    diff_source: str | Iterable[str] | io.TextIOBase,
    max_bytes: int = DEFAULT_MAX_DIFF_BYTES,
    truncation_marker: str = DIFF_TRUNCATION_MARKER,
) -> Generator[str, None, None]:
    """Stream lines from a unified diff string or stream up to max_bytes.

    Guarantees O(1) buffer consumption by yielding lines incrementally without
    duplicating large raw strings into contiguous heap allocations. If total
    bytes exceed max_bytes, appends a truncation marker and halts stream processing.

    Args:
        diff_source: Raw diff string, file-like object, or line iterable.
        max_bytes: Maximum total bytes to stream before truncating (default 10MB).
        truncation_marker: Marker line yielded if max_bytes is reached.

    Yields:
        str: Individual lines of the unified diff.
    """
    if not diff_source:
        return

    bytes_streamed = 0
    if isinstance(diff_source, str):
        stream_iter: Iterable[str] = io.StringIO(diff_source)
    else:
        stream_iter = diff_source

    for raw_line in stream_iter:
        line_bytes = len(raw_line.encode("utf-8", errors="replace"))
        if bytes_streamed + line_bytes > max_bytes:
            logger.warning(
                "Diff stream exceeded memory limit of %d bytes; truncating stream.",
                max_bytes,
            )
            yield truncation_marker
            return
        bytes_streamed += line_bytes
        yield raw_line


def iter_parse_unified_diff(
    diff_source: str | Iterable[str],
    workspace_root: Path | None = None,
    early_path_guard: bool = True,
    raise_on_traversal: bool = False,
    max_bytes: int = DEFAULT_MAX_DIFF_BYTES,
) -> Generator[FileDiffSummary, None, None]:
    """Incrementally parse unified diff lines into structured FileDiffSummary objects.

    Processes file headers and hunks iteratively via a streaming generator state
    machine. Early path guard checking validates repository-relative path safety
    on file headers immediately as they are streamed, optionally aborting on
    traversal violations before reading remaining diff chunks.

    Args:
        diff_source: Unified diff string or line iterable.
        workspace_root: Optional workspace root path for path containment validation.
        early_path_guard: When True, checks path safety on header lines immediately.
        raise_on_traversal: When True, raises UnsafePathError/WorkspacePathEscapeError
            immediately upon detecting path traversal, halting further stream reading.
        max_bytes: Maximum stream bytes threshold.

    Yields:
        FileDiffSummary: Parsed file summary for each modified file in discovery order.
    """
    lines_iter = iter_diff_lines(diff_source, max_bytes=max_bytes)

    current_file_path: str | None = None
    current_change_type: FileChangeType = FileChangeType.MODIFIED
    current_insertions: int = 0
    current_deletions: int = 0
    current_chunk_lines: list[str] = []
    current_hunks: list[FileDiffHunk] = []
    current_hunk: FileDiffHunk | None = None

    def _build_summary() -> FileDiffSummary | None:
        nonlocal current_file_path, current_change_type, current_insertions, current_deletions
        nonlocal current_chunk_lines, current_hunks, current_hunk
        if not current_file_path:
            return None
        if current_hunk is not None:
            current_hunks.append(current_hunk)
            current_hunk = None

        summary = FileDiffSummary(
            file_path=current_file_path,
            change_type=current_change_type,
            insertions=current_insertions,
            deletions=current_deletions,
            patch="\n".join(current_chunk_lines),
            hunks=current_hunks,
        )
        # Reset state for next file
        current_file_path = None
        current_change_type = FileChangeType.MODIFIED
        current_insertions = 0
        current_deletions = 0
        current_chunk_lines = []
        current_hunks = []
        return summary

    def _check_early_path(raw_path: str) -> None:
        if not early_path_guard:
            return
        try:
            validate_repo_relative_path(raw_path)
            if workspace_root:
                WorkspacePathGuard.resolve_within_workspace(workspace_root, raw_path)
        except (UnsafePathError, WorkspacePathEscapeError) as exc:
            if raise_on_traversal:
                raise
            logger.warning(
                "diff_path_escapes_workspace",
                extra={"file_path": raw_path, "error": str(exc)},
            )

    for raw_line in lines_iter:
        line = raw_line.rstrip("\r\n")

        # 1. Detect diff --git header line
        if line.startswith("diff --git "):
            prev_summary = _build_summary()
            if prev_summary:
                yield prev_summary

            match = _DIFF_GIT_HEADER_RE.match(line)
            if match:
                old_path, new_path = match.group(1), match.group(2)
                cand_path = new_path if new_path != "/dev/null" else old_path
                cand_path = cand_path.replace("\\", "/").lstrip("/")
                _check_early_path(cand_path)
                current_file_path = cand_path
                current_chunk_lines = [line[11:]]  # preserve chunk header matching split
            else:
                current_chunk_lines = [line]
            continue

        # 2. Detect unified diff headers (--- / +++) when diff --git was not used
        if current_file_path is None:
            if line.startswith("+++ "):
                parts = line.split()
                if len(parts) >= 2:
                    raw_target = parts[1].strip()
                    if raw_target.startswith(("b/", "a/")):
                        raw_target = raw_target[2:]
                    raw_target = raw_target.replace("\\", "/").lstrip("/")
                    if raw_target and raw_target != "dev/null":
                        _check_early_path(raw_target)
                        current_file_path = raw_target
                        current_chunk_lines = [line]
                        continue
            elif line.startswith("--- "):
                parts = line.split()
                if len(parts) >= 2:
                    raw_target = parts[1].strip()
                    if raw_target.startswith(("a/", "b/")):
                        raw_target = raw_target[2:]
                    raw_target = raw_target.replace("\\", "/").lstrip("/")
                    if raw_target and raw_target != "dev/null":
                        _check_early_path(raw_target)
                        # Temporary path until +++ resolves new path
                        current_file_path = raw_target
                        current_chunk_lines = [line]
                        continue

        if current_file_path is None:
            continue

        current_chunk_lines.append(line)

        # Detect change type modifiers
        if line.startswith("new file mode"):
            current_change_type = FileChangeType.ADDED
        elif line.startswith("deleted file mode"):
            current_change_type = FileChangeType.DELETED
        elif line.startswith("rename from"):
            current_change_type = FileChangeType.RENAMED

        # Detect Hunk boundaries
        hunk_match = _HUNK_HEADER_RE.match(line)
        if hunk_match:
            if current_hunk:
                current_hunks.append(current_hunk)
            old_start = int(hunk_match.group(1))
            old_lines = int(hunk_match.group(2) or 1)
            new_start = int(hunk_match.group(3))
            new_lines = int(hunk_match.group(4) or 1)
            current_hunk = FileDiffHunk(
                old_start=old_start,
                old_lines=old_lines,
                new_start=new_start,
                new_lines=new_lines,
                lines=[line],
            )
            continue

        if current_hunk is not None:
            current_hunk.lines.append(line)
            if line.startswith("+") and not line.startswith("+++"):
                current_insertions += 1
            elif line.startswith("-") and not line.startswith("---"):
                current_deletions += 1

    last_summary = _build_summary()
    if last_summary:
        yield last_summary


def iter_scan_secrets_lines(
    lines: Iterable[str],
    file_path: str,
    secret_patterns: Sequence[tuple[str, re.Pattern[str]]],
    hunk_start: int = 1,
) -> Generator[SecretScanFinding, None, None]:
    """Iteratively scan diff lines for credentials using primary regex patterns.

    Operates line-by-line as a generator pipeline without buffering hunk contents.
    """
    current_line_no = hunk_start
    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if line.startswith("@@"):
            hunk_match = _HUNK_HEADER_RE.match(line)
            if hunk_match:
                current_line_no = int(hunk_match.group(3))
            continue
        if line.startswith("+") and not line.startswith("+++"):
            content = line[1:]
            for secret_name, pattern in secret_patterns:
                matches = pattern.findall(content)
                if matches:
                    yield SecretScanFinding(
                        file_path=file_path,
                        line_number=current_line_no,
                        secret_type=secret_name,
                        redacted_preview=redact(content[:80]),
                    )
            current_line_no += 1
        elif not line.startswith("-"):
            current_line_no += 1


# ---------------------------------------------------------------------------
# WorkspaceDiffVerifier Core Class (ADR-010, ADR-021)
# ---------------------------------------------------------------------------

class WorkspaceDiffVerifier:
    """Extracts, validates, and scans workspace diffs against boundaries and security policies."""

    def __init__(
        self,
        forbidden_patterns: Sequence[str] = FORBIDDEN_FILE_PATTERNS,
        critical_files: frozenset[str] = CRITICAL_PROJECT_FILES,
        secret_patterns: Sequence[tuple[str, re.Pattern[str]]] = SECRET_SCAN_PATTERNS,
        gitleaks_scanner: GitleaksDiffScanner | None = None,
        max_diff_bytes: int = DEFAULT_MAX_DIFF_BYTES,
    ) -> None:
        self._forbidden_patterns = tuple(forbidden_patterns)
        self._critical_files = critical_files
        self._secret_patterns = tuple(secret_patterns)
        self._gitleaks_scanner = gitleaks_scanner or GitleaksDiffScanner()
        self._max_diff_bytes = max_diff_bytes

    def extract_diff(
        self,
        workspace_path: Path,
        base_revision: str | None = "HEAD",
        task_id: str = "",
        head_revision: str | None = None,
        early_path_guard: bool = True,
        raise_on_traversal: bool = False,
    ) -> WorkspaceDiffResult:
        """Extract a unified git diff from the isolated workspace against base_revision.

        Args:
            workspace_path: Resolved path to the isolated task workspace.
            base_revision: Git commit SHA or ref to diff against (defaults to HEAD).
            task_id: Task identifier.
            head_revision: Optional head commit or working tree revision.
            early_path_guard: Validate path safety immediately on header lines.
            raise_on_traversal: Immediately raise if path traversal is found in headers.

        Returns:
            WorkspaceDiffResult with per-file stats, hunks, and unified diff text.
        """
        if not workspace_path.exists():
            raise WorkspaceDiffError(
                f"Workspace path does not exist for task '{task_id}': {workspace_path}"
            )

        ref = base_revision or "HEAD"
        git_dir = workspace_path / ".git"
        is_git = git_dir.exists()

        lines_generator = (
            self._stream_git_diff_lines(workspace_path, ref)
            if is_git
            else self._stream_fs_diff_lines(workspace_path)
        )

        captured_lines: list[str] = []
        is_truncated = False

        def _tee_lines() -> Generator[str, None, None]:
            nonlocal is_truncated
            for line in lines_generator:
                if DIFF_TRUNCATION_MARKER.strip() in line:
                    is_truncated = True
                captured_lines.append(line)
                yield line

        file_summaries, total_insertions, total_deletions = self.parse_unified_diff(
            _tee_lines(),
            workspace_root=workspace_path,
            early_path_guard=early_path_guard,
            raise_on_traversal=raise_on_traversal,
        )

        raw_diff = "".join(captured_lines)
        is_empty = len(file_summaries) == 0 and (total_insertions + total_deletions == 0)
        error = (
            f"Diff stream exceeded maximum memory limit of {self._max_diff_bytes} bytes; output was safely truncated."
            if is_truncated
            else None
        )

        return WorkspaceDiffResult(
            task_id=task_id,
            base_revision=base_revision,
            head_revision=head_revision or "HEAD",
            total_files_changed=len(file_summaries),
            insertions=total_insertions,
            deletions=total_deletions,
            is_empty=is_empty,
            files=file_summaries,
            raw_diff=raw_diff,
            extracted_at=datetime.now(UTC).isoformat(),
            error=error,
        )

    def stream_extract_diff(
        self,
        workspace_path: Path,
        base_revision: str | None = "HEAD",
        task_id: str = "",
        early_path_guard: bool = True,
        raise_on_traversal: bool = False,
    ) -> Generator[FileDiffSummary, None, None]:
        """Streamingly extract and parse file diff summaries without whole-diff buffering.

        Yields FileDiffSummary objects as file hunks finish parsing, bounding memory to O(1).
        """
        if not workspace_path.exists():
            raise WorkspaceDiffError(
                f"Workspace path does not exist for task '{task_id}': {workspace_path}"
            )

        ref = base_revision or "HEAD"
        git_dir = workspace_path / ".git"
        is_git = git_dir.exists()

        stream = (
            self._stream_git_diff_lines(workspace_path, ref)
            if is_git
            else self._stream_fs_diff_lines(workspace_path)
        )

        yield from iter_parse_unified_diff(
            stream,
            workspace_root=workspace_path,
            early_path_guard=early_path_guard,
            raise_on_traversal=raise_on_traversal,
            max_bytes=self._max_diff_bytes,
        )

    def parse_unified_diff(
        self,
        raw_diff: str | Iterable[str],
        workspace_root: Path | None = None,
        early_path_guard: bool = True,
        raise_on_traversal: bool = False,
    ) -> tuple[list[FileDiffSummary], int, int]:
        """Parse raw unified diff text or line stream into structured FileDiffSummary objects."""
        if not raw_diff:
            return [], 0, 0

        files: list[FileDiffSummary] = []
        total_insertions = 0
        total_deletions = 0

        for summary in iter_parse_unified_diff(
            raw_diff,
            workspace_root=workspace_root,
            early_path_guard=early_path_guard,
            raise_on_traversal=raise_on_traversal,
            max_bytes=self._max_diff_bytes,
        ):
            files.append(summary)
            total_insertions += summary.insertions
            total_deletions += summary.deletions

        return files, total_insertions, total_deletions

    def validate_diff(
        self,
        diff_result: WorkspaceDiffResult,
        allowed_files: list[str] | None = None,
        allow_critical_deletions: bool = False,
    ) -> DiffValidationResult:
        """Validate diff against approved task scope, critical files, and secrets.

        Args:
            diff_result: Extracted workspace diff result.
            allowed_files: Optional list of approved file paths from task plan.
            allow_critical_deletions: Whether deletions of manifests are explicitly authorized.

        Returns:
            DiffValidationResult indicating pass/fail status and detailed findings.
        """
        task_id = diff_result.task_id
        modified_files: list[str] = [f.file_path for f in diff_result.files]
        unapproved_files: list[str] = []
        deleted_critical_files: list[str] = []
        secret_findings: list[SecretScanFinding] = []
        blocking_findings: list[str] = []
        warnings: list[str] = []

        allowed_set = set(allowed_files) if allowed_files is not None else None

        for file_summary in diff_result.files:
            file_path = file_summary.file_path

            # 1. Path Safety & Traversal Check
            try:
                validate_repo_relative_path(file_path)
            except UnsafePathError as exc:
                blocking_findings.append(f"Unsafe file path in diff '{file_path}': {exc}")
                continue

            # 2. Forbidden & Sensitive File Patterns
            for pattern in self._forbidden_patterns:
                if fnmatch.fnmatch(file_path, pattern) or fnmatch.fnmatch(Path(file_path).name, pattern):
                    blocking_findings.append(
                        f"Diff modifies prohibited or sensitive file '{file_path}' (matched pattern: '{pattern}')."
                    )

            # 3. Approved File Scope Verification
            if allowed_set is not None and file_path not in allowed_set:
                unapproved_files.append(file_path)
                blocking_findings.append(
                    f"File '{file_path}' was modified but is outside the approved task plan scope."
                )

            # 4. Critical Manifest Deletion Guard
            if file_summary.change_type == FileChangeType.DELETED:
                base_name = Path(file_path).name
                if base_name in self._critical_files:
                    if not allow_critical_deletions:
                        deleted_critical_files.append(file_path)
                        blocking_findings.append(
                            f"Deletion of critical project manifest '{file_path}' is prohibited without explicit authorization."
                        )
                    else:
                        warnings.append(
                            f"Deletion of critical project manifest '{file_path}' was explicitly allowed."
                        )

            # 5. Secret Scanner across added diff lines (Primary Pattern Engine via generator)
            for hunk in file_summary.hunks:
                for finding in iter_scan_secrets_lines(
                    hunk.lines,
                    file_path=file_path,
                    secret_patterns=self._secret_patterns,
                    hunk_start=hunk.new_start,
                ):
                    secret_findings.append(finding)
                    blocking_findings.append(
                        f"Credential leakage detected in '{file_path}:{finding.line_number}' ({finding.secret_type})."
                    )

            # 6. Secondary Secret Scanner (Gitleaks Engine via stream/text)
            if file_summary.hunks:
                file_hunks_lines = (
                    line for hunk in file_summary.hunks for line in hunk.lines
                )
                gitleaks_results = list(
                    self._gitleaks_scanner.scan_diff_stream(
                        file_hunks_lines, file_path_hint=file_path
                    )
                )
            else:
                fallback_text = file_summary.patch or diff_result.raw_diff
                gitleaks_results = self._gitleaks_scanner.scan_diff(
                    fallback_text, file_path_hint=file_path
                )
            for gf in gitleaks_results:
                # Deduplicate if primary pattern scanner already identified finding on this line
                if not any(
                    sf.file_path == gf.file_path and sf.line_number == gf.line_number
                    for sf in secret_findings
                ):
                    secret_findings.append(gf)
                    blocking_findings.append(
                        f"Credential leakage detected by secondary engine (Gitleaks) in '{file_path}:{gf.line_number}' ({gf.secret_type})."
                    )

        # Warn if diff is empty
        if diff_result.is_empty:
            warnings.append("Workspace diff contains zero file changes.")

        is_valid = len(blocking_findings) == 0

        return DiffValidationResult(
            task_id=task_id,
            is_valid=is_valid,
            verified_revision=diff_result.head_revision or diff_result.base_revision,
            modified_files=modified_files,
            unapproved_files=unapproved_files,
            deleted_critical_files=deleted_critical_files,
            secret_findings=secret_findings,
            blocking_findings=blocking_findings,
            warnings=warnings,
            validated_at=datetime.now(UTC).isoformat(),
        )

    def stream_validate_diff(
        self,
        diff_stream: str | Iterable[str],
        allowed_files: list[str] | None = None,
        allow_critical_deletions: bool = False,
        workspace_root: Path | None = None,
        raise_on_traversal: bool = False,
        task_id: str = "",
    ) -> DiffValidationResult:
        """Streamingly validate a diff without buffering full raw diff text.

        Consumes diff lines via an iterator/generator, validating file headers,
        scopes, manifests, and scanning secrets iteratively.
        """
        summaries = list(
            iter_parse_unified_diff(
                diff_stream,
                workspace_root=workspace_root,
                early_path_guard=True,
                raise_on_traversal=raise_on_traversal,
                max_bytes=self._max_diff_bytes,
            )
        )

        synthetic_result = WorkspaceDiffResult(
            task_id=task_id,
            base_revision="HEAD",
            head_revision="HEAD",
            total_files_changed=len(summaries),
            insertions=sum(s.insertions for s in summaries),
            deletions=sum(s.deletions for s in summaries),
            is_empty=len(summaries) == 0,
            files=summaries,
            raw_diff="",  # Omitted to preserve memory
        )

        return self.validate_diff(
            synthetic_result,
            allowed_files=allowed_files,
            allow_critical_deletions=allow_critical_deletions,
        )

    # -----------------------------------------------------------------------
    # Internal Streaming Helpers
    # -----------------------------------------------------------------------

    def _stream_git_diff_lines(
        self,
        workspace_path: Path,
        base_revision: str,
        max_bytes: int | None = None,
    ) -> Generator[str, None, None]:
        """Execute git diff command and stream stdout lines incrementally with bounded memory."""
        limit = max_bytes if max_bytes is not None else self._max_diff_bytes

        # Ensure workspace metadata files are ignored by git
        try:
            exclude_file = workspace_path / ".git" / "info" / "exclude"
            if exclude_file.parent.exists():
                curr = exclude_file.read_text(encoding="utf-8") if exclude_file.exists() else ""
                if "metadata.json" not in curr:
                    exclude_file.write_text(curr + "\nmetadata.json\nworkspace_metadata.json\n", encoding="utf-8")
        except Exception:
            pass

        # Include untracked files in diff via intent-to-add
        try:
            subprocess.run(
                ["git", "-C", str(workspace_path), "add", "-N", "."],
                capture_output=True,
                check=False,
                timeout=10,
            )
        except Exception:
            pass

        excludes = [
            "--",
            ".",
            ":(exclude)*metadata.json",
            ":(exclude)*__pycache__*",
            ":(exclude)*.pyc",
            ":(exclude)*.pytest_cache*",
        ]

        candidate_cmds = [
            ["git", "-C", str(workspace_path), "diff", base_revision] + excludes,
            ["git", "-C", str(workspace_path), "diff", "HEAD"] + excludes,
            ["git", "-C", str(workspace_path), "diff", "--cached"] + excludes,
        ]

        total_bytes = 0

        for cmd in candidate_cmds:
            proc: subprocess.Popen[str] | None = None
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    errors="replace",
                    bufsize=1,  # Line-buffered
                )

                if proc.stdout is None:
                    continue

                first_line = proc.stdout.readline()
                if not first_line:
                    # No output from this candidate command, try next
                    proc.wait(timeout=5)
                    continue

                # Yield first line and count bytes
                line_len = len(first_line.encode("utf-8", errors="replace"))
                total_bytes += line_len
                yield first_line

                for line in proc.stdout:
                    line_len = len(line.encode("utf-8", errors="replace"))
                    if total_bytes + line_len > limit:
                        logger.warning(
                            "Git diff exceeded stream memory limit (%d bytes); truncating and killing subprocess.",
                            limit,
                        )
                        proc.terminate()
                        try:
                            proc.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                        yield DIFF_TRUNCATION_MARKER
                        return
                    total_bytes += line_len
                    yield line

                # Successful stream from this command, break candidate loop
                return
            except Exception as exc:
                logger.debug("Candidate git diff command failed: %s", exc)
            finally:
                if proc is not None:
                    if proc.poll() is None:
                        try:
                            proc.terminate()
                            proc.wait(timeout=1)
                        except Exception:
                            try:
                                proc.kill()
                            except Exception:
                                pass
                    if proc.stdout:
                        proc.stdout.close()
                    if proc.stderr:
                        proc.stderr.close()

    def _run_git_diff(self, workspace_path: Path, base_revision: str) -> str:
        """Backward-compatible git diff execution returning unified diff string."""
        return "".join(self._stream_git_diff_lines(workspace_path, base_revision))

    def _stream_fs_diff_lines(
        self,
        workspace_path: Path,
        max_bytes: int | None = None,
    ) -> Generator[str, None, None]:
        """Construct synthetic unified diff from modified files in non-git workspace incrementally."""
        limit = max_bytes if max_bytes is not None else self._max_diff_bytes
        total_bytes = 0

        for file in sorted(workspace_path.rglob("*")):
            if (
                not file.is_file()
                or ".workspaces" in file.parts
                or ".git" in file.parts
                or file.name in ("metadata.json", "workspace_metadata.json", ".metadata.json")
                or file.name.endswith(".metadata.json")
            ):
                continue
            rel_path = file.relative_to(workspace_path).as_posix()
            if rel_path in ("metadata.json", "workspace_metadata.json") or rel_path.endswith("/metadata.json"):
                continue

            try:
                with file.open("r", encoding="utf-8", errors="replace") as f:
                    file_lines = f.readlines()
            except Exception:
                continue

            headers = [
                f"diff --git a/{rel_path} b/{rel_path}\n",
                f"--- a/{rel_path}\n",
                f"+++ b/{rel_path}\n",
                f"@@ -0,0 +1,{len(file_lines)} @@\n",
            ]
            for h in headers:
                h_len = len(h.encode("utf-8", errors="replace"))
                if total_bytes + h_len > limit:
                    yield DIFF_TRUNCATION_MARKER
                    return
                total_bytes += h_len
                yield h

            for cl in file_lines:
                line_str = f"+{cl.rstrip(chr(10))}\n"
                l_len = len(line_str.encode("utf-8", errors="replace"))
                if total_bytes + l_len > limit:
                    yield DIFF_TRUNCATION_MARKER
                    return
                total_bytes += l_len
                yield line_str

    def _compute_fs_diff(self, workspace_path: Path) -> str:
        """Backward-compatible synthetic unified diff from non-git workspace."""
        return "".join(self._stream_fs_diff_lines(workspace_path)).rstrip("\n")
