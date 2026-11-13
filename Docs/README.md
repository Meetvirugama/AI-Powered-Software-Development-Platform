# Platform Documentation — Master Index

Welcome to the **AI-Powered Software Development Platform** documentation. This directory contains all architectural specifications, implementation plans, API contracts, security guidelines, and task boards across all three milestones of the project.

---

## 🗺️ Milestone Roadmaps

| Milestone | Document | Focus & Objectives | Status |
|---|---|---|---|
| **Week 1** | [Week 1 — Repository Intelligence Foundation](./week1.md) | GitHub App integration, shallow clone, tree-sitter AST parsing, symbol graph, pgvector indexing, hybrid RAG pipeline (vector + lexical + RRF + reranking), grounded chat API, and React 19 Workbench UI. | 🟢 **COMPLETE** (369 tests passing, 71.3% coverage) |
| **Week 2** | [Week 2 — Developer Intelligence Suite](./week2.md) | Four standalone developer-intelligence features: Code Explanation, Bug Detection, Framework-Aware Test Generation, and Standalone AI Code Review with strict schema validation and persistence. | 🟢 **COMPLETE** (100% test pass, verified schemas) |
| **Week 3** | [Week 3 — Workflow Automation, GitHub Integration & Production Hardening](./week3.md) | End-to-end plan-to-PR workflow: Task planning, mandatory Human Approval Gate, isolated task workspace, policy-guarded tool routing, test execution, bounded repair loop (max 3), independent verification, and GitHub Draft PR creation. | 🟢 **COMPLETE** (17-step autonomous workflow verified) |
| **Post-Week 3** | [Retrieval](./retrieval/README.md), [Agentic Chat](./agentic-chat/README.md), [Test Generation](./test-generation/README.md), & [Code Review Intelligence](./code-review/README.md) | Enterprise hardening & advanced intelligence: Timing-safe JWT/OAuth auth (#181), durable webhook event worker (#182), multi-stage hybrid retrieval (#187), bounded agentic chat (#188), execution-verified test generation (#193), and production AI code review with inline GitHub PR reviews, precision gating, ESLint/Biome analysis, and feedback lifecycle (#194). | 🟢 **COMPLETE** (All suites passing, 100% verified) |
| **P0 Security** | [Secure Sandbox Execution Architecture](./security/sandbox/README.md) | Production-grade secure sandbox execution architecture for untrusted GitHub repositories: SandboxBackend abstraction, LocalSubprocessBackend (dev-only), ContainerBackend (Docker + gVisor `runsc`), dedicated internal Runner Service, Two-Phase Execution (controlled install vs offline tests with `--network=none`), resource bounding (2 vCPU, 4GB RAM, 512 PIDs, read-only rootfs), and 12-scenario attack verification (#200 / F20). | 🟢 **COMPLETE** (142 tests passing, 100% verified) |

---

## 📚 Core Documentation Directory

| Document | Description | Primary Owner |
|---|---|---|
| [Daily Task Breakdown](./daily_tasks.md) | Master checklist tracking daily atomic tasks for all 10 team members. | All Leads |
| [Database Migrations Workflow](./db_migrations.md) | Alembic migration guides, current migration inventory (12 migrations), and table-to-migration map. | Om |
| [Multi-Stage Code Retrieval Engine](./retrieval/README.md) | 7-step hybrid retrieval architecture, adaptive HNSW profiles, lexical code FTS, graph expansion, Redis cache, and benchmarks. | Meet |
| [Bounded Agentic Repository Chat](./agentic-chat/README.md) | Multi-turn repository investigation loop, tool registry, execution policy, budget control, and UI integration. | Meet |
| [Execution-Verified Test Generation](./test-generation/README.md) | 5-stage verification pipeline, 3-run stability, runtime coverage delta & attribution, iterative loop, and Vitest support. | Dev & Meet |
| [AI-Powered Code Review Intelligence](./code-review/README.md) | Inline GitHub PR review comments, precision quality gate, ESLint/Biome static analysis, multi-commit lifecycle tracking, and developer feedback loop. | Meet |
| [Autonomous Code Synthesis & Durable Execution](./autonomous-execution/README.md) | Search/replace edit blocks, 7-stage validation filter chain, bounded self-refinement, plan-bound security, DBOS durable steps, and HTTP 202 status tracking. | Meet |
| [GitHub App Setup Guide](./github_app_setup.md) | Setup instructions for GitHub App registration, permissions, webhooks, and private key storage. | Parth |
| [Product Vision & Specification](./project_idea.md) | Foundational product thesis, architecture diagrams, user personas, and differentiation. | Meet |
| [Prompt Architecture](./prompt_architecture.md) | System/data separation rules, prompt-injection defense guidelines, and placeholder specifications. | Dev |
| [RAG Quality Benchmark](./rag_benchmark_results.md) | Grounded retrieval benchmark suite testing against sample multi-file codebases. | Keval |
| [Team Rules & Boundaries](./team_rules.md) | Directory ownership map, branch protection rules, anti-clash guidelines, and PR workflow. | All Leads |
| [Week 1 Security Report](./security/week1_security_report.md) | Comprehensive security audit covering multi-tenant isolation, prompt injection, and credential scrubbers. | Sukun |
| [Week 3 Threat Model & Security Report](./security/week3_security_report.md) | Attack matrix, sandbox boundary isolation, secret redaction, and release checklist. | Sukun |

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
- [10. Development Tasks](./engineering/10_development_tasks.md) — Master task boards for Week 1, Week 2, Week 3, and Post-Week 3.
- [11. Testing & QA](./engineering/11_testing_qa.md) — Test strategies, fixture suites, and coverage policies.
- [12. Deployment & DevOps](./engineering/12_deployment_devops.md) — Local setup, Docker Compose, and environment variables.
- [13. Architecture Decisions](./engineering/13_architecture_decisions.md) — Architecture Decision Records (ADR-001 through ADR-010).
- [14. Changelog](./engineering/14_changelog.md) — Chronological log of major codebase milestones.
- [15. Authentication & Authorization Security Audit](./engineering/15_authentication_authorization_audit.md) — Timing-safe HMAC, secret validation, and token rotation audit.
- [16. Issue #181 Implementation Plan](./engineering/16_issue181_implementation_plan.md) — Implementation blueprint for JWT and OAuth hardening.
- [17. GitHub Webhook Automation Design](./engineering/17_github_webhook_automation_design.md) — Durable webhook queue, lease worker, and event state machine.
- [17. JWT & OAuth Hardening Architecture](./engineering/17_jwt_oauth_hardening.md) — Comprehensive reference for token rotation and security contracts.
- [18. Repository Deletion Audit](./engineering/18_repository_deletion_audit.md) — Cascade deletion and audit trails.
- [19. Background Worker Architecture](./engineering/19_background_worker_architecture.md) — Reliable background job processing.
- [20. DBOS Transact Evaluation](./engineering/20_dbos_transact_evaluation.md) — Durable execution analysis.
- [21. Provider Token Budget Calibration](./engineering/21_provider_token_budget_calibration.md) — Unified Token & Model Budget Calibration (Issue #189).
- [22. Security Analysis Expansion](./engineering/22_security_analysis_expansion.md) — Broader Security Analysis & Multi-Scanner Architecture (Issue #191).
- [23. Tool Permission Approval & MCP Elicitation](./engineering/23_tool_approval_and_mcp_elicitation.md) — Tool Permission Approval Gate and MCP Elicitation (Issue #199).
- [24. Analysis History Evaluation Export](./engineering/24_analysis_history_evaluation_export.md) — Evaluation Dataset Export from Analysis History (Issue #195).
- [25. GitHub Source Browsing & Consolidation](./engineering/25_github_source_browsing_and_consolidation.md) — Live remote issue browsing, PR demuxing, and duplicate execution surface consolidation (Issue #196).
- [26. Project Memory Entries & MCP Resources](./engineering/26_project_memory_entries.md) — Episodic Project Memory, Semantic Search & MCP Resources (Issue #217 / F36).
- [27. Branch, Commit, Push, and Draft PR Publication](./engineering/27_branch_commit_push_draft_pr_publication.md) — Host-Side Git Operations & Credential Isolation Architecture (Issue #207 / F26).
- [28. Bounded Self-Repair Loop & Anti-Reward Hacking](./engineering/28_bounded_self_repair_loop.md) — LLM-Driven Targeted Repair Synthesis, Reflexion Memory & Anti-Reward Hacking Architecture (Issue #205 / F24).

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
