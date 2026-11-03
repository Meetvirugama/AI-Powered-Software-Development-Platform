/**
 * RepositoryTaskStudio — Week 3 Day 1–7 Studio UI:
 * - F31 GitHub Issue Import & Issue List
 * - F32 Task Intake (segregated Requirements, Assumptions, Protected-File Constraints)
 * - F32 Structured Implementation Plan Viewer (steps, dependencies, files, tests, validation, risks, budget)
 * - F32 Human Approval Gate (Approve Plan vN, Reject Plan with reason, Revise Plan with notes, Execute Approved Plan)
 * - F33 Isolated Workspace Lifecycle Controls (Pause, Resume, Cancel, Branch & Sandbox Telemetry)
 * - F35 Test Runner & Bounded Self-Repair Loop Controls (Run Tests, Trigger Auto-Repair, 3-Attempt Budget Tracker)
 * - F36 Independent Verification & Review Panel (Run Verification across Tests, Diff Scope, Secret Scan, Static Analysis & AI Review)
 * - F37 Git Commit, Push & Draft PR Publication Gate (Mandatory Human Publication Authorization Checkbox & Draft PR Link)
 * - F38 & F39 Ordered Task Execution Timeline, Checkpoints & Crash Recovery Controls
 *
 * Owner: Dhramraj & Yug — Week 3 Day 1–7 Deliverable (Docs/week3.md §6 F31–F39)
 */

