"""Review Source Mapping Engine — Week 2 Feature 4 (Standalone AI Code Review).

Owner: Prit — Repository Engine Lead
Task: W2-Day5 — Review Source Mapping Integration
Milestone: Week 2 — Developer Intelligence Suite

Maps changed lines and diff hunks from code reviews, commits, and PRs to:
1. Exact source ranges and enclosing symbols (functions, methods, classes)
2. Structural AST context (node types, enclosing scopes, syntax checks, AST rules)
3. Preserved file identity, renames, and 1-indexed inclusive line numbers
4. Explicit mapping limitations (unsupported languages, module-level lines, deleted/binary files, syntax warnings)
"""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID, uuid4

from .ast_rules import ASTBugAnalyzer, ASTBugFinding
from .detector import LanguageDetector
from .extractor import SymbolExtractor
from .parser import Parser
from .source_location import ResolutionResult, SourceLocationResolver
from .symbols import FileInfo, ParseResult, SourceRange, Symbol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


@dataclass
class SymbolSummary:
    """Summary of a symbol identified during review source mapping."""

    name: str
    kind: str  # "function" | "class" | "method" | "constant" | "import" | "interface"
    start_line: int
    end_line: int
    signature: Optional[str] = None
    parent_name: Optional[str] = None
    qualified_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HunkASTContext:
    """Syntactic and structural AST context for a changed hunk."""

    node_types: List[str] = field(default_factory=list)
    scope_path: str = ""
    symbol_signature: Optional[str] = None
    symbol_snippet: Optional[str] = None
    surrounding_snippet: Optional[str] = None
    structural_defects: List[Dict[str, Any]] = field(default_factory=list)
    has_syntax_errors: bool = False
    syntax_error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MappingLimitation:
    """Explicit diagnostic limitation when an exact mapping cannot be established."""

    limitation_type: str
    # Types:
    # "UNSUPPORTED_LANGUAGE" | "MODULE_LEVEL_CODE" | "NO_ENCLOSING_SYMBOL"
    # "FILE_DELETED" | "BINARY_FILE" | "SYNTAX_ERROR" | "LINE_OUT_OF_BOUNDS"
    # "EMPTY_DIFF" | "MALFORMED_DIFF"
    file_path: str
    description: str
    line_range: Optional[Tuple[int, int]] = None
    remediation: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HunkMapping:
    """Mapping of a single diff hunk to source lines, symbols, and AST context."""

    hunk_index: int
    old_start_line: int
    old_line_count: int
    new_start_line: int
    new_line_count: int
    header: str = ""
    changed_line_numbers: List[int] = field(default_factory=list)
    enclosing_symbol: Optional[SymbolSummary] = None
    enclosing_class: Optional[str] = None
    qualified_symbol_name: Optional[str] = None
    symbol_range: Optional[SourceRange] = None
    change_scope: str = "module_level"
    # Scopes:
    # "inside_symbol" | "spans_symbols" | "signature_change" | "module_level" | "new_symbol" | "deleted_symbol"
    overlapping_symbols: List[SymbolSummary] = field(default_factory=list)
    ast_context: Optional[HunkASTContext] = None
    limitations: List[MappingLimitation] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hunk_index": self.hunk_index,
            "old_start_line": self.old_start_line,
            "old_line_count": self.old_line_count,
            "new_start_line": self.new_start_line,
            "new_line_count": self.new_line_count,
            "header": self.header,
            "changed_line_numbers": self.changed_line_numbers,
            "enclosing_symbol": self.enclosing_symbol.to_dict() if self.enclosing_symbol else None,
            "enclosing_class": self.enclosing_class,
            "qualified_symbol_name": self.qualified_symbol_name,
            "symbol_range": {
                "start_line": self.symbol_range.start_line,
                "end_line": self.symbol_range.end_line,
                "symbol_name": self.symbol_range.symbol_name,
            }
            if self.symbol_range
            else None,
            "change_scope": self.change_scope,
            "overlapping_symbols": [s.to_dict() for s in self.overlapping_symbols],
            "ast_context": self.ast_context.to_dict() if self.ast_context else None,
            "limitations": [l.to_dict() for l in self.limitations],
        }


