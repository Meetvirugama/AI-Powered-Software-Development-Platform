import { CheckCircle2, RefreshCw, XCircle, Clock } from 'lucide-react';
import { cn } from '../../lib/utils';
import type { SyncStage } from '../../types/api';

const STAGES: Array<{ id: SyncStage; label: string }> = [
  { id: 'CLONING', label: 'Cloning' },
  { id: 'SCANNING', label: 'Scanning' },
  { id: 'INDEXING', label: 'Indexing' },
  { id: 'READY', label: 'Ready' },
];

export interface SyncProgressIndicatorProps {
  currentStage: SyncStage;
  isFailed: boolean;
}

export function SyncProgressIndicator({
  currentStage,
  isFailed,
}: SyncProgressIndicatorProps) {
  let currentIndex = STAGES.findIndex((s) => s.id === currentStage);
  if (currentIndex === -1) {
    if (currentStage === 'SYNCING') {
      currentIndex = 2; // Active indexing in progress
    } else {
      currentIndex = isFailed ? 0 : -1;
    }
  }

  return (
    <div className="space-y-6">
      <div className="relative">
        <div className="flex items-center justify-between">
          {STAGES.map((step, index) => {
            const isCompleted = index < currentIndex || currentStage === 'READY';
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
              currentStage === 'READY'
                ? '100%'
                : currentIndex > 0
                ? `${(currentIndex / (STAGES.length - 1)) * 100}%`
                : '0%',
          }}
        />
      </div>

      {/* Real-time Subtitle Banner */}
      {!isFailed && currentStage !== 'READY' && (
        <div className="flex items-center gap-2.5 rounded-lg border border-border/80 bg-muted/20 px-3.5 py-2.5 text-xs text-muted-foreground">
          <RefreshCw className="h-3.5 w-3.5 animate-spin text-primary shrink-0" />
          <span className="truncate">
            Cloning files, extracting AST symbols, and generating 768-d semantic embeddings in the background.
          </span>
        </div>
      )}
    </div>
  );
}

export default SyncProgressIndicator;
