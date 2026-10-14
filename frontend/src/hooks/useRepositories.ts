import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  listRepositories,
  getRepository,
  getRepositoryFiles,
  getRepositoryDependencies,
  syncRepository,
  deleteRepository,
  getRepositoryFileContent,
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
  list: (page: number, pageSize: number) =>
    [...repositoryKeys.all, 'list', { page, pageSize }] as const,
  detail: (id: string) => [...repositoryKeys.all, 'detail', id] as const,
  files: (id: string, page: number, pageSize: number) =>
    [...repositoryKeys.detail(id), 'files', { page, pageSize }] as const,
  fileContent: (id: string, fileId: string) =>
    [...repositoryKeys.detail(id), 'files', fileId, 'content'] as const,
  dependencies: (id: string) =>
    [...repositoryKeys.detail(id), 'dependencies'] as const,
};

export function useRepositories(
  page: number = 1,
  pageSize: number = 20,
  options?: { refetchInterval?: number | false | ((query: any) => number | false | undefined) },
) {
  return useQuery<PaginatedRepositoryResponse>({
    queryKey: repositoryKeys.list(page, pageSize),
    queryFn: () => listRepositories({ page, pageSize }),
    ...options,
  });
}

export function useRepository(
  id: string | undefined,
  options?: { refetchInterval?: number | false | ((query: any) => number | false | undefined) },
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
export function syncProgressFromStatus(status: SyncStatus): SyncProgress {
  switch (status) {
    case 'SYNCING':
      // ASSUMPTION: Currently the backend does not distinguish between
      // Cloning, Scanning, and Indexing. We show CLONING as the active stage.
      // When backend adds intermediate status, update this switch to route
      // through the fine-grained stages.
      return {
        stage: 'CLONING',
        label: 'Cloning',
        isActive: true,
        isComplete: false,
        isFailed: false,
      };

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

/**
 * useSyncRepository — Triggers background synchronization for a repository.
 * Invalidates repository queries on success so all UI reflects the new SYNCING state.
 */
export function useSyncRepository() {
  const queryClient = useQueryClient();
  return useMutation<{ job_id: string }, ApiError, string>({
    mutationFn: (id: string) => syncRepository(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: repositoryKeys.all });
    },
  });
}

/**
 * useDeleteRepository — Disconnects and deletes a repository.
 * Invalidates repository queries on success so the dashboard updates.
 */
export function useDeleteRepository() {
  const queryClient = useQueryClient();
  return useMutation<void, ApiError, string>({
    mutationFn: (id: string) => deleteRepository(id),
    onSuccess: () => {
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

