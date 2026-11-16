# 03 — Integration Audit

Scope: Frontend ↔ Backend, Backend ↔ Database, Backend ↔ AI/LLM, AI ↔ Tools, AI ↔ Database, Frontend ↔ Real-time, Backend ↔ Workers, Backend ↔ External services.
Method: AST extraction of every FastAPI route decorator (`APIRouter` prefixes resolved), regex extraction of every `apiClient.<verb>(…)` call in `frontend/src` (tests and mocks excluded, multi-line calls included, plus the 3 calls built from variables: `syncRepository`, `listMemoryEntries`, SSE `EventSource`). Paths normalised (`${x}` / `{x}` → `{}`) and matched on method + path.

---

## 1. Summary

| Classification (task spec §4.1) | Count | Notes |
|---|---|---|
| Fully integrated (FE caller exists, contract consistent as far as checked) | 72 | |
| Integrated with a known defect (contract drift, scalability, security) | 9 | publish (ISS-017), create-pr fallback, pr-metadata (ISS-042), diff-ranges, dev-login (ISS-002), list repos (ISS-024), chat (ISS-015/016), events (ISS-020) |
| **Frontend calling a non-existent endpoint** | **0** | every FE call resolves to a backend route |
| Backend endpoint without a frontend consumer | 23 | features in 04 §3 (FEAT-12/15/16/17/18) |
| Implemented but not connected (UI exists but uses mock data) | 5 | `/mcp/servers*` ↔ `ToolsIntegrationsAdminPage` (ISS-003, ISS-033) |
| Duplicate endpoint | 5 (+ alias) | 3 `/source/*` task duplicates, 2 `/repositories/{id}/tasks`; `/publish` alias; GET+POST `/search` |
| Internal-only endpoint exposed publicly | 2 | `/memories/automated/*` (ISS-023) |
| Unused (deprecated stub) | 2 | `/source/task/{action}`, `/source/task-workspace/{action}` |
| Infra / external / browser navigation | 7 | health ×3 (mounted twice ⇒ 6 URLs), OAuth login/callback, GitHub install callback, webhook |
| **Total routes** | **125** | under `/api/v1` (+3 duplicate root health routes, ISS-030) |

Frontend API surface: 83 `apiClient` call sites (+1 SSE) across 9 files: `services/{tasks,repositories,analysis,memory,auth,chat,repositoryDiscovery}.ts`, `pages/Repositories.tsx` (inline call — move into `services/repositoryDiscovery.ts`, OPT-04), `realtime/index.ts`.

---

## 2. Complete API inventory

Columns: **Request body** = Pydantic model parameter(s) detected in the handler signature (query/path params omitted). **Response model** = `response_model=` in the decorator. **Auth** = `Public` (in `PUBLIC_PATHS`) or `JWT` (+ minimum role when the handler passes `min_role`). Ownership checks (`get_owned_repository` / `_owned_task` / `_request_user_id` lookups) are present in every non-public handler **except** `/mcp/servers*`. Error responses for all routes follow the envelope in `app/core/errors.py` (`{code, message, retryable, request_id, details?}`) with 401/403/404/409/422/429/503 as applicable; AI routes additionally return 502/504 on provider failure.

#### `/analysis-runs` routes

| ID | Method | Endpoint | Backend implementation | Request body | Response model | Auth | Frontend caller | Status |
|---|---|---|---|---|---|---|---|---|
| API-001 | GET | `/api/v1/analysis-runs/{run_id}` | `app/api/v1/analysis/history.py:382` `get_analysis_run` | — | `AnalysisRunDetailResponse` | JWT | `services/analysis.ts:173` | Fully integrated |
| API-002 | POST | `/api/v1/analysis-runs/{run_id}/findings/{finding_id}/feedback` | `app/api/v1/analysis/review.py:447` `submit_finding_feedback` | `ReviewFeedbackRequest` | `ReviewFeedbackResponse` | JWT | `services/analysis.ts:281` | Fully integrated |

#### `/auth` routes

| ID | Method | Endpoint | Backend implementation | Request body | Response model | Auth | Frontend caller | Status |
|---|---|---|---|---|---|---|---|---|
| API-003 | POST | `/api/v1/auth/dev-login` | `app/api/v1/auth.py:368` `dev_login` | — | `TokenResponse` | Public | `services/auth.ts:40` | Integrated (dev only) · security risk (ISS-002) |
| API-004 | GET | `/api/v1/auth/github/callback` | `app/api/v1/auth.py:176` `github_callback` | — | `None` | Public | — | Integrated via browser navigation / OAuth redirect |
| API-005 | GET | `/api/v1/auth/github/login` | `app/api/v1/auth.py:117` `github_login` | — | — (dict/JSONResponse) | Public | — | Integrated via browser navigation / OAuth redirect |
| API-006 | POST | `/api/v1/auth/logout` | `app/api/v1/auth.py:424` `logout` | — | — (dict/JSONResponse) | JWT | `services/auth.ts:32` | Fully integrated |
| API-007 | GET | `/api/v1/auth/me` | `app/api/v1/auth.py:416` `get_current_user` | — | `AuthenticatedUser` | JWT | `services/auth.ts:21` | Fully integrated |

#### `/events` routes

| ID | Method | Endpoint | Backend implementation | Request body | Response model | Auth | Frontend caller | Status |
|---|---|---|---|---|---|---|---|---|
| API-008 | GET | `/api/v1/events` | `app/api/v1/events.py:117` `stream_events` | — | — (dict/JSONResponse) | Public | `realtime/index.ts:107` | Integrated (repos only) · global fan-out (ISS-020) |

#### `/github` routes

