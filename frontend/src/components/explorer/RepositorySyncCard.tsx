import { RefreshCw } from 'lucide-react';
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
    <div className="flex-1 min-h-0 flex items-center justify-center p-4">
      <div className="w-full max-w-xl rounded-xl border border-border bg-card p-6 shadow-sm space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h2 className="text-base font-semibold text-foreground">
              {progress.isFailed
                ? 'Synchronization Failed'
                : isSyncActive
                ? 'Repository Synchronization in Progress'
                : 'Repository Not Synced'}
            </h2>
            <p className="text-xs text-muted-foreground mt-1">
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
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50 shrink-0"
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