@dataclass
class FileSourceMapping:
    """Complete source mapping for a single file affected by a review or diff."""

    file_path: str
    change_type: str = "modified"  # "modified" | "added" | "deleted" | "renamed"
    old_file_path: Optional[str] = None
    is_binary: bool = False
    is_supported: bool = True
    language: str = "unknown"
    total_lines: int = 0
    hunks: List[HunkMapping] = field(default_factory=list)
    modified_line_ranges: List[Tuple[int, int]] = field(default_factory=list)
    affected_symbols: List[SymbolSummary] = field(default_factory=list)
    has_syntax_errors: bool = False
    syntax_errors: List[str] = field(default_factory=list)
    limitations: List[MappingLimitation] = field(default_factory=list)
    base_revision: Optional[str] = None
    head_revision: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "change_type": self.change_type,
            "old_file_path": self.old_file_path,
            "is_binary": self.is_binary,
            "is_supported": self.is_supported,
            "language": self.language,
            "total_lines": self.total_lines,
            "hunks_count": len(self.hunks),
            "hunks": [h.to_dict() for h in self.hunks],
            "modified_line_ranges": self.modified_line_ranges,
            "affected_symbols": [s.to_dict() for s in self.affected_symbols],
            "has_syntax_errors": self.has_syntax_errors,
            "syntax_errors": self.syntax_errors,
            "limitations": [l.to_dict() for l in self.limitations],
            "base_revision": self.base_revision,
            "head_revision": self.head_revision,
        }


@dataclass
class ReviewSourceMapResult:
    """Root deliverable returned by ReviewSourceMapper."""

    success: bool
    files: List[FileSourceMapping] = field(default_factory=list)
    total_files: int = 0
    total_hunks: int = 0
    total_changed_lines: int = 0
    affected_symbols_count: int = 0
    base_revision: Optional[str] = None
    head_revision: Optional[str] = None
    commit_sha: Optional[str] = None
    pr_number: Optional[int] = None
    limitations: List[MappingLimitation] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "total_files": self.total_files,
            "total_hunks": self.total_hunks,
            "total_changed_lines": self.total_changed_lines,
            "affected_symbols_count": self.affected_symbols_count,
            "base_revision": self.base_revision,
            "head_revision": self.head_revision,
            "commit_sha": self.commit_sha,
            "pr_number": self.pr_number,
            "files": [f.to_dict() for f in self.files],
            "limitations": [l.to_dict() for l in self.limitations],
        }

    def to_source_references(self) -> List[Any]:
        """Convert mapped symbols and hunks to AnalysisSourceReference objects."""
        refs: List[Any] = []
        try:
            from app.schemas.analysis import AnalysisSourceReference
            has_schema = True
        except ImportError:
            has_schema = False

        revision = self.commit_sha or (
            f"{self.base_revision}..{self.head_revision}"
            if self.base_revision and self.head_revision
            else self.head_revision or self.base_revision
        )

        for file_map in self.files:
            for hunk in file_map.hunks:
                symbol_name = hunk.qualified_symbol_name or (
                    hunk.enclosing_symbol.name if hunk.enclosing_symbol else None
                )
                start_l = hunk.new_start_line if hunk.new_line_count > 0 else hunk.old_start_line
                end_l = start_l + max(1, hunk.new_line_count) - 1

                if has_schema:
                    refs.append(
                        AnalysisSourceReference(
                            file_path=file_map.file_path,
                            start_line=start_l,
                            end_line=end_l,
                            revision=revision,
                            symbol_name=symbol_name,
                        )
                    )
                else:
                    refs.append(
                        {
                            "file_path": file_map.file_path,
                            "start_line": start_l,
                            "end_line": end_l,
                            "revision": revision,
                            "symbol_name": symbol_name,
                        }
                    )
        return refs

    def to_modified_files(self) -> List[Any]:
        """Convert mapped files directly into Meet's ModifiedFile dataclasses."""
        mod_files: List[Any] = []
        try:
            from ai.context.review_context import ModifiedFile
            has_mod = True
        except ImportError:
            has_mod = False

        for f in self.files:
            hunk_headers = [h.header for h in f.hunks if h.header]
            if has_mod:
                mod_files.append(
                    ModifiedFile(
                        file_path=f.file_path,
                        change_type=f.change_type,
                        diff_hunks=hunk_headers,
                        modified_line_ranges=f.modified_line_ranges,
                    )
                )
            else:
                mod_files.append(
                    {
                        "file_path": f.file_path,
                        "change_type": f.change_type,
                        "diff_hunks": hunk_headers,
                        "modified_line_ranges": f.modified_line_ranges,
                    }
                )
        return mod_files


# ---------------------------------------------------------------------------
# Internal Diff Parsing Helper
# ---------------------------------------------------------------------------


