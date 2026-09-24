import { useQuery } from '@tanstack/react-query';
import { listRepositories } from '../services/repositories';
import type { PaginatedRepositoryResponse } from '../types/api';

/**
 * Query key factory for repository queries.
 *
 * Keeping keys in one place means invalidation (e.g. after an SSE event)
 * only needs to reference this factory, not recreate key shapes.
 */
export const repositoryKeys = {
  all: ['repositories'] as const,
  list: (page: number, pageSize: number) =>
    [...repositoryKeys.all, 'list', { page, pageSize }] as const,
  detail: (id: string) => [...repositoryKeys.all, 'detail', id] as const,
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