| ID | Method | Endpoint | Backend implementation | Request body | Response model | Auth | Frontend caller | Status |
|---|---|---|---|---|---|---|---|---|
| API-009 | GET | `/api/v1/github/events` | `app/api/v1/github.py:598` `list_webhook_events` | — | — (dict/JSONResponse) | JWT | — | Backend without FE consumer (FEAT-15) |
| API-010 | GET | `/api/v1/github/events/{event_id}` | `app/api/v1/github.py:677` `get_webhook_event` | — | — (dict/JSONResponse) | JWT | — | Backend without FE consumer (FEAT-15) |
| API-011 | POST | `/api/v1/github/events/{event_id}/replay` | `app/api/v1/github.py:715` `replay_webhook_event` | — | — (dict/JSONResponse) | JWT | — | Backend without FE consumer (FEAT-15) |
| API-012 | GET | `/api/v1/github/installation/callback` | `app/api/v1/github.py:402` `github_installation_callback` | — | — (dict/JSONResponse) | Public | — | External callback (GitHub App install) |
| API-013 | POST | `/api/v1/github/installations/link` | `app/api/v1/github.py:370` `link_github_installation` | `LinkInstallationRequest` | — (dict/JSONResponse) | JWT | `pages/Repositories.tsx:423` | Fully integrated |
| API-014 | GET | `/api/v1/github/repositories` | `app/api/v1/github.py:71` `list_github_repositories` | — | `PaginatedAvailableRepositoryResponse` | JWT | `services/repositoryDiscovery.ts:142` | Fully integrated |
| API-015 | GET | `/api/v1/github/repositories/{github_repo_id}/automation` | `app/api/v1/github.py:761` `get_repository_automation` | — | `RepositoryAutomationSettingsResponse` | JWT | — | Backend without FE consumer (FEAT-15) |
| API-016 | PATCH | `/api/v1/github/repositories/{github_repo_id}/automation` | `app/api/v1/github.py:786` `update_repository_automation` | `UpdateRepositoryAutomationSettingsRequest` | `RepositoryAutomationSettingsResponse` | JWT | — | Backend without FE consumer (FEAT-15) |
| API-017 | POST | `/api/v1/github/repositories/{github_repo_id}/connect` | `app/api/v1/github.py:260` `connect_repository` | — | `ConnectRepositoryResponse` | JWT | `services/repositoryDiscovery.ts:191` | Fully integrated |
| API-018 | POST | `/api/v1/github/webhook` | `app/api/v1/github.py:442` `github_webhook` | — | — (dict/JSONResponse) | Public (HMAC) | — | External (GitHub → HMAC) |

#### `/health` routes

| ID | Method | Endpoint | Backend implementation | Request body | Response model | Auth | Frontend caller | Status |
|---|---|---|---|---|---|---|---|---|
| API-019 | GET | `/api/v1/health` | `app/api/v1/health.py:28` `health_liveness` | — | `HealthResponse` | Public | — | Infra probe (no UI by design) |
| API-020 | GET | `/api/v1/health/live` | `app/api/v1/health.py:28` `health_liveness` | — | `HealthResponse` | Public | — | Infra probe (no UI by design) |
| API-021 | GET | `/api/v1/health/ready` | `app/api/v1/health.py:42` `health_readiness` | — | `ReadinessResponse` | Public | — | Infra probe (no UI by design) |

#### `/mcp` routes

| ID | Method | Endpoint | Backend implementation | Request body | Response model | Auth | Frontend caller | Status |
|---|---|---|---|---|---|---|---|---|
| API-022 | GET | `/api/v1/mcp/servers` | `app/api/v1/mcp_registry.py:74` `list_mcp_servers` | — | `List[MCPServerSchema]` | JWT only (no role/ownership) | — | Implemented but not connected (FE mock) · no RBAC (ISS-003/033) |
| API-023 | POST | `/api/v1/mcp/servers` | `app/api/v1/mcp_registry.py:79` `register_mcp_server` | `RegisterMCPServerRequest` | `MCPServerSchema` | JWT only (no role/ownership) | — | Implemented but not connected (FE mock) · no RBAC (ISS-003/033) |
| API-024 | POST | `/api/v1/mcp/servers/{server_id}/ping` | `app/api/v1/mcp_registry.py:103` `ping_mcp_server` | — | `MCPServerSchema` | JWT only (no role/ownership) | — | Implemented but not connected (FE mock) · no RBAC (ISS-003/033) |
| API-025 | PATCH | `/api/v1/mcp/servers/{server_id}/toggle` | `app/api/v1/mcp_registry.py:119` `toggle_mcp_server` | — | `MCPServerSchema` | JWT only (no role/ownership) | — | Implemented but not connected (FE mock) · no RBAC (ISS-003/033) |
| API-026 | PATCH | `/api/v1/mcp/servers/{server_id}/tools/{tool_name}/policy` | `app/api/v1/mcp_registry.py:140` `update_mcp_tool_policy` | `UpdateToolApprovalPolicyRequest` | `MCPServerSchema` | JWT only (no role/ownership) | — | Implemented but not connected (FE mock) · no RBAC (ISS-003/033) |

#### `/repositories` routes

