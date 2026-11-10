from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

EdgeProvenance = Literal["tree_sitter", "import_tracker", "scip"]
EdgeResolutionStatus = Literal["resolved", "ambiguous", "unresolved"]

EDGE_TYPE_DEFAULT_WEIGHTS: dict[str, float] = {
    "calls": 1.0,
    "inherits": 1.2,
    "extends": 1.2,
    "implements": 1.1,
    "imports": 0.6,
    "uses": 0.8,
    "tests": 0.5,
}

VALID_EDGE_TYPES: tuple[str, ...] = (
    "calls",
    "imports",
    "extends",
    "inherits",
    "implements",
    "uses",
    "tests",
)

VALID_EDGE_PROVENANCE: tuple[str, ...] = (
    "tree_sitter",
    "import_tracker",
    "scip",
)

VALID_EDGE_RESOLUTION_STATUS: tuple[str, ...] = (
    "resolved",
    "ambiguous",
    "unresolved",
)


@dataclass
class Symbol:
    id: UUID
    name: str
    kind: str           # "class" | "function" | "method" | "import" | "constant" | "interface" | "struct"
    file_id: UUID
    start_line: int
    end_line: int
    signature: str = ""
    parent_id: UUID | None = None
    file_path: str = ""
    calls: list[str] = field(default_factory=list)
    importance_score: float = 0.0


@dataclass
class SymbolEdge:
    source_id: UUID
    target_id: UUID | None
    edge_type: str      # "calls" | "imports" | "extends" | "inherits" | "implements" | "uses" | "tests"
    target_name: str | None = None
    provenance: str = "tree_sitter"
    resolution_status: EdgeResolutionStatus | str = "resolved"
    confidence: float = 1.0
    weight: float = 1.0
    candidate_target_ids: tuple[UUID, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if isinstance(self.candidate_target_ids, list):
            self.candidate_target_ids = tuple(self.candidate_target_ids)


@dataclass
class ScanResult:
    file_count: int
    symbol_count: int
    edge_count: int
    errors: list[str]


@dataclass
class FileInfo:
    path: str
    size_bytes: int
    language: str
    is_binary: bool


@dataclass
class SourceRange:
    file_path: str
    start_line: int
    end_line: int
    start_column: int = 0
    end_column: int = 0
    content: str = ""
    symbol_name: str | None = None
    symbol_kind: str | None = None


@dataclass
class ParseResult:
    success: bool
    tree: object | None = None
    language: str = "unknown"
    is_supported: bool = True
    error_message: str | None = None
    has_syntax_errors: bool = False
    grammar_backend: str | None = None
