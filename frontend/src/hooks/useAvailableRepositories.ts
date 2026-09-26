import { useQuery } from '@tanstack/react-query';
import { listAvailableRepositories } from '../services/repositoryDiscovery';
import type { PaginatedAvailableRepositoryResponse } from '../types/api';

// ---------------------------------------------------------------------------
// Query key factory
//
// Keys are structured so that:
//   - invalidateQueries({ queryKey: availableRepositoryKeys.all }) clears all
//     discovery queries (all pages, all search terms) in one call.
//   - Each (page, pageSize, search) combination is independently cached.
//   - Adding a new parameter in the future only requires updating the `list`
//     function and calling it with the new argument.
// ---------------------------------------------------------------------------

export const availableRepositoryKeys = {
  /** Prefix for ALL discovery queries. Invalidate this to clear everything. */
  all: ['github-repositories'] as const,

  /**
   * Key for a specific page + search combination.
   * Keeping page, pageSize, and search inside a single object means
   * TanStack Query deep-compares the full params — no missed re-fetches.
   */
  list: (page: number, pageSize: number, search: string) =>
    [
      ...availableRepositoryKeys.all,
      'list',
      { page, pageSize, search },
    ] as const,
};

// ---------------------------------------------------------------------------
// Hook parameters
// ---------------------------------------------------------------------------

export interface UseAvailableRepositoriesParams {
  /** 1-based page number (default: 1). */
  page?: number;
  /** Items per page (default: 20). */
  pageSize?: number;
  /**
   * Search term for server-side name filtering.
   * Empty string means no filter.
   * Note: debouncing belongs in the UI layer (Prompt 3), not here.
   */
  search?: string;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * useAvailableRepositories — TanStack Query hook for GitHub App repository discovery.
 *
 * Data flow:
 *   useAvailableRepositories({ page, pageSize, search })
 *     → listAvailableRepositories({ page, pageSize, search })
 *     → GET /api/v1/github/repositories?page=&page_size=&search=
 *     → PaginatedAvailableRepositoryResponse
 *
 * Design decisions (from Day 4 spec):
 *   - Search is server-side. The search term is sent to the API.
 *     No local array filtering.
 *   - Pagination is server-side. page + pageSize are sent to the API.
 *   - page, pageSize, and search are all part of the query key so TanStack
 *     Query treats each combination as an independent cache entry.
 *   - Zustand does NOT store discovered repositories. Only TanStack Query's
 *     cache holds this server state.
 *   - The hook does NOT implement the Connect mutation (that is Prompt 2).
 *   - The hook does NOT implement debounce (that belongs in the UI, Prompt 3).
 *
 * Exposed states (mirrors standard useQuery return):
 *   data          — PaginatedAvailableRepositoryResponse | undefined
 *   data?.items   — AvailableRepository[] for the current page/search
 *   data?.total   — total count across all pages
 *   data?.total_pages — total page count
 *   isLoading     — true on first load for this key
 *   isFetching    — true whenever a background refetch is in flight
 *   isError       — true if the last request failed
 *   error         — ApiError from the Axios response interceptor
 *   refetch       — manually trigger a refetch
 */
export function useAvailableRepositories({
  page = 1,
  pageSize = 20,
  search = '',
}: UseAvailableRepositoriesParams = {}) {
  return useQuery<PaginatedAvailableRepositoryResponse>({
    queryKey: availableRepositoryKeys.list(page, pageSize, search),
    queryFn: () => listAvailableRepositories({ page, pageSize, search }),
  });
}
