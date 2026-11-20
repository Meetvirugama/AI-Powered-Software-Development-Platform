"""Standalone AI services for Developer Intelligence & Week 3 Workflow Automation."""

from __future__ import annotations

from ai.services.agent_execution_loop import (
    AgentExecutionLoop,
    AgentExecutionResult,
    LoopDetectedError,
    StepExecutionRecord,
    StepExecutionStatus,
)
from ai.services.ai_quality_evaluator import AIQualityEvaluator
from ai.services.bounded_repair_loop import (
    BoundedRepairLoop,
    BoundedRepairOutcome,
    LLMRepairSynthesizer,
)
from ai.services.bug_detection_engine import BugDetectionEngine
from ai.services.code_review_engine import AICodeReviewEngine
from ai.services.execution_budget_manager import (
    BudgetExceededError,
    ExecutionBudget,
    ExecutionBudgetManager,
)
from ai.services.execution_checkpoint_manager import (
    ExecutionCheckpoint,
    ExecutionCheckpointManager,
)
from ai.services.execution_recovery import (
    ExecutionRecoveryService,
    RecoveryOutcome,
)
from ai.services.execution_verifier import (
    ExecutionVerifier,
    StepVerificationEvidence,
    StepVerificationOutcome,
)
from ai.services.explanation_service import CodeExplanationService
from ai.services.issue_task_adapter import (
    IssueToTaskAdapter,
    extract_safe_repo_paths,
    fence_untrusted_issue_data,
    format_issue_from_finding,
)
from ai.services.intent_router import (
    IntentAnalysisResult,
    IntentRouter,
    TaskIntent,
)
from ai.services.plan_critic import (
    CriticIssue,
    CriticReview,
    CriticSeverity,
    PlanCritic,
)
from ai.services.plan_replanner import PlanReplanner
from ai.services.requirement_verifier import (
    RequirementComplianceItem,
    RequirementToCodeVerifier,
    RequirementVerificationResult,
)
from ai.services.retrieval_optimizer import (
    AgentTokenBudgetManager,
    LatencyPercentiles,
    RetrievalLatencyOptimizer,
    TokenBudgetExhaustedError,
)
from ai.services.task_completeness_checker import (
    CompletenessIssue,
    PlanCompletenessReport,
    TaskCompletenessChecker,
)
from ai.services.task_planner import PlanningOutcome, TaskPlanner
from ai.services.task_requirement_discovery import (
    DiscoveredTaskRequirement,
    TaskRequirementDiscovery,
)
from ai.services.test_generation_service import TestGenerationService

__all__ = [
    "AICodeReviewEngine",
    "AIQualityEvaluator",
    "AgentExecutionLoop",
    "AgentExecutionResult",
    "AgentTokenBudgetManager",
    "BoundedRepairLoop",
    "BoundedRepairOutcome",
    "BudgetExceededError",
    "BugDetectionEngine",
    "CodeExplanationService",
    "CompletenessIssue",
    "CriticIssue",
    "CriticReview",
    "CriticSeverity",
    "DiscoveredTaskRequirement",
    "ExecutionBudget",
    "ExecutionBudgetManager",
    "ExecutionCheckpoint",
    "ExecutionCheckpointManager",
    "ExecutionRecoveryService",
    "ExecutionVerifier",
    "IntentAnalysisResult",
    "IntentRouter",
    "IssueToTaskAdapter",
    "LLMRepairSynthesizer",
    "LatencyPercentiles",
    "LoopDetectedError",
    "PlanCritic",
    "PlanCompletenessReport",
    "PlanReplanner",
    "PlanningOutcome",
    "RecoveryOutcome",
    "RequirementComplianceItem",
    "RequirementToCodeVerifier",
    "RequirementVerificationResult",
    "RetrievalLatencyOptimizer",
    "StepExecutionRecord",
    "StepExecutionStatus",
    "StepVerificationEvidence",
    "StepVerificationOutcome",
    "TaskCompletenessChecker",
    "TaskIntent",
    "TaskPlanner",
    "TaskRequirementDiscovery",
    "TestGenerationService",
    "TokenBudgetExhaustedError",
    "extract_safe_repo_paths",
    "fence_untrusted_issue_data",
    "format_issue_from_finding",
]
