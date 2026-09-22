from dataclasses import dataclass
from uuid import UUID
from typing import List, Optional

@dataclass
class Symbol:
    id: UUID
    name: str
    kind: str           # "class" | "function" | "method" | "import" | "constant"
    file_id: UUID
    start_line: int
    end_line: int
    signature: str
    parent_id: Optional[UUID]

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
    errors: List[str]

@dataclass
class FileInfo:
    path: str
    size_bytes: int
    language: str
    is_binary: bool
