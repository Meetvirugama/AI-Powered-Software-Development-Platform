# 04 — Feature Parity Audit (Frontend ↔ Backend)

Feature IDs (`FEAT-##`) are used across 03, 10 and 11. Status summary per feature is in 03 §5. This document specifies **what is missing on each side and how to implement it**, then which features should be merged or removed.

---

## 1. Feature catalogue

| ID | Feature | Frontend location | Backend location |
|---|---|---|---|
| FEAT-01 | Authentication | `pages/Login.tsx`, `pages/AuthCallback.tsx`, `hooks/useAuth.ts`, `stores/useAuthStore.ts` | `api/v1/auth.py`, `core/auth.py`, `core/security.py` |
| FEAT-02 | Repository discovery & connect | `pages/Repositories.tsx`, `services/repositoryDiscovery.ts`, `hooks/useAvailableRepositories.ts`, `hooks/useConnectRepository.ts` | `api/v1/github.py` |
| FEAT-03 | Sync & indexing progress | `components/explorer/SyncProgressIndicator.tsx`, `RepositorySyncCard.tsx`, `hooks/useRealtimeRepositories.ts` | `api/v1/repositories.py` (`/sync`), `services/sync_worker.py`, `indexer/*` |
| FEAT-04 | File explorer / code viewer | `pages/RepositoryDetail.tsx`, `components/explorer/{FileTree,CodeViewer,FilePreviewModal}.tsx` | `api/v1/repositories.py` (`/files*`) |
| FEAT-05 | Repository chat | `pages/RepositoryChat.tsx`, `hooks/useRepositoryChat.ts`, `services/chat.ts` | `api/v1/chat.py`, `ai/pipeline.py`, `ai/agent/*` |
| FEAT-06 | Explain studio | `pages/RepositoryExplainStudio.tsx`, `components/explorer/ExplanationResultView.tsx` | `api/v1/analysis/explain.py`, `services/explanation_orchestrator.py` |
| FEAT-07 | Bug studio (+ create issue) | `pages/RepositoryBugStudio.tsx`, `components/explorer/{BugScannerView,CreateIssueModal}.tsx` | `api/v1/analysis/bugs.py`, `api/v1/issues.py` |
| FEAT-08 | Test studio | `pages/RepositoryTestStudio.tsx`, `components/explorer/TestGenerationView.tsx` | `api/v1/analysis/tests.py` |
| FEAT-09 | Review studio | `pages/RepositoryReviewStudio.tsx`, `components/explorer/CodeReviewView.tsx` | `api/v1/analysis/review.py`, `services/review_*` |
| FEAT-10 | Analysis history | `components/explorer/AnalysisHistoryDrawer.tsx` | `api/v1/analysis/history.py` |
| FEAT-11 | Project memory | `components/explorer/ProjectMemoryPanel.tsx`, `services/memory.ts` | `api/v1/memories.py`, `services/memory_service.py` |
| FEAT-12 | Agent tasks | `pages/{Tasks,CreateTask,TaskDetail,RepositoryTaskStudio}.tsx`, `components/tasks/*`, `components/taskStudio/TaskPhasePanels.tsx` | `api/v1/tasks.py`, `services/task_execution_orchestrator.py`, `sandbox/*` |
| FEAT-13 | Issue import / create | `components/tasks/ImportIssueForm.tsx`, `CreateIssueModal.tsx` | `api/v1/issues.py` |
| FEAT-14 | Tools & MCP admin | `pages/ToolsIntegrationsAdminPage.tsx` | `api/v1/mcp_registry.py`, `app/mcp/server.py` |
| FEAT-15 | Webhook console & repository automation | — | `api/v1/github.py` (`/github/events*`, `/automation`) |
| FEAT-16 | Code search & symbol browser | — (Command palette subtitle promises "symbols") | `api/v1/repositories.py` (`/search`, `/symbols`, `/dependencies`*) |
| FEAT-17 | Source browser (live GitHub tree, commits, PRs, diffs) | — | `integrations/github/routes.py` (`/source/*`) |
| FEAT-18 | Tool approvals & MCP elicitations | `components/tasks/ApprovalHistoryPanel.tsx`, `services/tasks.ts` | `api/v1/tasks.py` (`/tool-approvals*`, `/mcp/elicitations*`) |
| FEAT-19 | Real-time events | `realtime/*`, `layouts/AppLayout.tsx` | `api/v1/events.py`, `services/sse_redis_streams.py` |
| FEAT-20 | Autonomous workflow | `services/tasks.ts` (`/run-workflow`, `/workflow-status`) | `api/v1/tasks.py`, `ai/workflows/*` |
| FEAT-21 | Repository-scoped task routes | — | `api/v1/tasks.py` `repo_tasks_router` |
| FEAT-22 | Health / readiness | — | `api/v1/health.py` |

