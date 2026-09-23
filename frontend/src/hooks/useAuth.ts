import { useState, useEffect, useCallback } from 'react';
import { getCurrentUser, logout as authServiceLogout } from '../services/auth';
import { useAuthStore } from '../stores/useAuthStore';

/**
 * useAuth — primary authentication hook.
 *
 * Checks the browser's HTTP-only session cookie by calling GET /api/v1/auth/me.
 * If the cookie is valid the user is stored in AuthStore and isAuthenticated
 * becomes true. On 401 or any error the store is cleared.
 *
 * The fetch is skipped when auth state is already resolved in the store
 * (e.g. when a child component calls useAuth() after ProtectedRoute already
 * completed the check), preventing duplicate /auth/me requests.
 *
 * Exposes:
 *   user            — the authenticated User, or null
 *   isAuthenticated — true when a valid session exists
 *   isLoading       — true only while the /auth/me check is in flight
 *   logout()        — calls POST /api/v1/auth/logout, then clears the store
 */
export function useAuth() {
  const { user, isAuthenticated, setUser, clearUser } = useAuthStore();

  // If the store already has a resolved user, we have already checked.
  // Start resolved immediately so child components don't re-fetch.
  const [isLoading, setIsLoading] = useState(() => user === null && !isAuthenticated);

  useEffect(() => {
    // Skip if auth state was already resolved before this component mounted.
    if (!isLoading) return;

    let cancelled = false;

    async function checkSession() {
      try {
        const currentUser = await getCurrentUser();
        if (!cancelled) setUser(currentUser);
      } catch {
        // 401 or network error — not authenticated.
        if (!cancelled) clearUser();
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    checkSession();

    return () => { cancelled = true; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const logout = useCallback(async () => {
    try {
      await authServiceLogout();
    } finally {
      clearUser();
    }
  }, [clearUser]);

  return { user, isAuthenticated, isLoading, logout };
}
