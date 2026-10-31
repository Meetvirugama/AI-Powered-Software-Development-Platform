/**
 * RepositoryTaskStudio — Week 3 Day 1 & Day 2 Studio UI:
 * - F31 GitHub Issue Import & Issue List
 * - F32 Task Intake (segregated Requirements, Assumptions, Protected-File Constraints)
 * - F32 Structured Implementation Plan Viewer (steps, dependencies, files, tests, validation, risks, budget)
 * - F32 Human Approval Gate (Approve Plan vN, Reject Plan with reason, Revise Plan with notes, Execute Approved Plan)
 * - F38 Ordered Task Execution Timeline & Audit History
 *
 * Owner: Dhramraj — Week 3 Day 1–2 Deliverable (Docs/week3.md §6 F31, F32, F38)
 */

import { useState, useEffect, useCallback } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  ExternalLink,
  FileCode,
  GitBranch,
  GitPullRequestDraft,
  History,
  ListChecks,
  Loader2,
  Play,
  Plus,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  XCircle,
} from 'lucide-react';
import { cn } from '../lib/utils';
import {
  approveTaskPlan,
  createTask,
  executeApprovedTask,
  generateTaskPlan,
  getTaskDetail,
  getTaskEvents,
  importGitHubIssue,
  listTasks,
  rejectTaskPlan,
} from '../services/tasks';
import type {
  PlanStep,
  TaskDetail,
  TaskEvent,
  TaskSummary,
} from '../types/task';

const STATUS_BADGE_MAP: Record<
  string,
  { label: string; className: string }
> = {
  CREATED: {
    label: 'Created',
    className: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
  },
  PLANNING: {
    label: 'Planning…',
    className: 'bg-blue-500/15 text-blue-300 border-blue-500/30',
  },
  PENDING_APPROVAL: {
    label: 'Pending Approval',
    className: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
  },
  APPROVED: {
    label: 'Approved',
    className: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40',
  },
  REJECTED: {
    label: 'Rejected',
    className: 'bg-rose-500/15 text-rose-300 border-rose-500/40',
  },
  WORKSPACE_SETUP: {
    label: 'Workspace Setup',
    className: 'bg-indigo-500/15 text-indigo-300 border-indigo-500/40',
  },
  EXECUTING: {
    label: 'Executing',
    className: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/40',
  },
  DRAFT_PR_CREATED: {
    label: 'Draft PR Created',
    className: 'bg-purple-500/15 text-purple-300 border-purple-500/40',
  },
};

const RISK_BADGE_MAP: Record<string, string> = {
  low: 'bg-blue-500/10 text-blue-400 border-blue-500/30',
  medium: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  high: 'bg-orange-500/15 text-orange-400 border-orange-500/30',
  critical: 'bg-rose-500/15 text-rose-400 border-rose-500/30',
};

