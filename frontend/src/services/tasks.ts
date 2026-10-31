/**
 * Week 3 Day 1 & Day 2 Frontend Service Layer:
 * - F31 GitHub Issue Integration (`/repositories/:id/issues`, `/repositories/:id/issues/import`)
 * - F32 Task Planning & Human Approval Gate (`/tasks`, `/tasks/:id/plan`, `/tasks/:id/approve`, `/tasks/:id/reject`, `/tasks/:id/execute`, `/tasks/:id/events`)
 */

import { apiClient, AI_ANALYSIS_TIMEOUT_MS } from './api';
import type {
  CreateIssueFromFindingPayload,
  CreateTaskPayload,
  GitHubIssueItem,
  ImportIssuePayload,
  IssueImportResponse,
  PaginatedTaskListResponse,
  TaskApproval,
  TaskDetail,
  TaskEvent,
  TaskPlan,
} from '../types/task';

export async function importGitHubIssue(
  repositoryId: string,
  payload: ImportIssuePayload
): Promise<IssueImportResponse> {
  const { data } = await apiClient.post<IssueImportResponse>(
    `/repositories/${repositoryId}/issues/import`,
    payload
  );
  return data;
}

export async function listRepositoryIssues(
  repositoryId: string,
  options?: { state?: 'open' | 'closed' | 'all'; syncRemote?: boolean }
): Promise<GitHubIssueItem[]> {
  const { data } = await apiClient.get<GitHubIssueItem[]>(
    `/repositories/${repositoryId}/issues`,
    {
      params: {
        state: options?.state ?? 'all',
        sync_remote: options?.syncRemote ?? false,
      },
    }
  );
  return data;
}

export async function createGitHubIssue(
  repositoryId: string,
  payload: CreateIssueFromFindingPayload
): Promise<IssueImportResponse> {
  const { data } = await apiClient.post<IssueImportResponse>(
    `/repositories/${repositoryId}/issues`,
    payload
  );
  return data;
}

export async function createTask(payload: CreateTaskPayload): Promise<TaskDetail> {
  const { data } = await apiClient.post<TaskDetail>('/tasks', payload);
  return data;
}

export async function listTasks(params?: {
  repository_id?: string;
  status?: string;
  page?: number;
  page_size?: number;
}): Promise<PaginatedTaskListResponse> {
  const { data } = await apiClient.get<PaginatedTaskListResponse>('/tasks', {
    params,
  });
  return data;
}

export async function getTaskDetail(taskId: string): Promise<TaskDetail> {
  const { data } = await apiClient.get<TaskDetail>(`/tasks/${taskId}`);
  return data;
}

export async function generateTaskPlan(
  taskId: string,
  options?: { base_revision?: string; revision_notes?: string }
): Promise<TaskPlan> {
  const { data } = await apiClient.post<TaskPlan>(
    `/tasks/${taskId}/plan`,
    options ?? {},
    { timeout: AI_ANALYSIS_TIMEOUT_MS }
  );
  return data;
}

export async function getTaskPlan(taskId: string, version?: number): Promise<TaskPlan> {
  const { data } = await apiClient.get<TaskPlan>(`/tasks/${taskId}/plan`, {
    params: version ? { version } : undefined,
  });
  return data;
}

export async function approveTaskPlan(
  taskId: string,
  payload?: { plan_version?: number; base_revision?: string; comment?: string }
): Promise<TaskApproval> {
  const { data } = await apiClient.post<TaskApproval>(
    `/tasks/${taskId}/approve`,
    payload ?? {}
  );
  return data;
}

export async function rejectTaskPlan(
  taskId: string,
  payload: { plan_version?: number; reason: string }
): Promise<TaskApproval> {
  const { data } = await apiClient.post<TaskApproval>(
    `/tasks/${taskId}/reject`,
    payload
  );
  return data;
}

export async function executeApprovedTask(taskId: string): Promise<TaskDetail> {
  const { data } = await apiClient.post<TaskDetail>(`/tasks/${taskId}/execute`);
  return data;
}

export async function cancelTask(taskId: string): Promise<TaskDetail> {
  const { data } = await apiClient.post<TaskDetail>(`/tasks/${taskId}/cancel`);
  return data;
}

export async function getTaskEvents(taskId: string): Promise<TaskEvent[]> {
  const { data } = await apiClient.get<TaskEvent[]>(`/tasks/${taskId}/events`);
  return data;
}
