import React, { memo } from 'react';
import {
  parseUnifiedDiffWithTokens,
  SyntaxToken,
  useVirtualRange,
} from '../../utils/virtualizationAndSyntax';

const TOKEN_COLOR_CLASS: Record<SyntaxToken['kind'], string> = {
  keyword: 'text-purple-400 font-medium',
  string: 'text-emerald-400',
  comment: 'text-slate-500 italic',
  number: 'text-amber-300',
  type: 'text-sky-300',
  function: 'text-blue-400',
  operator: 'text-pink-400',
  plain: 'text-slate-200',
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
    <section aria-label="Plan Review Phase" className="space-y-4 p-4 rounded-lg border border-slate-800 bg-slate-900/50">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-100">Phase 1 · Hierarchical Localisation &amp; Plan Review</h2>
          <p className="text-xs text-slate-400">
            Ranked file/symbol targets from Agentless 3-stage funnel and structured execution DAG.
          </p>
        </div>
        {!isApproved && (
          <button
            type="button"
            onClick={onApprovePlan}
            className="px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 text-xs font-medium text-white"
          >
            Approve Plan
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">Localized Targets</h3>
          {candidates.map((cand) => (
            <div key={`${cand.filePath}:${cand.symbolName ?? ''}`} className="p-2.5 rounded bg-slate-950 border border-slate-800 text-xs">
              <div className="flex items-center justify-between font-mono text-indigo-300">
                <span>{cand.filePath}{cand.symbolName ? ` :: ${cand.symbolName}` : ''}</span>
                <span className="text-emerald-400">{(cand.score * 100).toFixed(1)}%</span>
              </div>
              <p className="text-slate-400 mt-1">{cand.rationale}</p>
            </div>
          ))}
        </div>

        <div className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">Plan Steps</h3>
          {steps.map((step, idx) => (
            <div key={step.id} className="p-2.5 rounded bg-slate-950 border border-slate-800 text-xs flex items-start justify-between">
              <div>
                <span className="font-medium text-slate-200">{idx + 1}. {step.title}</span>
                <div className="text-slate-500 font-mono mt-0.5">{step.targetFiles.join(', ')}</div>
              </div>
              <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-300">{step.status}</span>
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
    <section aria-label="Execution Timeline Phase" className="space-y-4 p-4 rounded-lg border border-slate-800 bg-slate-900/50">
      <h2 className="text-base font-semibold text-slate-100">Phase 2 · Live Execution &amp; Tool/MCP Telemetry</h2>

      {pendingApprovals.map((gate) => (
        <div key={gate.approvalId} className="p-3 rounded border border-amber-700 bg-amber-950/40 space-y-2 text-xs">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-amber-200">
              Approval Required · <code className="font-mono">{gate.toolName}</code> ({gate.riskTier})
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => onResolveApproval(gate.approvalId, true)}
                className="px-2.5 py-1 rounded bg-emerald-700 hover:bg-emerald-600 text-white"
              >
                Approve
              </button>
              <button
                type="button"
                onClick={() => onResolveApproval(gate.approvalId, false)}
                className="px-2.5 py-1 rounded bg-rose-800 hover:bg-rose-700 text-white"
              >
                Reject
              </button>
            </div>
          </div>
          <pre className="p-2 rounded bg-slate-950 text-slate-300 overflow-x-auto font-mono">{gate.argumentsJson}</pre>
        </div>
      ))}

      <div className="space-y-2">
        {activeTools.map((tool) => (
          <div key={tool.callId} className="p-2.5 rounded bg-slate-950 border border-slate-800 text-xs space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="font-mono text-indigo-300">{tool.toolName}</span>
              <span className="text-slate-400">
                {tool.stage} {tool.progressPct != null ? `(${Math.round(tool.progressPct)}%)` : ''}
              </span>
            </div>
            {tool.progressPct != null && (
              <div className="w-full h-1.5 rounded bg-slate-800 overflow-hidden">
                <div
                  className="h-full bg-indigo-500 transition-all duration-150"
                  style={{ width: `${Math.max(0, Math.min(100, tool.progressPct))}%` }}
                />
              </div>
            )}
            {tool.message && <p className="text-slate-400">{tool.message}</p>}
          </div>
        ))}
      </div>

      {streamingAssistantText && (
        <div className="p-3 rounded bg-slate-950 border border-slate-800 font-mono text-xs text-slate-200 whitespace-pre-wrap">
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
      <section aria-label="Verification & Diff Phase" className="space-y-3 p-4 rounded-lg border border-slate-800 bg-slate-900/50">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-slate-100">Phase 3 · Verification, Self-Repair &amp; Virtualized Diff</h2>
          <div className="flex gap-3 text-xs">
            <span className="text-emerald-400">Passed: {testsPassed}</span>
            <span className="text-rose-400">Failed: {testsFailed}</span>
            <span className="text-slate-400">Repair Budget: {repairAttempt}/{maxRepairAttempts}</span>
          </div>
        </div>

        <div
          onScroll={onScroll}
          style={{ height: 352 }}
          className="overflow-y-auto rounded border border-slate-800 bg-slate-950 font-mono text-xs"
        >
          <div style={{ paddingTop: windowSlice.topPaddingPx, paddingBottom: windowSlice.bottomPaddingPx }}>
            {visibleLines.map((line, idx) => {
              const absoluteIdx = windowSlice.startIndex + idx;
              const rowBg =
                line.type === 'add'
                  ? 'bg-emerald-950/35'
                  : line.type === 'del'
                    ? 'bg-rose-950/35'
                    : line.type === 'hunk'
                      ? 'bg-indigo-950/30'
                      : '';
              return (
                <div
                  key={absoluteIdx}
                  style={{ height: 22 }}
                  className={`flex items-center px-3 whitespace-pre ${rowBg}`}
                >
                  <span className="w-10 select-none text-right pr-2 text-slate-600">
                    {line.oldLineNumber ?? ''}
                  </span>
                  <span className="w-10 select-none text-right pr-3 text-slate-600">
                    {line.newLineNumber ?? ''}
                  </span>
                  <span className="w-4 select-none text-slate-500">
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
    <section aria-label="Publication Phase" className="space-y-3 p-4 rounded-lg border border-slate-800 bg-slate-900/50">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-100">Phase 4 · Host-Isolated Git Publication</h2>
          <p className="text-xs text-slate-400">
            Branch <code className="font-mono text-indigo-300">{branchName}</code> · Secrets scrubbed: {secretsRedactedCount}
          </p>
        </div>
        {!pullRequestUrl ? (
          <button
            type="button"
            onClick={onPublishPullRequest}
            className="px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-xs font-medium text-white"
          >
            Publish Pull Request
          </button>
        ) : (
          <a
            href={pullRequestUrl}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-indigo-400 underline"
          >
            View Pull Request ({commitSha?.slice(0, 7) ?? 'HEAD'})
          </a>
        )}
      </div>
    </section>
  ),
);
TaskPublicationPhasePanel.displayName = 'TaskPublicationPhasePanel';

import {
  CheckCircle2,
  ExternalLink,
  FileCode,
  FlaskConical,
  GitBranch,
  GitCommit,
  GitPullRequest,
  Pause,
  Play,
  ShieldCheck,
  Terminal,
  Wrench,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import { CodeChangesPanel } from '../tasks/CodeChangesPanel';
import { TestExecutionPanel } from '../tasks/TestExecutionPanel';
import { VerificationPanel } from '../tasks/VerificationPanel';
import type { PlanStep } from '../../types/task';

export interface RepositoryTaskPlanTabProps {
  taskDetail: any;
  latestPlan: any;
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
              <CheckCircle2 className="h-4 w-4 text-emerald-400" />
              <span className="text-xs font-bold text-foreground">
                Plan v{latestPlan.plan_version} Ready for Approval
              </span>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setShowRevisionInput(!showRevisionInput)}
                className="text-xs text-muted-foreground hover:text-foreground underline cursor-pointer"
              >
                {showRevisionInput ? 'Hide Revision Notes' : 'Request Revision'}
              </button>
              <button
                type="button"
                onClick={() => setShowRejectionInput(!showRejectionInput)}
                className="text-xs text-rose-400 hover:text-rose-300 underline cursor-pointer"
              >
                {showRejectionInput ? 'Hide Rejection' : 'Reject'}
              </button>
            </div>
          </div>

          {showRevisionInput && (
            <div className="flex items-center gap-2 pt-2 border-t border-border/40">
              <input
                type="text"
                placeholder="Provide feedback to refine the plan..."
                value={revisionNotes}
                onChange={(e) => setRevisionNotes(e.target.value)}
                className="flex-1 px-3 py-1.5 text-xs rounded-lg border border-border bg-background text-foreground"
              />
              <button
                type="button"
                disabled={actionBusy !== null || !revisionNotes.trim()}
                onClick={handleGenerateOrRevisePlan}
                className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-card border border-border hover:bg-accent cursor-pointer"
              >
                Synthesize v{latestPlan.plan_version + 1}
              </button>
            </div>
          )}

          {showRejectionInput && (
            <div className="flex items-center gap-2 pt-2 border-t border-border/40">
              <input
                type="text"
                placeholder="Reason for rejecting plan..."
                value={rejectionReason}
                onChange={(e) => setRejectionReason(e.target.value)}
                className="flex-1 px-3 py-1.5 text-xs rounded-lg border border-rose-500/40 bg-background text-foreground"
              />
              <button
                type="button"
                disabled={actionBusy !== null}
                onClick={handleRejectPlan}
                className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-rose-600 text-white hover:bg-rose-500 cursor-pointer"
              >
                Reject Plan
              </button>
            </div>
          )}

          <div className="flex items-center gap-2.5 pt-1">
            <input
              type="text"
              placeholder="Optional approval comment..."
              value={approvalComment}
              onChange={(e) => setApprovalComment(e.target.value)}
              className="flex-1 px-3 py-1.5 text-xs rounded-lg border border-border bg-background text-foreground"
            />
            <button
              type="button"
              disabled={actionBusy !== null}
              onClick={handleApprovePlan}
              className="px-4 py-1.5 text-xs font-bold rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white transition-colors cursor-pointer"
            >
              Approve Plan
            </button>
          </div>
        </div>
      )}

      {latestPlan ? (
        <div className="rounded-xl border border-border bg-card p-4.5 space-y-4">
          <div className="space-y-1">
            <div className="text-[11px] font-mono uppercase text-primary font-bold">
              AI Implementation Plan (v{latestPlan.plan_version})
            </div>
            <p className="text-sm font-medium text-foreground leading-snug break-words">
              {latestPlan.summary}
            </p>
            {latestPlan.problem_statement && (
              <p className="text-xs text-muted-foreground break-words pt-1">
                {latestPlan.problem_statement}
              </p>
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
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[10px] text-primary font-bold px-1.5 py-0.5 rounded bg-primary/10">
                        Step {idx + 1}
                      </span>
                      <span className="font-mono text-[10px] uppercase font-bold text-muted-foreground px-1.5 py-0.5 rounded bg-muted">
                        {s.action_type || s.step_type || 'modify'}
                      </span>
                      <span className="font-semibold text-foreground">{s.description}</span>
                    </div>
                    {s.risk_level && (
                      <span
                        className={cn(
                          'px-2 py-0.5 rounded text-[10px] font-mono border uppercase font-semibold',
                          s.risk_level === 'low'
                            ? 'bg-blue-500/10 text-blue-400 border-blue-500/30'
                            : 'bg-amber-500/10 text-amber-400 border-amber-500/30'
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
                          className="px-1.5 py-0.2 rounded bg-background border border-border text-[10px]"
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
            className="px-3.5 py-1.5 rounded-lg bg-primary text-primary-foreground font-semibold text-xs cursor-pointer"
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
          <div className="text-[11px] font-mono uppercase text-rose-400 font-bold">
            Protected Safety Boundaries
          </div>
          <div className="space-y-1 text-xs text-muted-foreground">
            <p>Strictly shielded from modification:</p>
            <div className="flex items-center gap-1.5 font-mono text-[11px] text-rose-300 pt-1">
              <span className="px-2 py-0.5 rounded bg-rose-500/10 border border-rose-500/30">.env</span>
              <span className="px-2 py-0.5 rounded bg-rose-500/10 border border-rose-500/30">
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
  }) => (
    <div className="space-y-4 animate-in fade-in duration-150">
      {hasWorkspace && workspaceMeta ? (
        <div className="rounded-xl border border-indigo-500/30 bg-indigo-500/5 p-4.5 space-y-4">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-2">
              <Terminal className="h-4 w-4 text-indigo-400" />
              <h3 className="text-xs font-bold uppercase tracking-wider text-foreground">
                Isolated Sandbox Status
              </h3>
              <span className="px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 font-mono text-[10px]">
                {workspaceMeta.status}
              </span>
            </div>

            <div className="flex items-center gap-2">
              {workspaceMeta.status === 'IN_USE' && (
                <button
                  type="button"
                  disabled={actionBusy !== null}
                  onClick={handlePauseTask}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-amber-500/40 bg-amber-500/10 text-amber-300 text-xs font-medium hover:bg-amber-500/20 cursor-pointer"
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
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 text-emerald-300 text-xs font-medium hover:bg-emerald-500/20 cursor-pointer"
                >
                  <Play className="h-3 w-3" />
                  <span>Resume</span>
                </button>
              )}
              <button
                type="button"
                disabled={actionBusy !== null}
                onClick={handleCommitChanges}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-border bg-background text-foreground text-xs font-medium hover:bg-accent cursor-pointer"
              >
                <GitCommit className="h-3 w-3" />
                <span>Commit</span>
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
            <div className="p-2.5 rounded-lg bg-background/60 border border-border/60 space-y-1">
              <span className="text-[10px] font-mono text-muted-foreground uppercase">Isolated Branch</span>
              <div className="font-mono text-xs text-foreground font-semibold flex items-center gap-1.5">
                <GitBranch className="h-3.5 w-3.5 text-primary" />
                <span>{workspaceMeta.branch_name}</span>
              </div>
            </div>

            <div className="p-2.5 rounded-lg bg-background/60 border border-border/60 space-y-1">
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
              {latestPlan?.steps?.map((s: PlanStep, i: number) => (
                <div
                  key={s.step_id || i}
                  className="flex items-center justify-between text-xs py-1 px-2 rounded bg-muted/20"
                >
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                    <span className="font-semibold text-foreground">
                      Step {i + 1}: {s.description}
                    </span>
                  </div>
                  <span className="font-mono text-[10px] text-emerald-400 font-bold uppercase">
                    COMPLETED
                  </span>
                </div>
              ))}
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
            className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs cursor-pointer"
          >
            Start Workspace Execution
          </button>
        </div>
      )}
    </div>
  )
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

        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={actionBusy !== null}
            onClick={handleRunTests}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold cursor-pointer"
          >
            <FlaskConical className="h-3.5 w-3.5" />
            <span>Run Pytest</span>
          </button>

          <button
            type="button"
            disabled={actionBusy !== null || repairAttemptsUsed >= repairAttemptsMax}
            onClick={handleRunRepair}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-purple-500/40 bg-purple-500/10 text-purple-300 hover:bg-purple-500/20 text-xs font-semibold cursor-pointer disabled:opacity-40"
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
  currentRevision: string;
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
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-teal-600 hover:bg-teal-500 text-white text-xs font-semibold cursor-pointer"
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
        <div className="rounded-xl border border-purple-500/40 bg-purple-500/10 p-5 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <GitPullRequest className="h-5 w-5 text-purple-400" />
              <h3 className="text-sm font-bold text-foreground">
                Draft Pull Request #{draftPR.pr_number} Active
              </h3>
            </div>
            <a
              href={draftPR.pr_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-purple-600 hover:bg-purple-500 text-white text-xs font-semibold transition-colors"
            >
              <span>Open on GitHub</span>
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          </div>
          <p className="text-xs text-purple-200/90 leading-relaxed">
            The AI agent published this draft pull request to GitHub. Changes are verified and ready for review.
          </p>
          <div className="text-[11px] font-mono text-muted-foreground flex items-center gap-3 pt-1">
            <span>Branch: {draftPR.head_branch || draftPR.pr_id}</span>
            <span>→</span>
            <span>Target: {draftPR.base_branch}</span>
          </div>
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card p-5 space-y-4">
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-foreground">
              Publish GitHub Draft Pull Request
            </h3>
            <p className="text-xs text-muted-foreground pt-0.5">
              Push isolated task branch and open a review-ready Draft PR on GitHub.
            </p>
          </div>

          <div className="p-3.5 rounded-lg bg-muted/20 border border-border/60 space-y-2 text-xs">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-foreground">Verification Requirement</span>
              <span className="font-mono text-[10px] text-teal-400 font-bold uppercase">
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
              className="mt-0.5 rounded border-border text-primary focus:ring-primary/40"
            />
            <span>
              I authorize pushing the isolated task branch to remote GitHub and creating a Draft Pull Request.
            </span>
          </label>

          <button
            type="button"
            disabled={actionBusy !== null || !publicationAuthorized}
            onClick={handleCreateDraftPR}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-purple-600 hover:bg-purple-500 text-white text-xs font-bold shadow-md shadow-purple-600/20 disabled:opacity-40 cursor-pointer"
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
