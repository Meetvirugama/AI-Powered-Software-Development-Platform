"""backend/agent/specialized/base.py

Base contracts for Specialized Multi-Agent Engineering Architecture.
Part of Phase 3 (task.md §5 & 17 / TASK_PLANNER_IMPLEMENTATION_PLAN.md Phase 3).
"""

from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class SpecializedAgentRole(str, Enum):
    """Specialized engineering disciplines for multi-agent code modification."""

    BACKEND = "backend"
    FRONTEND = "frontend"
    DATABASE = "database"
    TESTING = "testing"
    COORDINATOR = "coordinator"


class SpecializedAgentSpec(BaseModel):
    """Configuration, capabilities, and system instructions for a specialized agent."""

    model_config = ConfigDict(extra="ignore")

    role: SpecializedAgentRole = Field(..., description="Engineering specialization discipline.")
    name: str = Field(..., description="Identifier name of the specialized agent.")
    system_prompt: str = Field(..., description="Role-specific system prompt enforcing engineering invariants.")
    allowed_file_patterns: list[str] = Field(
        default_factory=list,
        description="Glob patterns of files this agent is permitted to inspect or modify.",
    )
    forbidden_file_patterns: list[str] = Field(
        default_factory=lambda: [".env*", "*.pem", "*.key", "id_rsa*"],
        description="Glob patterns strictly prohibited from modification.",
    )
    allowed_tools: list[str] = Field(
        default_factory=list,
        description="Whitelisted tool identifiers permitted for this agent role.",
    )
    quality_gate_rules: list[str] = Field(
        default_factory=list,
        description="Mandatory validation rules before an agent can declare a step completed.",
    )

    def can_touch_file(self, file_path: str) -> bool:
        """Evaluate whether a file path falls within the agent's specialization domain."""
        norm = file_path.lower().replace("\\", "/").strip()
        # Strictly enforce forbidden patterns
        for forbidden in self.forbidden_file_patterns:
            f_clean = forbidden.rstrip("*").lower()
            if f_clean in norm:
                return False
        if not self.allowed_file_patterns:
            return True

        import fnmatch
        for pat in self.allowed_file_patterns:
            p_clean = pat.lower()
            if fnmatch.fnmatch(norm, p_clean) or fnmatch.fnmatch(norm, f"*/{p_clean.lstrip('/')}"):
                return True
            clean_sub = pat.strip("*").lower()
            if clean_sub and clean_sub in norm:
                return True
        return False