| ID | Method | Endpoint | Backend implementation | Request body | Response model | Auth | Frontend caller | Status |
|---|---|---|---|---|---|---|---|---|
| API-027 | GET | `/api/v1/repositories` | `app/api/v1/repositories.py:127` `list_repositories` | — | `list[RepositoryResponse]` | JWT | `services/repositories.ts:42` | Integrated · no server pagination (ISS-024) |
| API-028 | DELETE | `/api/v1/repositories/{repository_id}` | `app/api/v1/repositories.py:194` `delete_repository` | — | — (dict/JSONResponse) | JWT + developer+ | `services/repositories.ts:156` | Fully integrated |
| API-029 | GET | `/api/v1/repositories/{repository_id}` | `app/api/v1/repositories.py:145` `get_repository` | — | `RepositoryResponse` | JWT | `services/repositories.ts:65` | Fully integrated |
| API-030 | GET | `/api/v1/repositories/{repository_id}/analysis-runs` | `app/api/v1/analysis/history.py:56` `list_analysis_runs` | `AnalysisFeatureType | None,UUID | None` | `PaginatedAnalysisRunResponse` | JWT | `services/analysis.ts:160` | Fully integrated |
| API-031 | GET | `/api/v1/repositories/{repository_id}/analysis-runs/export` | `app/api/v1/analysis/history.py:269` `export_analysis_runs_dataset` | `AnalysisFeatureType | None` | — (dict/JSONResponse) | JWT | `services/analysis.ts:250` | Fully integrated |
| API-032 | GET | `/api/v1/repositories/{repository_id}/analysis-runs/summary` | `app/api/v1/analysis/history.py:177` `get_analysis_runs_summary` | — | `AnalysisRunMetricsSummaryResponse` | JWT | `services/analysis.ts:225` | Fully integrated |
| API-033 | POST | `/api/v1/repositories/{repository_id}/chat` | `app/api/v1/chat.py:59` `chat_with_repository` | `RepositoryChatRequest` | `RepositoryAnswer` | JWT | `services/chat.ts:61` | Integrated · no streaming/persistence (ISS-015/016) |
| API-034 | GET | `/api/v1/repositories/{repository_id}/dependencies` | `app/api/v1/repositories.py:397` `list_dependencies` | — | `list[RepositoryDependencyResponse]` | JWT | `services/repositories.ts:130` | Fully integrated |
| API-035 | POST | `/api/v1/repositories/{repository_id}/detect-bugs` | `app/api/v1/analysis/bugs.py:60` `detect_bugs` | `BugDetectionRequest` | `BugDetectionResponse` | JWT | `services/analysis.ts:86` | Fully integrated |
| API-036 | POST | `/api/v1/repositories/{repository_id}/explain` | `app/api/v1/analysis/explain.py:106` `explain_code` | `ExplainCodeRequest` | `CodeExplanationResponse` | JWT | `services/analysis.ts:47` | Fully integrated |
| API-037 | GET | `/api/v1/repositories/{repository_id}/explain/related-files` | `app/api/v1/analysis/explain.py:55` `get_related_files` | — | `RelatedFilesDiscoveryResponse` | JWT | `services/analysis.ts:65` | Fully integrated |
| API-038 | GET | `/api/v1/repositories/{repository_id}/files` | `app/api/v1/repositories.py:294` `list_files` | `Optional[str]` | `PaginatedResponse` | JWT | `services/repositories.ts:84` | Fully integrated |
| API-039 | GET | `/api/v1/repositories/{repository_id}/files/by-path` | `app/api/v1/repositories.py:314` `get_file_by_path` | — | `RepositoryFileResponse` | JWT | `services/repositories.ts:107` | Fully integrated |
| API-040 | GET | `/api/v1/repositories/{repository_id}/files/{file_id}/content` | `app/api/v1/repositories.py:332` `get_file_content` | — | `RepositoryFileContentResponse` | JWT | `services/repositories.ts:168` | Fully integrated |
| API-041 | POST | `/api/v1/repositories/{repository_id}/generate-tests` | `app/api/v1/analysis/tests.py:58` `generate_tests` | `TestGenerationRequest` | `TestGenerationResponse` | JWT | `services/analysis.ts:109` | Fully integrated |
| API-042 | GET | `/api/v1/repositories/{repository_id}/issues` | `app/api/v1/issues.py:309` `list_repository_issues` | — | `list[GitHubIssueResponse]` | JWT | `services/tasks.ts:694` | Fully integrated |
| API-043 | POST | `/api/v1/repositories/{repository_id}/issues` | `app/api/v1/issues.py:368` `create_github_issue` | `GitHubIssueCreateRequest` | `IssueImportResponse` | JWT | `services/tasks.ts:742` | Fully integrated |
| API-044 | POST | `/api/v1/repositories/{repository_id}/issues/import` | `app/api/v1/issues.py:152` `import_github_issue` | `GitHubIssueImportRequest` | `IssueImportResponse` | JWT | `services/tasks.ts:679` | Fully integrated |
| API-045 | GET | `/api/v1/repositories/{repository_id}/memories` | `app/api/v1/memories.py:99` `list_memory_entries` | `MemoryType | None,MemoryStatus | None` | `PaginatedMemoryEntriesResponse` | JWT | `services/memory.ts:43` | Fully integrated |
| API-046 | POST | `/api/v1/repositories/{repository_id}/memories` | `app/api/v1/memories.py:74` `create_memory_entry` | `MemoryEntryCreate` | `MemoryEntryResponse` | JWT + developer+ | `services/memory.ts:67` | Fully integrated |
| API-047 | POST | `/api/v1/repositories/{repository_id}/memories/automated/task-completion` | `app/api/v1/memories.py:139` `record_task_completion_endpoint` | `TaskCompletionMemoryRequest` | `MemoryEntryResponse` | JWT + developer+ | — | Internal-only, publicly exposed (ISS-023) → remove |
| API-048 | POST | `/api/v1/repositories/{repository_id}/memories/automated/task-failure` | `app/api/v1/memories.py:165` `record_task_failure_endpoint` | `TaskFailureMemoryRequest` | `MemoryEntryResponse` | JWT + developer+ | — | Internal-only, publicly exposed (ISS-023) → remove |
| API-049 | GET | `/api/v1/repositories/{repository_id}/memories/mcp-resources` | `app/api/v1/memories.py:255` `list_mcp_resources_endpoint` | — | `MCPMemoryResourcesListResponse` | JWT | `services/memory.ts:119` | Fully integrated |
| API-050 | GET | `/api/v1/repositories/{repository_id}/memories/mcp-resources/{resource_slug}` | `app/api/v1/memories.py:272` `get_mcp_resource_endpoint` | — | `MCPMemoryResource` | JWT | `services/memory.ts:132` | Fully integrated |
| API-051 | POST | `/api/v1/repositories/{repository_id}/memories/rules` | `app/api/v1/memories.py:189` `pin_architectural_rule_endpoint` | `ProjectRuleCreateRequest` | `MemoryEntryResponse` | JWT + developer+ | `services/memory.ts:106` | Fully integrated |
| API-052 | POST | `/api/v1/repositories/{repository_id}/memories/semantic-search` | `app/api/v1/memories.py:215` `semantic_search_memory_endpoint` | `SemanticSearchRequest` | `SemanticSearchResponse` | JWT | — | Backend without FE consumer (FEAT-11) |
| API-053 | DELETE | `/api/v1/repositories/{repository_id}/memories/{entry_id}` | `app/api/v1/memories.py:339` `delete_memory_entry` | — | — (dict/JSONResponse) | JWT + developer+ | `services/memory.ts:96` | Fully integrated |
| API-054 | GET | `/api/v1/repositories/{repository_id}/memories/{entry_id}` | `app/api/v1/memories.py:292` `get_memory_entry` | — | `MemoryEntryResponse` | JWT | `services/memory.ts:54` | Fully integrated |
| API-055 | PATCH | `/api/v1/repositories/{repository_id}/memories/{entry_id}` | `app/api/v1/memories.py:311` `update_memory_entry` | `MemoryEntryUpdate` | `MemoryEntryResponse` | JWT + developer+ | `services/memory.ts:82` | Fully integrated |
| API-056 | POST | `/api/v1/repositories/{repository_id}/review` | `app/api/v1/analysis/review.py:67` `review_code` | `CodeReviewRequest` | `ReviewReportResponse` | JWT | `services/analysis.ts:132` | Fully integrated |
| API-057 | POST | `/api/v1/repositories/{repository_id}/review/publish` | `app/api/v1/analysis/review.py:332` `publish_review_to_github` | `ReviewPublicationRequest` | `ReviewPublicationResponse` | JWT | `services/analysis.ts:312` | Broken contract (ISS-017) · duplicate alias of create-pr (DC-21) |
| API-058 | GET | `/api/v1/repositories/{repository_id}/review/settings` | `app/api/v1/analysis/review.py:504` `get_repository_review_settings` | — | `ReviewSettingsResponse` | JWT | `services/analysis.ts:334` | Fully integrated |
| API-059 | PATCH | `/api/v1/repositories/{repository_id}/review/settings` | `app/api/v1/analysis/review.py:529` `update_repository_review_settings` | `UpdateReviewSettingsRequest` | `ReviewSettingsResponse` | JWT | `services/analysis.ts:362` | Fully integrated |
| API-060 | GET | `/api/v1/repositories/{repository_id}/search` | `app/api/v1/repositories.py:229` `search_repository_get` | — | `RepositorySearchResponse` | JWT | — | Backend without FE consumer · GET/POST duplicate (DC-28, FEAT-16) |
| API-061 | POST | `/api/v1/repositories/{repository_id}/search` | `app/api/v1/repositories.py:253` `search_repository` | `RepositorySearchRequest` | `RepositorySearchResponse` | JWT | — | Backend without FE consumer · GET/POST duplicate (DC-28, FEAT-16) |
| API-062 | POST | `/api/v1/repositories/{repository_id}/source/agent-branch` | `app/integrations/github/routes.py:256` `create_agent_branch_endpoint` | `AgentBranchRequest | None` | `AgentBranchResponse` | JWT | — | Duplicate of `/tasks/{id}/branch|commit` (DC-01) · no FE consumer |
| API-063 | POST | `/api/v1/repositories/{repository_id}/source/commit` | `app/integrations/github/routes.py:296` `commit_workspace_changes_endpoint` | `CommitStagingRequest` | `CommitStagingResponse` | JWT | — | Duplicate of `/tasks/{id}/branch|commit` (DC-01) · no FE consumer |
| API-064 | GET | `/api/v1/repositories/{repository_id}/source/commits` | `app/integrations/github/routes.py:137` `list_commits` | — | `CommitListResponse` | JWT | — | Backend without FE consumer (FEAT-17) |
| API-065 | GET | `/api/v1/repositories/{repository_id}/source/commits/{sha}` | `app/integrations/github/routes.py:167` `get_commit_detail` | — | `CommitDetail` | JWT | — | Backend without FE consumer (FEAT-17) |
| API-066 | GET | `/api/v1/repositories/{repository_id}/source/diff-ranges/task/{task_id}` | `app/integrations/github/routes.py:395` `get_task_diff_ranges_endpoint` | — | `TaskDiffRanges` | JWT | `services/tasks.ts:350` | Integrated · overlaps `/tasks/{id}/diff` (DC-01) |
| API-067 | GET | `/api/v1/repositories/{repository_id}/source/file` | `app/integrations/github/routes.py:101` `get_file_content` | — | `FileContentResponse` | JWT | — | Backend without FE consumer (FEAT-17) |
| API-068 | GET | `/api/v1/repositories/{repository_id}/source/issues` | `app/integrations/github/routes.py:426` `list_remote_issues` | — | `list[RemoteIssueInfo]` | JWT | `services/repositories.ts:187` | Fully integrated |
| API-069 | GET | `/api/v1/repositories/{repository_id}/source/issues/{issue_number}` | `app/integrations/github/routes.py:451` `get_remote_issue` | — | `RemoteIssueInfo` | JWT | `services/repositories.ts:203` | Fully integrated |
| API-070 | POST | `/api/v1/repositories/{repository_id}/source/pr-metadata` | `app/integrations/github/routes.py:338` `prepare_pr_metadata_endpoint` | `PRMetadata` | `PRMetadata` | JWT | — | Duplicate of `/tasks/{id}/branch|commit` (DC-01) · no FE consumer |
| API-071 | GET | `/api/v1/repositories/{repository_id}/source/pr-metadata/{task_id}` | `app/integrations/github/routes.py:368` `get_pr_metadata_endpoint` | — | `PRMetadata` | JWT | `services/tasks.ts:549` | Integrated · duplicate PR model (ISS-042) |
| API-072 | GET | `/api/v1/repositories/{repository_id}/source/pulls` | `app/integrations/github/routes.py:199` `list_pull_requests` | — | `list[PullRequestInfo]` | JWT | — | Backend without FE consumer (FEAT-17) |
| API-073 | GET | `/api/v1/repositories/{repository_id}/source/pulls/{pr_number}/diff` | `app/integrations/github/routes.py:224` `get_pull_request_diff` | — | `PullRequestDiffResponse` | JWT | — | Backend without FE consumer (FEAT-17) |
| API-074 | ANY | `/api/v1/repositories/{repository_id}/source/task-workspace/{action:path}` | `app/integrations/github/routes.py:521` `deprecated_task_workspace_source_endpoint` | — | — (dict/JSONResponse) | JWT | — | Unused · deprecated stub (DC-01) |
| API-075 | ANY | `/api/v1/repositories/{repository_id}/source/task/{action:path}` | `app/integrations/github/routes.py:504` `deprecated_task_source_endpoint` | — | — (dict/JSONResponse) | JWT | — | Unused · deprecated stub (DC-01) |
| API-076 | GET | `/api/v1/repositories/{repository_id}/source/tree` | `app/integrations/github/routes.py:77` `get_file_tree` | — | `FileTreeResponse` | JWT | — | Backend without FE consumer (FEAT-17) |
| API-077 | GET | `/api/v1/repositories/{repository_id}/symbols` | `app/api/v1/repositories.py:377` `list_symbols` | — | `PaginatedResponse` | JWT | — | Backend without FE consumer (FEAT-16) |
| API-078 | POST | `/api/v1/repositories/{repository_id}/sync` | `app/api/v1/repositories.py:157` `sync_repository` | — | `SyncJobResponse` | JWT + developer+ | `services/repositories.ts:146` | Fully integrated |
| API-079 | GET | `/api/v1/repositories/{repository_id}/tasks` | `app/api/v1/tasks.py:2087` `list_repository_tasks` | — | `PaginatedTaskListResponse` | JWT | — | Duplicate of `/tasks` (DC-26) · no FE consumer |
| API-080 | POST | `/api/v1/repositories/{repository_id}/tasks` | `app/api/v1/tasks.py:2114` `create_repository_task` | `TaskCreateRequest` | `TaskDetailResponse` | JWT + developer+ | — | Duplicate of `/tasks` (DC-26) · no FE consumer |

