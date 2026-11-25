import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { realtimeClient } from '../realtime/index';
import {
  REPO_SYNC_PROGRESS,
  REPO_UPDATED,
  type RepoSyncProgressPayload,
  type RepoUpdatedPayload,
} from '../realtime/events';
import { useSyncProgressStore } from '../stores/useSyncProgressStore';
import { repositoryKeys } from './useRepositories';

/**
 * useRealtimeRepositories — connects SSE to TanStack Query for repository data (F-09).
 *
 * Uses targeted cache invalidation so updates to repository A do not trigger
 * unnecessary refetches for repository B or cause full-app query refetch storms,
 * and streams granular indexing progress directly into useSyncProgressStore.
 */
export function useRealtimeRepositories() {
  const queryClient = useQueryClient();

  useEffect(() => {
    realtimeClient.connect(
      {
        [REPO_SYNC_PROGRESS]: (payload: RepoSyncProgressPayload) => {
          if (payload?.repository_id) {
            useSyncProgressStore.getState().setProgress(payload);
          }
        },
        [REPO_UPDATED]: (payload: RepoUpdatedPayload) => {
          if (payload?.repository_id) {
            useSyncProgressStore.getState().clearProgress(payload.repository_id);
            queryClient.invalidateQueries({
              queryKey: repositoryKeys.detail(payload.repository_id),
            });
            queryClient.invalidateQueries({
              queryKey: repositoryKeys.lists(),
            });
            queryClient.invalidateQueries({
              queryKey: repositoryKeys.syncJobs(payload.repository_id),
            });
            queryClient.invalidateQueries({
              queryKey: [...repositoryKeys.detail(payload.repository_id), 'files'],
            });
            queryClient.invalidateQueries({
              queryKey: repositoryKeys.dependencies(payload.repository_id),
            });
            queryClient.invalidateQueries({
              queryKey: repositoryKeys.metrics(payload.repository_id),
            });
          } else {
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
