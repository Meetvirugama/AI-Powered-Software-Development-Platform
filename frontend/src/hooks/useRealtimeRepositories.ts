import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { realtimeClient } from '../realtime/index';
import { REPO_UPDATED, type RepoUpdatedPayload } from '../realtime/events';
import { repositoryKeys } from './useRepositories';

/**
 * useRealtimeRepositories — connects SSE to TanStack Query for repository data (F-09).
 *
 * Uses targeted cache invalidation so updates to repository A do not trigger
 * unnecessary refetches for repository B or cause full-app query refetch storms.
 */
export function useRealtimeRepositories() {
  const queryClient = useQueryClient();

  useEffect(() => {
    realtimeClient.connect(
      {
        [REPO_UPDATED]: (payload: RepoUpdatedPayload) => {
          // F-09: Targeted invalidation:
          // Invalidate the specific repository's detail query and list queries (for status badges),
          // preventing broad refetch storms.
          if (payload?.repository_id) {
            queryClient.invalidateQueries({
              queryKey: repositoryKeys.detail(payload.repository_id),
            });
            queryClient.invalidateQueries({
              queryKey: repositoryKeys.lists(),
            });
          } else {
            // Fallback for global broadcasts without repository ID
            queryClient.invalidateQueries({ queryKey: repositoryKeys.all });
          }
        },
      },
      (error) => {
        if (import.meta.env.DEV) {
          console.debug('[SSE] EventSource error encountered; backoff reconnection active', error);
        }
      }
    );

    return () => {
      realtimeClient.disconnect();
    };
  }, [queryClient]);
}
