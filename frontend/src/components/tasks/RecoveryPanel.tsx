import { useState } from 'react';
import {
  AlertTriangle,
  RefreshCw,
  RotateCcw,
  Play,
  CheckCircle2,
} from 'lucide-react';
import { useRecoverTask, useTaskRepairBudget } from '../../hooks/useTasks';
import { TaskStatus, canRecoverTask, type TaskDetailResponse } from '../../types/task';
import type { ApiError } from '../../types/api';
import { LoadingSpinner } from '../shared/LoadingSpinner';
import { cn } from '../../lib/utils';

export interface RecoveryPanelProps {
  task: TaskDetailResponse;
  className?: string;
  onRecovered?: () => void;
}

export function RecoveryPanel({ task, className, onRecovered }: RecoveryPanelProps) {
  const recoverMutation = useRecoverTask(task.task_id);
  const { data: repairBudget } = useTaskRepairBudget(task.task_id);
  const [error, setError] = useState<ApiError | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  if (!canRecoverTask(task.status)) {
    return null;
  }

  const isPending = recoverMutation.isPending;
  const isBudgetExhausted =
    task.repair_attempts_used >= task.repair_attempts_max ||
    Boolean(repairBudget?.is_budget_exhausted);

  // Permitted recovery actions strictly governed by backend state contracts:
  // - FAILED: reconcile, reset_to_plan, and retry (ONLY when repair budget remains)
  // - RECOVERY_REQUIRED: reconcile, reset_to_plan (retry is invalid for crash/interruption recovery)
  // - BLOCKED: reconcile (reset_to_plan and retry are invalid for policy/resource blocks)
  const allowRetry = task.status === TaskStatus.FAILED && !isBudgetExhausted;
  const allowReconcile =
    task.status === TaskStatus.RECOVERY_REQUIRED ||
    task.status === TaskStatus.FAILED ||
    task.status === TaskStatus.BLOCKED;
  const allowResetToPlan =
    task.status === TaskStatus.RECOVERY_REQUIRED || task.status === TaskStatus.FAILED;

  async function handleAction(action: 'retry' | 'reconcile' | 'reset_to_plan') {
    setError(null);
    setSuccessMessage(null);
    try {
      const res = await recoverMutation.mutateAsync({
        action,
        reason: `User requested recovery via ${action}`,
      });
      // Only set success after confirmed backend response
      setSuccessMessage(res.details || `Task recovered successfully (${res.current_status}).`);
      if (onRecovered) {
        onRecovered();
      }
    } catch (err) {
      setError(err as ApiError);
    }
  }

  return (
    <div
      data-testid="recovery-panel"
      className={cn(
        'rounded-lg border border-amber-500/40 bg-amber-500/10 p-5 shadow-xs space-y-4 text-xs',
        className
      )}
    >
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-amber-500/20 pb-3">
        <div className="flex items-center gap-2.5">
          <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0" />
          <div>
            <h4 className="font-semibold text-amber-300">
              {task.status === TaskStatus.RECOVERY_REQUIRED && 'State Recovery Required'}
              {task.status === TaskStatus.FAILED && 'Task Execution Halted — Recovery Available'}
              {task.status === TaskStatus.BLOCKED && 'Task Operation Blocked — Intervention Required'}
            </h4>
            <p className="text-[11px] text-amber-200/80">
              {task.status === TaskStatus.RECOVERY_REQUIRED &&
                'A worker crash or process interruption was detected. Reconcile workspace state to resume safely.'}
              {task.status === TaskStatus.FAILED &&
                'The previous execution run terminated with failure. Review logs and dispatch state reconciliation or retry.'}
              {task.status === TaskStatus.BLOCKED &&
                'Execution is held pending external resource resolution or policy unblocking.'}
            </p>
          </div>
        </div>

        <span className="font-mono text-[10px] bg-amber-500/20 text-amber-200 border border-amber-500/30 px-2 py-0.5 rounded uppercase font-bold shrink-0 self-start sm:self-auto">
          {task.status}
        </span>
      </div>

      {isBudgetExhausted && task.status === TaskStatus.FAILED && (
        <div
          data-testid="recovery-budget-exhausted-banner"
          className="rounded border border-rose-500/30 bg-rose-500/10 p-2.5 text-rose-300 text-[11px] flex items-center gap-2"
        >
          <AlertTriangle className="h-3.5 w-3.5 text-rose-400 shrink-0" />
          <span>Automated repair attempts limit reached ({task.repair_attempts_used}/{task.repair_attempts_max}). Retrying is unavailable.</span>
        </div>
      )}

      {error && (
        <div
          data-testid="recovery-error-alert"
          className="rounded border border-rose-500/30 bg-rose-500/10 p-3 text-rose-200 text-xs flex items-center justify-between"
        >
          <span>{error.message || 'Recovery operation failed.'}</span>
          <button
            type="button"
            onClick={() => setError(null)}
            className="text-xs text-rose-400 hover:text-rose-200 underline ml-2 cursor-pointer"
          >
            Dismiss
          </button>
        </div>
      )}

      {successMessage && (
        <div
          data-testid="recovery-success-alert"
          className="rounded border border-emerald-500/30 bg-emerald-500/10 p-3 text-emerald-200 text-xs flex items-center gap-2"
        >
          <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
          <span>{successMessage}</span>
        </div>
      )}

      <div className="flex items-center justify-between flex-wrap gap-3 pt-1">
        <span className="text-[11px] text-amber-200/70">
          Only backend-authorized lifecycle state reconciliations are permitted.
        </span>

        <div className="flex items-center gap-2">
          {allowReconcile && (
            <button
              type="button"
              data-testid="reconcile-state-button"
              disabled={isPending}
              onClick={() => handleAction('reconcile')}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-amber-500/40 bg-amber-500/20 text-amber-200 hover:bg-amber-500/30 transition-colors disabled:opacity-50 cursor-pointer"
            >
              {isPending ? (
                <LoadingSpinner size="sm" label="Reconciling..." />
              ) : (
                <RefreshCw className="h-3 w-3" />
              )}
              <span>Reconcile State</span>
            </button>
          )}

          {allowRetry && (
            <button
              type="button"
              data-testid="retry-execution-button"
              disabled={isPending}
              onClick={() => handleAction('retry')}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md bg-amber-600 text-white hover:bg-amber-500 transition-colors disabled:opacity-50 cursor-pointer shadow-xs"
            >
              {isPending ? (
                <LoadingSpinner size="sm" label="Retrying..." />
              ) : (
                <Play className="h-3 w-3" />
              )}
              <span>Retry Execution</span>
            </button>
          )}

          {allowResetToPlan && (
            <button
              type="button"
              data-testid="reset-plan-button"
              disabled={isPending}
              onClick={() => handleAction('reset_to_plan')}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-border bg-card text-muted-foreground hover:text-foreground hover:bg-accent transition-colors disabled:opacity-50 cursor-pointer"
            >
              <RotateCcw className="h-3 w-3" />
              <span>Reset to Plan</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
