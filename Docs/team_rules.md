# Team Rules, Ownership Boundaries & Anti-Clash Guidelines

These rules exist to prevent merge conflicts, duplicated work, broken interfaces, and wasted days. Every team member must read and follow this document before writing their first line of code.

---

## The Golden Rules (Apply to Everyone)

1. **You own your module. You do not touch anyone else's module without their knowledge.**
2. **Interfaces are sacred.** Once an interface is published to `main`, you cannot change it unilaterally — open a discussion first.
3. **Nothing goes to `main` without a PR.** Direct pushes to `main` are blocked. No exceptions.
4. **Broken `main` = team emergency.** If you break `main`, you fix it before anything else.
5. **If you depend on someone else's work, use mocks until the real implementation is merged.** Never block your own progress waiting on someone else.
6. **Every PR must have a description.** "Added stuff" is not a description. Explain what you changed and why.
7. **Talk before you refactor.** If you think someone else's code needs restructuring, open a discussion — don't silently reorganize it.
8. **Never put secrets in code.** API keys, passwords, tokens — all go in `.env` files, never committed.

---

## Directory Ownership Map

This is who owns which part of the codebase. **You do not create files in someone else's directory without their approval.**

```
project-root/
├── backend/
│   ├── app/
│   │   ├── api/              ← Yug (route handlers only)
│   │   ├── core/             ← Yug (settings, middleware, logging)
│   │   ├── models/           ← Om (SQLAlchemy models)
│   │   ├── schemas/          ← Yug + Dev (Pydantic schemas)
│   │   ├── services/         ← Module owner (e.g., auth → Yug, repo → Prit)
│   │   ├── repositories/     ← Om (database query layer)
│   │   ├── integrations/
│   │   │   └── github/       ← Parth
│   │   ├── workers/          ← Yug (job queue orchestration)
│   │   └── migrations/       ← Om (Alembic migrations ONLY)
│   ├── ai/
│   │   ├── llm/              ← Meet
│   │   ├── embeddings/       ← Meet
│   │   ├── retrieval/        ← Meet
│   │   ├── context/          ← Meet
│   │   ├── prompts/          ← Dev
│   │   └── schemas/          ← Dev
│   ├── scanner/              ← Prit
│   ├── indexer/              ← Divu
│   ├── sandbox/              ← Prit (Week 2+)
│   ├── agent/
│   │   ├── orchestrator/     ← Meet
│   │   ├── planner/          ← Meet + Dev
│   │   ├── tools/            ← Divu
│   │   ├── policy/           ← Sukun
│   │   └── memory/           ← Meet + Om
│   └── tests/                ← Keval (all test files)
├── frontend/
│   ├── src/
│   │   ├── components/       ← Dhramraj
│   │   ├── pages/            ← Dhramraj
│   │   ├── services/         ← Dhramraj (API client)
│   │   ├── hooks/            ← Dhramraj
│   │   ├── stores/           ← Dhramraj
│   │   └── types/            ← Dhramraj (mirrors backend schemas)
└── Docs/                     ← Everyone reads, Yug maintains
```

---

## Per-Member Ownership & Hard Boundaries

---

### 👤 Yug — Backend Lead

**You own:** FastAPI project skeleton, route handlers, API contracts, middleware, background job queue orchestration, error handling format.

**Your hard boundaries:**

