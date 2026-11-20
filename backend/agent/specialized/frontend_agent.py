"""backend/agent/specialized/frontend_agent.py

Specialized Frontend Engineering Agent Specification.
Focus: React components, TypeScript interfaces, Tailwind CSS styling, client state, error boundaries.
"""

from __future__ import annotations

from agent.specialized.base import SpecializedAgentRole, SpecializedAgentSpec

FRONTEND_SYSTEM_PROMPT = """You are the Senior Frontend Engineering Agent.
Your mandate is to build, refactor, and polish client-side web applications using React, TypeScript, and Tailwind CSS.

Core Responsibilities:
1. Components: Author modular, accessible React components with clean props and hooks.
2. Type Safety: Enforce strict TypeScript types; do not bypass with 'any' unless strictly necessary.
3. Styling: Use clean Tailwind CSS utility classes adhering to the dark/light design system.
4. Error Resilience: Wrap asynchronous network requests with loading states, error boundaries, and retry prompts.
5. Invariants: Avoid HTML nesting violations (e.g. <div> inside <p>); pass all vitest component tests.
"""

def create_frontend_agent_spec() -> SpecializedAgentSpec:
    return SpecializedAgentSpec(
        role=SpecializedAgentRole.FRONTEND,
        name="FrontendAgent",
        system_prompt=FRONTEND_SYSTEM_PROMPT,
        allowed_file_patterns=[
            "frontend/src/*",
            "frontend/public/*",
            "frontend/package.json",
        ],
        forbidden_file_patterns=[".env*", "*.pem", "*.key"],
        allowed_tools=[
            "read_file",
            "write_file",
            "patch_file",
            "delete_file",
            "list_files",
            "inspect_diff",
        ],
        quality_gate_rules=[
            "Balanced braces, brackets, and string literals in all TSX/TS files.",
            "Zero HTML tag nesting hydration defects.",
            "All client-side API calls properly handle 401/403/500 errors.",
        ],
    )
