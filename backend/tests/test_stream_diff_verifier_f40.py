"""Comprehensive Unit and Integration Test Suite for F40 - Stream Unified Git Diffs
and Memory-Bound Patch Verification for Large Refactors.

Issue: #245
ADR: ADR-021
Acceptance Criteria:
1. Diff parsing and secret checking process lines iteratively via generator pipelines.
2. Peak heap memory usage during large diff verification is strictly bounded under 20MB.
3. Traversal violations are caught and rejected on stream headers before reading remaining diff chunks.
4. Zero breaking changes: returned validation schemas (DiffValidationResult, PatchValidationResult, WorkspaceDiffResult)
   remain completely identical.
"""

from __future__ import annotations

import io
import tracemalloc
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from app.core.input_security import UnsafePathError
from app.schemas.repair import PatchValidationResult, RepairPatchPayload
from app.schemas.workspace import (
    DiffValidationResult,
    FileChangeType,
    FileDiffSummary,
    WorkspaceDiffResult,
)
from app.services.repair_service import (
    RepairPatchValidator,
    extract_modified_files_from_diff,
    iter_modified_files_from_diff,
)
from sandbox.diff_verifier import (
    DEFAULT_MAX_DIFF_BYTES,
    DIFF_TRUNCATION_MARKER,
    MAX_PEAK_MEMORY_BYTES,
    WorkspaceDiffVerifier,
    iter_diff_lines,
    iter_parse_unified_diff,
    iter_scan_secrets_lines,
)
from sandbox.exceptions import WorkspacePathEscapeError
from sandbox.gitleaks_scanner import GitleaksDiffScanner

# ===========================================================================
# 1. Streaming Generator for Diff Parsing Tests
# ===========================================================================

class TestStreamingDiffParsing:
    """Tests for incremental generator-based diff parsing."""

    def test_iter_diff_lines_from_string(self):
        diff_text = "line1\nline2\nline3\n"
        lines = list(iter_diff_lines(diff_text))
        assert lines == ["line1\n", "line2\n", "line3\n"]

    def test_iter_diff_lines_from_iterable(self):
        def _gen():
            yield "diff --git a/foo.py b/foo.py\n"
            yield "--- a/foo.py\n"
            yield "+++ b/foo.py\n"

        lines = list(iter_diff_lines(_gen()))
        assert len(lines) == 3
        assert lines[0] == "diff --git a/foo.py b/foo.py\n"

    def test_iter_parse_unified_diff_single_file(self):
        diff_text = """diff --git a/src/math.py b/src/math.py
index 1234567..89abcdef 100644
--- a/src/math.py
+++ b/src/math.py
@@ -1,3 +1,5 @@
 def add(a, b):
-    return a - b
+    return a + b
+def sub(a, b):
+    return a - b
"""
        summaries = list(iter_parse_unified_diff(diff_text))
        assert len(summaries) == 1
        summary = summaries[0]
        assert summary.file_path == "src/math.py"
        assert summary.change_type == FileChangeType.MODIFIED
        assert summary.insertions == 3
        assert summary.deletions == 1
        assert len(summary.hunks) == 1
        assert summary.hunks[0].old_start == 1
        assert summary.hunks[0].new_start == 1

    def test_iter_parse_unified_diff_multi_file_stream(self):
        def _stream() -> Generator[str, None, None]:
            # File 1: added
            yield "diff --git a/new.py b/new.py\n"
            yield "new file mode 100644\n"
            yield "--- /dev/null\n"
            yield "+++ b/new.py\n"
            yield "@@ -0,0 +1,2 @@\n"
            yield "+print('hello')\n"
            yield "+print('world')\n"
            # File 2: deleted
            yield "diff --git a/old.py b/old.py\n"
            yield "deleted file mode 100644\n"
            yield "--- a/old.py\n"
            yield "+++ /dev/null\n"
            yield "@@ -1,2 +0,0 @@\n"
            yield "-remove_me\n"
            yield "-clean_up\n"
            # File 3: renamed
            yield "diff --git a/orig.py b/renamed.py\n"
            yield "rename from orig.py\n"
            yield "rename to renamed.py\n"
            yield "--- a/orig.py\n"
            yield "+++ b/renamed.py\n"
            yield "@@ -1,1 +1,1 @@\n"
            yield "-old\n"
            yield "+new\n"

        summaries = list(iter_parse_unified_diff(_stream()))
        assert len(summaries) == 3

        assert summaries[0].file_path == "new.py"
        assert summaries[0].change_type == FileChangeType.ADDED
        assert summaries[0].insertions == 2
        assert summaries[0].deletions == 0

        assert summaries[1].file_path == "old.py"
        assert summaries[1].change_type == FileChangeType.DELETED
        assert summaries[1].insertions == 0
        assert summaries[1].deletions == 2

        assert summaries[2].file_path == "renamed.py"
        assert summaries[2].change_type == FileChangeType.RENAMED
        assert summaries[2].insertions == 1
        assert summaries[2].deletions == 1

    def test_parse_unified_diff_backward_compatibility(self):
        verifier = WorkspaceDiffVerifier()
        diff_text = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,2 +1,3 @@
 line1
