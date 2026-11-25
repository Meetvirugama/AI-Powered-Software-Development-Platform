import { create } from 'zustand';
import type { RepoSyncProgressPayload } from '../realtime/events';

export interface SyncProgressEntry extends RepoSyncProgressPayload {
  startedAt: number;
  updatedAt: number;
}

interface SyncProgressState {
  progressByRepo: Record<string, SyncProgressEntry>;
  setProgress: (payload: RepoSyncProgressPayload) => void;
  clearProgress: (repositoryId: string) => void;
}

export const useSyncProgressStore = create<SyncProgressState>((set) => ({
  progressByRepo: {},
  setProgress: (payload) =>
    set((state) => {
      const now = Date.now();
      const prev = state.progressByRepo[payload.repository_id];
      const sameRun =
        prev &&
        (!payload.job_id || !prev.job_id || prev.job_id === payload.job_id) &&
        payload.files_processed >= prev.files_processed;
      return {
        progressByRepo: {
          ...state.progressByRepo,
          [payload.repository_id]: {
            ...payload,
            startedAt: sameRun ? prev.startedAt : now,
            updatedAt: now,
          },
        },
      };
    }),
  clearProgress: (repositoryId) =>
    set((state) => {
      if (!(repositoryId in state.progressByRepo)) {
        return state;
      }
      const next = { ...state.progressByRepo };
      delete next[repositoryId];
      return { progressByRepo: next };
    }),
}));
