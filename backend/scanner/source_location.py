"""Source location utilities for AST symbol range resolution, enclosing symbol lookup,
and target snippet extraction.

Owner: Prit — Repository Engine Lead (W2-07)
Fulfills Week 2 Day 1: AST and Source Location Foundation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Sequence
from uuid import UUID

from .extractor import SymbolExtractor
from .parser import Parser
from .symbols import FileInfo, SourceRange, Symbol

logger = logging.getLogger(__name__)


@dataclass
class ResolutionResult:
    """Explicit result of resolving a target snippet or symbol range in source code."""

    success: bool
    range: Optional[SourceRange] = None
    enclosing_symbol: Optional[Symbol] = None
    error_code: Optional[str] = None  # "UNSUPPORTED_LANGUAGE" | "SYMBOL_NOT_FOUND" | "LINE_OUT_OF_BOUNDS" | "EMPTY_CONTENT" | "PARSE_ERROR"
    error_message: Optional[str] = None
    is_supported: bool = True

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "range": {
                "file_path": self.range.file_path,
                "start_line": self.range.start_line,
                "end_line": self.range.end_line,
                "start_column": self.range.start_column,
                "end_column": self.range.end_column,
                "content": self.range.content,
                "symbol_name": self.range.symbol_name,
                "symbol_kind": self.range.symbol_kind,
            }
            if self.range
            else None,
            "enclosing_symbol": {
                "name": self.enclosing_symbol.name,
                "kind": self.enclosing_symbol.kind,
                "start_line": self.enclosing_symbol.start_line,
                "end_line": self.enclosing_symbol.end_line,
                "signature": self.enclosing_symbol.signature,
            }
            if self.enclosing_symbol
            else None,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "is_supported": self.is_supported,
        }


class SourceLocationResolver:
    """Resolves symbols to source line ranges, identifies enclosing scopes,

    and extracts bounded source snippets for Developer Intelligence services.
    """

    def __init__(
        self,
        extractor: Optional[SymbolExtractor] = None,
        parser: Optional[Parser] = None,
    ):
        self.parser = parser or Parser()
        self.extractor = extractor or SymbolExtractor(parser=self.parser)

    def extract_snippet(
        self,
        content: str,
        start_line: int,
        end_line: int,
    ) -> str:
        """Safely extract source code lines between 1-indexed start_line and end_line inclusive.

        Clamps line bounds without raising IndexError or returning out-of-range text.
        """
        if not content:
            return ""

        lines = content.splitlines()
        total_lines = len(lines)

        if total_lines == 0:
            return ""

        # Clamp start and end lines to 1-indexed valid bounds
        clamped_start = max(1, min(start_line, total_lines))
        clamped_end = max(clamped_start, min(end_line, total_lines))

        selected = lines[clamped_start - 1 : clamped_end]
        return "\n".join(selected)

    def resolve_symbol_range(
        self,
        symbols: Sequence[Symbol],
        symbol_name: str,
        file_content: Optional[str] = None,
        file_path: str = "",
        kind: Optional[str] = None,
    ) -> Optional[SourceRange]:
        """Resolve a symbol name (or qualified name like `Class.method`) to its exact SourceRange.

        Returns None if no matching symbol is found.
        """
        if not symbols or not symbol_name:
            return None

        target_sym: Optional[Symbol] = None

        # Check for qualified name e.g. "User.save" or "MyClass.helper"
        if "." in symbol_name:
            parts = symbol_name.split(".")
            parent_name = parts[0]
            child_name = parts[-1]

            parent_candidates = [
                s for s in symbols if s.name == parent_name and s.kind in ("class", "interface")
            ]
            for parent in parent_candidates:
                child_candidates = [
                    s
                    for s in symbols
                    if s.name == child_name and s.parent_id == parent.id
                ]
                if child_candidates:
                    target_sym = child_candidates[0]
                    break

        if target_sym is None:
            # Direct exact match on name
            matches = [s for s in symbols if s.name == symbol_name]
            if kind:
                matches = [s for s in matches if s.kind == kind]

            if matches:
                # Prefer top-level symbol (parent_id is None) if multiple exist, else first
                top_level = [s for s in matches if s.parent_id is None]
                target_sym = top_level[0] if top_level else matches[0]

        if target_sym is None:
            return None

        snippet = ""
        if file_content is not None:
            snippet = self.extract_snippet(
                file_content, target_sym.start_line, target_sym.end_line
            )

        return SourceRange(
            file_path=file_path,
            start_line=target_sym.start_line,
            end_line=target_sym.end_line,
            start_column=0,
            end_column=0,
            content=snippet,
            symbol_name=target_sym.name,
            symbol_kind=target_sym.kind,
        )

    def find_enclosing_symbol(
        self,
        symbols: Sequence[Symbol],
        line: int,
    ) -> Optional[Symbol]:
        """Find the most specific (tightest span) symbol enclosing a given 1-indexed line number.

        For example, if line 25 is inside method `calculate` (lines 20-30) which is
        inside class `Calculator` (lines 10-50), returns the method `calculate`.
        """
        if not symbols or line < 1:
            return None

        enclosing = [
            s
            for s in symbols
            if s.start_line <= line <= s.end_line
        ]

        if not enclosing:
            return None

        # Sort by span length (end_line - start_line) ascending; smallest span is tightest
        enclosing.sort(key=lambda s: (s.end_line - s.start_line, 0 if s.parent_id else 1))
        return enclosing[0]

    def find_enclosing_scope(
        self,
        symbols: Sequence[Symbol],
        line: int,
    ) -> List[Symbol]:
        """Return the hierarchical chain of enclosing symbols from outermost (class) to innermost (method)."""
        if not symbols or line < 1:
            return []

        enclosing = [
            s
            for s in symbols
            if s.start_line <= line <= s.end_line
        ]

        # Sort by span length descending (outermost container first)
        enclosing.sort(key=lambda s: (s.end_line - s.start_line), reverse=True)
        return enclosing

    def resolve_target(
        self,
        file_path: str,
        content: str,
        symbols: Optional[Sequence[Symbol]] = None,
        symbol_name: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        language: Optional[str] = None,
    ) -> ResolutionResult:
        """Resolve a target snippet and enclosing context for an intelligence request.

        Supports resolution via:
        1. Explicit symbol name (`symbol_name`)
        2. Line range (`start_line`, `end_line`)
        3. Enclosing symbol for a single line (`start_line`)

        Returns an explicit ResolutionResult indicating success, exact ranges,
        enclosing symbol, or typed error code.
        """
        if not content and content != "":
            return ResolutionResult(
                success=False,
                error_code="EMPTY_CONTENT",
                error_message=f"File {file_path} is empty or unreadable.",
            )

        lines = content.splitlines()
        total_lines = len(lines)

        # Detect language if not provided
        lang = language or "unknown"
        if lang == "unknown":
            from .detector import LanguageDetector

            detector = LanguageDetector()
            lang = detector.detect(FileInfo(file_path, len(content), "unknown", False))

        is_supported = self.parser.is_language_supported(lang)
        if not is_supported and lang != "unknown":
            return ResolutionResult(
                success=False,
                is_supported=False,
                error_code="UNSUPPORTED_LANGUAGE",
                error_message=f"Language '{lang}' is not supported for AST source range resolution.",
            )

        # Extract symbols if not provided
        file_symbols: List[Symbol] = list(symbols) if symbols is not None else []
        if symbols is None and is_supported:
            file_info = FileInfo(file_path, len(content), lang, False)
            file_symbols = self.extractor.extract(file_info, content)

        # Strategy 1: Resolve by symbol name
        if symbol_name:
            resolved_range = self.resolve_symbol_range(
                file_symbols, symbol_name, file_content=content, file_path=file_path
            )
            if resolved_range is not None:
                enclosing = self.find_enclosing_symbol(
                    file_symbols, resolved_range.start_line
                )
                # If enclosing is the symbol itself, check if there is an outer parent
                if enclosing and enclosing.name == resolved_range.symbol_name:
                    scope = self.find_enclosing_scope(file_symbols, resolved_range.start_line)
                    enclosing = scope[0] if len(scope) > 1 else None

                return ResolutionResult(
                    success=True,
                    range=resolved_range,
                    enclosing_symbol=enclosing,
                    is_supported=True,
                )

            return ResolutionResult(
                success=False,
                error_code="SYMBOL_NOT_FOUND",
                error_message=f"Symbol '{symbol_name}' was not found in '{file_path}'.",
                is_supported=is_supported,
            )

        # Strategy 2: Resolve by line range
        if start_line is not None:
            if start_line < 1 or (total_lines > 0 and start_line > total_lines):
                return ResolutionResult(
                    success=False,
                    error_code="LINE_OUT_OF_BOUNDS",
                    error_message=f"Start line {start_line} is out of bounds for {file_path} (1..{total_lines}).",
                    is_supported=is_supported,
                )

            effective_end = end_line if end_line is not None else start_line
            if effective_end < start_line:
                effective_end = start_line

            snippet = self.extract_snippet(content, start_line, effective_end)
            enclosing = self.find_enclosing_symbol(file_symbols, start_line)

            source_range = SourceRange(
                file_path=file_path,
                start_line=start_line,
                end_line=min(effective_end, total_lines) if total_lines else effective_end,
                start_column=0,
                end_column=0,
                content=snippet,
                symbol_name=enclosing.name if enclosing else None,
                symbol_kind=enclosing.kind if enclosing else None,
            )

            return ResolutionResult(
                success=True,
                range=source_range,
                enclosing_symbol=enclosing,
                is_supported=is_supported,
            )

        # Default fallback: entire file
        snippet = content
        source_range = SourceRange(
            file_path=file_path,
            start_line=1,
            end_line=total_lines,
            start_column=0,
            end_column=0,
            content=snippet,
            symbol_name=file_symbols[0].name if file_symbols else None,
            symbol_kind=file_symbols[0].kind if file_symbols else None,
        )
        return ResolutionResult(
            success=True,
            range=source_range,
            enclosing_symbol=file_symbols[0] if file_symbols else None,
            is_supported=is_supported,
        )
