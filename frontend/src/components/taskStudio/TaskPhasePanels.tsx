import React, { memo } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  ExternalLink,
  FileCode,
  FlaskConical,
  GitBranch,
  GitCommit,
  GitPullRequest,
  Loader2,
  Pause,
  Play,
  RotateCcw,
  ShieldCheck,
  Terminal,
  Wrench,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import type { PlanStep, TaskPlan } from '../../types/task';
import {
  parseUnifiedDiffWithTokens,
  type SyntaxToken,
  useVirtualRange,
} from '../../utils/virtualizationAndSyntax';
import { CodeChangesPanel } from '../tasks/CodeChangesPanel';
import { TestExecutionPanel } from '../tasks/TestExecutionPanel';
import { VerificationPanel } from '../tasks/VerificationPanel';

const TOKEN_COLOR_CLASS: Record<SyntaxToken['kind'], string> = {
  keyword: 'text-rose-700 dark:text-rose-400 font-medium',
  string: 'text-emerald-700 dark:text-emerald-400',
  comment: 'text-muted-foreground/75 italic',
  number: 'text-sky-700 dark:text-sky-400',
  type: 'text-amber-700 dark:text-amber-400',
  function: 'text-teal-700 dark:text-teal-400',
  operator: 'text-muted-foreground',
  plain: 'text-foreground',
};

export interface PlanCandidateItem {
  filePath: string;
  symbolName?: string;
  score: number;
  rationale: string;
}

export interface PlanStepItem {
  id: string;
  title: string;
  status: 'pending' | 'in_progress' | 'completed' | 'failed';
  targetFiles: string[];
}

export interface TaskPlanPhaseProps {
  taskId: string;
  candidates: PlanCandidateItem[];
  steps: PlanStepItem[];
  isApproved: boolean;
  onApprovePlan: () => void;
}

