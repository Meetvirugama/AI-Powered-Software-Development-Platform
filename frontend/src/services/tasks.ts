/**
 * Typed API Service Layer for Week 3 Tasks, Structured Planning, Isolated Workspace, Tests & Bounded Repair.
 *
 * Uses the centralized apiClient instance from './api'.
 * Strictly typed with types from '../types/task'.
 */

import { apiClient, AI_ANALYSIS_TIMEOUT_MS } from './api';
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
  TaskApproval,
  TaskCreateRequest,
  TaskDetail,
  TaskDetailResponse,
  TaskDiffRanges,
  TaskEvent,
  TaskEventListResponse,
  TaskListFilterParams,
  TaskListResponse,
  TaskPlan,
  TaskTestResultsResponse,
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
  TaskEvent,
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
  const response = await apiClient.post<TaskDetailResponse>(`/tasks/${taskId}/execute`, payload || {});
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
    } catch {
      const fallback = await apiClient.get<TaskDiffRanges>(`/tasks/${taskId}/diff`);
      return fallback.data;
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
// Events, Tests & Verification Service Functions
// ============================================================================

/**
 * Retrieve chronological stream of lifecycle and audit events for a task.
 * GET /api/v1/tasks/:taskId/events
 *
 * Normalizes array vs { items, total } responses so that callers can use
 * either `eventsRes.items` or iterate over `eventsRes` directly as an array.
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
 * Retrieve independent verification and final review outcome for a task.
 * GET /api/v1/tasks/:taskId/verification
 */
export async function getTaskVerification(taskId: string): Promise<VerificationResult> {
  const response = await apiClient.get<VerificationResult>(`/tasks/${taskId}/verification`);
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
 *
 * Normalizes both raw array responses and `{ items, total }` envelopes so callers
 * can either iterate over the return value or access `.items`.
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
