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
  const [sessionError, setSessionError] = useState<string | null>(null);

  // If the store already has a resolved user, we have already checked.
  // Start resolved immediately so child components don't re-fetch.
  const [isLoading, setIsLoading] = useState(() => user === null && !isAuthenticated);

  const checkSession = useCallback(async () => {
    setIsLoading(true);
    setSessionError(null);
    try {
      const currentUser = await getCurrentUser();
      setUser(currentUser);
      setSessionError(null);
    } catch (err: unknown) {
      const errorObj = err as { code?: string; message?: string } | undefined;
      const isUnauthorized = errorObj?.code === 'UNAUTHORIZED';

      if (isUnauthorized) {
        clearUser();
        setSessionError(null);
      } else {
        // Network or 5xx server error: keep local user if already present, but surface retryable error
        setSessionError(
          errorObj?.message || 'Could not verify session due to a connection or server error.'
        );
      }
    } finally {
      setIsLoading(false);
    }
  }, [setUser, clearUser]);

  useEffect(() => {
    // Skip if auth state was already resolved before this component mounted.
    if (user !== null || isAuthenticated) {
      return;
    }

    // oxlint-disable-next-line react/set-state-in-effect
    checkSession();
  }, [checkSession, user, isAuthenticated]);

  const logout = useCallback(async () => {
    try {
      await authServiceLogout();
    } finally {
      clearUser();
      setSessionError(null);
    }
  }, [clearUser]);

  return {
    user,
    isAuthenticated,
    isLoading,
    sessionError,
    retrySessionCheck: checkSession,
    logout,
  };
}
