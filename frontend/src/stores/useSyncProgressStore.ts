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
      const filesProcessed = Number.isFinite(Number(payload.files_processed))
        ? Number(payload.files_processed)
        : (prev?.files_processed ?? 0);
      const filesTotal = Number.isFinite(Number(payload.files_total))
        ? Number(payload.files_total)
        : (prev?.files_total ?? 0);
      const progressPct = Number.isFinite(Number(payload.progress_pct))
        ? Number(payload.progress_pct)
        : (prev?.progress_pct ?? 0);
      const chunksEmbedded = Number.isFinite(Number(payload.chunks_embedded))
        ? Number(payload.chunks_embedded)
        : prev?.chunks_embedded;

      const sameRun =
        prev &&
        (!payload.job_id || !prev.job_id || prev.job_id === payload.job_id) &&
        filesProcessed >= prev.files_processed;
      return {
        progressByRepo: {
          ...state.progressByRepo,
          [payload.repository_id]: {
            ...payload,
            files_processed: filesProcessed,
            files_total: filesTotal,
            chunks_embedded: chunksEmbedded,
            progress_pct: progressPct,
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
