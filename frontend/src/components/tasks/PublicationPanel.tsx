import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  GitPullRequestDraft,
  GitBranch,
  GitCommit,
  FolderGit2,
  ExternalLink,
  ShieldAlert,
  AlertTriangle,
  CheckCircle2,
  Lock,
  UploadCloud,
  Clock,
} from 'lucide-react';
import {
  useTaskPullRequest,
  usePublishDraftPR,
  useTaskVerification,
  useCheckStaleRevision,
  taskKeys,
} from '../../hooks/useTasks';
import { useRepository } from '../../hooks/useRepositories';
import { getTaskPullRequest } from '../../services/tasks';
import {
  TaskStatus,
  isPublicationEligible,
  type TaskDetailResponse,
  type WorkspaceMetadata,
  type TaskPullRequest,
  type VerificationResult,
} from '../../types/task';
import type { ApiError } from '../../types/api';
import { LoadingSpinner } from '../shared/LoadingSpinner';
import { cn } from '../../lib/utils';

export interface PublicationPanelProps {
  task: TaskDetailResponse;
  workspace?: WorkspaceMetadata | null;
  verification?: VerificationResult | null;
  baseBranch?: string;
  className?: string;
  onPublished?: (pr: TaskPullRequest) => void;
}

function formatDate(dateStr: string): string {
  try {
    return new Date(dateStr).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return dateStr;
  }
}

