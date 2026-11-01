/**
 * CreateIssueModal — Week 3 Day 1 (F31) Modal for creating a GitHub Issue & Task
 * directly from an approved Bug Detection finding (`BugScannerView`) or AI Code Review finding (`CodeReviewView`).
 *
 * Owner: Dhramraj — Week 3 Day 1 Deliverable (Docs/daily_tasks.md & Docs/week3.md §6 F31)
 */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertCircle,
  CheckCircle2,
  ExternalLink,
  GitPullRequestDraft,
  Loader2,
  PlusCircle,
  Sparkles,
  Tag,
  X,
} from 'lucide-react';
import { createGitHubIssue } from '../../services/tasks';
import type { IssueImportResponse } from '../../types/task';
import type { SourceReference } from '../../types/analysis';

export interface FindingForIssue {
  id: string;
  title: string;
  description: string;
  severity: string;
  category: string;
  evidence?: string | null;
  suggested_fix?: string | null;
  rule_id?: string | null;
  source_reference?: SourceReference | null;
}

export interface CreateIssueModalProps {
  isOpen: boolean;
  onClose: () => void;
  repositoryId: string;
  finding: FindingForIssue | null;
  sourceType?: 'BUG_FINDING' | 'REVIEW_FINDING';
  onCreated?: (result: IssueImportResponse) => void;
}

function buildDefaultIssueBody(finding: FindingForIssue): string {
  const filePath = finding.source_reference?.file_path ?? 'unknown';
  const startLine = finding.source_reference?.start_line;
  const endLine = finding.source_reference?.end_line;
  const lineRange =
    typeof startLine === 'number'
      ? ` (Lines ${startLine}–${endLine ?? startLine})`
      : '';

  const lines: string[] = [
    '## Automated Developer Intelligence Finding',
    `- **Finding ID:** \`${finding.id}\``,
    `- **Severity:** \`${finding.severity}\``,
    `- **Category:** \`${finding.category}\``,
    `- **Location:** \`${filePath}\`${lineRange}`,
  ];
  if (finding.rule_id) {
    lines.push(`- **Rule ID:** \`${finding.rule_id}\``);
  }
  lines.push('', '### Description', finding.description);

  if (finding.evidence) {
    lines.push('', '### Supporting Evidence', '```', finding.evidence, '```');
  }
  if (finding.suggested_fix) {
    lines.push('', '### Suggested Remediation', '```', finding.suggested_fix, '```');
  }
  return lines.join('\n');
}

