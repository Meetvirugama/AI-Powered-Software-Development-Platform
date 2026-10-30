/**
 * Typed API Service Layer for Week 3 Tasks, Structured Planning & Approvals.
 *
 * Uses the centralized apiClient instance from './api'.
 * All 13 endpoints are strictly typed with types from '../types/task'.
 */

import { apiClient } from './api';
import type {
  TaskCreateRequest,
  TaskDetailResponse,
  TaskListFilterParams,
  TaskListResponse,
  TaskPlan,
  PlanGenerateRequest,
  PlanApprovalRequest,
  PlanRejectionRequest,
  TaskEventListResponse,
  TaskTestResultsResponse,
  VerificationResult,
  IssueImportRequest,
  IssueImportResponse,
  GitHubIssueListResponse,
} from '../types/task';

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
  const response = await apiClient.post<TaskPlan>(`/tasks/${taskId}/plan`, payload || {});
  return response.data;
}

/**
 * Explicit human approval of an implementation plan. Requires exact plan_version.
 * POST /api/v1/tasks/:taskId/approve
 */
export async function approveTaskPlan(
  taskId: string,
  payload: PlanApprovalRequest
): Promise<TaskDetailResponse> {
  const response = await apiClient.post<TaskDetailResponse>(`/tasks/${taskId}/approve`, payload);
  return response.data;
}

/**
 * Explicit human rejection of an implementation plan. Requires exact plan_version.
 * POST /api/v1/tasks/:taskId/reject
 */
export async function rejectTaskPlan(
  taskId: string,
  payload: PlanRejectionRequest
): Promise<TaskDetailResponse> {
  const response = await apiClient.post<TaskDetailResponse>(`/tasks/${taskId}/reject`, payload);
  return response.data;
}

/**
 * Dispatch task for workspace execution. Prohibited in Day 1/2 UI workflows.
 * POST /api/v1/tasks/:taskId/execute
 */
export async function executeTask(
  taskId: string,
  payload?: { dry_run?: boolean }
): Promise<TaskDetailResponse> {
  const response = await apiClient.post<TaskDetailResponse>(`/tasks/${taskId}/execute`, payload || {});
  return response.data;
}

// ============================================================================
// Events, Tests & Verification Service Functions
// ============================================================================

/**
 * Retrieve chronological stream of lifecycle and audit events for a task.
 * GET /api/v1/tasks/:taskId/events
 */
export async function getTaskEvents(
  taskId: string,
  params?: { limit?: number; since?: string }
): Promise<TaskEventListResponse> {
  const response = await apiClient.get<TaskEventListResponse>(`/tasks/${taskId}/events`, { params });
  return response.data;
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
 */
export async function listRepositoryIssues(
  repositoryId: string,
  params?: { state?: 'open' | 'closed' | 'all'; page?: number; page_size?: number }
): Promise<GitHubIssueListResponse> {
  const response = await apiClient.get<GitHubIssueListResponse>(
    `/repositories/${repositoryId}/issues`,
    { params }
  );
  return response.data;
}
