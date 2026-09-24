import { create } from 'zustand';
import type { User } from '../types/api';

/**
 * AuthStore — Zustand client-side authentication state.
 *
 * Authentication mechanism: HTTP-only cookies.
 * The backend sets the JWT as an httpOnly cookie after the OAuth callback.
 * The frontend never reads or stores the token value — Axios sends the cookie
 * automatically via `withCredentials: true`.
 *
 * This store holds only what the UI needs:
 *  - who is logged in (user)
 *  - whether a session exists (isAuthenticated)
 *
 * Populated by useAuth() after a successful GET /api/v1/auth/me.
 * Cleared by useAuth().logout() after POST /api/v1/auth/logout.
 */
interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  setUser: (user: User) => void;
  clearUser: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,

  setUser: (user) => set({ user, isAuthenticated: true }),
  clearUser: () => set({ user: null, isAuthenticated: false }),
}));