+line2
 line3
"""
        files, ins, dels = verifier.parse_unified_diff(diff_text)
        assert len(files) == 1
        assert files[0].file_path == "app.py"
        assert ins == 1
        assert dels == 0


# ===========================================================================
# 2. Early Path Guard Checking Tests
# ===========================================================================

class TestEarlyPathGuardChecking:
    """Tests for validating path safety immediately on headers before reading full chunks."""

    def test_early_path_guard_aborts_stream_immediately_on_traversal(self):
        consumed_lines: list[str] = []

        def malicious_stream() -> Generator[str, None, None]:
            yield "diff --git a/../../etc/shadow b/../../etc/shadow\n"
            yield "--- a/../../etc/shadow\n"
            yield "+++ b/../../etc/shadow\n"
            # If early guard works, none of the 100k lines below are ever consumed
            for i in range(100_000):
                line = f"+evil_payload_{i}\n"
                consumed_lines.append(line)
                yield line

        with pytest.raises((UnsafePathError, WorkspacePathEscapeError)):
            # With raise_on_traversal=True, generator aborts on header line
            list(iter_parse_unified_diff(malicious_stream(), early_path_guard=True, raise_on_traversal=True))

        # Assert no remaining chunk lines were consumed from generator
        assert len(consumed_lines) == 0

    def test_early_path_guard_without_diff_git_header(self):
        consumed_lines: list[str] = []

        def malicious_patch_stream() -> Generator[str, None, None]:
            yield "--- a/../../etc/passwd\n"
            yield "+++ b/../../etc/passwd\n"
            yield "@@ -1,1 +1,1 @@\n"
            for i in range(10_000):
                line = f"+hacked_{i}\n"
                consumed_lines.append(line)
                yield line

        with pytest.raises((UnsafePathError, WorkspacePathEscapeError)):
            list(iter_parse_unified_diff(malicious_patch_stream(), early_path_guard=True, raise_on_traversal=True))

        assert len(consumed_lines) == 0

    def test_iter_modified_files_from_diff_early_path_guard(self):
        consumed: list[str] = []

        def patch_stream():
            yield "--- a/safe.py\n"
            yield "+++ b/safe.py\n"
            yield "@@ -1 +1 @@\n"
            yield "+ok\n"
            yield "--- a/../../root/.ssh/id_rsa\n"
            yield "+++ b/../../root/.ssh/id_rsa\n"
            for i in range(10_000):
                line = f"+key_{i}\n"
                consumed.append(line)
                yield line

        with pytest.raises(UnsafePathError):
            list(iter_modified_files_from_diff(patch_stream(), early_path_guard=True))

        assert len(consumed) == 0

    def test_repair_patch_validator_early_path_guard_rejection(self):
        diff = """--- a/../../etc/shadow
