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
from ai.context.bug_context import (
    BugContextExtractor,
    extract_bug_context,
)
from ai.context.explanation import (
    ExplanationContextEnricher,
    enrich_explanation_context,
)
from ai.context.test_context import (
    TestContextBuilder,
    build_test_generation_context,
)

__all__ = [
    "AgentContext",
    "BugContextExtractor",
    "ChatMessage",
    "ContextBuilder",
    "ContextLimits",
    "ContextStatus",
    "ExplanationContextEnricher",
    "IntelligenceContext",
    "IntelligenceContextRequest",
    "IntelligenceContextResponse",
    "MemoryEntry",
    "MissingContextInfo",
    "RepositoryFile",
    "SymbolContext",
    "TargetSnippet",
    "TestContextBuilder",
    "count_tokens",
    "build_test_generation_context",
    "enrich_explanation_context",
    "extract_bug_context",
]
