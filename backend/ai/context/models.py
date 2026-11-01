"""Context domain models and dataclasses for chat and developer intelligence.
Owner: Meet — W1-12 / W2 Intelligence Suite
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from ai.retrieval.base import CodeChunk


@dataclass
class MemoryEntry:
    """A single project memory entry (architecture note, decision, rule, etc.)."""

    id: str
    content: str
    type: str  # "architecture" | "decision" | "rule" | "task" | "failure"
    created_at: str  # ISO 8601 string
    status: str = "active"  # "active" | "stale" | "archived"
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert entry to a serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MemoryEntry:
        """Create a MemoryEntry from a mapping or database record dict."""
        return cls(
            id=str(data.get("id", "")),
            content=str(data.get("content", "")),
            type=str(data.get("type", data.get("type_", "rule"))),
            created_at=str(data.get("created_at", "")),
            status=str(data.get("status", "active")),
            source=str(data.get("source", "")),
        )


@dataclass
class RepositoryFile:
    """Lightweight repository file metadata (path, language, size)."""

    id: str
    path: str
    language: str
    size_bytes: int
    line_count: int
    content_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert repository file metadata to a serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RepositoryFile:
        """Create a RepositoryFile from a dictionary."""
        return cls(
            id=str(data.get("id", "")),
            path=str(data.get("path", "")),
            language=str(data.get("language") or "text"),
            size_bytes=int(data.get("size_bytes", 0)),
            line_count=int(data.get("line_count", 0)),
            content_hash=str(data.get("content_hash", "")),
        )


@dataclass
class ChatMessage:
    """A single turn in conversation history."""

    role: str  # "user" | "assistant" | "system"
    content: str

    def to_dict(self) -> dict[str, str]:
        """Convert message to a dictionary compatible with LLM schemas."""
        return {"role": self.role, "content": self.content}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ChatMessage:
        """Create ChatMessage from a dictionary or schema payload."""
        return cls(
            role=str(data.get("role", "user")),
            content=str(data.get("content", "")),
        )

    @classmethod
    def from_any(cls, obj: Any) -> ChatMessage:
        """Coerce an object (dict, Pydantic model, or ChatMessage) into ChatMessage."""
        if isinstance(obj, ChatMessage):
            return obj
        if isinstance(obj, Mapping):
            return cls.from_dict(obj)
        role = getattr(obj, "role", "user")
        content = getattr(obj, "content", "")
        return cls(role=str(role), content=str(content))


@dataclass
class AgentContext:
    """
    The fully assembled, token-bounded context passed to the LLM for repository Q&A.

    Assembled exclusively by ContextBuilder.build() to guarantee token safety
    and strict data formatting rules.
    """

    code_chunks: list[CodeChunk] = field(default_factory=list)
    memory_chunks: list[MemoryEntry] = field(default_factory=list)
    related_files: list[RepositoryFile] = field(default_factory=list)
    recent_history: list[ChatMessage] = field(default_factory=list)
    total_tokens: int = 0
    chunk_tokens: int = 0
    memory_tokens: int = 0
    history_tokens: int = 0
    overhead_tokens: int = 0

    @property
    def is_empty(self) -> bool:
        """Return True if context contains no code chunks, memory, or history."""
        return not (self.code_chunks or self.memory_chunks or self.recent_history)

    def summary(self) -> dict[str, Any]:
        """Return a structured breakdown of context size and token allocation."""
        return {
            "total_tokens": self.total_tokens,
            "chunk_tokens": self.chunk_tokens,
            "memory_tokens": self.memory_tokens,
            "history_tokens": self.history_tokens,
            "overhead_tokens": self.overhead_tokens,
            "code_chunks_count": len(self.code_chunks),
            "memory_chunks_count": len(self.memory_chunks),
            "recent_history_count": len(self.recent_history),
            "related_files_count": len(self.related_files),
        }

    def to_dict(self) -> dict[str, Any]:
        """Return a dictionary representation of the context."""
        return {
            **self.summary(),
            "code_chunks": [
                asdict(c) if hasattr(c, "__dataclass_fields__") else vars(c)
                for c in self.code_chunks
            ],
            "memory_chunks": [m.to_dict() for m in self.memory_chunks],
            "related_files": [f.to_dict() for f in self.related_files],
            "recent_history": [h.to_dict() for h in self.recent_history],
        }


class ContextStatus(str, Enum):
    """Execution status of intelligence context resolution."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    MISSING_TARGET = "missing_target"
    OVERSIZED = "oversized"


@dataclass
class MissingContextInfo:
    """Explicit, inspectable record of missing, truncated, or unresolved context."""

    file_path: str
    reason: str
    symbol_name: str | None = None
    suggested_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MissingContextInfo:
        return cls(
            file_path=data.get("file_path", ""),
            reason=data.get("reason", ""),
            symbol_name=data.get("symbol_name"),
            suggested_action=data.get("suggested_action", ""),
        )