#### `/tasks` routes

| ID | Method | Endpoint | Backend implementation | Request body | Response model | Auth | Frontend caller | Status |
|---|---|---|---|---|---|---|---|---|
| API-081 | GET | `/api/v1/tasks` | `app/api/v1/tasks.py:559` `list_tasks` | `UUID | None` | `PaginatedTaskListResponse` | JWT | `services/tasks.ts:67` | Fully integrated |
| API-082 | POST | `/api/v1/tasks` | `app/api/v1/tasks.py:531` `create_task` | `TaskCreateRequest` | `TaskDetailResponse` | JWT + developer+ | `services/tasks.ts:92` | Fully integrated |
| API-083 | GET | `/api/v1/tasks/{task_id}` | `app/api/v1/tasks.py:606` `get_task_detail` | — | `TaskDetailResponse` | JWT | `services/tasks.ts:76` | Fully integrated |
| API-084 | GET | `/api/v1/tasks/{task_id}/approvals` | `app/api/v1/tasks.py:762` `list_all_task_approvals` | — | — (dict/JSONResponse) | JWT | `services/tasks.ts:161` | Fully integrated |
| API-085 | POST | `/api/v1/tasks/{task_id}/approve` | `app/api/v1/tasks.py:697` `approve_task_plan` | `PlanApprovalRequest | None` | `TaskApprovalResponse` | JWT + developer+ | `services/tasks.ts:133` | Fully integrated |
| API-086 | POST | `/api/v1/tasks/{task_id}/authorize-publication` | `app/api/v1/tasks.py:1680` `authorize_task_publication_endpoint` | `PublicationAuthorizationRequest` | `PublicationAuthorizationResponse` | JWT + developer+ | — | Backend without FE consumer · should be mandatory (ISS-004) |
| API-087 | POST | `/api/v1/tasks/{task_id}/branch` | `app/api/v1/tasks.py:1600` `ensure_task_branch_endpoint` | `TaskBranchSetupRequest | None` | — (dict/JSONResponse) | JWT + developer+ | — | Backend without FE consumer (FEAT-12/18) |
| API-088 | POST | `/api/v1/tasks/{task_id}/cancel` | `app/api/v1/tasks.py:1151` `cancel_task` | — | `TaskDetailResponse` | JWT + developer+ | `services/tasks.ts:327` | Fully integrated |
| API-089 | GET | `/api/v1/tasks/{task_id}/checkpoints` | `app/api/v1/tasks.py:1845` `list_task_checkpoints_endpoint` | — | `list[TaskCheckpointResponse]` | JWT | — | Backend without FE consumer (FEAT-12/18) |
| API-090 | POST | `/api/v1/tasks/{task_id}/checkpoints` | `app/api/v1/tasks.py:1820` `save_task_checkpoint_endpoint` | `TaskCheckpointCreateRequest` | `TaskCheckpointResponse` | JWT + developer+ | — | Backend without FE consumer (FEAT-12/18) |
| API-091 | POST | `/api/v1/tasks/{task_id}/commit` | `app/api/v1/tasks.py:1624` `commit_task_changes_endpoint` | `TaskCommitTriggerRequest | None` | — (dict/JSONResponse) | JWT + developer+ | `services/tasks.ts:514` | Fully integrated |
| API-092 | POST | `/api/v1/tasks/{task_id}/create-pr` | `app/api/v1/tasks.py:1711` `create_task_draft_pr_endpoint` | `TaskDraftPRCreateRequest | None` | `TaskPullRequestResponse` | JWT + developer+ | `services/tasks.ts:532`<br>`services/tasks.ts:612` | Integrated (FE fallback target, ISS-017) |
| API-093 | GET | `/api/v1/tasks/{task_id}/diff` | `app/api/v1/tasks.py:1224` `get_task_diff` | — | — (dict/JSONResponse) | JWT | `services/tasks.ts:358`<br>`services/tasks.ts:364` | Fully integrated |
| API-094 | GET | `/api/v1/tasks/{task_id}/events` | `app/api/v1/tasks.py:2067` `get_task_events` | — | `list[TaskEventResponse]` | JWT | `services/tasks.ts:424` | Fully integrated |
| API-095 | POST | `/api/v1/tasks/{task_id}/execute` | `app/api/v1/tasks.py:1076` `execute_approved_task` | `TaskExecuteRequest | None` | `TaskDetailResponse` | JWT + developer+ | `services/tasks.ts:284` | Fully integrated |
| API-096 | GET | `/api/v1/tasks/{task_id}/invariants` | `app/api/v1/tasks.py:1886` `check_task_invariants_endpoint` | — | — (dict/JSONResponse) | JWT | — | Backend without FE consumer (FEAT-12/18) |
| API-097 | GET | `/api/v1/tasks/{task_id}/mcp/elicitations` | `app/api/v1/tasks.py:972` `list_mcp_elicitations` | — | — (dict/JSONResponse) | JWT | `services/tasks.ts:233` | Fully integrated |
| API-098 | POST | `/api/v1/tasks/{task_id}/mcp/elicitations/request` | `app/api/v1/tasks.py:919` `request_mcp_elicitation` | `MCPElicitationRequest` | — (dict/JSONResponse) | JWT + developer+ | — | Backend without FE consumer (FEAT-12/18) |
| API-099 | POST | `/api/v1/tasks/{task_id}/mcp/elicitations/{elicitation_id}/cancel` | `app/api/v1/tasks.py:1033` `cancel_mcp_elicitation` | `MCPElicitationCancelRequest` | — (dict/JSONResponse) | JWT + developer+ | `services/tasks.ts:263` | Fully integrated |
| API-100 | POST | `/api/v1/tasks/{task_id}/mcp/elicitations/{elicitation_id}/respond` | `app/api/v1/tasks.py:994` `respond_mcp_elicitation` | `MCPElicitationResponseSubmit` | — (dict/JSONResponse) | JWT + developer+ | `services/tasks.ts:246` | Fully integrated |
| API-101 | POST | `/api/v1/tasks/{task_id}/pause` | `app/api/v1/tasks.py:1105` `pause_task` | `TaskPauseRequest | None` | `TaskDetailResponse` | JWT + developer+ | `services/tasks.ts:309` | Fully integrated |
| API-102 | GET | `/api/v1/tasks/{task_id}/plan` | `app/api/v1/tasks.py:664` `get_task_plan` | — | `TaskPlanResponse` | JWT | `services/tasks.ts:105` | Fully integrated |
| API-103 | POST | `/api/v1/tasks/{task_id}/plan` | `app/api/v1/tasks.py:626` `generate_task_plan` | `TaskPlanGenerateRequest | None` | `TaskPlanResponse` | JWT + developer+ | `services/tasks.ts:119` | Fully integrated |
| API-104 | POST | `/api/v1/tasks/{task_id}/publish` | `app/api/v1/tasks.py:1741` `publish_task_draft_pr_endpoint` | `TaskDraftPRCreateRequest | None` | `TaskPullRequestResponse` | JWT | `services/tasks.ts:603` | Broken contract (ISS-017) · duplicate alias of create-pr (DC-21) |
| API-105 | GET | `/api/v1/tasks/{task_id}/pull-request` | `app/api/v1/tasks.py:1755` `get_task_pull_request_endpoint` | — | `TaskPullRequestResponse` | JWT | `services/tasks.ts:582` | Fully integrated |
| API-106 | POST | `/api/v1/tasks/{task_id}/push` | `app/api/v1/tasks.py:1651` `push_task_branch_endpoint` | `TaskPushTriggerRequest | None` | — (dict/JSONResponse) | JWT + developer+ | — | Backend without FE consumer (FEAT-12/18) |
| API-107 | POST | `/api/v1/tasks/{task_id}/recover` | `app/api/v1/tasks.py:1860` `recover_task_endpoint` | `TaskRecoverTriggerRequest | None` | — (dict/JSONResponse) | JWT + developer+ | `services/tasks.ts:634` | Fully integrated |
| API-108 | POST | `/api/v1/tasks/{task_id}/reject` | `app/api/v1/tasks.py:733` `reject_task_plan` | `PlanRejectionRequest | None` | `TaskApprovalResponse` | JWT + developer+ | `services/tasks.ts:145` | Fully integrated |
| API-109 | POST | `/api/v1/tasks/{task_id}/repair` | `app/api/v1/tasks.py:1490` `trigger_task_repair` | `TaskRepairTriggerRequest | None` | — (dict/JSONResponse) | JWT + developer+ | `services/tasks.ts:406` | Fully integrated |
| API-110 | GET | `/api/v1/tasks/{task_id}/repair-budget` | `app/api/v1/tasks.py:1446` `get_task_repair_budget` | — | — (dict/JSONResponse) | JWT | `services/tasks.ts:388` | Fully integrated |
| API-111 | POST | `/api/v1/tasks/{task_id}/resume` | `app/api/v1/tasks.py:1129` `resume_task` | — | `TaskDetailResponse` | JWT + developer+ | `services/tasks.ts:318` | Fully integrated |
| API-112 | POST | `/api/v1/tasks/{task_id}/run-workflow` | `app/api/v1/tasks.py:1901` `run_autonomous_workflow_endpoint` | `TaskAutonomousWorkflowRequest | None` | — (dict/JSONResponse) | JWT + developer+ | `services/tasks.ts:661`<br>`services/tasks.ts:807` | Fully integrated |
| API-113 | GET | `/api/v1/tasks/{task_id}/stale-check` | `app/api/v1/tasks.py:1792` `check_task_stale_revision_endpoint` | — | — (dict/JSONResponse) | JWT | `services/tasks.ts:757` | Fully integrated |
| API-114 | GET | `/api/v1/tasks/{task_id}/tests` | `app/api/v1/tasks.py:1331` `get_task_tests` | — | — (dict/JSONResponse) | JWT | `services/tasks.ts:444` | Fully integrated |
| API-115 | POST | `/api/v1/tasks/{task_id}/tests` | `app/api/v1/tasks.py:1420` `trigger_task_tests` | `TaskTestTriggerRequest | None` | — (dict/JSONResponse) | JWT + developer+ | `services/tasks.ts:456` | Fully integrated |
| API-116 | GET | `/api/v1/tasks/{task_id}/tool-approvals` | `app/api/v1/tasks.py:823` `list_tool_approvals` | — | — (dict/JSONResponse) | JWT | `services/tasks.ts:175` | Fully integrated |
| API-117 | POST | `/api/v1/tasks/{task_id}/tool-approvals/request` | `app/api/v1/tasks.py:784` `request_tool_approval` | `ToolApprovalRequest` | — (dict/JSONResponse) | JWT + developer+ | `services/tasks.ts:187` | Fully integrated |
| API-118 | POST | `/api/v1/tasks/{task_id}/tool-approvals/{approval_id}/approve` | `app/api/v1/tasks.py:843` `approve_tool_execution` | `ToolApprovalDecisionRequest | None` | — (dict/JSONResponse) | JWT + developer+ | `services/tasks.ts:200` | Fully integrated |
| API-119 | POST | `/api/v1/tasks/{task_id}/tool-approvals/{approval_id}/reject` | `app/api/v1/tasks.py:880` `reject_tool_execution` | `ToolApprovalDecisionRequest | None` | — (dict/JSONResponse) | JWT + developer+ | `services/tasks.ts:215` | Fully integrated |
| API-120 | POST | `/api/v1/tasks/{task_id}/tools/{tool_name}` | `app/api/v1/tasks.py:1294` `invoke_task_tool` | `TaskToolInvokeRequest` | — (dict/JSONResponse) | JWT + developer+ | `services/tasks.ts:377` | Fully integrated |
| API-121 | GET | `/api/v1/tasks/{task_id}/traceability` | `app/api/v1/tasks.py:1777` `get_task_traceability_endpoint` | — | `TaskTraceabilityResponse` | JWT | — | Backend without FE consumer (FEAT-12/18) |
| API-122 | GET | `/api/v1/tasks/{task_id}/verification` | `app/api/v1/tasks.py:1562` `get_task_verification` | — | — (dict/JSONResponse) | JWT | `services/tasks.ts:482` | Fully integrated |
| API-123 | POST | `/api/v1/tasks/{task_id}/verify` | `app/api/v1/tasks.py:1530` `trigger_task_verification` | `TaskVerifyTriggerRequest | None` | — (dict/JSONResponse) | JWT + developer+ | `services/tasks.ts:470` | Fully integrated |
| API-124 | GET | `/api/v1/tasks/{task_id}/workflow-status` | `app/api/v1/tasks.py:1969` `get_task_workflow_status` | — | — (dict/JSONResponse) | JWT | `services/tasks.ts:822` | Fully integrated |
| API-125 | GET | `/api/v1/tasks/{task_id}/workspace` | `app/api/v1/tasks.py:1185` `get_task_workspace` | — | — (dict/JSONResponse) | JWT | `services/tasks.ts:336` | Fully integrated |
---

