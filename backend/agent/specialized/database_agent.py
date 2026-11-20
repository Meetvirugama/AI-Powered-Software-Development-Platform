"""backend/agent/specialized/database_agent.py

Specialized Database & Persistence Engineering Agent Specification.
Focus: SQLAlchemy models, Alembic migrations, foreign key cascades, constraints, schema indexing.
"""

from __future__ import annotations

from agent.specialized.base import SpecializedAgentRole, SpecializedAgentSpec

DATABASE_SYSTEM_PROMPT = """You are the Senior Database & Migration Engineering Agent.
Your mandate is to design, modify, and migrate relational database schemas and ORM models.

Core Responsibilities:
1. ORM Models: Maintain SQLAlchemy 2.0 declarative models with Mapped[...] types and index flags.
2. Migration Integrity: Whenever models are added or modified, create a clean Alembic migration.
3. Foreign Keys & Cascades: Ensure all foreign key relationships define explicit ondelete rules.
4. Concurrency: Avoid table locks or unindexed foreign keys that cause slow queries or deadlocks.
5. Invariants: Database migrations must be reversible (upgrade() and downgrade() both valid).
"""

def create_database_agent_spec() -> SpecializedAgentSpec:
    return SpecializedAgentSpec(
        role=SpecializedAgentRole.DATABASE,
        name="DatabaseAgent",
        system_prompt=DATABASE_SYSTEM_PROMPT,
        allowed_file_patterns=[
            "backend/app/models/*",
            "backend/alembic/*",
            "backend/alembic.ini",
            "backend/app/core/database.py",
        ],
        forbidden_file_patterns=[".env*", "*.pem", "*.key"],
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
            "Every model change is accompanied by an Alembic migration script.",
            "All foreign keys define explicit ondelete='CASCADE' or 'SET NULL'.",
            "Indexes exist on all queried foreign keys and filtered timestamp columns.",
        ],
    )
