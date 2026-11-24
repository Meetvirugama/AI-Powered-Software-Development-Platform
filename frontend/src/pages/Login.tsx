import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Cpu, ShieldCheck, AlertCircle, Wrench, Loader2 } from 'lucide-react';
import { API_BASE_URL } from '../services/api';
import { devLogin } from '../services/auth';
import { useAuthStore } from '../stores/useAuthStore';
import { ThemeToggle } from '../components/shared/ThemeToggle';

function getAuthErrorMessage(err: unknown, fallback: string): string {
  if (err && typeof err === 'object' && 'message' in err) {
    const msg = (err as { message?: unknown }).message;
    if (typeof msg === 'string' && msg.trim()) {
      return msg.trim();
    }
  }
  return fallback;
}

export function Login() {
  const [isRedirecting, setIsRedirecting] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [searchParams] = useSearchParams();
  const errorParam = searchParams.get('error');
  const redirectParam = searchParams.get('redirect');
  const displayError = authError ?? errorParam;

  function handleGitHubLogin() {
    setAuthError(null);
    setIsRedirecting(true);
    if (redirectParam && typeof sessionStorage !== 'undefined') {
      sessionStorage.setItem('auth_redirect', redirectParam);
    }
    const currentOrigin = typeof window !== 'undefined' ? window.location.origin : '';
    const callbackUrl = currentOrigin ? `${currentOrigin}/auth/callback` : '';
    const loginUrl = callbackUrl
      ? `${API_BASE_URL}/auth/github/login?redirect_url=${encodeURIComponent(callbackUrl)}`
      : `${API_BASE_URL}/auth/github/login`;
    window.location.href = loginUrl;
  }

  const devLoginTarget = (import.meta.env.VITE_DEV_LOGIN as string) || '';

  async function handleDevLogin() {
    if (!devLoginTarget) return;
    setAuthError(null);
    setIsRedirecting(true);
    try {
      const user = await devLogin(devLoginTarget);
      useAuthStore.getState().setUser(user);
      const dest =
        redirectParam ||
        (typeof sessionStorage !== 'undefined' ? sessionStorage.getItem('auth_redirect') : null) ||
        '/app/dashboard';
      window.location.href = dest;
    } catch (err) {
      setIsRedirecting(false);
      setAuthError(
        getAuthErrorMessage(err, 'Quick dev sign-in failed. Please verify the backend is running.')
      );
      console.error('Dev login failed:', err);
    }
  }

  return (
    <div className="flex min-h-screen flex-col bg-background px-4 py-4 sm:px-6 sm:py-5 text-foreground">
      <div className="flex justify-end">
        <ThemeToggle showLabel />
      </div>

      <div className="flex flex-1 items-center justify-center py-6">
        <div className="w-full max-w-sm space-y-6">
          {/* Brand header */}
          <div className="flex flex-col items-center text-center space-y-2.5">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-xs">
              <Cpu className="h-5 w-5" />
            </div>
            <div className="space-y-1">
              <h1 className="text-xl font-semibold tracking-tight text-foreground">
                Code Intelligence
              </h1>
              <p className="text-sm text-muted-foreground">
                Sign in to explore repositories, review code, and manage tasks.
              </p>
            </div>
          </div>

          {/* Error notification from failed OAuth or dev/mock sign-in */}
          {displayError && (
            <div
              role="alert"
              className="rounded-lg border border-destructive/30 bg-destructive/10 p-3.5 text-xs text-destructive flex items-start gap-2.5"
            >
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
              <div className="min-w-0">
                <p className="font-semibold">Authentication failed</p>
                <p className="text-muted-foreground mt-0.5 break-words">{displayError}</p>
              </div>
            </div>
          )}

          {/* Main login card */}
          <div className="rounded-xl border border-border bg-card p-6 shadow-xs space-y-4">
            <button
              type="button"
              onClick={handleGitHubLogin}
              disabled={isRedirecting}
              aria-busy={isRedirecting}
              className="w-full flex items-center justify-center gap-2.5 py-2.5 px-4 text-sm font-medium rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60 disabled:cursor-not-allowed transition-colors cursor-pointer"
            >
              {isRedirecting ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <GitHubIcon />
              )}
              {isRedirecting ? 'Connecting to GitHub…' : 'Continue with GitHub'}
            </button>

            {import.meta.env.DEV && Boolean(devLoginTarget) && (
              <button
                type="button"
                onClick={handleDevLogin}
                disabled={isRedirecting}
                className="w-full flex items-center justify-center gap-2 py-2 px-3 text-xs font-medium rounded-lg border border-border bg-background text-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60 disabled:cursor-not-allowed transition-colors cursor-pointer"
              >
                <Wrench className="h-3.5 w-3.5 text-muted-foreground" />
                Quick Dev Sign-In (Local Workspace)
              </button>
            )}

            <div className="pt-3 border-t border-border/70 flex items-center justify-center gap-1.5 text-xs text-muted-foreground">
              <ShieldCheck className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400 shrink-0" />
              <span>HTTP-only cookie session · Read-only indexing</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function GitHubIcon() {
  return (
    <svg height="16" width="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}
