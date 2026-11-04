/**
 * Typed API Service Layer for Week 3 Tasks, Structured Planning, Isolated Workspace, Tests, Bounded Repair, Independent Verification, Draft PR & Crash Recovery.
 *
 * Uses the centralized apiClient instance from './api'.
 * Strictly typed with types from '../types/task'.
 */

import { apiClient, AI_ANALYSIS_TIMEOUT_MS } from './api';
import type { ApiError } from '../types/api';
import type {
  CreateIssueFromFindingPayload,
  CreateTaskPayload,
  GitHubIssueItem,
  GitHubIssueListResponse,
  ImportIssuePayload,
  IssueImportRequest,
  IssueImportResponse,
  PlanApprovalRequest,
  PlanGenerateRequest,
  PlanRejectionRequest,
  PublishTaskRequest,
  StaleRevisionCheckResult,
  TaskApproval,
  TaskCheckpointResponse,
  TaskCreateRequest,
  TaskDetail,
  TaskDetailResponse,
  TaskDiffRanges,
  TaskEvent,
  TaskEventListResponse,
  TaskListFilterParams,
  TaskListResponse,
  TaskPlan,
  TaskPullRequest,
  TaskPullRequestResponse,
  TaskPublicationResponse,
  TaskRecoveryRequest,
  TaskRecoveryResponse,
  TaskTestResultsResponse,
  TriggerVerificationRequest,
  VerificationResult,
  WorkspaceMetadata,
  WorkspaceRepairBudgetStatus,
} from '../types/task';

export type {
  CreateTaskPayload,
  GitHubIssueItem,
  GitHubIssueListResponse,
  ImportIssuePayload,
  TaskApproval,
  TaskCheckpointResponse,
  TaskEvent,
  TaskPullRequestResponse,
  TaskRecoveryResponse,
};

// ============================================================================
// Task Intake & Detail Service Functions
// ============================================================================

/**
 * Retrieve a paginated list of tasks filtered by repository, status, or search query.
 * GET /api/v1/tasks
 */
export async function listTasks(params?: TaskListFilterParams): Promise<TaskListResponse> {
  const response = await apiClient.get<TaskListResponse>('/tasks', { params });
  return response.data;
}

/**
 * Retrieve full task detail including requirements, assumptions, and lifecycle metadata.
 * GET /api/v1/tasks/:taskId
 */
export async function getTask(taskId: string): Promise<TaskDetailResponse> {
  const response = await apiClient.get<TaskDetailResponse>(`/tasks/${taskId}`);
  return response.data;
}

/**
 * Alias for getTask to support both caller conventions.
 */
export async function getTaskDetail(taskId: string): Promise<TaskDetail> {
  return getTask(taskId);
}

/**
 * Register a new task intake with segregated requirements, assumptions, and constraints.
 * POST /api/v1/tasks
 */
export async function createTask(payload: TaskCreateRequest): Promise<TaskDetailResponse> {
  const response = await apiClient.post<TaskDetailResponse>('/tasks', payload);
  return response.data;
}

// ============================================================================
// Plan Management & Approval Gate Service Functions
// ============================================================================

/**
 * Retrieve the active or specified version of a structured implementation plan.
 * GET /api/v1/tasks/:taskId/plan
 */
export async function getTaskPlan(taskId: string, version?: number): Promise<TaskPlan> {
  const response = await apiClient.get<TaskPlan>(`/tasks/${taskId}/plan`, {
    params: version ? { version } : undefined,
  });
  return response.data;
}

/**
 * Trigger AI planner to generate or regenerate a structured plan (increments plan_version).
 * POST /api/v1/tasks/:taskId/plan
 */
export async function generateTaskPlan(
  taskId: string,
  payload?: PlanGenerateRequest
): Promise<TaskPlan> {
  const response = await apiClient.post<TaskPlan>(`/tasks/${taskId}/plan`, payload || {}, {
    timeout: AI_ANALYSIS_TIMEOUT_MS,
  });
  return response.data;
}

