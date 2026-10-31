"""Target selector and symbol resolution engine.

Owner: Prit — Repository Engine Lead (W2-Day2)
Fulfills Week 2 Day 2: Symbol Resolution & Target Selection integration.
Connects AST/source-location utilities to code intelligence targets,
resolves functions and classes to exact ranges, handles ambiguous symbols,
and ensures consistent 1-indexed inclusive line range interpretation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional, Sequence
from uuid import UUID

from .detector import LanguageDetector
from .extractor import SymbolExtractor
from .parser import Parser
from .source_location import SourceLocationResolver
from .symbols import FileInfo, SourceRange, Symbol

logger = logging.getLogger(__name__)


@dataclass
class TargetSelectionResult:
    """The fully verified result of target selection and symbol resolution."""

    success: bool
    target_type: str  # "file" | "symbol" | "range"
    file_path: str
    start_line: int  # 1-indexed inclusive
    end_line: int  # 1-indexed inclusive
    content: str  # Verified source snippet
    symbol_name: Optional[str] = None
    symbol_kind: Optional[str] = None  # "class" | "function" | "method" | "interface" | None
    enclosing_symbol: Optional[Symbol] = None
    child_symbols: List[Symbol] = field(default_factory=list)
    is_ambiguous: bool = False
    candidates: List[Symbol] = field(default_factory=list)
    ambiguity_note: Optional[str] = None
    parse_status: str = "OK"  # "OK" | "SYNTAX_WARNING" | "PARSE_ERROR" | "FALLBACK"
    has_syntax_errors: bool = False
    is_supported: bool = True
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    total_file_lines: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert result to a dictionary representation."""
        return {
            "success": self.success,
            "target_type": self.target_type,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "content": self.content,
            "symbol_name": self.symbol_name,
            "symbol_kind": self.symbol_kind,
            "enclosing_symbol": {
                "name": self.enclosing_symbol.name,
                "kind": self.enclosing_symbol.kind,
                "start_line": self.enclosing_symbol.start_line,
                "end_line": self.enclosing_symbol.end_line,
            }
            if self.enclosing_symbol
            else None,
            "child_symbols": [
                {
                    "name": s.name,
                    "kind": s.kind,
                    "start_line": s.start_line,
                    "end_line": s.end_line,
                }
                for s in self.child_symbols
            ],
            "is_ambiguous": self.is_ambiguous,
            "candidates": [
                {
                    "name": s.name,
                    "kind": s.kind,
                    "start_line": s.start_line,
                    "end_line": s.end_line,
                    "signature": s.signature,
                }
                for s in self.candidates
            ],
            "ambiguity_note": self.ambiguity_note,
            "parse_status": self.parse_status,
            "has_syntax_errors": self.has_syntax_errors,
            "is_supported": self.is_supported,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "total_file_lines": self.total_file_lines,
        }

    def to_target_snippet(self, language: str = "text") -> Any:
        """Convert into a TargetSnippet compatible with Meet's IntelligenceContext."""
        try:
            from ai.context.builder import TargetSnippet  # type: ignore

            return TargetSnippet(
                file_path=self.file_path,
                content=self.content,
                start_line=self.start_line,
                end_line=self.end_line,
                symbol_name=self.symbol_name,
                language=language,
            )
        except ImportError:
            # Fallback dataclass if ai.context.builder not in path
            return {
                "file_path": self.file_path,
                "content": self.content,
                "start_line": self.start_line,
                "end_line": self.end_line,
                "symbol_name": self.symbol_name,
                "language": language,
            }