## 3. Contract checks performed (beyond path matching)

| Endpoint | Check | Result |
|---|---|---|
| `POST /tasks/{id}/publish` / `create-pr` | FE `PublishTaskRequest`/`TaskPublicationResponse` vs BE `TaskDraftPRCreateRequest`/`TaskPullRequestResponse` | **Mismatch** — FE expects `success`, `summary`, `error`; BE returns `pr_id`, `head_sha`, `title`, `body`. FE sends `target_repository` (ignored by BE). ISS-017 |
| `GET /repositories` | FE `PaginatedRepositoryResponse` vs BE `list[RepositoryResponse]` | Bridged by client-side shim (`services/repositories.ts` L39–57). ISS-024 |
| `POST /repositories/{id}/chat` | FE `RepositoryChatRequest{question,history,mode}` vs BE (`app/schemas/repository.py` L140–148: `question≤4000`, `history≤50`, `mode∈{normal,agentic}`) | Consistent |
| `GET /tasks` | FE `TaskListFilterParams` vs BE query params (`repository_id`, `status`, `search`, `page`, `page_size≤100`) | Consistent |
| `GET /tasks/{id}/diff` and `GET /source/diff-ranges/task/{id}` | Both called by `services/tasks.ts` (L350, L358, L364) | Two sources for the same diff data (DC-01) |
| `GET /source/pr-metadata/{task_id}` and `GET /tasks/{id}/pull-request` | Both called | Two PR models (ISS-042) |
| SSE `/events` | FE `NAMED_SSE_EVENTS` (`frontend/src/realtime/events.ts`: `repository.updated`, `task.status.updated`, `task.step.updated`, `chat.*`, `tool.invocation.*`) vs consumers | Only `repository.updated` has a consumer (`useRealtimeRepositories`); task, chat and tool events are declared but unused (DC-31 candidate → wire in OPT-11 instead of deleting) |

