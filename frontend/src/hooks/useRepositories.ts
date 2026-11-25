import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { realtimeClient } from '../realtime/index';
import { useSyncProgressStore } from '../stores/useSyncProgressStore';
import {
  listRepositories,
  getRepository,
  getRepositoryFiles,
  getRepositoryDependencies,
  syncRepository,
  deleteRepository,
  getRepositoryFileContent,
  getRepositorySyncJobs,
  getRepositoryMetrics,
  getRepositoryBranches,
  switchRepositoryBranch,
  getRepositoryCommits,
  getRepositoryPullRequests,
} from '../services/repositories';
import type {
  PaginatedRepositoryResponse,
  Repository,
  SyncProgress,
  SyncStatus,
  PaginatedRepositoryFileResponse,
  RepositoryDependency,
  RepositoryFileContent,
  ApiError,
  SyncJob,
  RepositoryMetrics,
  RepositoryBranch,
  SwitchBranchResponse,
  RepositoryCommit,
  RepositoryPullRequest,
} from '../types/api';

/**
 * Query key factory for repository queries.
 *
 * Keeping keys in one place means invalidation (e.g. after an SSE event or
 * a successful Connect mutation) only needs to reference this factory,
 * not recreate key shapes.
 */
export const repositoryKeys = {
  all: ['repositories'] as const,
  lists: () => [...repositoryKeys.all, 'list'] as const,
  list: (page: number, pageSize: number) =>
    [...repositoryKeys.all, 'list', { page, pageSize }] as const,
  details: () => [...repositoryKeys.all, 'detail'] as const,
  detail: (id: string) => [...repositoryKeys.all, 'detail', id] as const,
  files: (id: string, page: number, pageSize: number) =>
    [...repositoryKeys.detail(id), 'files', { page, pageSize }] as const,
  fileContent: (id: string, fileId: string) =>
    [...repositoryKeys.detail(id), 'files', fileId, 'content'] as const,
  dependencies: (id: string) =>
    [...repositoryKeys.detail(id), 'dependencies'] as const,
  syncJobs: (id: string) => [...repositoryKeys.detail(id), 'sync-jobs'] as const,
  metrics: (id: string) => [...repositoryKeys.detail(id), 'metrics'] as const,
  branches: (id: string) => [...repositoryKeys.detail(id), 'branches'] as const,
  commits: (id: string, branch?: string) => [...repositoryKeys.detail(id), 'commits', branch ?? ''] as const,
  pulls: (id: string, state: string) => [...repositoryKeys.detail(id), 'pulls', state] as const,
};

export function useRepositories(
  page: number = 1,
  pageSize: number = 20,
  options?: {
    refetchInterval?:
      | number
      | false
      | ((query: { state: { data?: PaginatedRepositoryResponse } }) => number | false | undefined);
  },
) {
  return useQuery<PaginatedRepositoryResponse>({
    queryKey: repositoryKeys.list(page, pageSize),
    queryFn: () => listRepositories({ page, pageSize }),
    placeholderData: keepPreviousData,
    ...options,
  });
}

export function useRepository(
  id: string | undefined,
  options?: {
    refetchInterval?:
      | number
      | false
      | ((query: { state: { data?: Repository } }) => number | false | undefined);
  },
) {
  return useQuery<Repository>({
    queryKey: repositoryKeys.detail(id ?? ''),
    queryFn: () => getRepository(id!),
    enabled: Boolean(id),
    ...options,
  });
}

// ---------------------------------------------------------------------------
// syncProgressFromStatus — sync-stage adapter
//
// IMPORTANT: This function is the ONLY place in the frontend that maps
// backend SyncStatus values to the UI-facing SyncProgress representation.
//
// week1.md requires the step indicator:
//   Cloning → Scanning → Indexing → Ready
//
// Current backend SyncStatus enum (confirmed):
//   NOT_SYNCED | SYNCING | SYNCED | FAILED
//
// UNCONFIRMED: Whether the backend will expose intermediate stages
// (CLONING / SCANNING / INDEXING) as:
//   a) Additional SyncStatus values
//   b) A separate `sync_stage` field on RepositoryResponse
//   c) A dedicated job-status endpoint
//
// Current mapping (conservative — update when backend confirms):
//   NOT_SYNCED  → NOT_STARTED (no sync has run)
//   SYNCING     → CLONING     (we assume the earliest stage; backend will refine)
//   SYNCED      → READY
//   FAILED      → FAILED
//
// When the backend adds fine-grained stage information, add an overloaded
// signature that accepts a stage field and route through that. Only this
// function needs updating — hooks and UI read SyncProgress, not SyncStatus.
// ---------------------------------------------------------------------------

