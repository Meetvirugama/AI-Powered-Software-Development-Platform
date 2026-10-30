import { useState } from 'react';
import {
  Trash2,
  Code,
  Box,
  Clock,
  X,
} from 'lucide-react';
import type { Repository } from '../../types/api';

export interface RepositoryHeaderProps {
  repo: Repository;
  isDeletePending: boolean;
  onDelete: () => void;
  // Optional legacy props kept for type compatibility
  progress?: unknown;
  isReady?: boolean;
  isSyncActive?: boolean;
  onSync?: () => void;
}

export function RepositoryHeader({
  repo,
  isDeletePending,
  onDelete,
}: RepositoryHeaderProps) {
  const [showConfirmDelete, setShowConfirmDelete] = useState(false);

  return (
    <>
      <div className="shrink-0 flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 px-3 py-2 rounded-lg bg-card/60 border border-border/70 text-xs shadow-2xs">
        {/* Left: Metadata badges & Description */}
        <div className="flex flex-wrap items-center gap-2 min-w-0">
          {repo.language && (
            <div className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-muted/40 border border-border/60 text-foreground font-medium text-[11px]">
              <Code className="h-3 w-3 text-primary" />
              <span>{repo.language}</span>
            </div>
          )}

          {repo.framework && (
            <div className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-muted/40 border border-border/60 text-foreground font-medium text-[11px]">
              <Box className="h-3 w-3 text-emerald-500" />
              <span>{repo.framework}</span>
            </div>
          )}

          {repo.last_synced_at && (
            <div className="inline-flex items-center gap-1 text-[11px] text-muted-foreground font-mono">
              <Clock className="h-3 w-3" />
              <span>Synced {new Date(repo.last_synced_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
            </div>
          )}

          {repo.description && (
            <span className="hidden lg:inline text-muted-foreground/80 truncate max-w-md italic text-[11px]">
              — {repo.description}
            </span>
          )}
        </div>

        {/* Right: Disconnect action */}
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => setShowConfirmDelete(true)}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium text-muted-foreground hover:text-destructive hover:bg-destructive/10 border border-transparent hover:border-destructive/20 transition-colors"
            title="Disconnect repository from workspace"
          >
            <Trash2 className="h-3 w-3" />
            <span>Disconnect</span>
          </button>
        </div>
      </div>

      {/* Disconnect Confirmation Alert */}
      {showConfirmDelete && (
        <div
          role="alert"
          className="shrink-0 rounded-lg border border-destructive/30 bg-destructive/10 p-3 space-y-2 animate-in fade-in duration-150"
        >
          <div className="flex items-start justify-between">
            <div>
              <h3 className="font-semibold text-foreground text-xs">Disconnect {repo.name}?</h3>
              <p className="text-[11px] text-muted-foreground mt-0.5">
                This will delete repository indexing data, symbols, and vector chunks from this workspace.
              </p>
            </div>
            <button
              onClick={() => setShowConfirmDelete(false)}
              className="text-muted-foreground hover:text-foreground"
              aria-label="Cancel disconnect"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          <div className="flex items-center gap-2 justify-end">
            <button
              onClick={() => setShowConfirmDelete(false)}
              className="px-2.5 py-1 rounded border border-border bg-background text-xs font-medium text-foreground hover:bg-accent"
            >
              Cancel
            </button>
            <button
              onClick={onDelete}
              disabled={isDeletePending}
              className="px-2.5 py-1 rounded bg-destructive text-destructive-foreground text-xs font-medium hover:bg-destructive/90 disabled:opacity-50"
            >
              {isDeletePending ? 'Deleting…' : 'Confirm Disconnect'}
            </button>
          </div>
        </div>
      )}
    </>
  );
}

export default RepositoryHeader;
