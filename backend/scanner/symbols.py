from dataclasses import dataclass
from uuid import UUID


@dataclass
class Symbol:
    id: UUID
    name: str
    kind: str           # "class" | "function" | "method" | "import" | "constant"
    file_id: UUID
    start_line: int
    end_line: int
    signature: str
    parent_id: UUID | None = None

@dataclass
class SymbolEdge:
    source_id: UUID
    target_id: UUID
    edge_type: str      # "calls" | "imports" | "extends" | "implements"

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
