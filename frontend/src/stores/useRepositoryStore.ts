import { create } from 'zustand';
import type { Repository } from '../types/api';

/**
 * RepositoryStore — Zustand client-side repository UI state.
 *
 * Server data (the repository list, counts, sync status from the API) lives
 * in TanStack Query via useRepositories(). This store holds only UI concerns:
 *   - which repository is currently open/selected in the UI
 */
interface RepositoryState {
  selectedRepository: Repository | null;
  setSelectedRepository: (repository: Repository | null) => void;
}

export const useRepositoryStore = create<RepositoryState>((set) => ({
  selectedRepository: null,
  setSelectedRepository: (repository) => set({ selectedRepository: repository }),
}));