class TargetSelector:
    """Connects user/API target selections to AST parsing and source location utilities.

    Resolves target files, symbols, and line ranges into consistent, verified snippets.
    """

    def __init__(
        self,
        parser: Optional[Parser] = None,
        extractor: Optional[SymbolExtractor] = None,
        resolver: Optional[SourceLocationResolver] = None,
        detector: Optional[LanguageDetector] = None,
    ):
        self.parser = parser or Parser()
        self.extractor = extractor or SymbolExtractor(parser=self.parser)
        self.resolver = resolver or SourceLocationResolver(
            extractor=self.extractor, parser=self.parser
        )
        self.detector = detector or LanguageDetector()

    def select_target(
        self,
        file_path: str,
        content: str,
        target_type: str = "file",
        symbol_name: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        cursor_line: Optional[int] = None,
        language: Optional[str] = None,
        revision: Optional[str] = None,
    ) -> TargetSelectionResult:
        """Resolve an incoming target selection into a verified TargetSelectionResult.

        Handles:
        1. Target type 'file': Selects the entire file content.
        2. Target type 'symbol': Resolves class, function, or method by name with disambiguation.
        3. Target type 'range': Resolves 1-indexed inclusive line range and detects enclosing symbol.
        """
        norm_path = file_path.replace("\\", "/").strip()
        if not norm_path:
            return TargetSelectionResult(
                success=False,
                target_type=target_type,
                file_path=file_path,
                start_line=1,
                end_line=1,
                content="",
                error_code="INVALID_PATH",
                error_message="Target file path cannot be empty.",
            )

        # Normalize line endings to ensure consistent indexing across platforms
        normalized_content = content.replace("\r\n", "\n").replace("\r", "\n")
        lines = normalized_content.splitlines()
        total_lines = len(lines)

        if total_lines == 0 and content.strip() == "":
            return TargetSelectionResult(
                success=False,
                target_type=target_type,
                file_path=norm_path,
                start_line=1,
                end_line=1,
                content="",
                error_code="EMPTY_FILE",
                error_message=f"Target file '{norm_path}' is empty.",
                total_file_lines=0,
            )

        # Detect language
        detected_lang = language or self.detector.detect(
            FileInfo(norm_path, len(normalized_content), "unknown", False)
        )
        is_supported = self.parser.is_language_supported(detected_lang)

        # Perform AST parse
        parse_status = "OK"
        has_syntax_errors = False
        symbols: List[Symbol] = []

        if is_supported:
            file_info = FileInfo(norm_path, len(normalized_content), detected_lang, False)
            parse_res = self.parser.parse_with_status(file_info, normalized_content)
            has_syntax_errors = parse_res.has_syntax_errors
            if not parse_res.success:
                parse_status = "PARSE_ERROR"
            elif has_syntax_errors:
                parse_status = "SYNTAX_WARNING"

            # Extract symbols (gracefully handles syntax errors via error resilience)
            symbols = self.extractor.extract(file_info, normalized_content)
        else:
            parse_status = "UNSUPPORTED_LANGUAGE"

        # Auto-detect target_type if not explicitly set
        effective_type = target_type
        if effective_type == "file" and symbol_name:
            effective_type = "symbol"
        elif effective_type == "file" and start_line is not None:
            effective_type = "range"

        # -------------------------------------------------------------------
        # Mode 1: Symbol Selection
        # -------------------------------------------------------------------
        if effective_type == "symbol":
            if not symbol_name:
                return TargetSelectionResult(
                    success=False,
                    target_type="symbol",
                    file_path=norm_path,
                    start_line=1,
                    end_line=total_lines,
                    content="",
                    error_code="MISSING_SYMBOL_NAME",
                    error_message="Target type 'symbol' requires a non-empty symbol_name.",
                    total_file_lines=total_lines,
                )

            if not is_supported:
                return TargetSelectionResult(
                    success=False,
                    target_type="symbol",
                    file_path=norm_path,
                    start_line=1,
                    end_line=total_lines,
                    content="",
                    is_supported=False,
                    parse_status=parse_status,
                    error_code="UNSUPPORTED_LANGUAGE",
                    error_message=f"Language '{detected_lang}' does not support AST symbol selection.",
                    total_file_lines=total_lines,
                )

            return self._resolve_symbol(
                norm_path=norm_path,
                content=normalized_content,
                symbols=symbols,
                symbol_name=symbol_name,
                cursor_line=cursor_line or start_line,
                has_syntax_errors=has_syntax_errors,
                parse_status=parse_status,
                total_lines=total_lines,
            )

        # -------------------------------------------------------------------
        # Mode 2: Range Selection
        # -------------------------------------------------------------------
        if effective_type == "range":
            return self._resolve_range(
                norm_path=norm_path,
                content=normalized_content,
                symbols=symbols,
                start_line=start_line or 1,
                end_line=end_line or start_line or total_lines,
                is_supported=is_supported,
                has_syntax_errors=has_syntax_errors,
                parse_status=parse_status,
                total_lines=total_lines,
            )

        # -------------------------------------------------------------------
        # Mode 3: Whole File Selection
        # -------------------------------------------------------------------
        top_symbol = symbols[0] if symbols else None
        return TargetSelectionResult(
            success=True,
            target_type="file",
            file_path=norm_path,
            start_line=1,
            end_line=total_lines,
            content=normalized_content,
            symbol_name=top_symbol.name if top_symbol else None,
            symbol_kind=top_symbol.kind if top_symbol else None,
            child_symbols=symbols,
            is_supported=is_supported,
            has_syntax_errors=has_syntax_errors,
            parse_status=parse_status,
            total_file_lines=total_lines,
        )

    def _resolve_symbol(
        self,
        norm_path: str,
        content: str,
        symbols: List[Symbol],
        symbol_name: str,
        cursor_line: Optional[int],
        has_syntax_errors: bool,
        parse_status: str,
        total_lines: int,
    ) -> TargetSelectionResult:
        """Resolve a symbol name with qualified name matching and disambiguation."""
        # 1. Qualified name lookup e.g. "AccountManager.update_role"
        if "." in symbol_name:
            parts = symbol_name.split(".")
            parent_name = parts[0]
            member_name = parts[-1]

            parent_matches = [
                s for s in symbols if s.name == parent_name and s.kind in ("class", "interface")
            ]
            for parent in parent_matches:
                child_matches = [
                    s for s in symbols if s.name == member_name and s.parent_id == parent.id
                ]
                if child_matches:
                    target_sym = child_matches[0]
                    snippet = self.resolver.extract_snippet(
                        content, target_sym.start_line, target_sym.end_line
                    )
                    return TargetSelectionResult(
                        success=True,
                        target_type="symbol",
                        file_path=norm_path,
                        start_line=target_sym.start_line,
                        end_line=target_sym.end_line,
                        content=snippet,
                        symbol_name=target_sym.name,
                        symbol_kind=target_sym.kind,
                        enclosing_symbol=parent,
                        has_syntax_errors=has_syntax_errors,
                        parse_status=parse_status,
                        total_file_lines=total_lines,
                    )

        # 2. Collect all candidate symbols with exact name match
        candidates = [s for s in symbols if s.name == symbol_name]

        if not candidates:
            # Case-insensitive suggestion check
            close_matches = [
                s.name for s in symbols if s.name.lower() == symbol_name.lower()
            ]
            suggestion_note = (
                f" Did you mean '{close_matches[0]}'?" if close_matches else ""
            )
            return TargetSelectionResult(
                success=False,
                target_type="symbol",
                file_path=norm_path,
                start_line=1,
                end_line=total_lines,
                content="",
                symbol_name=symbol_name,
                has_syntax_errors=has_syntax_errors,
                parse_status=parse_status,
                error_code="SYMBOL_NOT_FOUND",
                error_message=f"Symbol '{symbol_name}' not found in '{norm_path}'.{suggestion_note}",
                total_file_lines=total_lines,
            )

        # 3. Handle Single Match vs Ambiguous Matches
        is_ambiguous = len(candidates) > 1
        selected_sym: Symbol
        ambiguity_note: Optional[str] = None

        if is_ambiguous:
            # Ambiguity Resolution Strategy:
            # Proximity heuristic: if cursor_line is provided, choose candidate enclosing or closest to cursor
            if cursor_line is not None and cursor_line >= 1:
                enclosing_candidates = [
                    c for c in candidates if c.start_line <= cursor_line <= c.end_line
                ]
                if enclosing_candidates:
                    selected_sym = enclosing_candidates[0]
                    ambiguity_note = (
                        f"Resolved ambiguous symbol '{symbol_name}' ({len(candidates)} definitions found) "
                        f"to scope enclosing line {cursor_line}."
                    )
                else:
                    # Pick closest start_line to cursor
                    candidates_by_distance = sorted(
                        candidates, key=lambda c: abs(c.start_line - cursor_line)
                    )
                    selected_sym = candidates_by_distance[0]
                    ambiguity_note = (
                        f"Resolved ambiguous symbol '{symbol_name}' ({len(candidates)} definitions found) "
                        f"to closest definition at line {selected_sym.start_line}."
                    )
            else:
                # Prefer top-level symbol (parent_id is None) if available, else first
                top_level = [c for c in candidates if c.parent_id is None]
                selected_sym = top_level[0] if top_level else candidates[0]
                cand_locations = [f"line {c.start_line} ({c.kind})" for c in candidates]
                ambiguity_note = (
                    f"Ambiguous symbol '{symbol_name}': {len(candidates)} definitions found at "
                    f"{', '.join(cand_locations)}. Defaulted to definition at line {selected_sym.start_line}."
                )
        else:
            selected_sym = candidates[0]

        # 4. Resolve enclosing parent and child symbols
        enclosing: Optional[Symbol] = None
        if selected_sym.parent_id is not None:
            parents = [s for s in symbols if s.id == selected_sym.parent_id]
            enclosing = parents[0] if parents else None

        children = [s for s in symbols if s.parent_id == selected_sym.id]
        snippet = self.resolver.extract_snippet(
            content, selected_sym.start_line, selected_sym.end_line
        )

        return TargetSelectionResult(
            success=True,
            target_type="symbol",
            file_path=norm_path,
            start_line=selected_sym.start_line,
            end_line=selected_sym.end_line,
            content=snippet,
            symbol_name=selected_sym.name,
            symbol_kind=selected_sym.kind,
            enclosing_symbol=enclosing,
            child_symbols=children,
            is_ambiguous=is_ambiguous,
            candidates=candidates if is_ambiguous else [],
            ambiguity_note=ambiguity_note,
            has_syntax_errors=has_syntax_errors,
            parse_status=parse_status,
            total_file_lines=total_lines,
        )

    def _resolve_range(
        self,
        norm_path: str,
        content: str,
        symbols: List[Symbol],
        start_line: int,
        end_line: int,
        is_supported: bool,
        has_syntax_errors: bool,
        parse_status: str,
        total_lines: int,
    ) -> TargetSelectionResult:
        """Resolve a line range consistently with bounds checking and enclosing scope detection."""
        # Validate 1-indexed bounds
        if start_line < 1 or (total_lines > 0 and start_line > total_lines):
            return TargetSelectionResult(
                success=False,
                target_type="range",
                file_path=norm_path,
                start_line=start_line,
                end_line=end_line,
                content="",
                has_syntax_errors=has_syntax_errors,
                parse_status=parse_status,
                is_supported=is_supported,
                error_code="LINE_OUT_OF_BOUNDS",
                error_message=(
                    f"Start line {start_line} is out of bounds for file '{norm_path}' "
                    f"(valid: 1..{total_lines})."
                ),
                total_file_lines=total_lines,
            )

        # Enforce end_line >= start_line and clamp to total_lines
        clamped_start = max(1, min(start_line, total_lines))
        clamped_end = max(clamped_start, min(end_line, total_lines))

        snippet = self.resolver.extract_snippet(content, clamped_start, clamped_end)

        # Identify enclosing symbol or exact symbol matching the range
        enclosing: Optional[Symbol] = None
        exact_match: Optional[Symbol] = None

        if symbols:
            # Check for exact boundary match (e.g. user selected exact function boundaries)
            for s in symbols:
                if s.start_line == clamped_start and s.end_line == clamped_end:
                    exact_match = s
                    break

            if exact_match is None:
                enclosing = self.resolver.find_enclosing_symbol(symbols, clamped_start)
            else:
                # If exact match is a method, find its enclosing class
                if exact_match.parent_id is not None:
                    parents = [s for s in symbols if s.id == exact_match.parent_id]
                    enclosing = parents[0] if parents else None

        active_symbol = exact_match or enclosing

        return TargetSelectionResult(
            success=True,
            target_type="range",
            file_path=norm_path,
            start_line=clamped_start,
            end_line=clamped_end,
            content=snippet,
            symbol_name=active_symbol.name if active_symbol else None,
            symbol_kind=active_symbol.kind if active_symbol else None,
            enclosing_symbol=enclosing,
            has_syntax_errors=has_syntax_errors,
            parse_status=parse_status,
            is_supported=is_supported,
            total_file_lines=total_lines,
        )
