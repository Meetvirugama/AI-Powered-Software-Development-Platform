import { Link } from 'react-router-dom';
import { Home, FolderGit2, ArrowLeft } from 'lucide-react';

export function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4 py-12 text-foreground">
      <div className="w-full max-w-md text-center">
        <div className="mb-4 inline-flex h-16 w-16 items-center justify-center rounded-2xl bg-muted/60 border border-border/80 shadow-sm">
          <span className="font-mono text-2xl font-bold tracking-tight text-primary">404</span>
        </div>
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Page not found</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          The page you are looking for doesn't exist, has been moved, or is temporarily unavailable.
        </p>

        <div className="mt-6 flex flex-col sm:flex-row items-center justify-center gap-3">
          <Link
            to="/app/dashboard"
            className="inline-flex w-full sm:w-auto items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-xs font-semibold text-primary-foreground shadow-sm hover:bg-primary/90 transition-colors"
          >
            <Home className="h-4 w-4" />
            Back to Dashboard
          </Link>
          <Link
            to="/app/repositories"
            className="inline-flex w-full sm:w-auto items-center justify-center gap-2 rounded-lg border border-border bg-card px-4 py-2.5 text-xs font-medium text-foreground hover:bg-accent transition-colors"
          >
            <FolderGit2 className="h-4 w-4" />
            Repositories
          </Link>
        </div>

        <div className="mt-8 pt-6 border-t border-border/60">
          <button
            onClick={() => window.history.back()}
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Go back to previous page
          </button>
        </div>
      </div>
    </div>
  );
}

export default NotFound;