/**
 * Explicit human approval of an implementation plan. Requires exact plan_version.
 * POST /api/v1/tasks/:taskId/approve
 */
export async function approveTaskPlan(
  taskId: string,
  payload: PlanApprovalRequest
): Promise<any> {
  const response = await apiClient.post<any>(`/tasks/${taskId}/approve`, payload);
  return response.data;
}

/**
 * Explicit human rejection of an implementation plan. Requires exact plan_version.
 * POST /api/v1/tasks/:taskId/reject
 */
export async function rejectTaskPlan(
  taskId: string,
  payload: PlanRejectionRequest
): Promise<any> {
  const response = await apiClient.post<any>(`/tasks/${taskId}/reject`, payload);
  return response.data;
}

/**
 * Dispatch task for workspace execution.
 * POST /api/v1/tasks/:taskId/execute
 */
export async function executeTask(
  taskId: string,
  payload?: {
    dry_run?: boolean;
    run_steps?: boolean;
    step_payloads?: Record<string, unknown>;
    run_tests_after?: boolean;
    auto_repair?: boolean;
  }
): Promise<TaskDetailResponse> {
  const response = await apiClient.post<TaskDetailResponse>(
    `/tasks/${taskId}/execute`,
    payload || {},
    {
      timeout: AI_ANALYSIS_TIMEOUT_MS,
    }
  );
  return response.data;
}

/**
 * Alias for executeTask to support both caller conventions.
 */
export async function executeApprovedTask(taskId: string): Promise<TaskDetail> {
  return executeTask(taskId);
}

/**
 * Pause active execution in the task's isolated workspace.
 * POST /api/v1/tasks/:taskId/pause
 */
export async function pauseTask(
  taskId: string,
  reason = 'Paused by operator.'
): Promise<TaskDetailResponse> {
  const response = await apiClient.post<TaskDetailResponse>(`/tasks/${taskId}/pause`, { reason });
  return response.data;
}

/**
 * Resume paused execution in the task's isolated workspace.
 * POST /api/v1/tasks/:taskId/resume
 */
export async function resumeTask(taskId: string): Promise<TaskDetailResponse> {
  const response = await apiClient.post<TaskDetailResponse>(`/tasks/${taskId}/resume`, {});
  return response.data;
}

/**
 * Cancel an active or pending task.
 * POST /api/v1/tasks/:taskId/cancel
 */
export async function cancelTask(taskId: string): Promise<TaskDetailResponse> {
  const response = await apiClient.post<TaskDetailResponse>(`/tasks/${taskId}/cancel`);
  return response.data;
}

/**
 * Retrieve isolated workspace metadata for a task.
 * GET /api/v1/tasks/:taskId/workspace
 */
export async function getTaskWorkspace(taskId: string): Promise<WorkspaceMetadata> {
  const response = await apiClient.get<WorkspaceMetadata>(`/tasks/${taskId}/workspace`);
  return response.data;
}

/**
 * Retrieve code modifications and git diff telemetry for a task.
 * Supports repository-scoped diff route with fallback to task-centric route.
 */
export async function getTaskDiff(
  taskId: string,
  repositoryId?: string
): Promise<TaskDiffRanges> {
  if (repositoryId) {
    try {
      const response = await apiClient.get<TaskDiffRanges>(
        `/repositories/${repositoryId}/source/diff-ranges/task/${taskId}`
      );
      return response.data;
    } catch (err: unknown) {
      const apiErr = err as ApiError;
      // Fallback to task-centric route ONLY when repository-scoped route returns HTTP 404
      if (apiErr?.status === 404 || apiErr?.code === 'NOT_FOUND') {
        const fallback = await apiClient.get<TaskDiffRanges>(`/tasks/${taskId}/diff`);
        return fallback.data;
      }
      throw err;
    }
  }
  const response = await apiClient.get<TaskDiffRanges>(`/tasks/${taskId}/diff`);
  return response.data;
}

/**
 * Invoke a policy-guarded workspace tool via ToolRouter.
 * POST /api/v1/tasks/:taskId/tools/:toolName
 */
