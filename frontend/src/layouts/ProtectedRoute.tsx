import { Navigate, Outlet } from 'react-router-dom';
import { LoadingSpinner } from '../components/shared/LoadingSpinner';

/**
 * ProtectedRoute — access control boundary.
 *
 * Day 1 Placeholder:
 * Authentication check is stubbed. The actual check (calling GET /api/v1/auth/me
 * and reading AuthStore) is implemented on Day 2 via the `useAuth()` hook.
 *
 * Architecture:
 * - Auth state lives in useAuthStore (Zustand).
 * - Loading is shown inside the content area, NOT by replacing the full screen,
 *   so the application shell (header/sidebar) is preserved.
 * - Unauthenticated users are redirected to /login.
 */
export function ProtectedRoute() {
  // Day 1: authentication check is a placeholder.
  // Replace with: const { isAuthenticated, isLoading } = useAuth();
  const isLoading = false;
  const isAuthenticated = true; // stub — always pass for layout preview

  if (isLoading) {
    return (
      <div className="flex items-center justify-center flex-1 min-h-[400px]">
        <LoadingSpinner size="lg" label="Checking authentication..." />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <Outlet />;
}
