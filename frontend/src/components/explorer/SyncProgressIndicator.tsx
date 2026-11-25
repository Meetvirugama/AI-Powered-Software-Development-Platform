import { CheckCircle2, RefreshCw, XCircle, Clock } from 'lucide-react';
import { cn } from '../../lib/utils';
import type { SyncProgressEntry } from '../../stores/useSyncProgressStore';
import type { SyncStage } from '../../types/api';

const STAGES: Array<{ id: SyncStage; label: string }> = [
  { id: 'CLONING', label: 'Cloning' },
  { id: 'SCANNING', label: 'Scanning' },
  { id: 'INDEXING', label: 'Indexing' },
  { id: 'READY', label: 'Ready' },
];

function computeEtaLabel(progress: SyncProgressEntry): string | null {
  if (progress.files_processed <= 0 || progress.files_total <= progress.files_processed) {
    return null;
  }
  const elapsedMs = progress.updatedAt - progress.startedAt;
  if (elapsedMs < 1000) return null;
  const remainingFiles = progress.files_total - progress.files_processed;
  const etaSeconds = Math.ceil(((elapsedMs / progress.files_processed) * remainingFiles) / 1000);
  if (etaSeconds < 60) return `~${etaSeconds}s left`;
  const mins = Math.ceil(etaSeconds / 60);
  return `~${mins}m left`;
}

export interface SyncProgressIndicatorProps {
  currentStage: SyncStage;
  isFailed: boolean;
  liveProgress?: SyncProgressEntry | null;
}

export function SyncProgressIndicator({
  currentStage,
  isFailed,
  liveProgress,
}: SyncProgressIndicatorProps) {
  const effectiveStage = (!isFailed && (liveProgress?.stage as SyncStage | undefined)) || currentStage;

  let currentIndex = STAGES.findIndex((s) => s.id === effectiveStage);
  if (currentIndex === -1) {
    if (effectiveStage === 'SYNCING') {
      currentIndex = 2; // Active indexing in progress
    } else {
      currentIndex = isFailed ? 0 : -1;
    }
  }

  const rawPct = liveProgress ? Number(liveProgress.progress_pct) : NaN;
  const pct =
    effectiveStage === 'READY'
      ? 100
      : Number.isFinite(rawPct)
      ? Math.min(100, Math.max(0, Math.round(rawPct)))
      : currentIndex > 0
      ? Math.round((currentIndex / (STAGES.length - 1)) * 100)
      : 0;
  const etaLabel = liveProgress ? computeEtaLabel(liveProgress) : null;

  return (
    <div className="space-y-6">
      <div className="relative">
        <div className="flex items-center justify-between">
          {STAGES.map((step, index) => {
            const isCompleted = index < currentIndex || effectiveStage === 'READY';
            const isCurrent = index === currentIndex && !isFailed;
            const isCurrentFailed = index === currentIndex && isFailed;

            return (
              <div key={step.id} className="relative z-10 flex flex-col items-center gap-2">
                <div
                  className={cn(
                    'flex h-9 w-9 items-center justify-center rounded-full border-2 bg-background transition-colors',
                    isCompleted
                      ? 'border-emerald-500 text-emerald-500 shadow-2xs'
                      : isCurrent
                      ? 'border-primary text-primary shadow-xs ring-4 ring-primary/10'
                      : isCurrentFailed
                      ? 'border-destructive text-destructive'
                      : 'border-muted text-muted-foreground/40'
                  )}
                >
                  {isCompleted ? (
                    <CheckCircle2 className="h-4 w-4" />
                  ) : isCurrent ? (
                    <RefreshCw className="h-4 w-4 animate-spin text-primary" />
                  ) : isCurrentFailed ? (
                    <XCircle className="h-4 w-4" />
                  ) : (
                    <Clock className="h-4 w-4 opacity-40" />
                  )}
                </div>

                <span
                  className={cn(
                    'text-xs font-medium transition-colors',
                    isCompleted
                      ? 'text-foreground font-semibold'
                      : isCurrent
                      ? 'text-primary font-semibold'
                      : isCurrentFailed
                      ? 'text-destructive font-semibold'
                      : 'text-muted-foreground'
                  )}
                >
                  {step.label}
                </span>
              </div>
            );
          })}
        </div>

        {/* Track Line */}
        <div className="absolute left-0 top-4.5 -z-10 h-[2px] w-full -translate-y-1/2 bg-muted/60" />

        {/* Active Progress Line */}
        <div
          className="absolute left-0 top-4.5 -z-10 h-[2px] -translate-y-1/2 bg-primary transition-all duration-500 ease-in-out"
          style={{
            width:
              effectiveStage === 'READY'
                ? '100%'
                : currentIndex > 0
                ? `${(currentIndex / (STAGES.length - 1)) * 100}%`
                : '0%',
          }}
        />
      </div>

      {/* Real-time Granular Progress Bar & Counters */}
      {!isFailed && effectiveStage !== 'READY' && liveProgress ? (
        <div className="space-y-2 rounded-lg border border-border/80 bg-muted/20 px-3.5 py-3">
          <div className="flex items-center justify-between gap-2 text-xs">
            <span className="truncate font-medium text-foreground">
              {liveProgress.message || 'Indexing repository files and embeddings…'}
            </span>
            <span className="shrink-0 font-mono text-[11px] font-semibold text-primary tabular-nums">
              {pct}%
            </span>
          </div>
          <div
            role="progressbar"
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Repository indexing progress"
            className="h-2 w-full overflow-hidden rounded-full bg-muted"
          >
            <div
              className="h-full rounded-full bg-primary transition-all duration-300 ease-out"
              style={{ width: `${pct}%` }}
            />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted-foreground font-mono tabular-nums">
            <span>
              {liveProgress.files_total > 0
                ? `${liveProgress.files_processed} / ${liveProgress.files_total} files`
                : 'Preparing repository workspace…'}
              {typeof liveProgress.chunks_embedded === 'number' && liveProgress.chunks_embedded > 0
                ? ` · ${liveProgress.chunks_embedded} chunks embedded`
                : ''}
            </span>
            {etaLabel && <span>{etaLabel}</span>}
          </div>
        </div>
      ) : (
        !isFailed &&
        effectiveStage !== 'READY' && (
          <div className="flex items-center gap-2.5 rounded-lg border border-border/80 bg-muted/20 px-3.5 py-2.5 text-xs text-muted-foreground">
            <RefreshCw className="h-3.5 w-3.5 animate-spin text-primary shrink-0" />
            <span className="truncate">
              Cloning files, extracting AST symbols, and generating 768-d semantic embeddings in the background.
            </span>
          </div>
        )
      )}
    </div>
  );
}

export default SyncProgressIndicator;
