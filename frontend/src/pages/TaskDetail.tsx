import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import {
  ChevronLeft,
  FolderGit2,
  ExternalLink,
  Layers,
  HelpCircle,
  ShieldAlert,
  FileCode2,
  Wrench,
  Clock,
  RefreshCw,
  Play,
  Slash,
  AlertTriangle,
} from 'lucide-react';
import { useTask, useExecuteTask, useCancelTask, useTaskPlan, taskKeys } from '../hooks/useTasks';
import { TaskStatus, isExecutionActive, canCancelTask } from '../types/task';
import type { ApiError } from '../types/api';
import { TaskStatusBadge } from '../components/tasks/TaskStatusBadge';
import { PlanReviewPanel } from '../components/tasks/PlanReviewPanel';
import { ApprovalHistoryPanel } from '../components/tasks/ApprovalHistoryPanel';
import { ExecutionTimeline } from '../components/tasks/ExecutionTimeline';
import { WorkspacePanel } from '../components/tasks/WorkspacePanel';
import { CodeChangesPanel } from '../components/tasks/CodeChangesPanel';
import { TestExecutionPanel } from '../components/tasks/TestExecutionPanel';
import { RepairBudgetTracker } from '../components/tasks/RepairBudgetTracker';
import { LoadingSpinner } from '../components/shared/LoadingSpinner';
import { ErrorMessage } from '../components/shared/ErrorMessage';
import { cn } from '../lib/utils';

function formatDate(dateStr: string): string {
  try {
    return new Date(dateStr).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return dateStr;
  }
}

