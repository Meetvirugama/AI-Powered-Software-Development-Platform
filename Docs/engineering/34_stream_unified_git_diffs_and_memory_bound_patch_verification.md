# Engineering Specification: Stream Unified Git Diffs and Memory-Bound Patch Verification for Large Refactors

| Metadata | Details |
|---|---|
| **Feature ID** | F40 |
| **Component** | Sandbox / Workspace Diff Verification & Repair Validation |
| **Primary Files** | `backend/sandbox/diff_verifier.py`, `backend/sandbox/gitleaks_scanner.py`, `backend/app/services/repair_service.py`, `backend/sandbox/__init__.py` |
| **Status** | Implemented & Verified |
| **Architecture Decision** | [ADR-021](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/Docs/engineering/13_architecture_decisions.md#adr-021-streaming-unified-git-diffs-and-memory-bound-patch-verification-for-large-refactors) |

---

## 1. Executive Summary & Problem Context

In `backend/sandbox/diff_verifier.py` and `backend/app/services/repair_service.py`, git diff extraction and patch verification historically buffered entire raw command outputs and unified diff strings directly into Python heap memory (`.read()`, `p.stdout.decode()`, `raw_diff.split("diff --git ")`).

For tasks that touch numerous files or involve large repository diffs (e.g., major multi-file refactoring, bulk asset updates, or generated code verification), buffering multi-megabyte diff payloads created:
1. **$O(\text{diff\_size})$ Unconstrained Heap Allocations:** Storing massive diff strings and duplicating them during UTF-8 decoding and chunk splitting consumed excessive contiguous memory.
2. **Docker OOM Kills & GC Pauses:** In memory-constrained containers (512MB–1GB RAM limits), simultaneous tasks processing large diffs risked Out-Of-Memory termination and garbage collection stalls.
3. **Delayed Security Rejections:** Path traversal checks (`validate_repo_relative_path`) and secret scans waited until the complete multi-megabyte diff was buffered before checking file safety, wasting memory and CPU on malicious or malformed payloads.

**F40** eliminates these bottlenecks by:
- Streaming unified git diff extraction and hunk parsing via iterator/generator pipelines.
- Enforcing an operational memory threshold (`10MB`) with standard truncation markers to guarantee peak heap memory remains strictly `< 20MB`.
- Validating repository-relative path safety immediately on file header lines (`diff --git`, `---`, `+++`), rejecting traversal attempts before consuming remaining diff chunks.
- Scanning added lines for credentials incrementally via dual-engine generators (regex + canonical Gitleaks rules).
- Retaining 100% backward compatibility across all validation schemas (`WorkspaceDiffResult`, `DiffValidationResult`, `PatchValidationResult`).

---

## 2. Technical Architecture

```mermaid
flowchart TD
    subgraph InputSource [Diff Stream Source]
        G1[Git Subprocess Popen stdout]
        F1[Filesystem Synthetic Diff Stream]
        S1[Patch Diff String / Stream]
    end

    subgraph StreamingPipeline [O(1) Streaming & Bounded Buffer]
        G1 & F1 & S1 --> L1[iter_diff_lines: Byte-accounting generator]
        L1 --> CHK{Bytes > 10MB Threshold?}
        CHK -- Yes --> TR[Yield DIFF_TRUNCATION_MARKER & Terminate Subprocess]
        CHK -- No --> H1[iter_parse_unified_diff: State Machine]
    end

    subgraph EarlySecurityGuard [Early Header Path Guard]
        H1 --> HD{Header: diff --git or +++ b/path}
        HD -- Yes --> PV{validate_repo_relative_path}
        PV -- Path Traversal Detected --> ERR[Abort Stream Immediately with UnsafePathError]
        PV -- Safe Path --> ST[Parse Hunks Incrementally]
        HD -- No --> ST
    end

    subgraph IncrementalVerification [Generator Pipeline Verification]
        ST --> FS[Yield FileDiffSummary]
        FS --> SS[iter_scan_secrets_lines & scan_diff_stream]
        SS --> VR[DiffValidationResult / PatchValidationResult]
    end
```

---

## 3. Core Implementation Details

### 3.1 Streaming Generator for Diff Parsing (`diff_verifier.py`)

Diff lines are consumed iteratively without creating monolithic in-memory lists:

```python
def iter_diff_lines(
    diff_source: str | Iterable[str] | io.TextIOBase,
    max_bytes: int = DEFAULT_MAX_DIFF_BYTES,
    truncation_marker: str = DIFF_TRUNCATION_MARKER,
) -> Generator[str, None, None]:
    """Yield lines incrementally from a string or stream up to max_bytes with O(1) memory."""
```

The unified diff parser processes file sections and hunks incrementally:

```python
def iter_parse_unified_diff(
    diff_source: str | Iterable[str],
    workspace_root: Path | None = None,
    early_path_guard: bool = True,
    raise_on_traversal: bool = False,
    max_bytes: int = DEFAULT_MAX_DIFF_BYTES,
) -> Generator[FileDiffSummary, None, None]:
    """Incrementally parse diff lines into FileDiffSummary objects with early path checks."""
```

### 3.2 Bounded Output Memory Threshold & Process Containment

- **`DEFAULT_MAX_DIFF_BYTES`**: Configured to 10MB (`10 * 1024 * 1024`).
- **`MAX_PEAK_MEMORY_BYTES`**: Hard operational ceiling of 20MB (`20 * 1024 * 1024`).
- **`DIFF_TRUNCATION_MARKER`**: Appended when diff output reaches memory bounds:
  `"[DIFF TRUNCATED: Diff stream exceeded maximum memory limit of 10485760 bytes]"`.
- **Subprocess Termination:** When streaming from `git diff`, `_stream_git_diff_lines` executes `proc.terminate()` (and `proc.kill()` if uncooperative) upon reaching `max_bytes`, preventing runaway processes.

### 3.3 Early Path Guard Checking on File Headers

As soon as a header line is encountered:
1. `diff --git a/<old> b/<new>`
2. `+++ b/<target>`
3. `--- a/<target>`

The target repository path is parsed and validated immediately:
```python
validate_repo_relative_path(cand_path)
if workspace_root:
    WorkspacePathGuard.resolve_within_workspace(workspace_root, cand_path)
```
When `raise_on_traversal=True`, any directory traversal (e.g., `../../etc/shadow`) raises `UnsafePathError` or `WorkspacePathEscapeError` on the header line itself. The stream generator halts immediately without reading the subsequent lines or hunks.

### 3.4 Dual-Engine Secret Scanning via Generator Pipelines

- **Primary Regex Engine (`iter_scan_secrets_lines`):** Scans added diff lines (`+` lines) line-by-line across hunks for OpenAI keys, GitHub tokens, AWS keys, and private key blocks.
- **Secondary Gitleaks Engine (`scan_diff_stream`, `iter_scan_rules`):** Evaluates canonical Gitleaks rules iteratively across streamed lines without creating intermediate text files or full-diff copies.

### 3.5 Memory-Bound Candidate Patch Verification (`repair_service.py`)

- `iter_modified_files_from_diff(diff_source, early_path_guard=...)`: Streams unified diff lines to extract modified file paths without `diff_text.splitlines()`.
- `extract_modified_files_from_diff(diff_source, early_path_guard=...)`: Backward-compatible entrypoint returning sorted lists from the generator.
- `RepairPatchValidator.validate_patch(payload, ..., early_path_guard=...)`: Consumes the generator pipeline, rejecting traversal attempts immediately on headers.

---

## 4. Verification & Testing Evidence

A comprehensive test suite was implemented in `backend/tests/test_stream_diff_verifier_f40.py` covering:

| Test Class | Focus | Assertions / Verification |
|---|---|---|
| `TestStreamingDiffParsing` | Generator line iteration & hunk parsing | Iterative line consumption, single/multi-file diffs, ADDED/DELETED/RENAMED change types, backward compatibility. |
| `TestEarlyPathGuardChecking` | Header path interception | Aborts generator immediately on header line without reading remaining chunk lines; rejects traversal in `repair_service`. |
| `TestBoundedMemoryThreshold` | Memory bounds & truncation | Yields truncation marker when byte limit is reached; terminates git diff subprocess; sets error message on `WorkspaceDiffResult`. |
| `TestPeakHeapMemoryBounded` | Peak heap memory (< 20MB) | Uses `tracemalloc` across 400-file, 30MB+ diff streams. Proves peak heap memory remains strictly `< 20MB`. |
| `TestStreamingSecretScanning` | Dual-engine secret scanner | Detects credentials line-by-line across primary regex and secondary Gitleaks rules. |
| `TestValidationSchemasZeroBreakingChanges` | Contract immutability | Verifies `WorkspaceDiffResult`, `DiffValidationResult`, and `PatchValidationResult` retain exact identical schemas and fields. |

### Test Execution Summary
```bash
PYTHONPATH=backend .venv/bin/pytest -o addopts="" backend/tests/test_stream_diff_verifier_f40.py backend/tests/test_prit_w3_d5_verification_and_draft_pr.py backend/tests/test_independent_verification_f25.py backend/tests/test_bounded_repair_loop_f24.py backend/tests/test_dev_w3_day4_repair.py
# 101 passed, 1 warning in 5.99s
```

---

## 5. Security & Operational Guarantees

1. **Denial of Service (DoS) Immunity:** Bounded stream consumption prevents memory exhaustion attacks using artificially massive diff outputs.
2. **Immediate Traversal Interception:** File path traversal attempts are rejected on header lines before any chunk data enters the processing pipeline.
3. **Process Leak Prevention:** Clean `try...finally` resource management ensures `proc.terminate()` and `proc.kill()` close file descriptors and processes on limit trips or cancellations.
4. **Zero Breaking Changes:** Full compatibility is preserved for existing callers, workflows, and test suites.
