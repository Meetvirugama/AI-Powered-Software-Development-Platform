"""backend/agent/specialized/backend_agent.py

Specialized Backend Engineering Agent Specification.
Focus: FastAPI routes, Pydantic schemas, dependency injection, business logic, auth validation.
"""

from __future__ import annotations

from agent.specialized.base import SpecializedAgentRole, SpecializedAgentSpec

BACKEND_SYSTEM_PROMPT = """You are the Senior Backend Engineering Agent.
Your mandate is to inspect, implement, and modify server-side components with production-grade reliability.

Core Responsibilities:
1. Endpoints & Routing: Author clean FastAPI route handlers under backend/app/api/ with proper status codes.
2. Type Safety: Enforce strict Pydantic v2 schemas for all requests and responses with explicit validators.
3. Security & Governance: Never leak secrets, API keys, or raw exception traces; use APIError and ErrorCode.
4. Error Handling: Always fail closed on missing credentials or permissions; use require_min_role.
5. Invariants: Maintain 100% test pass rate and backward-compatible serialization.
"""

def create_backend_agent_spec() -> SpecializedAgentSpec:
    return SpecializedAgentSpec(
        role=SpecializedAgentRole.BACKEND,
        name="BackendAgent",
        system_prompt=BACKEND_SYSTEM_PROMPT,
        allowed_file_patterns=[
            "backend/app/api/*",
            "backend/app/services/*",
            "backend/app/repositories/*",
            "backend/app/core/*",
            "backend/app/schemas/*",
            "backend/ai/*",
        ],
        forbidden_file_patterns=[".env*", "*.pem", "*.key", "id_rsa*"],
        allowed_tools=[
            "read_file",
            "write_file",
            "patch_file",
            "delete_file",
            "list_files",
            "execute_command",
            "inspect_diff",
        ],
        quality_gate_rules=[
            "Code compiles with clean AST syntax without SyntaxError.",
            "All modified endpoints have structured Pydantic schemas.",
            "Zero sensitive tokens or private keys present in source code.",
        ],
    )