export function PublicationPanel({
  task,
  workspace,
  baseBranch: explicitBaseBranch,
  className,
  onPublished,
}: PublicationPanelProps) {
  const queryClient = useQueryClient();
  const { data: prData } = useTaskPullRequest(task.task_id, { repositoryId: task.repository_id });

  const {
    data: verification,
    isLoading: isVerificationLoading,
    isError: isVerificationError,
  } = useTaskVerification(task.task_id);

  const {
    data: staleCheck,
    isLoading: isStaleCheckLoading,
    isError: isStaleCheckError,
  } = useCheckStaleRevision(task.task_id);

  const {
    data: repository,
    isLoading: isRepoLoading,
  } = useRepository(task.repository_id);

  const publishMutation = usePublishDraftPR(task.task_id);

  const [authorizedChecked, setAuthorizedChecked] = useState(false);
  const [publishError, setPublishError] = useState<ApiError | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [publishedPR, setPublishedPR] = useState<TaskPullRequest | null>(null);

  const activePR = prData || publishedPR;

  // Canonical base branch resolution (no hardcoded 'main' assumption)
  const canonicalBaseBranch =
    explicitBaseBranch ||
    activePR?.base_branch ||
    (task as any).base_branch ||
    repository?.default_branch ||
    null;

  const baseBranch = canonicalBaseBranch;
  const targetRepo = repository?.full_name || repository?.name || null;
  const sourceBranch = workspace?.branch_name || null;
  const verifiedSha = verification?.verified_revision || null;

  // Stale revision evaluation: canonical backend stale check + workspace drift check
  const isStale = Boolean(
    staleCheck?.is_stale ||
    (verifiedSha && workspace?.base_revision && verifiedSha !== workspace.base_revision)
  );

  const isMetadataAvailable = Boolean(targetRepo && sourceBranch && baseBranch && verifiedSha);

  const eligible = isPublicationEligible({
    status: task.status,
    verification,
    isStale,
    isLoadingVerification: isVerificationLoading,
    hasVerificationError: isVerificationError,
    isStaleCheckLoading,
    hasStaleCheckError: isStaleCheckError,
    hasBranchMetadata: Boolean(sourceBranch && targetRepo),
    baseBranch,
  });

  const isPublishing =
    task.status === TaskStatus.PUBLISHING ||
    publishMutation.isPending ||
    isSubmitting;

  const isAlreadyPublished =
    task.status === TaskStatus.DRAFT_PR_CREATED ||
    Boolean(activePR);

  async function handlePublish() {
    if (!eligible || !authorizedChecked || isPublishing || !baseBranch || !sourceBranch) {
      return;
    }
    setPublishError(null);
    setIsSubmitting(true);
    try {
      const res = await publishMutation.mutateAsync({
        publication_authorized: true,
        title: `[AI Task] ${task.title}`,
        base_branch: baseBranch,
        target_repository: targetRepo || undefined,
      });
      if (res && res.pr_url) {
        const pr: TaskPullRequest = {
          task_id: task.task_id,
          pr_number: res.pr_number,
          pr_url: res.pr_url,
          title: `[AI Task] ${task.title}`,
          head_branch: res.head_branch || sourceBranch,
          base_branch: res.base_branch || baseBranch,
          is_draft: true,
          created_at: res.created_at || new Date().toISOString(),
          summary: res.summary,
        };
        queryClient.setQueryData(taskKeys.pullRequest(task.task_id), pr);
        setPublishedPR(pr);
        if (onPublished) {
          onPublished(pr);
        }
      } else {
        // Successful response without res.pr_url: treat as uncertain outcome and reconcile
        try {
          const existingPR = await getTaskPullRequest(task.task_id, task.repository_id);
          if (existingPR && existingPR.pr_url) {
            queryClient.setQueryData(taskKeys.pullRequest(task.task_id), existingPR);
            setPublishedPR(existingPR);
            queryClient.invalidateQueries({ queryKey: taskKeys.detail(task.task_id) });
            if (onPublished) {
              onPublished(existingPR);
            }
            return;
          }
        } catch {
          // Reconciliation failed
        }
        setPublishError({
          status_code: 500,
          error: 'Uncertain Publication Outcome',
          message: 'Publication request completed without returning a Pull Request URL, and reconciliation could not locate an existing Pull Request.',
        } as unknown as ApiError);
      }
    } catch (err) {
      // Uncertain network outcome: reconcile existing PR before prompting retry
      try {
        const existingPR = await getTaskPullRequest(task.task_id, task.repository_id);
        if (existingPR && existingPR.pr_url) {
          queryClient.setQueryData(taskKeys.pullRequest(task.task_id), existingPR);
          setPublishedPR(existingPR);
          queryClient.invalidateQueries({ queryKey: taskKeys.detail(task.task_id) });
          if (onPublished) {
            onPublished(existingPR);
          }
          return;
        }
      } catch {
        // Reconciliation failed, proceed to surface error
      }
      setPublishError(err as ApiError);
    } finally {
      setIsSubmitting(false);
    }
  }

  // When task is in READY_FOR_PUBLICATION, wait until initial verification data resolves
  const isInitialLoading =
    !isAlreadyPublished &&
    task.status === TaskStatus.READY_FOR_PUBLICATION &&
    isVerificationLoading &&
    !verification;

  if (isInitialLoading) {
    return (
      <div
        data-testid="publication-panel-loading"
        className={cn(
          'rounded-lg border border-border bg-card p-6 shadow-xs flex items-center justify-center min-h-[140px]',
          className
        )}
      >
        <LoadingSpinner size="md" label="Loading publication eligibility and verification state..." />
      </div>
    );
  }

  return (
    <div
      data-testid="publication-panel"
      className={cn(
        'rounded-lg border border-border bg-card p-6 shadow-xs space-y-6',
        className
      )}
    >
      {/* ------------------------------------------------------------------ */}
      {/* 1. Header with ADR-010 Compliance Notice                           */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-border pb-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2.5 flex-wrap">
            <h3 className="text-base font-semibold text-foreground flex items-center gap-2">
              <GitPullRequestDraft className="h-5 w-5 text-primary" />
              Publication Authorization & GitHub Draft PR
            </h3>

            <span className="font-mono text-[10px] bg-primary/10 text-primary border border-primary/20 px-2 py-0.5 rounded-full font-semibold">
              ADR-010 COMPLIANT
            </span>
          </div>

          <p className="text-xs text-muted-foreground leading-relaxed">
            Human approval of the implementation plan authorized local code changes. Pushing to GitHub and opening a pull request requires explicit publication authorization.
          </p>
        </div>

        {isAlreadyPublished && (
          <span
            data-testid="published-badge"
            className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-mono font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 shrink-0 self-start sm:self-auto"
          >
            <CheckCircle2 className="h-3.5 w-3.5" />
            DRAFT PR PUBLISHED
          </span>
        )}
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* 2. Published Draft PR Result View                                  */}
      {/* ------------------------------------------------------------------ */}
      {isAlreadyPublished && activePR ? (
        <div
          data-testid="draft-pr-card"
          className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-5 space-y-4"
        >
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div className="space-y-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-mono text-xs bg-muted text-foreground px-2 py-0.5 rounded border border-border">
                  #{activePR.pr_number || 'Draft'}
                </span>
                <span className="font-mono text-[11px] bg-emerald-500/10 text-emerald-300 border border-emerald-500/30 px-2 py-0.5 rounded-full font-semibold uppercase">
                  Draft Pull Request
                </span>
              </div>
              <h4 className="text-base font-semibold text-foreground">{activePR.title}</h4>
              {activePR.created_at && (
                <p className="text-xs text-muted-foreground flex items-center gap-1">
                  <Clock className="h-3 w-3 text-muted-foreground/70" />
                  <span>Created {formatDate(activePR.created_at)}</span>
                </p>
              )}
            </div>

            <a
              href={activePR.pr_url}
              target="_blank"
              rel="noopener noreferrer"
              data-testid="open-pr-link"
              className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors shadow-xs shrink-0 self-start sm:self-auto"
            >
              <span>View PR on GitHub</span>
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          </div>

          {/* Git Branch Details */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2 text-xs">
            <div className="p-3 rounded bg-background/60 border border-border space-y-1">
              <span className="text-[11px] text-muted-foreground flex items-center gap-1">
                <FolderGit2 className="h-3 w-3" /> Target Repository
              </span>
              <p className="font-mono font-medium text-foreground">{targetRepo}</p>
            </div>

            <div className="p-3 rounded bg-background/60 border border-border space-y-1">
              <span className="text-[11px] text-muted-foreground flex items-center gap-1">
                <GitBranch className="h-3 w-3" /> Head Branch
              </span>
              <p className="font-mono font-medium text-foreground">{activePR.head_branch || sourceBranch}</p>
            </div>

            <div className="p-3 rounded bg-background/60 border border-border space-y-1">
              <span className="text-[11px] text-muted-foreground flex items-center gap-1">
                <GitBranch className="h-3 w-3" /> Base Branch
              </span>
              <p className="font-mono font-medium text-foreground">{activePR.base_branch || baseBranch}</p>
            </div>
          </div>

          {/* ADR-010 Safety Guarantee Notice */}
          <div className="rounded p-3 bg-muted/40 border border-border text-[11px] text-muted-foreground space-y-1">
            <span className="font-semibold text-foreground flex items-center gap-1.5">
              <Lock className="h-3.5 w-3.5 text-primary" />
              ADR-010 Safety Guarantee
            </span>
            <p className="leading-relaxed">
              This pull request is unconditionally opened in Draft state (<code className="font-mono">draft: true</code>). Automated merging and production deployment are strictly prohibited by system policy.
            </p>
          </div>

          {activePR.summary && (
            <div className="p-3 rounded bg-background/40 border border-border/80 text-xs space-y-1">
              <span className="text-[11px] font-semibold uppercase text-muted-foreground tracking-wider">
                Generated PR Summary
              </span>
              <p className="text-foreground/90 whitespace-pre-wrap leading-relaxed">
                {activePR.summary}
              </p>
            </div>
          )}
        </div>
      ) : isPublishing ? (
        <div
          data-testid="publishing-state"
          className="rounded-lg border border-sky-500/30 bg-sky-500/10 p-8 text-center space-y-3"
        >
          <LoadingSpinner size="md" label="Publishing to GitHub..." />
          <h4 className="text-sm font-semibold text-sky-200">Publication in Progress</h4>
          <p className="text-xs text-sky-300/80 max-w-md mx-auto">
            Verifying commit signatures, pushing task branch <code className="font-mono text-sky-100">{sourceBranch}</code> to remote origin, and creating the GitHub Draft Pull Request...
          </p>
        </div>
      ) : (
        /* ---------------------------------------------------------------- */
        /* 3. Publication Authorization Gate Controls                       */
        /* ---------------------------------------------------------------- */
        <div className="space-y-6">
          {/* Target Git Metadata Table */}
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3 text-xs">
            <div className="p-3 rounded-md border border-border/80 bg-background/40 space-y-1">
              <span className="text-[11px] text-muted-foreground flex items-center gap-1">
                <FolderGit2 className="h-3 w-3" /> Target Repo
              </span>
              <p className="font-mono font-medium text-foreground truncate" data-testid="target-repo-display">
                {isRepoLoading ? (
                  <span className="text-muted-foreground italic font-sans flex items-center gap-1">
                    <LoadingSpinner size="sm" label="Loading repository metadata..." /> Loading...
                  </span>
                ) : targetRepo ? (
                  targetRepo
                ) : (
                  <span className="text-rose-400 italic font-sans">Unavailable</span>
                )}
              </p>
            </div>

            <div className="p-3 rounded-md border border-border/80 bg-background/40 space-y-1">
              <span className="text-[11px] text-muted-foreground flex items-center gap-1">
                <GitBranch className="h-3 w-3" /> Source Branch
              </span>
              <p className="font-mono font-medium text-foreground truncate">
                {sourceBranch || <span className="text-rose-400 italic font-sans">Unavailable</span>}
              </p>
            </div>

            <div className="p-3 rounded-md border border-border/80 bg-background/40 space-y-1">
              <span className="text-[11px] text-muted-foreground flex items-center gap-1">
                <GitBranch className="h-3 w-3" /> Base Branch
              </span>
              <p className="font-mono font-medium text-foreground truncate">
                {baseBranch || <span className="text-rose-400 italic font-sans">Unavailable</span>}
              </p>
            </div>

            <div className="p-3 rounded-md border border-border/80 bg-background/40 space-y-1">
              <span className="text-[11px] text-muted-foreground flex items-center gap-1">
                <GitCommit className="h-3 w-3" /> Verified Revision
              </span>
              <p className="font-mono font-medium text-foreground truncate">
                {verifiedSha ? verifiedSha.slice(0, 10) : <span className="text-rose-400 italic font-sans">Unavailable</span>}
              </p>
            </div>
          </div>

          {/* Missing Metadata Alert */}
          {!isMetadataAvailable && (
            <div
              data-testid="missing-metadata-alert"
              className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3.5 text-xs text-amber-200 flex items-center gap-2.5"
            >
              <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0" />
              <span>
                Publication is blocked: Required repository, branch, or verified revision metadata is unavailable.
              </span>
            </div>
          )}

          {/* Stale Revision Alert */}
          {isStale && (
            <div
              data-testid="stale-revision-alert"
              className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3.5 text-xs text-amber-200 flex items-center gap-2.5"
            >
              <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0" />
              <span>
                {`Publication is blocked: Workspace revision has drifted from the verified revision. ${staleCheck?.message || 'Re-run verification above before publishing.'}`}
              </span>
            </div>
          )}

          {/* Stale Check Error Alert */}
          {isStaleCheckError && (
            <div
              data-testid="stale-check-error-alert"
              className="rounded-md border border-rose-500/40 bg-rose-500/10 p-3.5 text-xs text-rose-200 flex items-center gap-2.5"
            >
              <AlertTriangle className="h-4 w-4 text-rose-400 shrink-0" />
              <span>
                Publication is blocked: Remote revision stale-check API failed. Server state cannot be verified.
              </span>
            </div>
          )}

          {/* Verification Error Alert */}
          {isVerificationError && (
            <div
              data-testid="verification-error-alert"
              className="rounded-md border border-rose-500/40 bg-rose-500/10 p-3.5 text-xs text-rose-200 flex items-center gap-2.5"
            >
              <ShieldAlert className="h-4 w-4 text-rose-400 shrink-0" />
              <span>
                Publication is blocked: Verification outcome check failed or is unavailable.
              </span>
            </div>
          )}

          {/* Blocking Findings Alert */}
          {verification?.blocking_findings && verification.blocking_findings.length > 0 && (
            <div
              data-testid="blocking-findings-alert"
              className="rounded-md border border-rose-500/40 bg-rose-500/10 p-3.5 text-xs text-rose-200 flex items-center gap-2.5"
            >
              <ShieldAlert className="h-4 w-4 text-rose-400 shrink-0" />
              <span>
                Publication is blocked: {verification.blocking_findings.length} blocking finding(s) exist in the verification report. Resolve them before publishing.
              </span>
            </div>
          )}

          {/* Publication Error Banner */}
          {publishError && (
            <div
              data-testid="publication-error-alert"
              className="rounded-md border border-rose-500/30 bg-rose-500/10 p-3.5 text-xs text-rose-200 flex items-center justify-between"
            >
              <div className="flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-rose-400 shrink-0" />
                <span>
                  {publishError.message || 'Failed to publish task branch to GitHub.'}
                </span>
              </div>
              <button
                type="button"
                onClick={() => setPublishError(null)}
                className="text-xs text-rose-400 hover:text-rose-200 underline ml-2 cursor-pointer"
              >
                Dismiss
              </button>
            </div>
          )}

          {/* Publication Authorization Form */}
          <div className="p-4 rounded-md border border-border/80 bg-background/30 space-y-4">
            <div className="flex items-start gap-3">
              <input
                type="checkbox"
                id="authorize-publication-checkbox"
                data-testid="authorize-publication-checkbox"
                checked={authorizedChecked}
                onChange={(e) => setAuthorizedChecked(e.target.checked)}
                disabled={!eligible || isPublishing || !isMetadataAvailable}
                className="mt-1 h-4 w-4 rounded border-border text-primary focus:ring-primary disabled:opacity-50 cursor-pointer"
              />
              <label
                htmlFor="authorize-publication-checkbox"
                className={cn(
                  'text-xs leading-relaxed select-none',
                  eligible && isMetadataAvailable ? 'text-foreground cursor-pointer' : 'text-muted-foreground opacity-60 cursor-not-allowed'
                )}
              >
                <span className="font-semibold">Explicit Human Publication Authorization</span>
                <p className="text-muted-foreground text-[11px] mt-0.5">
                  I have inspected the verified diff, test execution telemetry, and security checks. I explicitly authorize pushing branch{' '}
                  <code className="font-mono text-foreground font-semibold">{sourceBranch || 'Not allocated'}</code> to GitHub and opening a Draft Pull Request. Server authorization enforcement is independently validated before publication.
                </p>
              </label>
            </div>

            <div className="flex items-center justify-between pt-2 border-t border-border/50 flex-wrap gap-3">
              <div className="text-[11px] text-muted-foreground">
                {!eligible ? (
                  <span className="text-rose-400 flex items-center gap-1 font-medium">
                    <ShieldAlert className="h-3 w-3" /> Verification must pass before publication is unlocked.
                  </span>
                ) : !authorizedChecked ? (
                  <span>Check authorization above to unlock the publication trigger.</span>
                ) : (
                  <span className="text-emerald-400 flex items-center gap-1 font-medium">
                    <CheckCircle2 className="h-3 w-3" /> Publication authorization ready.
                  </span>
                )}
              </div>

              <button
                type="button"
                data-testid="authorize-publish-button"
                disabled={!eligible || !authorizedChecked || isPublishing || !isMetadataAvailable}
                onClick={handlePublish}
                className={cn(
                  'inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-md shadow-xs transition-colors cursor-pointer',
                  eligible && authorizedChecked && !isPublishing && isMetadataAvailable
                    ? 'bg-primary text-primary-foreground hover:bg-primary/90'
                    : 'bg-muted text-muted-foreground border border-border opacity-50 cursor-not-allowed'
                )}
              >
                {isPublishing ? (
                  <>
                    <LoadingSpinner size="sm" label="Publishing..." />
                    <span>Publishing to GitHub...</span>
                  </>
                ) : (
                  <>
                    <UploadCloud className="h-3.5 w-3.5" />
                    <span>Authorize & Publish Draft PR</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
