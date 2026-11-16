# Documentation

Official documentation for the AI-Powered Software Development Platform. Every page describes the **current implementation** verified against the source code (commit `5d0b3ff`, 2026-11-16). Historical sprint plans, audit reports and per-day acceptance reports are intentionally not part of this set.

## Map

| Section | Documents |
|---|---|
| 01 Overview | [Project overview](01-overview/PROJECT_OVERVIEW.md) · [Features and status](01-overview/FEATURES.md) |
| 02 Architecture | [System](02-architecture/SYSTEM_ARCHITECTURE.md) · [Frontend](02-architecture/FRONTEND_ARCHITECTURE.md) · [Backend](02-architecture/BACKEND_ARCHITECTURE.md) · [AI and RAG](02-architecture/AI_AND_RAG_ARCHITECTURE.md) · [Database](02-architecture/DATABASE_ARCHITECTURE.md) · [Agent execution](02-architecture/AGENT_EXECUTION_ARCHITECTURE.md) |
| 03 Engineering | [API reference](03-engineering/API_REFERENCE.md) · [Developer intelligence features](03-engineering/DEVELOPER_INTELLIGENCE.md) · [Tool registry](03-engineering/TOOL_REGISTRY.md) · [Data flows](03-engineering/DATA_FLOW.md) |
| 04 Security | [Security](04-security/SECURITY.md) |
| 05 Testing | [Testing guide](05-testing/TESTING_GUIDE.md) |
| 06 Development | [Setup](06-development/DEVELOPMENT_SETUP.md) · [Development guide](06-development/DEVELOPMENT_GUIDE.md) · [Contributing](06-development/CONTRIBUTING.md) |
| 07 Deployment | [Deployment guide](07-deployment/DEPLOYMENT_GUIDE.md) · [Environment configuration](07-deployment/ENVIRONMENT_CONFIGURATION.md) · [Runbooks](07-deployment/RUNBOOKS.md) |
| 08 Reference | [Architecture decisions](08-reference/ARCHITECTURE_DECISIONS.md) · [Known limitations](08-reference/KNOWN_LIMITATIONS.md) · [Glossary](08-reference/GLOSSARY.md) |

## Status labels used

| Label | Meaning |
|---|---|
| **Implemented** | Present in code and wired into a reachable path |
| **Partial** | Present but incomplete, simulated, or dependent on infrastructure that is not provisioned by default |
| **Planned** | Described as a goal; not implemented |
| **Deprecated** | Still reachable but marked for removal |

## Source of truth

1. Source code (`backend/`, `frontend/`)
2. `openapi.json` (129 operations, regenerated 2026-11-16)
3. Alembic migrations (`backend/migrations/versions`, 20 revisions)
4. CI workflows (`.github/workflows`)