export async function invokeTaskTool(
  taskId: string,
  toolName: string,
  argumentsPayload: Record<string, unknown>
): Promise<{ task_id: string; tool_name: string; success: boolean; output: unknown; error?: string | null }> {
  const response = await apiClient.post(`/tasks/${taskId}/tools/${toolName}`, {
    arguments: argumentsPayload,
  });
  return response.data;
}

/**
 * Retrieve server-authoritative repair budget status.
 * GET /api/v1/tasks/:taskId/repair-budget
 */
export async function getTaskRepairBudget(taskId: string): Promise<WorkspaceRepairBudgetStatus> {
  const response = await apiClient.get<WorkspaceRepairBudgetStatus>(`/tasks/${taskId}/repair-budget`);
  return response.data;
}

/**
 * Trigger bounded self-repair cycle (max 3 attempts).
 * POST /api/v1/tasks/:taskId/repair
 */
export async function triggerTaskRepair(
  taskId: string,
  payload?: {
    framework?: string;
    test_path?: string;
    patch_diff?: string;
    patch_explanation?: string;
    target_files?: string[];
  }
): Promise<WorkspaceRepairBudgetStatus & { success?: boolean; final_test_status?: string; final_output_summary?: string }> {
  const response = await apiClient.post(`/tasks/${taskId}/repair`, payload || {}, {
    timeout: AI_ANALYSIS_TIMEOUT_MS,
  });
  return response.data;
}

// ============================================================================
// Events, Tests, Verification, Git Publication & Recovery Service Functions
// ============================================================================

/**
 * Retrieve chronological stream of lifecycle and audit events for a task.
 * GET /api/v1/tasks/:taskId/events
 */
export async function getTaskEvents(
  taskId: string,
  params?: { limit?: number; since?: string }
): Promise<TaskEventListResponse> {
  const response = await apiClient.get<any>(`/tasks/${taskId}/events`, { params });
  const raw = response.data;
  if (Array.isArray(raw)) {
    const list = [...raw] as any;
    list.items = raw;
    list.total = raw.length;
    return list as TaskEventListResponse;
  }
  const items = Array.isArray(raw?.items) ? raw.items : [];
  const list = [...items] as any;
  list.items = items;
  list.total = typeof raw?.total === 'number' ? raw.total : items.length;
  return list as TaskEventListResponse;
}

/**
 * Retrieve test execution telemetry and bounded repair attempt counts.
 * GET /api/v1/tasks/:taskId/tests
 */
export async function getTaskTests(taskId: string): Promise<TaskTestResultsResponse> {
  const response = await apiClient.get<TaskTestResultsResponse>(`/tasks/${taskId}/tests`);
  return response.data;
}

/**
 * Trigger restricted test suite execution inside the task workspace.
 * POST /api/v1/tasks/:taskId/tests
 */
export async function triggerTaskTests(
  taskId: string,
  payload?: { test_path?: string; framework?: string; arguments?: string[]; timeout_seconds?: number }
): Promise<TaskTestResultsResponse> {
  const response = await apiClient.post<TaskTestResultsResponse>(`/tasks/${taskId}/tests`, payload || {}, {
    timeout: AI_ANALYSIS_TIMEOUT_MS,
  });
  return response.data;
}

/**
 * Execute independent multi-dimensional verification over workspace changes.
 * POST /api/v1/tasks/:taskId/verify
 */
export async function triggerTaskVerification(
  taskId: string,
  payload?: TriggerVerificationRequest
): Promise<VerificationResult> {
  const response = await apiClient.post<VerificationResult>(`/tasks/${taskId}/verify`, payload || {}, {
    timeout: AI_ANALYSIS_TIMEOUT_MS,
  });
  return response.data;
}

/**
 * Retrieve independent verification and final review outcome for a task.
 * GET /api/v1/tasks/:taskId/verification
 */
export async function getTaskVerification(taskId: string): Promise<VerificationResult | null> {
  try {
    const response = await apiClient.get<VerificationResult>(`/tasks/${taskId}/verification`);
    return response.data;
  } catch (err: unknown) {
    const apiErr = err as ApiError;
    if (apiErr?.code === 'NOT_FOUND' || apiErr?.status === 404) {
      return null;
    }
    throw err;
  }
}

