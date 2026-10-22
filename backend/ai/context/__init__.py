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
from ai.context.review_context import (
    ModifiedFile,
    ReviewBlastRadius,
    ReviewContextBuilder,
    build_multi_file_review_context,
)
from ai.context.service import (
    ALLOWED_AI_PROVIDERS,
    RepositoryContextService,
    RevisionDriftError,
    shared_context_service,
)
from ai.context.test_context import (
    TestContextBuilder,
    build_test_generation_context,
)

__all__ = [
    "ALLOWED_AI_PROVIDERS",
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
    "ModifiedFile",
    "RepositoryContextService",
    "RepositoryFile",
    "ReviewBlastRadius",
    "ReviewContextBuilder",
    "RevisionDriftError",
    "SymbolContext",
    "TargetSnippet",
    "TestContextBuilder",
    "count_tokens",
    "build_multi_file_review_context",
    "build_test_generation_context",
    "enrich_explanation_context",
    "extract_bug_context",
    "shared_context_service",
]
