import { RefreshCw, Database } from 'lucide-react';
import { cn } from '../../lib/utils';
import { SyncProgressIndicator } from './SyncProgressIndicator';
import type { Repository, SyncProgress } from '../../types/api';

export interface RepositorySyncCardProps {
  repo: Pick<Repository, 'sync_status'>;
  progress: SyncProgress;
  isSyncActive: boolean;
  onSync: () => void;
}

export function RepositorySyncCard({
  repo,
  progress,
  isSyncActive,
  onSync,
}: RepositorySyncCardProps) {
  return (
    <div className="flex-1 min-h-0 flex items-center justify-center p-4 sm:p-6">
      <div className="w-full max-w-xl rounded-2xl border border-border bg-card/80 backdrop-blur-sm p-6 sm:p-8 shadow-md space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-border/60 pb-5">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="p-1.5 rounded-md bg-primary/10 text-primary">
                <Database className="h-4 w-4" />
              </span>
              <h2 className="text-base font-semibold text-foreground tracking-tight">
                {progress.isFailed
                  ? 'Synchronization Failed'
                  : isSyncActive
                  ? 'Repository Synchronization in Progress'
                  : 'Repository Not Synced'}
              </h2>
            </div>
            <p className="text-xs text-muted-foreground">
              {progress.isFailed
                ? 'An issue occurred during repository indexing. Click Retry to re-run the sync process.'
                : isSyncActive
                ? 'Files are being cloned, scanned, and indexed into the AI vector database.'
                : 'This repository has not been indexed yet. Start synchronization to enable file explorer and AI chat.'}
            </p>
          </div>

          {(progress.isFailed || repo.sync_status === 'NOT_SYNCED') && (
            <button
              onClick={onSync}
              disabled={isSyncActive}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3.5 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50 shrink-0 shadow-xs"
            >
              <RefreshCw className={cn('h-3.5 w-3.5', isSyncActive && 'animate-spin')} />
              <span>{isSyncActive ? 'Starting…' : 'Retry Sync'}</span>
            </button>
          )}
        </div>

        <SyncProgressIndicator
          currentStage={progress.stage}
          isFailed={progress.isFailed}
        />
      </div>
    </div>
  );
}

export default RepositorySyncCard;
