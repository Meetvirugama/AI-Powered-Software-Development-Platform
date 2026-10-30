/**
 * Centralized React Query Hooks for Tasks, Plan Reviews, Approvals & Timelines.
 *
 * Source of truth:
 * - Docs/week3.md §6 & §7
 * - PROJECT.md (§ React Query Keys & Hooks)
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  listTasks,
  getTask,
  createTask,
  getTaskPlan,
  generateTaskPlan,
  approveTaskPlan,
  rejectTaskPlan,
  executeTask,
  getTaskEvents,
  getTaskTests,
  getTaskVerification,
  importGitHubIssue,
  listRepositoryIssues,
} from '../services/tasks';
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
import type { ApiError } from '../types/api';

// ============================================================================
// Query Key Factory
// ============================================================================

export const taskKeys = {
  all: ['tasks'] as const,
  lists: () => [...taskKeys.all, 'list'] as const,
  list: (filters?: TaskListFilterParams) => [...taskKeys.all, 'list', filters] as const,
  details: () => [...taskKeys.all, 'detail'] as const,
  detail: (taskId: string) => [...taskKeys.all, 'detail', taskId] as const,
  plans: () => [...taskKeys.all, 'plan'] as const,
  plan: (taskId: string, version?: number) =>
    [...taskKeys.all, 'detail', taskId, 'plan', version] as const,
  events: (taskId: string, params?: { limit?: number; since?: string }) =>
    [...taskKeys.all, 'detail', taskId, 'events', params] as const,
  tests: (taskId: string) => [...taskKeys.all, 'detail', taskId, 'tests'] as const,
  verification: (taskId: string) => [...taskKeys.all, 'detail', taskId, 'verification'] as const,
  repoIssues: (
    repoId: string,
    params?: { state?: 'open' | 'closed' | 'all'; page?: number; page_size?: number }
  ) => [...taskKeys.all, 'repoIssues', repoId, params] as const,
};

// ============================================================================
// Query Hooks
// ============================================================================

/**
 * Hook to retrieve a filtered and paginated list of tasks.
 */
export function useTasks(
  filters?: TaskListFilterParams,
  options?: { enabled?: boolean; refetchInterval?: number | false }
) {
  return useQuery<TaskListResponse, ApiError>({
    queryKey: taskKeys.list(filters),
    queryFn: () => listTasks(filters),
    ...options,
  });
}

/**
 * Hook to retrieve a single task by ID.
 */
export function useTask(taskId: string | undefined, options?: { enabled?: boolean }) {
  return useQuery<TaskDetailResponse, ApiError>({
    queryKey: taskKeys.detail(taskId || ''),
    queryFn: () => getTask(taskId!),
    enabled: Boolean(taskId) && (options?.enabled ?? true),
  });
}

/**
 * Hook to retrieve the active or specified plan for a task.
 */
export function useTaskPlan(
  taskId: string | undefined,
  version?: number,
  options?: { enabled?: boolean }
) {
  return useQuery<TaskPlan, ApiError>({
    queryKey: taskKeys.plan(taskId || '', version),
    queryFn: () => getTaskPlan(taskId!, version),
    enabled: Boolean(taskId) && (options?.enabled ?? true),
  });
}

/**
 * Hook to retrieve chronological lifecycle and audit events for a task.
 */
export function useTaskEvents(
  taskId: string | undefined,
  params?: { limit?: number; since?: string },
  options?: { enabled?: boolean }
) {
  return useQuery<TaskEventListResponse, ApiError>({
    queryKey: taskKeys.events(taskId || '', params),
    queryFn: () => getTaskEvents(taskId!, params),
    enabled: Boolean(taskId) && (options?.enabled ?? true),
  });
}

/**
 * Hook to retrieve test execution telemetry and repair attempt count.
 */
export function useTaskTests(taskId: string | undefined, options?: { enabled?: boolean }) {
  return useQuery<TaskTestResultsResponse, ApiError>({
    queryKey: taskKeys.tests(taskId || ''),
    queryFn: () => getTaskTests(taskId!),
    enabled: Boolean(taskId) && (options?.enabled ?? true),
  });
}

/**
 * Hook to retrieve independent verification result.
 */
export function useTaskVerification(taskId: string | undefined, options?: { enabled?: boolean }) {
  return useQuery<VerificationResult, ApiError>({
    queryKey: taskKeys.verification(taskId || ''),
    queryFn: () => getTaskVerification(taskId!),
    enabled: Boolean(taskId) && (options?.enabled ?? true),
  });
}

/**
 * Hook to list candidate GitHub issues available for import from a repository.
 */
