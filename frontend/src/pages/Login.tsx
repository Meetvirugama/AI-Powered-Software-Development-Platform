import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Cpu, ShieldCheck, Terminal, Layers, AlertCircle } from 'lucide-react';

export function Login() {
  const [isRedirecting, setIsRedirecting] = useState(false);
  const [searchParams] = useSearchParams();
  const errorParam = searchParams.get('error');
  const redirectParam = searchParams.get('redirect');

  function handleGitHubLogin() {
    setIsRedirecting(true);
    if (redirectParam && typeof sessionStorage !== 'undefined') {
      sessionStorage.setItem('auth_redirect', redirectParam);
    }
    // Full browser navigation — backend handles OAuth + sets httpOnly cookie.
    window.location.href = `/api/v1/auth/github/login`;
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4 py-12 text-foreground">
      <div className="w-full max-w-md space-y-6">
        {/* Brand header */}
        <div className="flex flex-col items-center text-center space-y-2">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 border border-primary/20 text-primary mb-2 shadow-sm">
            <Cpu className="h-6 w-6" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">
            Code Intelligence
          </h1>
          <p className="text-xs uppercase font-mono tracking-wider text-muted-foreground">
            Engineering Workspace
          </p>
          <p className="text-sm text-muted-foreground max-w-xs pt-1">
            Grounded code intelligence, symbol graphs, and interactive repository conversation.
          </p>
        </div>

        {/* Error notification if returned from failed OAuth */}
        {errorParam && (
          <div
            role="alert"
            className="rounded-lg border border-destructive/30 bg-destructive/10 p-3.5 text-xs text-destructive flex items-start gap-2.5"
          >
            <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
            <div className="min-w-0">
              <p className="font-semibold">Authentication failed</p>
              <p className="text-muted-foreground mt-0.5">{errorParam}</p>
            </div>
          </div>
        )}

        {/* Main login card */}
        <div className="rounded-xl border border-border bg-card p-6 shadow-md space-y-5">
          <div className="space-y-1">
            <h2 className="text-sm font-semibold text-foreground">Sign in to your workspace</h2>
            <p className="text-xs text-muted-foreground">
              Authenticate via GitHub OAuth to discover and index your repositories.
            </p>
          </div>

          <button
            onClick={handleGitHubLogin}
            disabled={isRedirecting}
            className="w-full flex items-center justify-center gap-2.5 py-2.5 px-4 text-sm font-medium rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60 disabled:cursor-not-allowed transition-all shadow-sm"
          >
            <GitHubIcon />
            {isRedirecting ? 'Connecting to GitHub…' : 'Continue with GitHub'}
          </button>

          <div className="pt-2 border-t border-border/60 space-y-2.5">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <ShieldCheck className="h-4 w-4 text-emerald-500 shrink-0" />
              <span>Strict cookie session · Tokens never stored in browser</span>
            </div>
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Terminal className="h-4 w-4 text-primary shrink-0" />
              <span>Read-only repository access for AST parsing & search</span>
            </div>
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Layers className="h-4 w-4 text-muted-foreground shrink-0" />
              <span>Multi-tenant repository isolation enforced by database</span>
            </div>
          </div>
        </div>

        <p className="text-center text-xs text-muted-foreground select-none">
          Antigravity & Claude Code workflow references · Week 1 Engine
        </p>
      </div>
    </div>
  );
}

function GitHubIcon() {
  return (
    <svg height="18" width="18" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}