/**
 * Ensure isolated task branch agent/task-<id> and reject protected branches.
 * POST /api/v1/tasks/:taskId/branch
 */
export async function ensureTaskBranch(
  taskId: string,
  branchName?: string
): Promise<{
  task_id: string;
  repository_id: string;
  branch_name: string;
  base_revision: string;
  workspace_status: string;
  is_protected: boolean;
}> {
  const response = await apiClient.post(`/tasks/${taskId}/branch`, branchName ? { branch_name: branchName } : {});
  return response.data;
}

/**
 * Stage and commit validated workspace changes on the task branch.
 * POST /api/v1/tasks/:taskId/commit
 */
export async function commitTaskChanges(
  taskId: string,
  payload?: {
    message?: string;
    branch_name?: string;
    files?: string[];
    author_name?: string;
    author_email?: string;
  }
): Promise<{
  success: boolean;
  task_id: string;
  commit_sha: string;
  branch: string;
  message: string;
  files_committed: string[];
}> {
  const response = await apiClient.post(`/tasks/${taskId}/commit`, payload || {});
  return response.data;
}

/**
 * Push verified task branch after checking human publication authorization.
 * POST /api/v1/tasks/:taskId/push
 */
export async function pushTaskBranch(
  taskId: string,
  payload: {
    publication_authorized: boolean;
    branch_name?: string;
    remote_name?: string;
    current_remote_head_sha?: string;
  }
): Promise<{
  success: boolean;
  task_id: string;
  branch: string;
  pushed_sha: string;
  remote_name: string;
}> {
  const response = await apiClient.post(`/tasks/${taskId}/push`, payload);
  return response.data;
}

/**
 * Create a reviewable GitHub Draft Pull Request (is_draft=True, zero auto-merge).
 * POST /api/v1/tasks/:taskId/create-pr
 */
export async function createTaskDraftPR(
  taskId: string,
  payload: {
    publication_authorized: boolean;
    title?: string;
    body?: string;
    base_branch?: string;
    head_branch?: string;
  }
): Promise<TaskPullRequestResponse> {
  const response = await apiClient.post<TaskPullRequestResponse>(`/tasks/${taskId}/create-pr`, payload);
  return response.data;
}

/**
 * Retrieve GitHub Pull Request metadata associated with a published task.
 * Returns null if the PR does not exist (404).
 * Supports repository-scoped PR metadata route with fallback to canonical task-centric route.
 * GET /api/v1/repositories/:repositoryId/source/pr-metadata/:taskId
 * GET /api/v1/tasks/:taskId/pull-request
 */
export async function getTaskPullRequest(
  taskId: string,
  repositoryId?: string
): Promise<TaskPullRequest | null> {
  if (repositoryId) {
    try {
      const response = await apiClient.get<{
        task_id?: string;
        pr_number?: number | null;
        pr_url?: string | null;
        commit_message?: string;
        verification_summary?: string;
        branch?: string;
        base_branch?: string;
        status?: string;
      }>(`/repositories/${repositoryId}/source/pr-metadata/${taskId}`);
      if (response.data && (response.data.pr_url || response.data.pr_number)) {
        return {
          task_id: response.data.task_id || taskId,
          pr_number: response.data.pr_number,
          pr_url: response.data.pr_url || '',
          title: response.data.commit_message || 'Draft Pull Request',
          body: response.data.verification_summary,
          head_branch: response.data.branch || '',
          base_branch: response.data.base_branch || 'main',
          is_draft: true,
          status: response.data.status,
          created_at: new Date().toISOString(),
        };
      }
    } catch (err: unknown) {
      const apiErr = err as ApiError;
      if (apiErr?.code !== 'NOT_FOUND' && apiErr?.status !== 404) {
        throw err;
      }
    }
  }

  try {
    const response = await apiClient.get<TaskPullRequest>(`/tasks/${taskId}/pull-request`);
    return response.data;
  } catch (err: unknown) {
    const apiErr = err as ApiError;
    if (apiErr?.code === 'NOT_FOUND' || apiErr?.status === 404) {
      return null;
    }
    throw err;
  }
}

