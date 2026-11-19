"""backend/agent/specialized/__init__.py

Specialized multi-agent architecture and dispatcher.
"""

from agent.specialized.base import SpecializedAgentRole, SpecializedAgentSpec
from agent.specialized.backend_agent import create_backend_agent_spec
from agent.specialized.frontend_agent import create_frontend_agent_spec
from agent.specialized.database_agent import create_database_agent_spec
from agent.specialized.testing_agent import create_testing_agent_spec
from agent.specialized.dispatcher import AgentDispatcher

__all__ = [
    "SpecializedAgentRole",
    "SpecializedAgentSpec",
    "create_backend_agent_spec",
    "create_frontend_agent_spec",
    "create_database_agent_spec",
    "create_testing_agent_spec",
    "AgentDispatcher",
]
