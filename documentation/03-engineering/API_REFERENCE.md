# API Reference

Generated from `openapi.json` (version 1.0.0, 129 operations, 168 component schemas) and checked against the routers in `backend/app/api/v1`. All paths are under `/api/v1`. The interactive spec is served at `/docs` when the API runs.

## Conventions

- **Authentication:** httpOnly access-token cookie (`access_token`) set by the OAuth callback; a bearer token is also accepted. `POST /auth/refresh` rotates using the refresh cookie. Public routes: health, OAuth login/callback, installation callback, webhook (HMAC-verified), dev login (only when enabled outside production).
- **CSRF:** state-changing cookie-authenticated requests must carry an allowed `Origin`/`Referer`.
- **Authorisation:** role hierarchy `viewer < developer < admin`; every repository/task route checks ownership.
- **Errors:** `{"code", "message", "retryable", "request_id", "details"?}` with standard HTTP status codes; `429` from rate limiting; `503` when a fail-closed dependency (e.g. Redis for auth) is unavailable.
- **Pagination:** list endpoints accept `page`/`page_size` or `skip`/`limit` where noted.

## Authentication

| Method | Path | Summary | Body | Query | Responses |
|---|---|---|---|---|---|
| GET | `/auth/github/login` | Start GitHub OAuth login |  | redirect_url? | 200:, 422:HTTPValidationError |
| GET | `/auth/github/callback` | Complete GitHub OAuth login or App Installation |  | code?, state?, installation_id?, setup_action?, redirect_url? | 200:, 422:HTTPValidationError |
| POST | `/auth/dev-login` | Quick local developer authentication |  | login? | 200:TokenResponse, 422:HTTPValidationError |
| POST | `/auth/refresh` | Refresh access token using refresh token |  |  | 200:TokenResponse |
| GET | `/auth/me` | Get the current authenticated user |  |  | 200:AuthenticatedUser |
| POST | `/auth/logout` | Revoke the current access token |  |  | 204 |

## Repositories

| Method | Path | Summary | Body | Query | Responses |
|---|---|---|---|---|---|
| GET | `/repositories` | List connected repositories |  | page?, page_size?, skip?, limit? | 200:RepositoryResponse[], 422:HTTPValidationError |
| GET | `/repositories/{repository_id}` | Get repository details |  |  | 200:RepositoryResponse, 422:HTTPValidationError |
| DELETE | `/repositories/{repository_id}` | Disconnect and remove a repository |  |  | 204, 422:HTTPValidationError |
| POST | `/repositories/{repository_id}/sync` | Queue repository synchronization |  | force? | 202:SyncJobResponse, 422:HTTPValidationError |
| POST | `/repositories/{repository_id}/search` | Hybrid code search | `RepositorySearchRequest` |  | 200:RepositorySearchResponse, 422:HTTPValidationError |
| GET | `/repositories/{repository_id}/files` | List indexed repository files |  | page?, page_size?, path? | 200:PaginatedResponse, 422:HTTPValidationError |
| GET | `/repositories/{repository_id}/files/by-path` | Look up an indexed repository file by exact path |  | path | 200:RepositoryFileResponse, 422:HTTPValidationError |
| GET | `/repositories/{repository_id}/files/{file_id}/content` | Get indexed file content and symbols |  |  | 200:RepositoryFileContentResponse, 422:HTTPValidationError |
| GET | `/repositories/{repository_id}/symbols` | List extracted repository symbols |  | page?, page_size? | 200:PaginatedResponse, 422:HTTPValidationError |
| GET | `/repositories/{repository_id}/dependencies` | List top-level repository dependencies |  |  | 200:RepositoryDependencyResponse[], 422:HTTPValidationError |

## Chat

| Method | Path | Summary | Body | Query | Responses |
|---|---|---|---|---|---|
| POST | `/repositories/{repository_id}/chat` | Ask a grounded question about a repository | `RepositoryChatRequest` |  | 200:RepositoryAnswer, 422:HTTPValidationError |

## Analysis (explain, bugs, tests, review, history)

