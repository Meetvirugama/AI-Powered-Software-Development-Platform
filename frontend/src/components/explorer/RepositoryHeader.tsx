import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowLeft,
  RotateCw,
  Trash2,
  MessageSquare,
  GitBranch,
  Code,
  Box,
  CheckCircle2,
  RefreshCw,
  Clock,
  X,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import type { Repository, SyncProgress } from '../../types/api';

export interface RepositoryHeaderProps {
  repo: Repository;
  progress: SyncProgress;
  isReady: boolean;
  isSyncActive: boolean;
  isDeletePending: boolean;
  onSync: () => void;
  onDelete: () => void;
}

export function RepositoryHeader({
  repo,
  progress,
  isReady,
  isSyncActive,
  isDeletePending,
  onSync,
  onDelete,
}: RepositoryHeaderProps) {
  const [showConfirmDelete, setShowConfirmDelete] = useState(false);

  return (
    <>
      <header className="shrink-0 space-y-2.5 bg-card/50 border border-border/80 rounded-xl p-3 sm:p-4 shadow-sm">
        {/* Navigation & Header Actions */}
        <div className="flex items-center justify-between gap-3">
          <Link
            to="/app/dashboard"
            className="inline-flex items-center gap-2 text-xs sm:text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            <span>Back to Dashboard</span>
          </Link>

          <div className="flex items-center gap-2 shrink-0">
            {/* Re-sync Button */}
            <button
              onClick={onSync}
              disabled={isSyncActive}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-background px-2.5 py-1.5 text-xs font-medium text-foreground hover:bg-accent transition-colors disabled:opacity-50"
              title="Re-synchronize repository"
              aria-label="Re-synchronize repository"
            >
              <RotateCw className={cn('h-3.5 w-3.5', isSyncActive && 'animate-spin text-primary')} />
              <span className="hidden sm:inline">{isSyncActive ? 'Syncing…' : 'Re-sync'}</span>
            </button>

            {/* Disconnect Button */}
            <button
              onClick={() => setShowConfirmDelete(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-destructive/30 bg-destructive/5 px-2.5 py-1.5 text-xs font-medium text-destructive hover:bg-destructive/10 transition-colors"
              title="Disconnect repository"
              aria-label="Disconnect repository"
            >
              <Trash2 className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Disconnect</span>
            </button>

            {/* Chat with Repository Button */}
            <Link
              to={`/app/repositories/${repo.id}/chat`}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring shrink-0 shadow-sm',
                !progress.isComplete || progress.isFailed
                  ? 'pointer-events-none opacity-50'
                  : 'hover:bg-primary/90'
              )}
              aria-disabled={!progress.isComplete || progress.isFailed}
              tabIndex={!progress.isComplete || progress.isFailed ? -1 : undefined}
            >
              <MessageSquare className="h-3.5 w-3.5" />
              <span>Chat with this repository</span>
            </Link>
          </div>
        </div>

        {/* Repository Meta Details */}
        <div className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-2 pt-1 border-t border-border/50">
          <div className="flex flex-wrap items-baseline gap-2 min-w-0">
            <h1 className="text-lg sm:text-xl font-bold text-foreground tracking-tight truncate">
              {repo.name}
            </h1>
            <span className="text-xs text-muted-foreground font-mono truncate">
              {repo.full_name}
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-2 sm:gap-3 text-xs text-muted-foreground shrink-0">
            <div className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-muted/40 border border-border/60">
              <GitBranch className="h-3 w-3 text-muted-foreground" />
              <span className="font-mono">{repo.default_branch || 'main'}</span>
            </div>

            {repo.language && (
              <div className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-muted/40 border border-border/60">
                <Code className="h-3 w-3 text-primary" />
                <span>{repo.language}</span>
              </div>
            )}

            {repo.framework && (
              <div className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-muted/40 border border-border/60">
                <Box className="h-3 w-3 text-emerald-500" />
                <span>{repo.framework}</span>
              </div>
            )}

            <div
              className={cn(
                'inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-xs font-medium',
                isReady
                  ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                  : isSyncActive
                  ? 'bg-blue-500/10 border-blue-500/30 text-blue-400'
                  : 'bg-muted/40 border-border text-muted-foreground'
              )}
            >
              {isReady ? (
                <CheckCircle2 className="h-3 w-3" />
              ) : (
                <RefreshCw className={cn('h-3 w-3', isSyncActive && 'animate-spin')} />
              )}
              <span>{isSyncActive ? 'Syncing…' : progress.label}</span>
            </div>

            {repo.last_synced_at && (
              <div className="hidden md:inline-flex items-center gap-1 text-[11px] text-muted-foreground">
                <Clock className="h-3 w-3" />
                <span>Synced {new Date(repo.last_synced_at).toLocaleDateString()}</span>
              </div>
            )}
          </div>
        </div>

        {/* Optional Description */}
        {repo.description && (
          <p className="text-xs text-muted-foreground line-clamp-1 italic">
            {repo.description}
          </p>
        )}
      </header>

      {/* Disconnect Confirmation Alert */}
      {showConfirmDelete && (
        <div
          role="alert"
          className="shrink-0 rounded-xl border border-destructive/30 bg-destructive/10 p-3 sm:p-4 space-y-2 animate-in fade-in duration-200"
        >
          <div className="flex items-start justify-between">
            <div>
              <h3 className="font-semibold text-foreground text-sm">Disconnect {repo.name}?</h3>
              <p className="text-xs text-muted-foreground mt-0.5">
                This will delete repository indexing data, symbols, and vector chunks from this workspace.
              </p>
            </div>
            <button
              onClick={() => setShowConfirmDelete(false)}
              className="text-muted-foreground hover:text-foreground"
              aria-label="Cancel disconnect"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="flex items-center gap-2 justify-end">
            <button
              onClick={() => setShowConfirmDelete(false)}
              className="px-3 py-1 rounded-lg border border-border bg-background text-xs font-medium text-foreground hover:bg-accent"
            >
              Cancel
            </button>
            <button
              onClick={onDelete}
              disabled={isDeletePending}
              className="px-3 py-1 rounded-lg bg-destructive text-destructive-foreground text-xs font-medium hover:bg-destructive/90 disabled:opacity-50"
            >
              {isDeletePending ? 'Deleting…' : 'Confirm Disconnect'}
            </button>
          </div>
        </div>
      )}
    </>
  );
}