Recommended permanent control (OPT-03): generate `frontend/src/types/api.gen.ts` from `/openapi.json` with `openapi-typescript` in CI and fail the build on drift; add a contract test that loads `app.openapi()` and asserts every FE path/method exists (TST-30).

---

## 4. Data-flow traces and break points

The full sequence diagrams are in 02 §8. Break points per flow:

| Flow | Path | Where communication breaks or degrades |
|---|---|---|
| Login | `Login.tsx` → `/auth/github/login` → GitHub → `/auth/github/callback` → cookie → `/auth/me` | Session ends after 15 min (ISS-012); dev path impersonation (ISS-002) |
| Connect + index | `Repositories.tsx` → `/github/repositories` → `/github/repositories/{id}/connect` → Redis queue → sync worker → DB → SSE `repo.updated` → `useRealtimeRepositories` | **No worker in prod** (ISS-005, suspected); SSE fan-out (ISS-020); polling + no pagination (ISS-024) |
| Chat | `RepositoryChat.tsx` → `useRepositoryChat` → `POST /chat` → `RAGPipeline.chat` / `AgentOrchestrator.run` → `RepositoryAnswer` | Graph expansion off (ISS-007); memory never supplied (ISS-036); no streaming (ISS-015); history lost on refresh (ISS-016); async handler + sync session (ISS-009) |
| Explain / Bugs / Tests / Review | Studio → `useAnalysis` → `POST /repositories/{id}/<feature>` → orchestrator → LLM → `analysis_runs` → `AnalysisHistoryDrawer` | Static scanners absent in prod image (ISS-013); history fallback to memory (ISS-038); event-loop blocking (ISS-009) |
| Review → GitHub | `CodeReviewView` → `/review/publish` → `ReviewPublicationService` → GitHub review API | Integrated |
| Bug → Issue | `CreateIssueModal` → `POST /repositories/{id}/issues` → `GitHubService.create_issue` | Integrated |
| Task lifecycle | `CreateTask`/`ImportIssueForm` → `/tasks` → `/plan` → `/approve` → `/execute` or `/run-workflow` → `/tests` → `/repair` → `/verify` → `/publish` | Workflows not durable (ISS-010); publication authorization weak (ISS-004); contract drift (ISS-017); simulated push (ISS-018); sandbox may be unavailable (ISS-006) |
| Project memory | `ProjectMemoryPanel` → `/memories` CRUD | Stored but never used by AI (ISS-036) |
| Tools admin | `ToolsIntegrationsAdminPage` | **No backend communication at all** (ISS-033) |