| Method | Path | Summary | Body | Query | Responses |
|---|---|---|---|---|---|
| GET | `/repositories/{repository_id}/explain/related-files` | Discover automatically related files for a code explanation target |  | path, symbol? | 200:RelatedFilesDiscoveryResponse, 400:ErrorResponseEnvelope, 401:ErrorResponseEnvelope, 404:ErrorResponseEnvelope, 413:ErrorResponseEnvelope, 422:ErrorResponseEnvelope, 429:ErrorResponseEnvelope, 500:ErrorResponseEnvelope, 503:ErrorResponseEnvelope |
| POST | `/repositories/{repository_id}/explain` | Explain a file, symbol, or line range using repository context | `ExplainCodeRequest` |  | 200:CodeExplanationResponse, 400:ErrorResponseEnvelope, 401:ErrorResponseEnvelope, 404:ErrorResponseEnvelope, 413:ErrorResponseEnvelope, 422:ErrorResponseEnvelope, 429:ErrorResponseEnvelope, 500:ErrorResponseEnvelope, 503:ErrorResponseEnvelope |
| POST | `/repositories/{repository_id}/detect-bugs` | Detect potential bugs using static analysis and AI reasoning | `BugDetectionRequest` |  | 200:BugDetectionResponse, 400:ErrorResponseEnvelope, 401:ErrorResponseEnvelope, 404:ErrorResponseEnvelope, 413:ErrorResponseEnvelope, 422:ErrorResponseEnvelope, 429:ErrorResponseEnvelope, 500:ErrorResponseEnvelope, 503:ErrorResponseEnvelope |
| POST | `/repositories/{repository_id}/generate-tests` | Generate framework-aware test files for a repository file or symbol | `TestGenerationRequest` |  | 200:TestGenerationResponse, 400:ErrorResponseEnvelope, 401:ErrorResponseEnvelope, 404:ErrorResponseEnvelope, 413:ErrorResponseEnvelope, 422:ErrorResponseEnvelope, 429:ErrorResponseEnvelope, 500:ErrorResponseEnvelope, 503:ErrorResponseEnvelope |
| POST | `/repositories/{repository_id}/review` | Run a standalone AI and static code review on a file, commit, PR, or diff | `CodeReviewRequest` |  | 200:ReviewReportResponse, 400:ErrorResponseEnvelope, 401:ErrorResponseEnvelope, 404:ErrorResponseEnvelope, 413:ErrorResponseEnvelope, 422:ErrorResponseEnvelope, 429:ErrorResponseEnvelope, 500:ErrorResponseEnvelope, 503:ErrorResponseEnvelope |
| POST | `/repositories/{repository_id}/review/publish` | Publish review findings as inline GitHub PR comments | `ReviewPublicationRequest` |  | 200:ReviewPublicationResponse, 422:HTTPValidationError |
| POST | `/analysis-runs/{run_id}/findings/{finding_id}/feedback` | Submit developer feedback on an AI code review finding | `ReviewFeedbackRequest` |  | 200:ReviewFeedbackResponse, 422:HTTPValidationError |
| GET | `/repositories/{repository_id}/review/settings` | Get repository code review settings |  |  | 200:ReviewSettingsResponse, 422:HTTPValidationError |
| PATCH | `/repositories/{repository_id}/review/settings` | Update repository code review settings | `UpdateReviewSettingsRequest` |  | 200:ReviewSettingsResponse, 422:HTTPValidationError |
| GET | `/repositories/{repository_id}/analysis-runs` | List historical analysis runs for an authorized repository |  | feature_type?, status?, target_path?, source_revision?, user_id?, page?, page_size? | 200:PaginatedAnalysisRunResponse, 400:ErrorResponseEnvelope, 401:ErrorResponseEnvelope, 404:ErrorResponseEnvelope, 413:ErrorResponseEnvelope, 422:ErrorResponseEnvelope, 429:ErrorResponseEnvelope, 500:ErrorResponseEnvelope, 503:ErrorResponseEnvelope |
| GET | `/repositories/{repository_id}/analysis-runs/summary` | Get analysis run summary, database integrity, and retention metrics |  |  | 200:AnalysisRunMetricsSummaryResponse, 400:ErrorResponseEnvelope, 401:ErrorResponseEnvelope, 404:ErrorResponseEnvelope, 413:ErrorResponseEnvelope, 422:ErrorResponseEnvelope, 429:ErrorResponseEnvelope, 500:ErrorResponseEnvelope, 503:ErrorResponseEnvelope |
| GET | `/repositories/{repository_id}/analysis-runs/export` | Export analysis runs and user feedback as an evaluation dataset (Issue #195) |  | format?, feature_type?, status?, include_feedback_only?, limit? | 200:, 400:ErrorResponseEnvelope, 401:ErrorResponseEnvelope, 404:ErrorResponseEnvelope, 413:ErrorResponseEnvelope, 422:ErrorResponseEnvelope, 429:ErrorResponseEnvelope, 500:ErrorResponseEnvelope, 503:ErrorResponseEnvelope |
| GET | `/analysis-runs/{run_id}` | Get a specific analysis run and its structured findings |  |  | 200:AnalysisRunDetailResponse, 400:ErrorResponseEnvelope, 401:ErrorResponseEnvelope, 404:ErrorResponseEnvelope, 413:ErrorResponseEnvelope, 422:ErrorResponseEnvelope, 429:ErrorResponseEnvelope, 500:ErrorResponseEnvelope, 503:ErrorResponseEnvelope |

## GitHub App, installations and webhooks

| Method | Path | Summary | Body | Query | Responses |
|---|---|---|---|---|---|
| GET | `/github/repositories` | List repositories accessible via GitHub App |  | page?, page_size?, search?, installation_id? | 200:PaginatedAvailableRepositoryResponse, 422:HTTPValidationError |
| POST | `/github/repositories/{github_repo_id}/connect` | Connect a GitHub repository to the platform |  |  | 201:ConnectRepositoryResponse, 422:HTTPValidationError |
| POST | `/github/installations/link` | Link a GitHub App installation to the authenticated user | `LinkInstallationRequest` |  | 200:, 422:HTTPValidationError |
| GET | `/github/installation/callback` | GitHub App installation redirect callback |  | installation_id, setup_action? | 200:, 422:HTTPValidationError |
| POST | `/github/webhook` | GitHub App webhook handler |  |  | 200: |
| GET | `/github/events` | List durably persisted GitHub webhook events |  | status?, event_type?, repository_id?, page?, page_size? | 200:, 422:HTTPValidationError |
| GET | `/github/events/{event_id}` | Get detailed status of a webhook event |  |  | 200:, 422:HTTPValidationError |
| POST | `/github/events/{event_id}/replay` | Safely replay a failed or dead-letter webhook event |  |  | 200:, 422:HTTPValidationError |
| GET | `/github/repositories/{github_repo_id}/automation` | Get repository automation settings |  |  | 200:RepositoryAutomationSettingsResponse, 422:HTTPValidationError |
| PATCH | `/github/repositories/{github_repo_id}/automation` | Update repository automation settings | `UpdateRepositoryAutomationSettingsRequest` |  | 200:RepositoryAutomationSettingsResponse, 422:HTTPValidationError |

## GitHub source browsing (`/source/*`)

| Method | Path | Summary | Body | Query | Responses |
|---|---|---|---|---|---|
| GET | `/repositories/{repository_id}/source/tree` | Get repository file tree |  | ref? | 200:FileTreeResponse, 422:HTTPValidationError |
| GET | `/repositories/{repository_id}/source/file` | Get file content |  | path, ref?, start_line?, end_line? | 200:FileContentResponse, 422:HTTPValidationError |
| GET | `/repositories/{repository_id}/source/commits` | List repository commits |  | ref?, path?, per_page?, page? | 200:CommitListResponse, 422:HTTPValidationError |
| GET | `/repositories/{repository_id}/source/commits/{sha}` | Get commit detail |  |  | 200:CommitDetail, 422:HTTPValidationError |
| GET | `/repositories/{repository_id}/source/pulls` | List pull requests |  | state?, per_page?, page? | 200:PullRequestInfo[], 422:HTTPValidationError |
| GET | `/repositories/{repository_id}/source/pulls/{pr_number}/diff` | Get pull-request diff |  |  | 200:PullRequestDiffResponse, 422:HTTPValidationError |
| POST | `/repositories/{repository_id}/source/agent-branch` | Create agent branch for task execution | `AgentBranchRequest | null` | task_id?, base_branch? | 200:AgentBranchResponse, 422:HTTPValidationError |
| POST | `/repositories/{repository_id}/source/commit` | Stage and commit agent workspace changes | `CommitStagingRequest` |  | 200:CommitStagingResponse, 422:HTTPValidationError |
| POST | `/repositories/{repository_id}/source/pr-metadata` | Prepare and persist PR metadata | `PRMetadata` |  | 200:PRMetadata, 422:HTTPValidationError |
| GET | `/repositories/{repository_id}/source/pr-metadata/{task_id}` | Retrieve prepared PR metadata |  |  | 200:PRMetadata, 422:HTTPValidationError |
| GET | `/repositories/{repository_id}/source/diff-ranges/task/{task_id}` | Get task workspace diff line ranges |  | base_branch?, workspace_path? | 200:TaskDiffRanges, 422:HTTPValidationError |
| GET | `/repositories/{repository_id}/source/issues` | List remote repository issues |  | state?, per_page?, page? | 200:RemoteIssueInfo[], 422:HTTPValidationError |
| GET | `/repositories/{repository_id}/source/issues/{issue_number}` | Get remote issue detail |  |  | 200:RemoteIssueInfo, 422:HTTPValidationError |
| POST | `/repositories/{repository_id}/source/task/{action}` | Deprecated duplicate task execution surface **(deprecated)** |  |  | 200:, 422:HTTPValidationError |
| DELETE | `/repositories/{repository_id}/source/task/{action}` | Deprecated duplicate task execution surface **(deprecated)** |  |  | 200:, 422:HTTPValidationError |
| PUT | `/repositories/{repository_id}/source/task/{action}` | Deprecated duplicate task execution surface **(deprecated)** |  |  | 200:, 422:HTTPValidationError |
| PATCH | `/repositories/{repository_id}/source/task/{action}` | Deprecated duplicate task execution surface **(deprecated)** |  |  | 200:, 422:HTTPValidationError |
| GET | `/repositories/{repository_id}/source/task/{action}` | Deprecated duplicate task execution surface **(deprecated)** |  |  | 200:, 422:HTTPValidationError |
| POST | `/repositories/{repository_id}/source/task-workspace/{action}` | Deprecated duplicate task workspace execution surface **(deprecated)** |  |  | 200:, 422:HTTPValidationError |
| DELETE | `/repositories/{repository_id}/source/task-workspace/{action}` | Deprecated duplicate task workspace execution surface **(deprecated)** |  |  | 200:, 422:HTTPValidationError |
| PUT | `/repositories/{repository_id}/source/task-workspace/{action}` | Deprecated duplicate task workspace execution surface **(deprecated)** |  |  | 200:, 422:HTTPValidationError |
| PATCH | `/repositories/{repository_id}/source/task-workspace/{action}` | Deprecated duplicate task workspace execution surface **(deprecated)** |  |  | 200:, 422:HTTPValidationError |
| GET | `/repositories/{repository_id}/source/task-workspace/{action}` | Deprecated duplicate task workspace execution surface **(deprecated)** |  |  | 200:, 422:HTTPValidationError |

## GitHub issues

| Method | Path | Summary | Body | Query | Responses |
|---|---|---|---|---|---|
| POST | `/repositories/{repository_id}/issues/import` | Import an authorized GitHub issue as a development task | `GitHubIssueImportRequest` |  | 200:IssueImportResponse, 422:HTTPValidationError |
| GET | `/repositories/{repository_id}/issues` | List imported and created GitHub issues for a repository |  | state?, sync_remote? | 200:GitHubIssueResponse[], 422:HTTPValidationError |
| POST | `/repositories/{repository_id}/issues` | Create a GitHub issue from an approved bug/review finding or requirement | `GitHubIssueCreateRequest` |  | 201:IssueImportResponse, 422:HTTPValidationError |

## Project memory

| Method | Path | Summary | Body | Query | Responses |
|---|---|---|---|---|---|
| POST | `/repositories/{repository_id}/memories` | Create a new project memory entry | `MemoryEntryCreate` |  | 201:MemoryEntryResponse, 422:HTTPValidationError |
| GET | `/repositories/{repository_id}/memories` | List and search project memory entries |  | query?, type?, status?, page?, page_size? | 200:PaginatedMemoryEntriesResponse, 422:HTTPValidationError |
| POST | `/repositories/{repository_id}/memories/rules` | Pin an architectural convention or rule | `ProjectRuleCreateRequest` |  | 201:MemoryEntryResponse, 422:HTTPValidationError |
| POST | `/repositories/{repository_id}/memories/semantic-search` | Semantic cosine search over memory embeddings | `SemanticSearchRequest` |  | 200:SemanticSearchResponse, 422:HTTPValidationError |
| GET | `/repositories/{repository_id}/memories/mcp-resources` | List exposed MCP memory resources |  |  | 200:MCPMemoryResourcesListResponse, 422:HTTPValidationError |
| GET | `/repositories/{repository_id}/memories/mcp-resources/{resource_slug}` | Resolve a specific MCP memory resource |  |  | 200:MCPMemoryResource, 422:HTTPValidationError |
| GET | `/repositories/{repository_id}/memories/{entry_id}` | Get a specific memory entry |  |  | 200:MemoryEntryResponse, 422:HTTPValidationError |
| PATCH | `/repositories/{repository_id}/memories/{entry_id}` | Update a project memory entry | `MemoryEntryUpdate` |  | 200:MemoryEntryResponse, 422:HTTPValidationError |
| DELETE | `/repositories/{repository_id}/memories/{entry_id}` | Delete a project memory entry |  |  | 204, 422:HTTPValidationError |

## Tasks (agentic workflow)

| Method | Path | Summary | Body | Query | Responses |
|---|---|---|---|---|---|
| POST | `/tasks` | Create a new development task with segregated requirements, assumptions, and constraints | `TaskIntakePayload` |  | 201:TaskDetailResponse, 422:HTTPValidationError |
| GET | `/tasks` | List tasks for the authenticated user |  | repository_id?, status?, search?, page?, page_size? | 200:PaginatedTaskListResponse, 422:HTTPValidationError |
| GET | `/tasks/{task_id}` | Get complete task details, latest plan, and approval history |  |  | 200:TaskDetailResponse, 422:HTTPValidationError |
| POST | `/tasks/{task_id}/plan` | Generate or revise a structured implementation plan for a task | `TaskPlanGenerateRequest | null` |  | 200:app__schemas__plan__TaskPlanResponse, 422:HTTPValidationError |
| GET | `/tasks/{task_id}/plan` | Retrieve the current or specified version of a task's implementation plan |  | version? | 200:app__schemas__plan__TaskPlanResponse, 422:HTTPValidationError |
| POST | `/tasks/{task_id}/approve` | Approve the current implementation plan version for execution | `PlanApprovalRequest | null` |  | 200:app__schemas__plan__TaskApprovalResponse, 422:HTTPValidationError |
| POST | `/tasks/{task_id}/reject` | Reject the current implementation plan version | `PlanRejectionRequest | null` |  | 200:app__schemas__plan__TaskApprovalResponse, 422:HTTPValidationError |
| GET | `/tasks/{task_id}/approvals` | List all approval records (plans, tools, MCP elicitations) for a task |  | approval_type?, status? | 200:object[], 422:HTTPValidationError |
| POST | `/tasks/{task_id}/tool-approvals/request` | Request explicit human approval for a high-risk tool execution | `ToolApprovalRequest` |  | 200:object, 422:HTTPValidationError |
| GET | `/tasks/{task_id}/tool-approvals` | List tool approvals for a task |  | status? | 200:object[], 422:HTTPValidationError |
| POST | `/tasks/{task_id}/tool-approvals/{approval_id}/approve` | Approve a pending tool approval request | `ToolApprovalDecisionRequest | null` |  | 200:object, 422:HTTPValidationError |
| POST | `/tasks/{task_id}/tool-approvals/{approval_id}/reject` | Reject a pending tool approval request | `ToolApprovalDecisionRequest | null` |  | 200:object, 422:HTTPValidationError |
| POST | `/tasks/{task_id}/mcp/elicitations/request` | Request MCP Form or URL elicitation | `MCPElicitationRequest` |  | 200:object, 422:HTTPValidationError |
| GET | `/tasks/{task_id}/mcp/elicitations` | List MCP elicitations for a task |  | session_id?, status? | 200:object[], 422:HTTPValidationError |
| POST | `/tasks/{task_id}/mcp/elicitations/{elicitation_id}/respond` | Submit user response or confirmation to an MCP elicitation | `MCPElicitationResponseSubmit` |  | 200:object, 422:HTTPValidationError |
| POST | `/tasks/{task_id}/mcp/elicitations/{elicitation_id}/cancel` | Cancel a pending MCP elicitation | `MCPElicitationCancelRequest` |  | 200:object, 422:HTTPValidationError |
| POST | `/tasks/{task_id}/execute` | Validate human approval gate, provision isolated workspace, and start execution | `TaskExecuteRequest | null` |  | 200:TaskDetailResponse, 422:HTTPValidationError |
| POST | `/tasks/{task_id}/pause` | Pause active execution in the task's isolated workspace | `TaskPauseRequest | null` |  | 200:TaskDetailResponse, 422:HTTPValidationError |
| POST | `/tasks/{task_id}/resume` | Resume paused execution in the task's isolated workspace |  |  | 200:TaskDetailResponse, 422:HTTPValidationError |
| POST | `/tasks/{task_id}/cancel` | Cancel an active or pending task and stop its workspace |  |  | 200:TaskDetailResponse, 422:HTTPValidationError |
| GET | `/tasks/{task_id}/workspace` | Get isolated workspace status and telemetry for a task |  |  | 200:object, 422:HTTPValidationError |
| GET | `/tasks/{task_id}/diff` | Get modified files and git diff telemetry from the task workspace |  |  | 200:object, 422:HTTPValidationError |
| POST | `/tasks/{task_id}/tools/{tool_name}` | Execute a policy-guarded workspace tool via ToolRouter | `TaskToolInvokeRequest` |  | 200:object, 422:HTTPValidationError |
| GET | `/tasks/{task_id}/tests` | Get test execution history and bounded repair attempt telemetry for a task |  |  | 200:object, 422:HTTPValidationError |
| POST | `/tasks/{task_id}/tests` | Trigger restricted test execution inside the task's isolated workspace | `TaskTestTriggerRequest | null` |  | 200:object, 422:HTTPValidationError |
| GET | `/tasks/{task_id}/repair-budget` | Get server-authoritative bounded self-repair budget status and history |  |  | 200:object, 422:HTTPValidationError |
| POST | `/tasks/{task_id}/repair` | Trigger bounded self-repair cycle (max 3 task-level attempts) | `TaskRepairTriggerRequest | null` |  | 200:object, 422:HTTPValidationError |
| POST | `/tasks/{task_id}/verify` | Execute independent multi-dimensional verification over workspace changes | `TaskVerifyTriggerRequest | null` |  | 200:object, 422:HTTPValidationError |
| GET | `/tasks/{task_id}/verification` | Get latest independent verification result for a task |  |  | 200:object, 422:HTTPValidationError |
| POST | `/tasks/{task_id}/branch` | Ensure isolated task branch agent/task-<id> and block protected branches | `TaskBranchSetupRequest | null` |  | 200:object, 422:HTTPValidationError |
| POST | `/tasks/{task_id}/commit` | Stage and commit validated workspace changes on the isolated task branch | `TaskCommitTriggerRequest | null` |  | 200:object, 422:HTTPValidationError |
| POST | `/tasks/{task_id}/push` | Push verified task branch after checking human publication authorization and diff immutability | `TaskPushTriggerRequest | null` |  | 200:object, 422:HTTPValidationError |
| POST | `/tasks/{task_id}/authorize-publication` | Explicitly authorize branch publication and transition READY_FOR_PUBLICATION -> PUBLISHING | `PublicationAuthorizationRequest` |  | 200:PublicationAuthorizationResponse, 422:HTTPValidationError |
| POST | `/tasks/{task_id}/create-pr` | Create a reviewable GitHub Draft Pull Request (is_draft=True, zero auto-merge) | `TaskDraftPRCreateRequest | null` |  | 200:TaskPullRequestResponse, 422:HTTPValidationError |
| POST | `/tasks/{task_id}/publish` | Alias for POST /api/v1/tasks/{task_id}/create-pr | `TaskDraftPRCreateRequest | null` |  | 200:TaskPullRequestResponse, 422:HTTPValidationError |
| GET | `/tasks/{task_id}/pull-request` | Get published GitHub Draft Pull Request details for a task |  |  | 200:TaskPullRequestResponse, 422:HTTPValidationError |
| GET | `/tasks/{task_id}/traceability` | Get end-to-end audit traceability graph from finding/issue to Draft PR (Day 5) |  |  | 200:TaskTraceabilityResponse, 422:HTTPValidationError |
| GET | `/tasks/{task_id}/stale-check` | Check whether the workspace base revision has drifted relative to the repository/plan revision (Day 6) |  | current_remote_head_sha? | 200:object, 422:HTTPValidationError |
| POST | `/tasks/{task_id}/checkpoints` | Save a secret-scrubbed recovery checkpoint for a task | `TaskCheckpointCreateRequest` |  | 201:TaskCheckpointResponse, 422:HTTPValidationError |
| GET | `/tasks/{task_id}/checkpoints` | List persisted recovery checkpoints for a task |  |  | 200:TaskCheckpointResponse[], 422:HTTPValidationError |
| POST | `/tasks/{task_id}/recover` | Reconcile an interrupted or failed task and its workspace while preserving the 3-attempt repair budget | `TaskRecoverTriggerRequest | null` |  | 200:object, 422:HTTPValidationError |
| GET | `/tasks/{task_id}/invariants` | Run Day 6 sandbox security, path confinement, disk budget, and diff immutability invariant checks |  |  | 200:object, 422:HTTPValidationError |
| POST | `/tasks/{task_id}/run-workflow` | Execute the Day 7 autonomous post-approval workflow (Execute -> Test -> Repair -> Verify -> Draft PR) | `TaskAutonomousWorkflowRequest | null` |  | 200:object, 422:HTTPValidationError |
| GET | `/tasks/{task_id}/workflow-status` | Get durable workflow execution progress and status |  |  | 200:object, 422:HTTPValidationError |
| GET | `/tasks/{task_id}/events` | Get ordered timeline and audit events for a task |  |  | 200:app__schemas__plan__TaskEventResponse[], 422:HTTPValidationError |

## MCP registry (admin)

| Method | Path | Summary | Body | Query | Responses |
|---|---|---|---|---|---|
| GET | `/mcp/servers` | List built-in MCP tools |  |  | 200:MCPServerSchema[] |
| POST | `/mcp/servers/{server_id}/ping` | Ping the built-in MCP dispatcher |  |  | 200:MCPServerSchema, 422:HTTPValidationError |

## Real-time events

| Method | Path | Summary | Body | Query | Responses |
|---|---|---|---|---|---|
| GET | `/events` | Subscribe to real-time platform events (SSE) |  |  | 200: |

## Health

| Method | Path | Summary | Body | Query | Responses |
|---|---|---|---|---|---|
| GET | `/health/live` | Check API liveness |  |  | 200:HealthResponse |
| GET | `/health` | Check API liveness (legacy/default) |  |  | 200:HealthResponse |
| GET | `/health/ready` | Check complete system readiness |  |  | 200:ReadinessResponse, 503 |

## Notes

- The `/repositories/{repository_id}/source/task/{action}` and `/source/task-workspace/{action}` routes are deprecated duplicates of the canonical `/tasks/{task_id}/*` surface and should not be used by new clients.
- `POST /tasks/{task_id}/publish` is an alias of `/create-pr`.
- `POST /repositories/{id}/chat` accepts `mode: "normal" | "agentic"`; the response is returned in full (no token streaming).
- MCP registry state is held in process memory (see Known limitations).