export function RepositoryTaskStudio() {
  const { id } = useParams<{ id: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const repoId = id ?? '';

  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(
    searchParams.get('taskId')
  );
  const [taskDetail, setTaskDetail] = useState<TaskDetail | null>(null);
  const [events, setEvents] = useState<TaskEvent[]>([]);

  const [loadingList, setLoadingList] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);

  // Import GitHub Issue state
  const [issueNumberInput, setIssueNumberInput] = useState('');
  const [showNewTaskForm, setShowNewTaskForm] = useState(false);
  const [newTaskTitle, setNewTaskTitle] = useState('');
  const [newTaskDesc, setNewTaskDesc] = useState('');
  const [newTaskFiles, setNewTaskFiles] = useState('');
  const [newTaskForbidden, setNewTaskForbidden] = useState('.env, .github/workflows/deploy.yml');

  // Approval / Rejection / Revision inputs
  const [approvalComment, setApprovalComment] = useState('');
  const [rejectionReason, setRejectionReason] = useState('');
  const [revisionNotes, setRevisionNotes] = useState('');

  const fetchTasks = useCallback(async () => {
    if (!repoId) return;
    setLoadingList(true);
    try {
      const res = await listTasks({ repository_id: repoId, page_size: 50 });
      setTasks(res.items);
      if (!selectedTaskId && res.items.length > 0) {
        setSelectedTaskId(res.items[0].task_id);
      }
    } catch (err: any) {
      setErrorBanner(err?.message || 'Failed to load repository tasks.');
    } finally {
      setLoadingList(false);
    }
  }, [repoId, selectedTaskId]);

  const fetchTaskDetailAndEvents = useCallback(async (taskId: string) => {
    setLoadingDetail(true);
    try {
      const [detail, evtList] = await Promise.all([
        getTaskDetail(taskId),
        getTaskEvents(taskId),
      ]);
      setTaskDetail(detail);
      setEvents(Array.isArray(evtList) ? evtList : (evtList as any)?.items || []);
    } catch (err: any) {
      setErrorBanner(err?.message || 'Failed to load task details.');
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  useEffect(() => {
    fetchTasks();
  }, [fetchTasks]);

  useEffect(() => {
    if (selectedTaskId) {
      setSearchParams({ taskId: selectedTaskId }, { replace: true });
      fetchTaskDetailAndEvents(selectedTaskId);
    } else {
      setTaskDetail(null);
      setEvents([]);
    }
  }, [selectedTaskId, fetchTaskDetailAndEvents, setSearchParams]);

  async function handleImportIssue(e: React.FormEvent) {
    e.preventDefault();
    const num = parseInt(issueNumberInput.trim(), 10);
    if (isNaN(num) || num < 1) {
      setErrorBanner('Enter a valid positive GitHub issue number.');
      return;
    }
    setActionBusy('import');
    setErrorBanner(null);
    try {
      const res = await importGitHubIssue(repoId, {
        issue_number: num,
        title: `GitHub Issue #${num}`,
      });
      setIssueNumberInput('');
      await fetchTasks();
      setSelectedTaskId(res.task_id);
    } catch (err: any) {
      setErrorBanner(err?.message || `Failed to import issue #${num}.`);
    } finally {
      setActionBusy(null);
    }
  }

  async function handleCreateNewTask(e: React.FormEvent) {
    e.preventDefault();
    if (!newTaskTitle.trim() || !newTaskDesc.trim()) return;

    const targetFiles = newTaskFiles
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    const forbiddenFiles = newTaskForbidden
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);

    setActionBusy('create');
    setErrorBanner(null);
    try {
      const created = await createTask({
        repository_id: repoId,
        title: newTaskTitle.trim(),
        description: newTaskDesc.trim(),
        source: { type: 'USER_PROMPT', repository_id: repoId },
        requirements: [
          {
            id: 'req-1',
            description: newTaskDesc.trim(),
            category: 'functional',
            target_files: targetFiles,
            acceptance_criteria: [
              'All target changes implemented cleanly.',
              'Existing and new unit tests pass.',
            ],
          },
        ],
        assumptions: [
          {
            id: 'asm-1',
            description: 'Isolated workspace will branch from default branch HEAD.',
            unresolved: false,
            risk_level: 'low',
          },
        ],
        constraints: [
          {
            id: 'cst-1',
            description: 'Protected files must not be modified.',
            constraint_type: 'protected_file',
            forbidden_files: forbiddenFiles,
            forbidden_packages: [],
            max_budget_tokens: 20000,
          },
        ],
      });
      setShowNewTaskForm(false);
      setNewTaskTitle('');
      setNewTaskDesc('');
      setNewTaskFiles('');
      await fetchTasks();
      setSelectedTaskId(created.task_id);
    } catch (err: any) {
      setErrorBanner(err?.message || 'Failed to create task.');
    } finally {
      setActionBusy(null);
    }
  }

  async function handleGenerateOrRevisePlan() {
    if (!taskDetail) return;
    setActionBusy('plan');
    setErrorBanner(null);
    try {
      await generateTaskPlan(taskDetail.task_id, {
        revision_notes: revisionNotes.trim() || undefined,
      });
      setRevisionNotes('');
      await fetchTasks();
      await fetchTaskDetailAndEvents(taskDetail.task_id);
    } catch (err: any) {
      setErrorBanner(err?.message || 'Failed to generate implementation plan.');
    } finally {
      setActionBusy(null);
    }
  }

  async function handleApprovePlan() {
    if (!taskDetail || !taskDetail.latest_plan) return;
    setActionBusy('approve');
    setErrorBanner(null);
    try {
      await approveTaskPlan(taskDetail.task_id, {
        plan_version: taskDetail.latest_plan.plan_version,
        base_revision: taskDetail.latest_plan.base_revision ?? undefined,
        comment: approvalComment.trim() || 'Approved for isolated workspace execution.',
      });
      setApprovalComment('');
      await fetchTasks();
      await fetchTaskDetailAndEvents(taskDetail.task_id);
    } catch (err: any) {
      setErrorBanner(err?.message || 'Failed to approve plan.');
    } finally {
      setActionBusy(null);
    }
  }

  async function handleRejectPlan() {
    if (!taskDetail || !taskDetail.latest_plan) return;
    setActionBusy('reject');
    setErrorBanner(null);
    try {
      await rejectTaskPlan(taskDetail.task_id, {
        plan_version: taskDetail.latest_plan.plan_version,
        reason: rejectionReason.trim() || 'Plan rejected; requires revision.',
      });
      setRejectionReason('');
      await fetchTasks();
      await fetchTaskDetailAndEvents(taskDetail.task_id);
    } catch (err: any) {
      setErrorBanner(err?.message || 'Failed to reject plan.');
    } finally {
      setActionBusy(null);
    }
  }

  async function handleExecuteTask() {
    if (!taskDetail) return;
    setActionBusy('execute');
    setErrorBanner(null);
    try {
      await executeApprovedTask(taskDetail.task_id);
      await fetchTasks();
      await fetchTaskDetailAndEvents(taskDetail.task_id);
    } catch (err: any) {
      setErrorBanner(err?.message || 'Execution blocked by approval gate.');
    } finally {
      setActionBusy(null);
    }
  }

  const latestPlan = taskDetail?.latest_plan ?? null;
  const isApproved =
    taskDetail?.status === 'APPROVED' &&
    taskDetail.approved_plan_version != null &&
    taskDetail.approved_plan_version === latestPlan?.plan_version;

  return (
    <div className="flex flex-col h-full w-full overflow-hidden bg-background">
      {/* Top Action Toolbar: Issue Import & New Task */}
      <div className="shrink-0 bg-card border-b border-border px-4 py-2.5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <ListChecks className="h-4 w-4 text-primary" />
          <span className="text-xs font-semibold text-foreground">
            Week 3 Workflow Automation — Task Planner & Human Approval Gate
          </span>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <form onSubmit={handleImportIssue} className="flex items-center gap-1.5">
            <input
              type="number"
              min={1}
              value={issueNumberInput}
              onChange={(e) => setIssueNumberInput(e.target.value)}
              placeholder="GitHub Issue # (e.g. 42)"
              className="w-44 px-2.5 py-1 text-xs rounded-md border border-border bg-background text-foreground font-mono focus:outline-none focus:border-primary"
            />
            <button
              type="submit"
              disabled={actionBusy !== null || !issueNumberInput.trim()}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-border bg-background hover:bg-accent text-xs font-medium text-foreground disabled:opacity-50"
            >
              {actionBusy === 'import' ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <GitPullRequestDraft className="h-3.5 w-3.5 text-primary" />
              )}
              <span>Import Issue</span>
            </button>
          </form>

          <button
            type="button"
            onClick={() => setShowNewTaskForm(!showNewTaskForm)}
            className="inline-flex items-center gap-1.5 px-3 py-1 rounded-md bg-primary text-primary-foreground text-xs font-semibold hover:bg-primary/90"
          >
            <Plus className="h-3.5 w-3.5" />
            <span>New Task</span>
          </button>
        </div>
      </div>

      {errorBanner && (
        <div className="shrink-0 px-4 py-2 bg-destructive/10 border-b border-destructive/30 text-xs text-destructive flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span>{errorBanner}</span>
          </div>
          <button
            type="button"
            onClick={() => setErrorBanner(null)}
            className="text-xs underline"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Collapsible New Task Intake Form */}
      {showNewTaskForm && (
        <form
          onSubmit={handleCreateNewTask}
          className="shrink-0 bg-muted/20 border-b border-border p-4 space-y-3"
        >
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] font-mono uppercase text-muted-foreground block mb-1">
                Task Title
              </label>
              <input
                type="text"
                required
                value={newTaskTitle}
                onChange={(e) => setNewTaskTitle(e.target.value)}
                placeholder="e.g. Fix negative amount validation in src/validation.py"
                className="w-full px-3 py-1.5 text-xs rounded-lg border border-border bg-background text-foreground"
              />
            </div>
            <div>
              <label className="text-[11px] font-mono uppercase text-muted-foreground block mb-1">
                Target Files (comma-separated, relative paths)
              </label>
              <input
                type="text"
                value={newTaskFiles}
                onChange={(e) => setNewTaskFiles(e.target.value)}
                placeholder="e.g. src/validation.py, tests/test_validation.py"
                className="w-full px-3 py-1.5 text-xs rounded-lg border border-border bg-background text-foreground font-mono"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] font-mono uppercase text-muted-foreground block mb-1">
                Requirement Description
              </label>
              <textarea
                rows={2}
                required
                value={newTaskDesc}
                onChange={(e) => setNewTaskDesc(e.target.value)}
                placeholder="Describe what must be built or fixed…"
                className="w-full px-3 py-1.5 text-xs rounded-lg border border-border bg-background text-foreground"
              />
            </div>
            <div>
              <label className="text-[11px] font-mono uppercase text-muted-foreground block mb-1">
                Protected / Forbidden Files Constraint
              </label>
              <input
                type="text"
                value={newTaskForbidden}
                onChange={(e) => setNewTaskForbidden(e.target.value)}
                className="w-full px-3 py-1.5 text-xs rounded-lg border border-border bg-background text-foreground font-mono"
              />
            </div>
          </div>

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setShowNewTaskForm(false)}
              className="px-3 py-1 rounded-md border border-border text-xs"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={actionBusy === 'create'}
              className="px-3.5 py-1 rounded-md bg-primary text-primary-foreground text-xs font-semibold"
            >
              {actionBusy === 'create' ? 'Creating…' : 'Create Task'}
            </button>
          </div>
        </form>
      )}

      {/* Main Split View: Left Task List, Center Plan & Approval Gate, Right Timeline */}
      <div className="flex-1 min-h-0 flex overflow-hidden">
        {/* Left Sidebar: Task List */}
        <aside className="w-80 shrink-0 border-r border-border bg-card/30 flex flex-col min-h-0">
          <div className="px-3.5 py-2.5 border-b border-border flex items-center justify-between text-xs font-semibold">
            <span>Tasks ({tasks.length})</span>
            <button
              type="button"
              onClick={fetchTasks}
              className="text-muted-foreground hover:text-foreground p-1"
              title="Refresh tasks"
            >
              <RefreshCw className={cn('h-3.5 w-3.5', loadingList && 'animate-spin')} />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto divide-y divide-border/50">
            {tasks.length === 0 ? (
              <div className="p-6 text-center text-xs text-muted-foreground space-y-2">
                <p>No tasks created for this repository yet.</p>
                <p className="text-[11px]">
                  Import a GitHub issue above, create a task from Bug Hunter / Code Review findings, or click &ldquo;New Task&rdquo;.
                </p>
              </div>
            ) : (
              tasks.map((t) => {
                const badge = STATUS_BADGE_MAP[t.status] || {
                  label: t.status,
                  className: 'bg-muted text-muted-foreground border-border',
                };
                const isSelected = t.task_id === selectedTaskId;
                return (
                  <button
                    key={t.task_id}
                    type="button"
                    onClick={() => setSelectedTaskId(t.task_id)}
                    className={cn(
                      'w-full text-left p-3 space-y-1.5 transition-colors hover:bg-accent/40',
                      isSelected && 'bg-primary/10 border-l-2 border-l-primary'
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span
                        className={cn(
                          'px-2 py-0.5 rounded border text-[10px] font-mono font-semibold',
                          badge.className
                        )}
                      >
                        {badge.label}
                      </span>
                      <span className="text-[10px] font-mono text-muted-foreground">
                        v{t.plan_version}
                      </span>
                    </div>
                    <div className="text-xs font-medium text-foreground line-clamp-2">
                      {t.title}
                    </div>
                    <div className="flex items-center justify-between text-[10px] font-mono text-muted-foreground">
                      <span>{t.source_type}</span>
                      {t.source.issue_number && <span>#{t.source.issue_number}</span>}
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </aside>

        {/* Center Canvas: Task Detail, Structured Plan & Approval Gate */}
        <div className="flex-1 min-h-0 overflow-y-auto p-5 space-y-5">
          {loadingDetail && !taskDetail ? (
            <div className="h-64 flex items-center justify-center text-xs text-muted-foreground gap-2">
              <Loader2 className="h-5 w-5 animate-spin text-primary" />
              <span>Loading task and implementation plan…</span>
            </div>
          ) : !taskDetail ? (
            <div className="h-64 flex flex-col items-center justify-center text-center text-xs text-muted-foreground space-y-2">
              <Sparkles className="h-8 w-8 text-primary/60" />
              <p>Select a task on the left to inspect its intake, generate a plan, or approve execution.</p>
            </div>
          ) : (
            <>
              {/* Task Header Card */}
              <div className="rounded-xl border border-border bg-card p-4 space-y-3">
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span
                        className={cn(
                          'px-2 py-0.5 rounded border text-[10px] font-mono font-bold',
                          (STATUS_BADGE_MAP[taskDetail.status] || STATUS_BADGE_MAP.CREATED).className
                        )}
                      >
                        {taskDetail.status}
                      </span>
                      <span className="text-[11px] font-mono text-muted-foreground">
                        Source: <strong className="text-foreground">{taskDetail.source_type}</strong>
                      </span>
                      {taskDetail.base_revision && (
                        <span className="inline-flex items-center gap-1 text-[11px] font-mono text-muted-foreground">
                          <GitBranch className="h-3 w-3" />
                          <span>{taskDetail.base_revision.slice(0, 12)}</span>
                        </span>
                      )}
                      {taskDetail.source.issue_url && (
                        <a
                          href={taskDetail.source.issue_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-[11px] font-mono text-primary hover:underline"
                        >
                          <span>Issue #{taskDetail.source.issue_number}</span>
                          <ExternalLink className="h-3 w-3" />
                        </a>
                      )}
                    </div>
                    <h2 className="text-base font-bold text-foreground">{taskDetail.title}</h2>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      disabled={actionBusy !== null}
                      onClick={handleGenerateOrRevisePlan}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary text-primary-foreground text-xs font-semibold hover:bg-primary/90 disabled:opacity-50"
                    >
                      {actionBusy === 'plan' ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Sparkles className="h-3.5 w-3.5" />
                      )}
                      <span>
                        {latestPlan
                          ? `Revise Plan (v${latestPlan.plan_version + 1})`
                          : 'Generate Implementation Plan'}
                      </span>
                    </button>

                    <button
                      type="button"
                      disabled={!isApproved || actionBusy !== null}
                      onClick={handleExecuteTask}
                      title={
                        isApproved
                          ? 'Execute approved plan in isolated workspace'
                          : 'Execution is blocked until the current plan version is approved'
                      }
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 text-white text-xs font-semibold hover:bg-emerald-500 disabled:opacity-40"
                    >
                      <Play className="h-3.5 w-3.5" />
                      <span>Start Workspace Execution</span>
                    </button>
                  </div>
                </div>

                {/* Segregated Intake Summary: Requirements, Assumptions, Constraints */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-2 border-t border-border/60 text-xs">
                  <div className="rounded-lg bg-muted/20 border border-border/50 p-2.5 space-y-1">
                    <div className="text-[10px] font-mono uppercase text-primary font-bold">
                      Requirements ({taskDetail.requirements.length})
                    </div>
                    {taskDetail.requirements.map((r) => (
                      <div key={r.id} className="text-[11px] text-foreground/90">
                        • {r.description}
                        {r.target_files.length > 0 && (
                          <div className="text-[10px] font-mono text-muted-foreground mt-0.5">
                            Files: {r.target_files.join(', ')}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>

                  <div className="rounded-lg bg-muted/20 border border-border/50 p-2.5 space-y-1">
                    <div className="text-[10px] font-mono uppercase text-amber-400 font-bold">
                      Assumptions ({taskDetail.assumptions.length})
                    </div>
                    {taskDetail.assumptions.map((a) => (
                      <div key={a.id} className="text-[11px] text-foreground/90">
                        • {a.description}
                      </div>
                    ))}
                  </div>

                  <div className="rounded-lg bg-muted/20 border border-border/50 p-2.5 space-y-1">
                    <div className="text-[10px] font-mono uppercase text-rose-400 font-bold">
                      Protected Constraints ({taskDetail.constraints.length})
                    </div>
                    {taskDetail.constraints.map((c) => (
                      <div key={c.id} className="text-[11px] text-foreground/90">
                        • {c.description}
                        {c.forbidden_files.length > 0 && (
                          <div className="text-[10px] font-mono text-rose-300 mt-0.5">
                            Forbidden: {c.forbidden_files.join(', ')}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Human Approval Gate Banner & Plan Viewer */}
              {!latestPlan ? (
                <div className="rounded-xl border border-dashed border-border p-8 text-center space-y-3">
                  <Sparkles className="h-8 w-8 text-primary mx-auto" />
                  <div className="space-y-1">
                    <h3 className="text-sm font-semibold text-foreground">
                      No Implementation Plan Generated Yet
                    </h3>
                    <p className="text-xs text-muted-foreground max-w-md mx-auto">
                      Click &ldquo;Generate Implementation Plan&rdquo; above to run TaskPlanner and synthesize ordered implementation steps, affected files, test commands, and risk analysis.
                    </p>
                  </div>
                </div>
              ) : (
                <div className="space-y-4">
                  {/* Server-Enforced Human Approval Gate Card */}
                  <div
                    className={cn(
                      'rounded-xl border p-4 space-y-3',
                      isApproved
                        ? 'border-emerald-500/40 bg-emerald-500/10'
                        : taskDetail.status === 'REJECTED'
                        ? 'border-rose-500/40 bg-rose-500/10'
                        : 'border-amber-500/40 bg-amber-500/10'
                    )}
                  >
                    <div className="flex items-start justify-between gap-3 flex-wrap">
                      <div className="flex items-start gap-2.5">
                        {isApproved ? (
                          <ShieldCheck className="h-5 w-5 text-emerald-400 shrink-0 mt-0.5" />
                        ) : taskDetail.status === 'REJECTED' ? (
                          <XCircle className="h-5 w-5 text-rose-400 shrink-0 mt-0.5" />
                        ) : (
                          <ShieldAlert className="h-5 w-5 text-amber-400 shrink-0 mt-0.5" />
                        )}
                        <div className="space-y-0.5">
                          <h3 className="text-xs font-bold uppercase tracking-wider text-foreground">
                            Human Approval Gate — Plan v{latestPlan.plan_version}
                            {latestPlan.plan_hash ? ` (Hash: ${latestPlan.plan_hash.slice(0, 10)})` : ''}
                          </h3>
                          <p className="text-xs text-muted-foreground">
                            {isApproved
                              ? `Plan v${latestPlan.plan_version} is explicitly approved. Any change to the plan or base revision will automatically invalidate this approval.`
                              : taskDetail.status === 'REJECTED'
                              ? `Plan v${latestPlan.plan_version} was rejected. Execution is blocked until a revised plan is generated and approved.`
                              : `Execution is blocked by backend policy until Plan v${latestPlan.plan_version} is explicitly approved.`}
                          </p>
                        </div>
                      </div>
                    </div>

                    {/* Approve / Reject / Revise Controls */}
                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 pt-2 border-t border-border/40">
                      <div className="flex items-center gap-2">
                        <input
                          type="text"
                          value={approvalComment}
                          onChange={(e) => setApprovalComment(e.target.value)}
                          placeholder="Approval note (optional)…"
                          className="flex-1 px-2.5 py-1.5 text-xs rounded-lg border border-border bg-background text-foreground"
                        />
                        <button
                          type="button"
                          disabled={actionBusy !== null || taskDetail.status === 'REJECTED'}
                          onClick={handleApprovePlan}
                          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-600 text-white text-xs font-semibold hover:bg-emerald-500 disabled:opacity-40 shrink-0"
                        >
                          <ThumbsUp className="h-3.5 w-3.5" />
                          <span>Approve v{latestPlan.plan_version}</span>
                        </button>
                      </div>

                      <div className="flex items-center gap-2">
                        <input
                          type="text"
                          value={rejectionReason}
                          onChange={(e) => setRejectionReason(e.target.value)}
                          placeholder="Rejection reason…"
                          className="flex-1 px-2.5 py-1.5 text-xs rounded-lg border border-border bg-background text-foreground"
                        />
                        <button
                          type="button"
                          disabled={actionBusy !== null}
                          onClick={handleRejectPlan}
                          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-rose-600 text-white text-xs font-semibold hover:bg-rose-500 disabled:opacity-40 shrink-0"
                        >
                          <ThumbsDown className="h-3.5 w-3.5" />
                          <span>Reject</span>
                        </button>
                      </div>

                      <div className="flex items-center gap-2">
                        <input
                          type="text"
                          value={revisionNotes}
                          onChange={(e) => setRevisionNotes(e.target.value)}
                          placeholder="Revision instructions for v(N+1)…"
                          className="flex-1 px-2.5 py-1.5 text-xs rounded-lg border border-border bg-background text-foreground"
                        />
                        <button
                          type="button"
                          disabled={actionBusy !== null}
                          onClick={handleGenerateOrRevisePlan}
                          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-border bg-background hover:bg-accent text-xs font-semibold text-foreground shrink-0"
                        >
                          <RefreshCw className="h-3.5 w-3.5" />
                          <span>Revise</span>
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* Plan Summary, Expected Files, Tests & Budget */}
                  <div className="rounded-xl border border-border bg-card p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                        Structured Plan Overview (v{latestPlan.plan_version})
                      </h3>
                      {latestPlan.resource_budget && (
                        <span className="text-[11px] font-mono text-muted-foreground">
                          Max Repair Budget: {latestPlan.resource_budget.max_repair_attempts ?? 3} attempts ·{' '}
                          {latestPlan.resource_budget.max_tokens ?? 20000} tokens
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-foreground leading-relaxed">{latestPlan.summary}</p>

                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {((latestPlan.expected_files || (latestPlan as any).expected_files_to_modify || []) as string[]).map((fp: string) => (
                        <span
                          key={fp}
                          className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-primary/10 border border-primary/20 text-primary text-[11px] font-mono"
                        >
                          <FileCode className="h-3 w-3" />
                          <span>{fp}</span>
                        </span>
                      ))}
                    </div>
                  </div>

                  {/* Ordered Implementation Steps */}
                  <div className="space-y-2.5">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                      Ordered Implementation Steps ({latestPlan.steps.length})
                    </h3>
                    {latestPlan.steps.map((step: PlanStep, index: number) => (
                      <div
                        key={step.step_id}
                        className="rounded-xl border border-border bg-card/60 p-3.5 space-y-2"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <span className="px-2 py-0.5 rounded bg-primary/15 text-primary border border-primary/30 text-[10px] font-mono font-bold">
                              #{index + 1} · {step.step_id}
                            </span>
                            <span className="px-2 py-0.5 rounded bg-muted text-muted-foreground text-[10px] font-mono uppercase">
                              {step.action_type || step.step_type}
                            </span>
                            <h4 className="text-xs font-semibold text-foreground">{step.title}</h4>
                          </div>
                          {step.depends_on && step.depends_on.length > 0 && (
                            <span className="text-[10px] font-mono text-muted-foreground">
                              Depends on: {step.depends_on.join(', ')}
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground leading-relaxed">
                          {step.description}
                        </p>
                        <div className="flex flex-wrap items-center gap-2 text-[11px] font-mono">
                          {step.expected_files.map((f) => (
                            <span
                              key={f}
                              className="px-1.5 py-0.5 rounded bg-muted/40 border border-border text-foreground"
                            >
                              {f}
                            </span>
                          ))}
                          {step.verification.map((v, i) => (
                            <span
                              key={i}
                              className="inline-flex items-center gap-1 text-emerald-400"
                            >
                              <CheckCircle2 className="h-3 w-3" />
                              <span>{v}</span>
                            </span>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* Risks & Validation Strategy */}
                  {Array.isArray(latestPlan.risks) && latestPlan.risks.length > 0 && (
                    <div className="rounded-xl border border-border bg-card p-4 space-y-2">
                      <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                        Identified Risks & Mitigations
                      </h3>
                      {latestPlan.risks.map((risk: any, rIdx: number) => {
                        const isObj = typeof risk === 'object' && risk !== null;
                        const rId = isObj ? (risk.id || risk.risk_id || `risk-${rIdx}`) : `risk-${rIdx}`;
                        const rDesc = isObj ? risk.description : String(risk);
                        const rMitigation = isObj ? risk.mitigation : null;
                        const rSeverity = isObj ? (risk.severity || 'low') : 'low';
                        return (
                          <div
                            key={rId}
                            className="flex items-start justify-between gap-3 text-xs border-t border-border/40 pt-2"
                          >
                            <div className="space-y-0.5">
                              <div className="font-medium text-foreground">{rDesc}</div>
                              {rMitigation && (
                                <div className="text-[11px] text-muted-foreground">
                                  Mitigation: {rMitigation}
                                </div>
                              )}
                            </div>
                            <span
                              className={cn(
                                'px-2 py-0.5 rounded border text-[10px] font-mono uppercase font-bold shrink-0',
                                RISK_BADGE_MAP[rSeverity] || RISK_BADGE_MAP.low
                              )}
                            >
                              {rSeverity}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        {/* Right Sidebar: Ordered Audit Timeline */}
        <aside className="w-72 shrink-0 border-l border-border bg-card/30 flex flex-col min-h-0">
          <div className="px-3.5 py-2.5 border-b border-border flex items-center gap-1.5 text-xs font-semibold">
            <History className="h-3.5 w-3.5 text-primary" />
            <span>Audit Timeline ({events.length})</span>
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-3">
            {events.length === 0 ? (
              <div className="text-center text-xs text-muted-foreground py-8">
                No timeline events recorded yet.
              </div>
            ) : (
              events.map((evt) => (
                <div
                  key={evt.event_id}
                  className="rounded-lg border border-border/60 bg-background/60 p-2.5 space-y-1 text-xs"
                >
                  <div className="flex items-center justify-between gap-1 text-[10px] font-mono">
                    <span className="text-primary font-semibold">{evt.event_type}</span>
                    <span className="text-muted-foreground inline-flex items-center gap-0.5">
                      <Clock className="h-2.5 w-2.5" />
                      {evt.created_at ? new Date(evt.created_at).toLocaleTimeString() : ''}
                    </span>
                  </div>
                  <p className="text-[11px] text-foreground/90 leading-snug">{evt.summary}</p>
                  {evt.to_status && (
                    <div className="text-[10px] font-mono text-muted-foreground">
                      {evt.from_status ? `${evt.from_status} → ` : ''}
                      <span className="text-emerald-400">{evt.to_status}</span>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}

export default RepositoryTaskStudio;