---

## 5. Integration gap matrix (actual features)

| Feature (04 ID) | Frontend | Backend | AI | Database | Integration status |
|---|---|---|---|---|---|
| FEAT-01 Auth (GitHub OAuth, dev login) | Implemented | Implemented | N/A | `users` | Integrated · no refresh (ISS-012) · dev-login risk (ISS-002) |
| FEAT-02 Repository discovery & connect | Implemented | Implemented | N/A | `github_installations`, `repositories` | Integrated |
| FEAT-03 Sync & indexing progress | Implemented (SSE) | Implemented | Embeddings | `sync_jobs`, files/symbols/edges/chunks | **Verify** — worker deployment (ISS-005) |
| FEAT-04 File explorer / code viewer | Implemented | Implemented | N/A | `repository_files` | Integrated |
| FEAT-05 Repository chat | Implemented | Implemented | RAG + agent | chunks; **no chat tables** | Partial (ISS-015, ISS-016, ISS-007) |
| FEAT-06 Explain | Implemented | Implemented | Yes | `analysis_runs` | Integrated |
| FEAT-07 Bug detection (+ create issue) | Implemented | Implemented | Yes + static | `analysis_*`, `github_issues` | Integrated · scanners missing in prod (ISS-013) |
| FEAT-08 Test generation | Implemented | Implemented | Yes | `analysis_runs` | Integrated |
| FEAT-09 Code review (+ publish, settings, feedback) | Implemented | Implemented | Yes + static | `analysis_*`, repo settings | Integrated · scanners (ISS-013) |
| FEAT-10 Analysis history / export | Implemented | Implemented | N/A | `analysis_runs/findings` | Integrated · memory fallback (ISS-038) · no purge job (OPT-21) |
| FEAT-11 Project memory | CRUD implemented; semantic search missing | Implemented | **Not consumed** | `memory_entries` (HNSW) | Incomplete (ISS-036, ISS-023) |
| FEAT-12 Agent tasks | Implemented (two UIs, DC-20) | Implemented (47 routes) | Planner/repair/verify | 13 task tables | Integrated core · gaps: authorize-publication, branch/push, checkpoints, invariants, traceability |
| FEAT-13 Issue import / create | Implemented | Implemented | N/A | `github_issues` | Integrated |
| FEAT-14 Tools & MCP admin | **Mock only** | In-memory, no RBAC | N/A | **None** | Not integrated (ISS-003, ISS-033) |
| FEAT-15 Webhook console & repo automation | Missing | Implemented | Auto-review | `github_webhook_events`, repo flags | Frontend missing |
| FEAT-16 Code search & symbols | Missing | Implemented | Hybrid retrieval | chunks/symbols | Frontend missing |
| FEAT-17 Source browser (tree, commits, PRs, diffs) | Missing | Implemented | N/A | N/A (GitHub live) | Frontend missing |
| FEAT-18 Tool approvals & MCP elicitations | Implemented (request-elicitation missing) | Implemented | Agent | `task_approvals` | Integrated (minor gap) |
| FEAT-19 Real-time events | Repos only | Repos, tasks, chat | N/A | Redis Streams | Partial (tasks/chat poll) |
| FEAT-20 Autonomous workflow | Implemented | Implemented (threads) | Yes | in-memory + task tables | Integrated · not durable (ISS-010) |
| FEAT-21 Repo-scoped task routes | Not used | Implemented | N/A | tasks | Duplicate (DC-26) |
| FEAT-22 Health / readiness | N/A | Implemented | N/A | DB/Redis checks | Integrated (readiness lacks worker/scanner signals, ISS-005/013) |