export function CreateIssueModal({
  isOpen,
  onClose,
  repositoryId,
  finding,
  onCreated,
}: CreateIssueModalProps) {
  const navigate = useNavigate();

  const defaultTitle = finding
    ? `[${finding.severity}] ${finding.title}`
    : '';
  const defaultBody = finding ? buildDefaultIssueBody(finding) : '';
  const defaultLabels = finding
    ? [
        'ai-finding',
        finding.category.toLowerCase().includes('security') ? 'security' : 'bug',
        `severity:${finding.severity.toLowerCase()}`,
      ].join(', ')
    : 'bug, ai-finding';

  const [title, setTitle] = useState(defaultTitle);
  const [body, setBody] = useState(defaultBody);
  const [labelsInput, setLabelsInput] = useState(defaultLabels);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [createdResult, setCreatedResult] = useState<IssueImportResponse | null>(null);

  if (!isOpen || !finding) return null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!finding || isSubmitting) return;

    const cleanTitle = title.trim() || defaultTitle;
    if (cleanTitle.length < 3) {
      setErrorMessage('Issue title must be at least 3 characters.');
      return;
    }

    const parsedLabels = labelsInput
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);

    setIsSubmitting(true);
    setErrorMessage(null);

    try {
      const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
      const validFindingUuid = uuidRegex.test(finding.id) ? finding.id : undefined;

      const res = await createGitHubIssue(repositoryId, {
        finding_id: validFindingUuid,
        title: cleanTitle,
        body: body.trim() || defaultBody,
        labels: parsedLabels,
        create_task: true,
      });
      setCreatedResult(res);
      onCreated?.(res);
    } catch (err: any) {
      setErrorMessage(
        err?.message || 'Failed to create GitHub issue from finding.'
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Create GitHub Issue from Finding"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-background/80 backdrop-blur-xs animate-in fade-in duration-150"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded-xl border border-border bg-card shadow-2xl overflow-hidden flex flex-col max-h-[85vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-5 py-3.5 border-b border-border flex items-center justify-between bg-muted/20">
          <div className="flex items-center gap-2">
            <div className="h-7 w-7 rounded-lg bg-primary/15 border border-primary/30 flex items-center justify-center text-primary">
              <PlusCircle className="h-4 w-4" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-foreground">
                Create GitHub Issue & Development Task
              </h3>
              <p className="text-[11px] text-muted-foreground font-mono">
                Source Finding: {finding.source_reference?.file_path ?? 'Repository Finding'}
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground p-1 rounded-md"
            aria-label="Close modal"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        {createdResult ? (
          <div className="p-6 space-y-4">
            <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4 flex items-start gap-3">
              <CheckCircle2 className="h-5 w-5 text-emerald-400 shrink-0 mt-0.5" />
              <div className="space-y-1 text-xs">
                <h4 className="font-semibold text-emerald-300 text-sm">
                  GitHub Issue #{createdResult.issue?.issue_number} & Task Created
                </h4>
                <p className="text-muted-foreground">
                  The finding has been published as an issue and normalized into task{' '}
                  <span className="font-mono text-foreground">
                    {createdResult.task_id.slice(0, 8)}
                  </span>{' '}
                  ({createdResult.status}).
                </p>
              </div>
            </div>

            <div className="flex items-center justify-between gap-3 pt-2">
              {createdResult.issue?.html_url && (
                <a
                  href={createdResult.issue.html_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 text-xs font-mono text-primary hover:underline"
                >
                  <span>View Issue #{createdResult.issue.issue_number} on GitHub</span>
                  <ExternalLink className="h-3.5 w-3.5" />
                </a>
              )}

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-3 py-1.5 rounded-lg border border-border bg-background text-xs font-medium text-foreground hover:bg-accent"
                >
                  Done
                </button>
                <button
                  type="button"
                  onClick={() => {
                    onClose();
                    navigate(
                      `/app/repositories/${repositoryId}/tasks?taskId=${createdResult.task_id}`
                    );
                  }}
                  className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-primary text-primary-foreground text-xs font-semibold hover:bg-primary/90"
                >
                  <GitPullRequestDraft className="h-3.5 w-3.5" />
                  <span>Open in Task Planner Studio</span>
                </button>
              </div>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="p-5 space-y-4 overflow-y-auto">
            {errorMessage && (
              <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-xs text-destructive flex items-start gap-2">
                <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                <span>{errorMessage}</span>
              </div>
            )}

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-foreground block">
                Issue Title
              </label>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
                className="w-full px-3 py-2 text-xs rounded-lg border border-border bg-background text-foreground focus:outline-none focus:border-primary font-mono"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                <Tag className="h-3.5 w-3.5 text-primary" />
                <span>Labels (comma-separated)</span>
              </label>
              <input
                type="text"
                value={labelsInput}
                onChange={(e) => setLabelsInput(e.target.value)}
                className="w-full px-3 py-1.5 text-xs rounded-lg border border-border bg-background text-foreground focus:outline-none focus:border-primary font-mono"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-foreground block">
                Issue Description & Evidence (Markdown)
              </label>
              <textarea
                rows={9}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                className="w-full px-3 py-2 text-xs rounded-lg border border-border bg-background text-foreground focus:outline-none focus:border-primary font-mono leading-relaxed"
              />
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-border">
              <button
                type="button"
                onClick={onClose}
                className="px-3 py-1.5 rounded-lg border border-border bg-background text-xs font-medium text-muted-foreground hover:text-foreground"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isSubmitting}
                className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-primary text-primary-foreground text-xs font-semibold hover:bg-primary/90 disabled:opacity-50"
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    <span>Creating Issue & Task…</span>
                  </>
                ) : (
                  <>
                    <Sparkles className="h-3.5 w-3.5" />
                    <span>Create Issue & Task</span>
                  </>
                )}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
