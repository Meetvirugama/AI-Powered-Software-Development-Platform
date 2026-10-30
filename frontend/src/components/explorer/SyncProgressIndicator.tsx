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
  if (currentStage === 'SYNCING') {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-border/80 bg-muted/40 px-4 py-3">
        <RefreshCw className="h-4 w-4 animate-spin text-primary shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium text-foreground">Syncing repository…</p>
          <p className="text-[11px] text-muted-foreground truncate">
            Cloning files and indexing symbols in the background.
          </p>
        </div>
      </div>
    );
  }

  let currentIndex = STAGES.findIndex((s) => s.id === currentStage);
  if (currentIndex === -1) {
    currentIndex = isFailed ? 0 : -1;
  }

  return (
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
                    ? 'border-emerald-600 text-emerald-600'
                    : isCurrent
                    ? 'border-blue-600 text-blue-600 shadow-sm'
                    : isCurrentFailed
                    ? 'border-destructive text-destructive'
                    : 'border-muted-foreground/30 text-muted-foreground'
                )}
              >
                {isCompleted ? (
                  <CheckCircle2 className="h-4 w-4" />
                ) : isCurrent ? (
                  <RefreshCw className="h-4 w-4 animate-spin" />
                ) : isCurrentFailed ? (
                  <XCircle className="h-4 w-4" />
                ) : (
                  <Clock className="h-4 w-4 opacity-50" />
                )}
              </div>

              <span
                className={cn(
                  'text-xs font-medium transition-colors',
                  isCompleted
                    ? 'text-foreground'
                    : isCurrent
                    ? 'text-blue-500'
                    : isCurrentFailed
                    ? 'text-destructive'
                    : 'text-muted-foreground'
                )}
              >
                {step.label}
              </span>
            </div>
          );
        })}
      </div>

      <div className="absolute left-0 top-4.5 -z-10 h-[2px] w-full -translate-y-1/2 bg-muted-foreground/20" />

      <div
        className="absolute left-0 top-4.5 -z-10 h-[2px] -translate-y-1/2 bg-emerald-600 transition-all duration-500 ease-in-out"
        style={{
          width:
            currentIndex > 0
              ? `${(currentIndex / (STAGES.length - 1)) * 100}%`
              : currentStage === 'READY'
              ? '100%'
              : '0%',
        }}
      />
    </div>
  );
}