export const TaskPlanPhasePanel: React.FC<TaskPlanPhaseProps> = memo(
  ({ candidates, steps, isApproved, onApprovePlan }) => (
    <section aria-label="Plan Review Phase" className="space-y-4 p-4 rounded-xl border border-border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-foreground">Phase 1 · Hierarchical Localisation &amp; Plan Review</h2>
          <p className="text-xs text-muted-foreground">
            Ranked file/symbol targets from Agentless 3-stage funnel and structured execution DAG.
          </p>
        </div>
        {!isApproved && (
          <button
            type="button"
            onClick={onApprovePlan}
            className="px-3 py-1.5 rounded-lg bg-primary hover:bg-primary/90 text-xs font-medium text-primary-foreground transition-colors cursor-pointer shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Approve Plan
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="space-y-2 min-w-0">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Localized Targets</h3>
          {candidates.map((cand) => (
            <div key={`${cand.filePath}:${cand.symbolName ?? ''}`} className="p-2.5 rounded-lg bg-background border border-border text-xs">
              <div className="flex flex-wrap items-center justify-between gap-2 font-mono text-foreground">
                <span className="break-all">{cand.filePath}{cand.symbolName ? ` :: ${cand.symbolName}` : ''}</span>
                <span className="text-emerald-700 dark:text-emerald-400 shrink-0">{(cand.score * 100).toFixed(1)}%</span>
              </div>
              <p className="text-muted-foreground mt-1">{cand.rationale}</p>
            </div>
          ))}
        </div>

        <div className="space-y-2 min-w-0">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Plan Steps</h3>
          {steps.map((step, idx) => (
            <div key={step.id} className="p-2.5 rounded-lg bg-background border border-border text-xs flex items-start justify-between gap-2">
              <div className="min-w-0">
                <span className="font-medium text-foreground">{idx + 1}. {step.title}</span>
                <div className="text-muted-foreground font-mono mt-0.5 break-all">{step.targetFiles.join(', ')}</div>
              </div>
              <span className="px-2 py-0.5 rounded bg-muted text-muted-foreground shrink-0">{step.status}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  ),
);
TaskPlanPhasePanel.displayName = 'TaskPlanPhasePanel';

export interface ActiveToolProgressItem {
  callId: string;
  toolName: string;
  stage: 'started' | 'progress' | 'completed' | 'failed';
  progressPct?: number | null;
  message?: string | null;
}

export interface PendingApprovalGateItem {
  approvalId: string;
  toolName: string;
  riskTier: string;
  argumentsJson: string;
}

export interface TaskExecutionPhaseProps {
  activeTools: ActiveToolProgressItem[];
  pendingApprovals: PendingApprovalGateItem[];
  streamingAssistantText: string;
  onResolveApproval: (approvalId: string, approved: boolean) => void;
}

export const TaskExecutionPhasePanel: React.FC<TaskExecutionPhaseProps> = memo(
  ({ activeTools, pendingApprovals, streamingAssistantText, onResolveApproval }) => (
    <section aria-label="Execution Timeline Phase" className="space-y-4 p-4 rounded-xl border border-border bg-card">
      <h2 className="text-sm font-semibold text-foreground">Phase 2 · Live Execution &amp; Tool/MCP Telemetry</h2>

      {pendingApprovals.map((gate) => (
        <div key={gate.approvalId} className="p-3 rounded-lg border border-amber-500/30 bg-amber-500/10 space-y-2 text-xs">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-semibold text-amber-800 dark:text-amber-300">
              Approval Required · <code className="font-mono">{gate.toolName}</code> ({gate.riskTier})
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => onResolveApproval(gate.approvalId, true)}
                className="px-2.5 py-1 rounded-md bg-emerald-700 hover:bg-emerald-600 text-white cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                Approve
              </button>
              <button
                type="button"
                onClick={() => onResolveApproval(gate.approvalId, false)}
                className="px-2.5 py-1 rounded-md bg-destructive hover:bg-destructive/90 text-destructive-foreground cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                Reject
              </button>
            </div>
          </div>
          <pre className="p-2 rounded bg-background border border-border text-foreground overflow-x-auto font-mono">{gate.argumentsJson}</pre>
        </div>
      ))}

      <div className="space-y-2">
        {activeTools.map((tool) => (
          <div key={tool.callId} className="p-2.5 rounded-lg bg-background border border-border text-xs space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="font-mono font-medium text-foreground">{tool.toolName}</span>
              <span className="text-muted-foreground">
                {tool.stage} {tool.progressPct != null ? `(${Math.round(tool.progressPct)}%)` : ''}
              </span>
            </div>
            {tool.progressPct != null && (
              <div className="w-full h-1.5 rounded bg-muted overflow-hidden">
                <div
                  className="h-full bg-primary transition-all duration-150"
                  style={{ width: `${Math.max(0, Math.min(100, tool.progressPct))}%` }}
                />
              </div>
            )}
            {tool.message && <p className="text-muted-foreground">{tool.message}</p>}
          </div>
        ))}
      </div>

      {streamingAssistantText && (
        <div className="p-3 rounded-lg bg-background border border-border font-mono text-xs text-foreground whitespace-pre-wrap">
          {streamingAssistantText}
        </div>
      )}
    </section>
  ),
);
TaskExecutionPhasePanel.displayName = 'TaskExecutionPhasePanel';

export interface TaskVerificationPhaseProps {
  unifiedDiff: string;
  repairAttempt: number;
  maxRepairAttempts: number;
  testsPassed: number;
  testsFailed: number;
}

export const TaskVerificationPhasePanel: React.FC<TaskVerificationPhaseProps> = memo(
  ({ unifiedDiff, repairAttempt, maxRepairAttempts, testsPassed, testsFailed }) => {
    const parsedLines = React.useMemo(() => parseUnifiedDiffWithTokens(unifiedDiff), [unifiedDiff]);
    const { windowSlice, onScroll } = useVirtualRange({
      totalCount: parsedLines.length,
      itemHeightPx: 22,
      viewportHeightPx: 352,
      overscan: 10,
      resetKey: unifiedDiff.length,
    });

    const visibleLines = parsedLines.slice(windowSlice.startIndex, windowSlice.endIndex);

    return (
      <section aria-label="Verification & Diff Phase" className="space-y-3 p-4 rounded-xl border border-border bg-card">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <h2 className="text-sm font-semibold text-foreground">Phase 3 · Verification, Self-Repair &amp; Virtualized Diff</h2>
          <div className="flex gap-3 text-xs font-mono">
            <span className="text-emerald-700 dark:text-emerald-400">Passed: {testsPassed}</span>
            <span className="text-rose-700 dark:text-rose-400">Failed: {testsFailed}</span>
            <span className="text-muted-foreground">Repair Budget: {repairAttempt}/{maxRepairAttempts}</span>
          </div>
        </div>

        <div
          onScroll={onScroll}
          style={{ height: 352 }}
          className="overflow-auto rounded-lg border border-border bg-background font-mono text-xs"
        >
          <div
            className="min-w-max"
            style={{ paddingTop: windowSlice.topPaddingPx, paddingBottom: windowSlice.bottomPaddingPx }}
          >
            {visibleLines.map((line, idx) => {
              const absoluteIdx = windowSlice.startIndex + idx;
              const rowBg =
                line.type === 'add'
                  ? 'bg-emerald-500/10'
                  : line.type === 'del'
                    ? 'bg-rose-500/10'
                    : line.type === 'hunk'
                      ? 'bg-muted/70'
                      : '';
              return (
                <div
                  key={absoluteIdx}
                  style={{ height: 22 }}
                  className={`flex items-center px-3 whitespace-pre ${rowBg}`}
                >
                  <span className="w-10 shrink-0 select-none text-right pr-2 text-muted-foreground/60">
                    {line.oldLineNumber ?? ''}
                  </span>
                  <span className="w-10 shrink-0 select-none text-right pr-3 text-muted-foreground/60">
                    {line.newLineNumber ?? ''}
                  </span>
                  <span className="w-4 shrink-0 select-none text-muted-foreground">
                    {line.type === 'add' ? '+' : line.type === 'del' ? '-' : ' '}
                  </span>
                  <span>
                    {line.tokens.map((tok, tIdx) => (
                      <span key={tIdx} className={TOKEN_COLOR_CLASS[tok.kind]}>
                        {tok.text}
                      </span>
                    ))}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </section>
    );
  },
);
TaskVerificationPhasePanel.displayName = 'TaskVerificationPhasePanel';

export interface TaskPublicationPhaseProps {
  branchName: string;
  commitSha?: string | null;
  pullRequestUrl?: string | null;
  secretsRedactedCount: number;
  onPublishPullRequest: () => void;
}

export const TaskPublicationPhasePanel: React.FC<TaskPublicationPhaseProps> = memo(
  ({ branchName, commitSha, pullRequestUrl, secretsRedactedCount, onPublishPullRequest }) => (
    <section aria-label="Publication Phase" className="space-y-3 p-4 rounded-xl border border-border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-foreground">Phase 4 · Host-Isolated Git Publication</h2>
          <p className="text-xs text-muted-foreground break-words">
            Branch <code className="font-mono text-foreground">{branchName}</code> · Secrets scrubbed: {secretsRedactedCount}
          </p>
        </div>
        {!pullRequestUrl ? (
          <button
            type="button"
            onClick={onPublishPullRequest}
            className="px-3 py-1.5 rounded-lg bg-primary hover:bg-primary/90 text-xs font-medium text-primary-foreground cursor-pointer shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Publish Pull Request
          </button>
        ) : (
          <a
            href={pullRequestUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs font-medium text-foreground underline underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
          >
            View Pull Request ({commitSha?.slice(0, 7) ?? 'HEAD'})
          </a>
        )}
      </div>
    </section>
  ),
);
TaskPublicationPhasePanel.displayName = 'TaskPublicationPhasePanel';

export interface RepositoryTaskPlanTabProps {
  taskDetail: any;
  latestPlan: TaskPlan | null | any;
  showRevisionInput: boolean;
  setShowRevisionInput: (v: boolean) => void;
  showRejectionInput: boolean;
  setShowRejectionInput: (v: boolean) => void;
  revisionNotes: string;
  setRevisionNotes: (v: string) => void;
  rejectionReason: string;
  setRejectionReason: (v: string) => void;
  approvalComment: string;
  setApprovalComment: (v: string) => void;
  actionBusy: string | null;
  handleGenerateOrRevisePlan: () => void;
  handleRejectPlan: () => void;
  handleApprovePlan: () => void;
}

export const RepositoryTaskPlanTab: React.FC<RepositoryTaskPlanTabProps> = memo(
  ({
    taskDetail,
    latestPlan,
    showRevisionInput,
    setShowRevisionInput,
    showRejectionInput,
    setShowRejectionInput,
    revisionNotes,
    setRevisionNotes,
    rejectionReason,
    setRejectionReason,
    approvalComment,
    setApprovalComment,
    actionBusy,
    handleGenerateOrRevisePlan,
    handleRejectPlan,
    handleApprovePlan,
  }) => (
    <div className="space-y-4 animate-in fade-in duration-150">
      {taskDetail.status === 'PENDING_APPROVAL' && latestPlan && (
        <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/5 p-4.5 space-y-3">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
              <span className="text-xs font-bold text-foreground">
                Plan v{latestPlan.plan_version} Ready for Approval
              </span>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setShowRevisionInput(!showRevisionInput)}
                className="text-xs text-muted-foreground hover:text-foreground underline cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
              >
                {showRevisionInput ? 'Hide Revision Notes' : 'Request Revision'}
              </button>
              <button
                type="button"
                onClick={() => setShowRejectionInput(!showRejectionInput)}
                className="text-xs text-rose-700 hover:text-rose-800 dark:text-rose-400 dark:hover:text-rose-300 underline cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
              >
                {showRejectionInput ? 'Hide Rejection' : 'Reject'}
              </button>
            </div>
          </div>

          {showRevisionInput && (
            <div className="flex flex-col sm:flex-row sm:items-center gap-2 pt-2 border-t border-border/40">
              <input
                type="text"
                aria-label="Revision notes"
                placeholder="Provide feedback to refine the plan..."
                value={revisionNotes}
                onChange={(e) => setRevisionNotes(e.target.value)}
                className="flex-1 min-w-0 px-3 py-1.5 text-xs rounded-lg border border-border bg-background text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
              <button
                type="button"
                disabled={actionBusy !== null || !revisionNotes.trim()}
                onClick={handleGenerateOrRevisePlan}
                className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-card border border-border hover:bg-accent cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                Synthesize v{latestPlan.plan_version + 1}
              </button>
            </div>
          )}

          {showRejectionInput && (
            <div className="flex flex-col sm:flex-row sm:items-center gap-2 pt-2 border-t border-border/40">
              <input
                type="text"
                aria-label="Rejection reason"
                placeholder="Reason for rejecting plan..."
                value={rejectionReason}
                onChange={(e) => setRejectionReason(e.target.value)}
                className="flex-1 min-w-0 px-3 py-1.5 text-xs rounded-lg border border-rose-500/40 bg-background text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
              <button
                type="button"
                disabled={actionBusy !== null}
                onClick={handleRejectPlan}
                className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-rose-700 text-white hover:bg-rose-600 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                Reject Plan
              </button>
            </div>
          )}

          <div className="flex flex-col sm:flex-row sm:items-center gap-2.5 pt-1">
            <input
              type="text"
              aria-label="Optional approval comment"
              placeholder="Optional approval comment..."
              value={approvalComment}
              onChange={(e) => setApprovalComment(e.target.value)}
              className="flex-1 min-w-0 px-3 py-1.5 text-xs rounded-lg border border-border bg-background text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            <button
              type="button"
              disabled={actionBusy !== null}
              onClick={handleApprovePlan}
              className="px-4 py-1.5 text-xs font-bold rounded-lg bg-emerald-700 hover:bg-emerald-600 text-white transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              Approve Plan
            </button>
          </div>
        </div>
      )}

      {latestPlan ? (
        <div className="rounded-xl border border-border bg-card p-4.5 space-y-4">
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <div className="text-[11px] font-mono uppercase text-primary font-bold">
                AI Implementation Plan (v{latestPlan.plan_version})
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {latestPlan.intent && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-blue-500/10 text-blue-700 dark:text-blue-400 border border-blue-500/30">
                    <Wrench className="h-3 w-3" />
                    <span>Intent: {latestPlan.intent.toUpperCase()}</span>
                  </span>
                )}
                {latestPlan.critic_score !== undefined && (
                  <span className={cn(
                    "inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-bold border",
                    latestPlan.critic_score >= 80
                      ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/30"
                      : "bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/30"
                  )}>
                    <ShieldCheck className="h-3 w-3" />
                    <span>Critic Score: {latestPlan.critic_score}/100</span>
                  </span>
                )}
              </div>
            </div>
            <p className="text-sm font-medium text-foreground leading-snug break-words">
              {latestPlan.summary}
            </p>
            {latestPlan.problem_statement && (
              <p className="text-xs text-muted-foreground break-words pt-1">
                {latestPlan.problem_statement}
              </p>
            )}
            {latestPlan.critic_notes && latestPlan.critic_notes.length > 0 && (
              <div className="mt-2 p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/25 text-xs text-amber-800 dark:text-amber-300 space-y-1">
                <div className="font-semibold text-[11px] uppercase tracking-wider flex items-center gap-1.5">
                  <AlertCircle className="h-3.5 w-3.5" />
                  <span>Adversarial Critic Notes:</span>
                </div>
                <ul className="list-disc list-inside space-y-0.5 text-[11px] text-muted-foreground">
                  {latestPlan.critic_notes.map((note: string, idx: number) => (
                    <li key={idx}>{note}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          <div className="space-y-2">
            <div className="text-[11px] font-mono uppercase text-muted-foreground font-bold">
              Ordered Execution Steps ({latestPlan.steps?.length ?? 0})
            </div>
            <div className="space-y-2">
              {latestPlan.steps?.map((s: PlanStep, idx: number) => (
                <div
                  key={s.step_id || idx}
                  className="p-3 rounded-lg bg-muted/20 border border-border/60 space-y-1.5 text-xs"
                >
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <div className="flex flex-wrap items-center gap-2 min-w-0">
                      <span className="font-mono text-[10px] text-primary font-bold px-1.5 py-0.5 rounded bg-primary/10 shrink-0">
                        Step {idx + 1}
                      </span>
                      <span className="font-mono text-[10px] uppercase font-bold text-muted-foreground px-1.5 py-0.5 rounded bg-muted shrink-0">
                        {s.action_type || s.step_type || 'modify'}
                      </span>
                      <span className="font-semibold text-foreground break-words">{s.description}</span>
                    </div>
                    {s.risk_level && (
                      <span
                        className={cn(
                          'px-2 py-0.5 rounded text-[10px] font-mono border uppercase font-semibold shrink-0',
                          s.risk_level === 'low'
                            ? 'bg-blue-500/10 text-blue-700 dark:text-blue-400 border-blue-500/30'
                            : 'bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/30'
                        )}
                      >
                        Risk: {s.risk_level}
                      </span>
                    )}
                  </div>

                  {s.expected_files && s.expected_files.length > 0 && (
                    <div className="text-[11px] font-mono text-muted-foreground flex items-center gap-1.5 flex-wrap pt-0.5">
                      <FileCode className="h-3 w-3 text-primary/70 shrink-0" />
                      <span>Target Files:</span>
                      {s.expected_files.map((f: string) => (
                        <span
                          key={f}
                          className="px-1.5 py-0.5 rounded bg-background border border-border text-[10px] break-all"
                        >
                          {f}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div className="p-8 text-center text-xs text-muted-foreground space-y-2 border border-border rounded-xl bg-card">
          <p>No implementation plan generated yet.</p>
          <button
            type="button"
            onClick={handleGenerateOrRevisePlan}
            className="px-3.5 py-1.5 rounded-lg bg-primary text-primary-foreground font-semibold text-xs cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Synthesize Plan
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="rounded-xl border border-border bg-card p-4 space-y-2">
          <div className="text-[11px] font-mono uppercase text-primary font-bold">
            Requirements ({taskDetail.requirements?.length ?? 0})
          </div>
          <div className="space-y-1 text-xs">
            {taskDetail.requirements && taskDetail.requirements.length > 0 ? (
              taskDetail.requirements.map((r: any) => (
                <div key={r.id} className="text-foreground/90 break-words">
                  • {r.description}
                </div>
              ))
            ) : (
              <div className="text-muted-foreground">Autonomous functional repair.</div>
            )}
          </div>
        </div>

        <div className="rounded-xl border border-border bg-card p-4 space-y-2">
          <div className="text-[11px] font-mono uppercase text-rose-700 dark:text-rose-400 font-bold">
            Protected Safety Boundaries
          </div>
          <div className="space-y-1 text-xs text-muted-foreground">
            <p>Strictly shielded from modification:</p>
            <div className="flex flex-wrap items-center gap-1.5 font-mono text-[11px] text-rose-700 dark:text-rose-300 pt-1">
              <span className="px-2 py-0.5 rounded bg-rose-500/10 border border-rose-500/30">.env</span>
              <span className="px-2 py-0.5 rounded bg-rose-500/10 border border-rose-500/30 break-all">
                .github/workflows/deploy.yml
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
);
RepositoryTaskPlanTab.displayName = 'RepositoryTaskPlanTab';

export interface RepositoryTaskWorkspaceTabProps {
  hasWorkspace: boolean;
  workspaceMeta: any;
  latestPlan: any;
  actionBusy: string | null;
  handlePauseTask: () => void;
  handleResumeTask: () => void;
  handleCommitChanges: () => void;
  handleExecuteTask: (runSteps?: boolean) => void;
  taskStatus?: string;
  handleRecoverTask?: () => void;
}

export const RepositoryTaskWorkspaceTab: React.FC<RepositoryTaskWorkspaceTabProps> = memo(
  ({
    hasWorkspace,
    workspaceMeta,
    latestPlan,
    actionBusy,
    handlePauseTask,
    handleResumeTask,
    handleCommitChanges,
    handleExecuteTask,
    taskStatus,
    handleRecoverTask,
  }) => {
    const isFailedOrRecover = taskStatus === 'FAILED' || taskStatus === 'RECOVERY_REQUIRED';

    return (
      <div className="space-y-4 animate-in fade-in duration-150">
        {isFailedOrRecover && (
          <div className="flex flex-wrap items-center justify-between gap-2 p-3 rounded-lg bg-destructive/10 border border-destructive/25 text-destructive text-xs">
            <div className="flex items-center gap-2 min-w-0">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>
                Task execution interrupted. Click <strong>Recover Task</strong> to reconcile state and resume safely.
              </span>
            </div>
            {handleRecoverTask && (
              <button
                type="button"
                disabled={actionBusy !== null}
                onClick={handleRecoverTask}
                className="inline-flex items-center gap-1 px-3 py-1 rounded-md bg-destructive hover:bg-destructive/90 text-destructive-foreground font-medium text-xs shrink-0 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <RotateCcw className="h-3 w-3" />
                <span>Recover Task</span>
              </button>
            )}
          </div>
        )}

        {hasWorkspace && workspaceMeta ? (
          <div className="rounded-xl border border-border bg-card p-4 space-y-4">
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <div className="flex flex-wrap items-center gap-2 min-w-0">
                <Terminal className="h-4 w-4 text-muted-foreground shrink-0" />
                <h3 className="text-xs font-semibold uppercase tracking-wider text-foreground">
                  Isolated Sandbox Status
                </h3>
                <span className="px-2 py-0.5 rounded bg-muted text-foreground border border-border font-mono text-[10px]">
                  {workspaceMeta.status}
                </span>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                {isFailedOrRecover ? (
                  handleRecoverTask && (
                    <button
                      type="button"
                      disabled={actionBusy !== null}
                      onClick={handleRecoverTask}
                      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400 text-xs font-medium hover:bg-amber-500/20 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <RotateCcw className="h-3 w-3" />
                      <span>Recover</span>
                    </button>
                  )
                ) : (
                  <>
                    {workspaceMeta.status === 'IN_USE' && (
                      <button
                        type="button"
                        disabled={actionBusy !== null}
                        onClick={handlePauseTask}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400 text-xs font-medium hover:bg-amber-500/20 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <Pause className="h-3 w-3" />
                        <span>Pause</span>
                      </button>
                    )}
                    {workspaceMeta.status === 'STOPPED' && (
                      <button
                        type="button"
                        disabled={actionBusy !== null}
                        onClick={handleResumeTask}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 text-xs font-medium hover:bg-emerald-500/20 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <Play className="h-3 w-3" />
                        <span>Resume</span>
                      </button>
                    )}
                    <button
                      type="button"
                      disabled={actionBusy !== null}
                      onClick={handleCommitChanges}
                      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-border bg-background text-foreground text-xs font-medium hover:bg-accent cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <GitCommit className="h-3 w-3" />
                      <span>Commit</span>
                    </button>
                  </>
                )}
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
              <div className="p-2.5 rounded-lg bg-background/60 border border-border/60 space-y-1 min-w-0">
                <span className="text-[10px] font-mono text-muted-foreground uppercase">Isolated Branch</span>
                <div className="font-mono text-xs text-foreground font-semibold flex items-center gap-1.5 min-w-0">
                  <GitBranch className="h-3.5 w-3.5 text-primary shrink-0" />
                  <span className="truncate">{workspaceMeta.branch_name}</span>
                </div>
              </div>

              <div className="p-2.5 rounded-lg bg-background/60 border border-border/60 space-y-1 min-w-0">
                <span className="text-[10px] font-mono text-muted-foreground uppercase">Sandbox Location</span>
                <div
                  className="font-mono text-[11px] text-muted-foreground truncate"
                  title={workspaceMeta.workspace_path}
                >
                  {workspaceMeta.workspace_path}
                </div>
              </div>
            </div>

            <div className="p-3 rounded-lg bg-background/70 border border-border/60 space-y-2">
              <div className="text-[10px] font-mono uppercase text-muted-foreground font-bold">
                Step Execution Progress
              </div>
              <div className="space-y-1.5">
                {latestPlan?.steps?.map((s: PlanStep, i: number) => {
                  let stepStatus: 'COMPLETED' | 'IN_PROGRESS' | 'FAILED' | 'PENDING' = 'PENDING';
                  if (
                    ['READY_FOR_PUBLICATION', 'DRAFT_PR_CREATED', 'COMPLETED', 'VERIFYING', 'TESTING'].includes(
                      taskStatus || ''
                    )
                  ) {
                    stepStatus = 'COMPLETED';
                  } else if (taskStatus === 'EXECUTING') {
                    stepStatus = i === 0 ? 'IN_PROGRESS' : 'PENDING';
                  } else if (isFailedOrRecover) {
                    stepStatus = i === 0 ? 'FAILED' : 'PENDING';
                  }

                  return (
                    <div
                      key={s.step_id || i}
                      className="flex flex-wrap items-center justify-between gap-2 text-xs py-1 px-2 rounded bg-muted/20"
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        {stepStatus === 'COMPLETED' && (
                          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400 shrink-0" />
                        )}
                        {stepStatus === 'IN_PROGRESS' && (
                          <Loader2 className="h-3.5 w-3.5 text-cyan-600 dark:text-cyan-400 animate-spin shrink-0" />
                        )}
                        {stepStatus === 'FAILED' && (
                          <AlertCircle className="h-3.5 w-3.5 text-rose-600 dark:text-rose-400 shrink-0" />
                        )}
                        {stepStatus === 'PENDING' && (
                          <Clock className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                        )}
                        <span className="font-semibold text-foreground break-words">
                          Step {i + 1}: {s.description}
                        </span>
                      </div>
                      <span
                        className={`font-mono text-[10px] font-bold uppercase shrink-0 ${
                          stepStatus === 'COMPLETED'
                            ? 'text-emerald-700 dark:text-emerald-400'
                            : stepStatus === 'FAILED'
                            ? 'text-rose-700 dark:text-rose-400'
                            : stepStatus === 'IN_PROGRESS'
                            ? 'text-cyan-700 dark:text-cyan-400'
                            : 'text-muted-foreground'
                        }`}
                      >
                        {stepStatus}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        ) : (
          <div className="p-8 text-center text-xs text-muted-foreground space-y-3 border border-border rounded-xl bg-card">
            <Terminal className="h-8 w-8 text-muted-foreground/40 mx-auto" />
            <p>Workspace has not been provisioned yet.</p>
            <button
              type="button"
              onClick={() => handleExecuteTask(true)}
              className="px-4 py-2 rounded-lg bg-emerald-700 hover:bg-emerald-600 text-white font-bold text-xs cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              Start Workspace Execution
            </button>
          </div>
        )}
      </div>
    );
  }
);
RepositoryTaskWorkspaceTab.displayName = 'RepositoryTaskWorkspaceTab';

export interface RepositoryTaskTestsTabProps {
  taskId: string;
  testResults: any;
  actionBusy: string | null;
  repairAttemptsUsed: number;
  repairAttemptsMax: number;
  handleRunTests: () => void;
  handleRunRepair: () => void;
  testRunnerLabel?: string;
}

export const RepositoryTaskTestsTab: React.FC<RepositoryTaskTestsTabProps> = memo(
  ({
    taskId,
    testResults,
    actionBusy,
    repairAttemptsUsed,
    repairAttemptsMax,
    handleRunTests,
    handleRunRepair,
    testRunnerLabel,
  }) => (
    <div className="space-y-4 animate-in fade-in duration-150">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-xs font-bold uppercase tracking-wider text-foreground">
            Automated Test Suite &amp; Self-Healing Loop
          </h3>
          <p className="text-xs text-muted-foreground">
            Validates repository functionality on the isolated sandbox branch.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={actionBusy !== null}
            onClick={handleRunTests}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sky-700 hover:bg-sky-600 text-white text-xs font-semibold cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <FlaskConical className="h-3.5 w-3.5" />
            <span>{testRunnerLabel || 'Run Tests'}</span>
          </button>

          <button
            type="button"
            disabled={actionBusy !== null || repairAttemptsUsed >= repairAttemptsMax}
            onClick={handleRunRepair}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border bg-background text-foreground hover:bg-accent text-xs font-medium cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Wrench className="h-3.5 w-3.5" />
            <span>
              Self-Repair ({repairAttemptsUsed}/{repairAttemptsMax})
            </span>
          </button>
        </div>
      </div>

      <TestExecutionPanel taskId={taskId} testResults={testResults} />
    </div>
  )
);
RepositoryTaskTestsTab.displayName = 'RepositoryTaskTestsTab';

export interface RepositoryTaskChangesTabProps {
  taskId: string;
  repositoryId: string;
  plannedTargetFiles: string[];
}

export const RepositoryTaskChangesTab: React.FC<RepositoryTaskChangesTabProps> = memo(
  ({ taskId, repositoryId, plannedTargetFiles }) => (
    <div className="space-y-4 animate-in fade-in duration-150">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-xs font-bold uppercase tracking-wider text-foreground">
            Workspace Code Changes
          </h3>
          <p className="text-xs text-muted-foreground">
            Inspect modifications made by the AI agent before committing.
          </p>
        </div>
      </div>

      <CodeChangesPanel
        taskId={taskId}
        repositoryId={repositoryId}
        plannedTargetFiles={plannedTargetFiles}
      />
    </div>
  )
);
RepositoryTaskChangesTab.displayName = 'RepositoryTaskChangesTab';

export interface RepositoryTaskVerificationTabProps {
  taskId: string;
  currentRevision?: string | null;
  actionBusy: string | null;
  handleRunVerification: () => void;
}

export const RepositoryTaskVerificationTab: React.FC<RepositoryTaskVerificationTabProps> = memo(
  ({ taskId, currentRevision, actionBusy, handleRunVerification }) => (
    <div className="space-y-4 animate-in fade-in duration-150">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-xs font-bold uppercase tracking-wider text-foreground">
            Independent Quality &amp; Security Verification
          </h3>
          <p className="text-xs text-muted-foreground">
            5-point validation across tests, diff scope, secret detection, static analysis, and review.
          </p>
        </div>

        <button
          type="button"
          disabled={actionBusy !== null}
          onClick={handleRunVerification}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-teal-700 hover:bg-teal-600 text-white text-xs font-semibold cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ShieldCheck className="h-3.5 w-3.5" />
          <span>Run Verification</span>
        </button>
      </div>

      <VerificationPanel taskId={taskId} currentRevision={currentRevision} />
    </div>
  )
);
RepositoryTaskVerificationTab.displayName = 'RepositoryTaskVerificationTab';

export interface RepositoryTaskPrTabProps {
  draftPR: any;
  verificationResult: any;
  publicationAuthorized: boolean;
  setPublicationAuthorized: (v: boolean) => void;
  actionBusy: string | null;
  handleCreateDraftPR: () => void;
}

export const RepositoryTaskPrTab: React.FC<RepositoryTaskPrTabProps> = memo(
  ({
    draftPR,
    verificationResult,
    publicationAuthorized,
    setPublicationAuthorized,
    actionBusy,
    handleCreateDraftPR,
  }) => (
    <div className="space-y-4 animate-in fade-in duration-150">
      {draftPR ? (
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-5 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <GitPullRequest className="h-5 w-5 text-emerald-600 dark:text-emerald-400 shrink-0" />
              <h3 className="text-sm font-semibold text-foreground">
                Draft Pull Request #{draftPR.pr_number} Active
              </h3>
            </div>
            <a
              href={draftPR.pr_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary hover:bg-primary/90 text-primary-foreground text-xs font-medium transition-colors shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span>Open on GitHub</span>
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          </div>
          <p className="text-xs text-muted-foreground leading-relaxed">
            The agent published this draft pull request to GitHub. Changes are verified and ready for review.
          </p>
          <div className="text-[11px] font-mono text-muted-foreground flex flex-wrap items-center gap-2 sm:gap-3 pt-1">
            <span className="break-all">Branch: {draftPR.head_branch || draftPR.pr_id}</span>
            <span>→</span>
            <span className="break-all">Target: {draftPR.base_branch}</span>
          </div>
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card p-5 space-y-4">
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-foreground">
              Publish GitHub Draft Pull Request
            </h3>
            <p className="text-xs text-muted-foreground pt-0.5">
              Push isolated task branch and open a review-ready Draft PR on GitHub.
            </p>
          </div>

          <div className="p-3.5 rounded-lg bg-muted/40 border border-border space-y-2 text-xs">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-semibold text-foreground">Verification Requirement</span>
              <span className="font-mono text-[10px] text-teal-700 dark:text-teal-400 font-semibold uppercase">
                {verificationResult?.status || 'REQUIRES VERIFICATION'}
              </span>
            </div>
            <p className="text-muted-foreground text-[11px]">
              All unit tests and scope bounds are verified before pull request publication is unlocked.
            </p>
          </div>

          <label className="flex items-start gap-2.5 text-xs text-foreground cursor-pointer pt-1">
            <input
              type="checkbox"
              checked={publicationAuthorized}
              onChange={(e) => setPublicationAuthorized(e.target.checked)}
              className="mt-0.5 rounded border-border text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
            />
            <span>
              I authorize pushing the isolated task branch to remote GitHub and creating a Draft Pull Request.
            </span>
          </label>

          <button
            type="button"
            disabled={actionBusy !== null || !publicationAuthorized}
            onClick={handleCreateDraftPR}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary hover:bg-primary/90 text-primary-foreground text-xs font-medium disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <GitPullRequest className="h-4 w-4" />
            <span>Publish Draft Pull Request</span>
          </button>
        </div>
      )}
    </div>
  )
);
RepositoryTaskPrTab.displayName = 'RepositoryTaskPrTab';