---

## 6. Per-boundary findings

### 6.1 Backend ↔ Database
- Sync `Session` from `get_db` is the dominant pattern; async engine used by retrieval (`AsyncSessionLocal` → `VectorRetriever`, `LexicalRetriever`, `GroundingValidator`, `SymbolGraphExpander`) and `RAGPipeline`. Mixed use inside async handlers → ISS-009.
- Ownership enforced in the data-access calls (`RepositoryRepository.get_for_user`, `TaskRepository.get_task_for_user`). Good.
- Persistence failures are frequently swallowed (ISS-038, ISS-040).
- Two PR tables (ISS-042); no tables for chat, MCP registry, durable jobs (02 §6.2).

### 6.2 Backend ↔ AI/LLM
- All AI services are singletons on `app.state`, created only when an LLM key exists; routes return 503 `SERVICE_UNAVAILABLE` (retryable) otherwise — correct degradation.
- Wiring bugs: ISS-007 (graph), ISS-008 (reranker), ISS-036 (memory).
- Missing controls: ISS-025 (concurrency), per-user AI quotas (rate limiter is generic).
- Sync↔async bridging: ISS-011.

### 6.3 AI/LLM ↔ Tools
- Chat agent: 4 read-only tools via `ai/agent/tool_registry.py`, executed **sequentially** with per-tool timeout (5 s), result size caps (8 KB/24 KB total), duplicate-call detection, budget of 6 calls — well bounded.
- Task tools: `agent/tools/router.py` with schema validation (`jsonschema`), rate limiting and approval gates (`app/services/tool_approval_gate.py`, `app/core/tool_api_policy.py`). MCP tool policies edited in the admin API are **not** read by this router (ISS-003 — verify before relying).
- Two registries (DC-16).

### 6.4 AI/LLM ↔ Database
- Retrieval reads via async engine with HNSW `ef_search` set per query inside a savepoint (adaptive profiles 40/64/120).
- Grounding validation re-reads chunks to verify citations.
- Agent DB helper (`ai/agent/db.py`) accepts either sessionmakers or sessions, sync or async — flexible but hard to reason about; standardize on `AsyncSession` (OPT-05).

### 6.5 Frontend ↔ Real-time
- Single SSE connection from `AppLayout`; reconnect with backoff (×1.5) and Last-Event-ID replay.
- Only repository updates are consumed; task panels poll (`refetchInterval`), chat waits on HTTP. Use SSE invalidation for tasks (OPT-11) once ISS-020 is fixed.

### 6.6 Backend ↔ Background workers
- Sync: Redis queue + DB status + lease/heartbeat + per-repo lock; standalone entrypoint exists. Production deployment of it is unverified (ISS-005).
- Webhooks: durable table with atomic claim, attempts, backoff; embedded in every API process (ISS-014).
- Workflows: threads (ISS-010).

### 6.7 Backend ↔ External services
| Service | Client | Resilience | Notes |
|---|---|---|---|
| GitHub REST/App | `app/integrations/github/client.py` (httpx), `token_manager.py`, `cache.py` | Token caching; retries in client (verify per method) | Webhook HMAC with `compare_digest`; delivery-ID dedupe in Redis |
| Gemini / Groq | `ai/llm/*_provider.py` | Key rotation, retries, fallback, timeouts (`ai_request_timeout_seconds=30`) | No global concurrency cap (ISS-025) |
| Gemini embeddings | `ai/embeddings/gemini_provider.py` + `CachedEmbeddingService` | RPM limit 120, concurrency 5, Redis cache | |
| Langfuse / OTLP | `app/observability/*` | Off by default | Prompt/response capture off by default (good) |
| Sandbox runner | `sandbox/runner_client.py` | Bearer secret (`compare_digest`), timeout 60 s | Not deployed in compose (ISS-006) |
