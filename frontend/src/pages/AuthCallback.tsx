import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { LoadingSpinner } from '../components/shared/LoadingSpinner';
import { ErrorMessage } from '../components/shared/ErrorMessage';

/**
 * AuthCallback — handles the frontend route after the backend completes GitHub OAuth.
 *
 * By the time the browser lands here, the backend has already:
 *  - validated the OAuth state
 *  - exchanged the GitHub code for a token
 *  - created/updated the user in the database
 *  - set the JWT in an HTTP-only auth cookie
 *
 * This page simply calls useAuth() which runs GET /api/v1/auth/me.
 * If that succeeds → the session cookie is valid → navigate to /app/dashboard.
 * If it fails     → clear auth state → navigate back to /login.
 */
export function AuthCallback() {
  const { isAuthenticated, isLoading } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (isLoading) return;

    if (isAuthenticated) {
      navigate('/app/dashboard', { replace: true });
    } else {
      navigate('/login', { replace: true });
    }
  }, [isAuthenticated, isLoading, navigate]);

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-4 bg-background">
        <LoadingSpinner size="lg" label="Completing sign in…" />
        <p className="text-sm text-muted-foreground">Completing sign in…</p>
      </div>
    );
  }

  // isLoading is false but the useEffect hasn't navigated yet (rare flash).
  // Show a neutral state rather than a blank screen.
  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-4 bg-background">
      <ErrorMessage message="Something went wrong during sign in." />
      <a href="/login" className="text-sm text-primary underline">
        Return to login
      </a>
    </div>
  );
}
