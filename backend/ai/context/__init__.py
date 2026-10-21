"""
AI Context Assembly Module.

Provides token-bounded context assembly and formatting for repository Q&A.
"""

from ai.context.builder import (
    AgentContext,
    ChatMessage,
    ContextBuilder,
    ContextLimits,
    ContextStatus,
    IntelligenceContext,
    IntelligenceContextRequest,
    IntelligenceContextResponse,
    MemoryEntry,
    MissingContextInfo,
    RepositoryFile,
    SymbolContext,
    TargetSnippet,
    count_tokens,
)

__all__ = [
    "AgentContext",
    "ChatMessage",
    "ContextBuilder",
    "ContextLimits",
    "ContextStatus",
    "IntelligenceContext",
    "IntelligenceContextRequest",
    "IntelligenceContextResponse",
    "MemoryEntry",
    "MissingContextInfo",
    "RepositoryFile",
    "SymbolContext",
    "TargetSnippet",
    "count_tokens",
]
