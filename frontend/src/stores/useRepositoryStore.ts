import { create } from 'zustand';
import type { Repository, SyncStatus } from '../types/api';

/**
 * RepositoryStore — Zustand client-side repository selection state.
 *
 * Day 1 contract: store shape and actions only.
 * The actual repository list is server state fetched via TanStack Query.
 * This store holds UI-level concerns: which repo is selected and its sync status.
 *
 * Do NOT put the fetched repositories list here — that belongs in TanStack Query.
 * The `repositories` field is a Day 1 placeholder per the contract requirement.
 */
interface RepositoryState {
  /**
   * Day 1 placeholder per daily_tasks.md contract.
   * The live data will come from TanStack Query (GET /api/v1/repositories).
   * This field may be removed or re-scoped once TanStack Query integration
   * is implemented on Day 3+.
   */
  repositories: Repository[];
  /** The repository currently open/viewed in the UI. */
  selectedRepository: Repository | null;
  /** Sync status of the selected repository. */
  syncStatus: SyncStatus;

  setRepositories: (repositories: Repository[]) => void;
  setSelectedRepository: (repository: Repository | null) => void;
  setSyncStatus: (status: SyncStatus) => void;
}

export const useRepositoryStore = create<RepositoryState>((set) => ({
  repositories: [],
  selectedRepository: null,
  syncStatus: 'idle',

  setRepositories: (repositories) => set({ repositories }),
  setSelectedRepository: (repository) => set({ selectedRepository: repository }),
  setSyncStatus: (status) => set({ syncStatus: status }),
}));
