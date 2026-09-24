import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { LoadingSpinner } from '../components/shared/LoadingSpinner';
import { ErrorMessage } from '../components/shared/ErrorMessage';

/**
 * AuthCallback — handles the frontend route after the backend completes GitHub OAuth.
 *
 * By the time the browser lands here, the backend has already set the JWT in
 * an HTTP-only auth cookie. This page calls useAuth() → GET /api/v1/auth/me
 * to confirm the cookie is valid, then redirects accordingly.
 */
export function AuthCallback() {
  const { isAuthenticated, isLoading } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (isLoading) return;
    navigate(isAuthenticated ? '/app/dashboard' : '/login', { replace: true });
  }, [isAuthenticated, isLoading, navigate]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-background">
        <LoadingSpinner size="lg" label="Completing sign in…" />
      </div>
    );
  }

  // Rarely visible — shown for the single frame before the useEffect navigates.
  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-4 bg-background">
      <ErrorMessage message="Something went wrong during sign in." />
      <a href="/login" className="text-sm text-primary underline">Return to login</a>
    </div>
  );
}
