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
  const { isAuthenticated, isLoading } = useAuth();

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
