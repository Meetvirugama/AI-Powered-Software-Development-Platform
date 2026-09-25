import { cn } from '../../lib/utils';
import { useNavigate } from 'react-router-dom';
import {
  CheckCircle2,
  RefreshCw,
  XCircle,
  Clock,
  MessageSquare,
  FolderOpen,
} from 'lucide-react';
import type { Repository, SyncStatus } from '../../types/api';

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
  const status = syncStatusConfig(repo.sync_status);

  return (
    <article
      className="flex flex-col gap-4 rounded-xl border border-border bg-card p-5 shadow-sm transition-shadow hover:shadow-md"
      aria-label={`Repository ${repo.full_name}`}
    >
      {/* Header: name + language */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3
            className="truncate text-sm font-semibold text-foreground"
            title={repo.full_name}
          >
            {repo.name}
          </h3>
          <p className="truncate text-xs text-muted-foreground">{repo.owner}</p>
        </div>
        {repo.language && (
          <span className="shrink-0 rounded-full border border-border bg-muted px-2 py-0.5 text-xs text-muted-foreground">
            {repo.language}
          </span>
        )}
      </div>

      {/* Sync status badge */}
      <div className="flex items-center gap-3">
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
        <span className="text-xs text-muted-foreground" aria-label={`Last synced: ${formatLastSynced(repo.last_synced_at)}`}>
          {formatLastSynced(repo.last_synced_at)}
        </span>
      </div>

      {/* Actions */}
      <div className="mt-auto flex gap-2">
        <button
          onClick={() => navigate(`/app/repositories/${repo.id}`)}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={`View ${repo.name}`}
        >
          <FolderOpen className="h-3.5 w-3.5" />
          View
        </button>
        <button
          onClick={() => navigate(`/app/repositories/${repo.id}/chat`)}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={`Ask about ${repo.name}`}
        >
          <MessageSquare className="h-3.5 w-3.5" />
          Ask AI
        </button>
      </div>
    </article>
  );
}
