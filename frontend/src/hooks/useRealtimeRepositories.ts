import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { realtimeClient } from '../realtime/index';
import { REPO_UPDATED } from '../realtime/events';
import { repositoryKeys } from './useRepositories';

/**
 * useRealtimeRepositories — connects SSE to TanStack Query for repository data.
 *
 * Data flow:
 *   SSE connection (EventSource)
 *     ↓ repository.updated event
 *   queryClient.invalidateQueries(repositoryKeys.all)
 *     ↓ TanStack Query refetches
 *   GET /api/v1/repositories
 *     ↓ cache updated
 *   Dashboard re-renders automatically
 *
 * Design decisions:
 *  - The SSE layer does NOT store repository data. It only triggers a cache
 *    invalidation, letting TanStack Query manage the actual server state.
 *  - `repositoryKeys.all` invalidates every repository query (all pages, all
 *    detail views) so no page is left stale after a sync-status change.
 *  - The connection is opened when this hook mounts and closed on cleanup.
 *    Mount/unmount lifecycle is managed by the caller (AppLayout or a page
 *    that is mounted for the duration of the authenticated session).
 *
 * Usage:
 *   Call once from a component that lives for the entire authenticated
 *   session (e.g. AppLayout) so the connection is not repeatedly torn down.
 *
 *   function AppLayout() {
 *     useRealtimeRepositories();
 *     ...
 *   }
 */
export function useRealtimeRepositories() {
  const queryClient = useQueryClient();

  useEffect(() => {
    realtimeClient.connect(
      {
        [REPO_UPDATED]: (_payload) => {
          // A repository's status/data changed on the backend.
          // Invalidate all repository queries so every page refetches.
          // We use repositoryKeys.all (the prefix) so TanStack Query
          // invalidates ['repositories', 'list', ...] and ['repositories', 'detail', ...]
          // simultaneously.
          queryClient.invalidateQueries({ queryKey: repositoryKeys.all });
        },
      },
      (_error) => {
        // SSE connection error — the client has already disconnected.
        // No reconnection here; the next navigation or page refresh
        // will re-mount this hook and reconnect.
        // TODO: add exponential backoff reconnection if needed in a future prompt.
      },
    );

    return () => {
      realtimeClient.disconnect();
    };
  }, [queryClient]);
}
