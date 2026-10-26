import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { LoadingSpinner } from '../components/shared/LoadingSpinner';

/**
 * ProtectedRoute — access control boundary.
 *
 * Uses useAuth() to determine the current session state:
 *  - While /auth/me is in flight: renders a loading spinner in the content area.
 *  - If not authenticated (401 from /auth/me): redirects to /login.
 *  - If authenticated: renders the child routes via <Outlet />.
 *
 * The loading state is shown inside the layout content area, not full-screen,
 * so the application shell is preserved during the check.
 */
export function ProtectedRoute() {
  const { isAuthenticated, isLoading, sessionError, retrySessionCheck } = useAuth();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-background">
        <LoadingSpinner size="lg" label="Verifying session…" />
      </div>
    );
  }

  if (sessionError && !isAuthenticated) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-4 bg-background p-6 text-center">
        <div className="w-full max-w-md rounded-xl border border-border bg-card p-6 shadow-sm space-y-4">
          <h2 className="text-lg font-semibold text-foreground">Session Verification Failed</h2>
          <p className="text-sm text-muted-foreground">{sessionError}</p>
          <div className="flex items-center justify-center gap-3 pt-2">
            <button
              onClick={() => retrySessionCheck()}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              Retry Connection
            </button>
            <a
              href="/login"
              className="rounded-lg border border-border bg-background px-4 py-2 text-sm font-medium text-foreground hover:bg-accent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              Sign In Again
            </a>
          </div>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <Outlet />;
}
