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
  RotateCw,
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
        icon: <CheckCircle2 className="h-3.5 w-3.5" />,
        className: 'text-emerald-600 bg-emerald-50 border-emerald-200',
      };
    case 'SYNCING':
      return {
        label: 'Syncing…',
        icon: <RefreshCw className="h-3.5 w-3.5 animate-spin" />,
        className: 'text-blue-600 bg-blue-50 border-blue-200',
      };
    case 'FAILED':
      return {
        label: 'Failed',
        icon: <XCircle className="h-3.5 w-3.5" />,
        className: 'text-destructive bg-destructive/10 border-destructive/20',
      };
    case 'NOT_SYNCED':
      return {
        label: 'Not synced',
        icon: <Clock className="h-3.5 w-3.5" />,
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
  const { mutate: deleteRepo, isPending: isDeletePending } = useDeleteRepository();

  const isSyncing = repo.sync_status === 'SYNCING' || isSyncPending;
  const isFailed = repo.sync_status === 'FAILED';
  const isNotSynced = repo.sync_status === 'NOT_SYNCED';
  const isSynced = repo.sync_status === 'SYNCED';

  const status = syncStatusConfig(isSyncing ? 'SYNCING' : repo.sync_status);

  function handleSync(e: React.MouseEvent) {
    e.stopPropagation();
    triggerSync(repo.id);
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
      className="group relative flex flex-col gap-4 rounded-xl border border-border bg-card p-5 shadow-sm transition-all hover:shadow-md hover:border-border/80"
      aria-label={`Repository ${repo.full_name}`}
    >
      {/* Top Header: name, language, quick actions */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <button
            onClick={() => navigate(`/app/repositories/${repo.id}`)}
            className="text-left font-semibold text-foreground hover:text-primary transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
            title={repo.full_name}
          >
            <h3 className="truncate text-sm">{repo.name}</h3>
          </button>
          <p className="truncate text-xs text-muted-foreground">{repo.owner}</p>
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          {repo.language && (
            <span className="rounded-full border border-border bg-muted px-2 py-0.5 text-xs text-muted-foreground font-mono">
              {repo.language}
            </span>
          )}

          {/* Quick Re-sync button */}
          <button
            onClick={handleSync}
            disabled={isSyncing}
            className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-accent transition-colors disabled:opacity-40"
            title="Re-sync repository"
            aria-label={`Re-sync ${repo.name}`}
          >
            <RotateCw className={cn("h-3.5 w-3.5", isSyncing && "animate-spin text-primary")} />
          </button>

          {/* Quick Delete / Disconnect button */}
          <button
            onClick={(e) => {
              e.stopPropagation();
              setShowConfirmDelete(true);
            }}
            className="p-1 rounded text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
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
              'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium',
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

        {/* If failed or not synced, show a direct inline sync button */}
        {(isFailed || isNotSynced) && (
          <button
            onClick={handleSync}
            disabled={isSyncing}
            className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:text-primary/80 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={cn("h-3 w-3", isSyncing && "animate-spin")} />
            {isFailed ? 'Retry' : 'Sync'}
          </button>
        )}
      </div>

      {/* Confirmation banner for deletion */}
      {showConfirmDelete && (
        <div
          role="alert"
          className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-xs space-y-2"
        >
          <p className="text-foreground font-medium">Disconnect this repository?</p>
          <p className="text-muted-foreground">This removes all indexed files and vector embeddings.</p>
          <div className="flex items-center gap-2 justify-end pt-1">
            <button
              onClick={() => setShowConfirmDelete(false)}
              className="px-2.5 py-1 rounded border border-border bg-background text-foreground hover:bg-accent"
            >
              Cancel
            </button>
            <button
              onClick={handleDelete}
              disabled={isDeletePending}
              className="px-2.5 py-1 rounded bg-destructive text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50 font-medium"
            >
              {isDeletePending ? 'Removing…' : 'Disconnect'}
            </button>
          </div>
        </div>
      )}

      {/* Action Buttons */}
      <div className="mt-auto flex gap-2 pt-1">
        <button
          onClick={() => navigate(`/app/repositories/${repo.id}`)}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-border bg-background px-3 py-2 text-xs font-medium text-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={`View ${repo.name}`}
        >
          <FolderOpen className="h-3.5 w-3.5" />
          View
        </button>

        {isFailed || isNotSynced ? (
          <button
            onClick={handleSync}
            disabled={isSyncing}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
            aria-label={`Sync ${repo.name}`}
          >
            <RefreshCw className={cn("h-3.5 w-3.5", isSyncing && "animate-spin")} />
            {isSyncing ? 'Syncing…' : isFailed ? 'Retry Sync' : 'Sync Now'}
          </button>
        ) : (
          <button
            onClick={() => navigate(`/app/repositories/${repo.id}/chat`)}
            disabled={!isSynced}
            className={cn(
              "flex flex-1 items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              isSynced
                ? "bg-primary text-primary-foreground hover:bg-primary/90"
                : "bg-muted text-muted-foreground cursor-not-allowed opacity-60"
            )}
            aria-label={`Ask about ${repo.name}`}
            title={!isSynced ? "Sync repository first to use AI chat" : undefined}
          >
            <MessageSquare className="h-3.5 w-3.5" />
            Ask AI
          </button>
        )}
      </div>
    </article>
  );
}

