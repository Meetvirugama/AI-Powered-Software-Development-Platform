import { create } from 'zustand';

const STORAGE_KEY = 'devplatform:selected-files-by-repo';

function loadInitialMap(): Record<string, string> {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.sessionStorage?.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, string>) : {};
  } catch {
    return {};
  }
}

function persistMap(map: Record<string, string>) {
  if (typeof window === 'undefined') return;
  try {
    window.sessionStorage?.setItem(STORAGE_KEY, JSON.stringify(map));
  } catch {
    // Ignore storage quota or restricted-mode errors
  }
}

interface SelectedFileState {
  selectedPathByRepo: Record<string, string>;
  setSelectedFilePath: (repoId: string, filePath: string) => void;
  clearSelectedFilePath: (repoId: string) => void;
  reset: () => void;
}

export const useSelectedFileStore = create<SelectedFileState>((set) => ({
  selectedPathByRepo: loadInitialMap(),
  setSelectedFilePath: (repoId, filePath) =>
    set((state) => {
      if (!repoId || !filePath || state.selectedPathByRepo[repoId] === filePath) {
        return state;
      }
      const next = { ...state.selectedPathByRepo, [repoId]: filePath };
      persistMap(next);
      return { selectedPathByRepo: next };
    }),
  clearSelectedFilePath: (repoId) =>
    set((state) => {
      if (!(repoId in state.selectedPathByRepo)) return state;
      const next = { ...state.selectedPathByRepo };
      delete next[repoId];
      persistMap(next);
      return { selectedPathByRepo: next };
    }),
  reset: () => {
    persistMap({});
    set({ selectedPathByRepo: {} });
  },
}));