/**
 * Map a backend SyncStatus value to the UI-facing SyncProgress representation.
 *
 * @param status  The sync_status string from a Repository API response.
 * @returns SyncProgress consumed by the step-indicator UI component (Prompt 3).
 *
 * ASSUMPTION (unconfirmed, to be updated after backend confirms):
 *   The entire SYNCING state is represented as CLONING until the backend
 *   exposes the Scanning/Indexing intermediate stages.
 */
export function syncProgressFromStatus(status: SyncStatus, jobStage?: string | null): SyncProgress {
  switch (status) {
    case 'SYNCING': {
      // The backend now reports the running job's stage (GET /repositories/:id/sync-jobs).
      const stageMap: Record<string, { stage: SyncProgress['stage']; label: string }> = {
        CLONING: { stage: 'CLONING', label: 'Cloning repository…' },
        SCANNING: { stage: 'SCANNING', label: 'Scanning files…' },
        INDEXING: { stage: 'INDEXING', label: 'Indexing code…' },
        FINALIZING: { stage: 'INDEXING', label: 'Finalizing index…' },
      };
      const mapped = jobStage ? stageMap[jobStage] : undefined;
      if (mapped) {
        return { stage: mapped.stage, label: mapped.label, isActive: true, isComplete: false, isFailed: false };
      }
      // General syncing state without assuming specific sub-stages
      return {
        stage: 'SYNCING',
        label: 'Syncing repository…',
        isActive: true,
        isComplete: false,
        isFailed: false,
      };
    }

    case 'SYNCED':
      return {
        stage: 'READY',
        label: 'Ready',
        isActive: false,
        isComplete: true,
        isFailed: false,
      };

    case 'FAILED':
      return {
        stage: 'FAILED',
        label: 'Failed',
        isActive: false,
        isComplete: false,
        isFailed: true,
      };

    case 'NOT_SYNCED':
    default:
      return {
        stage: 'NOT_STARTED',
        label: 'Not synced',
        isActive: false,
        isComplete: false,
        isFailed: false,
      };
  }
}

// ---------------------------------------------------------------------------
// useRepositoryFiles — file tree hook
//
// Day 5 requires a 2-level file tree.
// ---------------------------------------------------------------------------

export function useRepositoryFiles(
  id: string | undefined,
  page: number = 1,
  pageSize: number = 50,
  options?: { enabled?: boolean },
) {
  return useQuery<PaginatedRepositoryFileResponse>({
    queryKey: repositoryKeys.files(id ?? '', page, pageSize),
    queryFn: () => getRepositoryFiles(id!, { page, pageSize }),
    enabled: Boolean(id) && (options?.enabled ?? true),
    placeholderData: keepPreviousData,
  });
}

// ---------------------------------------------------------------------------
// useRepositoryDependencies — dependencies hook
//
// Day 5 requires top-level dependencies.
// ---------------------------------------------------------------------------

export function useRepositoryDependencies(
  id: string | undefined,
  options?: { enabled?: boolean },
) {
  return useQuery<RepositoryDependency[]>({
    queryKey: repositoryKeys.dependencies(id ?? ''),
    queryFn: () => getRepositoryDependencies(id!),
    enabled: Boolean(id) && (options?.enabled ?? true),
  });
}

// ---------------------------------------------------------------------------
// Repository Actions: Sync, Delete, and File Content
// ---------------------------------------------------------------------------

type SyncMutationContext = {
  previousDetail?: Repository;
  previousLists: Array<[readonly unknown[], PaginatedRepositoryResponse | undefined]>;
};

type DeleteMutationContext = {
  previousLists: Array<[readonly unknown[], PaginatedRepositoryResponse | undefined]>;
};

/**
 * useSyncRepository — Triggers background synchronization for a repository.
 * Optimistically sets sync_status to SYNCING and rolls back on error.
 */
