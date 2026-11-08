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
    calculate_calibration_ratio,
    calculate_effective_budget,
    estimate_messages_tokens,
    estimate_tokens,
    get_calibration_tracker,
    get_encoding_for_model,
    get_safety_factor,
    DEFAULT_SAFETY_FACTOR,
    PROVIDER_SAFETY_FACTORS,
    TokenCalibrationSample,
    TokenCalibrationTracker,
)
from ai.context.bug_context import (
    BugContextExtractor,
    extract_bug_context,
)
from ai.context.explanation import (
    CallerResolution,
    ExplanationContextEnricher,
    enrich_explanation_context,
    resolve_caller_status,
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
from ai.context.task_context import (
    TaskContextBuilder,
    TaskContextManifest,
)
from ai.context.intelligence_context import (
    build_intelligence_context,
)
from ai.context.chat_context import (
    build_chat_context,
    dedup_memory,
)

__all__ = [
    "ALLOWED_AI_PROVIDERS",
    "AgentContext",
    "BugContextExtractor",
    "CallerResolution",
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
    "TaskContextBuilder",
    "TaskContextManifest",
    "TestContextBuilder",
    "TokenCalibrationSample",
    "TokenCalibrationTracker",
    "calculate_calibration_ratio",
    "calculate_effective_budget",
    "count_tokens",
    "DEFAULT_SAFETY_FACTOR",
    "estimate_messages_tokens",
    "estimate_tokens",
    "get_calibration_tracker",
    "get_encoding_for_model",
    "get_safety_factor",
    "PROVIDER_SAFETY_FACTORS",
    "build_chat_context",
    "build_intelligence_context",
    "build_multi_file_review_context",
    "build_test_generation_context",
    "dedup_memory",
    "enrich_explanation_context",
    "extract_bug_context",
    "resolve_caller_status",
    "shared_context_service",
]
