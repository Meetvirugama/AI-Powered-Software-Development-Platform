import { useState } from 'react';
import {
  CheckCircle2,
  XCircle,
  Shield,
  Clock,
  RefreshCw,
  Wrench,
  FileCode2,
  ExternalLink,
  AlertTriangle,
} from 'lucide-react';
import {
  useTaskEvents,
  useTaskApprovals,
  useApproveTool,
  useRejectTool,
} from '../../hooks/useTasks';
import type { TaskDetailResponse, TaskApproval } from '../../types/task';
import { LoadingSpinner } from '../shared/LoadingSpinner';
import { ErrorMessage } from '../shared/ErrorMessage';
import { getDecisionPlanVersion } from '../../lib/taskUtils';
import { cn } from '../../lib/utils';

export interface ApprovalHistoryPanelProps {
  taskId: string;
  task: TaskDetailResponse;
  className?: string;
}

function formatDate(dateStr?: string | null): string {
  if (!dateStr) return '';
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

export function ApprovalHistoryPanel({
  taskId,
  task,
  className,
}: ApprovalHistoryPanelProps) {
  const {
    data: eventsData,
    isLoading: isEventsLoading,
    isError: isEventsError,
    error: eventsError,
    refetch: refetchEvents,
  } = useTaskEvents(taskId);

  const {
    data: approvalsData,
    isLoading: isApprovalsLoading,
    isError: isApprovalsError,
    error: approvalsError,
    refetch: refetchApprovals,
  } = useTaskApprovals(taskId);

  const approveToolMutation = useApproveTool(taskId);
  const rejectToolMutation = useRejectTool(taskId);

  const [activeTab, setActiveTab] = useState<'all' | 'execution' | 'tools' | 'mcp'>('all');

  const isError = isEventsError || isApprovalsError;
  const error = eventsError || approvalsError;
  const isLoading = isEventsLoading || (isApprovalsLoading && !approvalsData);

  const refetch = () => {
    refetchEvents();
    refetchApprovals();
  };

  const planApprovalEvents = (eventsData?.items || []).filter(
    (e) => e.event_type === 'PLAN_APPROVED' || e.event_type === 'PLAN_REJECTED'
  );

  const toolApprovals: TaskApproval[] = (approvalsData || []).filter(
    (a) => a.approval_type === 'tool'
  );

  const mcpElicitations: TaskApproval[] = (approvalsData || []).filter(
    (a) => a.approval_type === 'mcp_elicitation'
  );

  const totalDecisions = planApprovalEvents.length + toolApprovals.length + mcpElicitations.length;

  return (
    <div
      className={cn(
        'rounded-lg border border-border bg-card p-5 shadow-xs space-y-4',
        className
      )}
    >
      <div className="flex items-center justify-between border-b border-border pb-3">
        <h3 className="text-base font-semibold text-foreground flex items-center gap-2">
          <Shield className="h-4 w-4 text-primary" />
          Approval & Rejection History
        </h3>
        <span className="text-xs font-mono text-muted-foreground">
          {isError ? 'Error' : `${totalDecisions} decision(s)`}
        </span>
      </div>

      {/* Category Filter Tabs when multiple types present */}
      {(toolApprovals.length > 0 || mcpElicitations.length > 0) && !isError && (
        <div className="flex items-center gap-1.5 border-b border-border/60 pb-2 text-xs">
          <button
            type="button"
            onClick={() => setActiveTab('all')}
            className={cn(
              'px-2.5 py-1 rounded font-medium transition-colors cursor-pointer',
              activeTab === 'all'
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted'
            )}
          >
            All ({totalDecisions})
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('execution')}
            className={cn(
              'px-2.5 py-1 rounded font-medium transition-colors cursor-pointer',
              activeTab === 'execution'
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted'
            )}
          >
            Execution ({planApprovalEvents.length})
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('tools')}
            className={cn(
              'px-2.5 py-1 rounded font-medium transition-colors cursor-pointer',
              activeTab === 'tools'
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted'
            )}
          >
            Tools ({toolApprovals.length})
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('mcp')}
            className={cn(
              'px-2.5 py-1 rounded font-medium transition-colors cursor-pointer',
              activeTab === 'mcp'
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted'
            )}
          >
            MCP ({mcpElicitations.length})
          </button>
        </div>
      )}

      {isError ? (
        <div className="space-y-3 py-2">
          <ErrorMessage error={error} message="Failed to load approval history." />
          <div className="flex justify-end">
            <button
              type="button"
              onClick={refetch}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-border bg-card text-muted-foreground hover:text-foreground hover:bg-accent transition-colors cursor-pointer"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              <span>Retry</span>
            </button>
          </div>
        </div>
      ) : isLoading ? (
        <div className="py-8 text-center">
          <LoadingSpinner size="sm" label="Loading approval records..." />
        </div>
      ) : totalDecisions === 0 ? (
        <div className="py-6 text-center text-muted-foreground space-y-1">
          <p className="text-xs italic">No approval or rejection decisions recorded yet.</p>
          {task.status === 'PENDING_APPROVAL' && (
            <p className="text-[11px] text-amber-400">
              Awaiting human sign-off on implementation plan v{task.plan_version}.
            </p>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {/* 1. Plan / Execution Approvals */}
          {(activeTab === 'all' || activeTab === 'execution') &&
            planApprovalEvents.map((evt, idx) => {
              const isApproved = evt.event_type === 'PLAN_APPROVED';
              const notes =
                (evt.details?.notes as string) ||
                (evt.details?.reason as string) ||
                evt.description;
              const decisionVersion = getDecisionPlanVersion(evt, task);

              return (
                <div
                  key={evt.id || idx}
                  className={cn(
                    'p-3.5 rounded-md border text-xs space-y-2',
                    isApproved
                      ? 'border-emerald-500/20 bg-emerald-500/5'
                      : 'border-rose-500/20 bg-rose-500/5'
                  )}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-primary/10 text-primary border border-primary/20">
                        EXECUTION APPROVAL
                      </span>
                      <span
                        className={cn(
                          'inline-flex items-center gap-1 font-mono font-bold px-2 py-0.5 rounded text-[11px]',
                          isApproved
                            ? 'bg-emerald-500/10 text-emerald-400'
                            : 'bg-rose-500/10 text-rose-400'
                        )}
                      >
                        {isApproved ? (
                          <CheckCircle2 className="h-3 w-3" />
                        ) : (
                          <XCircle className="h-3 w-3" />
                        )}
                        {isApproved ? 'APPROVED' : 'REJECTED'}
                      </span>

                      <span
                        className="font-mono text-muted-foreground text-[11px]"
                        data-testid="decision-plan-version"
                      >
                        Plan v{decisionVersion}
                      </span>
                    </div>

                    <div className="flex items-center gap-1 text-[11px] text-muted-foreground">
                      <Clock className="h-3 w-3" />
                      <span>{formatDate(evt.created_at)}</span>
                    </div>
                  </div>

                  {/* Reviewer */}
                  <div className="text-[11px] text-muted-foreground">
                    Decision by:{' '}
                    <span className="font-medium text-foreground">
                      {evt.user_id || 'Human Reviewer'}
                    </span>
                  </div>

                  {/* Decision notes/reason */}
                  {notes && (
                    <div className="p-2 rounded bg-background/60 border border-border/60 text-foreground/90 font-sans">
                      <span className="font-medium text-muted-foreground mr-1">
                        {isApproved ? 'Notes:' : 'Reason:'}
                      </span>
                      {notes}
                    </div>
                  )}
                </div>
              );
            })}

          {/* 2. Tool Approvals */}
          {(activeTab === 'all' || activeTab === 'tools') &&
            toolApprovals.map((appr) => {
              const isPending = appr.status === 'pending';
              const isApproved = appr.status === 'approved' || appr.status === 'consumed';

              return (
                <div
                  key={appr.id || appr.approval_id}
                  className={cn(
                    'p-3.5 rounded-md border text-xs space-y-2.5',
                    isPending
                      ? 'border-amber-500/30 bg-amber-500/5'
                      : isApproved
                      ? 'border-indigo-500/20 bg-indigo-500/5'
                      : 'border-rose-500/20 bg-rose-500/5'
                  )}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                        <Wrench className="h-3 w-3" />
                        TOOL APPROVAL
                      </span>
                      <span className="font-mono font-semibold text-foreground text-xs">
                        {appr.tool_name}
                      </span>
                      {appr.risk_level && (
                        <span
                          className={cn(
                            'px-1.5 py-0.5 rounded text-[10px] font-mono uppercase',
                            appr.risk_level === 'critical' || appr.risk_level === 'high'
                              ? 'bg-rose-500/15 text-rose-400'
                              : 'bg-amber-500/15 text-amber-400'
                          )}
                        >
                          {appr.risk_level}
                        </span>
                      )}
                      <span
                        className={cn(
                          'px-1.5 py-0.5 rounded text-[10px] font-mono uppercase font-bold',
                          isApproved
                            ? 'bg-emerald-500/10 text-emerald-400'
                            : isPending
                            ? 'bg-amber-500/10 text-amber-400 animate-pulse'
                            : 'bg-rose-500/10 text-rose-400'
                        )}
                      >
                        {appr.status}
                      </span>
                    </div>

                    <div className="flex items-center gap-1 text-[11px] text-muted-foreground">
                      <Clock className="h-3 w-3" />
                      <span>{formatDate(appr.created_at)}</span>
                    </div>
                  </div>

                  {/* Canonical Argument Hash */}
                  {appr.argument_hash && (
                    <div className="text-[11px] font-mono text-muted-foreground flex items-center gap-1">
                      <span className="text-foreground/70 font-semibold">Arg Hash:</span>
                      <code className="bg-muted px-1 rounded text-[10px]">{appr.argument_hash}</code>
                    </div>
                  )}

                  {/* Sanitized Arguments with [REDACTED] */}
                  {appr.sanitized_arguments && Object.keys(appr.sanitized_arguments).length > 0 && (
                    <div className="space-y-1">
                      <span className="text-[10px] font-semibold text-muted-foreground uppercase">
                        Sanitized Arguments
                      </span>
                      <pre className="p-2 rounded bg-background/80 border border-border/70 text-[11px] font-mono text-foreground/90 overflow-x-auto max-h-32">
                        {JSON.stringify(appr.sanitized_arguments, null, 2)}
                      </pre>
                    </div>
                  )}

                  {/* Pending Action Controls */}
                  {isPending && appr.id && (
                    <div className="flex items-center justify-end gap-2 pt-1 border-t border-border/50">
                      <button
                        type="button"
                        disabled={rejectToolMutation.isPending}
                        onClick={() => rejectToolMutation.mutate({ approvalId: appr.id! })}
                        className="px-2.5 py-1 text-xs font-medium rounded border border-rose-500/30 bg-rose-500/10 text-rose-400 hover:bg-rose-500/20 transition-colors cursor-pointer"
                      >
                        Reject Tool
                      </button>
                      <button
                        type="button"
                        disabled={approveToolMutation.isPending}
                        onClick={() => approveToolMutation.mutate({ approvalId: appr.id! })}
                        className="px-2.5 py-1 text-xs font-medium rounded border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 transition-colors cursor-pointer"
                      >
                        Approve Tool
                      </button>
                    </div>
                  )}
                </div>
              );
            })}

          {/* 3. MCP Elicitations */}
          {(activeTab === 'all' || activeTab === 'mcp') &&
            mcpElicitations.map((elic) => {
              const isPending = elic.status === 'pending';
              const isSubmitted = elic.status === 'approved' || elic.status === 'consumed';

              return (
                <div
                  key={elic.id || elic.approval_id}
                  className={cn(
                    'p-3.5 rounded-md border text-xs space-y-2.5',
                    isPending
                      ? 'border-sky-500/30 bg-sky-500/5'
                      : isSubmitted
                      ? 'border-emerald-500/20 bg-emerald-500/5'
                      : 'border-rose-500/20 bg-rose-500/5'
                  )}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-sky-500/10 text-sky-400 border border-sky-500/20">
                        {elic.elicitation_type === 'url' ? (
                          <ExternalLink className="h-3 w-3" />
                        ) : (
                          <FileCode2 className="h-3 w-3" />
                        )}
                        MCP {elic.elicitation_type?.toUpperCase() || 'ELICITATION'}
                      </span>
                      <span className="font-mono text-muted-foreground text-[11px]">
                        Session: {elic.session_id || 'active'}
                      </span>
                      <span
                        className={cn(
                          'px-1.5 py-0.5 rounded text-[10px] font-mono uppercase font-bold',
                          isSubmitted
                            ? 'bg-emerald-500/10 text-emerald-400'
                            : isPending
                            ? 'bg-sky-500/10 text-sky-400 animate-pulse'
                            : 'bg-rose-500/10 text-rose-400'
                        )}
                      >
                        {elic.status}
                      </span>
                    </div>

                    <div className="flex items-center gap-1 text-[11px] text-muted-foreground">
                      <Clock className="h-3 w-3" />
                      <span>{formatDate(elic.created_at)}</span>
                    </div>
                  </div>

                  {/* Elicitation Payload / Details */}
                  {elic.elicitation_payload && (
                    <div className="space-y-1">
                      <span className="text-[10px] font-semibold text-muted-foreground uppercase">
                        Request Details
                      </span>
                      <pre className="p-2 rounded bg-background/80 border border-border/70 text-[11px] font-mono text-foreground/90 overflow-x-auto max-h-32">
                        {JSON.stringify(elic.elicitation_payload, null, 2)}
                      </pre>
                    </div>
                  )}

                  {/* Response Summary if responded */}
                  {elic.elicitation_response && Object.keys(elic.elicitation_response).length > 0 && (
                    <div className="space-y-1">
                      <span className="text-[10px] font-semibold text-emerald-400 uppercase">
                        Submitted Response
                      </span>
                      <pre className="p-2 rounded bg-background/80 border border-emerald-500/20 text-[11px] font-mono text-emerald-300 overflow-x-auto max-h-32">
                        {JSON.stringify(elic.elicitation_response, null, 2)}
                      </pre>
                    </div>
                  )}

                  {/* Non-equivalence Notice */}
                  {isPending && (
                    <div className="flex items-center gap-1 text-[11px] text-amber-400 bg-amber-500/10 p-2 rounded border border-amber-500/20">
                      <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                      <span>
                        An elicitation response provides required parameters only. It does not authorize tool execution.
                      </span>
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