export function TaskDetail() {
  const { taskId } = useParams<{ taskId: string }>();

  const {
    data: task,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useTask(taskId);

  const queryClient = useQueryClient();

  const [executionError, setExecutionError] = useState<ApiError | null>(null);
  const [cancelError, setCancelError] = useState<ApiError | null>(null);

  const executeMutation = useExecuteTask(task?.task_id || '');
  const cancelMutation = useCancelTask(task?.task_id || '');
  const { data: plan } = useTaskPlan(task?.task_id, task?.plan_version);

  function handleManualRefresh() {
    refetch();
    if (task?.task_id) {
      queryClient.invalidateQueries({ queryKey: taskKeys.events(task.task_id) });
      queryClient.invalidateQueries({ queryKey: taskKeys.workspace(task.task_id) });
      queryClient.invalidateQueries({ queryKey: taskKeys.diff(task.task_id) });
      queryClient.invalidateQueries({ queryKey: taskKeys.tests(task.task_id) });
      queryClient.invalidateQueries({ queryKey: taskKeys.repairBudget(task.task_id) });
      queryClient.invalidateQueries({ queryKey: taskKeys.plan(task.task_id) });
    }
  }

  async function handleStartExecution() {
    if (!task || task.status !== TaskStatus.APPROVED) return;
    setExecutionError(null);
    setCancelError(null);
    try {
      await executeMutation.mutateAsync({});
    } catch (err) {
      setExecutionError(err as ApiError);
    }
  }

  async function handleCancelTask() {
    if (!task || !canCancelTask(task.status)) return;
    setExecutionError(null);
    setCancelError(null);
    try {
      await cancelMutation.mutateAsync();
    } catch (err) {
      setCancelError(err as ApiError);
    }
  }

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-28 space-y-4">
        <LoadingSpinner size="lg" label="Loading task details..." />
        <p className="text-sm text-muted-foreground">Loading task and lifecycle state...</p>
      </div>
    );
  }

  if (isError || !task) {
    return (
      <div className="flex flex-col h-full min-h-0 overflow-y-auto max-w-4xl mx-auto py-12 space-y-6">
        <Link
          to="/app/tasks"
          className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
          <span>Back to Tasks</span>
        </Link>

        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-6 space-y-4">
          <ErrorMessage
            error={error}
            message={`Task with ID '${taskId}' could not be loaded.`}
          />
          <div className="flex items-center gap-3">
            <button
              onClick={() => refetch()}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-destructive text-destructive-foreground hover:bg-destructive/90 transition-colors"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Retry
            </button>
            <Link
              to="/app/tasks"
              className="px-3 py-1.5 text-xs font-medium rounded-md border border-border bg-card text-foreground hover:bg-accent transition-colors"
            >
              Go to Task List
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full min-h-0 overflow-y-auto space-y-8 max-w-6xl mx-auto w-full pb-12">
      {/* ------------------------------------------------------------------ */}
      {/* 1. Header & Navigation                                              */}
      {/* ------------------------------------------------------------------ */}
      <div className="space-y-4">
        <div className="flex items-center justify-between gap-4 mb-2">
          <Link
            to="/app/tasks"
            className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            <span>Back to Tasks</span>
          </Link>

          <button
            type="button"
            onClick={handleManualRefresh}
            disabled={isFetching}
            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground p-1 rounded hover:bg-accent transition-colors"
            title="Refresh task"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', isFetching && 'animate-spin')} />
            <span className="hidden sm:inline">Refresh</span>
          </button>
        </div>

        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
          <div className="space-y-1.5">
            <div className="flex items-center gap-2.5 flex-wrap">
              <span className="font-mono text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded border border-border">
                {task.task_id}
              </span>
              <TaskStatusBadge status={task.status} size="md" />

              {task.source?.issue_url && (
                <a
                  href={task.source.issue_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-primary hover:underline bg-primary/10 border border-primary/20 px-2 py-0.5 rounded-full"
                >
                  <span>Issue #{task.source.issue_number}</span>
                  <ExternalLink className="h-3 w-3" />
                </a>
              )}
            </div>

            <h1 className="text-2xl font-bold tracking-tight text-foreground">{task.title}</h1>

            <p className="text-xs text-muted-foreground flex items-center gap-3 flex-wrap">
              <span className="inline-flex items-center gap-1 font-mono">
                <FolderGit2 className="h-3.5 w-3.5 text-primary" />
                {task.repository_id}
              </span>

              <span>•</span>

              <span className="inline-flex items-center gap-1">
                <Clock className="h-3.5 w-3.5 text-muted-foreground/70" />
                Created {formatDate(task.created_at)}
              </span>

              {task.repair_attempts_used > 0 && (
                <>
                  <span>•</span>
                  <span className="inline-flex items-center gap-1 text-amber-400 font-mono">
                    <Wrench className="h-3 w-3" />
                    Repair attempts: {task.repair_attempts_used}/{task.repair_attempts_max}
                  </span>
                </>
              )}
            </p>
          </div>

          {/* Execution & Lifecycle Controls Toolbar */}
          <div className="flex items-center gap-2.5 flex-wrap">
            {task.status === TaskStatus.APPROVED && (
              <button
                type="button"
                data-testid="start-execution-button"
                disabled={executeMutation.isPending}
                onClick={handleStartExecution}
                className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-md bg-emerald-600 text-white hover:bg-emerald-500 transition-colors shadow-xs disabled:opacity-50 cursor-pointer"
              >
                {executeMutation.isPending ? (
                  <>
                    <LoadingSpinner size="sm" label="Starting execution..." />
                    <span>Starting Execution...</span>
                  </>
                ) : (
                  <>
                    <Play className="h-3.5 w-3.5" />
                    <span>Start Execution</span>
                  </>
                )}
              </button>
            )}

            {canCancelTask(task.status) && (
              <button
                type="button"
                data-testid="cancel-task-button"
                disabled={cancelMutation.isPending}
                onClick={handleCancelTask}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold rounded-md border border-rose-500/40 bg-rose-500/10 text-rose-400 hover:bg-rose-500/20 transition-colors disabled:opacity-50 cursor-pointer"
              >
                {cancelMutation.isPending ? (
                  <>
                    <LoadingSpinner size="sm" label="Cancelling task..." />
                    <span>Cancelling...</span>
                  </>
                ) : (
                  <>
                    <Slash className="h-3.5 w-3.5" />
                    <span>Cancel Task</span>
                  </>
                )}
              </button>
            )}
          </div>
        </div>

        {/* Server Error Alert for Execution or Cancellation */}
        {(executionError || cancelError) && (
          <div
            data-testid="execution-error-alert"
            className="rounded-md border border-rose-500/30 bg-rose-500/10 p-3.5 text-xs text-rose-200 flex items-center justify-between"
          >
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-rose-400 shrink-0" />
              <span>
                {executionError?.message ||
                  cancelError?.message ||
                  'Action could not be executed due to server error.'}
              </span>
            </div>
            <button
              type="button"
              onClick={() => {
                setExecutionError(null);
                setCancelError(null);
              }}
              className="text-xs text-rose-400 hover:text-rose-200 font-medium underline ml-3"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Active Execution Indicator Banner */}
        {isExecutionActive(task.status) && (
          <div
            data-testid="active-execution-indicator"
            className="rounded-md border border-sky-500/30 bg-sky-500/10 p-3.5 text-xs text-sky-200 flex items-center justify-between"
          >
            <div className="flex items-center gap-2.5">
              <RefreshCw className="h-4 w-4 text-sky-400 animate-spin shrink-0" />
              <div>
                <span className="font-semibold text-sky-300">
                  {task.status === TaskStatus.WORKSPACE_SETUP && 'Workspace Setup in Progress'}
                  {task.status === TaskStatus.EXECUTING && 'Task Execution Active'}
                  {task.status === TaskStatus.TESTING && 'Test Execution in Progress'}
                  {task.status === TaskStatus.REPAIRING && 'Bounded Self-Repair Active'}
                </span>
                <p className="text-[11px] text-sky-300/80">
                  The task is active inside the isolated sandbox. Polling for real-time progress and telemetry.
                </p>
              </div>
            </div>
            <span className="font-mono text-[11px] bg-sky-500/20 px-2.5 py-0.5 rounded text-sky-200 uppercase font-bold border border-sky-500/30">
              {task.status.replace(/_/g, ' ')}
            </span>
          </div>
        )}
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* 2. Overview & Segregated Intake Details                             */}
      {/* ------------------------------------------------------------------ */}
      <div className="rounded-lg border border-border bg-card p-6 shadow-xs space-y-6">
        {/* Description */}
        <div>
          <h2 className="text-xs font-semibold uppercase text-muted-foreground tracking-wider mb-2">
            Task Description
          </h2>
          <p className="text-sm text-foreground/90 leading-relaxed whitespace-pre-wrap bg-background/50 p-4 rounded-md border border-border/80">
            {task.description || 'No description provided.'}
          </p>
        </div>

        {/* Segregated Requirements */}
        <div>
          <h2 className="text-xs font-semibold uppercase text-muted-foreground tracking-wider mb-3 flex items-center gap-1.5">
            <Layers className="h-4 w-4 text-primary" />
            Segregated Requirements ({task.requirements.length})
          </h2>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
            {task.requirements.map((req, idx) => (
              <div
                key={req.id || idx}
                className="p-4 rounded-md border border-border/80 bg-background/40 space-y-2.5"
              >
                <div className="flex items-center justify-between border-b border-border/50 pb-2">
                  <span className="font-mono text-xs font-bold text-primary">
                    {req.id || `req-${idx + 1}`}
                  </span>
                  <span className="text-[10px] font-mono uppercase bg-accent text-accent-foreground px-2 py-0.5 rounded border border-border">
                    {req.category}
                  </span>
                </div>

                <p className="text-xs text-foreground/90 leading-relaxed font-medium">
                  {req.description}
                </p>

                {req.target_files && req.target_files.length > 0 && (
                  <div className="pt-1">
                    <span className="text-[11px] text-muted-foreground flex items-center gap-1 mb-1">
                      <FileCode2 className="h-3 w-3" /> Target files:
                    </span>
                    <div className="flex flex-wrap gap-1">
                      {req.target_files.map((tf) => (
                        <span
                          key={tf}
                          className="font-mono text-[11px] bg-background px-1.5 py-0.5 rounded border border-border/80 text-foreground"
                        >
                          {tf}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {req.acceptance_criteria && req.acceptance_criteria.length > 0 && (
                  <div className="pt-1 text-[11px] text-muted-foreground">
                    <span className="font-medium">Acceptance criteria:</span>
                    <ul className="list-disc list-inside mt-0.5 space-y-0.5 text-foreground/80">
                      {req.acceptance_criteria.map((c, i) => (
                        <li key={i}>{c}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Assumptions & Constraints Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-2">
          {/* Assumptions */}
          <div>
            <h2 className="text-xs font-semibold uppercase text-muted-foreground tracking-wider mb-3 flex items-center gap-1.5">
              <HelpCircle className="h-4 w-4 text-purple-400" />
              Assumptions ({task.assumptions?.length || 0})
            </h2>

            {task.assumptions && task.assumptions.length > 0 ? (
              <div className="space-y-2.5">
                {task.assumptions.map((asm, idx) => (
                  <div
                    key={asm.id || idx}
                    className="p-3 rounded-md border border-border/80 bg-background/40 text-xs space-y-1.5"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-[11px] font-semibold text-purple-400">
                        {asm.id || `asm-${idx + 1}`}
                      </span>
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[10px] uppercase text-muted-foreground">
                          {asm.risk_level} risk
                        </span>
                        {asm.unresolved && (
                          <span className="font-mono text-[10px] bg-amber-500/10 text-amber-400 px-1.5 py-0.2 rounded border border-amber-500/20">
                            Unresolved
                          </span>
                        )}
                      </div>
                    </div>
                    <p className="text-foreground/90">{asm.description}</p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground italic">No assumptions specified.</p>
            )}
          </div>

          {/* Constraints */}
          <div>
            <h2 className="text-xs font-semibold uppercase text-muted-foreground tracking-wider mb-3 flex items-center gap-1.5">
              <ShieldAlert className="h-4 w-4 text-amber-400" />
              Constraints ({task.constraints?.length || 0})
            </h2>

            {task.constraints && task.constraints.length > 0 ? (
              <div className="space-y-2.5">
                {task.constraints.map((cst, idx) => (
                  <div
                    key={cst.id || idx}
                    className="p-3 rounded-md border border-border/80 bg-background/40 text-xs space-y-1.5"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-[11px] font-semibold text-amber-400">
                        {cst.id || `cst-${idx + 1}`}
                      </span>
                      <span className="font-mono text-[10px] uppercase bg-muted px-1.5 py-0.2 rounded">
                        {cst.constraint_type}
                      </span>
                    </div>

                    <p className="text-foreground/90">{cst.description}</p>

                    {cst.forbidden_files && cst.forbidden_files.length > 0 && (
                      <div className="text-[11px] text-muted-foreground font-mono">
                        Forbidden files: {cst.forbidden_files.join(', ')}
                      </div>
                    )}

                    {cst.max_budget_tokens && (
                      <div className="text-[11px] text-muted-foreground font-mono">
                        Max tokens: {cst.max_budget_tokens.toLocaleString()}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground italic">No constraints specified.</p>
            )}
          </div>
        </div>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* ------------------------------------------------------------------ */}
      {/* 3. Structured Plan Review & Approval Panel                         */}
      {/* ------------------------------------------------------------------ */}
      <PlanReviewPanel task={task} />

      {/* ------------------------------------------------------------------ */}
      {/* 4. Approval History & Audit Trail                                  */}
      {/* ------------------------------------------------------------------ */}
      <ApprovalHistoryPanel taskId={task.task_id} task={task} />

      {/* ------------------------------------------------------------------ */}
      {/* 5. Isolated Workspace Sandbox Panel                                */}
      {/* ------------------------------------------------------------------ */}
      <WorkspacePanel taskId={task.task_id} />

      {/* ------------------------------------------------------------------ */}
      {/* 6. Code Changes & Diff Telemetry Panel                             */}
      {/* ------------------------------------------------------------------ */}
      <CodeChangesPanel
        taskId={task.task_id}
        repositoryId={task.repository_id}
        plannedTargetFiles={task.requirements.flatMap((r) => r.target_files || [])}
        plannedExpectedFiles={plan?.expected_files_to_modify || []}
      />

      {/* ------------------------------------------------------------------ */}
      {/* 7. Bounded Self-Repair Budget Tracker                              */}
      {/* ------------------------------------------------------------------ */}
      <RepairBudgetTracker
        taskId={task.task_id}
        repairAttemptsUsed={task.repair_attempts_used}
        repairAttemptsMax={task.repair_attempts_max}
      />

      {/* ------------------------------------------------------------------ */}
      {/* 8. Test Execution Telemetry Panel                                  */}
      {/* ------------------------------------------------------------------ */}
      <TestExecutionPanel taskId={task.task_id} />

      {/* ------------------------------------------------------------------ */}
      {/* 9. Chronological Event Timeline                                    */}
      {/* ------------------------------------------------------------------ */}
      <ExecutionTimeline taskId={task.task_id} />
    </div>
  );
}