export function useRepositoryIssues(
  repositoryId: string | undefined,
  params?: { state?: 'open' | 'closed' | 'all'; page?: number; page_size?: number },
  options?: { enabled?: boolean }
) {
  return useQuery<GitHubIssueListResponse, ApiError>({
    queryKey: taskKeys.repoIssues(repositoryId || '', params),
    queryFn: () => listRepositoryIssues(repositoryId!, params),
    enabled: Boolean(repositoryId) && (options?.enabled ?? true),
  });
}

// ============================================================================
// Mutation Hooks with Cache Invalidation
// ============================================================================

/**
 * Mutation hook to register a new task intake.
 * Invalidates task list queries upon success.
 */
export function useCreateTask() {
  const queryClient = useQueryClient();

  return useMutation<TaskDetailResponse, ApiError, TaskCreateRequest>({
    mutationFn: (payload: TaskCreateRequest) => createTask(payload),
    onSuccess: (newTask) => {
      queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
      queryClient.setQueryData(taskKeys.detail(newTask.task_id), newTask);
    },
  });
}

/**
 * Mutation hook to import a GitHub issue into a task.
 * Invalidates task lists and repository issue candidate queries.
 */
export function useImportIssue(repositoryId: string) {
  const queryClient = useQueryClient();

  return useMutation<IssueImportResponse, ApiError, IssueImportRequest>({
    mutationFn: (payload: IssueImportRequest) => importGitHubIssue(repositoryId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
      queryClient.invalidateQueries({ queryKey: [...taskKeys.all, 'repoIssues', repositoryId] });
    },
  });
}

/**
 * Mutation hook to synthesize or revise a structured plan.
 * Invalidates task detail, plan queries, and timeline events.
 */
export function useGeneratePlan(taskId: string) {
  const queryClient = useQueryClient();

  return useMutation<TaskPlan, ApiError, PlanGenerateRequest | undefined>({
    mutationFn: (payload?: PlanGenerateRequest) => generateTaskPlan(taskId, payload),
    onSuccess: (newPlan) => {
      queryClient.invalidateQueries({ queryKey: taskKeys.detail(taskId) });
      queryClient.invalidateQueries({ queryKey: taskKeys.plan(taskId) });
      queryClient.invalidateQueries({ queryKey: taskKeys.events(taskId) });
      queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
      queryClient.setQueryData(taskKeys.plan(taskId, newPlan.plan_version), newPlan);
    },
  });
}

/**
 * Mutation hook to approve a structured plan.
 * Verifies exact plan_version and invalidates task detail, plan, events, and task list.
 */
export function useApprovePlan(taskId: string) {
  const queryClient = useQueryClient();

  return useMutation<TaskDetailResponse, ApiError, PlanApprovalRequest>({
    mutationFn: (payload: PlanApprovalRequest) => approveTaskPlan(taskId, payload),
    onSuccess: (updatedTask) => {
      queryClient.invalidateQueries({ queryKey: taskKeys.detail(taskId) });
      queryClient.invalidateQueries({ queryKey: taskKeys.plan(taskId) });
      queryClient.invalidateQueries({ queryKey: taskKeys.events(taskId) });
      queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
      queryClient.setQueryData(taskKeys.detail(taskId), updatedTask);
    },
  });
}

/**
 * Mutation hook to reject a structured plan.
 * Verifies exact plan_version and invalidates task detail, plan, events, and task list.
 */
export function useRejectPlan(taskId: string) {
  const queryClient = useQueryClient();

  return useMutation<TaskDetailResponse, ApiError, PlanRejectionRequest>({
    mutationFn: (payload: PlanRejectionRequest) => rejectTaskPlan(taskId, payload),
    onSuccess: (updatedTask) => {
      queryClient.invalidateQueries({ queryKey: taskKeys.detail(taskId) });
      queryClient.invalidateQueries({ queryKey: taskKeys.plan(taskId) });
      queryClient.invalidateQueries({ queryKey: taskKeys.events(taskId) });
      queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
      queryClient.setQueryData(taskKeys.detail(taskId), updatedTask);
    },
  });
}

/**
 * Mutation hook to dispatch workspace execution (for backend/integration test verification).
 */
export function useExecuteTask(taskId: string) {
  const queryClient = useQueryClient();

  return useMutation<TaskDetailResponse, ApiError, { dry_run?: boolean } | undefined>({
    mutationFn: (payload?: { dry_run?: boolean }) => executeTask(taskId, payload),
    onSuccess: (updatedTask) => {
      queryClient.invalidateQueries({ queryKey: taskKeys.detail(taskId) });
      queryClient.invalidateQueries({ queryKey: taskKeys.events(taskId) });
      queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
      queryClient.setQueryData(taskKeys.detail(taskId), updatedTask);
    },
  });
}
