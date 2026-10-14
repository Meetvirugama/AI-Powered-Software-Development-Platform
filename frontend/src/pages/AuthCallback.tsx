import { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { LoadingSpinner } from '../components/shared/LoadingSpinner';

export function AuthCallback() {
  const { isAuthenticated, isLoading, sessionError, retrySessionCheck } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const errorParam = searchParams.get('error') || searchParams.get('error_description');

  useEffect(() => {
    if (errorParam) {
      navigate(`/login?error=${encodeURIComponent(errorParam)}`, { replace: true });
      return;
    }

    if (isLoading) return;

    if (isAuthenticated) {
      navigate('/app/dashboard', { replace: true });
    }
  }, [isAuthenticated, isLoading, errorParam, navigate]);

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-3 bg-background text-foreground">
        <LoadingSpinner size="lg" label="Completing GitHub authentication…" />
        <p className="text-xs text-muted-foreground font-mono">Verifying secure session cookie…</p>
      </div>
    );
  }

  if (sessionError) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-4 bg-background p-6 text-center text-foreground">
        <div className="w-full max-w-sm rounded-xl border border-border bg-card p-6 shadow-sm space-y-4">
          <h2 className="text-base font-semibold">Sign in Verification Delayed</h2>
          <p className="text-xs text-muted-foreground">{sessionError}</p>
          <div className="flex items-center justify-center gap-3 pt-2">
            <button
              onClick={() => retrySessionCheck()}
              className="rounded-lg bg-primary px-4 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              Retry Check
            </button>
            <a
              href="/login"
              className="rounded-lg border border-border bg-background px-4 py-2 text-xs font-medium text-foreground hover:bg-accent transition-colors"
            >
              Return to Login
            </a>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-4 bg-background p-6 text-center text-foreground">
      <div className="w-full max-w-sm rounded-xl border border-border bg-card p-6 shadow-sm space-y-3">
        <h2 className="text-base font-semibold">Authentication incomplete</h2>
        <p className="text-xs text-muted-foreground">Session could not be established. Please try logging in again.</p>
        <a
          href="/login"
          className="inline-block rounded-lg bg-primary px-4 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
        >
          Return to Login
        </a>
      </div>
    </div>
  );
}
