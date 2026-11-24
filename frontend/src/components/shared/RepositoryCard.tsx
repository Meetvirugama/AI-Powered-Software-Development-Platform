import { useState } from 'react';
import { cn } from '../../lib/utils';
import { useNavigate } from 'react-router-dom';
import {
  CheckCircle2,
  RefreshCw,
  XCircle,
  Clock,
  MessageSquare,
  FolderOpen,
  Trash2,
} from 'lucide-react';
import type { Repository, SyncStatus } from '../../types/api';
import { useSyncRepository, useDeleteRepository } from '../../hooks/useRepositories';

// ---------------------------------------------------------------------------
// Sync status presentation
// ---------------------------------------------------------------------------

interface StatusConfig {
  label: string;
  icon: React.ReactNode;
  className: string;
}

function syncStatusConfig(status: SyncStatus): StatusConfig {
  switch (status) {
    case 'SYNCED':
      return {
        label: 'Synced',
        icon: <CheckCircle2 className="h-3 w-3" />,
        className: 'text-emerald-700 dark:text-emerald-400 bg-emerald-500/10 border-emerald-500/25',
      };
    case 'SYNCING':
      return {
        label: 'Syncing…',
        icon: <RefreshCw className="h-3 w-3 animate-spin" />,
        className: 'text-amber-700 dark:text-amber-400 bg-amber-500/10 border-amber-500/25',
      };
    case 'FAILED':
      return {
        label: 'Failed',
        icon: <XCircle className="h-3 w-3" />,
        className: 'text-destructive bg-destructive/10 border-destructive/25',
      };
    case 'NOT_SYNCED':
      return {
        label: 'Not synced',
        icon: <Clock className="h-3 w-3" />,
        className: 'text-muted-foreground bg-muted border-border',
      };
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatLastSynced(isoString: string | null): string {
  if (!isoString) return 'Never';
  const date = new Date(isoString);
  const now = Date.now();
  const diffMs = now - date.getTime();
  const diffMins = Math.floor(diffMs / 60_000);
  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}

// ---------------------------------------------------------------------------
// RepositoryCard
// ---------------------------------------------------------------------------

interface RepositoryCardProps {
  repo: Repository;
}

export function RepositoryCard({ repo }: RepositoryCardProps) {
  const navigate = useNavigate();
  const [showConfirmDelete, setShowConfirmDelete] = useState(false);

  const { mutate: triggerSync, isPending: isSyncPending } = useSyncRepository();
  const { mutate: deleteRepo, isPending: isDeletePending, error: deleteError } = useDeleteRepository();

  const isSyncing = repo.sync_status === 'SYNCING' || isSyncPending;
  const isFailed = repo.sync_status === 'FAILED';
  const isNotSynced = repo.sync_status === 'NOT_SYNCED';

  const status = syncStatusConfig(isSyncing ? 'SYNCING' : repo.sync_status);

  function handleSync(e: React.MouseEvent) {
    e.stopPropagation();
    triggerSync({ id: repo.id, force: isFailed });
  }

  function handleDelete(e: React.MouseEvent) {
    e.stopPropagation();
    deleteRepo(repo.id, {
      onSuccess: () => {
        setShowConfirmDelete(false);
      },
    });
  }

  return (
    <article
      className="group relative flex flex-col gap-3.5 rounded-xl border border-border bg-card p-4 transition-colors hover:border-foreground/20"
      aria-label={`Repository ${repo.full_name}`}
    >
      {/* Top Header: name, language, quick actions */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <button
            type="button"
            onClick={() => navigate(`/app/repositories/${repo.id}`)}
            className="block max-w-full text-left font-semibold text-foreground hover:underline transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded cursor-pointer"
            title={repo.full_name}
          >
            <h3 className="truncate text-sm">{repo.name}</h3>
          </button>
          <p className="truncate text-xs text-muted-foreground mt-0.5">{repo.owner}</p>
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          {repo.language && (
            <span className="rounded-md bg-muted px-2 py-0.5 text-[11px] text-muted-foreground font-mono">
              {repo.language}
            </span>
          )}

          {/* Quick Delete / Disconnect button */}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setShowConfirmDelete(true);
            }}
            className="inline-flex items-center justify-center min-h-8 min-w-8 p-1.5 rounded-md text-muted-foreground opacity-80 sm:opacity-65 sm:group-hover:opacity-100 focus-visible:opacity-100 hover:text-destructive hover:bg-destructive/10 transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
            title="Disconnect repository"
            aria-label={`Disconnect ${repo.name}`}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Sync status badge + timestamp */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium',
              status.className,
            )}
            aria-label={`Sync status: ${status.label}`}
          >
            {status.icon}
            {status.label}
          </span>
          <span
            className="text-xs text-muted-foreground"
            aria-label={`Last synced: ${formatLastSynced(repo.last_synced_at)}`}
          >
            {formatLastSynced(repo.last_synced_at)}
          </span>
        </div>
      </div>

      {/* Why the last sync failed (recorded by the sync worker) */}
      {isFailed && repo.last_sync_error && (
        <p
          className="rounded-md border border-destructive/20 bg-destructive/5 px-2.5 py-1.5 text-[11px] text-destructive line-clamp-2"
          title={repo.last_sync_error}
        >
          {repo.last_sync_error}
        </p>
      )}

      {/* Confirmation banner for deletion */}
      {showConfirmDelete && (
        <div
          role="alert"
          className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-xs space-y-2"
        >
          <p className="text-foreground font-medium">Disconnect this repository?</p>
          <p className="text-muted-foreground">This removes all indexed files and vector embeddings.</p>
          {deleteError && (
            <p className="text-destructive">{deleteError.message || 'Could not disconnect the repository.'}</p>
          )}
          <div className="flex items-center gap-2 justify-end pt-1">
            <button
              type="button"
              onClick={() => setShowConfirmDelete(false)}
              className="px-2.5 py-1.5 rounded border border-border bg-background text-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleDelete}
              disabled={isDeletePending}
              className="px-2.5 py-1.5 rounded bg-destructive text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring font-medium cursor-pointer"
            >
              {isDeletePending ? 'Removing…' : 'Disconnect'}
            </button>
          </div>
        </div>
      )}

      {/* Action Buttons: strictly 2 consistent enterprise actions */}
      <div className="mt-auto flex flex-wrap gap-2 pt-1">
        <button
          type="button"
          onClick={() => navigate(`/app/repositories/${repo.id}`)}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-border bg-background px-3 py-2 text-xs font-medium text-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
          aria-label={`View ${repo.name}`}
        >
          <FolderOpen className="h-3.5 w-3.5" />
          View
        </button>

        {isSyncing ? (
          <button
            type="button"
            disabled
            className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-amber-500/10 border border-amber-500/25 px-3 py-2 text-xs font-medium text-amber-700 dark:text-amber-400 cursor-not-allowed"
            aria-label={`Syncing ${repo.name}`}
          >
            <RefreshCw className="h-3.5 w-3.5 animate-spin" />
            <span>Syncing…</span>
          </button>
        ) : isFailed ? (
          <button
            type="button"
            onClick={handleSync}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-destructive px-3 py-2 text-xs font-medium text-destructive-foreground transition-colors hover:bg-destructive/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring shadow-xs cursor-pointer"
            aria-label={`Retry sync for ${repo.name}`}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            <span>Retry Sync</span>
          </button>
        ) : isNotSynced ? (
          <button
            type="button"
            onClick={handleSync}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring shadow-xs cursor-pointer"
            aria-label={`Sync ${repo.name}`}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            <span>Sync Now</span>
          </button>
        ) : (
          <button
            type="button"
            onClick={() => navigate(`/app/repositories/${repo.id}/chat`)}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring shadow-xs cursor-pointer"
            aria-label={`Ask about ${repo.name}`}
          >
            <MessageSquare className="h-3.5 w-3.5" />
            <span>Ask AI</span>
          </button>
        )}
      </div>
    </article>
  );
}

