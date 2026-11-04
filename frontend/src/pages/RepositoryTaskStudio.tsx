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
  Bot,
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
  const [newTaskPrompt, setNewTaskPrompt] = useState('');
  const [newTaskCustomTitle, setNewTaskCustomTitle] = useState('');
  const [newTaskTitle, setNewTaskTitle] = useState('');
  const [newTaskDesc, setNewTaskDesc] = useState('');
  const [newTaskFiles, setNewTaskFiles] = useState('');
  const [newTaskForbidden, setNewTaskForbidden] = useState('.env, .github/workflows/deploy.yml');
  const [autoPlanImmediately, setAutoPlanImmediately] = useState(true);
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);

  // Approval / Rejection / Revision / Publication inputs
  const [approvalComment, setApprovalComment] = useState('');
  const [rejectionReason, setRejectionReason] = useState('');
  const [revisionNotes, setRevisionNotes] = useState('');
  const [publicationAuthorized, setPublicationAuthorized] = useState(false);
  const [showApprovedRevision, setShowApprovedRevision] = useState(false);

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
    const prompt = (newTaskPrompt || newTaskDesc).trim();
    if (!prompt) return;

    const finalTitle =
      newTaskCustomTitle.trim() ||
      newTaskTitle.trim() ||
      (() => {
        const firstLine = prompt.split('\n')[0].replace(/^[\s#*•-]+/, '');
        return firstLine.length > 70 ? firstLine.slice(0, 67) + '...' : firstLine || 'Autonomous Task';
      })();

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
        title: finalTitle,
        description: prompt,
        source: { type: 'USER_PROMPT', repository_id: repoId },
        requirements: [
          {
            id: 'req-1',
            description: prompt,
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
            forbidden_files: forbiddenFiles.length > 0 ? forbiddenFiles : ['.env', '.github/workflows/deploy.yml'],
            forbidden_packages: [],
            max_budget_tokens: 20000,
          },
        ],
      });
      setShowNewTaskForm(false);
      setNewTaskPrompt('');
      setNewTaskCustomTitle('');
      setNewTaskTitle('');
      setNewTaskDesc('');
      setNewTaskFiles('');
      handleSelectTask(created.task_id);

      if (autoPlanImmediately) {
        setActionBusy('plan');
        try {
          await generateTaskPlan(created.task_id);
        } catch (planErr: any) {
          setErrorBanner(`Task created, but auto-planning encountered an issue: ${planErr?.message || planErr}`);
        }
      }

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
    const tid = taskDetail.task_id;
    setActionBusy('execute');
    setErrorBanner(null);
    try {
      await executeTask(tid, { run_steps: runSteps });
    } catch (err: any) {
      setErrorBanner(err?.message || 'Execution blocked by approval gate.');
    } finally {
      await refreshTasksAndCurrentDetail(tid);
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
    const tid = taskDetail.task_id;
    setActionBusy('tests');
    setErrorBanner(null);
    try {
      await triggerTaskTests(tid, { framework: 'pytest' });
    } catch (err: any) {
      setErrorBanner(err?.message || 'Failed to run workspace tests.');
    } finally {
      await refreshTasksAndCurrentDetail(tid);
      setActionBusy(null);
    }
  }

  async function handleRunRepair() {
    if (!taskDetail) return;
    const tid = taskDetail.task_id;
    setActionBusy('repair');
    setErrorBanner(null);
    try {
      await triggerTaskRepair(tid, { framework: 'pytest' });
    } catch (err: any) {
      setErrorBanner(err?.message || 'Bounded self-repair failed or budget exhausted.');
    } finally {
      await refreshTasksAndCurrentDetail(tid);
      setActionBusy(null);
    }
  }

  async function handleRunVerification() {
    if (!taskDetail) return;
    const tid = taskDetail.task_id;
    setActionBusy('verify');
    setErrorBanner(null);
    try {
      await triggerTaskVerification(tid, {
        require_passing_tests: true,
        strict_scope: true,
      });
    } catch (err: any) {
      setErrorBanner(err?.message || 'Independent verification failed.');
    } finally {
      await refreshTasksAndCurrentDetail(tid);
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
    taskDetail?.status === 'APPROVED' &&
    taskDetail.approved_plan_version != null &&
    taskDetail.approved_plan_version === latestPlan?.plan_version;
  const hasWorkspace =
    workspaceMeta && workspaceMeta.status && workspaceMeta.status !== 'NOT_CREATED';
  const canPublishPR =
    taskDetail?.status === 'READY_FOR_PUBLICATION' ||
    (verificationResult &&
      (verificationResult.status === 'PASS' || verificationResult.status === 'REQUIRES_HUMAN_REVIEW') &&
      (verificationResult.blocking_findings || []).length === 0);

  return (
    <div className="flex flex-col h-full w-full overflow-hidden bg-background">
      {/* Top Action Toolbar: Issue Import & New Task */}
      <div className="shrink-0 bg-card border-b border-border px-4 py-2.5 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <ListChecks className="h-4 w-4 text-primary shrink-0" />
          <span className="text-xs font-semibold text-foreground truncate">
            Week 3 Workflow Automation — Task Planner, Sandbox, Bounded Repair, Verification &amp; Draft PR
          </span>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <form onSubmit={handleImportIssue} className="flex items-center gap-1.5">
            <input
              type="number"
              min={1}
              value={issueNumberInput}
              onChange={(e) => setIssueNumberInput(e.target.value)}
              placeholder="GitHub Issue # (e.g. 42)"
              className="w-36 sm:w-44 px-2.5 py-1 text-xs rounded-md border border-border bg-background text-foreground font-mono focus:outline-none focus:border-primary"
            />
            <button
              type="submit"
              disabled={actionBusy !== null || !issueNumberInput.trim()}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-border bg-background hover:bg-accent text-xs font-medium text-foreground disabled:opacity-50 shrink-0"
            >
              {actionBusy === 'import' ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <GitPullRequestDraft className="h-3.5 w-3.5 text-primary" />
              )}
              <span className="hidden sm:inline">Import Issue</span>
              <span className="sm:hidden">Import</span>
            </button>
          </form>

          <button
            type="button"
            onClick={() => setShowNewTaskForm(!showNewTaskForm)}
            className="inline-flex items-center gap-1.5 px-3 py-1 rounded-md bg-primary text-primary-foreground text-xs font-semibold hover:bg-primary/90 shrink-0"
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

      {/* Autonomous AI Agent Task Intake Form */}
      {showNewTaskForm && (
        <form
          onSubmit={handleCreateNewTask}
          className="shrink-0 bg-primary/5 border-b border-primary/20 p-4 space-y-3"
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" />
              <span className="text-xs font-semibold text-foreground">
                Autonomous AI Task Creation
              </span>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-primary/10 text-primary border border-primary/20">
                Agent decides affected files & security boundaries
              </span>
            </div>
            <button
              type="button"
              onClick={() => setShowAdvancedOptions(!showAdvancedOptions)}
              className="text-[11px] text-muted-foreground hover:text-foreground underline flex items-center gap-1"
            >
              {showAdvancedOptions ? 'Hide Advanced Settings' : 'Advanced Settings (Optional)'}
            </button>
          </div>

          <div>
            <label className="text-[11px] font-semibold text-foreground block mb-1">
              What do you want the agent to do?
            </label>
            <textarea
              rows={3}
              required
              autoFocus
              value={newTaskPrompt}
              onChange={(e) => {
                setNewTaskPrompt(e.target.value);
                setNewTaskDesc(e.target.value);
              }}
              placeholder="Describe what must be built, fixed, or refactored (e.g. 'Fix negative amount validation in checkout and add unit tests'). The agent automatically inspects repository files, AST, and symbols to resolve target files and draft the plan."
              className="w-full px-3.5 py-2 text-xs rounded-lg border border-border bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/40 font-normal leading-relaxed"
            />
          </div>

          {/* Autonomous agent file discovery indicator */}
          <div className="flex items-center gap-2.5 text-[11px] text-muted-foreground bg-background/60 rounded-lg p-2.5 border border-border/60">
            <Bot className="h-4 w-4 text-emerald-500 shrink-0" />
            <div className="flex-1">
              <strong className="text-foreground">Autonomous Resolution:</strong> Write only your task above. The agent automatically discovers target files, enforces protected file shields, and prepares the implementation plan without requiring manual file inputs.
            </div>
          </div>

          {/* Collapsible Advanced Overrides */}
          {showAdvancedOptions && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 border-t border-border/40">
              <div>
                <label className="text-[11px] font-mono uppercase text-muted-foreground block mb-1">
                  Custom Task Title (Optional)
                </label>
                <input
                  type="text"
                  value={newTaskCustomTitle}
                  onChange={(e) => {
                    setNewTaskCustomTitle(e.target.value);
                    setNewTaskTitle(e.target.value);
                  }}
                  placeholder="Auto-derived from prompt if left blank"
                  className="w-full px-3 py-1.5 text-xs rounded-lg border border-border bg-background text-foreground"
                />
              </div>
              <div>
                <label className="text-[11px] font-mono uppercase text-muted-foreground block mb-1">
                  Manual Target Files Override (Optional)
                </label>
                <input
                  type="text"
                  value={newTaskFiles}
                  onChange={(e) => setNewTaskFiles(e.target.value)}
                  placeholder="Leave empty for autonomous agent detection"
                  className="w-full px-3 py-1.5 text-xs rounded-lg border border-border bg-background text-foreground font-mono"
                />
              </div>
              <div className="md:col-span-2">
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
          )}

          <div className="flex items-center justify-between pt-1">
            <label className="flex items-center gap-2 cursor-pointer text-xs text-foreground select-none">
              <input
                type="checkbox"
                checked={autoPlanImmediately}
                onChange={(e) => setAutoPlanImmediately(e.target.checked)}
                className="rounded border-border text-primary focus:ring-primary"
              />
              <span>Immediately generate plan with AI Agent</span>
            </label>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setShowNewTaskForm(false)}
                className="px-3 py-1 rounded-md border border-border text-xs hover:bg-muted"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={actionBusy === 'create' || actionBusy === 'plan'}
                className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-primary text-primary-foreground text-xs font-semibold hover:bg-primary/90 shadow-sm disabled:opacity-50"
              >
                {actionBusy === 'create' ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    <span>Creating Task…</span>
                  </>
                ) : actionBusy === 'plan' ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    <span>Agent Planning…</span>
                  </>
                ) : (
                  <>
                    <Sparkles className="h-3.5 w-3.5" />
                    <span>Start Autonomous Task</span>
                  </>
                )}
              </button>
            </div>
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
                {/* Row 1: Badges & Metadata */}
                <div className="flex items-center justify-between gap-2 flex-wrap">
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
                </div>

                {/* Row 2: Full-Width Task Title */}
                <h2 className="text-base sm:text-lg font-bold text-foreground break-words leading-relaxed w-full">
                  {taskDetail.title}
                </h2>

                {/* Row 3: Action Buttons Bar */}
                <div className="flex items-center justify-between gap-2 flex-wrap pt-1 border-t border-border/40">
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
                      className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-emerald-600 text-white text-xs font-semibold hover:bg-emerald-500 disabled:opacity-40"
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
                  </div>

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

                {/* Segregated Intake Summary: Requirements, Assumptions, Constraints */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-2 border-t border-border/60 text-xs">
                  <div className="rounded-lg bg-muted/20 border border-border/50 p-2.5 space-y-1 min-w-0">
                    <div className="text-[10px] font-mono uppercase text-primary font-bold">
                      Requirements ({taskDetail.requirements.length})
                    </div>
                    {taskDetail.requirements.map((r) => (
                      <div key={r.id} className="text-[11px] text-foreground/90 break-words">
                        • {r.description}
                        {r.target_files.length > 0 && (
                          <div className="text-[10px] font-mono text-muted-foreground mt-0.5 break-words">
                            Files: {r.target_files.join(', ')}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>

                  <div className="rounded-lg bg-muted/20 border border-border/50 p-2.5 space-y-1 min-w-0">
                    <div className="text-[10px] font-mono uppercase text-amber-400 font-bold">
                      Assumptions ({taskDetail.assumptions.length})
                    </div>
                    {taskDetail.assumptions.map((a) => (
                      <div key={a.id} className="text-[11px] text-foreground/90 break-words">
                        • {a.description}
                      </div>
                    ))}
                  </div>

                  <div className="rounded-lg bg-muted/20 border border-border/50 p-2.5 space-y-1 min-w-0">
                    <div className="text-[10px] font-mono uppercase text-rose-400 font-bold">
                      Protected Constraints ({taskDetail.constraints.length})
                    </div>
                    {taskDetail.constraints.map((c) => (
                      <div key={c.id} className="text-[11px] text-foreground/90 break-words">
                        • {c.description}
                        {c.forbidden_files.length > 0 && (
                          <div className="text-[10px] font-mono text-rose-300 mt-0.5 break-words">
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
                      'rounded-xl border p-4.5 space-y-3.5 transition-all',
                      isApproved
                        ? 'border-emerald-500/50 bg-gradient-to-r from-emerald-950/20 via-emerald-900/10 to-transparent'
                        : taskDetail.status === 'REJECTED'
                        ? 'border-rose-500/40 bg-gradient-to-r from-rose-950/20 via-rose-900/10 to-transparent'
                        : 'border-amber-500/50 bg-gradient-to-r from-amber-950/25 via-amber-900/10 to-transparent'
                    )}
                  >
                    {/* Header Banner */}
                    <div className="flex items-start justify-between gap-4 flex-wrap">
                      <div className="flex items-start gap-3 flex-1 min-w-0">
                        <div
                          className={cn(
                            'p-2 rounded-lg shrink-0 mt-0.5',
                            isApproved
                              ? 'bg-emerald-500/20 text-emerald-400'
                              : taskDetail.status === 'REJECTED'
                              ? 'bg-rose-500/20 text-rose-400'
                              : 'bg-amber-500/20 text-amber-400'
                          )}
                        >
                          {isApproved ? (
                            <ShieldCheck className="h-5 w-5" />
                          ) : taskDetail.status === 'REJECTED' ? (
                            <XCircle className="h-5 w-5" />
                          ) : (
                            <ShieldAlert className="h-5 w-5" />
                          )}
                        </div>
                        <div className="space-y-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span
                              className={cn(
                                'px-2 py-0.5 rounded text-[10px] font-mono font-bold tracking-wider uppercase',
                                isApproved
                                  ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                                  : taskDetail.status === 'REJECTED'
                                  ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                                  : 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                              )}
                            >
                              {isApproved
                                ? 'Plan Approved & Locked'
                                : taskDetail.status === 'REJECTED'
                                ? 'Plan Rejected'
                                : 'Human Approval Required'}
                            </span>
                            <span className="text-[11px] font-mono text-muted-foreground">
                              Plan v{latestPlan.plan_version}
                              {latestPlan.plan_hash ? ` • Hash: ${latestPlan.plan_hash.slice(0, 10)}` : ''}
                            </span>
                          </div>
                          <h4 className="text-sm font-bold text-foreground">
                            {isApproved
                              ? 'Plan Verified & Ready for Workspace Execution'
                              : taskDetail.status === 'REJECTED'
                              ? 'Plan Rejected — Revision Required'
                              : 'Human Approval Gate (ADR-009 Policy Boundary)'}
                          </h4>
                          <p className="text-xs text-muted-foreground leading-relaxed">
                            {isApproved
                              ? `Plan v${latestPlan.plan_version} is explicitly approved. Any change to the plan or base revision will automatically invalidate this approval.`
                              : taskDetail.status === 'REJECTED'
                              ? `Plan v${latestPlan.plan_version} was rejected. Execution is completely blocked until a revised plan is generated and approved.`
                              : `Autonomous workspace execution is blocked by backend policy until Plan v${latestPlan.plan_version} is explicitly approved by a human developer.`}
                          </p>
                        </div>
                      </div>

                      {/* Top Action Shortcut for Approved State */}
                      {isApproved && (
                        <div className="flex items-center gap-2 shrink-0">
                          <button
                            type="button"
                            disabled={actionBusy !== null}
                            onClick={() => handleExecuteTask(true)}
                            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold shadow-md shadow-emerald-950/40 transition-all hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50"
                          >
                            <Play className="h-4 w-4 fill-white" />
                            <span>Start Workspace Execution</span>
                          </button>
                        </div>
                      )}
                    </div>

                    {/* Approved State Footer */}
                    {isApproved && (
                      <div className="pt-2 border-t border-emerald-500/30 flex items-center justify-between flex-wrap gap-2 text-xs">
                        <span className="text-[11px] text-emerald-300/90 flex items-center gap-1.5">
                          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                          Ready for execution. Click &ldquo;Start Workspace Execution&rdquo; to launch isolated sandbox.
                        </span>
                        <button
                          type="button"
                          onClick={() => setShowApprovedRevision(!showApprovedRevision)}
                          className="text-[11px] text-muted-foreground hover:text-foreground underline transition-colors"
                        >
                          {showApprovedRevision ? 'Close Revision Controls' : 'Need Changes? Request Plan Revision or Reject'}
                        </button>
                      </div>
                    )}

                    {/* Pending Approval Gate Controls OR Approved Revision Dropdown */}
                    {(!isApproved || showApprovedRevision) && (
                      <div className="pt-3 border-t border-border/40 space-y-3">
                        {/* Primary Approval Row (Visible when not yet approved) */}
                        {!isApproved && taskDetail.status !== 'REJECTED' && (
                          <div className="p-3 rounded-lg bg-background/70 border border-emerald-500/30 space-y-2">
                            <span className="text-[11px] font-bold text-foreground flex items-center gap-1.5">
                              <ThumbsUp className="h-3.5 w-3.5 text-emerald-400" />
                              Approve Plan &amp; Unlock Autonomous Workspace
                            </span>
                            <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2.5">
                              <input
                                type="text"
                                value={approvalComment}
                                onChange={(e) => setApprovalComment(e.target.value)}
                                placeholder="Optional approval note or sign-off comment…"
                                className="flex-1 min-w-0 px-3 py-1.5 text-xs rounded-lg border border-border bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-emerald-500/40"
                              />
                              <button
                                type="button"
                                disabled={actionBusy !== null}
                                onClick={handleApprovePlan}
                                className="inline-flex items-center justify-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold shadow-sm shrink-0 transition-colors disabled:opacity-50"
                              >
                                {actionBusy === 'approve' ? (
                                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                ) : (
                                  <ThumbsUp className="h-3.5 w-3.5" />
                                )}
                                <span>Approve Plan v{latestPlan.plan_version}</span>
                              </button>
                            </div>
                          </div>
                        )}

                        {/* Revision & Rejection Actions: Clean 2-column layout with no overlap */}
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                          {/* Request Changes / Revise Plan */}
                          <div className="p-3 rounded-lg bg-background/60 border border-border/60 space-y-2 min-w-0">
                            <div className="flex items-center justify-between">
                              <span className="text-[11px] font-semibold text-foreground flex items-center gap-1.5">
                                <RefreshCw className="h-3 w-3 text-primary" />
                                Request Plan Revision
                              </span>
                              <span className="text-[10px] font-mono text-muted-foreground">
                                Synthesizes v{latestPlan.plan_version + 1}
                              </span>
                            </div>
                            <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
                              <input
                                type="text"
                                value={revisionNotes}
                                onChange={(e) => setRevisionNotes(e.target.value)}
                                placeholder="Feedback for AI planner…"
                                className="flex-1 min-w-0 px-2.5 py-1.5 text-xs rounded-md border border-border bg-background text-foreground placeholder:text-muted-foreground"
                              />
                              <button
                                type="button"
                                disabled={actionBusy !== null || !revisionNotes.trim()}
                                onClick={handleGenerateOrRevisePlan}
                                className="inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md border border-border bg-card hover:bg-accent text-xs font-semibold shrink-0 disabled:opacity-40"
                              >
                                {actionBusy === 'plan' ? (
                                  <Loader2 className="h-3 w-3 animate-spin" />
                                ) : (
                                  <Sparkles className="h-3 w-3 text-primary" />
                                )}
                                <span>Revise</span>
                              </button>
                            </div>
                          </div>

                          {/* Reject Plan */}
                          <div className="p-3 rounded-lg bg-background/60 border border-border/60 space-y-2 min-w-0">
                            <div className="flex items-center justify-between">
                              <span className="text-[11px] font-semibold text-rose-400 flex items-center gap-1.5">
                                <ThumbsDown className="h-3 w-3" />
                                Reject Plan
                              </span>
                              <span className="text-[10px] font-mono text-muted-foreground">
                                Blocks execution
                              </span>
                            </div>
                            <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
                              <input
                                type="text"
                                value={rejectionReason}
                                onChange={(e) => setRejectionReason(e.target.value)}
                                placeholder="Reason for rejection…"
                                className="flex-1 min-w-0 px-2.5 py-1.5 text-xs rounded-md border border-border bg-background text-foreground placeholder:text-muted-foreground"
                              />
                              <button
                                type="button"
                                disabled={actionBusy !== null}
                                onClick={handleRejectPlan}
                                className="inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md bg-rose-600/90 hover:bg-rose-600 text-white text-xs font-semibold shrink-0 disabled:opacity-40"
                              >
                                {actionBusy === 'reject' ? (
                                  <Loader2 className="h-3 w-3 animate-spin" />
                                ) : (
                                  <ThumbsDown className="h-3 w-3" />
                                )}
                                <span>Reject</span>
                              </button>
                            </div>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Structured Plan Summary & Steps */}
                  <div className="rounded-xl border border-border bg-card p-4 space-y-4">
                    <div className="space-y-1">
                      <div className="text-[10px] font-mono uppercase text-primary font-bold">
                        Plan Summary (v{latestPlan.plan_version})
                      </div>
                      <p className="text-sm font-medium text-foreground leading-snug break-words">{latestPlan.summary}</p>
                      {latestPlan.problem_statement && (
                        <p className="text-xs text-muted-foreground break-words">{latestPlan.problem_statement}</p>
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
                          className="rounded-lg border border-border/70 bg-muted/15 p-3 space-y-2 min-w-0 overflow-hidden"
                        >
                          <div className="flex items-start justify-between gap-2.5">
                            <div className="flex items-center gap-2 flex-wrap flex-1 min-w-0">
                              <span className="px-2 py-0.5 rounded bg-primary/15 text-primary font-mono text-[10px] font-bold shrink-0">
                                #{idx + 1} • {step.step_id}
                              </span>
                              <span className="px-2 py-0.5 rounded border border-border text-[10px] font-mono uppercase text-muted-foreground shrink-0">
                                {step.action_type || step.step_type}
                              </span>
                              <span className="text-xs font-semibold text-foreground break-words">
                                {step.title}
                              </span>
                            </div>
                            <span
                              className={cn(
                                'px-2 py-0.5 rounded border text-[10px] font-mono uppercase shrink-0',
                                RISK_BADGE_MAP[step.risk_level || 'low'] || RISK_BADGE_MAP.low
                              )}
                            >
                              Risk: {step.risk_level || 'low'}
                            </span>
                          </div>

                          <p className="text-xs text-muted-foreground leading-relaxed break-words">{step.description}</p>

                          <div className="flex flex-wrap gap-3 text-[11px] font-mono text-muted-foreground">
                            {step.expected_files.length > 0 && (
                              <span className="inline-flex items-center gap-1 break-all">
                                <FileCode className="h-3 w-3 text-primary shrink-0" />
                                <span>Files: {step.expected_files.join(', ')}</span>
                              </span>
                            )}
                            {(step.depends_on || step.dependencies || []).length > 0 && (
                              <span className="break-words">
                                Depends on: {(step.depends_on || step.dependencies || []).join(', ')}
                              </span>
                            )}
                          </div>

                          {step.verification.length > 0 && (
                            <div className="text-[11px] text-emerald-400/90 font-mono break-words">
                              ✓ Verification: {step.verification.join(' | ')}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>

                    {/* Expected Files, Tests to Run, Validation Strategy & Risks */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 border-t border-border/60 text-xs">
                      {/* Column 1: Files & Tests */}
                      <div className="rounded-lg bg-muted/20 border border-border/50 p-3 space-y-2 min-w-0 overflow-hidden">
                        <div className="text-[10px] font-mono uppercase text-primary font-bold tracking-wider">
                          Expected Files &amp; Permitted Tests
                        </div>
                        <div className="space-y-2">
                          <div>
                            <span className="text-[10px] font-mono text-muted-foreground uppercase block mb-1">
                              Files to Modify ({(latestPlan.expected_files || latestPlan.expected_files_to_modify || []).length})
                            </span>
                            <div className="flex flex-wrap gap-1.5">
                              {(latestPlan.expected_files || latestPlan.expected_files_to_modify || []).length > 0 ? (
                                (latestPlan.expected_files || latestPlan.expected_files_to_modify || []).map((f: string) => (
                                  <span
                                    key={f}
                                    className="px-2 py-0.5 rounded bg-background border border-border text-[11px] font-mono text-foreground/90 break-all inline-block"
                                  >
                                    {f}
                                  </span>
                                ))
                              ) : (
                                <span className="text-muted-foreground italic text-[11px]">No specific files locked</span>
                              )}
                            </div>
                          </div>

                          <div className="pt-1.5 border-t border-border/40">
                            <span className="text-[10px] font-mono text-muted-foreground uppercase block mb-1">
                              Automated Tests to Run
                            </span>
                            <div className="flex flex-wrap gap-1.5">
                              {(latestPlan.tests_to_run || latestPlan.tests_to_add || ['pytest']).map((t: string) => (
                                <span
                                  key={t}
                                  className="px-2 py-0.5 rounded bg-sky-500/10 border border-sky-500/30 text-[11px] font-mono text-sky-300 inline-block"
                                >
                                  {t}
                                </span>
                              ))}
                            </div>
                          </div>
                        </div>
                      </div>

                      {/* Column 2: Risks & Resource Budget */}
                      <div className="rounded-lg bg-muted/20 border border-border/50 p-3 space-y-2 min-w-0 overflow-hidden">
                        <div className="text-[10px] font-mono uppercase text-amber-400 font-bold tracking-wider">
                          Risks &amp; Resource Budget
                        </div>
                        <div className="space-y-1.5">
                          {(latestPlan.risks || []).length > 0 ? (
                            (latestPlan.risks || []).map((r: any, i: number) => (
                              <div key={r.id || i} className="text-[11px] text-foreground/90 leading-snug break-words">
                                <span className="font-mono text-amber-400 font-bold">
                                  [{String(r.severity || 'medium').toUpperCase()}]
                                </span>{' '}
                                {r.description || String(r)}
                                {r.mitigation && (
                                  <span className="text-muted-foreground block text-[10px] mt-0.5">
                                    ↳ Mitigation: {r.mitigation}
                                  </span>
                                )}
                              </div>
                            ))
                          ) : (
                            <div className="text-muted-foreground text-[11px] italic">No high-risk vectors detected</div>
                          )}

                          {latestPlan.resource_budget && (
                            <div className="text-[10px] font-mono text-muted-foreground pt-1.5 border-t border-border/40 flex items-center justify-between flex-wrap gap-2">
                              <span>Max Repairs: <strong>{latestPlan.resource_budget.max_repair_attempts ?? 3}</strong> attempts</span>
                              <span>Token Budget: <strong>{latestPlan.resource_budget.max_tokens ?? 20000}</strong> tokens</span>
                            </div>
                          )}
                        </div>
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