import { useState, useCallback, useMemo } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  ExternalLink,
  FileCode,
  FlaskConical,
  GitBranch,
  GitCommit,
  GitPullRequestDraft,
  History,
  ListChecks,
  Loader2,
  Pause,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
  Slash,
  Sparkles,
  Terminal,
  ThumbsDown,
  ThumbsUp,
  Wrench,
  XCircle,
} from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { cn } from '../lib/utils';
import {
  useTasks,
  useTask,
  useTaskEvents,
  useTaskWorkspace,
  useTaskTests,
  useTaskRepairBudget,
  useTaskVerification,
  useTaskPullRequest,
  taskKeys,
} from '../hooks/useTasks';
import {
  approveTaskPlan,
  cancelTask,
  commitTaskChanges,
  createTask,
  createTaskDraftPR,
  executeTask,
  generateTaskPlan,
  importGitHubIssue,
  pauseTask,
  recoverTask,
  rejectTaskPlan,
  resumeTask,
  triggerTaskRepair,
  triggerTaskTests,
  triggerTaskVerification,
} from '../services/tasks';
import type {
  PlanStep,
  TaskDetail,
  TaskEvent,
  TaskPullRequestResponse,
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
  TESTING: {
    label: 'Testing',
    className: 'bg-sky-500/15 text-sky-300 border-sky-500/40',
  },
  REPAIRING: {
    label: 'Self-Repairing',
    className: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
  },
  VERIFYING: {
    label: 'Verifying',
    className: 'bg-teal-500/15 text-teal-300 border-teal-500/40',
  },
  READY_FOR_PUBLICATION: {
    label: 'Ready for Publication',
    className: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40',
  },
  PUBLISHING: {
    label: 'Publishing PR…',
    className: 'bg-purple-500/15 text-purple-300 border-purple-500/40',
  },
  DRAFT_PR_CREATED: {
    label: 'Draft PR Created',
    className: 'bg-purple-500/15 text-purple-300 border-purple-500/40',
  },
  RECOVERY_REQUIRED: {
    label: 'Recovery Required',
    className: 'bg-orange-500/15 text-orange-300 border-orange-500/40',
  },
  BLOCKED: {
    label: 'Blocked',
    className: 'bg-rose-500/15 text-rose-300 border-rose-500/40',
  },
  FAILED: {
    label: 'Failed',
    className: 'bg-rose-500/15 text-rose-300 border-rose-500/40',
  },
  CANCELLED: {
    label: 'Cancelled',
    className: 'bg-zinc-500/15 text-zinc-400 border-zinc-500/40',
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

  const queryClient = useQueryClient();
  const [errorBanner, setErrorBanner] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState<string | null>(null);

  // 1. Task List Query (P0.4: independent of selectedTaskId, fetched via useTasks)
  const {
    data: taskListData,
    isLoading: loadingList,
    error: taskListError,
  } = useTasks({ repository_id: repoId, page_size: 50 }, { enabled: Boolean(repoId) });

  const tasks: TaskSummary[] = useMemo(() => taskListData?.items ?? [], [taskListData?.items]);

  // 2. Selected Task State (P0.3 & P0.4)
  const urlTaskId = searchParams.get('taskId');
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(urlTaskId);
  const [prevUrlTaskId, setPrevUrlTaskId] = useState<string | null>(urlTaskId);

  if (urlTaskId !== prevUrlTaskId) {
    setPrevUrlTaskId(urlTaskId);
    setSelectedTaskId(urlTaskId);
  }

  const activeTaskId = selectedTaskId || (tasks.length > 0 ? tasks[0].task_id : null);
  const isTaskActive = Boolean(activeTaskId);

  const handleSelectTask = useCallback(
    (taskId: string) => {
      setErrorBanner(null);
      setSelectedTaskId(taskId);
      setSearchParams({ taskId }, { replace: true });
    },
    [setSearchParams]
  );

  // 3. Task Resource Queries (P0.3: scoped strictly to activeTaskId)
  const {
    data: taskDetailData,
    isLoading: loadingDetail,
    error: taskDetailError,
  } = useTask(activeTaskId ?? undefined, {
    enabled: isTaskActive,
  });
  const taskDetail = (isTaskActive ? taskDetailData : null) as TaskDetail | null;

  const { data: eventsData } = useTaskEvents(activeTaskId ?? undefined, undefined, {
    enabled: isTaskActive,
  });
  const events: TaskEvent[] = isTaskActive
    ? (Array.isArray(eventsData) ? eventsData : (eventsData as any)?.items || [])
    : [];

  const { data: workspaceData } = useTaskWorkspace(activeTaskId ?? undefined, {
    enabled: isTaskActive,
  });
  const workspaceMeta = isTaskActive ? (workspaceData ?? null) : null;

  const { data: testResultsData } = useTaskTests(activeTaskId ?? undefined, {
    enabled: isTaskActive,
  });
  const testResults = isTaskActive ? (testResultsData ?? null) : null;

  const { data: repairBudgetData } = useTaskRepairBudget(activeTaskId ?? undefined, {
    enabled: isTaskActive,
  });
  const repairBudget = isTaskActive ? (repairBudgetData ?? null) : null;

  const { data: verificationData } = useTaskVerification(activeTaskId ?? undefined, {
    enabled: isTaskActive,
  });
  const verificationResult = isTaskActive ? (verificationData ?? null) : null;

  const { data: draftPRData } = useTaskPullRequest(activeTaskId ?? undefined, {
    enabled: isTaskActive,
    repositoryId: repoId,
  });
  const draftPR = (isTaskActive ? (draftPRData ?? null) : null) as TaskPullRequestResponse | null;

  // Surface task list or detail errors if no manual error banner is active
  const effectiveErrorBanner =
    errorBanner ||
    (taskListError ? (taskListError as any)?.message || 'Failed to load repository tasks.' : null) ||
    (taskDetailError ? (taskDetailError as any)?.message || 'Failed to load task details.' : null);

  // Import GitHub Issue state
  const [issueNumberInput, setIssueNumberInput] = useState('');
  const [showNewTaskForm, setShowNewTaskForm] = useState(false);
  const [newTaskTitle, setNewTaskTitle] = useState('');
  const [newTaskDesc, setNewTaskDesc] = useState('');
  const [newTaskFiles, setNewTaskFiles] = useState('');
  const [newTaskForbidden, setNewTaskForbidden] = useState('.env, .github/workflows/deploy.yml');

  // Approval / Rejection / Revision / Publication inputs
  const [approvalComment, setApprovalComment] = useState('');
  const [rejectionReason, setRejectionReason] = useState('');
  const [revisionNotes, setRevisionNotes] = useState('');
  const [publicationAuthorized, setPublicationAuthorized] = useState(false);

  const refreshTasksAndCurrentDetail = useCallback(
    async (targetTaskId?: string) => {
      const tid = targetTaskId || activeTaskId;
      await queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
      if (tid) {
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: taskKeys.detail(tid) }),
          queryClient.invalidateQueries({ queryKey: taskKeys.events(tid) }),
          queryClient.invalidateQueries({ queryKey: taskKeys.workspace(tid) }),
          queryClient.invalidateQueries({ queryKey: taskKeys.tests(tid) }),
          queryClient.invalidateQueries({ queryKey: taskKeys.repairBudget(tid) }),
          queryClient.invalidateQueries({ queryKey: taskKeys.verification(tid) }),
          queryClient.invalidateQueries({ queryKey: taskKeys.pullRequest(tid) }),
        ]);
      }
    },
    [queryClient, activeTaskId]
  );

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
      handleSelectTask(res.task_id);
      await refreshTasksAndCurrentDetail(res.task_id);
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
      handleSelectTask(created.task_id);
      await refreshTasksAndCurrentDetail(created.task_id);
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
      await refreshTasksAndCurrentDetail(taskDetail.task_id);
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
      await refreshTasksAndCurrentDetail(taskDetail.task_id);
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
      await refreshTasksAndCurrentDetail(taskDetail.task_id);
    } catch (err: any) {
      setErrorBanner(err?.message || 'Failed to reject plan.');
    } finally {
      setActionBusy(null);
    }
  }

  async function handleExecuteTask(runSteps = true) {
    if (!taskDetail) return;
    setActionBusy('execute');
    setErrorBanner(null);
    try {
      await executeTask(taskDetail.task_id, { run_steps: runSteps });
      await refreshTasksAndCurrentDetail(taskDetail.task_id);
    } catch (err: any) {
      setErrorBanner(err?.message || 'Execution blocked by approval gate.');
    } finally {
      setActionBusy(null);
    }
  }

  async function handlePauseTask() {
    if (!taskDetail) return;
    setActionBusy('pause');
    setErrorBanner(null);
    try {
      await pauseTask(taskDetail.task_id);
      await refreshTasksAndCurrentDetail(taskDetail.task_id);
    } catch (err: any) {
      setErrorBanner(err?.message || 'Failed to pause workspace execution.');
    } finally {
      setActionBusy(null);
    }
  }

  async function handleResumeTask() {
    if (!taskDetail) return;
    setActionBusy('resume');
    setErrorBanner(null);
    try {
      await resumeTask(taskDetail.task_id);
      await refreshTasksAndCurrentDetail(taskDetail.task_id);
    } catch (err: any) {
      setErrorBanner(err?.message || 'Failed to resume workspace execution.');
    } finally {
      setActionBusy(null);
    }
  }

  async function handleCancelTask() {
    if (!taskDetail) return;
    setActionBusy('cancel');
    setErrorBanner(null);
    try {
      await cancelTask(taskDetail.task_id);
      await refreshTasksAndCurrentDetail(taskDetail.task_id);
    } catch (err: any) {
      setErrorBanner(err?.message || 'Failed to cancel task.');
    } finally {
      setActionBusy(null);
    }
  }

  async function handleRunTests() {
    if (!taskDetail) return;
    setActionBusy('tests');
    setErrorBanner(null);
    try {
      await triggerTaskTests(taskDetail.task_id, { framework: 'pytest' });
      await refreshTasksAndCurrentDetail(taskDetail.task_id);
    } catch (err: any) {
      setErrorBanner(err?.message || 'Failed to run workspace tests.');
    } finally {
      setActionBusy(null);
    }
  }

  async function handleRunRepair() {
    if (!taskDetail) return;
    setActionBusy('repair');
    setErrorBanner(null);
    try {
      await triggerTaskRepair(taskDetail.task_id, { framework: 'pytest' });
      await refreshTasksAndCurrentDetail(taskDetail.task_id);
    } catch (err: any) {
      setErrorBanner(err?.message || 'Bounded self-repair failed or budget exhausted.');
    } finally {
      setActionBusy(null);
    }
  }

  async function handleRunVerification() {
    if (!taskDetail) return;
    setActionBusy('verify');
    setErrorBanner(null);
    try {
      await triggerTaskVerification(taskDetail.task_id, {
        require_passing_tests: true,
        strict_scope: true,
      });
      await refreshTasksAndCurrentDetail(taskDetail.task_id);
    } catch (err: any) {
      setErrorBanner(err?.message || 'Independent verification failed.');
    } finally {
      setActionBusy(null);
    }
  }

  async function handleCommitChanges() {
    if (!taskDetail) return;
    setActionBusy('commit');
    setErrorBanner(null);
    try {
      await commitTaskChanges(taskDetail.task_id, {
        message: `feat(task): implement ${taskDetail.title}`,
      });
      await refreshTasksAndCurrentDetail(taskDetail.task_id);
    } catch (err: any) {
      setErrorBanner(err?.message || 'Failed to commit workspace changes.');
    } finally {
      setActionBusy(null);
    }
  }

  async function handleCreateDraftPR() {
    if (!taskDetail) return;
    setActionBusy('create-pr');
    setErrorBanner(null);
    try {
      const pr = await createTaskDraftPR(taskDetail.task_id, {
        publication_authorized: publicationAuthorized,
        title: `feat: ${taskDetail.title}`,
      });
      queryClient.setQueryData(taskKeys.pullRequest(taskDetail.task_id), pr);
      await refreshTasksAndCurrentDetail(taskDetail.task_id);
    } catch (err: any) {
      setErrorBanner(
        err?.message || 'Publication blocked: Independent verification and explicit human authorization are required.'
      );
    } finally {
      setActionBusy(null);
    }
  }

  async function handleRecoverTask() {
    if (!taskDetail) return;
    setActionBusy('recover');
    setErrorBanner(null);
    try {
      await recoverTask(taskDetail.task_id);
      await refreshTasksAndCurrentDetail(taskDetail.task_id);
    } catch (err: any) {
      setErrorBanner(err?.message || 'Failed to recover interrupted task.');
    } finally {
      setActionBusy(null);
    }
  }

  const latestPlan = taskDetail?.latest_plan ?? null;
  const isApproved =
    (taskDetail?.status === 'APPROVED' || taskDetail?.status === 'WORKSPACE_SETUP') &&
    taskDetail.approved_plan_version != null &&
    taskDetail.approved_plan_version === latestPlan?.plan_version;
  const hasWorkspace =
    workspaceMeta && workspaceMeta.status && workspaceMeta.status !== 'NOT_CREATED';
  const canPublishPR =
    taskDetail?.status === 'READY_FOR_PUBLICATION' ||
    taskDetail?.status === 'PUBLISHING' ||
    (verificationResult &&
      (verificationResult.status === 'PASS' || verificationResult.status === 'REQUIRES_HUMAN_REVIEW') &&
      (verificationResult.blocking_findings || []).length === 0);

  return (
    <div className="flex flex-col h-full w-full overflow-hidden bg-background">
      {/* Top Action Toolbar: Issue Import & New Task */}
      <div className="shrink-0 bg-card border-b border-border px-4 py-2.5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <ListChecks className="h-4 w-4 text-primary" />
          <span className="text-xs font-semibold text-foreground">
            Week 3 Workflow Automation — Task Planner, Sandbox, Bounded Repair, Verification &amp; Draft PR
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

      {effectiveErrorBanner && (
        <div className="shrink-0 px-4 py-2 bg-destructive/10 border-b border-destructive/30 text-xs text-destructive flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span>{effectiveErrorBanner}</span>
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

      {/* Main Split View: Left Task List, Center Plan/Sandbox/Repair/Verification/PR, Right Timeline */}
      <div className="flex-1 min-h-0 flex overflow-hidden">
        {/* Left Sidebar: Task List */}
        <aside className="w-80 shrink-0 border-r border-border bg-card/30 flex flex-col min-h-0">
          <div className="px-3.5 py-2.5 border-b border-border flex items-center justify-between text-xs font-semibold">
            <span>Tasks ({tasks.length})</span>
            <button
              type="button"
              onClick={() => refreshTasksAndCurrentDetail()}
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
                const isSelected = t.task_id === activeTaskId;
                return (
                  <button
                    key={t.task_id}
                    type="button"
                    onClick={() => handleSelectTask(t.task_id)}
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

        {/* Center Canvas: Task Detail, Structured Plan, Workspace Sandbox, Verification & Draft PR */}
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
                      {draftPR && (
                        <a
                          href={draftPR.pr_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-purple-500/15 border border-purple-500/40 text-[11px] font-mono text-purple-300 hover:underline"
                        >
                          <GitPullRequestDraft className="h-3 w-3" />
                          <span>Draft PR #{draftPR.pr_number}</span>
                          <ExternalLink className="h-3 w-3" />
                        </a>
                      )}
                    </div>
                    <h2 className="text-base font-bold text-foreground">{taskDetail.title}</h2>
                  </div>

                  <div className="flex items-center gap-2 flex-wrap">
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
                      onClick={() => handleExecuteTask(true)}
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

                    {(taskDetail.status === 'RECOVERY_REQUIRED' || taskDetail.status === 'FAILED') && (
                      <button
                        type="button"
                        disabled={actionBusy !== null}
                        onClick={handleRecoverTask}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-orange-500/40 bg-orange-500/15 text-orange-300 text-xs font-semibold hover:bg-orange-500/25 disabled:opacity-40"
                      >
                        <RotateCcw className="h-3.5 w-3.5" />
                        <span>Recover Task</span>
                      </button>
                    )}

                    {taskDetail.status !== 'CANCELLED' &&
                      taskDetail.status !== 'FAILED' &&
                      taskDetail.status !== 'DRAFT_PR_CREATED' && (
                        <button
                          type="button"
                          disabled={actionBusy !== null}
                          onClick={handleCancelTask}
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-rose-500/40 bg-rose-500/10 text-rose-300 text-xs font-semibold hover:bg-rose-500/20 disabled:opacity-40"
                        >
                          <Slash className="h-3.5 w-3.5" />
                          <span>Cancel</span>
                        </button>
                      )}
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

              {/* Day 3–7: Isolated Workspace, Test Runner, Bounded Repair, Independent Verification & Draft PR Card */}
              {hasWorkspace && workspaceMeta && (
                <div className="rounded-xl border border-indigo-500/30 bg-indigo-500/5 p-4 space-y-4">
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div className="flex items-center gap-2">
                      <Terminal className="h-4 w-4 text-indigo-400" />
                      <h3 className="text-xs font-bold uppercase tracking-wider text-foreground">
                        Isolated Workspace, Verification &amp; Publication Controls
                      </h3>
                      <span className="px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 font-mono text-[10px]">
                        {workspaceMeta.status}
                      </span>
                      <span className="text-[11px] font-mono text-muted-foreground">
                        Branch: <strong className="text-foreground">{workspaceMeta.branch_name}</strong>
                      </span>
                    </div>

                    <div className="flex items-center gap-2 flex-wrap">
                      {workspaceMeta.status === 'IN_USE' && (
                        <button
                          type="button"
                          disabled={actionBusy !== null}
                          onClick={handlePauseTask}
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-amber-500/40 bg-amber-500/10 text-amber-300 text-xs font-medium hover:bg-amber-500/20"
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
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 text-emerald-300 text-xs font-medium hover:bg-emerald-500/20"
                        >
                          <Play className="h-3 w-3" />
                          <span>Resume</span>
                        </button>
                      )}
                      <button
                        type="button"
                        disabled={actionBusy !== null}
                        onClick={handleRunTests}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-sky-500/40 bg-sky-500/10 text-sky-300 text-xs font-medium hover:bg-sky-500/20"
                      >
                        <FlaskConical className="h-3 w-3" />
                        <span>Run Tests</span>
                      </button>
                      <button
                        type="button"
                        disabled={
                          actionBusy !== null ||
                          taskDetail.repair_attempts_used >= taskDetail.repair_attempts_max
                        }
                        onClick={handleRunRepair}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-purple-500/40 bg-purple-500/10 text-purple-300 text-xs font-medium hover:bg-purple-500/20 disabled:opacity-40"
                      >
                        <Wrench className="h-3 w-3" />
                        <span>
                          Auto-Repair ({taskDetail.repair_attempts_used}/{taskDetail.repair_attempts_max})
                        </span>
                      </button>
                      <button
                        type="button"
                        disabled={actionBusy !== null}
                        onClick={handleRunVerification}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-teal-500/40 bg-teal-500/10 text-teal-300 text-xs font-medium hover:bg-teal-500/20"
                      >
                        <CheckCircle2 className="h-3 w-3" />
                        <span>Run Verification</span>
                      </button>
                      <button
                        type="button"
                        disabled={actionBusy !== null}
                        onClick={handleCommitChanges}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-border bg-background text-foreground text-xs font-medium hover:bg-accent"
                      >
                        <GitCommit className="h-3 w-3" />
                        <span>Commit</span>
                      </button>
                    </div>
                  </div>

                  {/* Test, Repair & Verification Telemetry Summary */}
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs pt-2 border-t border-border/50">
                    <div className="rounded-lg bg-background/60 border border-border/60 p-2.5 space-y-1">
                      <div className="text-[10px] font-mono uppercase text-sky-400 font-bold">
                        Test Execution Runs ({testResults?.runs?.length || 0})
                      </div>
                      {testResults?.runs && testResults.runs.length > 0 ? (
                        <div className="text-[11px] font-mono space-y-0.5">
                          <div>
                            Latest: <strong>{testResults.runs[testResults.runs.length - 1].status}</strong> (
                            {testResults.runs[testResults.runs.length - 1].tests_passed} passed,{' '}
                            {testResults.runs[testResults.runs.length - 1].tests_failed} failed)
                          </div>
                        </div>
                      ) : (
                        <div className="text-[11px] text-muted-foreground">No test runs recorded yet.</div>
                      )}
                    </div>

                    <div className="rounded-lg bg-background/60 border border-border/60 p-2.5 space-y-1">
                      <div className="text-[10px] font-mono uppercase text-purple-400 font-bold">
                        Bounded Self-Repair Budget ({taskDetail.repair_attempts_used}/{taskDetail.repair_attempts_max})
                      </div>
                      <div className="text-[11px] text-muted-foreground">
                        {repairBudget?.is_budget_exhausted
                          ? 'Retry budget exhausted (3/3 attempts used). Human review required.'
                          : `${taskDetail.repair_attempts_max - taskDetail.repair_attempts_used} repair attempt(s) remaining.`}
                      </div>
                    </div>

                    <div className="rounded-lg bg-background/60 border border-border/60 p-2.5 space-y-1">
                      <div className="text-[10px] font-mono uppercase text-teal-400 font-bold">
                        Independent Verification ({verificationResult?.status || 'INCONCLUSIVE'})
                      </div>
                      {verificationResult && verificationResult.checks.length > 0 ? (
                        <div className="text-[11px] font-mono space-y-0.5">
                          <div>
                            Checks: {verificationResult.checks.filter((c) => c.status === 'PASSED').length}/
                            {verificationResult.checks.length} passed • Blockers:{' '}
                            {verificationResult.blocking_findings.length}
                          </div>
                        </div>
                      ) : (
                        <div className="text-[11px] text-muted-foreground">
                          Click &ldquo;Run Verification&rdquo; to evaluate diff, secrets, static rules &amp; requirements.
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Day 5 Publication Gate: Explicit Human Authorization & Draft PR Creation */}
                  <div className="rounded-lg bg-background/70 border border-purple-500/30 p-3 flex flex-wrap items-center justify-between gap-3 text-xs">
                    <label className="flex items-center gap-2 cursor-pointer select-none">
                      <input
                        type="checkbox"
                        checked={publicationAuthorized}
                        onChange={(e) => setPublicationAuthorized(e.target.checked)}
                        className="rounded border-border text-primary focus:ring-primary"
                      />
                      <span className="text-[11px] text-foreground">
                        <strong>Authorize Branch Push &amp; Draft PR Publication (ADR-010):</strong> I confirm independent verification has been reviewed and authorize creating a GitHub Draft PR (auto-merge disabled).
                      </span>
                    </label>

                    <div className="flex items-center gap-2">
                      {draftPR ? (
                        <a
                          href={draftPR.pr_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-purple-600 text-white text-xs font-semibold hover:bg-purple-500"
                        >
                          <GitPullRequestDraft className="h-3.5 w-3.5" />
                          <span>View Draft PR #{draftPR.pr_number}</span>
                          <ExternalLink className="h-3 w-3" />
                        </a>
                      ) : (
                        <button
                          type="button"
                          disabled={!publicationAuthorized || !canPublishPR || actionBusy !== null}
                          onClick={handleCreateDraftPR}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-purple-600 text-white text-xs font-semibold hover:bg-purple-500 disabled:opacity-40"
                        >
                          <GitPullRequestDraft className="h-3.5 w-3.5" />
                          <span>Create GitHub Draft PR</span>
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              )}

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
                          placeholder="Revision instructions for AI planner…"
                          className="flex-1 px-2.5 py-1.5 text-xs rounded-lg border border-border bg-background text-foreground"
                        />
                        <button
                          type="button"
                          disabled={actionBusy !== null}
                          onClick={handleGenerateOrRevisePlan}
                          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-border bg-background hover:bg-accent text-xs font-semibold shrink-0"
                        >
                          <RefreshCw className="h-3.5 w-3.5" />
                          <span>Revise</span>
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* Structured Plan Summary & Steps */}
                  <div className="rounded-xl border border-border bg-card p-4 space-y-4">
                    <div className="space-y-1">
                      <div className="text-[10px] font-mono uppercase text-primary font-bold">
                        Plan Summary (v{latestPlan.plan_version})
                      </div>
                      <p className="text-sm font-medium text-foreground">{latestPlan.summary}</p>
                      {latestPlan.problem_statement && (
                        <p className="text-xs text-muted-foreground">{latestPlan.problem_statement}</p>
                      )}
                    </div>

                    {/* Ordered Implementation Steps */}
                    <div className="space-y-2.5">
                      <div className="text-[11px] font-mono uppercase text-muted-foreground font-bold">
                        Ordered Implementation Steps ({latestPlan.steps.length})
                      </div>
                      {latestPlan.steps.map((step: PlanStep, idx: number) => (
                        <div
                          key={step.step_id}
                          className="rounded-lg border border-border/70 bg-muted/15 p-3 space-y-2"
                        >
                          <div className="flex items-center justify-between gap-2 flex-wrap">
                            <div className="flex items-center gap-2">
                              <span className="px-2 py-0.5 rounded bg-primary/15 text-primary font-mono text-[10px] font-bold">
                                #{idx + 1} • {step.step_id}
                              </span>
                              <span className="px-2 py-0.5 rounded border border-border text-[10px] font-mono uppercase">
                                {step.action_type || step.step_type}
                              </span>
                              <span className="text-xs font-semibold text-foreground">
                                {step.title}
                              </span>
                            </div>
                            <span
                              className={cn(
                                'px-2 py-0.5 rounded border text-[10px] font-mono uppercase',
                                RISK_BADGE_MAP[step.risk_level || 'low'] || RISK_BADGE_MAP.low
                              )}
                            >
                              Risk: {step.risk_level || 'low'}
                            </span>
                          </div>

                          <p className="text-xs text-muted-foreground">{step.description}</p>

                          <div className="flex flex-wrap gap-3 text-[11px] font-mono text-muted-foreground">
                            {step.expected_files.length > 0 && (
                              <span className="inline-flex items-center gap-1">
                                <FileCode className="h-3 w-3 text-primary" />
                                <span>Files: {step.expected_files.join(', ')}</span>
                              </span>
                            )}
                            {(step.depends_on || step.dependencies || []).length > 0 && (
                              <span>
                                Depends on: {(step.depends_on || step.dependencies || []).join(', ')}
                              </span>
                            )}
                          </div>

                          {step.verification.length > 0 && (
                            <div className="text-[11px] text-emerald-400/90 font-mono">
                              ✓ Verification: {step.verification.join(' | ')}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>

                    {/* Expected Files, Tests to Run, Validation Strategy & Risks */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 border-t border-border/60 text-xs">
                      <div className="rounded-lg bg-muted/20 border border-border/50 p-3 space-y-1.5">
                        <div className="text-[10px] font-mono uppercase text-primary font-bold">
                          Expected Files &amp; Permitted Tests
                        </div>
                        <div className="text-[11px] font-mono text-foreground/90">
                          <strong>Files:</strong>{' '}
                          {(latestPlan.expected_files || latestPlan.expected_files_to_modify || []).join(', ') || 'None'}
                        </div>
                        <div className="text-[11px] font-mono text-foreground/90">
                          <strong>Tests:</strong>{' '}
                          {(latestPlan.tests_to_run || latestPlan.tests_to_add || []).join(' ; ') || 'pytest'}
                        </div>
                      </div>

                      <div className="rounded-lg bg-muted/20 border border-border/50 p-3 space-y-1.5">
                        <div className="text-[10px] font-mono uppercase text-amber-400 font-bold">
                          Risks &amp; Resource Budget
                        </div>
                        {(latestPlan.risks || []).map((r: any, i: number) => (
                          <div key={r.id || i} className="text-[11px] text-foreground/90">
                            • [{String(r.severity || 'medium').toUpperCase()}] {r.description || String(r)} —{' '}
                            <span className="text-muted-foreground">{r.mitigation || ''}</span>
                          </div>
                        ))}
                        {latestPlan.resource_budget && (
                          <div className="text-[10px] font-mono text-muted-foreground pt-1">
                            Budget: max {latestPlan.resource_budget.max_repair_attempts ?? 3} repair attempts •{' '}
                            {latestPlan.resource_budget.max_tokens ?? 20000} tokens
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* Right Sidebar: Ordered Audit & Execution Timeline (F38) */}
        <aside className="w-80 shrink-0 border-l border-border bg-card/30 flex flex-col min-h-0">
          <div className="px-3.5 py-2.5 border-b border-border flex items-center gap-2 text-xs font-semibold">
            <History className="h-3.5 w-3.5 text-primary" />
            <span>Execution &amp; Audit Timeline ({events.length})</span>
          </div>

          <div className="flex-1 overflow-y-auto p-3.5 space-y-3">
            {events.length === 0 ? (
              <div className="text-xs text-muted-foreground text-center py-8">
                No timeline events recorded yet.
              </div>
            ) : (
              events.map((evt, idx) => (
                <div
                  key={evt.event_id || evt.id || idx}
                  className="rounded-lg border border-border/60 bg-background/60 p-2.5 space-y-1 text-xs"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-[10px] font-bold text-primary">
                      {evt.event_type}
                    </span>
                    <span className="inline-flex items-center gap-1 text-[10px] font-mono text-muted-foreground">
                      <Clock className="h-2.5 w-2.5" />
                      <span>
                        {evt.created_at
                          ? new Date(evt.created_at).toLocaleTimeString([], {
                              hour: '2-digit',
                              minute: '2-digit',
                              second: '2-digit',
                            })
                          : ''}
                      </span>
                    </span>
                  </div>
                  <p className="text-[11px] text-foreground/90">
                    {evt.summary || evt.description}
                  </p>
                  {evt.from_status && evt.to_status && (
                    <div className="text-[10px] font-mono text-muted-foreground">
                      {evt.from_status} → <strong className="text-foreground">{evt.to_status}</strong>
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