| ✅ You do this | ❌ You do NOT do this |
|---------------|-----------------------|
| Write route handlers that call services | Write business logic inside route handlers |
| Define the API contract (URL, request/response schema) | Implement the AI logic (that's Meet + Dev) |
| Orchestrate the sync job flow | Write the actual scanner/indexer logic (that's Prit/Divu) |
| Define the standard error JSON format | Invent ad-hoc error formats in individual routes |
| Run the background worker queue | Implement what the worker does inside (delegate to module owner) |
| Merge PRs from others after review | Push directly to `main` |

**Interface you publish (others depend on this):**
- All REST API endpoints with their exact URL, method, request body, response schema, and error codes
- Publish this as an OpenAPI spec on Day 1. Dhramraj mocks against it immediately.

**Conflict prevention:**
- Any new API endpoint must be documented in the OpenAPI spec before implementation
- If Dhramraj or Keval files a bug against an API, you own the fix

---

### 👤 Om — Database Lead

**You own:** PostgreSQL schema, all Alembic migrations, all SQLAlchemy models, the database query (repository) layer.

**Your hard boundaries:**

| ✅ You do this | ❌ You do NOT do this |
|---------------|-----------------------|
| Create and run all Alembic migrations | Let anyone else create a migration file |
| Define all SQLAlchemy models | Allow anyone to write raw SQL outside the repository layer |
| Own the `app/repositories/` query layer | Write business logic in repositories (that belongs in services) |
| Enforce repository_id scoping on every query | Add application-layer logic to migrations |
| Add and tune all database indexes | Change the API contract (that's Yug) |
| Review any PR that touches a model or migration | Merge migrations that conflict with your schema |

**Critical rules:**
- **Only Om creates migration files.** If someone else needs a schema change, they open a GitHub issue describing what they need — Om creates the migration.
- **Migration naming convention:** `YYYYMMDD_HHMMSS_description.py` — always timestamped
- **Every migration must be reversible.** Every `upgrade()` must have a working `downgrade()`
- **Never drop a column in production without a two-step migration** (first add new column, migrate data, then drop old)

**Interface you publish (others depend on this):**
- Stable SQLAlchemy models that others import
- Stable repository functions (`get_chunks_by_repository`, `create_task`, etc.)
- Notify the team **24 hours in advance** before renaming or removing any model field

---

### 👤 Parth — GitHub Integration Lead

**You own:** GitHub App configuration, installation token management, all GitHub API calls, webhook processing, Git branch/commit/push/PR operations.

**Your hard boundaries:**

| ✅ You do this | ❌ You do NOT do this |
|---------------|-----------------------|
| All GitHub API calls go through your `GitHubService` class | Let anyone else call the GitHub API directly |
| Manage installation tokens in Redis | Store GitHub tokens in the database |
| Implement webhook signature verification | Skip HMAC verification for speed |
| Own `app/integrations/github/` entirely | Create files in `app/api/` (that's Yug) |
| Expose clean service methods to Yug | Return raw GitHub API responses to callers |
| Handle all GitHub error codes (401, 403, 404, 429) | Propagate raw GitHub errors to the frontend |

**Interface you publish (others depend on this):**
```python
class GitHubService:
    def list_repositories(installation_id) -> list[Repository]
    def clone_repository(owner, repo, branch, workspace_path) -> None
    def create_branch(owner, repo, branch_name, base_sha) -> str
    def push_branch(owner, repo, local_branch, remote_branch) -> None
    def create_pull_request(owner, repo, head, base, title, body) -> PullRequest
```
These method signatures are frozen once published. Anyone calling your service depends on them.

**Conflict prevention:**
- Yug calls your service — your service does NOT call Yug's routes
- Prit calls your clone method — you do not write file scanning logic
- Webhooks are processed by your worker — you emit standardized events that others consume

---

### 👤 Prit — Repository Engine Lead

**You own:** File walker, language detector, tree-sitter parser, AST symbol extractor, dependency graph builder, workspace manager (file read/write in sandbox).

**Your hard boundaries:**

| ✅ You do this | ❌ You do NOT do this |
|---------------|-----------------------|
| Own `backend/scanner/` entirely | Write chunking logic (that's Divu) |
| Produce stable `Symbol` and `SymbolEdge` data structures | Write embedding or vector search code (that's Meet) |
| Write the workspace file operations (read/write/patch) | Write database queries directly (use Om's repository layer) |
| Define the `Chunk`-ready symbol format Divu consumes | Decide what chunk size or overlap to use |
| Sandbox isolation and file operation security | Policy enforcement (that's Sukun) |
| Test your parser against fixture repositories | Write API routes (that's Yug) |

**Interface you publish (others depend on this):**
```python
@dataclass
class Symbol:
    id: UUID
    name: str
    kind: str           # "class" | "function" | "method" | "import" | "constant"
    file_id: UUID
    start_line: int
    end_line: int
    signature: str
    parent_id: UUID | None

@dataclass
class SymbolEdge:
    source_id: UUID
    target_id: UUID
    edge_type: str      # "calls" | "imports" | "extends" | "implements"
```
**Once Divu starts chunking against your symbol output, changing these fields requires coordinating with Divu first.**

**Critical rules:**
- The scanner must never raise an unhandled exception on a malformed file — catch, log, and skip
- Path traversal validation is YOUR responsibility — every file operation must be checked against the workspace root

---

### 👤 Divu — Indexing Lead

**You own:** Code chunking strategy, embedding queue, incremental indexing, tool definitions for the agent (read tools, write tools, test tool), tool router.

**Your hard boundaries:**

| ✅ You do this | ❌ You do NOT do this |
|---------------|-----------------------|
| Own `backend/indexer/` and `backend/agent/tools/` | Write the embedding model code (that's Meet) |
| Consume Prit's `Symbol` output → produce `Chunk` objects | Write AST parsing code (that's Prit) |
| Manage the embedding queue (push jobs, handle failures) | Write to pgvector directly (use Om's repository layer) |
| Define all agent tool schemas and the tool router | Execute tools without calling the policy engine first |
| Build the static review pipeline (secret scan, lint, etc.) | Write the LLM review logic (that's Dev) |
| Build the blast radius engine | Write route handlers (that's Yug) |

**Interface you publish (others depend on this):**
```python
# Tool schema — every tool must match this
class ToolDefinition:
    name: str
    description: str
    parameters: dict    # JSON Schema

# Tool router — Meet calls this
class ToolRouter:
    def route(request: ToolRequest, agent_state: AgentState) -> ToolResult
```
The tool router is the gatekeeper. Meet calls it; Divu implements it. Sukun's PolicyEngine is called inside the router — Divu does not bypass it.

**Critical rules:**
- Every tool call in the router MUST call `PolicyEngine.check()` before execution
- Tool output must be sanitized (secret scan + truncation) before returning to the agent
- Never add a new tool without a corresponding policy rule from Sukun

---

### 👤 Meet — AI/ML + RAG Lead

**You own:** LLM Gateway, embedding service, vector retrieval, lexical retrieval, RRF fusion, reranker, context builder, agent orchestrator, ReAct execution loop, memory extraction.

**Your hard boundaries:**

| ✅ You do this | ❌ You do NOT do this |
|---------------|-----------------------|
| Own `backend/ai/` and `backend/agent/orchestrator/` | Write prompt templates (that's Dev) |
| Implement the LLM Gateway (one entry point for all LLM calls) | Call LLM APIs directly from other modules — route through your gateway |
| Implement hybrid retrieval (vector + lexical + RRF + rerank) | Write database schema or migrations (that's Om) |
| Build the agent orchestrator and FSM | Write tool implementations (that's Divu) |
| Implement memory extraction from agent runs | Write security/policy checks (that's Sukun) |
| Define `AgentContext` and `AgentBudget` | Change API routes (that's Yug) |

**Interface you publish (others depend on this):**
```python
class LLMGateway:
    async def generate(request: LLMRequest, schema: BaseModel) -> LLMResponse

class RAGPipeline:
    async def retrieve(query: str, repository_id: UUID, top_k: int) -> list[CodeChunk]
    async def chat(question: str, repository_id: UUID, history: list) -> RepositoryAnswer

class AgentOrchestrator:
    async def start(task: Task) -> AgentRun
    async def pause(run_id: UUID) -> None
    async def resume(run_id: UUID) -> None
    async def cancel(run_id: UUID) -> None
```

**Critical rules:**
- The LLM Gateway is the ONLY place in the codebase that calls the LLM API. No one else imports the LLM SDK directly.
- Every LLM call must log: model, input_tokens, output_tokens, latency, success/failure
- The orchestrator state machine must validate every transition — invalid transitions raise an exception, they do not silently succeed

---

### 👤 Dev — AI Quality Lead

**You own:** All prompt templates, output validation schemas, grounding validation, AI error handling, independent verifier, LLM code review engine, PR summary generation, AI quality benchmarks.

**Your hard boundaries:**

| ✅ You do this | ❌ You do NOT do this |
|---------------|-----------------------|
| Own `backend/ai/prompts/` and `backend/ai/schemas/` | Write the retrieval logic (that's Meet) |
| Define Pydantic schemas for all LLM inputs/outputs | Write database queries (that's Om) |
| Build the output validation + repair loop | Implement the agent FSM (that's Meet) |
| Build the independent verifier (separate LLM call) | Share context or reasoning with the coding agent in the verifier |
| Build the LLM code review engine | Write the static review pipeline (that's Divu) |
| Write prompt injection test cases | Change the tool router (that's Divu) |

**Critical rules:**
- **The independent verifier must be a completely separate LLM call.** It must not receive any of the coding agent's intermediate outputs, chain-of-thought, or reasoning. It sees only: the original task, the final code diff, and the test results.
- **Prompt templates must be version-controlled.** Every change to a prompt template must include a test showing the output did not regress.
- **Repository content is always DATA, never SYSTEM instructions.** Every prompt you write must enforce this separation.

**Interface you publish (others depend on this):**
```python
class OutputValidator:
    def validate(raw_output: str, schema: BaseModel) -> tuple[BaseModel, bool]
    def repair(raw_output: str, schema: BaseModel) -> BaseModel

class IndependentVerifier:
    async def verify(task: Task, diff: str, test_results: TestResult) -> VerificationResult
```

---

### 👤 Dhramraj — Frontend Lead

**You own:** All frontend code — every React component, every page, every API service call, every store, every hook.

**Your hard boundaries:**

| ✅ You do this | ❌ You do NOT do this |
|---------------|-----------------------|
| Own `frontend/src/` entirely | Write any backend code |
| Build against the API contract Yug publishes | Call the database or GitHub API directly from the frontend |
| Use MSW or mock data when the backend isn't ready | Wait for backend completion before starting frontend work |
| Define TypeScript types that mirror Yug's Pydantic schemas | Define your own types that diverge from backend schemas |
| Report API bugs to Yug via GitHub Issues | Fix backend code yourself |
| Implement loading states and error states on every async call | Display raw API error objects to the user |

**Critical rules:**
- **Never store JWT tokens in localStorage.** Tokens must live in httpOnly cookies managed by the backend.
- **Never render user-generated or repository content as raw HTML.** Always escape. This prevents XSS.
- **All API calls go through one central API client** (`services/api.ts`) — not scattered `fetch()` calls throughout the codebase.
- **Match the Pydantic schema exactly.** When Yug changes a response schema, Dhramraj must update the TypeScript type. These should be in sync.

**Interface you consume (your dependency):**
- Yug's OpenAPI spec — build the TypeScript client from this
- Never assume an API field exists without checking the spec

---

### 👤 Keval — Testing Lead

**You own:** Test infrastructure setup, all test fixtures, integration tests, E2E tests, test coverage reports, and the CI pipeline test configuration.

**Your hard boundaries:**

| ✅ You do this | ❌ You do NOT do this |
|---------------|-----------------------|
| Own `backend/tests/` entirely | Write production code in the `backend/app/` or `backend/ai/` directories |
| Write tests as soon as a feature is merged | Batch all tests to Day 7 |
| Use mocks for external services (GitHub, LLM, Embedding) | Call real external APIs in tests |
| Own the test fixture repositories | Add test files inside other people's module directories |
| Report test failures as GitHub Issues against the module owner | Fix other people's production bugs yourself |
| Define the minimum coverage thresholds | Merge code that drops below coverage thresholds |

**Critical rules:**
- **Test as you go.** When a module is marked complete and merged, Keval writes or reviews tests for it within 24 hours.
- **Test database is isolated.** Every test run uses a fresh test database — never the development database.
- **All external API calls must be mocked.** Use `responses` (Python) or MSW (JS) — never call GitHub, OpenAI, or any other external service in automated tests.
- **Test fixtures go in `backend/tests/fixtures/`.** Small Python, JS, and TypeScript repos used for scanner and RAG tests. These are shared — do not modify them without notifying the team.

**Failure protocol:**
- When a test fails in CI, file a GitHub Issue tagged with the module owner within 4 hours
- Include: failing test name, error message, reproduction steps
- Do not fix the production code yourself unless it's clearly in the test setup

---

### 👤 Sukun — Security + Observability

**You own:** Secret management baseline, authentication security review, repository isolation tests, secret scanner for indexed code, input validation tests, API rate limiting, security response headers, policy engine implementation, sandbox security rules, prompt injection defense tests.

**Your hard boundaries:**

| ✅ You do this | ❌ You do NOT do this |
|---------------|-----------------------|
| Own `backend/agent/policy/` entirely | Write business logic in the policy engine |
| Define the `PolicyEngine` interface and decisions | Call the LLM or database directly from the policy engine |
| Write security tests that run in CI | Add security checks only at the end of the project |
| Scan every PR for committed secrets (automated check) | Block PRs for non-security reasons |
| Write the allowed-command list for the sandbox | Configure the Docker/gVisor runtime (that's Prit) |
| Report security vulnerabilities via a private channel | Discuss vulnerability details in public Slack/Discord |

**Critical rules:**
- **The policy engine is called on every tool request — no bypass.** If Divu's ToolRouter has a code path that skips `PolicyEngine.check()`, that is a critical bug.
- **Secret detection runs on EVERY chunk before it enters the embedding pipeline.** This is non-negotiable. The detection runs in Divu's indexer, but Sukun defines the patterns and reviews the implementation.
- **Prompt injection tests are part of CI.** They run on every merge — not just at release.
- **Rate limiting is applied before authentication checks.** A request that is rate-limited never reaches the auth layer.

**Interface you publish (others depend on this):**
```python
class PolicyEngine:
    def check(
        tool: str,
        agent_state: AgentState,
        context: PolicyContext,
    ) -> PolicyDecision  # ALLOW | ASK | DENY
```
Divu's ToolRouter calls this. The interface must never change without coordinating with Divu.

---

## Interface Contracts & Publish Protocol

When you finish a module interface that other people depend on, follow this protocol:

1. **Write the interface** (Python abstract class / TypeScript interface / OpenAPI spec)
2. **Create a stub implementation** that returns hardcoded fixtures — so dependents can build against it immediately
3. **Open a PR titled `[INTERFACE] ModuleName API v1`** — this signals that the contract is now published
4. **Once this PR merges, the interface is frozen.** Changes require a new PR titled `[INTERFACE CHANGE] ModuleName` with justification
5. **Notify in the team channel** when an interface PR merges

---

## Branch and Git Rules

```
main                    ← Protected. PR-only. Passing CI required.
develop                 ← Integration branch. PR from your feature branch.
meet/skeleton                  ← Your working branch. Format: {owner}/{description}
om/db-schema
prit/scanner
```

**Branch naming format:** `{owner}/{description}` (Do not use week-wise branch names)
- Example: `meet/react-loop`
- Example: `om/user-model`

**PR rules:**
- PR title must reference the task ID: `[W1-08] AST Symbol Extraction — tree-sitter integration`
- PR description must include: what changed, why, how to test it, and any interface changes
- PRs into `main` require 1 approval from the module owner and 1 from Yug (as backend lead) or Dhramraj (as frontend lead)
- PRs must not break any existing CI tests

**Commit message format:**
```
feat(scanner): extract class and function symbols using tree-sitter

- Implements Symbol and SymbolEdge data classes
- Handles Python, TypeScript, JavaScript
- Skips binary files and files > 1MB
- Returns stable output for Divu's chunker

Task: W1-08
```

---

## Communication Rules

**When to block on someone else:**
- If you are blocked because someone's code isn't ready: use a mock, keep moving, and file a GitHub Issue tagging them
- Do not wait more than 4 hours without flagging the blockage in the team channel

**When to discuss before coding:**
- You're about to change a published interface → discuss first, always
- You think another person's module needs restructuring → open a GitHub Discussion
- You need a database schema change → create a GitHub Issue for Om with full requirements

**Daily sync (10 minutes):**
- What did I merge yesterday?
- What am I doing today?
- Am I blocked on anyone?

**GitHub Issues vs Slack:**
- Bugs, interface changes, schema requests → GitHub Issues (trackable)
- Quick questions, clarifications → Slack/Discord
- Never make a significant decision in Slack alone — document it as a GitHub Issue or PR comment

---

## Dependency & Integration Rules

These rules prevent the most common integration failures.

### Rule 1 — Consume interfaces, not implementations

```python
# ✅ Correct — depend on the abstract interface
from app.integrations.github.base import GitHubServiceBase

# ❌ Wrong — depend on the concrete class directly
from app.integrations.github.service import GitHubService
```

When the implementation changes, your code shouldn't break.

### Rule 2 — Publish your interface before your implementation

On Day 1 of any week, every person should have their **interface stub** published. The implementation fills in later. This lets everyone work in parallel.

### Rule 3 — Shared database tables have one writer

For any database table, only one person's code performs `INSERT`, `UPDATE`, and `DELETE`. Others may `SELECT`.

| Table | Writer | Readers |
|-------|--------|---------|
| `users` | Yug (auth flow) | Everyone |
| `repositories` | Parth/Yug | Everyone |
| `repository_files` | Prit (scanner) | Om, Divu, Meet |
| `code_symbols` | Prit (scanner) | Divu, Meet |
| `code_chunks` | Divu (indexer) | Meet, Om |
| `memory_entries` | Meet (extractor) | Meet, Dhramraj |
| `tasks` | Yug (API) | Everyone |
| `agent_runs` | Meet (orchestrator) | Yug, Dhramraj |
| `agent_actions` | Meet (orchestrator) | Keval, Sukun |
| `review_findings` | Divu (static) + Dev (LLM) | Yug, Dhramraj |
| `pull_requests` | Parth | Yug, Dhramraj |

### Rule 4 — Config lives in one place

All configuration (database URL, Redis URL, API keys, feature flags) lives in `app/core/config.py` (backend) and `.env` files. No hardcoded values anywhere else.

### Rule 5 — Logging is structured

Every log statement must be structured (JSON-compatible), not `print()`:
```python
# ✅ Correct
logger.info("chunk_embedded", extra={"chunk_id": str(chunk.id), "repo_id": str(repo.id)})

# ❌ Wrong
print(f"embedded chunk {chunk.id}")
```

All logs must include a `request_id` or `task_id` for correlation.

---

## Week-by-Week Conflict Prevention Focus

### Week 1 — Interface Freeze Day = Day 2

By end of Day 2, these interfaces must be published and frozen:
- **Yug:** OpenAPI spec with all Week 1 endpoints
- **Om:** SQLAlchemy models for users, repositories, code_chunks, memory_entries
- **Parth:** `GitHubService` method signatures
- **Prit:** `Symbol` and `SymbolEdge` dataclass definitions
- **Meet:** `LLMGateway.generate()` and `EmbeddingService.embed()` signatures
- **Dev:** `RepositoryAnswer` and `SourceReference` Pydantic schemas

Anyone building against these after Day 2 can trust they won't change without notice.

### Week 2 — Agent Boundary Rules

In Week 2, the agent orchestrator, tool router, and policy engine interact heavily. These rules prevent chaos:

- **The tool router (Divu) is the only caller of the policy engine (Sukun).** The orchestrator (Meet) does not call the policy engine directly.
- **The orchestrator (Meet) is the only caller of the tool router (Divu).** No other module calls tools directly.
- **Only the orchestrator (Meet) transitions agent state.** No other module changes `agent_state`.
- **Only Om's repository layer writes to `agent_runs` and `agent_actions`.** The orchestrator calls Om's repository functions — it does not write SQL directly.

```
Meet (Orchestrator) → Divu (ToolRouter) → Sukun (PolicyEngine)
                                        → Prit (Workspace)
                                        → Sandbox
```

### Week 3 — Review and PR Boundary Rules

- **The blast radius engine (Divu) runs before LLM review (Dev).** Dev's review prompt receives blast radius context as input.
- **Only Parth creates commits and pushes branches.** Meet's orchestrator calls `GitBranchService.commit()` — it does not run `git` commands directly.
- **The PR is created after human approval.** The orchestrator must reach `WAITING_PUSH_APPROVAL` state and receive explicit user confirmation before Parth's push method is called.
- **Review findings (Divu static + Dev LLM) both write to `review_findings`.** Use `reviewer_type: "static" | "llm"` to distinguish them. No overlap or duplication.

---

## What Happens When Rules Are Broken

| Violation | Consequence |
|-----------|-------------|
| Direct push to `main` | Revert immediately, PR required |
| Migration created by non-Om | Deleted, Om rewrites it |
| LLM called outside Meet's gateway | PR blocked until refactored |
| Test dropped below coverage threshold | PR blocked |
| Secret committed to git | Rotate the secret immediately, scrub git history |
| Interface changed without notice | Revert change, open a discussion, re-agree |
| Bypassing policy engine in tool router | Critical bug, fix before any other work |

These are not punishments — they're guardrails that keep the team moving fast without breaking each other's work.

---

## Quick Reference Card

Print this and keep it visible.

```
BEFORE WRITING CODE:
□ Does this touch another person's directory? → Ask first
□ Am I changing a published interface? → Discussion first
□ Do I depend on something not merged yet? → Use a mock

BEFORE OPENING A PR:
□ CI passes?
□ Coverage ≥ threshold?
□ No secrets in code?
□ PR description complete?
□ Interface change documented?

WHEN BLOCKED:
□ Use a mock and keep going
□ File a GitHub Issue tagging the blocker
□ Flag in team channel after 4 hours

COMMUNICATION:
□ Bugs / schema changes → GitHub Issues
□ Quick questions → Slack
□ Architecture decisions → GitHub Discussions + documented in PR
```
