import { useState, useEffect, useCallback } from 'react';
import { getCurrentUser, logout as authServiceLogout } from '../services/auth';
import { useAuthStore } from '../stores/useAuthStore';
import type { User } from '../types/api';

/**
 * useAuth — primary authentication hook.
 *
 * Dependency flow:
 *   useAuth()  →  auth.ts  →  api.ts  →  backend
 *   auth.ts    →  useAuthStore  →  UI
 *
 * On mount, calls GET /api/v1/auth/me to determine if the browser's HTTP-only
 * session cookie is valid. On success, the user is stored in AuthStore and
 * isAuthenticated becomes true. On 401 (or any error), the store is cleared.
 *
 * The hook is designed to be called once near the top of the protected route
 * tree (e.g. in ProtectedRoute) so that auth state is resolved before any
 * child pages render.
 *
 * Exposes:
 *   user            — the authenticated User, or null
 *   isAuthenticated — true when a valid session exists
 *   isLoading       — true while the /auth/me check is in flight
 *   logout()        — calls POST /api/v1/auth/logout, then clears the store
 */
export function useAuth() {
  const { user, isAuthenticated, setUser, clearUser } = useAuthStore();
  const [isLoading, setIsLoading] = useState(true);

  // Check auth status on mount (once per page load).
  useEffect(() => {
    let cancelled = false;

    async function checkSession() {
      try {
        const currentUser: User = await getCurrentUser();
        if (!cancelled) {
          setUser(currentUser);
        }
      } catch {
        // 401 or any network error → not authenticated.
        if (!cancelled) {
          clearUser();
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    checkSession();

    return () => {
      cancelled = true;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const logout = useCallback(async () => {
    try {
      await authServiceLogout();
    } finally {
      // Always clear local state, even if the request fails.
      clearUser();
    }
  }, [clearUser]);

  return { user, isAuthenticated, isLoading, logout };
}
