import { useState } from 'react';
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
} from '../../hooks/useTasks';
import {
  TaskStatus,
  isPublicationEligible,
  type TaskDetailResponse,
  type WorkspaceMetadata,
  type TaskPullRequest,
} from '../../types/task';
import type { ApiError } from '../../types/api';
import { LoadingSpinner } from '../shared/LoadingSpinner';
import { cn } from '../../lib/utils';

export interface PublicationPanelProps {
  task: TaskDetailResponse;
  workspace?: WorkspaceMetadata | null;
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
  className,
  onPublished,
}: PublicationPanelProps) {
  const { data: prData } = useTaskPullRequest(task.task_id);

  const { data: verification } = useTaskVerification(task.task_id);
  const publishMutation = usePublishDraftPR(task.task_id);

  const [authorizedChecked, setAuthorizedChecked] = useState(false);
  const [publishError, setPublishError] = useState<ApiError | null>(null);

  const isStale = Boolean(
    verification?.verified_revision &&
    workspace?.base_revision &&
    verification.verified_revision !== workspace.base_revision
  );

  const eligible = isPublicationEligible(task.status, verification, isStale);
  const isPublishing = task.status === TaskStatus.PUBLISHING || publishMutation.isPending;
  const isAlreadyPublished = task.status === TaskStatus.DRAFT_PR_CREATED || Boolean(prData);

  const targetRepo = task.repository_id;
  const sourceBranch = workspace?.branch_name || 'Not allocated';
  const baseBranch = 'main';
  const verifiedSha = verification?.verified_revision || workspace?.base_revision || task.base_revision;

  async function handlePublish() {
    if (!eligible || !authorizedChecked || isPublishing) {
      return;
    }
    setPublishError(null);
    try {
      const res = await publishMutation.mutateAsync({
        publication_authorized: true,
        title: `[AI Task] ${task.title}`,
        base_branch: baseBranch,
      });
      if (res.pr_url && onPublished) {
        onPublished({
          task_id: task.task_id,
          pr_number: res.pr_number,
          pr_url: res.pr_url,
          title: `[AI Task] ${task.title}`,
          head_branch: res.head_branch || sourceBranch,
          base_branch: res.base_branch || baseBranch,
          is_draft: true,
          created_at: res.created_at,
          summary: res.summary,
        });
      }
    } catch (err) {
      setPublishError(err as ApiError);
    }
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
      {isAlreadyPublished && prData ? (
        <div
          data-testid="draft-pr-card"
          className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-5 space-y-4"
        >
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div className="space-y-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-mono text-xs bg-muted text-foreground px-2 py-0.5 rounded border border-border">
                  #{prData.pr_number || 'Draft'}
                </span>
                <span className="font-mono text-[11px] bg-emerald-500/10 text-emerald-300 border border-emerald-500/30 px-2 py-0.5 rounded-full font-semibold uppercase">
                  Draft Pull Request
                </span>
              </div>
              <h4 className="text-base font-semibold text-foreground">{prData.title}</h4>
              {prData.created_at && (
                <p className="text-xs text-muted-foreground flex items-center gap-1">
                  <Clock className="h-3 w-3 text-muted-foreground/70" />
                  <span>Created {formatDate(prData.created_at)}</span>
                </p>
              )}
            </div>

            <a
              href={prData.pr_url}
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
              <p className="font-mono font-medium text-foreground">{prData.head_branch}</p>
            </div>

            <div className="p-3 rounded bg-background/60 border border-border space-y-1">
              <span className="text-[11px] text-muted-foreground flex items-center gap-1">
                <GitBranch className="h-3 w-3" /> Base Branch
              </span>
              <p className="font-mono font-medium text-foreground">{prData.base_branch}</p>
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

          {prData.summary && (
            <div className="p-3 rounded bg-background/40 border border-border/80 text-xs space-y-1">
              <span className="text-[11px] font-semibold uppercase text-muted-foreground tracking-wider">
                Generated PR Summary
              </span>
              <p className="text-foreground/90 whitespace-pre-wrap leading-relaxed">
                {prData.summary}
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
              <p className="font-mono font-medium text-foreground truncate">{targetRepo}</p>
            </div>

            <div className="p-3 rounded-md border border-border/80 bg-background/40 space-y-1">
              <span className="text-[11px] text-muted-foreground flex items-center gap-1">
                <GitBranch className="h-3 w-3" /> Source Branch
              </span>
              <p className="font-mono font-medium text-foreground truncate">{sourceBranch}</p>
            </div>

            <div className="p-3 rounded-md border border-border/80 bg-background/40 space-y-1">
              <span className="text-[11px] text-muted-foreground flex items-center gap-1">
                <GitBranch className="h-3 w-3" /> Base Branch
              </span>
              <p className="font-mono font-medium text-foreground truncate">{baseBranch}</p>
            </div>

            <div className="p-3 rounded-md border border-border/80 bg-background/40 space-y-1">
              <span className="text-[11px] text-muted-foreground flex items-center gap-1">
                <GitCommit className="h-3 w-3" /> Verified Revision
              </span>
              <p className="font-mono font-medium text-foreground truncate">
                {verifiedSha ? verifiedSha.slice(0, 10) : 'Not Verified'}
              </p>
            </div>
          </div>

          {/* Stale Revision Alert */}
          {isStale && (
            <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3.5 text-xs text-amber-200 flex items-center gap-2.5">
              <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0" />
              <span>
                Publication is blocked: Workspace revision has drifted from the verified revision. Re-run verification above before publishing.
              </span>
            </div>
          )}

          {/* Blocking Findings Alert */}
          {verification?.blocking_findings && verification.blocking_findings.length > 0 && (
            <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-3.5 text-xs text-rose-200 flex items-center gap-2.5">
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
                disabled={!eligible || isPublishing}
                className="mt-1 h-4 w-4 rounded border-border text-primary focus:ring-primary disabled:opacity-50 cursor-pointer"
              />
              <label
                htmlFor="authorize-publication-checkbox"
                className={cn(
                  'text-xs leading-relaxed select-none',
                  eligible ? 'text-foreground cursor-pointer' : 'text-muted-foreground opacity-60 cursor-not-allowed'
                )}
              >
                <span className="font-semibold">Explicit Human Publication Authorization</span>
                <p className="text-muted-foreground text-[11px] mt-0.5">
                  I have inspected the verified diff, test execution telemetry, and security checks. I explicitly authorize pushing branch{' '}
                  <code className="font-mono text-foreground font-semibold">{sourceBranch}</code> to GitHub and opening a Draft Pull Request. I understand automated merging is strictly forbidden.
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
                disabled={!eligible || !authorizedChecked || isPublishing}
                onClick={handlePublish}
                className={cn(
                  'inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-md shadow-xs transition-colors cursor-pointer',
                  eligible && authorizedChecked && !isPublishing
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
