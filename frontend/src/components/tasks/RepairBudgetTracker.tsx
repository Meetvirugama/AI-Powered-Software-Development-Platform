import {
  Wrench,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Clock,
  GitCommit,
  ShieldAlert,
} from 'lucide-react';
import { useTaskRepairBudget } from '../../hooks/useTasks';
import type { RepairAttemptRecord, WorkspaceRepairBudgetStatus } from '../../types/task';
import { cn } from '../../lib/utils';
import { LoadingSpinner } from '../shared/LoadingSpinner';
import { ErrorMessage } from '../shared/ErrorMessage';

export interface RepairBudgetTrackerProps {
  taskId?: string;
  budget?: WorkspaceRepairBudgetStatus | null;
  repairAttemptsUsed?: number | null;
  repairAttemptsMax?: number | null;
  history?: RepairAttemptRecord[];
  isEligibleForRepair?: boolean;
  isLoading?: boolean;
  error?: any;
  className?: string;
}

function formatDate(dateStr: string): string {
  try {
    return new Date(dateStr).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return dateStr;
  }
}

export function RepairBudgetTracker({
  taskId,
  budget: propBudget,
  repairAttemptsUsed,
  repairAttemptsMax,
  history: propHistory,
  isEligibleForRepair: propEligible,
  isLoading: propLoading = false,
  error: propError = null,
  className,
}: RepairBudgetTrackerProps) {
  const {
    data: fetchedBudget,
    isLoading: queryLoading,
    error: queryError,
  } = useTaskRepairBudget(taskId, {
    enabled: Boolean(taskId) && propBudget === undefined,
  });

  const budget = propBudget !== undefined ? propBudget : fetchedBudget;
  const isLoading = propLoading || (queryLoading && repairAttemptsUsed === undefined && repairAttemptsMax === undefined);
  const error = propError || (queryError && repairAttemptsUsed === undefined && repairAttemptsMax === undefined ? queryError : null);
  if (isLoading) {
    return (
      <div
        data-testid="repair-budget-tracker"
        className={cn(
          'rounded-lg border border-border bg-card p-5 shadow-xs space-y-3',
          className
        )}
      >
        <div className="flex items-center gap-2 border-b border-border pb-3">
          <Wrench className="h-4 w-4 text-primary" />
          <h3 className="text-base font-semibold text-foreground">Bounded Repair Budget</h3>
        </div>
        <div className="py-6 text-center space-y-2">
          <LoadingSpinner size="sm" label="Loading repair budget..." />
          <p className="text-xs text-muted-foreground">Fetching repair attempt limits...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div
        data-testid="repair-budget-tracker"
        className={cn(
          'rounded-lg border border-border bg-card p-5 shadow-xs space-y-3',
          className
        )}
      >
        <div className="flex items-center gap-2 border-b border-border pb-3">
          <Wrench className="h-4 w-4 text-primary" />
          <h3 className="text-base font-semibold text-foreground">Bounded Repair Budget</h3>
        </div>
        <ErrorMessage error={error} message="Failed to load repair budget telemetry." />
      </div>
    );
  }

  const effectiveUsed = budget !== undefined && budget !== null
    ? budget.repair_attempts_used
    : repairAttemptsUsed;
  const effectiveMax = budget !== undefined && budget !== null
    ? budget.repair_attempts_max
    : repairAttemptsMax;
  const history = budget?.history ?? propHistory ?? [];
  const isEligibleForRepair = budget?.is_eligible_for_repair ?? propEligible ?? true;

  // Gracefully handle missing server telemetry: never fabricate values
  const hasTelemetry =
    effectiveUsed !== undefined &&
    effectiveUsed !== null &&
    effectiveMax !== undefined &&
    effectiveMax !== null;

  if (!hasTelemetry) {
    return (
      <div
        data-testid="repair-budget-tracker"
        className={cn(
          'rounded-lg border border-border bg-card p-5 shadow-xs space-y-3',
          className
        )}
      >
        <div className="flex items-center gap-2 border-b border-border pb-3">
          <Wrench className="h-4 w-4 text-primary" />
          <h3 className="text-base font-semibold text-foreground">Bounded Repair Budget</h3>
        </div>
        <div className="p-4 text-center border border-dashed border-border rounded-md bg-background/50">
          <p className="text-xs text-muted-foreground italic">
            Repair telemetry not available yet from the server.
          </p>
        </div>
      </div>
    );
  }

  const used = effectiveUsed;
  const max = effectiveMax;
  const remaining = Math.max(0, max - used);
  const isExhausted = budget?.is_budget_exhausted ?? used >= max;

  // Render slots for each attempt up to max (e.g. 3)
  const slotCount = Math.max(max, 3);
  const slots = Array.from({ length: slotCount }, (_, idx) => idx + 1);

  return (
    <div
      data-testid="repair-budget-tracker"
      className={cn(
        'rounded-lg border border-border bg-card p-5 shadow-xs space-y-4',
        className
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border pb-3">
        <div className="flex items-center gap-2">
          <Wrench className="h-4 w-4 text-primary" />
          <h3 className="text-base font-semibold text-foreground">Bounded Repair Budget</h3>
        </div>

        <div className="flex items-center gap-2">
          <span
            data-testid="repair-attempts-count"
            className={cn(
              'font-mono text-xs font-semibold px-2 py-0.5 rounded border',
              isExhausted
                ? 'bg-rose-500/10 text-rose-400 border-rose-500/30'
                : used > 0
                ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
            )}
          >
            {used} / {max} Attempts Used
          </span>
        </div>
      </div>

      {/* Visual Attempt Slots */}
      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>Attempt Allocation (Max {max} per ADR-010):</span>
          <span className="font-mono text-[11px]">
            {remaining} attempt{remaining === 1 ? '' : 's'} remaining
          </span>
        </div>

        <div className="grid grid-cols-3 gap-2.5">
          {slots.map((slotNum) => {
            const isUsedSlot = slotNum <= used;
            const slotHistory = history.find((h) => h.attempt_number === slotNum);

            return (
              <div
                key={slotNum}
                data-testid={`repair-slot-${slotNum}`}
                className={cn(
                  'rounded-md border p-3 flex flex-col items-center justify-center text-center space-y-1 transition-colors',
                  isUsedSlot
                    ? isExhausted
                      ? 'bg-rose-500/10 border-rose-500/30 text-rose-300'
                      : 'bg-amber-500/10 border-amber-500/30 text-amber-300'
                    : 'bg-background/60 border-border/80 text-muted-foreground'
                )}
              >
                <div className="flex items-center gap-1 font-mono text-xs font-bold">
                  {isUsedSlot ? (
                    slotHistory?.success ? (
                      <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                    ) : (
                      <XCircle className="h-3.5 w-3.5 text-rose-400" />
                    )
                  ) : (
                    <Clock className="h-3.5 w-3.5 text-muted-foreground/60" />
                  )}
                  <span>Attempt {slotNum}</span>
                </div>

                <span className="text-[10px] font-mono uppercase">
                  {isUsedSlot
                    ? slotHistory?.success
                      ? 'Success'
                      : 'Used / Failed'
                    : 'Available'}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Retry Budget Exhaustion Warning Banner */}
      {isExhausted && (
        <div
          data-testid="repair-budget-exhausted-banner"
          className="rounded-md border border-rose-500/30 bg-rose-500/10 p-3.5 text-xs text-rose-200 space-y-1.5"
        >
          <div className="flex items-center gap-1.5 font-semibold text-rose-400">
            <ShieldAlert className="h-4 w-4 shrink-0" />
            <span>Repair Budget Exhausted — Auto-Repair Terminated</span>
          </div>
          <p className="pl-5.5 text-rose-200/90 leading-relaxed">
            Maximum repair budget limit reached ({max}/{max}). Automatic repair cannot continue. The hard limit of {max} task-level repair attempts has been exhausted in accordance with platform safety constraints (ADR-010). Review test failures and inspect diffs manually.
          </p>
        </div>
      )}

      {/* Repair Eligibility Note */}
      {!isEligibleForRepair && !isExhausted && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-300 flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400 mt-0.5" />
          <p className="leading-relaxed">
            The latest test failure was classified as non-repairable (e.g. infrastructure error, timeout, or security policy violation). Auto-repair will not consume budget for this run.
          </p>
        </div>
      )}

      {/* Repair Attempt History */}
      {history.length > 0 && (
        <div className="space-y-2 pt-2 border-t border-border/60">
          <h4 className="text-xs font-semibold uppercase text-muted-foreground tracking-wider">
            Repair History ({history.length})
          </h4>

          <div className="space-y-2">
            {history.map((record) => (
              <div
                key={record.attempt_number}
                data-testid={`repair-history-item-${record.attempt_number}`}
                className="rounded-md border border-border/80 bg-background/50 p-3 text-xs space-y-1.5"
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono font-bold text-foreground">
                    Attempt #{record.attempt_number}
                  </span>
                  <span className="text-[10px] text-muted-foreground font-mono">
                    {formatDate(record.timestamp)}
                  </span>
                </div>

                <p className="text-foreground/90 font-medium">{record.patch_summary}</p>

                <div className="flex items-center gap-3 font-mono text-[11px] text-muted-foreground flex-wrap pt-0.5">
                  {record.workspace_revision && (
                    <span className="flex items-center gap-1">
                      <GitCommit className="h-3 w-3 text-purple-400" />
                      Revision: {record.workspace_revision.substring(0, 8)}
                    </span>
                  )}
                  {record.test_status_before && record.test_status_after && (
                    <span>
                      Outcome: {record.test_status_before} → {record.test_status_after}
                    </span>
                  )}
                  <span
                    className={cn(
                      'px-1.5 py-0.2 rounded text-[10px] font-semibold',
                      record.success
                        ? 'bg-emerald-500/10 text-emerald-400'
                        : 'bg-rose-500/10 text-rose-400'
                    )}
                  >
                    {record.success ? 'Resolved' : 'Failed'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