/**
 * Explicit human publication authorization gate.
 * Authorizes pushing the task branch to remote and opening a GitHub Draft PR.
 * POST /api/v1/tasks/:taskId/publish (with fallback to /tasks/:taskId/create-pr)
 */
export async function publishDraftPR(
  taskId: string,
  payload: PublishTaskRequest
): Promise<TaskPublicationResponse> {
  try {
    const response = await apiClient.post<TaskPublicationResponse>(
      `/tasks/${taskId}/publish`,
      payload
    );
    return response.data;
  } catch (err: unknown) {
    const apiErr = err as ApiError;
    // Fallback to /create-pr if backend exposes that canonical path
    if (apiErr?.status === 404 || apiErr?.code === 'NOT_FOUND') {
      const fallbackResponse = await apiClient.post<TaskPublicationResponse>(
        `/tasks/${taskId}/create-pr`,
        payload
      );
      return fallbackResponse.data;
    }
    throw err;
  }
}

/**
 * Save a secret-scrubbed recovery checkpoint for a task.
 * POST /api/v1/tasks/:taskId/checkpoints
 */
export async function saveTaskCheckpoint(
  taskId: string,
  payload: {
    step_name: string;
    state_data?: Record<string, unknown>;
    recovery_instructions?: string;
  }
): Promise<TaskCheckpointResponse> {
  const response = await apiClient.post<TaskCheckpointResponse>(`/tasks/${taskId}/checkpoints`, payload);
  return response.data;
}

/**
 * List persisted recovery checkpoints for a task.
 * GET /api/v1/tasks/:taskId/checkpoints
 */
export async function listTaskCheckpoints(taskId: string): Promise<TaskCheckpointResponse[]> {
  const response = await apiClient.get<TaskCheckpointResponse[]>(`/tasks/${taskId}/checkpoints`);
  return response.data;
}

/**
 * Execute recovery and state reconciliation for an interrupted, blocked, or failed task.
 * POST /api/v1/tasks/:taskId/recover
 */
export async function recoverTask(
  taskId: string,
  payload?: TaskRecoveryRequest | string
): Promise<TaskRecoveryResponse> {
  const body =
    typeof payload === 'string'
      ? { target_status: payload }
      : payload || {};
  const response = await apiClient.post<TaskRecoveryResponse>(
    `/tasks/${taskId}/recover`,
    body
  );
  return response.data;
}

/**
 * Run Day 6 sandbox security, path confinement, disk budget, and diff immutability checks.
 * GET /api/v1/tasks/:taskId/invariants
 */
export async function checkTaskInvariants(
  taskId: string
): Promise<{
  task_id: string;
  valid: boolean;
  violations: string[];
  disk_budget?: Record<string, unknown> | null;
  diff_immutability?: Record<string, unknown> | null;
}> {
  const response = await apiClient.get(`/tasks/${taskId}/invariants`);
  return response.data;
}

/**
 * Execute the Day 7 autonomous post-approval workflow end-to-end.
 * POST /api/v1/tasks/:taskId/run-workflow
 */
export async function runTaskAutonomousWorkflow(
  taskId: string,
  payload?: {
    step_payloads?: Record<string, unknown>;
    run_tests?: boolean;
    auto_repair?: boolean;
    publication_authorized?: boolean;
    pr_title?: string;
    pr_body?: string;
  }
): Promise<{
  task_id: string;
  status: string;
  verification?: VerificationResult | null;
  pull_request?: TaskPullRequestResponse | null;
}> {
  const response = await apiClient.post(`/tasks/${taskId}/run-workflow`, payload || {}, {
    timeout: AI_ANALYSIS_TIMEOUT_MS,
  });
  return response.data;
}

// ============================================================================
// GitHub Issue Intake Service Functions
// ============================================================================

/**
 * Ingest an external GitHub issue and normalize it into an internal task.
 * POST /api/v1/repositories/:repositoryId/issues/import
 */
