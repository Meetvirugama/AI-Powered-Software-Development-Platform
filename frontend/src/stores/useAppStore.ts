import { create } from 'zustand';

export type ThemePreference = 'light' | 'dark' | 'system';
export type ResolvedTheme = 'light' | 'dark';

const THEME_STORAGE_KEY = 'ci-theme';

function readStoredTheme(): ThemePreference {
  try {
    if (typeof window !== 'undefined' && window.localStorage) {
      const value = window.localStorage.getItem(THEME_STORAGE_KEY);
      if (value === 'light' || value === 'dark' || value === 'system') {
        return value;
      }
    }
  } catch {
    // Ignore storage access failures in restricted environments
  }
  return 'system';
}

function getSystemTheme(): ResolvedTheme {
  try {
    if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
  } catch {
    // Fallback
  }
  return 'dark';
}

export function resolveTheme(preference: ThemePreference): ResolvedTheme {
  return preference === 'system' ? getSystemTheme() : preference;
}

export function applyThemeToDocument(resolved: ResolvedTheme): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  if (resolved === 'dark') {
    root.classList.add('dark');
  } else {
    root.classList.remove('dark');
  }
}

function persistTheme(preference: ThemePreference): void {
  try {
    if (typeof window !== 'undefined' && window.localStorage) {
      window.localStorage.setItem(THEME_STORAGE_KEY, preference);
    }
  } catch {
    // Ignore storage access failures
  }
}

const initialPreference = readStoredTheme();
const initialResolved = resolveTheme(initialPreference);
applyThemeToDocument(initialResolved);

interface AppState {
  sidebarOpen: boolean;
  toggleSidebar: () => void;
  /** Mobile slide-over navigation drawer (< md), closed by default. */
  mobileNavOpen: boolean;
  setMobileNavOpen: (open: boolean) => void;
  toggleMobileNav: () => void;
  /** Global command palette (Ctrl/Cmd+K), owned by AppLayout so it works on every page. */
  commandPaletteOpen: boolean;
  setCommandPaletteOpen: (open: boolean) => void;
  toggleCommandPalette: () => void;
  /** Theme preference and resolved active mode ('light' | 'dark'). */
  theme: ThemePreference;
  resolvedTheme: ResolvedTheme;
  setTheme: (theme: ThemePreference) => void;
  toggleTheme: () => void;
  // UI state only, server state goes to TanStack Query
}

export const useAppStore = create<AppState>((set, get) => ({
  sidebarOpen: true,
  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
  mobileNavOpen: false,
  setMobileNavOpen: (open) => set({ mobileNavOpen: open }),
  toggleMobileNav: () => set((state) => ({ mobileNavOpen: !state.mobileNavOpen })),
  commandPaletteOpen: false,
  setCommandPaletteOpen: (open) => set({ commandPaletteOpen: open }),
  toggleCommandPalette: () => set((state) => ({ commandPaletteOpen: !state.commandPaletteOpen })),
  theme: initialPreference,
  resolvedTheme: initialResolved,
  setTheme: (theme) => {
    const resolved = resolveTheme(theme);
    persistTheme(theme);
    applyThemeToDocument(resolved);
    set({ theme, resolvedTheme: resolved });
  },
  toggleTheme: () => {
    const next: ResolvedTheme = get().resolvedTheme === 'dark' ? 'light' : 'dark';
    persistTheme(next);
    applyThemeToDocument(next);
    set({ theme: next, resolvedTheme: next });
  },
}));

// Keep system preference live-synced when user has not explicitly pinned light/dark
if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
  try {
    const mql = window.matchMedia('(prefers-color-scheme: dark)');
    const handleMediaChange = (event: MediaQueryListEvent) => {
      if (useAppStore.getState().theme === 'system') {
        const next: ResolvedTheme = event.matches ? 'dark' : 'light';
        applyThemeToDocument(next);
        useAppStore.setState({ resolvedTheme: next });
      }
    };
    mql.addEventListener?.('change', handleMediaChange);
  } catch {
    // Ignore in environments without MediaQueryList listener support
  }
}