@dataclass
class _RawDiffHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header: str
    lines: List[str]
    added_line_numbers: List[int]
    deleted_line_numbers: List[int]


@dataclass
class _RawDiffFile:
    old_path: Optional[str]
    new_path: Optional[str]
    change_type: str  # "modified" | "added" | "deleted" | "renamed"
    is_binary: bool
    hunks: List[_RawDiffHunk]


# ---------------------------------------------------------------------------
# ReviewSourceMapper Engine
# ---------------------------------------------------------------------------


class ReviewSourceMapper:
    """Integrates diff parsing, AST parsing, symbol extraction, and structural bug checking

    to map changed code lines to exact source ranges and symbols for standalone code reviews.
    """

    HUNK_HEADER_REGEX = re.compile(
        r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@(?:[ ]?(.*))?$"
    )
    DIFF_FILE_HEADER = re.compile(r"^diff --git a/(.*?) b/(.*?)$")

    def __init__(
        self,
        parser: Optional[Parser] = None,
        resolver: Optional[SourceLocationResolver] = None,
        extractor: Optional[SymbolExtractor] = None,
        analyzer: Optional[ASTBugAnalyzer] = None,
        detector: Optional[LanguageDetector] = None,
    ):
        self.parser = parser or Parser()
        self.resolver = resolver or SourceLocationResolver(self.parser)
        self.extractor = extractor or SymbolExtractor(self.parser)
        self.analyzer = analyzer or ASTBugAnalyzer(self.parser)
        self.detector = detector or LanguageDetector()

    # -----------------------------------------------------------------------
    # Diff Parsing
    # -----------------------------------------------------------------------

    def _detect_language(self, file_path: str) -> str:
        """Detect language using LanguageDetector with extension fallback."""
        file_info = FileInfo(path=file_path, size_bytes=0, language="", is_binary=False)
        try:
            detected = self.detector.detect(file_info)
            if detected and detected != "unknown":
                return detected
        except Exception:
            pass

        ext = Path(file_path).suffix.lower()
        mapping = {
            ".py": "Python",
            ".ts": "TypeScript",
            ".tsx": "TypeScript",
            ".js": "JavaScript",
            ".jsx": "JavaScript",
            ".java": "Java",
            ".go": "Go",
            ".rs": "Rust",
            ".c": "C",
            ".cpp": "C++",
            ".h": "C",
            ".hpp": "C++",
        }
        return mapping.get(ext, "unknown")

    def parse_unified_diff(self, diff_text: str) -> List[_RawDiffFile]:
        """Parse unified diff text into structured file and hunk representations."""
        if not diff_text or not diff_text.strip():
            return []

        raw_files: List[_RawDiffFile] = []
        lines = diff_text.splitlines()

        current_file: Optional[_RawDiffFile] = None
        current_hunk: Optional[_RawDiffHunk] = None
        current_new_line = 0
        current_old_line = 0

        i = 0
        while i < len(lines):
            line = lines[i]

            # Detect git diff file boundaries
            m_file = self.DIFF_FILE_HEADER.match(line)
            if m_file:
                if current_hunk and current_file:
                    current_file.hunks.append(current_hunk)
                    current_hunk = None
                if current_file:
                    raw_files.append(current_file)

                old_p = m_file.group(1).strip()
                new_p = m_file.group(2).strip()
                current_file = _RawDiffFile(
                    old_path=old_p if old_p != "/dev/null" else None,
                    new_path=new_p if new_p != "/dev/null" else None,
                    change_type="modified",
                    is_binary=False,
                    hunks=[],
                )
                i += 1
                continue

            # Check for file status indicators
            if line.startswith("new file mode") and current_file:
                current_file.change_type = "added"
                current_file.old_path = None
                i += 1
                continue
            elif line.startswith("deleted file mode") and current_file:
                current_file.change_type = "deleted"
                current_file.new_path = None
                i += 1
                continue
            elif (line.startswith("similarity index") or line.startswith("rename from")) and current_file:
                current_file.change_type = "renamed"
                i += 1
                continue
            elif line.startswith("Binary files ") and current_file:
                current_file.is_binary = True
                i += 1
                continue

            # Standard unified diff file path headers
            if line.startswith("--- "):
                p = line[4:].strip()
                if p.startswith("a/"):
                    p = p[2:]
                old_p = p if p != "/dev/null" else None

                if current_file is not None and current_file.hunks:
                    raw_files.append(current_file)
                    current_file = None

                if current_file is None:
                    current_file = _RawDiffFile(
                        old_path=old_p,
                        new_path=None,
                        change_type="modified",
                        is_binary=False,
                        hunks=[],
                    )
                else:
                    if old_p is not None:
                        current_file.old_path = old_p
                i += 1
                continue

            elif line.startswith("+++ "):
                p = line[4:].strip()
                if p.startswith("b/"):
                    p = p[2:]
                new_p = p if p != "/dev/null" else None

                if current_file is None:
                    current_file = _RawDiffFile(
                        old_path=None,
                        new_path=new_p,
                        change_type="modified",
                        is_binary=False,
                        hunks=[],
                    )
                else:
                    if new_p is not None:
                        current_file.new_path = new_p
                    elif current_file.change_type == "deleted":
                        current_file.new_path = None
                i += 1
                continue

            # Check for hunk header @@ -old,count +new,count @@
            m_hunk = self.HUNK_HEADER_REGEX.match(line)
            if m_hunk:
                if current_hunk and current_file:
                    current_file.hunks.append(current_hunk)
                    current_hunk = None

                # Fallback if no file header was provided
                if current_file is None:
                    current_file = _RawDiffFile(
                        old_path="target_file",
                        new_path="target_file",
                        change_type="modified",
                        is_binary=False,
                        hunks=[],
                    )

                old_start = int(m_hunk.group(1))
                old_count = int(m_hunk.group(2)) if m_hunk.group(2) is not None else 1
                new_start = int(m_hunk.group(3))
                new_count = int(m_hunk.group(4)) if m_hunk.group(4) is not None else 1

                current_hunk = _RawDiffHunk(
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                    header=line,
                    lines=[line],
                    added_line_numbers=[],
                    deleted_line_numbers=[],
                )
                current_old_line = old_start
                current_new_line = new_start
                i += 1
                continue

            # Hunk content lines
            if current_hunk is not None:
                current_hunk.lines.append(line)
                if line.startswith("+") and not line.startswith("+++"):
                    current_hunk.added_line_numbers.append(current_new_line)
                    current_new_line += 1
                elif line.startswith("-") and not line.startswith("---"):
                    current_hunk.deleted_line_numbers.append(current_old_line)
                    current_old_line += 1
                elif line.startswith(" ") or not line:
                    current_old_line += 1
                    current_new_line += 1

            i += 1

        if current_hunk and current_file:
            current_file.hunks.append(current_hunk)
        if current_file:
            raw_files.append(current_file)

        return raw_files

    # -----------------------------------------------------------------------
    # Core Mapping API
    # -----------------------------------------------------------------------

    def map_file_changes(
        self,
        file_path: str,
        content: str,
        modified_ranges: Optional[Sequence[Tuple[int, int]]] = None,
        diff_hunk_text: Optional[str] = None,
        old_content: Optional[str] = None,
        language: Optional[str] = None,
        change_type: str = "modified",
        old_file_path: Optional[str] = None,
        base_revision: Optional[str] = None,
        head_revision: Optional[str] = None,
    ) -> FileSourceMapping:
        """Map changed lines for a single file into exact source ranges, symbols, and AST context."""
        norm_path = file_path.replace("\\", "/").lstrip("/")

        # Language detection
        detected_lang = language or self._detect_language(norm_path)
        is_supported = self.parser.is_language_supported(detected_lang)

        lines = content.splitlines() if content else []
        total_lines = len(lines)

        file_mapping = FileSourceMapping(
            file_path=norm_path,
            change_type=change_type,
            old_file_path=old_file_path,
            is_supported=is_supported,
            language=detected_lang,
            total_lines=total_lines,
            base_revision=base_revision,
            head_revision=head_revision,
        )

        # Handle deleted files
        if change_type == "deleted":
            file_mapping.limitations.append(
                MappingLimitation(
                    limitation_type="FILE_DELETED",
                    file_path=norm_path,
                    description=f"File '{norm_path}' was deleted in target revision; AST symbols cannot be resolved.",
                    remediation="Inspect deletion in diff hunk without AST symbol resolution.",
                )
            )
            return file_mapping

        # Handle empty file content
        if not content and change_type != "deleted":
            file_mapping.limitations.append(
                MappingLimitation(
                    limitation_type="EMPTY_DIFF",
                    file_path=norm_path,
                    description=f"File '{norm_path}' content is empty.",
                )
            )
            return file_mapping

        # Determine modified line ranges and hunks
        hunks_to_process: List[HunkMapping] = []
        if diff_hunk_text:
            raw_diff_files = self.parse_unified_diff(diff_hunk_text)
            target_raw = [
                rf
                for rf in raw_diff_files
                if rf.new_path == norm_path or rf.old_path == norm_path or len(raw_diff_files) == 1
            ]
            if target_raw:
                for idx, rh in enumerate(target_raw[0].hunks, start=1):
                    changed_lines = (
                        rh.added_line_numbers
                        if rh.added_line_numbers
                        else [rh.new_start]
                        if rh.new_count > 0
                        else [rh.old_start]
                    )
                    hunks_to_process.append(
                        HunkMapping(
                            hunk_index=idx,
                            old_start_line=rh.old_start,
                            old_line_count=rh.old_count,
                            new_start_line=rh.new_start,
                            new_line_count=rh.new_count,
                            header=rh.header,
                            changed_line_numbers=changed_lines,
                        )
                    )

        if not hunks_to_process and modified_ranges:
            for idx, r in enumerate(modified_ranges, start=1):
                start_l, end_l = r
                clamped_start = max(1, start_l)
                clamped_end = max(clamped_start, min(end_l, total_lines or end_l))
                hunks_to_process.append(
                    HunkMapping(
                        hunk_index=idx,
                        old_start_line=clamped_start,
                        old_line_count=clamped_end - clamped_start + 1,
                        new_start_line=clamped_start,
                        new_line_count=clamped_end - clamped_start + 1,
                        header=f"@@ -{clamped_start},{clamped_end - clamped_start + 1} +{clamped_start},{clamped_end - clamped_start + 1} @@",
                        changed_line_numbers=list(range(clamped_start, clamped_end + 1)),
                    )
                )

        # Collect normalized modified line ranges
        collected_ranges: List[Tuple[int, int]] = []
        for h in hunks_to_process:
            if h.changed_line_numbers:
                collected_ranges.append((min(h.changed_line_numbers), max(h.changed_line_numbers)))
            elif h.new_line_count > 0:
                collected_ranges.append((h.new_start_line, h.new_start_line + h.new_line_count - 1))
        file_mapping.modified_line_ranges = self._merge_line_ranges(collected_ranges)

        # Unsupported language check
        if not is_supported:
            file_mapping.limitations.append(
                MappingLimitation(
                    limitation_type="UNSUPPORTED_LANGUAGE",
                    file_path=norm_path,
                    description=f"Language '{detected_lang}' is not supported for AST symbol resolution.",
                    remediation="Line ranges and diff locations are preserved without syntactic AST symbols.",
                )
            )
            # Still record hunks and line ranges
            file_mapping.hunks = hunks_to_process
            return file_mapping

        # Extract symbols and parse status
        file_info = FileInfo(
            path=norm_path,
            size_bytes=len(content.encode("utf-8")),
            language=detected_lang,
            is_binary=False,
        )
        parse_result: ParseResult = self.parser.parse_with_status(file_info, content)

        if parse_result.has_syntax_errors:
            file_mapping.has_syntax_errors = True
            msg = parse_result.error_message or "Syntax errors detected in file"
            file_mapping.syntax_errors.append(msg)
            file_mapping.limitations.append(
                MappingLimitation(
                    limitation_type="SYNTAX_ERROR",
                    file_path=norm_path,
                    description=f"Syntax error in '{norm_path}': {msg}. Partial symbols extracted where possible.",
                    remediation="Correct syntax errors for comprehensive AST symbol mapping.",
                )
            )

        symbols = self.extractor.extract(file_info, content)
        all_symbol_summaries = [self._to_symbol_summary(s, symbols) for s in symbols]

        # Filter to structural symbols for review scope mapping
        structural_symbols = [
            s
            for s in all_symbol_summaries
            if s.kind in ("function", "method", "class", "interface")
        ]

        # Map each hunk to symbols and AST context
        affected_symbol_names: set[str] = set()

        for hunk in hunks_to_process:
            hunk_start = hunk.new_start_line if hunk.new_line_count > 0 else hunk.old_start_line
            hunk_end = hunk_start + max(1, hunk.new_line_count) - 1

            # Line range boundary validation
            if total_lines > 0 and (hunk_start > total_lines or hunk_end > total_lines + 5):
                hunk.limitations.append(
                    MappingLimitation(
                        limitation_type="LINE_OUT_OF_BOUNDS",
                        file_path=norm_path,
                        line_range=(hunk_start, hunk_end),
                        description=f"Changed line range [{hunk_start}, {hunk_end}] exceeds file length ({total_lines} lines).",
                    )
                )

            # Find overlapping structural symbols
            overlapping: List[SymbolSummary] = []
            for s_sum in structural_symbols:
                if not (s_sum.end_line < hunk_start or s_sum.start_line > hunk_end):
                    overlapping.append(s_sum)

            hunk.overlapping_symbols = overlapping

            # Determine enclosing symbol and scope
            if not overlapping:
                hunk.change_scope = "module_level"
                hunk.limitations.append(
                    MappingLimitation(
                        limitation_type="MODULE_LEVEL_CODE",
                        file_path=norm_path,
                        line_range=(hunk_start, hunk_end),
                        description="Modified lines are at module level (e.g. imports, global constants, comments).",
                    )
                )
            else:
                tightest = self._find_tightest_enclosing(overlapping, hunk_start, hunk_end)
                target_sym = tightest or overlapping[0]
                hunk.enclosing_symbol = target_sym
                hunk.enclosing_class = target_sym.parent_name
                hunk.qualified_symbol_name = target_sym.qualified_name or target_sym.name
                hunk.symbol_range = SourceRange(
                    file_path=norm_path,
                    start_line=target_sym.start_line,
                    end_line=target_sym.end_line,
                    symbol_name=target_sym.name,
                    symbol_kind=target_sym.kind,
                )

                # Check if changed lines fall completely within target_sym
                if hunk_start >= target_sym.start_line and hunk_end <= target_sym.end_line:
                    if hunk_start == target_sym.start_line:
                        hunk.change_scope = "signature_change"
                    else:
                        hunk.change_scope = "inside_symbol"
                else:
                    funcs_and_methods = [
                        s for s in overlapping if s.kind in ("function", "method")
                    ]
                    if len(funcs_and_methods) > 1:
                        hunk.change_scope = "spans_symbols"
                    elif hunk_start <= target_sym.start_line:
                        hunk.change_scope = "signature_change"
                    else:
                        hunk.change_scope = "inside_symbol"

                affected_symbol_names.add(target_sym.name)
                for s in overlapping:
                    affected_symbol_names.add(s.name)

            # Supply AST context for hunk
            hunk.ast_context = self.supply_ast_context(
                content=content,
                language=detected_lang,
                start_line=hunk_start,
                end_line=hunk_end,
                file_path=norm_path,
            )

        file_mapping.hunks = hunks_to_process
        file_mapping.affected_symbols = [
            s for s in all_symbol_summaries if s.name in affected_symbol_names
        ]

        return file_mapping

    def map_unified_diff(
        self,
        diff_text: str,
        repo_files: Optional[Dict[str, str]] = None,
        repo_root: Optional[str] = None,
        base_revision: Optional[str] = None,
        head_revision: Optional[str] = None,
        commit_sha: Optional[str] = None,
        pr_number: Optional[int] = None,
    ) -> ReviewSourceMapResult:
        """Parse unified diff text and map all changed files against repository content."""
        if not diff_text or not diff_text.strip():
            return ReviewSourceMapResult(
                success=True,
                files=[],
                total_files=0,
                total_hunks=0,
                total_changed_lines=0,
                base_revision=base_revision,
                head_revision=head_revision,
                commit_sha=commit_sha,
                pr_number=pr_number,
                limitations=[
                    MappingLimitation(
                        limitation_type="EMPTY_DIFF",
                        file_path="diff",
                        description="Provided diff text is empty or contains no valid hunks.",
                    )
                ],
            )

        raw_diff_files = self.parse_unified_diff(diff_text)
        file_mappings: List[FileSourceMapping] = []
        global_limitations: List[MappingLimitation] = []

        total_changed_lines = 0
        total_hunks = 0
        affected_symbols_set: set[str] = set()

        for rdf in raw_diff_files:
            target_path = rdf.new_path or rdf.old_path or "unknown_file"

            # Check binary
            if rdf.is_binary:
                fm = FileSourceMapping(
                    file_path=target_path,
                    change_type=rdf.change_type,
                    old_file_path=rdf.old_path,
                    is_binary=True,
                    is_supported=False,
                    base_revision=base_revision,
                    head_revision=head_revision,
                )
                fm.limitations.append(
                    MappingLimitation(
                        limitation_type="BINARY_FILE",
                        file_path=target_path,
                        description=f"File '{target_path}' is binary; AST symbol extraction skipped.",
                    )
                )
                file_mappings.append(fm)
                continue

            # Read content from repo_files or disk
            file_content = ""
            if repo_files and target_path in repo_files:
                file_content = repo_files[target_path]
            elif repo_root:
                disk_file = Path(repo_root) / target_path
                if disk_file.exists() and disk_file.is_file():
                    try:
                        file_content = disk_file.read_text(encoding="utf-8", errors="replace")
                    except Exception as exc:
                        logger.warning(f"Error reading {disk_file}: {exc}")

            # Reconstruct single file diff text for mapping
            single_diff_lines: List[str] = []
            for h in rdf.hunks:
                single_diff_lines.extend(h.lines)
            single_diff_text = "\n".join(single_diff_lines)

            fm = self.map_file_changes(
                file_path=target_path,
                content=file_content,
                diff_hunk_text=single_diff_text,
                change_type=rdf.change_type,
                old_file_path=rdf.old_path,
                base_revision=base_revision,
                head_revision=head_revision,
            )

            file_mappings.append(fm)
            total_hunks += len(fm.hunks)
            for h in fm.hunks:
                total_changed_lines += len(h.changed_line_numbers)
            for s in fm.affected_symbols:
                affected_symbols_set.add(f"{fm.file_path}:{s.name}")

        return ReviewSourceMapResult(
            success=True,
            files=file_mappings,
            total_files=len(file_mappings),
            total_hunks=total_hunks,
            total_changed_lines=total_changed_lines,
            affected_symbols_count=len(affected_symbols_set),
            base_revision=base_revision,
            head_revision=head_revision,
            commit_sha=commit_sha,
            pr_number=pr_number,
            limitations=global_limitations,
        )

    def map_commit_changes(
        self,
        commit_files: Sequence[Any],
        repo_files: Optional[Dict[str, str]] = None,
        repo_root: Optional[str] = None,
        commit_sha: Optional[str] = None,
    ) -> ReviewSourceMapResult:
        """Map a list of commit or pull request file changes (compatible with Parth's CommitFileChange)."""
        combined_diff_parts: List[str] = []

        for cf in commit_files:
            # Handle CommitFileChange or dict
            fn = getattr(cf, "filename", None) or (cf.get("filename") if isinstance(cf, dict) else "")
            patch = getattr(cf, "patch", None) or (cf.get("patch") if isinstance(cf, dict) else "")
            status = getattr(cf, "status", None) or (cf.get("status") if isinstance(cf, dict) else "modified")

            if fn and patch:
                combined_diff_parts.append(f"diff --git a/{fn} b/{fn}")
                if status == "added":
                    combined_diff_parts.append("new file mode 100644")
                elif status == "removed" or status == "deleted":
                    combined_diff_parts.append("deleted file mode 100644")
                combined_diff_parts.append(f"--- a/{fn}")
                combined_diff_parts.append(f"+++ b/{fn}")
                combined_diff_parts.append(patch)

        full_diff = "\n".join(combined_diff_parts)
        return self.map_unified_diff(
            diff_text=full_diff,
            repo_files=repo_files,
            repo_root=repo_root,
            commit_sha=commit_sha,
        )

    def map_line_to_symbol(
        self,
        file_path: str,
        line_number: int,
        content: str,
        language: Optional[str] = None,
    ) -> Tuple[Optional[SymbolSummary], Optional[SourceRange], List[str]]:
        """Map a specific line number to its enclosing symbol and line range."""
        norm_path = file_path.replace("\\", "/").lstrip("/")
        detected_lang = language or self._detect_language(norm_path)

        if not self.parser.is_language_supported(detected_lang):
            return None, None, [f"UNSUPPORTED_LANGUAGE: '{detected_lang}' is not supported"]

        file_info = FileInfo(
            path=norm_path,
            size_bytes=len(content.encode("utf-8")),
            language=detected_lang,
            is_binary=False,
        )
        symbols = self.extractor.extract(file_info, content)
        enclosing = self.resolver.find_enclosing_symbol(symbols, line_number)

        if enclosing is None:
            return None, None, ["MODULE_LEVEL_CODE: Line is outside any function or class"]

        summary = self._to_symbol_summary(enclosing, symbols)
        s_range = SourceRange(
            file_path=norm_path,
            start_line=enclosing.start_line,
            end_line=enclosing.end_line,
            symbol_name=enclosing.name,
            symbol_kind=enclosing.kind,
        )
        return summary, s_range, []

    # -----------------------------------------------------------------------
    # AST Context Enrichment & Structural Rule Evaluation
    # -----------------------------------------------------------------------

    def supply_ast_context(
        self,
        content: str,
        language: str,
        start_line: int,
        end_line: int,
        file_path: str = "",
    ) -> HunkASTContext:
        """Extract syntactic node types, surrounding snippet, and structural defects for a line range."""
        ctx = HunkASTContext()
        lines = content.splitlines() if content else []
        total_lines = len(lines)

        # Snippet extraction with boundary clamping
        clamped_start = max(1, start_line)
        clamped_end = max(clamped_start, min(end_line, total_lines or end_line))
        ctx.surrounding_snippet = self.resolver.extract_snippet(content, clamped_start, clamped_end)

        # Check Python AST
        if language in ("Python", "python"):
            try:
                tree = ast.parse(content)
                node_types: List[str] = []
                scope_parts: List[str] = ["module"]

                for node in ast.walk(tree):
                    if hasattr(node, "lineno") and hasattr(node, "end_lineno"):
                        if not (node.end_lineno < clamped_start or node.lineno > clamped_end):
                            nt = type(node).__name__
                            if nt not in node_types:
                                node_types.append(nt)
                            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                                if node.name not in scope_parts:
                                    scope_parts.append(node.name)

                ctx.node_types = node_types
                ctx.scope_path = ".".join(scope_parts)
            except SyntaxError as exc:
                ctx.has_syntax_errors = True
                ctx.syntax_error_message = f"Syntax error at line {exc.lineno}: {exc.msg}"

        # Evaluate AST bug rules scoped to the changed range
        try:
            target_range = SourceRange(
                file_path=file_path or "target_file",
                start_line=clamped_start,
                end_line=clamped_end,
            )
            rule_result = self.analyzer.analyze_code(
                content=content,
                file_path=file_path or "target_file",
                language=language,
                target_range=target_range,
            )
            if rule_result.findings:
                ctx.structural_defects = [f.to_dict() for f in rule_result.findings]
            if rule_result.has_syntax_errors:
                ctx.has_syntax_errors = True
                ctx.syntax_error_message = rule_result.error_message
        except Exception as exc:
            logger.debug(f"AST rule evaluation skipped for hunk: {exc}")

        return ctx

    # -----------------------------------------------------------------------
    # Helper Methods
    # -----------------------------------------------------------------------

    def _to_symbol_summary(self, s: Symbol, all_symbols: Sequence[Symbol]) -> SymbolSummary:
        parent_name: Optional[str] = None
        if s.parent_id is not None:
            parents = [p for p in all_symbols if p.id == s.parent_id]
            if parents:
                parent_name = parents[0].name

        qualified = f"{parent_name}.{s.name}" if parent_name else s.name
        return SymbolSummary(
            name=s.name,
            kind=s.kind,
            start_line=s.start_line,
            end_line=s.end_line,
            signature=s.signature,
            parent_name=parent_name,
            qualified_name=qualified,
        )

    def _find_tightest_enclosing(
        self,
        symbols: Sequence[SymbolSummary],
        start_line: int,
        end_line: int,
    ) -> Optional[SymbolSummary]:
        """Find the tightest enclosing symbol (smallest line span enclosing start_line or overlapping range)."""
        if not symbols:
            return None

        # 1. Look for symbols enclosing start_line
        enclosing = [
            s
            for s in symbols
            if s.start_line <= start_line <= s.end_line
        ]
        # 2. If nothing encloses start_line, look for symbols enclosing end_line
        if not enclosing:
            enclosing = [
                s
                for s in symbols
                if s.start_line <= end_line <= s.end_line
            ]
        # 3. If still nothing, look for symbols contained entirely within [start_line, end_line]
        if not enclosing:
            enclosing = [
                s
                for s in symbols
                if start_line <= s.start_line and s.end_line <= end_line
            ]
        if not enclosing:
            enclosing = list(symbols)

        # Sort by span length (smallest span first), prefer methods/functions over classes
        enclosing.sort(
            key=lambda s: (
                s.end_line - s.start_line,
                0 if s.kind in ("method", "function") else 1,
            )
        )
        return enclosing[0]

    def _merge_line_ranges(self, ranges: Sequence[Tuple[int, int]]) -> List[Tuple[int, int]]:
        """Merge overlapping or adjacent 1-indexed inclusive line ranges."""
        if not ranges:
            return []
        sorted_ranges = sorted(ranges, key=lambda r: (r[0], r[1]))
        merged: List[Tuple[int, int]] = [sorted_ranges[0]]

        for current in sorted_ranges[1:]:
            prev_start, prev_end = merged[-1]
            curr_start, curr_end = current
            if curr_start <= prev_end + 1:
                merged[-1] = (prev_start, max(prev_end, curr_end))
            else:
                merged.append(current)
        return merged