\* `/dependencies` **is** called (`services/repositories.ts` L130).

---

## 2. Frontend features missing (or faked) in the backend — task spec §5.1

### FP-FE-01 — Tools & MCP admin uses hard-coded data (FEAT-14, ISS-033, ISS-003)
1. **Feature:** Manage MCP servers, inspect tool schemas, toggle approval gates.
2. **Frontend location:** `frontend/src/pages/ToolsIntegrationsAdminPage.tsx` L25 (`INITIAL_SERVERS`), L89 (`useState(INITIAL_SERVERS)`); route `/app/tools` (`App.tsx`), command palette entry (`components/studios/CommandPalette.tsx` L145).
3. **Expected behaviour:** Persistent, role-protected registry; real health status; policy changes affect task tool approvals.
4. **Missing backend functionality:** Persistence, RBAC, real connectivity checks, coupling of policy to `agent/tools/router.py`.
5. **Required endpoints:** keep `GET/POST /mcp/servers`, `POST /mcp/servers/{id}/ping`, `PATCH /mcp/servers/{id}/toggle`, `PATCH /mcp/servers/{id}/tools/{tool}/policy`; add `DELETE /mcp/servers/{id}`.
6. **Service logic:** `app/services/mcp_registry_service.py` (new): CRUD, health probe (with ISS-022 SSRF rules), tool discovery via MCP `tools/list` for remote servers, policy lookups with caching for the tool router.
7. **Database changes:** new tables `mcp_servers(id, name, transport, endpoint_or_command, enabled, status, protocol_version, last_latency_ms, last_checked_at, created_by, created_at)` and `mcp_tool_policies(server_id FK, tool_name, requires_approval, risk_tier, updated_by, updated_at, PK(server_id, tool_name))`.
8. **AI integration:** `agent/tools/router.py` reads `requires_approval` from `mcp_tool_policies` (fallback to `DEFAULT_MCP_TOOLS`).
9. **Implementation steps:** migration → repository → service → rewrite `mcp_registry.py` routes with `require_role(ADMIN)` for mutations → `frontend/src/services/mcp.ts` + `hooks/useMcpServers.ts` → bind page; hide mutation controls for non-admins (role from `/auth/me`).
10. **Acceptance criteria:** reload preserves state; viewer/developer get 403 on mutations; toggling `requiresApproval` on a tool changes whether `/tasks/{id}/tools/{name}` requires approval.

*Alternative (product decision):* remove the page and the API until MCP is a real product capability (DC-29 note). Do not keep a fake admin screen.

