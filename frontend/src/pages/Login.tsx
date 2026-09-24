import { useState } from 'react';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1';

export function Login() {
  const [isRedirecting, setIsRedirecting] = useState(false);

  function handleGitHubLogin() {
    setIsRedirecting(true);
    // Full browser navigation — the backend handles the OAuth exchange
    // and sets the HTTP-only auth cookie. Do not use Axios here.
    window.location.href = `${API_BASE}/auth/github/login`;
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-background">
      <div className="w-full max-w-sm p-8 space-y-6 border rounded-xl shadow-lg bg-card">
        <div className="space-y-1 text-center">
          <h1 className="text-2xl font-bold text-foreground">AI Dev Platform</h1>
          <p className="text-sm text-muted-foreground">
            Connect your GitHub account to get started.
          </p>
        </div>

        <button
          onClick={handleGitHubLogin}
          disabled={isRedirecting}
          className="w-full flex items-center justify-center gap-2 py-2.5 px-4 font-semibold rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
        >
          <GitHubIcon />
          {isRedirecting ? 'Redirecting…' : 'Continue with GitHub'}
        </button>
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