export function useSyncRepository() {
  const queryClient = useQueryClient();
  return useMutation<
    { job_id: string },
    ApiError,
    string | { id: string; force?: boolean },
    SyncMutationContext
  >({
    mutationFn: (param) => {
      const id = typeof param === 'string' ? param : param.id;
      const force = typeof param === 'string' ? false : Boolean(param.force);
      return syncRepository(id, force);
    },
    onMutate: async (param) => {
      const id = typeof param === 'string' ? param : param.id;
      await Promise.all([
        queryClient.cancelQueries({ queryKey: repositoryKeys.detail(id) }),
        queryClient.cancelQueries({ queryKey: repositoryKeys.lists() }),
      ]);

      const previousDetail = queryClient.getQueryData<Repository>(repositoryKeys.detail(id));
      const previousLists = queryClient.getQueriesData<PaginatedRepositoryResponse>({
        queryKey: repositoryKeys.lists(),
      });

      if (previousDetail) {
        queryClient.setQueryData<Repository>(repositoryKeys.detail(id), {
          ...previousDetail,
          sync_status: 'SYNCING',
          last_sync_error: null,
        });
      }

      queryClient.setQueriesData<PaginatedRepositoryResponse>(
        { queryKey: repositoryKeys.lists() },
        (old) => {
          if (!old) return old;
          return {
            ...old,
            items: old.items.map((repo) =>
              repo.id === id ? { ...repo, sync_status: 'SYNCING', last_sync_error: null } : repo,
            ),
          };
        },
      );

      useSyncProgressStore.getState().clearProgress(id);
      return { previousDetail, previousLists };
    },
    onError: (_err, param, context) => {
      const id = typeof param === 'string' ? param : param.id;
      if (context?.previousDetail) {
        queryClient.setQueryData(repositoryKeys.detail(id), context.previousDetail);
      }
      if (context?.previousLists) {
        for (const [key, data] of context.previousLists) {
          queryClient.setQueryData(key, data);
        }
      }
    },
    onSettled: (_data, _err, param) => {
      const id = typeof param === 'string' ? param : param.id;
      queryClient.invalidateQueries({ queryKey: repositoryKeys.detail(id) });
      queryClient.invalidateQueries({ queryKey: repositoryKeys.lists() });
      queryClient.invalidateQueries({ queryKey: repositoryKeys.syncJobs(id) });
    },
  });
}

/**
 * useDeleteRepository — Disconnects and deletes a repository.
 * Optimistically removes the repository from list caches and rolls back on error.
 */
export function useDeleteRepository() {
  const queryClient = useQueryClient();
  return useMutation<void, ApiError, string, DeleteMutationContext>({
    mutationFn: (id: string) => deleteRepository(id),
    onMutate: async (id: string) => {
      await queryClient.cancelQueries({ queryKey: repositoryKeys.lists() });
      const previousLists = queryClient.getQueriesData<PaginatedRepositoryResponse>({
        queryKey: repositoryKeys.lists(),
      });

      queryClient.setQueriesData<PaginatedRepositoryResponse>(
        { queryKey: repositoryKeys.lists() },
        (old) => {
          if (!old) return old;
          const nextItems = old.items.filter((repo) => repo.id !== id);
          const removedCount = old.items.length - nextItems.length;
          return {
            ...old,
            items: nextItems,
            total: Math.max(0, old.total - removedCount),
          };
        },
      );

      return { previousLists };
    },
    onError: (_err, _id, context) => {
      if (context?.previousLists) {
        for (const [key, data] of context.previousLists) {
          queryClient.setQueryData(key, data);
        }
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: repositoryKeys.all });
    },
  });
}

/**
 * useRepositoryFileContent — Fetches indexed code content and symbols for a file.
 */
export function useRepositoryFileContent(
  repositoryId: string | undefined,
  fileId: string | undefined,
) {
  return useQuery<RepositoryFileContent>({
    queryKey: repositoryKeys.fileContent(repositoryId ?? '', fileId ?? ''),
    queryFn: () => getRepositoryFileContent(repositoryId!, fileId!),
    enabled: Boolean(repositoryId && fileId),
  });
}



// ---------------------------------------------------------------------------
// Sync status, metrics and live GitHub data
// ---------------------------------------------------------------------------

/** Recent sync jobs; falls back to 20s polling only when SSE is disconnected while active. */
export function useRepositorySyncJobs(id: string | undefined, limit = 10) {
  return useQuery<SyncJob[], ApiError>({
    queryKey: repositoryKeys.syncJobs(id ?? ''),
    queryFn: () => getRepositorySyncJobs(id!, limit),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      if (realtimeClient.isConnected) return false;
      const latest = query.state.data?.[0];
      return latest && (latest.status === 'QUEUED' || latest.status === 'RUNNING') ? 20_000 : false;
    },
  });
}

export function useRepositoryMetrics(id: string | undefined) {
  return useQuery<RepositoryMetrics, ApiError>({
    queryKey: repositoryKeys.metrics(id ?? ''),
    queryFn: () => getRepositoryMetrics(id!),
    enabled: Boolean(id),
    staleTime: 30_000,
  });
}