export async function importGitHubIssue(
  repositoryId: string,
  payload: IssueImportRequest
): Promise<IssueImportResponse> {
  const response = await apiClient.post<IssueImportResponse>(
    `/repositories/${repositoryId}/issues/import`,
    payload
  );
  return response.data;
}

/**
 * List candidate GitHub issues available for import from a repository.
 * GET /api/v1/repositories/:repositoryId/issues
 */
export async function listRepositoryIssues(
  repositoryId: string,
  params?: { state?: 'open' | 'closed' | 'all'; page?: number; page_size?: number; syncRemote?: boolean }
): Promise<GitHubIssueListResponse> {
  const response = await apiClient.get<any>(
    `/repositories/${repositoryId}/issues`,
    {
      params: {
        state: params?.state ?? 'all',
        page: params?.page,
        page_size: params?.page_size,
        sync_remote: params?.syncRemote ?? false,
      },
    }
  );
  const raw = response.data;
  if (Array.isArray(raw)) {
    const normalized = raw.map((item: any) => ({
      ...item,
      url: item.url || item.html_url || '',
      is_imported: Boolean(item.is_imported ?? item.task_id),
    }));
    const list = [...normalized] as any;
    list.items = normalized;
    list.total = normalized.length;
    list.page = params?.page ?? 1;
    list.page_size = params?.page_size ?? 20;
    return list as GitHubIssueListResponse;
  }
  const items = Array.isArray(raw?.items)
    ? raw.items.map((item: any) => ({
        ...item,
        url: item.url || item.html_url || '',
        is_imported: Boolean(item.is_imported ?? item.task_id),
      }))
    : [];
  const list = [...items] as any;
  list.items = items;
  list.total = typeof raw?.total === 'number' ? raw.total : items.length;
  list.page = raw?.page ?? params?.page ?? 1;
  list.page_size = raw?.page_size ?? params?.page_size ?? 20;
  return list as GitHubIssueListResponse;
}

/**
 * Create a new GitHub issue from a bug/review finding.
 * POST /api/v1/repositories/:repositoryId/issues
 */
export async function createGitHubIssue(
  repositoryId: string,
  payload: CreateIssueFromFindingPayload
): Promise<IssueImportResponse> {
  const response = await apiClient.post<IssueImportResponse>(
    `/repositories/${repositoryId}/issues`,
    payload
  );
  return response.data;
}

/**
 * Explicitly authorize branch publication (READY_FOR_PUBLICATION -> PUBLISHING).
 * POST /api/v1/tasks/:taskId/authorize-publication
 */
export async function authorizeTaskPublication(
  taskId: string,
  payload: { head_sha: string; notes?: string }
): Promise<{
  task_id: string;
  status: string;
  head_sha: string;
  authorized: boolean;
  user_id?: string | null;
  authorized_at?: string | null;
}> {
  const response = await apiClient.post(`/tasks/${taskId}/authorize-publication`, payload);
  return response.data;
}

/**
 * Retrieve end-to-end audit traceability graph from finding/issue to Draft PR.
 * GET /api/v1/tasks/:taskId/traceability
 */
export async function getTaskTraceability(taskId: string): Promise<Record<string, any>> {
  const response = await apiClient.get<Record<string, any>>(`/tasks/${taskId}/traceability`);
  return response.data;
}

/**
 * Detect whether the workspace base revision has drifted relative to the repository/plan revision.
 * GET /api/v1/tasks/:taskId/stale-check
 */
export async function checkStaleRevision(
  taskId: string,
  currentRemoteHeadSha?: string
): Promise<StaleRevisionCheckResult> {
  const response = await apiClient.get<StaleRevisionCheckResult>(`/tasks/${taskId}/stale-check`, {
    params: currentRemoteHeadSha ? { current_remote_head_sha: currentRemoteHeadSha } : undefined,
  });
  return response.data;
}

/**
 * Compatibility aliases for Day 5-7 verification & Draft PR publication callers.
 */
export const triggerVerification = triggerTaskVerification;
