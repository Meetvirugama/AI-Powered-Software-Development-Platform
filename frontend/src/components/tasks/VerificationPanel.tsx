import { useState } from 'react';
import {
  ShieldCheck,
  ShieldAlert,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Clock,
  RefreshCw,
  FileCode,
  HelpCircle,
  MinusCircle,
  Ban,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';
import { useTaskVerification, useTriggerVerification, useCheckStaleRevision } from '../../hooks/useTasks';
import {
  TaskStatus,
  isPublicationEligible,
  type VerificationResult,
  type VerificationCheckStatus,
  type VerificationOverallStatus,
  type FindingSeverity,
} from '../../types/task';
import type { ApiError } from '../../types/api';
import { LoadingSpinner } from '../shared/LoadingSpinner';
import { ErrorMessage } from '../shared/ErrorMessage';
import { cn } from '../../lib/utils';

export interface VerificationPanelProps {
  taskId: string;
  currentRevision?: string | null;
  className?: string;
  onVerificationCompleted?: (result: VerificationResult) => void;
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

function getOverallStatusBadge(status: VerificationOverallStatus) {
  switch (status) {
    case 'PASS':
      return {
        label: 'VERIFICATION PASSED',
        bg: 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400',
        icon: <CheckCircle2 className="h-4 w-4 text-emerald-400" />,
      };
    case 'FAIL':
      return {
        label: 'VERIFICATION FAILED',
        bg: 'bg-rose-500/15 border-rose-500/30 text-rose-400',
        icon: <XCircle className="h-4 w-4 text-rose-400" />,
      };
    case 'REQUIRES_HUMAN_REVIEW':
      return {
        label: 'REQUIRES HUMAN REVIEW',
        bg: 'bg-amber-500/15 border-amber-500/30 text-amber-400',
        icon: <AlertTriangle className="h-4 w-4 text-amber-400" />,
      };
    case 'INCONCLUSIVE':
    default:
      return {
        label: 'INCONCLUSIVE',
        bg: 'bg-yellow-500/15 border-yellow-500/30 text-yellow-400',
        icon: <HelpCircle className="h-4 w-4 text-yellow-400" />,
      };
  }
}

function getCheckStatusBadge(status: VerificationCheckStatus | string) {
  switch (status) {
    case 'PASSED':
      return {
        label: 'Passed',
        bg: 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400',
        icon: <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />,
      };
    case 'FAILED':
      return {
        label: 'Failed',
        bg: 'bg-rose-500/10 border-rose-500/20 text-rose-400',
        icon: <XCircle className="h-3.5 w-3.5 text-rose-400" />,
      };
    case 'RUNNING':
      return {
        label: 'Running',
        bg: 'bg-sky-500/10 border-sky-500/20 text-sky-400',
        icon: <RefreshCw className="h-3.5 w-3.5 text-sky-400 animate-spin" />,
      };
    case 'SKIPPED':
      return {
        label: 'Skipped',
        bg: 'bg-slate-500/10 border-slate-500/20 text-slate-400',
        icon: <MinusCircle className="h-3.5 w-3.5 text-slate-400" />,
      };
    case 'UNSUPPORTED':
      return {
        label: 'Unsupported',
        bg: 'bg-amber-500/10 border-amber-500/20 text-amber-400',
        icon: <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />,
      };
    case 'UNAVAILABLE':
      return {
        label: 'Unavailable',
        bg: 'bg-zinc-500/10 border-zinc-500/20 border-dashed text-zinc-400',
        icon: <Ban className="h-3.5 w-3.5 text-zinc-400" />,
      };
    case 'COMPLETED':
      return {
        label: 'Completed',
        bg: 'bg-blue-500/10 border-blue-500/20 text-blue-400',
        icon: <CheckCircle2 className="h-3.5 w-3.5 text-blue-400" />,
      };
    default:
      return {
        label: String(status),
        bg: 'bg-muted border-border text-muted-foreground',
        icon: <HelpCircle className="h-3.5 w-3.5 text-muted-foreground" />,
      };
  }
}

function getSeverityBadge(severity: FindingSeverity | string) {
  switch (severity) {
    case 'CRITICAL':
      return 'bg-red-500/20 text-red-300 border-red-500/30';
    case 'HIGH':
      return 'bg-rose-500/20 text-rose-300 border-rose-500/30';
    case 'MEDIUM':
      return 'bg-amber-500/20 text-amber-300 border-amber-500/30';
    case 'LOW':
      return 'bg-blue-500/20 text-blue-300 border-blue-500/30';
    case 'INFO':
    default:
      return 'bg-slate-500/20 text-slate-300 border-slate-500/30';
  }
}

function formatCheckName(name: string): string {
  switch (name) {
    case 'tests':
    case 'test_suite':
      return 'Test Suite Execution';
    case 'static_analysis':
      return 'Static Analysis & Linting';
    case 'ai_code_review':
      return 'AI Code Review (Week 2)';
    case 'secret_scan':
    case 'security_checks':
      return 'Addition-Level Secret Scan';
    default:
      return name
        .replace(/_/g, ' ')
        .replace(/\b\w/g, (c) => c.toUpperCase());
  }
}

export function VerificationPanel({
  taskId,
  currentRevision,
  className,
  onVerificationCompleted,
}: VerificationPanelProps) {
  const { data: verification, isLoading, isError, error, refetch } = useTaskVerification(taskId);
  const {
    data: staleCheck,
    isLoading: isStaleCheckLoading,
    isError: isStaleCheckError,
  } = useCheckStaleRevision(taskId);
  const triggerMutation = useTriggerVerification(taskId);
  const [expandedDetails, setExpandedDetails] = useState<Record<string, boolean>>({});
  const [triggerError, setTriggerError] = useState<ApiError | null>(null);

  const isStale = Boolean(
    staleCheck?.is_stale ||
    (verification?.verified_revision &&
      currentRevision &&
      verification.verified_revision !== currentRevision)
  );

  const isEligible = isPublicationEligible({
    status: TaskStatus.READY_FOR_PUBLICATION,
    verification,
    isStale,
    isLoadingVerification: isLoading,
    hasVerificationError: isError,
    isStaleCheckLoading,
    hasStaleCheckError: isStaleCheckError,
  });

  function toggleExpand(checkName: string) {
    setExpandedDetails((prev) => ({ ...prev, [checkName]: !prev[checkName] }));
  }

  async function handleReverify() {
    setTriggerError(null);
    try {
      const res = await triggerMutation.mutateAsync({ force_reverify: true });
      if (onVerificationCompleted) {
        onVerificationCompleted(res);
      }
    } catch (err) {
      setTriggerError(err as ApiError);
    }
  }

  return (
    <div
      data-testid="verification-panel"
      className={cn(
        'rounded-lg border border-border bg-card p-6 shadow-xs space-y-6',
        className
      )}
    >
      {/* ------------------------------------------------------------------ */}
      {/* 1. Header with Status & Action                                     */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-border pb-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2.5 flex-wrap">
            <h3 className="text-base font-semibold text-foreground flex items-center gap-2">
              <ShieldCheck className="h-5 w-5 text-primary" />
              Independent Verification & Quality Review
            </h3>

            {verification && (
              <span
                data-testid="verification-status-badge"
                className={cn(
                  'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-mono font-semibold border',
                  getOverallStatusBadge(verification.status).bg
                )}
              >
                {getOverallStatusBadge(verification.status).icon}
                {getOverallStatusBadge(verification.status).label}
              </span>
            )}
          </div>

          <p className="text-xs text-muted-foreground flex items-center gap-2 flex-wrap">
            <span>Evaluates code changes independently of generation before publication authorization.</span>
            {verification?.verified_revision && (
              <>
                <span>•</span>
                <span className="font-mono">
                  Verified SHA: <code className="text-foreground">{verification.verified_revision.slice(0, 10)}</code>
                </span>
              </>
            )}
            {verification?.created_at && (
              <>
                <span>•</span>
                <span className="inline-flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  {formatDate(verification.created_at)}
                </span>
              </>
            )}
          </p>
        </div>

        <button
          type="button"
          data-testid="reverify-button"
          disabled={triggerMutation.isPending}
          onClick={handleReverify}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-border bg-card text-foreground hover:bg-accent transition-colors disabled:opacity-50 cursor-pointer self-start sm:self-auto shrink-0"
        >
          {triggerMutation.isPending ? (
            <>
              <LoadingSpinner size="sm" label="Re-verifying..." />
              <span>Verifying...</span>
            </>
          ) : (
            <>
              <RefreshCw className="h-3.5 w-3.5" />
              <span>{verification ? 'Re-run Verification' : 'Run Verification'}</span>
            </>
          )}
        </button>
      </div>

      {/* Trigger Error Alert */}
      {triggerError && (
        <div className="rounded-md border border-rose-500/30 bg-rose-500/10 p-3.5 text-xs text-rose-200 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-rose-400 shrink-0" />
            <span>{triggerError.message || 'Verification could not be initiated.'}</span>
          </div>
          <button
            type="button"
            onClick={() => setTriggerError(null)}
            className="text-xs text-rose-400 hover:text-rose-200 underline ml-2 cursor-pointer"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Stale Revision Warning Banner */}
      {isStale && (
        <div
          data-testid="stale-verification-warning"
          className="rounded-md border border-amber-500/40 bg-amber-500/10 p-4 text-xs text-amber-200 space-y-1.5"
        >
          <div className="flex items-center gap-2 font-semibold text-amber-300">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span>Stale Verification Detected — Revision Mismatch</span>
          </div>
          <p className="pl-6 text-amber-200/90 leading-relaxed">
            The workspace was modified or rebased after verification occurred. The verified commit (
            <code className="font-mono text-amber-100">{verification?.verified_revision?.slice(0, 10)}</code>) differs from the current revision (
            <code className="font-mono text-amber-100">{currentRevision?.slice(0, 10)}</code>). Re-run verification to revalidate changes before publication.
          </p>
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* 2. Loading / Error / Empty States                                  */}
      {/* ------------------------------------------------------------------ */}
      {isLoading ? (
        <div className="py-10 text-center space-y-3">
          <LoadingSpinner size="md" label="Loading independent verification..." />
          <p className="text-xs text-muted-foreground">Inspecting test outcomes, static checks, and security findings...</p>
        </div>
      ) : isError ? (
        <div className="space-y-3 py-2">
          <ErrorMessage error={error} message="Failed to load verification outcome." />
          <div className="flex justify-end">
            <button
              type="button"
              onClick={() => refetch()}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-border bg-card text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              <span>Retry</span>
            </button>
          </div>
        </div>
      ) : !verification ? (
        <div className="py-8 text-center border border-dashed border-border rounded-md bg-background/50 space-y-2">
          <ShieldAlert className="h-8 w-8 mx-auto text-muted-foreground/50" />
          <p className="text-xs font-medium text-foreground">Verification Not Yet Run</p>
          <p className="text-xs text-muted-foreground max-w-md mx-auto">
            Independent verification evaluates test execution, static analysis, AI code review, and secret scans before publication.
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {/* PR Summary Statement */}
          {verification.pr_summary && (
            <div className="p-3.5 rounded-md border border-border/80 bg-background/40 space-y-1">
              <span className="text-[11px] font-semibold uppercase text-muted-foreground tracking-wider">
                Verification Summary Statement
              </span>
              <p className="text-xs text-foreground/90 leading-relaxed">
                {verification.pr_summary}
              </p>
            </div>
          )}

          {/* ---------------------------------------------------------------- */}
          {/* 3. Individual Check Items Grid                                   */}
          {/* ---------------------------------------------------------------- */}
          <div>
            <h4 className="text-xs font-semibold uppercase text-muted-foreground tracking-wider mb-3">
              Verification Gates ({verification.checks.length})
            </h4>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
              {verification.checks.map((check) => {
                const badge = getCheckStatusBadge(check.status);
                const hasDetails = Object.keys(check.details || {}).length > 0;
                const isExpanded = Boolean(expandedDetails[check.name]);

                return (
                  <div
                    key={check.name}
                    data-testid={`verification-check-${check.name}`}
                    className="p-4 rounded-md border border-border/80 bg-background/40 space-y-2.5"
                  >
                    <div className="flex items-center justify-between gap-2 border-b border-border/50 pb-2">
                      <span className="font-medium text-xs text-foreground">
                        {formatCheckName(check.name)}
                      </span>
                      <span
                        className={cn(
                          'inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-mono font-medium border',
                          badge.bg
                        )}
                      >
                        {badge.icon}
                        <span>{badge.label}</span>
                      </span>
                    </div>

                    <p className="text-xs text-foreground/80 leading-relaxed">
                      {check.message || 'No additional details provided.'}
                    </p>

                    <div className="flex items-center justify-between text-[11px] text-muted-foreground pt-1">
                      <span className="font-mono">
                        {check.duration_ms > 0 ? `${check.duration_ms}ms` : 'Immediate'}
                      </span>

                      <div className="flex items-center gap-2">
                        {check.findings_count > 0 && (
                          <span className="font-mono bg-accent text-accent-foreground px-1.5 py-0.5 rounded border border-border text-[10px]">
                            {check.findings_count} finding{check.findings_count === 1 ? '' : 's'}
                          </span>
                        )}

                        {hasDetails && (
                          <button
                            type="button"
                            onClick={() => toggleExpand(check.name)}
                            className="inline-flex items-center gap-0.5 text-xs text-primary hover:underline"
                          >
                            <span>Details</span>
                            {isExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                          </button>
                        )}
                      </div>
                    </div>

                    {isExpanded && hasDetails && (
                      <pre className="mt-2 p-2.5 rounded bg-background border border-border text-[11px] font-mono text-foreground/80 overflow-x-auto max-h-40">
                        {JSON.stringify(check.details, null, 2)}
                      </pre>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* ---------------------------------------------------------------- */}
          {/* 4. Blocking Findings (Strict Gates)                              */}
          {/* ---------------------------------------------------------------- */}
          {verification.blocking_findings && verification.blocking_findings.length > 0 && (
            <div data-testid="blocking-findings-section" className="space-y-3">
              <div className="flex items-center gap-2 text-xs font-semibold text-rose-400">
                <ShieldAlert className="h-4 w-4" />
                <span>Blocking Findings ({verification.blocking_findings.length}) — Publication Forbidden</span>
              </div>

              <div className="space-y-2.5">
                {verification.blocking_findings.map((finding) => (
                  <div
                    key={finding.id}
                    className="p-3.5 rounded-md border border-rose-500/30 bg-rose-500/10 text-xs space-y-2"
                  >
                    <div className="flex items-center justify-between flex-wrap gap-2">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className={cn('px-2 py-0.5 rounded text-[10px] font-mono font-bold border uppercase', getSeverityBadge(finding.severity))}>
                          {finding.severity}
                        </span>
                        <span className="font-mono text-muted-foreground text-[11px]">
                          Category: {finding.category}
                        </span>
                        {finding.rule_id && (
                          <span className="font-mono bg-background/60 text-foreground px-1.5 py-0.2 rounded border border-border text-[10px]">
                            Rule: {finding.rule_id}
                          </span>
                        )}
                      </div>
                      <span className="font-mono text-[10px] text-muted-foreground">{finding.id}</span>
                    </div>

                    <p className="text-rose-200 leading-relaxed font-medium">
                      {finding.message}
                    </p>

                    {finding.file_path && (
                      <div className="inline-flex items-center gap-1.5 font-mono text-[11px] text-rose-300/90 bg-rose-950/40 px-2 py-0.5 rounded border border-rose-500/20">
                        <FileCode className="h-3 w-3" />
                        <span>{finding.file_path}</span>
                        {finding.line_number && <span>:L{finding.line_number}</span>}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ---------------------------------------------------------------- */}
          {/* 5. Non-Blocking Warnings & Observations                          */}
          {/* ---------------------------------------------------------------- */}
          {verification.warnings && verification.warnings.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-xs font-semibold text-amber-400">
                <AlertTriangle className="h-4 w-4" />
                <span>Warnings & Observations ({verification.warnings.length})</span>
              </div>

              <div className="space-y-2.5">
                {verification.warnings.map((warning) => (
                  <div
                    key={warning.id}
                    className="p-3 rounded-md border border-amber-500/30 bg-amber-500/10 text-xs space-y-1.5"
                  >
                    <div className="flex items-center justify-between flex-wrap gap-2">
                      <div className="flex items-center gap-2">
                        <span className={cn('px-1.5 py-0.2 rounded text-[10px] font-mono font-bold border uppercase', getSeverityBadge(warning.severity))}>
                          {warning.severity}
                        </span>
                        <span className="font-mono text-muted-foreground text-[11px]">
                          {warning.category}
                        </span>
                        {warning.rule_id && (
                          <span className="font-mono bg-background/60 text-foreground px-1.5 py-0.2 rounded border border-border text-[10px]">
                            {warning.rule_id}
                          </span>
                        )}
                      </div>
                      <span className="font-mono text-[10px] text-muted-foreground">{warning.id}</span>
                    </div>

                    <p className="text-amber-200 leading-relaxed">
                      {warning.message}
                    </p>

                    {warning.file_path && (
                      <div className="inline-flex items-center gap-1 font-mono text-[11px] text-amber-300/80">
                        <FileCode className="h-3 w-3" />
                        <span>{warning.file_path}</span>
                        {warning.line_number && <span>:L{warning.line_number}</span>}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ---------------------------------------------------------------- */}
          {/* 6. Publication Eligibility Verdict                               */}
          {/* ---------------------------------------------------------------- */}
          {isStaleCheckLoading ? (
            <div
              data-testid="publication-eligibility-verdict"
              className="rounded-md p-4 text-xs space-y-1 border border-border bg-muted/40 text-muted-foreground"
            >
              <div className="flex items-center gap-2 font-semibold text-foreground">
                <LoadingSpinner size="sm" label="Checking revision state..." />
                <span>Publication Eligibility Pending — Checking Revision Freshness</span>
              </div>
              <p className="pl-6 text-[11px] leading-relaxed">
                Verifying whether workspace revision matches the verified revision...
              </p>
            </div>
          ) : isStaleCheckError ? (
            <div
              data-testid="publication-eligibility-verdict"
              className="rounded-md p-4 text-xs space-y-1 border border-rose-500/40 bg-rose-500/10 text-rose-200"
            >
              <div className="flex items-center gap-2 font-semibold">
                <XCircle className="h-4 w-4 text-rose-400" />
                <span className="text-rose-300">Publication Blocked — Revision Freshness Check Failed</span>
              </div>
              <p className="pl-6 text-[11px] opacity-90 leading-relaxed">
                Remote revision stale-check API failed. Server state cannot be verified.
              </p>
            </div>
          ) : (
            <div
              data-testid="publication-eligibility-verdict"
              className={cn(
                'rounded-md p-4 text-xs space-y-1 border',
                isEligible
                  ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
                  : 'border-rose-500/40 bg-rose-500/10 text-rose-200'
              )}
            >
              <div className="flex items-center gap-2 font-semibold">
                {isEligible ? (
                  <>
                    <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                    <span className="text-emerald-300">Publication Eligible — Independent Verification Passed</span>
                  </>
                ) : (
                  <>
                    <XCircle className="h-4 w-4 text-rose-400" />
                    <span className="text-rose-300">Publication Blocked — Verification Incomplete or Failed</span>
                  </>
                )}
              </div>
              <p className="pl-6 text-[11px] opacity-90 leading-relaxed">
                {isEligible
                  ? 'All mandatory test and security checks have passed without blocking findings. Proceed to the Publication panel to provide explicit human publication authorization.'
                  : 'Automated publication to GitHub is strictly forbidden until all blocking findings are resolved, tests pass, and independent verification is revalidated.'}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