@dataclass
class ContextLimits:
    """Configurable budget limits for retrieved repository context."""

    max_tokens: int = 10_000
    max_symbols: int = 15
    max_chunks: int = 10
    max_files: int = 50
    max_rules: int = 10
    target_budget_ratio: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContextLimits:
        return cls(
            max_tokens=data.get("max_tokens", 10_000),
            max_symbols=data.get("max_symbols", 15),
            max_chunks=data.get("max_chunks", 10),
            max_files=data.get("max_files", 50),
            max_rules=data.get("max_rules", 10),
            target_budget_ratio=data.get("target_budget_ratio", 0.5),
        )


@dataclass
class TargetSnippet:
    """The primary target code under intelligence analysis."""

    file_path: str
    content: str
    start_line: int
    end_line: int
    symbol_name: str | None = None
    language: str = "text"
    revision: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TargetSnippet:
        return cls(
            file_path=data.get("file_path", ""),
            content=data.get("content", ""),
            start_line=data.get("start_line", 1),
            end_line=data.get("end_line", 1),
            symbol_name=data.get("symbol_name"),
            language=data.get("language", "text"),
            revision=data.get("revision"),
        )


@dataclass
class SymbolContext:
    """A related caller, callee, imported type, or symbol."""

    name: str
    kind: str  # "function" | "class" | "caller" | "type" | "import" | "callee"
    file_path: str
    start_line: int
    end_line: int
    content: str = ""
    score: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SymbolContext:
        return cls(
            name=data.get("name", ""),
            kind=data.get("kind", "function"),
            file_path=data.get("file_path", ""),
            start_line=data.get("start_line", 1),
            end_line=data.get("end_line", 1),
            content=data.get("content", ""),
            score=data.get("score", 1.0),
        )


@dataclass
class IntelligenceContext:
    """
    Shared repository intelligence context for:
    1. Code Explanation
    2. Bug Detection
    3. Test Generation
    4. AI Code Review
    """

    target: TargetSnippet
    related_symbols: list[SymbolContext] = field(default_factory=list)
    relevant_chunks: list[CodeChunk] = field(default_factory=list)
    repository_files: list[RepositoryFile] = field(default_factory=list)
    project_rules: list[str] = field(default_factory=list)
    missing_context: list[MissingContextInfo] = field(default_factory=list)
    status: ContextStatus = ContextStatus.COMPLETE
    total_tokens: int = 0
    token_budget: int = 10_000
    revision: str | None = None

    @property
    def is_complete(self) -> bool:
        return self.status == ContextStatus.COMPLETE

    @property
    def has_missing_context(self) -> bool:
        return len(self.missing_context) > 0 or self.status != ContextStatus.COMPLETE

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target.to_dict() if hasattr(self.target, "to_dict") else asdict(self.target),
            "related_symbols": [s.to_dict() if hasattr(s, "to_dict") else asdict(s) for s in self.related_symbols],
            "relevant_chunks_count": len(self.relevant_chunks),
            "repository_files_count": len(self.repository_files),
            "project_rules": self.project_rules,
            "missing_context": [m.to_dict() if hasattr(m, "to_dict") else asdict(m) for m in self.missing_context],
            "status": self.status.value if isinstance(self.status, ContextStatus) else str(self.status),
            "total_tokens": self.total_tokens,
            "token_budget": self.token_budget,
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntelligenceContext:
        target_raw = data.get("target", {})
        target = TargetSnippet.from_dict(target_raw) if isinstance(target_raw, dict) else target_raw
        related_symbols = [
            SymbolContext.from_dict(s) if isinstance(s, dict) else s
            for s in data.get("related_symbols", [])
        ]
        missing_context = [
            MissingContextInfo.from_dict(m) if isinstance(m, dict) else m
            for m in data.get("missing_context", [])
        ]
        status_raw = data.get("status", "complete")
        try:
            status = ContextStatus(status_raw)
        except ValueError:
            status = ContextStatus.PARTIAL

        return cls(
            target=target,
            related_symbols=related_symbols,
            project_rules=data.get("project_rules", []),
            missing_context=missing_context,
            status=status,
            total_tokens=data.get("total_tokens", 0),
            token_budget=data.get("token_budget", 10_000),
            revision=data.get("revision"),
        )


@dataclass
class IntelligenceContextRequest:
    """Request contract for retrieving targeted repository context."""

    repository_id: str
    file_path: str
    start_line: int | None = None
    end_line: int | None = None
    symbol_name: str | None = None
    include_callers: bool = True
    include_dependencies: bool = True
    include_conventions: bool = True
    limits: ContextLimits = field(default_factory=ContextLimits)
    revision: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository_id": self.repository_id,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "symbol_name": self.symbol_name,
            "include_callers": self.include_callers,
            "include_dependencies": self.include_dependencies,
            "include_conventions": self.include_conventions,
            "limits": self.limits.to_dict(),
            "revision": self.revision,
        }


@dataclass
class IntelligenceContextResponse:
    """Response container wrapping resolved intelligence context with diagnostic metadata."""

    context: IntelligenceContext
    elapsed_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "context": self.context.to_dict(),
            "elapsed_ms": self.elapsed_ms,
            "metadata": self.metadata,
        }

