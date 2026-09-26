import { useQuery } from '@tanstack/react-query';
import {
  listRepositories,
  getRepository,
  getRepositoryFiles,
  getRepositoryDependencies,
} from '../services/repositories';
import type {
  PaginatedRepositoryResponse,
  Repository,
  SyncProgress,
  SyncStatus,
  PaginatedRepositoryFileResponse,
  RepositoryDependency,
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
  dependencies: (id: string) =>
    [...repositoryKeys.detail(id), 'dependencies'] as const,
};

/**
 * useRepositories — TanStack Query hook for the paginated repository list.
 *
 * Data flow:
 *   useRepositories(page, pageSize)
 *     → listRepositories({ page, pageSize })
 *     → GET /api/v1/repositories
 *     → PaginatedRepositoryResponse
 *
 * Each page is cached independently. Switching pages does not discard the
 * previous page's data — it stays in cache until stale.
 *
 * Returns the standard useQuery result. Components should consume:
 *   data?.items    — the Repository[] for the current page
 *   data?.total    — total count for pagination controls
 *   isLoading      — true on first load for this page
 *   isFetching     — true whenever a background refetch is in flight
 *   isError        — true if the last request failed
 *   error          — the ApiError from the response interceptor
 */
export function useRepositories(page: number = 1, pageSize: number = 20) {
  return useQuery<PaginatedRepositoryResponse>({
    queryKey: repositoryKeys.list(page, pageSize),
    queryFn: () => listRepositories({ page, pageSize }),
  });
}

// ---------------------------------------------------------------------------
// useRepository — single repository detail hook
//
// Used by the Day 4 flow to retrieve sync status after a Connect mutation:
//
//   useConnectRepository() succeeds
//     → ConnectRepositoryResponse.repository_id
//     → useRepository(repository_id)
//     → GET /api/v1/repositories/:id
//     → Repository { sync_status, ... }
//     → syncProgressFromStatus(sync_status)
//     → SyncProgress { stage, label, isActive, isComplete, isFailed }
//     → UI step indicator
//
// The actual polling interval is deliberately NOT set here because the
// backend contract for intermediate sync stages is not yet confirmed.
// The UI layer (Prompt 3) will add refetchInterval once confirmed.
// ---------------------------------------------------------------------------

/**
 * useRepository — TanStack Query hook for a single repository by ID.
 *
 * Data flow:
 *   useRepository(id)
 *     → getRepository(id)
 *     → GET /api/v1/repositories/:id
 *     → Repository
 *
 * This hook reuses repositoryKeys.detail(id) so that:
 *   - Invalidating repositoryKeys.all (e.g. after Connect or SSE event) also
 *     invalidates this query automatically.
 *   - The Dashboard and the Repository Selector can share cached detail data.
 *
 * The hook is disabled (no request made) when id is undefined/empty so it
 * can be mounted before the repository_id is known from the Connect response.
 *
 * @param id   Our internal repository UUID. Pass undefined to skip fetching.
 * @param options  Optional TanStack Query overrides (e.g. refetchInterval).
 */
export function useRepository(
  id: string | undefined,
  options?: { refetchInterval?: number | false },
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