### FP-FE-02 — Chat UI expects streaming events that never arrive (FEAT-05, ISS-015)
1. **Feature:** Token-by-token chat.
2. **Location:** `frontend/src/realtime/events.ts` declares `chat.stream.started/chunk/completed/error`, `chat.token`; no consumer; `RepositoryChat.tsx` waits on HTTP.
3. **Expected:** Visible incremental answer, cancel button that stops generation.
4. **Missing backend:** a real streaming endpoint.
5. **Endpoint:** `POST /api/v1/repositories/{id}/chat/stream` (`text/event-stream`; events `started`, `token`, `sources`, `completed`, `error`).
6. **Service:** `RAGPipeline.chat_stream()` using `LLMGateway.generate_stream` (fallback only before first chunk), grounding on final buffer.
7. **DB:** persist final message (FP-FE-03).
8. **AI:** streaming in both Gemini and Groq providers (exists, unused).
9. **Steps:** backend endpoint → `services/chat.ts` `streamRepositoryQuestion()` using `fetch` + `ReadableStream` (EventSource cannot POST) → `useRepositoryChat` appends tokens → abort via `AbortController`.
10. **Acceptance:** first token rendered before completion; abort stops server generation (disconnect detected via `request.is_disconnected()`).

### FP-FE-03 — Chat history cannot persist (FEAT-05, ISS-016)
1–3. Chat page keeps messages in React state; users expect conversations to survive reloads and to be listed.
4. **Missing backend:** chat session storage.
5. **Endpoints:** `GET/POST /repositories/{id}/chat/sessions`, `GET /chat/sessions/{sid}/messages`, `DELETE /chat/sessions/{sid}`; chat endpoints accept `session_id`.
6. **Service:** `ChatSessionService` (load last N messages within token budget server-side; ignore client-supplied assistant turns).
7. **DB:** `chat_sessions`, `chat_messages` (see ISS-016), index `(session_id, created_at)`.
8. **AI:** `RAGPipeline.chat(history=server_history)`.
9. **Steps:** migration → repository/service → routes → FE session list sidebar in `RepositoryChat.tsx` → hook changes.
10. **Acceptance:** reload restores the selected session; history is not accepted from the client.

### FP-FE-04 — Repository list pagination shim (FEAT-02/03, ISS-024)
Frontend models `PaginatedRepositoryResponse` and slices locally (`services/repositories.ts` L39–57). **Backend:** add `page`, `page_size`, `q`, `sync_status` query params to `GET /repositories` and return `{items,total,page,page_size}`; index `repositories(user_id, created_at DESC)`. **FE:** delete the shim. **Acceptance:** payload bounded; dashboard polling cost independent of repository count.

### FP-FE-05 — Publication panel reads fields the backend never returns (FEAT-12, ISS-017)
`PublicationPanel.tsx` L144–160 uses `res.summary`; backend `TaskPullRequestResponse` has no `summary`. **Decide:** either add `summary` (PR body excerpt / verification summary) to the response, or remove it from the UI. Generate types from OpenAPI (OPT-03). **Acceptance:** no FE field typed as present that the backend never sends.

### FP-FE-06 — Command palette promises symbol browsing (FEAT-16)
`CommandPalette.tsx` L68–69 ("Browse repository file tree and symbols") while no UI calls `/symbols`. Covered by FP-BE-02 below.

*No frontend action calls a non-existent endpoint, and no other screen uses hard-coded business data (scan for mock/dummy/placeholder/simulated strings outside tests and mocks returned only the Tools page).*

---

## 3. Backend features missing in the frontend — task spec §5.2