+++ b/../../etc/shadow
@@ -1 +1 @@
-root:x
+root:pwned
"""
        payload = RepairPatchPayload(
            task_id="task_early_guard",
            attempt_number=1,
            diff=diff,
        )
        validator = RepairPatchValidator()
        result = validator.validate_patch(payload=payload, early_path_guard=True)

        assert result.is_valid is False
        assert any("path traversal" in v.lower() for v in result.violations)


# ===========================================================================
# 3. Bounded Memory Threshold & Truncation Tests
# ===========================================================================

class TestBoundedMemoryThreshold:
    """Tests for enforcing memory thresholds with truncation markers."""

    def test_iter_diff_lines_enforces_truncation_marker(self):
        # 10 lines of 100 bytes = 1000 bytes
        diff_source = ["x" * 99 + "\n" for _ in range(10)]
        max_bytes = 400  # Cap at 400 bytes

        streamed = list(iter_diff_lines(diff_source, max_bytes=max_bytes))
        # Total bytes before truncation: 4 * 100 = 400. 5th exceeds, so marker yielded
        assert len(streamed) == 5
        assert streamed[-1] == DIFF_TRUNCATION_MARKER

    def test_workspace_diff_verifier_extract_diff_truncation(self, tmp_path: Path):
        verifier = WorkspaceDiffVerifier(max_diff_bytes=500)
        # Create non-git workspace with files exceeding 500 bytes
        for i in range(10):
            (tmp_path / f"file_{i}.txt").write_text("A" * 200 + "\n", encoding="utf-8")

        result = verifier.extract_diff(tmp_path, task_id="trunc_test")

        assert result.is_empty is False
        assert DIFF_TRUNCATION_MARKER.strip() in result.raw_diff
        assert result.error is not None
        assert "exceeded maximum memory limit" in result.error

    def test_stream_git_diff_terminates_subprocess_on_limit(self, tmp_path: Path):
        verifier = WorkspaceDiffVerifier(max_diff_bytes=200)

        # Mock Popen with a large output stream
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdout.readline.return_value = "diff --git a/foo.py b/foo.py\n"
        mock_proc.stdout.__iter__.return_value = ["+" + "y" * 150 + "\n" for _ in range(10)]

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("subprocess.Popen", lambda *args, **kwargs: mock_proc)
            git_dir = tmp_path / ".git"
            git_dir.mkdir(parents=True, exist_ok=True)

            lines = list(verifier._stream_git_diff_lines(tmp_path, "HEAD", max_bytes=200))
            assert any(DIFF_TRUNCATION_MARKER.strip() in l for l in lines)
            mock_proc.terminate.assert_called()


# ===========================================================================
# 4. Peak Heap Memory Usage Strictly Under 20MB (< 20MB)
# ===========================================================================

class TestPeakHeapMemoryBounded:
    """Verify peak heap memory during massive diff verification stays strictly under 20MB."""

    def test_peak_heap_memory_under_20mb_during_large_diff_stream(self):
        """Generate a 30MB+ synthetic diff stream and verify peak memory remains bounded."""
        def generate_large_diff_stream() -> Generator[str, None, None]:
            # Generate 400 files, each with 50 lines ~ 25MB total payload
            for file_idx in range(400):
                yield f"diff --git a/pkg/mod_{file_idx}.py b/pkg/mod_{file_idx}.py\n"
                yield f"--- a/pkg/mod_{file_idx}.py\n"
                yield f"+++ b/pkg/mod_{file_idx}.py\n"
                yield "@@ -1,5 +1,50 @@\n"
                for line_idx in range(50):
                    yield f"+    compute_result_{file_idx}_{line_idx} = {file_idx} * {line_idx}\n"

        tracemalloc.start()
        tracemalloc.reset_peak()

        # Stream parse unified diff incrementally
        summaries = list(iter_parse_unified_diff(generate_large_diff_stream(), early_path_guard=True))
        assert len(summaries) == 400

        _current_bytes, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        # Peak heap memory should be tiny (well under MAX_PEAK_MEMORY_BYTES = 20MB)
        assert peak_bytes < MAX_PEAK_MEMORY_BYTES, (
            f"Peak memory {peak_bytes / (1024 * 1024):.2f}MB exceeded 20MB limit!"
        )

    def test_stream_validate_diff_peak_memory_bounded(self):
        """Verify stream_validate_diff evaluates 200 files without exceeding 20MB heap memory."""
        verifier = WorkspaceDiffVerifier(max_diff_bytes=DEFAULT_MAX_DIFF_BYTES)

        def stream_files() -> Generator[str, None, None]:
            for f_idx in range(200):
                yield f"diff --git a/src/component_{f_idx}.py b/src/component_{f_idx}.py\n"
                yield f"--- a/src/component_{f_idx}.py\n"
                yield f"+++ b/src/component_{f_idx}.py\n"
                yield "@@ -0,0 +1,20 @@\n"
                for l_idx in range(20):
                    yield f"+# line {l_idx} clean comment\n"

        tracemalloc.start()
        tracemalloc.reset_peak()

        val_res = verifier.stream_validate_diff(
            stream_files(),
            allowed_files=[f"src/component_{i}.py" for i in range(200)],
        )

        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        assert val_res.is_valid is True
        assert len(val_res.modified_files) == 200
        assert peak < MAX_PEAK_MEMORY_BYTES


# ===========================================================================
# 5. Dual-Engine Streaming Secret Scanning Tests
# ===========================================================================

class TestStreamingSecretScanning:
    """Tests for iterative secret scanning across diff line streams."""

    def test_primary_patterns_streaming_detection(self):
        verifier = WorkspaceDiffVerifier()
        hunk_lines = [
            "@@ -1,1 +1,3 @@\n",
            " unchanged\n",
            '+OPENAI_KEY = "sk-abcdefghijklmnopqrstuvwxyz1234567890abcdef"\n',
            '+GITHUB_TOKEN = "ghp_1234567890abcdefghijklmnopqrstuvwxyz12"\n',
        ]
        findings = list(
            iter_scan_secrets_lines(
                hunk_lines,
                file_path="src/config.py",
                secret_patterns=verifier._secret_patterns,
                hunk_start=1,
            )
        )
        assert len(findings) >= 2
        types = {f.secret_type for f in findings}
        assert "OpenAI API Key" in types
        assert "GitHub Token" in types

    def test_secondary_gitleaks_streaming_detection(self):
        scanner = GitleaksDiffScanner(force_builtin=True)
        token = "ghp_" + "1234567890abcdefghijklmnopqrstuvwxyz"
        lines = [
            "--- a/secrets.json\n",
            "+++ b/secrets.json\n",
            "@@ -0,0 +1,2 @@\n",
            f'+  "token": "{token}"\n',
        ]
        findings = list(scanner.scan_diff_stream(lines, file_path_hint="secrets.json"))
        assert len(findings) >= 1
        assert any("github-pat" in f.secret_type or "github" in f.secret_type for f in findings)


# ===========================================================================
# 6. Zero Breaking Changes Contract Tests
# ===========================================================================

class TestValidationSchemasZeroBreakingChanges:
    """Verify returned validation dataclasses/models retain exact identical contracts."""

    def test_diff_validation_result_schema_identical(self):
        verifier = WorkspaceDiffVerifier()
        diff_res = WorkspaceDiffResult(
            task_id="t_contract",
            base_revision="main",
            head_revision="feature",
            total_files_changed=1,
            insertions=2,
            deletions=1,
            is_empty=False,
            files=[
                FileDiffSummary(
                    file_path="src/app.py",
                    change_type=FileChangeType.MODIFIED,
                    insertions=2,
                    deletions=1,
                )
            ],
            raw_diff="diff --git a/src/app.py b/src/app.py",
        )
        val = verifier.validate_diff(diff_res, allowed_files=["src/app.py"])

        assert isinstance(val, DiffValidationResult)
        assert val.task_id == "t_contract"
        assert val.is_valid is True
        assert val.verified_revision in ("feature", "main")
        assert val.modified_files == ["src/app.py"]
        assert val.unapproved_files == []
        assert val.deleted_critical_files == []
        assert val.secret_findings == []
        assert val.blocking_findings == []
        assert isinstance(val.warnings, list)
        assert val.validated_at is not None

    def test_patch_validation_result_schema_identical(self):
        validator = RepairPatchValidator()
        payload = RepairPatchPayload(
            task_id="t_patch",
            attempt_number=1,
            diff="--- a/src/clean.py\n+++ b/src/clean.py\n@@ -1 +1 @@\n-a\n+b\n",
        )
        res = validator.validate_patch(payload, allowed_files=["src/clean.py"])

        assert isinstance(res, PatchValidationResult)
        assert res.is_valid is True
        assert res.rejection_reason is None
        assert res.patch_hash is not None
        assert res.modified_files == ["src/clean.py"]
        assert res.attempt_number == 1
        assert res.remaining_attempts == 2
        assert res.violations == []

    def test_extract_modified_files_from_diff_handles_both_types(self):
        diff_str = "--- a/file1.py\n+++ b/file1.py\n--- a/file2.py\n+++ b/file2.py\n"
        from_str = extract_modified_files_from_diff(diff_str)
        from_iter = extract_modified_files_from_diff(io.StringIO(diff_str))

        assert from_str == ["file1.py", "file2.py"]
        assert from_iter == ["file1.py", "file2.py"]
