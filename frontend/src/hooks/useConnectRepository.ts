import { useMutation, useQueryClient } from '@tanstack/react-query';
import { connectRepository } from '../services/repositoryDiscovery';
import { repositoryKeys } from './useRepositories';
import { availableRepositoryKeys } from './useAvailableRepositories';
import type { ConnectRepositoryResponse, ApiError } from '../types/api';

/**
 * useConnectRepository — TanStack Query mutation hook for connecting a GitHub
 * repository to the platform.
 *
 * Data flow:
 *   useConnectRepository()
 *     → connectRepository(githubRepoId)
 *     → POST /api/v1/github/repositories/:githubRepoId/connect
 *     → ConnectRepositoryResponse { repository_id, job_id }
 *     → invalidate discovery + connected-repository caches
 *     → caller navigates to /repositories/:repository_id
 *
 * Design decisions:
 *   - TanStack Query useMutation owns the mutation lifecycle.
 *   - No Zustand state is written. Cache invalidation drives UI updates.
 *   - Navigation is NOT performed here — the UI layer decides when to navigate
 *     using the onSuccess result (repository_id).
 *   - Errors are exposed via `error` / `isError` — never swallowed silently.
 *   - The mutation accepts an optional onSuccess callback so the UI can
 *     navigate after cache invalidation completes (not before).
 *
 * Exposed states (mirrors standard useMutation return):
 *   mutate(githubRepoId)         — fire-and-forget, no return value
 *   mutateAsync(githubRepoId)    — returns Promise<ConnectRepositoryResponse>
 *   isPending                    — true while the request is in flight
 *   isSuccess                    — true on successful response
 *   isError                      — true if the request failed
 *   error                        — ApiError from Axios response interceptor
 *   data                         — ConnectRepositoryResponse on success
 *   reset()                      — reset mutation state (clear error/success)
 *
 * Cache invalidation on success:
 *   1. availableRepositoryKeys.all  — discovery list re-fetches so is_connected
 *      updates for the newly connected repository.
 *   2. repositoryKeys.all           — connected-repository list re-fetches so
 *      Dashboard shows the new entry immediately.
 *
 * Usage example (UI layer only — Prompt 3):
 *   const { mutate, isPending, isError, error } = useConnectRepository();
 *   const handleConnect = (repo: AvailableRepository) => {
 *     mutate(repo.github_repo_id, {
 *       onSuccess: ({ repository_id }) => {
 *         navigate(`/repositories/${repository_id}`);
 *       },
 *     });
 *   };
 */
export function useConnectRepository() {
  const queryClient = useQueryClient();

  return useMutation<ConnectRepositoryResponse, ApiError, string>({
    mutationFn: (githubRepoId: string) => connectRepository(githubRepoId),

    onSuccess: async () => {
      // Invalidate both caches in parallel.
      //
      // availableRepositoryKeys.all:
      //   The discovery list must re-fetch so the newly connected repository
      //   shows is_connected: true. Using the .all prefix invalidates every
      //   page and search combination simultaneously.
      //
      // repositoryKeys.all:
      //   The connected-repository list must re-fetch so the Dashboard shows
      //   the new repository. Using the .all prefix invalidates the list and
      //   any cached detail views.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: availableRepositoryKeys.all }),
        queryClient.invalidateQueries({ queryKey: repositoryKeys.all }),
      ]);
    },

    // onError: errors are exposed via the `error` field on the mutation result.
    // The UI layer is responsible for displaying the error to the user.
    // We do NOT write the error to Zustand or redirect.
  });
}