### FP-BE-01 — Webhook event console & repository automation (FEAT-15)
1. **Backend:** `GET /github/events` (filters: status, event_type, repository_id; scoped to user's repos/installations), `GET /github/events/{id}`, `POST /github/events/{id}/replay`, `GET/PATCH /github/repositories/{github_repo_id}/automation` (`auto_sync_enabled`, `pr_review_enabled`).
2. **Existing functionality:** durable webhook processing with replay, push-to-sync, automatic PR review.
3. **Missing frontend:** settings toggles and an events table.
4. **Components:** `RepositoryAutomationSettings` (two switches + help text) in `RepositoryDetail` header/sidebar; `WebhookEventsTable` (status chips, attempts, last error, replay button).
5. **Routes:** `/app/repositories/:id/settings` (new child route in `App.tsx`) hosting both.
6. **API integration:** `services/github.ts` (new) — `listWebhookEvents`, `getWebhookEvent`, `replayWebhookEvent`, `get/updateRepositoryAutomation`. Note the automation route is keyed by **`github_repo_id`**, not the internal UUID; `RepositoryResponse` already exposes `github_repo_id` (`app/schemas/repository.py`), so no backend change is needed for routing.
7. **State:** TanStack Query keys `['github','events',repoId,filters]`, `['github','automation',githubRepoId]`; invalidate on replay/update.
8. **Error/loading:** skeleton rows; 409 on replay of non-failed events → toast with message.
9. **Steps:** service → hooks → components → route → nav entry in `StudioSubNav.tsx`.
10. **Acceptance:** toggling auto-review persists and is reflected by the next PR webhook; failed event can be replayed from the UI.

### FP-BE-02 — Code search & symbol browser (FEAT-16)
1. **Backend:** `GET|POST /repositories/{id}/search` (hybrid retrieval), `GET /repositories/{id}/symbols` (filters), `GET /repositories/{id}/dependencies` (already used).
2. **Missing FE:** search box with results (file, lines, snippet, score) and a symbols tab in the explorer.
3. **Components:** `CodeSearchPanel`, `SymbolList` (virtualized; reuse `utils/virtualizationAndSyntax.ts`).
4. **Routes:** inside `RepositoryDetail` (tab) — no new top-level route.
5. **API:** `services/repositories.ts` add `searchRepository(id, {query, top_k})` (use **one** of GET/POST — DC-28) and `listSymbols(id, params)`.
6. **State:** debounced query (300 ms) → `useQuery(['repo',id,'search',q])`.
7. **Error/loading:** empty state when index generation is 0 / sync not completed.
8. **Steps:** pick canonical search verb → services → hooks → components → open-in-viewer navigation via existing `sourceReference` helpers.
9. **Acceptance:** clicking a result opens `CodeViewer` at the line range; symbol filter by kind works.

### FP-BE-03 — Live source browser (FEAT-17)
1. **Backend:** `/repositories/{id}/source/{tree,file,commits,commits/{sha},pulls,pulls/{n}/diff,issues,issues/{n}}`.
2. **Existing use:** issues endpoints are used; tree/file/commits/pulls/diff are not.
3. **Recommendation:** Do **not** build a full GitHub browser (duplicates GitHub UI and the indexed explorer). Build only **"Review a pull request"**: list open PRs (`/source/pulls`) and diff (`/source/pulls/{n}/diff`) inside `RepositoryReviewStudio` to choose a review target. Leave tree/file/commits as internal APIs or remove them after a usage check (DC-01).
4–10. Components `PullRequestPicker`; integrates with existing `POST /review` by `pr_number` (`CodeReviewRequest` in `app/schemas/analysis.py` normalizes a `pr_number` target, ~L1179). **Acceptance:** user can pick an open PR and run a review without typing a number.

### FP-BE-04 — Task lifecycle endpoints without UI (FEAT-12)
| Endpoint | Recommendation |
|---|---|
| `POST /tasks/{id}/authorize-publication` | **Use it** in `PublicationPanel` confirmation (ISS-004) — mandatory step. |
| `POST /tasks/{id}/branch`, `POST /tasks/{id}/push` | Keep internal to the orchestrator; hide from public API (or admin-only). The UI's publish flow should be one action. |
| `GET/POST /tasks/{id}/checkpoints` | Show read-only checkpoint list inside `RecoveryPanel` (helps users choose recovery). POST should be orchestrator-internal. |
| `GET /tasks/{id}/invariants` | Show as a "Safety checks" block in `VerificationPanel`. |
| `GET /tasks/{id}/traceability` | Show requirement→change→test mapping in `TaskDetail` (new `TraceabilityPanel`). |
| `POST /tasks/{id}/mcp/elicitations/request` | Agent-side action; keep internal (not a user action). |
Each addition: service function in `services/tasks.ts`, hook in `hooks/useTasks.ts`, panel component, loading/error states consistent with existing panels. **Acceptance:** each panel renders real data for a completed fixture task.

### FP-BE-05 — Project memory semantic search (FEAT-11)
`POST /repositories/{id}/memories/semantic-search` has no UI. Add a search field to `ProjectMemoryPanel` (debounced) → results ranked by similarity. More important is ISS-036 (AI consumption). **Acceptance:** query returns semantically related memories; empty-embedding entries handled.

### FP-BE-06 — Real-time task and tool events (FEAT-19)
Backend publishes task/tool events (event names declared in FE `realtime/events.ts`), but task pages poll. Subscribe in `useTasks` to `task.status.updated` / `task.step.updated` / `tool.invocation.*` and invalidate the matching query keys; reduce polling to a slow safety interval (OPT-11).

---

## 4. Feature consolidation — task spec §5.3

| # | Overlap | Recommendation | Reasoning |
|---|---|---|---|
| C-1 | Two task UIs: `/app/tasks/:taskId` (`TaskDetail.tsx`, full panels) and `/app/repositories/:id/tasks` (`RepositoryTaskStudio.tsx` 1,552 LOC + `TaskPhasePanels.tsx` 926 LOC) | **Merge** into one task detail component used by both routes (the studio embeds it; `/app/tasks/:id` redirects to `/app/repositories/:repoId/tasks?task=:id` or renders the same component) | Two state machines in UI code drift; every new task feature currently needs two implementations (DC-20) |
| C-2 | `POST /tasks/{id}/publish` alias + `create-pr` + FE 404 fallback | **Keep `create-pr` only** (or `publish` only), remove fallback | Duplicate surface; unsafe retry (ISS-017, DC-21) |
| C-3 | Diff data from `/tasks/{id}/diff` and `/source/diff-ranges/task/{id}` | **Merge** into `/tasks/{id}/diff?ranges=true` | One source of truth for task diffs (DC-01) |
| C-4 | PR metadata (`/source/pr-metadata*`, table `pull_requests`) and task PR (`/tasks/{id}/pull-request`, table `task_pull_requests`) | **Merge** into task PR model | ISS-042 |
| C-5 | `/repositories/{id}/tasks` vs `/tasks?repository_id=` | **Remove** repository-scoped routes (no consumer) | Duplicate API (DC-26) |
| C-6 | `/source/agent-branch`, `/source/commit`, `POST /source/pr-metadata` vs `/tasks/{id}/branch`, `/tasks/{id}/commit` | **Remove** `/source/*` task variants | Second write path to workspaces bypasses task state machine checks — verify which guards each applies before deleting (DC-01) |
| C-7 | GET and POST `/repositories/{id}/search` | **Keep POST** (body carries filters), remove GET | DC-28 |
| C-8 | Two tool registries (`ai/agent` chat tools; `agent/tools` task tools) | **Keep separate runtime**, **share** the schema/risk model (`ToolSpec`) and validation | Different trust contexts (read-only chat vs workspace-mutating task tools); merging runtimes would weaken isolation (DC-16) |
| C-9 | Tools & MCP admin | **Implement properly or remove** (FP-FE-01) | A fake admin UI misrepresents security posture |
| C-10 | Internal automated-memory endpoints | **Remove from public API** | ISS-023 |
| C-11 | Live source tree/file/commits (FEAT-17) vs indexed explorer (FEAT-04) | Keep indexed explorer as the browsing UI; retain only PR list/diff from FEAT-17 | Avoid duplicating GitHub's UI; indexed view is what AI features use |

---

## 5. Parity acceptance checklist
- [ ] Every page performs at least one real API call or is explicitly static (marketing/404).
- [ ] Every backend route is either consumed by the UI, documented as external/infra/internal, or removed.
- [ ] Frontend types are generated from OpenAPI (no hand-written duplicates of response models).
- [ ] No feature is reachable in two UIs with divergent implementations (C-1).
