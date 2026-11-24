"""backend/ai/services/intent_router.py

Intent Router and Ambiguity Detector for Universal AI Prompt-to-PR System.
Decomposes user freeform natural language prompts into classified task intents,
complexity scores, affected architectural layers, and ambiguity signals.
Reference: task.md Part 5 / TASK_PLANNER_IMPLEMENTATION_PLAN.md Phase 2.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class TaskIntent(str, Enum):
    """Normalized intent category for task engineering requests."""

    BUG_FIX = "bug_fix"
    NEW_FEATURE = "new_feature"
    REFACTOR = "refactor"
    SECURITY_FIX = "security_fix"
    PERFORMANCE = "performance"
    FRONTEND = "frontend"
    BACKEND = "backend"
    DATABASE = "database"
    AI_ML = "ai_ml"
    DOCUMENTATION = "documentation"
    TESTING = "testing"
    DEVOPS = "devops"
    INFRASTRUCTURE = "infrastructure"
    API_INTEGRATION = "api_integration"
    MULTI_COMPONENT = "multi_component"
    MIXED = "mixed"


class IntentAnalysisResult(BaseModel):
    """Structured decomposition and routing assessment of a development prompt."""

    model_config = ConfigDict(extra="ignore")

    primary_intent: TaskIntent = Field(..., description="Dominant task intent.")
    secondary_intents: list[TaskIntent] = Field(
        default_factory=list,
        description="Secondary or cross-cutting intents involved in request.",
    )
    confidence: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Classification confidence score in [0.0, 1.0].",
    )
    complexity_score: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Estimated architectural complexity score.",
    )
    is_ambiguous: bool = Field(
        default=False,
        description="Whether the prompt is too open-ended or ambiguous to plan deterministically.",
    )
    ambiguity_reason: str | None = Field(
        default=None,
        description="Explanation when prompt is flagged as ambiguous.",
    )
    affected_layers: list[str] = Field(
        default_factory=list,
        description="Architectural layers involved: backend, frontend, database, testing, security, devops.",
    )
    suggested_clarifications: list[str] = Field(
        default_factory=list,
        description="Clarifying questions or suggested scoping proposals.",
    )
    extracted_keywords: list[str] = Field(
        default_factory=list,
        description="Key domain and code terms extracted from the prompt.",
    )


class IntentRouter:
    """Classifies user engineering requests and detects underspecified requirements."""

    _SECURITY_KEYWORDS = {
        "cwe", "vulnerability", "xss", "csrf", "sqli", "injection",
        "secret", "token", "leak", "unauthorized", "auth", "permission",
        "sanitize", "hardcoded", "overflow", "cve", "rbac", "exploit",
    }

    _BUG_KEYWORDS = {
        "bug", "fix", "crash", "error", "traceback", "exception",
        "broken", "fails", "failed", "failure", "resolves", "incorrect",
        "regression", "hang", "freeze", "infinite loop", "flaky",
    }

    _PERF_KEYWORDS = {
        "optimize", "performance", "speed", "latency", "slow",
        "throughput", "cache", "caching", "memory leak", "cpu", "bottleneck",
    }

    _REFACTOR_KEYWORDS = {
        "refactor", "cleanup", "clean up", "restructure", "modularize",
        "extract", "dead code", "deprecate", "rename", "simplify", "deduplicate",
    }

    _DATABASE_KEYWORDS = {
        "migration", "alembic", "table", "column", "schema", "database",
        "postgres", "foreign key", "index", "sql", "model", "orm",
    }

    _FRONTEND_KEYWORDS = {
        "ui", "frontend", "react", "component", "tailwind", "css",
        "modal", "button", "dialog", "page", "render", "view", "panel", "screen",
    }

    _TESTING_KEYWORDS = {
        "test", "tests", "pytest", "vitest", "jest", "unittest",
        "coverage", "mock", "fixture", "assert", "assertion", "testcase",
    }

    _DOCS_KEYWORDS = {
        "doc", "docs", "documentation", "readme", "swagger", "openapi",
        "docstring", "comment", "guide", "tutorial", "markdown",
    }

    _AMBIGUOUS_PATTERNS = [
        re.compile(r"^\s*(make|do|fix|improve|update|change)\s+(it|this|that|something|things|code|app)\b", re.IGNORECASE),
        re.compile(r"^\s*(help|please help|make it better|improve my code)\s*$", re.IGNORECASE),
        re.compile(r"\bhelp\b.*\b(improve|fix|clean)\b.*\b(code|app|things|it)\b", re.IGNORECASE),
        re.compile(r"\b(improve|make better)\s+(my\s+)?(code|app)\b", re.IGNORECASE),
        re.compile(r"^\s*help\b", re.IGNORECASE),
    ]

    def classify_intent(
        self,
        prompt: str,
        context: dict[str, Any] | None = None,
    ) -> IntentAnalysisResult:
        """Analyze prompt and return intent, complexity, layers, and ambiguity assessment."""
        text = (prompt or "").strip()
        lower = text.lower()

        # 1. Ambiguity detection
        is_ambiguous = False
        ambiguity_reason = None
        suggested_clarifications: list[str] = []

        if len(text) < 15 and not any(k in lower for k in ("fix", "bug", "add", "test", "doc")):
            is_ambiguous = True
            ambiguity_reason = "Prompt is very brief and lacks specific target files, symbols, or requirements."
            suggested_clarifications = [
                "Which component or feature would you like to modify?",
                "What specific behavior or outcome should be verified?",
            ]
        else:
            for pat in self._AMBIGUOUS_PATTERNS:
                if pat.search(text):
                    is_ambiguous = True
                    ambiguity_reason = "Prompt is unbounded and does not specify target modules or desired behavior."
                    suggested_clarifications = [
                        "Could you specify which feature or error message you want addressed?",
                        "What are the expected acceptance criteria for this change?",
                    ]
                    break

        # 2. Extract keywords and match categories
        words = set(re.findall(r"\b[a-zA-Z0-9_\-\.]{3,}\b", lower))
        matched_categories: dict[TaskIntent, int] = {}

        def _count_matches(kw_set: set[str], intent: TaskIntent, weight: int = 1) -> None:
            matches = sum(1 for kw in kw_set if kw in lower or kw in words)
            if matches > 0:
                matched_categories[intent] = matched_categories.get(intent, 0) + (matches * weight)

        _count_matches(self._SECURITY_KEYWORDS, TaskIntent.SECURITY_FIX, weight=2)
        _count_matches(self._BUG_KEYWORDS, TaskIntent.BUG_FIX, weight=2)
        _count_matches(self._PERF_KEYWORDS, TaskIntent.PERFORMANCE)
        _count_matches(self._DATABASE_KEYWORDS, TaskIntent.DATABASE)
        _count_matches(self._FRONTEND_KEYWORDS, TaskIntent.FRONTEND)
        _count_matches(self._TESTING_KEYWORDS, TaskIntent.TESTING)
        _count_matches(self._DOCS_KEYWORDS, TaskIntent.DOCUMENTATION)
        _count_matches(self._REFACTOR_KEYWORDS, TaskIntent.REFACTOR)
        _count_matches({"backend", "middleware", "endpoint", "fastapi", "server"}, TaskIntent.BACKEND)
        _count_matches({"llm", "embedding", "retrieval", "rag", "machine learning", "inference"}, TaskIntent.AI_ML)
        _count_matches({"ci/cd", "github actions", "deployment", "pipeline", "release"}, TaskIntent.DEVOPS)
        _count_matches({"terraform", "kubernetes", "docker", "azure", "load balancer"}, TaskIntent.INFRASTRUCTURE)
        _count_matches({"webhook", "third-party api", "api integration", "oauth callback"}, TaskIntent.API_INTEGRATION)

        # Feature matching if prompt mentions adding/creating new things
        if any(term in lower for term in ("add", "create", "implement", "support", "new", "build")):
            matched_categories[TaskIntent.NEW_FEATURE] = matched_categories.get(TaskIntent.NEW_FEATURE, 0) + 2

        # 3. Determine primary & secondary intents
        if not matched_categories:
            primary_intent = TaskIntent.NEW_FEATURE
            secondary_intents = []
        else:
            sorted_intents = sorted(matched_categories.items(), key=lambda x: x[1], reverse=True)
            primary_intent = sorted_intents[0][0]
            secondary_intents = [item[0] for item in sorted_intents[1:4]]

        if len(secondary_intents) >= 2 and TaskIntent.MIXED not in secondary_intents:
            secondary_intents.append(TaskIntent.MIXED)

        # 4. Infer affected architectural layers
        affected_layers: list[str] = []
        if TaskIntent.FRONTEND in matched_categories or "ui" in lower or "frontend" in lower:
            affected_layers.append("frontend")
        if TaskIntent.DATABASE in matched_categories or "migration" in lower or "table" in lower:
            affected_layers.append("database")
        if TaskIntent.SECURITY_FIX in matched_categories or "auth" in lower or "secret" in lower:
            affected_layers.append("security")
        if TaskIntent.TESTING in matched_categories or "test" in lower:
            affected_layers.append("testing")
        if TaskIntent.BACKEND in matched_categories or not affected_layers:
            affected_layers.insert(0, "backend")
        for intent in (TaskIntent.AI_ML, TaskIntent.DEVOPS, TaskIntent.INFRASTRUCTURE, TaskIntent.API_INTEGRATION):
            if intent in matched_categories:
                affected_layers.append(intent.value)
        implementation_layers = set(affected_layers) - {"security", "testing"}
        if len(implementation_layers) > 1:
            secondary_intents.append(TaskIntent.MULTI_COMPONENT)

        # 5. Compute complexity score
        complexity = min(1.0, max(0.2, (len(affected_layers) * 0.2) + (len(text) / 500.0) * 0.2))

        # Extracted domain keywords
        all_kw_matches = [
            w for w in words
            if len(w) > 3 and any(w in kw_set for kw_set in (
                self._SECURITY_KEYWORDS, self._BUG_KEYWORDS, self._DATABASE_KEYWORDS,
                self._FRONTEND_KEYWORDS, self._PERF_KEYWORDS, self._REFACTOR_KEYWORDS,
            ))
        ]

        return IntentAnalysisResult(
            primary_intent=primary_intent,
            secondary_intents=secondary_intents,
            confidence=0.90 if matched_categories else 0.70,
            complexity_score=round(complexity, 2),
            is_ambiguous=is_ambiguous,
            ambiguity_reason=ambiguity_reason,
            affected_layers=list(dict.fromkeys(affected_layers)),
            suggested_clarifications=suggested_clarifications,
            extracted_keywords=list(dict.fromkeys(all_kw_matches))[:10],
        )

    def decompose_requirements(self, prompt: str) -> list[str]:
        """Decompose a developer prompt into atomic requirement statements."""
        text = (prompt or "").strip()
        if not text:
            return []
        parts = re.split(r"(?:\r?\n|;|\band\b|(?<=[.!?])\s+)", text)
        reqs = [p.strip().lstrip("-*•0123456789. ") for p in parts if len(p.strip()) > 5]
        return reqs if reqs else [text]
