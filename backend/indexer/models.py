from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass
class Chunk:
    repository_id: UUID
    file_id: UUID
    symbol_id: UUID | None
    content: str
    start_line: int
    end_line: int
    language: str
    chunk_type: str
    token_count: int
    content_hash: str
    metadata: dict[str, Any]