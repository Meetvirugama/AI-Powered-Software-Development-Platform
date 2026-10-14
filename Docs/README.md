# Platform Documentation — Master Index

Welcome to the **AI-Powered Software Development Platform** documentation. This directory contains all architectural specifications, implementation plans, API contracts, security guidelines, and task boards across all three milestones of the project.

---

## 🗺️ Milestone Roadmaps

| Milestone | Document | Focus & Objectives | Status |
|---|---|---|---|
| **Week 1** | [Week 1 — Repository Intelligence Foundation](./week1.md) | GitHub App integration, shallow clone, tree-sitter AST parsing, symbol graph, pgvector indexing, hybrid RAG pipeline (vector + lexical + RRF + reranking), grounded chat API, and React 19 Workbench UI. | 🟢 **COMPLETE** (369 tests passing, 71.3% coverage) |
| **Week 2** | [Week 2 — Developer Intelligence Suite](./week2.md) | Four standalone developer-intelligence features: Code Explanation, Bug Detection, Framework-Aware Test Generation, and Standalone AI Code Review with strict schema validation and persistence. | 🔵 **ACTIVE** |
| **Week 3** | [Week 3 — Workflow Automation, GitHub Integration & Production Hardening](./week3.md) | End-to-end plan-to-PR workflow: Task planning, mandatory Human Approval Gate, isolated task workspace, policy-guarded tool routing, test execution, bounded repair loop (max 3), independent verification, and GitHub Draft PR creation. | ⚪ **UPCOMING** |

---

## 📚 Core Documentation Directory

| Document | Description | Primary Owner |
|---|---|---|
| [Daily Task Breakdown](./daily_tasks.md) | Master checklist tracking daily atomic tasks for all 10 team members. | All Leads |
| [Database Migrations Workflow](./db_migrations.md) | Alembic migration guides, current migration inventory (5 migrations), and table-to-migration map. | Om |
| [GitHub App Setup Guide](./github_app_setup.md) | Setup instructions for GitHub App registration, permissions, webhooks, and private key storage. | Parth |
| [Product Vision & Specification](./project_idea.md) | Foundational product thesis, architecture diagrams, user personas, and differentiation. | Meet |
| [Prompt Architecture](./prompt_architecture.md) | System/data separation rules, prompt-injection defense guidelines, and placeholder specifications. | Dev |
| [RAG Quality Benchmark](./rag_benchmark_results.md) | Grounded retrieval benchmark suite testing against sample multi-file codebases. | Keval |
| [Team Rules & Boundaries](./team_rules.md) | Directory ownership map, branch protection rules, anti-clash guidelines, and PR workflow. | All Leads |
| [Week 1 Security Report](./security/week1_security_report.md) | Comprehensive security audit covering multi-tenant isolation, prompt injection, and credential scrubbers. | Sukun |

---

## 🛠️ Engineering Documentation Suite (`Docs/engineering/`)

The [engineering/](./engineering/) directory contains deep-dive architectural specifications:

- [00. Dashboard](./engineering/00_dashboard.md) — High-level project health, sprint status, and feature checklist.
- [01. Project Overview](./engineering/01_project_overview.md) — Technical problem statement, objectives, and flow.
- [02. Requirements](./engineering/02_requirements.md) — Functional (FR) and non-functional (NFR) requirements matrix.
- [03. Features Overview](./engineering/03_features_overview.md) — Priority-ranked feature inventory with assigned owners.
- [04. User Roles & Permissions](./engineering/04_user_roles_permissions.md) — Multi-tenant access control and JWT authentication.
- [05. System Architecture](./engineering/05_system_architecture.md) — Component diagrams, module relationships, and data flows.
- [06. UML Diagrams](./engineering/06_uml_diagrams.md) — Activity, sequence, class, state, and component diagrams.
- [07. Database Documentation](./engineering/07_database_documentation.md) — PostgreSQL + pgvector schema, ER diagrams, and indexes.
- [08. API Documentation](./engineering/08_api_documentation.md) — REST API catalog, schemas, and error conventions.
- [09. Feature Documentation](./engineering/09_feature_documentation.md) — Technical designs for RAG, scanner, chunker, and chat.
- [10. Development Tasks](./engineering/10_development_tasks.md) — Master task boards for Week 1, Week 2, and Week 3.
- [11. Testing & QA](./engineering/11_testing_qa.md) — Test strategies, fixture suites, and coverage policies.
- [12. Deployment & DevOps](./engineering/12_deployment_devops.md) — Local setup, Docker Compose, and environment variables.
- [13. Architecture Decisions](./engineering/13_architecture_decisions.md) — Architecture Decision Records (ADR-001 through ADR-010).
- [14. Changelog](./engineering/14_changelog.md) — Chronological log of major codebase milestones.

---

## 👥 Team Ownership Matrix

| Member | Primary Ownership Area | Key Focus (Weeks 1–3) |
|---|---|---|
| **Meet** | Repository Context, RAG, Intelligence Pipelines | ContextBuilder, Hybrid RAG, TaskPlanner, Execution Lifecycle |
| **Dev** | AI Analysis Engines, Structured Schemas | Explanation, Bug Engine, Test Generation, AI Review, Verification |
| **Dhramraj** | Frontend UX, Workbench, Workflow UI | React 19 Workbench, Explorer, Code Inspection Drawers, Task Timeline |
| **Yug** | API Gateway, Backend Architecture | FastAPI Routing, Auth, Analysis Endpoints, Task Orchestration APIs |
| **Om** | Database, ORM Models, Migrations | PostgreSQL + pgvector schema, Alembic migrations, Analysis/Task Persistence |
| **Parth** | GitHub Ecosystem & Git Lifecycle | GitHub App, OAuth, Clone/Sync, Authorized Diffs, Branch/PR Publication |
| **Prit** | AST Parsing, Frameworks, Workspace Isolation | Tree-sitter AST, Symbol Extraction, Framework Detector, Workspace Manager |
| **Devu** | Static Analysis, Chunker, Tool Policy | SymbolChunker, Ruff/Bandit Scanner, Tool Router, Allowed Commands |
| **Sukun** | Security Architecture & Defense | Prompt-Injection Shields, Secret Scrubbing, Workspace Sandbox Policy |
| **Keval** | Quality Assurance & Acceptance Testing | Regression Test Suites, Quality Fixtures, End-to-End Acceptance Gates |