/** Live GitHub data: a missing GitHub App (503/409) is not worth retrying. */
const githubQueryDefaults = { staleTime: 60_000, retry: 1 } as const;

export function useRepositoryBranches(
  id: string | undefined,
  options?: { enabled?: boolean },
) {
  return useQuery<RepositoryBranch[], ApiError>({
    queryKey: repositoryKeys.branches(id ?? ''),
    queryFn: () => getRepositoryBranches(id!),
    enabled: Boolean(id) && (options?.enabled ?? true),
    ...githubQueryDefaults,
  });
}

type SwitchBranchContext = {
  previousDetail?: Repository;
  previousLists: Array<[readonly unknown[], PaginatedRepositoryResponse | undefined]>;
};

/**
 * useSwitchRepositoryBranch — Switches the active tracked branch and queues re-indexing.
 * Optimistically updates default_branch and sync_status to SYNCING, rolling back on error.
 */
export function useSwitchRepositoryBranch() {
  const queryClient = useQueryClient();
  return useMutation<
    SwitchBranchResponse,
    ApiError,
    { id: string; branch: string },
    SwitchBranchContext
  >({
    mutationFn: ({ id, branch }) => switchRepositoryBranch(id, branch),
    onMutate: async ({ id, branch }) => {
      await Promise.all([
        queryClient.cancelQueries({ queryKey: repositoryKeys.detail(id) }),
        queryClient.cancelQueries({ queryKey: repositoryKeys.lists() }),
      ]);

      const previousDetail = queryClient.getQueryData<Repository>(repositoryKeys.detail(id));
      const previousLists = queryClient.getQueriesData<PaginatedRepositoryResponse>({
        queryKey: repositoryKeys.lists(),
      });

      if (previousDetail && previousDetail.default_branch !== branch) {
        queryClient.setQueryData<Repository>(repositoryKeys.detail(id), {
          ...previousDetail,
          default_branch: branch,
          sync_status: 'SYNCING',
          last_sync_error: null,
        });
      }

      queryClient.setQueriesData<PaginatedRepositoryResponse>(
        { queryKey: repositoryKeys.lists() },
        (old) => {
          if (!old) return old;
          return {
            ...old,
            items: old.items.map((repo) =>
              repo.id === id && repo.default_branch !== branch
                ? { ...repo, default_branch: branch, sync_status: 'SYNCING', last_sync_error: null }
                : repo,
            ),
          };
        },
      );

      useSyncProgressStore.getState().clearProgress(id);
      return { previousDetail, previousLists };
    },
    onError: (_err, { id }, context) => {
      if (context?.previousDetail) {
        queryClient.setQueryData(repositoryKeys.detail(id), context.previousDetail);
      }
      if (context?.previousLists) {
        for (const [key, data] of context.previousLists) {
          queryClient.setQueryData(key, data);
        }
      }
    },
    onSuccess: (data, { id }) => {
      if (data?.repository) {
        queryClient.setQueryData(repositoryKeys.detail(id), data.repository);
      }
    },
    onSettled: (_data, _err, { id }) => {
      queryClient.invalidateQueries({ queryKey: repositoryKeys.detail(id) });
      queryClient.invalidateQueries({ queryKey: repositoryKeys.lists() });
      queryClient.invalidateQueries({ queryKey: repositoryKeys.branches(id) });
      queryClient.invalidateQueries({ queryKey: repositoryKeys.syncJobs(id) });
      queryClient.invalidateQueries({ queryKey: [...repositoryKeys.detail(id), 'files'] });
      queryClient.invalidateQueries({ queryKey: [...repositoryKeys.detail(id), 'commits'] });
    },
  });
}

export function useRepositoryCommits(id: string | undefined, branch?: string) {
  return useQuery<RepositoryCommit[], ApiError>({
    queryKey: repositoryKeys.commits(id ?? '', branch),
    queryFn: () => getRepositoryCommits(id!, { branch, pageSize: 20 }),
    enabled: Boolean(id),
    ...githubQueryDefaults,
  });
}

export function useRepositoryPullRequests(id: string | undefined, state: 'open' | 'closed' | 'all' = 'open') {
  return useQuery<RepositoryPullRequest[], ApiError>({
    queryKey: repositoryKeys.pulls(id ?? '', state),
    queryFn: () => getRepositoryPullRequests(id!, { state, pageSize: 20 }),
    enabled: Boolean(id),
    ...githubQueryDefaults,
  });
}
