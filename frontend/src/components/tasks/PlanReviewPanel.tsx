import { useState } from 'react';
import {
  Brain,
  CheckCircle2,
  XCircle,
  RefreshCw,
  AlertCircle,
  ShieldAlert,
  GitCommit,
  Layers,
  FileCode2,
  ChevronDown,
  ChevronUp,
  FileCheck,
} from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import {
  useTaskPlan,
  useApprovePlan,
  useRejectPlan,
  useGeneratePlan,
  taskKeys,
} from '../../hooks/useTasks';
import { TaskStatus, type TaskDetailResponse, type PlanStep } from '../../types/task';
import { LoadingSpinner } from '../shared/LoadingSpinner';
import { ErrorMessage } from '../shared/ErrorMessage';
import { cn } from '../../lib/utils';
import type { ApiError } from '../../types/api';

export interface PlanReviewPanelProps {
  task: TaskDetailResponse;
  className?: string;
}

export function PlanReviewPanel({ task, className }: PlanReviewPanelProps) {
  const queryClient = useQueryClient();

  // Active or versioned plan query
  const {
    data: plan,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useTaskPlan(task.task_id, task.plan_version);

  // Approval & Rejection mutations
  const approveMutation = useApprovePlan(task.task_id);
  const rejectMutation = useRejectPlan(task.task_id);
  const generatePlanMutation = useGeneratePlan(task.task_id);

  // Approval/Rejection input state
  const [approvalNotes, setApprovalNotes] = useState('');
  const [rejectionReason, setRejectionReason] = useState('');
  const [isRejectOpen, setIsRejectOpen] = useState(false);
  const [isReviseOpen, setIsReviseOpen] = useState(false);
  const [reviseInstructions, setReviseInstructions] = useState('');

  // Version mismatch alert state
  const [versionMismatchAlert, setVersionMismatchAlert] = useState<string | null>(null);

  // Check if current task state allows approval/rejection
  const canApproveOrReject = task.status === TaskStatus.PENDING_APPROVAL;

  // Handle plan approval
  async function handleApprove() {
    if (!plan || !canApproveOrReject) return;
    setVersionMismatchAlert(null);
    rejectMutation.reset();
    generatePlanMutation.reset();

    try {
      await approveMutation.mutateAsync({
        plan_version: plan.plan_version,
        notes: approvalNotes.trim() || undefined,
      });
      setApprovalNotes('');
    } catch (err: unknown) {
      const apiErr = err as ApiError;
      if (apiErr.code === 'PLAN_VERSION_MISMATCH' || (!apiErr.code && apiErr.status === 409)) {
        setVersionMismatchAlert(
          apiErr.message ||
            'The plan has been revised. Please refresh the page and review the updated plan version.'
        );
      }
    }
  }

  // Handle plan rejection
  async function handleReject() {
    if (!plan || !canApproveOrReject) return;
    setVersionMismatchAlert(null);
    approveMutation.reset();
    generatePlanMutation.reset();

    try {
      await rejectMutation.mutateAsync({
        plan_version: plan.plan_version,
        reason: rejectionReason.trim() || undefined,
      });
      setRejectionReason('');
      setIsRejectOpen(false);
    } catch (err: unknown) {
      const apiErr = err as ApiError;
      if (apiErr.code === 'PLAN_VERSION_MISMATCH' || (!apiErr.code && apiErr.status === 409)) {
        setVersionMismatchAlert(
          apiErr.message ||
            'The plan has been revised. Please refresh the page and review the updated plan version.'
        );
      }
    }
  }

  // Handle plan revision / re-generation
  async function handleRevise() {
    setVersionMismatchAlert(null);
    approveMutation.reset();
    rejectMutation.reset();

    try {
      await generatePlanMutation.mutateAsync({
        regenerate: true,
        prompt_instructions: reviseInstructions.trim() || undefined,
      });
      setReviseInstructions('');
      setIsReviseOpen(false);
    } catch {
      // Error handled by mutation
    }
  }

  // Handle refresh action
  function handleRefreshPlan() {
    setVersionMismatchAlert(null);
    queryClient.invalidateQueries({ queryKey: taskKeys.detail(task.task_id) });
    queryClient.invalidateQueries({ queryKey: taskKeys.plan(task.task_id) });
    refetch();
  }

  // --------------------------------------------------------------------------
  // Loading & Error States
  // --------------------------------------------------------------------------
  if (isLoading) {
    return (
      <div className={cn('rounded-lg border border-border bg-card p-8 text-center', className)}>
        <LoadingSpinner size="md" label="Loading implementation plan..." />
        <p className="mt-3 text-sm text-muted-foreground">Retrieving structured plan...</p>
      </div>
    );
  }

  if (isError || !plan) {
    return (
      <div className={cn('rounded-lg border border-border bg-card p-6 space-y-4', className)}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-foreground font-semibold">
            <Brain className="h-5 w-5 text-primary" />
            <span>Implementation Plan</span>
          </div>
          <span className="text-xs font-mono text-muted-foreground">Version 0</span>
        </div>

        {isError && error?.status !== 404 ? (
          <ErrorMessage error={error} />
        ) : (
          <div className="p-6 text-center border border-dashed border-border rounded-md bg-background/50 space-y-3">
            <Brain className="h-8 w-8 mx-auto text-muted-foreground/60" />
            <p className="text-sm font-medium text-foreground">No plan generated yet</p>
            <p className="text-xs text-muted-foreground max-w-md mx-auto">
              This task does not have an active implementation plan. Generate a plan with the AI Planner to initiate structured steps and validation strategies.
            </p>
            {generatePlanMutation.isError && (
              <div className="pt-1">
                <ErrorMessage error={generatePlanMutation.error} />
              </div>
            )}
            <div className="pt-2">
              <button
                type="button"
                onClick={() => {
                  setVersionMismatchAlert(null);
                  approveMutation.reset();
                  rejectMutation.reset();
                  generatePlanMutation.mutate({ regenerate: false });
                }}
                disabled={generatePlanMutation.isPending}
                className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                {generatePlanMutation.isPending ? (
                  <>
                    <LoadingSpinner size="sm" label="Synthesizing plan..." />
                    <span>Synthesizing Plan...</span>
                  </>
                ) : (
                  <>
                    <Brain className="h-4 w-4" />
                    <span>Generate Implementation Plan</span>
                  </>
                )}
              </button>
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className={cn('rounded-lg border border-border bg-card shadow-xs overflow-hidden', className)}>
      {/* ------------------------------------------------------------------ */}
      {/* 1. Plan Header                                                      */}
      {/* ------------------------------------------------------------------ */}
      <div className="p-5 border-b border-border bg-card flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5 flex-wrap">
            <div className="flex items-center gap-1.5 text-foreground font-semibold text-base">
              <Brain className="h-5 w-5 text-primary" />
              <span>Implementation Plan</span>
            </div>

            <span className="inline-flex items-center gap-1 font-mono text-xs font-semibold px-2.5 py-0.5 rounded-full border border-primary/20 bg-primary/10 text-primary">
              v{plan.plan_version}
            </span>

            <span
              className={cn(
                'inline-flex items-center gap-1 font-mono text-xs px-2.5 py-0.5 rounded-full border',
                plan.status === 'APPROVED'
                  ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                  : plan.status === 'REJECTED'
                  ? 'bg-rose-500/10 text-rose-400 border-rose-500/20'
                  : 'bg-amber-500/10 text-amber-400 border-amber-500/20'
              )}
            >
              {plan.status === 'APPROVED' && <CheckCircle2 className="h-3 w-3" />}
              {plan.status === 'REJECTED' && <XCircle className="h-3 w-3" />}
              {plan.status.replace(/_/g, ' ')}
            </span>
          </div>

          <p className="mt-1 text-xs text-muted-foreground flex items-center gap-2 flex-wrap">
            <span className="inline-flex items-center gap-1 font-mono">
              <GitCommit className="h-3 w-3 text-muted-foreground/70" />
              Base: {plan.base_revision || 'HEAD'}
            </span>
            {plan.approved_by && (
              <span>• Approved by {plan.approved_by}</span>
            )}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleRefreshPlan}
            disabled={isFetching}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs rounded border border-border text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
            title="Refresh plan"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', isFetching && 'animate-spin')} />
            <span className="hidden sm:inline">Refresh</span>
          </button>
        </div>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* 2. Concurrency / Version Mismatch Alert                            */}
      {/* ------------------------------------------------------------------ */}
      {versionMismatchAlert && (
        <div
          role="alert"
          className="m-5 rounded-md border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-400 space-y-2"
        >
          <div className="flex items-start gap-2">
            <AlertCircle className="h-5 w-5 shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold">Plan Version Mismatch</p>
              <p className="text-xs mt-0.5">{versionMismatchAlert}</p>
            </div>
          </div>
          <div className="flex justify-end pt-1">
            <button
              type="button"
              onClick={handleRefreshPlan}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded bg-amber-500 text-black hover:bg-amber-400 transition-colors"
            >
              <RefreshCw className="h-3 w-3" />
              Refresh Plan to Current Version
            </button>
          </div>
        </div>
      )}

      {/* Backend errors */}
      {(approveMutation.isError || rejectMutation.isError || generatePlanMutation.isError) && (
        <div className="m-5">
          <ErrorMessage
            error={approveMutation.error || rejectMutation.error || generatePlanMutation.error}
          />
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* 3. Plan Content & Details                                          */}
      {/* ------------------------------------------------------------------ */}
      <div className="p-5 space-y-6">
        {/* Plan Summary */}
        <div>
          <h4 className="text-xs font-semibold uppercase text-muted-foreground tracking-wider mb-1.5">
            Plan Summary
          </h4>
          <p className="text-sm text-foreground leading-relaxed bg-background/60 p-3.5 rounded-md border border-border/80">
            {plan.summary}
          </p>
        </div>

        {/* Problem Statement if available */}
        {plan.problem_statement && (
          <div>
            <h4 className="text-xs font-semibold uppercase text-muted-foreground tracking-wider mb-1.5">
              Problem Statement
            </h4>
            <p className="text-xs text-muted-foreground leading-relaxed bg-background/40 p-3 rounded-md border border-border/60">
              {plan.problem_statement}
            </p>
          </div>
        )}

        {/* Ordered Plan Steps */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h4 className="text-xs font-semibold uppercase text-muted-foreground tracking-wider flex items-center gap-1.5">
              <Layers className="h-4 w-4 text-primary" />
              Ordered Implementation Steps ({plan.steps.length})
            </h4>
          </div>

          <div className="space-y-3">
            {plan.steps.map((step: PlanStep, idx: number) => (
              <div
                key={step.step_id || idx}
                className="rounded-md border border-border/80 bg-background/40 p-4 space-y-2.5"
              >
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/50 pb-2">
                  <div className="flex items-center gap-2">
                    <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary/20 text-primary text-xs font-mono font-bold">
                      {idx + 1}
                    </span>
                    <span className="font-semibold text-sm text-foreground">
                      {step.title || step.step_id}
                    </span>
                  </div>

                  <div className="flex items-center gap-2">
                    {step.step_type && (
                      <span className="font-mono text-[10px] uppercase px-2 py-0.5 rounded border border-border bg-accent text-accent-foreground">
                        {step.step_type}
                      </span>
                    )}
                    {step.risk_level && (
                      <span
                        className={cn(
                          'text-[10px] uppercase font-mono px-1.5 py-0.5 rounded border',
                          step.risk_level === 'high' || step.risk_level === 'critical'
                            ? 'bg-rose-500/10 text-rose-400 border-rose-500/20'
                            : 'bg-muted text-muted-foreground border-border'
                        )}
                      >
                        {step.risk_level} risk
                      </span>
                    )}
                  </div>
                </div>

                <p className="text-xs text-foreground/90 leading-relaxed">{step.description}</p>

                {/* Expected files */}
                {step.expected_files && step.expected_files.length > 0 && (
                  <div className="flex items-center gap-2 text-xs flex-wrap pt-1">
                    <span className="text-muted-foreground text-[11px] font-medium flex items-center gap-1">
                      <FileCode2 className="h-3 w-3" /> Target files:
                    </span>
                    {step.expected_files.map((file) => (
                      <span
                        key={file}
                        className="font-mono text-[11px] bg-background px-1.5 py-0.5 rounded border border-border/80 text-foreground"
                      >
                        {file}
                      </span>
                    ))}
                  </div>
                )}

                {/* Verification criteria */}
                {step.verification && step.verification.length > 0 && (
                  <div className="flex items-start gap-1.5 text-xs text-muted-foreground pt-1">
                    <FileCheck className="h-3.5 w-3.5 text-emerald-400 shrink-0 mt-0.5" />
                    <span>Verification: {step.verification.join('; ')}</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Validation Strategy & Risks Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
          {/* Validation Strategy */}
          <div className="rounded-md border border-border/80 bg-background/40 p-4 space-y-2">
            <h4 className="text-xs font-semibold uppercase text-muted-foreground tracking-wider flex items-center gap-1.5">
              <FileCheck className="h-4 w-4 text-emerald-400" />
              Validation Strategy
            </h4>
            <div className="text-xs text-foreground/90 leading-relaxed">
              {typeof plan.validation_strategy === 'string' ? (
                <p>{plan.validation_strategy}</p>
              ) : (
                <div className="space-y-1.5">
                  {plan.validation_strategy.automated_tests?.length > 0 && (
                    <div>
                      <span className="font-medium text-muted-foreground">Automated Tests:</span>
                      <ul className="list-disc list-inside mt-0.5 space-y-0.5">
                        {plan.validation_strategy.automated_tests.map((t: string, i: number) => (
                          <li key={i} className="font-mono text-[11px]">{t}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {plan.validation_strategy.rollback_plan && (
                    <p className="text-muted-foreground mt-1">
                      <span className="font-medium">Rollback:</span> {plan.validation_strategy.rollback_plan}
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Risks & Mitigations */}
          <div className="rounded-md border border-border/80 bg-background/40 p-4 space-y-2">
            <h4 className="text-xs font-semibold uppercase text-muted-foreground tracking-wider flex items-center gap-1.5">
              <ShieldAlert className="h-4 w-4 text-amber-400" />
              Identified Risks
            </h4>
            {Array.isArray(plan.risks) && plan.risks.length > 0 ? (
              <ul className="text-xs space-y-1.5 list-disc list-inside text-foreground/90">
                {plan.risks.map((risk, i) => (
                  <li key={i}>
                    {typeof risk === 'string' ? risk : `${risk.description} (Mitigation: ${risk.mitigation})`}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-muted-foreground italic">No elevated risks identified.</p>
            )}
          </div>
        </div>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* 4. Plan Approval, Rejection & Revision Controls Gate              */}
      {/* STRICT CONSTRAINT: Disabled unless task.status === PENDING_APPROVAL*/}
      {/* NO Day 3+ execution triggers rendered here!                       */}
      {/* ------------------------------------------------------------------ */}
      <div className="p-5 border-t border-border bg-card/80 space-y-4">
        {/* Status explanation when not PENDING_APPROVAL */}
        {!canApproveOrReject && (
          <div className="rounded-md border border-border bg-muted/40 p-3 text-xs text-muted-foreground flex items-center gap-2">
            <AlertCircle className="h-4 w-4 shrink-0 text-muted-foreground/80" />
            <span>
              {task.status === TaskStatus.APPROVED
                ? 'This implementation plan has been approved by human reviewer.'
                : task.status === TaskStatus.REJECTED
                ? 'This plan was rejected. You can revise and regenerate the plan below.'
                : `Plan approval controls are inactive while task status is "${task.status}".`}
            </span>
          </div>
        )}

        {/* Approval notes input (shown when PENDING_APPROVAL) */}
        {canApproveOrReject && (
          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-foreground">
              Approval Notes (Optional)
            </label>
            <input
              type="text"
              placeholder="e.g. Approved. Proceed with AST depth cap implementation."
              value={approvalNotes}
              onChange={(e) => setApprovalNotes(e.target.value)}
              className="w-full py-1.5 px-3 text-xs bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>
        )}

        {/* Action Buttons Bar */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            {/* Revise / Regenerate Toggle */}
            <button
              type="button"
              onClick={() => setIsReviseOpen(!isReviseOpen)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-border bg-background text-foreground hover:bg-accent transition-colors"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              <span>Revise Plan</span>
              {isReviseOpen ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            </button>

            {/* Reject Plan Toggle (shown when pending) */}
            {canApproveOrReject && (
              <button
                type="button"
                onClick={() => setIsRejectOpen(!isRejectOpen)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-rose-500/30 text-rose-400 hover:bg-rose-500/10 transition-colors"
              >
                <XCircle className="h-3.5 w-3.5" />
                <span>Reject Plan</span>
              </button>
            )}
          </div>

          <div className="flex items-center gap-3">
            {/* Approve Button */}
            <button
              type="button"
              data-testid="approve-button"
              disabled={!canApproveOrReject || approveMutation.isPending}
              onClick={handleApprove}
              className={cn(
                'inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold rounded-md shadow-xs transition-colors',
                canApproveOrReject
                  ? 'bg-emerald-600 text-white hover:bg-emerald-500'
                  : 'bg-muted text-muted-foreground cursor-not-allowed opacity-50'
              )}
            >
              {approveMutation.isPending ? (
                <>
                  <LoadingSpinner size="sm" label="Approving plan..." />
                  <span>Approving (v{plan.plan_version})...</span>
                </>
              ) : (
                <>
                  <CheckCircle2 className="h-4 w-4" />
                  <span>Approve Plan (v{plan.plan_version})</span>
                </>
              )}
            </button>
          </div>
        </div>

        {/* Rejection Form Dropdown */}
        {isRejectOpen && canApproveOrReject && (
          <div className="rounded-md border border-rose-500/30 bg-rose-500/5 p-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-rose-400">Specify Rejection Reason</span>
              <button
                type="button"
                onClick={() => setIsRejectOpen(false)}
                className="text-xs text-muted-foreground hover:text-foreground"
              >
                Cancel
              </button>
            </div>
            <textarea
              rows={2}
              placeholder="e.g. Plan steps target forbidden grammar.py parser file."
              value={rejectionReason}
              onChange={(e) => setRejectionReason(e.target.value)}
              className="w-full py-1.5 px-3 text-xs bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            <div className="flex justify-end">
              <button
                type="button"
                data-testid="reject-button"
                disabled={rejectMutation.isPending}
                onClick={handleReject}
                className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold rounded-md bg-rose-600 text-white hover:bg-rose-500 transition-colors"
              >
                {rejectMutation.isPending ? (
                  <>
                    <LoadingSpinner size="sm" label="Rejecting plan..." />
                    <span>Rejecting...</span>
                  </>
                ) : (
                  <>
                    <XCircle className="h-3.5 w-3.5" />
                    <span>Confirm Rejection (v{plan.plan_version})</span>
                  </>
                )}
              </button>
            </div>
          </div>
        )}

        {/* Revise / Regenerate Form Dropdown */}
        {isReviseOpen && (
          <div className="rounded-md border border-primary/30 bg-primary/5 p-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-primary">
                Revise Plan Instructions (Increments Plan to v{plan.plan_version + 1})
              </span>
              <button
                type="button"
                onClick={() => setIsReviseOpen(false)}
                className="text-xs text-muted-foreground hover:text-foreground"
              >
                Cancel
              </button>
            </div>
            <textarea
              rows={2}
              placeholder="e.g. Add explicit unit tests for negative token depth limits and summarize private helper exports."
              value={reviseInstructions}
              onChange={(e) => setReviseInstructions(e.target.value)}
              className="w-full py-1.5 px-3 text-xs bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            <div className="flex items-center justify-between pt-1">
              <p className="text-[11px] text-muted-foreground">
                Revising increments plan_version and invalidates any previous approval.
              </p>
              <button
                type="button"
                disabled={generatePlanMutation.isPending}
                onClick={handleRevise}
                className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
              >
                {generatePlanMutation.isPending ? (
                  <>
                    <LoadingSpinner size="sm" label="Synthesizing..." />
                    <span>Generating v{plan.plan_version + 1}...</span>
                  </>
                ) : (
                  <>
                    <Brain className="h-3.5 w-3.5" />
                    <span>Synthesize Revised Plan (v{plan.plan_version + 1})</span>
                  </>
                )}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
