import { useState } from 'react';
import {
  TestTube2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  HelpCircle,
  Slash,
  ChevronDown,
  ChevronRight,
  Terminal,
  RefreshCw,
  Wrench,
  AlertCircle,
} from 'lucide-react';
import { useTaskTests } from '../../hooks/useTasks';
import type { TaskTestResultsResponse, TestRunItem } from '../../types/task';
import type { ApiError } from '../../types/api';
import { LoadingSpinner } from '../shared/LoadingSpinner';
import { ErrorMessage } from '../shared/ErrorMessage';
import { cn } from '../../lib/utils';

export interface TestExecutionPanelProps {
  taskId?: string;
  testResults?: TaskTestResultsResponse | null;
  isLoading?: boolean;
  error?: ApiError | null;
  className?: string;
}

export type NormalizedTestOutcome =
  | 'PASSED'
  | 'TEST_FAILURE'
  | 'INFRASTRUCTURE_ERROR'
  | 'TIMEOUT'
  | 'UNSUPPORTED_FRAMEWORK'
  | 'SKIPPED'
  | 'NOT_RUN'
  | 'UNAVAILABLE';

function classifyTestOutcome(run: TestRunItem): {
  outcome: NormalizedTestOutcome;
  label: string;
  className: string;
  isRepairEligible: boolean;
} {
  const statusUpper = (run.status || '').toUpperCase();
  const classUpper = (run.classification || '').toUpperCase();

  // Strict check: Only status === 'PASSED' is classified as PASSED
  if (statusUpper === 'PASSED') {
    return {
      outcome: 'PASSED',
      label: 'Passed',
      className: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
      isRepairEligible: false,
    };
  }

  if (statusUpper === 'TIMEOUT' || run.timed_out || classUpper === 'TIMEOUT') {
    return {
      outcome: 'TIMEOUT',
      label: 'Timeout',
      className: 'bg-orange-500/10 text-orange-400 border-orange-500/30',
      isRepairEligible: false,
    };
  }

  if (classUpper === 'INFRASTRUCTURE_ERROR' || classUpper === 'SECURITY_VIOLATION') {
    return {
      outcome: 'INFRASTRUCTURE_ERROR',
      label: 'Infrastructure Failure',
      className: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
      isRepairEligible: false,
    };
  }

  if (statusUpper === 'UNSUPPORTED_FRAMEWORK') {
    return {
      outcome: 'UNSUPPORTED_FRAMEWORK',
      label: 'Unsupported Framework',
      className: 'bg-slate-500/10 text-slate-400 border-slate-500/30',
      isRepairEligible: false,
    };
  }

  if (statusUpper === 'SKIPPED') {
    return {
      outcome: 'SKIPPED',
      label: 'Skipped',
      className: 'bg-zinc-500/10 text-zinc-400 border-zinc-500/30',
      isRepairEligible: false,
    };
  }

  if (statusUpper === 'NOT_RUN') {
    return {
      outcome: 'NOT_RUN',
      label: 'Not Run',
      className: 'bg-zinc-500/10 text-zinc-400 border-zinc-500/30',
      isRepairEligible: false,
    };
  }

  if (statusUpper === 'UNAVAILABLE') {
    return {
      outcome: 'UNAVAILABLE',
      label: 'Unavailable',
      className: 'bg-zinc-500/10 text-zinc-400 border-zinc-500/30',
      isRepairEligible: false,
    };
  }

  if (statusUpper === 'FAILED' || statusUpper === 'ERROR') {
    // Check if repair eligible
    const repairEligible =
      run.is_repair_eligible ??
      (classUpper === 'TEST_FAILURE' || classUpper === 'NONE' || classUpper === '');

    return {
      outcome: 'TEST_FAILURE',
      label: 'Assertion Failure',
      className: 'bg-rose-500/10 text-rose-400 border-rose-500/30',
      isRepairEligible: repairEligible,
    };
  }

  return {
    outcome: 'UNAVAILABLE',
    label: 'Unavailable',
    className: 'bg-zinc-500/10 text-zinc-400 border-zinc-500/30',
    isRepairEligible: false,
  };
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

export function TestExecutionPanel({
  taskId,
  testResults: initialResults,
  isLoading: initialLoading,
  error: initialError,
  className,
}: TestExecutionPanelProps) {
  const {
    data: fetchedResults,
    isLoading: queryLoading,
    isError: queryIsError,
    error: queryError,
    refetch,
    isFetching,
  } = useTaskTests(taskId, {
    enabled: initialResults === undefined,
  });

  const testResults = initialResults !== undefined ? initialResults : fetchedResults;
  const isLoading = initialLoading !== undefined ? initialLoading : queryLoading;
  const error = initialError !== undefined ? initialError : (queryIsError ? queryError : null);

  const [expandedRuns, setExpandedRuns] = useState<Record<number, boolean>>({ 0: true });

  function toggleRun(index: number) {
    setExpandedRuns((prev) => ({
      ...prev,
      [index]: !prev[index],
    }));
  }

  const runs = testResults?.runs || [];

  return (
    <div
      data-testid="test-execution-panel"
      className={cn(
        'rounded-lg border border-border bg-card p-5 shadow-xs space-y-4',
        className
      )}
    >
      <div className="flex items-center justify-between border-b border-border pb-3">
        <div className="flex items-center gap-2">
          <TestTube2 className="h-4 w-4 text-primary" />
          <h3 className="text-base font-semibold text-foreground">Test Execution Telemetry</h3>
        </div>

        <button
          type="button"
          onClick={() => refetch()}
          disabled={isFetching || isLoading}
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground p-1 rounded hover:bg-accent transition-colors disabled:opacity-50"
          title="Refresh test results"
        >
          <RefreshCw className={cn('h-3.5 w-3.5', (isFetching || isLoading) && 'animate-spin')} />
        </button>
      </div>

      {isLoading ? (
        <div className="py-8 text-center space-y-2">
          <LoadingSpinner size="sm" label="Loading test telemetry..." />
          <p className="text-xs text-muted-foreground">Retrieving test execution results...</p>
        </div>
      ) : error ? (
        <div className="space-y-3 py-2">
          <ErrorMessage error={error} message="Failed to load test telemetry." />
        </div>
      ) : runs.length === 0 ? (
        <div className="p-6 text-center border border-dashed border-border rounded-md bg-background/50 space-y-2">
          <TestTube2 className="h-7 w-7 mx-auto text-muted-foreground/60" />
          <p className="text-xs font-medium text-foreground">No Tests Executed Yet</p>
          <p className="text-xs text-muted-foreground max-w-md mx-auto">
            Test telemetry will appear after the workspace execution phase runs repository test commands.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {runs.map((run, idx) => {
            const { outcome, label, className: badgeClass, isRepairEligible } = classifyTestOutcome(run);
            const isExpanded = expandedRuns[idx] ?? (idx === runs.length - 1);
            const passedCount = run.tests_passed ?? run.passed_count;
            const failedCount = run.tests_failed ?? run.failed_count;
            const totalCount = run.tests_total ?? run.total_count;
            const skippedCount = run.skipped_count ?? run.tests_skipped ?? 0;
            const errorCount = run.error_count ?? 0;

            return (
              <div
                key={run.attempt ?? idx}
                data-testid={`test-run-attempt-${run.attempt ?? idx + 1}`}
                className="rounded-md border border-border/80 bg-background/50 overflow-hidden"
              >
                {/* Run Header */}
                <button
                  type="button"
                  onClick={() => toggleRun(idx)}
                  className="w-full flex flex-col sm:flex-row sm:items-center sm:justify-between p-3.5 hover:bg-accent/40 transition-colors text-left gap-2"
                >
                  <div className="flex items-center gap-2.5 flex-wrap min-w-0">
                    {isExpanded ? (
                      <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />
                    ) : (
                      <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
                    )}

                    <span className="font-mono text-xs font-bold text-foreground">
                      Run #{run.attempt ?? idx + 1}
                    </span>

                    {/* Outcome Badge */}
                    <span
                      data-testid={`test-outcome-badge-${run.attempt ?? idx + 1}`}
                      className={cn(
                        'font-mono text-[11px] font-semibold px-2 py-0.5 rounded border uppercase flex items-center gap-1',
                        badgeClass
                      )}
                    >
                      {outcome === 'PASSED' && <CheckCircle2 className="h-3 w-3" />}
                      {outcome === 'TEST_FAILURE' && <XCircle className="h-3 w-3" />}
                      {outcome === 'INFRASTRUCTURE_ERROR' && <AlertTriangle className="h-3 w-3" />}
                      {outcome === 'TIMEOUT' && <Clock className="h-3 w-3" />}
                      {outcome === 'UNSUPPORTED_FRAMEWORK' && <HelpCircle className="h-3 w-3" />}
                      {outcome === 'SKIPPED' && <Slash className="h-3 w-3" />}
                      {outcome === 'NOT_RUN' && <Slash className="h-3 w-3" />}
                      {outcome === 'UNAVAILABLE' && <AlertCircle className="h-3 w-3" />}
                      <span>{label}</span>
                    </span>

                    {/* Framework */}
                    {run.framework && (
                      <span className="font-mono text-[10px] bg-muted px-1.5 py-0.5 rounded text-muted-foreground">
                        {run.framework}
                      </span>
                    )}

                    {/* Repair Eligibility Indicator */}
                    {outcome === 'TEST_FAILURE' && (
                      <span
                        className={cn(
                          'text-[10px] font-mono px-1.5 py-0.5 rounded border flex items-center gap-1',
                          isRepairEligible
                            ? 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                            : 'bg-zinc-500/10 text-zinc-400 border-zinc-500/20'
                        )}
                      >
                        <Wrench className="h-2.5 w-2.5" />
                        {isRepairEligible ? 'Repair Eligible' : 'Ineligible for Repair'}
                      </span>
                    )}
                  </div>

                  {/* Summary Counts */}
                  <div className="flex items-center gap-3 font-mono text-xs text-muted-foreground shrink-0 pl-6 sm:pl-0">
                    {passedCount !== undefined && (
                      <span className="text-emerald-400 font-semibold">{passedCount} passed</span>
                    )}
                    {failedCount !== undefined && (
                      <span className={cn('font-semibold', failedCount > 0 ? 'text-rose-400' : 'text-muted-foreground')}>
                        {failedCount} failed
                      </span>
                    )}
                    {skippedCount > 0 && <span>{skippedCount} skipped</span>}
                    {errorCount > 0 && <span className="text-amber-400">{errorCount} error</span>}
                    {totalCount !== undefined && <span>({totalCount} total)</span>}
                  </div>
                </button>

                {/* Expanded Details */}
                {isExpanded && (
                  <div className="border-t border-border/60 p-4 space-y-3.5 bg-muted/10 text-xs">
                    {/* Execution Details Bar */}
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 font-mono text-[11px] bg-background/60 p-2.5 rounded border border-border/60">
                      <div>
                        <span className="text-muted-foreground block text-[10px]">Command:</span>
                        <span className="text-foreground font-semibold break-all">{run.command}</span>
                      </div>
                      <div>
                        <span className="text-muted-foreground block text-[10px]">Exit Code:</span>
                        <span
                          className={cn(
                            'font-semibold',
                            run.exit_code === 0 ? 'text-emerald-400' : 'text-rose-400'
                          )}
                        >
                          {run.exit_code}
                        </span>
                      </div>
                      <div>
                        <span className="text-muted-foreground block text-[10px]">Duration:</span>
                        <span className="text-foreground">
                          {run.duration_ms < 1000
                            ? `${run.duration_ms} ms`
                            : `${(run.duration_ms / 1000).toFixed(2)} s`}
                        </span>
                      </div>
                      <div>
                        <span className="text-muted-foreground block text-[10px]">Executed At:</span>
                        <span className="text-foreground">{formatDate(run.executed_at)}</span>
                      </div>
                    </div>

                    {/* Failed Test Names */}
                    {run.failed_test_names && run.failed_test_names.length > 0 && (
                      <div className="space-y-1">
                        <span className="text-[11px] font-semibold text-rose-400 uppercase tracking-wider flex items-center gap-1">
                          <XCircle className="h-3 w-3" /> Failed Tests ({run.failed_test_names.length})
                        </span>
                        <ul className="list-disc list-inside space-y-0.5 bg-rose-950/20 border border-rose-500/30 p-2.5 rounded font-mono text-xs text-rose-300">
                          {run.failed_test_names.map((name, i) => (
                            <li key={i} className="truncate">{name}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Output Summary */}
                    {run.output_summary && (
                      <div className="space-y-1">
                        <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
                          Outcome Summary
                        </span>
                        <p className="p-2.5 rounded bg-background/70 border border-border/70 font-mono text-xs text-foreground/90 whitespace-pre-wrap">
                          {run.output_summary}
                        </p>
                      </div>
                    )}

                    {/* Stdout / Stderr logs (bounded & safe as text) */}
                    {(run.stdout || run.stderr) && (
                      <div className="space-y-2">
                        <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
                          <Terminal className="h-3 w-3" />
                          Execution Logs (Bounded)
                        </span>

                        {run.stdout && (
                          <div className="space-y-1">
                            <span className="text-[10px] text-muted-foreground font-mono">stdout:</span>
                            <pre
                              data-testid="test-stdout"
                              className="max-h-56 overflow-y-auto whitespace-pre-wrap font-mono text-[11px] bg-background/90 p-3 rounded border border-border text-foreground/90 leading-relaxed select-text"
                            >
                              {run.stdout.length > 50000
                                ? `${run.stdout.slice(0, 50000)}\n... [output truncated at 50,000 characters]`
                                : run.stdout}
                            </pre>
                          </div>
                        )}

                        {run.stderr && (
                          <div className="space-y-1">
                            <span className="text-[10px] text-rose-400 font-mono">stderr:</span>
                            <pre
                              data-testid="test-stderr"
                              className="max-h-56 overflow-y-auto whitespace-pre-wrap font-mono text-[11px] bg-rose-950/20 p-3 rounded border border-rose-500/30 text-rose-300 leading-relaxed select-text"
                            >
                              {run.stderr.length > 50000
                                ? `${run.stderr.slice(0, 50000)}\n... [output truncated at 50,000 characters]`
                                : run.stderr}
                            </pre>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
