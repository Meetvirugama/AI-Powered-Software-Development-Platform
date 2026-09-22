import { create } from 'zustand';
import type { User } from '../types/api';

/**
 * AuthStore — Zustand client-side auth state.
 *
 * Authentication contract (from Docs/daily_tasks.md Day 2):
 *   - GitHub OAuth callback → backend sets JWT in an **httpOnly cookie**.
 *   - The frontend NEVER reads or stores the raw token value.
 *   - `token` is intentionally null: the cookie is sent automatically by
 *     the browser via `withCredentials: true` on the Axios client.
 *   - `user` is populated after a successful GET /api/v1/auth/me call
 *     (implemented on Day 2 via the `useAuth()` hook).
 *   - `isAuthenticated` is derived from whether `user` is non-null.
 *
 * Day 1 contract: store shape and actions only. No real API calls yet.
 */
interface AuthState {
  /** Authenticated user object from GET /api/v1/auth/me. Null when logged out. */
  user: User | null;
  /**
   * Always null — authentication uses httpOnly cookies managed by the backend.
   * This field exists to satisfy the Day 1 store contract. Bearer token
   * injection would go here only if the project moved to a non-cookie strategy.
   */
  token: null;
  /** True when a user object is present. */
  isAuthenticated: boolean;
  /** Store the user returned by /auth/me and mark as authenticated. */
  login: (user: User) => void;
  /** Clear all auth state. The backend's logout endpoint must also be called. */
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: null,
  isAuthenticated: false,

  login: (user) =>
    set({
      user,
      isAuthenticated: true,
    }),

  logout: () =>
    set({
      user: null,
      isAuthenticated: false,
    }),
}));
