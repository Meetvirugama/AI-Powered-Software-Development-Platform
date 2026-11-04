/**
 * RepositoryTaskStudio — Autonomous AI Developer Studio
 *
 * Professional, intuitive, and modern engineering sub-application:
 * - Visual interactive 6-stage workflow pipeline (Plan -> Execute -> Test -> Diff -> Verify -> Ship PR)
 * - Hero Next-Step Action Bar with plain-English guidance and one-click primary CTAs
 * - Tabbed workspace views eliminating clutter and cognitive overload
 * - One-click "⚡ Auto-Pilot" mode for automated planning, execution, and verification
 * - Sleek prompt-driven Task Intake modal with quick starter templates
 * - Comprehensive code diff inspector, test runner, quality gates, and GitHub PR integration
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
  FileDiff,
  FlaskConical,
  FolderGit2,
  GitBranch,
  GitCommit,
  GitPullRequest,
  History,
  ListChecks,
  Loader2,
  Pause,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldCheck,
  Slash,
  Sparkles,
  Terminal,
  Wrench,
  X,
  XCircle,
  Zap,
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
import { CodeChangesPanel } from '../components/tasks/CodeChangesPanel';
import { TestExecutionPanel } from '../components/tasks/TestExecutionPanel';
import { VerificationPanel } from '../components/tasks/VerificationPanel';
import { ExecutionTimeline } from '../components/tasks/ExecutionTimeline';

const STATUS_BADGE_MAP: Record<
  string,
  { label: string; className: string; icon: typeof CheckCircle2 }
> = {
  CREATED: {
    label: 'Created',
    className: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
    icon: Clock,
  },
  PLANNING: {
    label: 'Planning…',
    className: 'bg-blue-500/15 text-blue-300 border-blue-500/30',
    icon: Bot,
  },
  PENDING_APPROVAL: {
    label: 'Pending Approval',
    className: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
    icon: Clock,
  },
  APPROVED: {
    label: 'Plan Approved',
    className: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40',
    icon: CheckCircle2,
  },
  REJECTED: {
    label: 'Plan Rejected',
    className: 'bg-rose-500/15 text-rose-300 border-rose-500/40',
    icon: XCircle,
  },
  WORKSPACE_SETUP: {
    label: 'Setting Up Sandbox',
    className: 'bg-indigo-500/15 text-indigo-300 border-indigo-500/40',
    icon: Terminal,
  },
  EXECUTING: {
    label: 'Agent Executing',
    className: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/40',
    icon: Zap,
  },
  TESTING: {
    label: 'Running Tests',
    className: 'bg-sky-500/15 text-sky-300 border-sky-500/40',
    icon: FlaskConical,
  },
  REPAIRING: {
    label: 'Self-Repairing',
    className: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
    icon: Wrench,
  },
  VERIFYING: {
    label: 'Verifying Quality',
    className: 'bg-teal-500/15 text-teal-300 border-teal-500/40',
    icon: ShieldCheck,
  },
  READY_FOR_PUBLICATION: {
    label: 'Ready to Ship',
    className: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40',
    icon: CheckCircle2,
  },
  PUBLISHING: {
    label: 'Publishing PR…',
    className: 'bg-purple-500/15 text-purple-300 border-purple-500/40',
    icon: GitPullRequest,
  },
  DRAFT_PR_CREATED: {
    label: 'Draft PR Created',
    className: 'bg-purple-500/15 text-purple-300 border-purple-500/40',
    icon: GitPullRequest,
  },
  RECOVERY_REQUIRED: {
    label: 'Recovery Needed',
    className: 'bg-orange-500/15 text-orange-300 border-orange-500/40',
    icon: AlertTriangle,
  },
  BLOCKED: {
    label: 'Blocked',
    className: 'bg-rose-500/15 text-rose-300 border-rose-500/40',
    icon: XCircle,
  },
  FAILED: {
    label: 'Failed',
    className: 'bg-rose-500/15 text-rose-300 border-rose-500/40',
    icon: XCircle,
  },
  CANCELLED: {
    label: 'Cancelled',
    className: 'bg-zinc-500/15 text-zinc-400 border-zinc-500/40',
    icon: Slash,
  },
};

type StudioTab = 'plan' | 'workspace' | 'tests' | 'changes' | 'verification' | 'pr';

function getRecommendedTabForStatus(status?: string): StudioTab {
  if (!status) return 'plan';
  if (status === 'CREATED' || status === 'PLANNING' || status === 'PENDING_APPROVAL') return 'plan';
  if (status === 'APPROVED' || status === 'WORKSPACE_SETUP' || status === 'EXECUTING') return 'workspace';
  if (status === 'TESTING' || status === 'REPAIRING') return 'tests';
  if (status === 'VERIFYING') return 'verification';
  if (status === 'READY_FOR_PUBLICATION' || status === 'PUBLISHING' || status === 'DRAFT_PR_CREATED') return 'pr';
  return 'changes';
}

const STARTER_PROMPTS = [
  { label: '🎨 Change CSS Theme / Colors', text: 'Change page background color to white and refine dark mode theme' },
  { label: '🐛 Fix Negative Amount Bug', text: 'Fix negative amount validation in checkout and add unit test coverage' },
  { label: '⚡ Add API Rate Limiter', text: 'Add token bucket rate limiting middleware for public endpoints' },
  { label: '🧪 Generate Pytest Suite', text: 'Generate comprehensive unit tests for core validation services' },
];

export function RepositoryTaskStudio() {
  const { id } = useParams<{ id: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const repoId = id ?? '';

  const queryClient = useQueryClient();
  const [errorBanner, setErrorBanner] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState<string | null>(null);

  // Active studio tab
  const [userSelectedTab, setUserSelectedTab] = useState<StudioTab | null>(null);
  const [taskSearchFilter, setTaskSearchFilter] = useState('');

  // New Task Modal State
  const [showNewTaskModal, setShowNewTaskModal] = useState(false);
  const [newTaskPrompt, setNewTaskPrompt] = useState('');
  const [autoPilotOnCreate, setAutoPilotOnCreate] = useState(false);

  // Import Issue Form State
  const [showImportIssueModal, setShowImportIssueModal] = useState(false);
  const [issueNumberInput, setIssueNumberInput] = useState('');

  // Human Review Input State
  const [approvalComment, setApprovalComment] = useState('');
  const [revisionNotes, setRevisionNotes] = useState('');
  const [showRevisionInput, setShowRevisionInput] = useState(false);
  const [rejectionReason, setRejectionReason] = useState('');
  const [showRejectionInput, setShowRejectionInput] = useState(false);
  const [publicationAuthorized, setPublicationAuthorized] = useState(false);

  // Query: Repository Task List
  const {
    data: taskListData,
    isLoading: loadingTasks,
  } = useTasks({ repository_id: repoId });
  const tasks: TaskSummary[] = useMemo(() => taskListData?.items ?? [], [taskListData?.items]);

  // Task Selection
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
      setUserSelectedTab(null);
      setSelectedTaskId(taskId);
      setSearchParams({ taskId });
      setErrorBanner(null);
    },
    [setSearchParams]
  );

  // Query: Active Task Detail
  const {
    data: taskDetailData,
    isLoading: loadingDetail,
  } = useTask(activeTaskId ?? undefined, { enabled: isTaskActive });
  const taskDetail = (isTaskActive ? taskDetailData : null) as TaskDetail | null;

  // Query: Events, Workspace, Tests, Repair, Verification, Draft PR
  const { data: eventsData } = useTaskEvents(activeTaskId ?? undefined, undefined, {
    enabled: isTaskActive,
  });
  const events: TaskEvent[] = isTaskActive
    ? ((eventsData?.items as unknown as TaskEvent[]) ?? [])
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
  const repairAttemptsUsed = repairBudgetData?.repair_attempts_used ?? taskDetail?.repair_attempts_used ?? 0;
  const repairAttemptsMax = repairBudgetData?.repair_attempts_max ?? taskDetail?.repair_attempts_max ?? 3;

  const { data: verificationData } = useTaskVerification(activeTaskId ?? undefined, {
    enabled: isTaskActive,
  });
  const verificationResult = isTaskActive ? (verificationData ?? null) : null;

  const { data: draftPRData } = useTaskPullRequest(activeTaskId ?? undefined, {
    enabled: isTaskActive,
  });
  const draftPR = (isTaskActive ? (draftPRData ?? null) : null) as TaskPullRequestResponse | null;

  // Active studio tab: defaults to recommended tab for current status, but preserves user click
  const activeTab: StudioTab = userSelectedTab ?? getRecommendedTabForStatus(taskDetail?.status);
  const setActiveTab = (tab: StudioTab) => setUserSelectedTab(tab);

  // Global Refresher
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
          queryClient.invalidateQueries({ queryKey: taskKeys.diff(tid) }),
        ]);
      }
    },
    [activeTaskId, queryClient]
  );

  // Latest plan helper
  const latestPlan = useMemo(() => {
    return taskDetail?.latest_plan || null;
  }, [taskDetail]);

  const hasWorkspace = Boolean(workspaceMeta);

  // Filtered task list
  const filteredTasks = useMemo(() => {
    if (!taskSearchFilter.trim()) return tasks;
    const q = taskSearchFilter.toLowerCase();
    return tasks.filter(
      (t) =>
        t.title.toLowerCase().includes(q) ||
        t.status.toLowerCase().includes(q) ||
        (t.source_type && t.source_type.toLowerCase().includes(q))
    );
  }, [tasks, taskSearchFilter]);

  // --- Task Action Handlers ---

  async function handleCreateNewTask(e?: React.FormEvent) {
    if (e) e.preventDefault();
    const prompt = newTaskPrompt.trim();
    if (!prompt) return;

    const firstLine = prompt.split('\n')[0].replace(/^[\s#*•-]+/, '');
    const finalTitle = firstLine.length > 70 ? firstLine.slice(0, 67) + '...' : firstLine || 'Autonomous Task';

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
            target_files: [],
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
            forbidden_files: ['.env', '.github/workflows/deploy.yml'],
            forbidden_packages: [],
          },
        ],
      });

      setShowNewTaskModal(false);
      setNewTaskPrompt('');
      handleSelectTask(created.task_id);

      try {
        await generateTaskPlan(created.task_id, {
          prompt_instructions: `Autonomous plan for: ${prompt}`,
        });
        if (autoPilotOnCreate) {
          await approveTaskPlan(created.task_id, { comment: 'Auto-pilot instant approval' });
          await executeTask(created.task_id, { run_steps: true, run_tests_after: true, auto_repair: true });
        }
      } catch {
        // Non-blocking
      }
    } catch (err: any) {
      setErrorBanner(err?.message || 'Failed to create task.');
    } finally {
      await refreshTasksAndCurrentDetail();
      setActionBusy(null);
    }
  }

  async function handleImportIssue(e: React.FormEvent) {
    e.preventDefault();
    const num = parseInt(issueNumberInput.trim(), 10);
    if (isNaN(num) || num < 1) return;

    setActionBusy('import');
    setErrorBanner(null);
    try {
      const created = await importGitHubIssue(repoId, { issue_number: num });
      setIssueNumberInput('');
      setShowImportIssueModal(false);
      handleSelectTask(created.task_id);
    } catch (err: any) {
      setErrorBanner(err?.message || `Failed to import issue #${num}.`);
    } finally {
      await refreshTasksAndCurrentDetail();
      setActionBusy(null);
    }
  }

  async function handleApprovePlan() {
    if (!taskDetail || !latestPlan) return;
    setActionBusy('approve');
    setErrorBanner(null);
    try {
      await approveTaskPlan(taskDetail.task_id, {
        plan_version: latestPlan.plan_version,
        comment: approvalComment.trim() || 'Plan approved by user via Studio.',
      });
      setApprovalComment('');
    } catch (err: any) {
      setErrorBanner(err?.message || 'Failed to approve plan.');
    } finally {
      await refreshTasksAndCurrentDetail(taskDetail.task_id);
      setActionBusy(null);
    }
  }

  async function handleApproveAndExecute() {
    if (!taskDetail || !latestPlan) return;
    setActionBusy('approve-execute');
    setErrorBanner(null);
    try {
      if (taskDetail.status !== 'APPROVED') {
        await approveTaskPlan(taskDetail.task_id, {
          plan_version: latestPlan.plan_version,
          comment: 'Plan approved with instant execution launch.',
        });
      }
      setActiveTab('workspace');
      await executeTask(taskDetail.task_id, { run_steps: true });
    } catch (err: any) {
      setErrorBanner(err?.message || 'Execution failed or blocked by gate.');
    } finally {
      await refreshTasksAndCurrentDetail(taskDetail.task_id);
      setActionBusy(null);
    }
  }

  async function handleExecuteTask(runSteps = true) {
    if (!taskDetail) return;
    const tid = taskDetail.task_id;
    setActionBusy('execute');
    setErrorBanner(null);
    try {
      setActiveTab('workspace');
      await executeTask(tid, { run_steps: runSteps });
    } catch (err: any) {
      setErrorBanner(err?.message || 'Execution blocked by approval gate.');
    } finally {
      await refreshTasksAndCurrentDetail(tid);
      setActionBusy(null);
    }
  }

  async function handleRunAutoPilot() {
    if (!taskDetail) return;
    const tid = taskDetail.task_id;
    setActionBusy('autopilot');
    setErrorBanner(null);
    try {
      if (taskDetail.status === 'PENDING_APPROVAL' && latestPlan) {
        await approveTaskPlan(tid, {
          plan_version: latestPlan.plan_version,
          comment: 'Auto-pilot approval',
        });
      }
      setActiveTab('workspace');
      await executeTask(tid, {
        run_steps: true,
        run_tests_after: true,
        auto_repair: true,
      });
    } catch (err: any) {
      setErrorBanner(err?.message || 'Auto-pilot pipeline encountered an error.');
    } finally {
      await refreshTasksAndCurrentDetail(tid);
      setActionBusy(null);
    }
  }

  async function handleGenerateOrRevisePlan() {
    if (!taskDetail) return;
    setActionBusy('plan');
    setErrorBanner(null);
    try {
      await generateTaskPlan(taskDetail.task_id, {
        prompt_instructions: revisionNotes.trim() || undefined,
      });
      setRevisionNotes('');
      setShowRevisionInput(false);
    } catch (err: any) {
      setErrorBanner(err?.message || 'Failed to synthesize implementation plan.');
    } finally {
      await refreshTasksAndCurrentDetail(taskDetail.task_id);
      setActionBusy(null);
    }
  }

  async function handleRejectPlan() {
    if (!taskDetail) return;
    setActionBusy('reject');
    setErrorBanner(null);
    try {
      await rejectTaskPlan(taskDetail.task_id, {
        reason: rejectionReason.trim() || 'Plan rejected by user.',
      });
      setRejectionReason('');
      setShowRejectionInput(false);
    } catch (err: any) {
      setErrorBanner(err?.message || 'Failed to reject plan.');
    } finally {
      await refreshTasksAndCurrentDetail(taskDetail.task_id);
      setActionBusy(null);
    }
  }

  async function handlePauseTask() {
    if (!taskDetail) return;
    setActionBusy('pause');
    setErrorBanner(null);
    try {
      await pauseTask(taskDetail.task_id);
    } catch (err: any) {
      setErrorBanner(err?.message || 'Failed to pause workspace execution.');
    } finally {
      await refreshTasksAndCurrentDetail(taskDetail.task_id);
      setActionBusy(null);
    }
  }

  async function handleResumeTask() {
    if (!taskDetail) return;
    setActionBusy('resume');
    setErrorBanner(null);
    try {
      await resumeTask(taskDetail.task_id);
    } catch (err: any) {
      setErrorBanner(err?.message || 'Failed to resume workspace execution.');
    } finally {
      await refreshTasksAndCurrentDetail(taskDetail.task_id);
      setActionBusy(null);
    }
  }

  async function handleCancelTask() {
    if (!taskDetail) return;
    setActionBusy('cancel');
    setErrorBanner(null);
    try {
      await cancelTask(taskDetail.task_id);
    } catch (err: any) {
      setErrorBanner(err?.message || 'Failed to cancel task.');
    } finally {
      await refreshTasksAndCurrentDetail(taskDetail.task_id);
      setActionBusy(null);
    }
  }

  async function handleRunTests() {
    if (!taskDetail) return;
    const tid = taskDetail.task_id;
    setActionBusy('tests');
    setErrorBanner(null);
    try {
      setActiveTab('tests');
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
      setActiveTab('tests');
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
      setActiveTab('verification');
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
        message: `feat(agent): implement ${taskDetail.title}`,
      });
    } catch (err: any) {
      setErrorBanner(err?.message || 'Failed to commit changes in isolated workspace.');
    } finally {
      await refreshTasksAndCurrentDetail(taskDetail.task_id);
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
    } catch (err: any) {
      setErrorBanner(
        err?.message || 'Publication blocked: Independent verification and authorization are required.'
      );
    } finally {
      await refreshTasksAndCurrentDetail(taskDetail.task_id);
      setActionBusy(null);
    }
  }

  async function handleRecoverTask() {
    if (!taskDetail) return;
    setActionBusy('recover');
    setErrorBanner(null);
    try {
      await recoverTask(taskDetail.task_id);
    } catch (err: any) {
      setErrorBanner(err?.message || 'Failed to recover task state.');
    } finally {
      await refreshTasksAndCurrentDetail(taskDetail.task_id);
      setActionBusy(null);
    }
  }

  // Determine the primary next step recommendation for the user
  const nextStepInfo = useMemo(() => {
    if (!taskDetail) return null;
    const st = taskDetail.status;

    if (st === 'CREATED' || st === 'PLANNING') {
      return {
        stage: 'Planning',
        headline: 'AI Agent is Analyzing Code & Drafting Plan',
        description: 'Inspecting repository AST, symbol dependencies, and target files.',
        actionLabel: 'Regenerate Plan',
        actionIcon: Bot,
        actionType: 'generate_plan',
        color: 'blue',
      };
    }
    if (st === 'PENDING_APPROVAL') {
      return {
        stage: 'Approval',
        headline: `Plan v${latestPlan?.plan_version ?? 1} Ready for Review`,
        description: 'Review the planned steps below. One-click approval launches the isolated agent.',
        actionLabel: 'Approve & Start Execution',
        actionIcon: Play,
        actionType: 'approve_and_execute',
        color: 'emerald',
      };
    }
    if (st === 'APPROVED') {
      return {
        stage: 'Execution',
        headline: 'Plan Approved — Ready to Launch Autonomous Agent',
        description: 'Sandbox workspace will be provisioned on an isolated git branch.',
        actionLabel: 'Start Workspace Execution',
        actionIcon: Play,
        actionType: 'execute',
        color: 'emerald',
      };
    }
    if (st === 'WORKSPACE_SETUP' || st === 'EXECUTING') {
      return {
        stage: 'Execution',
        headline: 'Agent Actively Working in Isolated Sandbox',
        description: `Running implementation steps on branch '${workspaceMeta?.branch_name || 'agent/task'}'...`,
        actionLabel: 'View Active Sandbox',
        actionIcon: Terminal,
        actionType: 'tab_workspace',
        color: 'cyan',
        inProgress: true,
      };
    }
    if (st === 'TESTING' || st === 'REPAIRING') {
      return {
        stage: 'Testing',
        headline: 'Executing Automated Test Suite & Self-Healing',
        description: 'Running pytest verification to ensure zero regressions.',
        actionLabel: 'View Test Results',
        actionIcon: FlaskConical,
        actionType: 'tab_tests',
        color: 'sky',
        inProgress: true,
      };
    }
    if (st === 'VERIFYING') {
      return {
        stage: 'Verification',
        headline: 'Running Independent Quality & Security Verification',
        description: 'Verifying diff boundaries, secrets scan, and static analysis.',
        actionLabel: 'Inspect Verification Gates',
        actionIcon: ShieldCheck,
        actionType: 'tab_verification',
        color: 'teal',
        inProgress: true,
      };
    }
    if (st === 'READY_FOR_PUBLICATION') {
      return {
        stage: 'Publish',
        headline: 'All Verification Gates Passed — Ready to Open Pull Request',
        description: 'Code is verified, tests pass, and isolated git branch is ready to ship.',
        actionLabel: 'Review & Open GitHub PR',
        actionIcon: GitPullRequest,
        actionType: 'tab_pr',
        color: 'purple',
      };
    }
    if (st === 'DRAFT_PR_CREATED') {
      return {
        stage: 'Shipped',
        headline: 'Draft Pull Request Published to GitHub!',
        description: `Tracked under PR #${draftPR?.pr_number ?? 'draft'}. Ready for team code review.`,
        actionLabel: 'View Pull Request on GitHub',
        actionIcon: ExternalLink,
        actionType: 'open_pr',
        color: 'purple',
      };
    }
    if (st === 'RECOVERY_REQUIRED' || st === 'FAILED') {
      return {
        stage: 'Recovery',
        headline: 'Execution Interrupted — Rollback Available',
        description: 'Safely recover previous checkpoint or re-run planning.',
        actionLabel: 'Recover Task State',
        actionIcon: RotateCcw,
        actionType: 'recover',
        color: 'orange',
      };
    }

    return {
      stage: 'Inspect',
      headline: `Task Status: ${st.replace(/_/g, ' ')}`,
      description: 'Inspect workspace files, test results, or audit timeline.',
      actionLabel: 'Inspect Code Changes',
      actionIcon: FileDiff,
      actionType: 'tab_changes',
      color: 'slate',
    };
  }, [
    taskDetail,
    latestPlan?.plan_version,
    workspaceMeta?.branch_name,
    draftPR?.pr_number,
  ]);

  const handlePrimaryStepAction = () => {
    if (!nextStepInfo) return;
    switch (nextStepInfo.actionType) {
      case 'generate_plan':
        handleGenerateOrRevisePlan();
        break;
      case 'approve_and_execute':
        handleApproveAndExecute();
        break;
      case 'execute':
        handleExecuteTask(true);
        break;
      case 'tab_workspace':
        setActiveTab('workspace');
        break;
      case 'tab_tests':
        setActiveTab('tests');
        break;
      case 'tab_verification':
        setActiveTab('verification');
        break;
      case 'tab_pr':
        setActiveTab('pr');
        break;
      case 'open_pr':
        if (draftPR?.pr_url) window.open(draftPR.pr_url, '_blank');
        break;
      case 'recover':
        handleRecoverTask();
        break;
      default:
        setActiveTab('changes');
        break;
    }
  };

  return (
    <div className="flex flex-col h-full bg-background text-foreground overflow-hidden font-sans select-none">
      {/* -------------------------------------------------------------------- */}
      {/* 1. Autonomous Studio Topbar                                          */}
      {/* -------------------------------------------------------------------- */}
      <header className="h-13 shrink-0 border-b border-border bg-card/60 px-4 flex items-center justify-between gap-3 backdrop-blur-md">
        <div className="flex items-center gap-2.5">
          <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-primary to-indigo-600 flex items-center justify-center text-primary-foreground shadow-sm">
            <Sparkles className="h-4 w-4" />
          </div>
          <div>
            <div className="flex items-center gap-1.5 text-xs font-bold text-foreground">
              <span>Autonomous AI Developer Studio</span>
              <span className="px-1.5 py-0.2 rounded text-[10px] font-mono bg-primary/10 text-primary border border-primary/20">
                PRO
              </span>
            </div>
            <div className="text-[10px] text-muted-foreground flex items-center gap-1 font-mono">
              <FolderGit2 className="h-3 w-3 text-primary/70" />
              <span>CareerPath-Pro</span>
              <span>/</span>
              <GitBranch className="h-3 w-3 text-muted-foreground/70" />
              <span>main</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowImportIssueModal(true)}
            className="hidden sm:inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded-lg border border-border bg-background hover:bg-accent text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
          >
            <GitPullRequest className="h-3.5 w-3.5 text-primary" />
            <span>Import Issue</span>
          </button>

          <button
            type="button"
            onClick={() => refreshTasksAndCurrentDetail()}
            disabled={actionBusy !== null}
            className="p-1.5 rounded-lg border border-border bg-background hover:bg-accent text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
            title="Refresh Studio State"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', actionBusy && 'animate-spin')} />
          </button>

          <button
            type="button"
            onClick={() => setShowNewTaskModal(true)}
            className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-all shadow-sm shadow-primary/20 cursor-pointer"
          >
            <Plus className="h-3.5 w-3.5" />
            <span>New Task</span>
          </button>
        </div>
      </header>

      {/* -------------------------------------------------------------------- */}
      {/* Error Alert Banner                                                   */}
      {/* -------------------------------------------------------------------- */}
      {errorBanner && (
        <div className="shrink-0 bg-rose-500/10 border-b border-rose-500/30 px-4 py-2.5 text-xs text-rose-300 flex items-center justify-between gap-3 animate-in fade-in duration-200">
          <div className="flex items-center gap-2 min-w-0">
            <AlertTriangle className="h-4 w-4 shrink-0 text-rose-400" />
            <span className="truncate">{errorBanner}</span>
          </div>
          <button
            type="button"
            onClick={() => setErrorBanner(null)}
            className="text-xs text-rose-400 hover:text-rose-200 font-semibold underline shrink-0 cursor-pointer"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* -------------------------------------------------------------------- */}
      {/* 2. Main Studio Workspace Layout                                      */}
      {/* -------------------------------------------------------------------- */}
      <div className="flex-1 min-h-0 flex overflow-hidden">
        {/* Left Sidebar: Task List */}
        <aside className="w-72 sm:w-80 shrink-0 border-r border-border bg-card/30 flex flex-col min-h-0">
          <div className="p-3 border-b border-border/60 flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <input
                type="text"
                placeholder="Search tasks..."
                value={taskSearchFilter}
                onChange={(e) => setTaskSearchFilter(e.target.value)}
                className="w-full pl-8 pr-2.5 py-1 text-xs rounded-md border border-border bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
              />
            </div>
            <span className="text-[10px] font-mono text-muted-foreground px-1.5 py-0.5 rounded bg-muted">
              {filteredTasks.length}
            </span>
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto p-2 space-y-1.5">
            {loadingTasks && tasks.length === 0 ? (
              <div className="p-8 text-center text-xs text-muted-foreground space-y-2">
                <Loader2 className="h-5 w-5 animate-spin mx-auto text-primary" />
                <p>Loading agent tasks…</p>
              </div>
            ) : filteredTasks.length === 0 ? (
              <div className="p-8 text-center text-xs text-muted-foreground space-y-3">
                <Bot className="h-8 w-8 text-muted-foreground/40 mx-auto" />
                <p>No tasks found.</p>
                <button
                  type="button"
                  onClick={() => setShowNewTaskModal(true)}
                  className="px-3 py-1.5 rounded-md bg-primary/10 hover:bg-primary/20 text-primary text-xs font-medium transition-colors cursor-pointer"
                >
                  Create First Task
                </button>
              </div>
            ) : (
              filteredTasks.map((t) => {
                const isSelected = t.task_id === activeTaskId;
                const badge = STATUS_BADGE_MAP[t.status] || STATUS_BADGE_MAP.CREATED;
                const BadgeIcon = badge.icon;
                return (
                  <button
                    key={t.task_id}
                    type="button"
                    onClick={() => handleSelectTask(t.task_id)}
                    className={cn(
                      'w-full text-left p-2.5 rounded-lg border transition-all cursor-pointer space-y-1.5',
                      isSelected
                        ? 'bg-primary/10 border-primary/50 shadow-xs'
                        : 'bg-card/40 border-border/50 hover:bg-muted/40 hover:border-border'
                    )}
                  >
                    <div className="flex items-center justify-between gap-1.5">
                      <span
                        className={cn(
                          'inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold border',
                          badge.className
                        )}
                      >
                        <BadgeIcon className="h-2.5 w-2.5" />
                        <span>{badge.label}</span>
                      </span>
                      <span className="text-[10px] font-mono text-muted-foreground">
                        {t.source_type || 'TASK'}
                      </span>
                    </div>

                    <div className="text-xs font-semibold text-foreground line-clamp-2 leading-snug">
                      {t.title}
                    </div>

                    <div className="flex items-center justify-between text-[10px] font-mono text-muted-foreground/80">
                      <span>{t.task_id.slice(0, 8)}</span>
                      {t.source?.issue_number && <span>Issue #{t.source.issue_number}</span>}
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </aside>

        {/* Center Canvas: Agent Studio Workbench */}
        <main className="flex-1 min-h-0 flex flex-col overflow-hidden bg-background/50">
          {!taskDetail ? (
            <div className="flex-1 flex flex-col items-center justify-center p-8 text-center space-y-4">
              <div className="h-14 w-14 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary shadow-inner">
                <Sparkles className="h-7 w-7" />
              </div>
              <div className="space-y-1 max-w-sm">
                <h3 className="text-base font-bold text-foreground">Select or Launch an AI Task</h3>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  The AI Autonomous Studio plans, sandboxes, executes, and verifies code changes with zero manual friction.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowNewTaskModal(true)}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-xs font-semibold shadow-md shadow-primary/20 hover:bg-primary/90 transition-all cursor-pointer"
              >
                <Plus className="h-4 w-4" />
                <span>Launch New Task</span>
              </button>
            </div>
          ) : (
            <div className="flex-1 min-h-0 overflow-y-auto p-4 sm:p-6 space-y-5">
              {/* ------------------------------------------------------------ */}
              {/* Header: Title & Badges                                       */}
              {/* ------------------------------------------------------------ */}
              <div className="space-y-3">
                <div className="flex items-center justify-between gap-3 flex-wrap">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span
                      className={cn(
                        'inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full border text-xs font-mono font-bold',
                        (STATUS_BADGE_MAP[taskDetail.status] || STATUS_BADGE_MAP.CREATED).className
                      )}
                    >
                      <span>{(STATUS_BADGE_MAP[taskDetail.status] || STATUS_BADGE_MAP.CREATED).label}</span>
                    </span>

                    <span className="text-[11px] font-mono text-muted-foreground bg-muted/40 px-2 py-0.5 rounded border border-border/50">
                      ID: <strong className="text-foreground">{taskDetail.task_id.slice(0, 12)}</strong>
                    </span>

                    {workspaceMeta?.branch_name && (
                      <span className="inline-flex items-center gap-1 text-[11px] font-mono text-indigo-400 bg-indigo-500/10 px-2 py-0.5 rounded border border-indigo-500/30">
                        <GitBranch className="h-3 w-3" />
                        <span>{workspaceMeta.branch_name}</span>
                      </span>
                    )}

                    {draftPR && (
                      <a
                        href={draftPR.pr_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-purple-500/15 border border-purple-500/40 text-xs font-mono text-purple-300 hover:underline"
                      >
                        <GitPullRequest className="h-3 w-3" />
                        <span>Draft PR #{draftPR.pr_number}</span>
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    )}
                  </div>

                  {/* Secondary control actions */}
                  <div className="flex items-center gap-2">
                    {taskDetail.status !== 'CANCELLED' &&
                      taskDetail.status !== 'FAILED' &&
                      taskDetail.status !== 'DRAFT_PR_CREATED' && (
                        <button
                          type="button"
                          disabled={actionBusy !== null}
                          onClick={handleCancelTask}
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-border hover:bg-rose-500/10 hover:border-rose-500/40 text-muted-foreground hover:text-rose-300 text-xs font-medium transition-colors cursor-pointer"
                        >
                          <Slash className="h-3 w-3" />
                          <span>Cancel Task</span>
                        </button>
                      )}

                    {(taskDetail.status === 'RECOVERY_REQUIRED' || taskDetail.status === 'FAILED') && (
                      <button
                        type="button"
                        disabled={actionBusy !== null}
                        onClick={handleRecoverTask}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-orange-500/40 bg-orange-500/10 text-orange-300 text-xs font-semibold hover:bg-orange-500/20 cursor-pointer"
                      >
                        <RotateCcw className="h-3 w-3" />
                        <span>Recover</span>
                      </button>
                    )}
                  </div>
                </div>

                {loadingDetail && (
                  <div className="flex items-center gap-2 text-xs text-primary font-mono">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    <span>Synchronizing task details...</span>
                  </div>
                )}

                <h2 className="text-lg sm:text-xl font-bold tracking-tight text-foreground break-words leading-tight">
                  {taskDetail.title}
                </h2>
              </div>

              {/* ------------------------------------------------------------ */}
              {/* Visual Interactive Workflow Stepper (Pipeline)               */}
              {/* ------------------------------------------------------------ */}
              <div className="rounded-xl border border-border bg-card/60 p-3.5 backdrop-blur-xs">
                <div className="flex items-center justify-between gap-1 overflow-x-auto pb-1 scrollbar-none">
                  {[
                    { key: 'plan', label: '1. Plan & Scope', icon: ListChecks, activeStages: ['CREATED', 'PLANNING', 'PENDING_APPROVAL', 'APPROVED'] },
                    { key: 'workspace', label: '2. Sandbox Execution', icon: Zap, activeStages: ['WORKSPACE_SETUP', 'EXECUTING'] },
                    { key: 'tests', label: '3. Tests & Self-Repair', icon: FlaskConical, activeStages: ['TESTING', 'REPAIRING'] },
                    { key: 'changes', label: '4. Code Diff', icon: FileDiff, activeStages: [] },
                    { key: 'verification', label: '5. Quality Gates', icon: ShieldCheck, activeStages: ['VERIFYING'] },
                    { key: 'pr', label: '6. GitHub PR', icon: GitPullRequest, activeStages: ['READY_FOR_PUBLICATION', 'PUBLISHING', 'DRAFT_PR_CREATED'] },
                  ].map((step) => {
                    const isSelected = activeTab === step.key;
                    const isCurrentStage = step.activeStages.includes(taskDetail.status);
                    const StepIcon = step.icon;

                    return (
                      <button
                        key={step.key}
                        type="button"
                        onClick={() => setActiveTab(step.key as StudioTab)}
                        className={cn(
                          'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all shrink-0 cursor-pointer',
                          isSelected
                            ? 'bg-primary text-primary-foreground shadow-sm'
                            : isCurrentStage
                            ? 'bg-primary/10 text-primary border border-primary/30'
                            : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground'
                        )}
                      >
                        <StepIcon className="h-3.5 w-3.5 shrink-0" />
                        <span>{step.label}</span>
                        {isCurrentStage && (
                          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse ml-0.5" />
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* ------------------------------------------------------------ */}
              {/* Hero "Mission Control" Next-Step Action Banner               */}
              {/* ------------------------------------------------------------ */}
              {nextStepInfo && (
                <div
                  className={cn(
                    'rounded-xl border p-4.5 flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4 transition-all shadow-sm',
                    nextStepInfo.color === 'emerald' && 'bg-emerald-500/10 border-emerald-500/30',
                    nextStepInfo.color === 'blue' && 'bg-blue-500/10 border-blue-500/30',
                    nextStepInfo.color === 'cyan' && 'bg-cyan-500/10 border-cyan-500/30',
                    nextStepInfo.color === 'sky' && 'bg-sky-500/10 border-sky-500/30',
                    nextStepInfo.color === 'teal' && 'bg-teal-500/10 border-teal-500/30',
                    nextStepInfo.color === 'purple' && 'bg-purple-500/10 border-purple-500/30',
                    nextStepInfo.color === 'orange' && 'bg-orange-500/10 border-orange-500/30',
                    nextStepInfo.color === 'slate' && 'bg-muted/40 border-border'
                  )}
                >
                  <div className="space-y-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-mono uppercase font-bold tracking-wider px-2 py-0.5 rounded bg-background/80 border border-border/60">
                        Next Stage: {nextStepInfo.stage}
                      </span>
                      {nextStepInfo.inProgress && (
                        <span className="inline-flex items-center gap-1 text-[11px] font-medium text-primary">
                          <Loader2 className="h-3 w-3 animate-spin" />
                          <span>Active</span>
                        </span>
                      )}
                    </div>
                    <div className="text-sm font-bold text-foreground leading-snug">
                      {nextStepInfo.headline}
                    </div>
                    <div className="text-xs text-muted-foreground leading-relaxed">
                      {nextStepInfo.description}
                    </div>
                  </div>

                  {/* Primary CTA Button */}
                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      type="button"
                      disabled={actionBusy !== null}
                      onClick={handlePrimaryStepAction}
                      className={cn(
                        'inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-lg text-xs font-bold shadow-md transition-all cursor-pointer disabled:opacity-50',
                        nextStepInfo.color === 'emerald' && 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-emerald-600/20',
                        nextStepInfo.color === 'purple' && 'bg-purple-600 hover:bg-purple-500 text-white shadow-purple-600/20',
                        nextStepInfo.color === 'sky' && 'bg-sky-600 hover:bg-sky-500 text-white shadow-sky-600/20',
                        nextStepInfo.color === 'teal' && 'bg-teal-600 hover:bg-teal-500 text-white shadow-teal-600/20',
                        (nextStepInfo.color === 'blue' || nextStepInfo.color === 'cyan') && 'bg-primary hover:bg-primary/90 text-primary-foreground shadow-primary/20',
                        nextStepInfo.color === 'orange' && 'bg-orange-600 hover:bg-orange-500 text-white shadow-orange-600/20',
                        nextStepInfo.color === 'slate' && 'bg-card hover:bg-accent text-foreground border border-border'
                      )}
                    >
                      {actionBusy ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <nextStepInfo.actionIcon className="h-4 w-4" />
                      )}
                      <span>{nextStepInfo.actionLabel}</span>
                    </button>

                    {/* Auto-pilot 1-click trigger when task is approved or pending */}
                    {(taskDetail.status === 'APPROVED' || taskDetail.status === 'PENDING_APPROVAL') && (
                      <button
                        type="button"
                        disabled={actionBusy !== null}
                        onClick={handleRunAutoPilot}
                        className="inline-flex items-center gap-1.5 px-3 py-2.5 rounded-lg border border-amber-500/40 bg-amber-500/10 text-amber-300 hover:bg-amber-500/20 text-xs font-bold transition-colors cursor-pointer"
                        title="Run steps, tests, repair, and verification automatically"
                      >
                        <Zap className="h-3.5 w-3.5 text-amber-400" />
                        <span className="hidden sm:inline">Auto-Pilot</span>
                      </button>
                    )}
                  </div>
                </div>
              )}

              {/* ------------------------------------------------------------ */}
              {/* Tab Navigation Bar                                           */}
              {/* ------------------------------------------------------------ */}
              <div className="border-b border-border flex items-center gap-1 overflow-x-auto scrollbar-none">
                {[
                  { id: 'plan', label: 'Plan & Scope', icon: ListChecks },
                  { id: 'workspace', label: 'Workspace & Terminal', icon: Terminal },
                  { id: 'tests', label: 'Tests & Self-Repair', icon: FlaskConical },
                  { id: 'changes', label: 'Code Changes (Diff)', icon: FileDiff },
                  { id: 'verification', label: 'Verification Gates', icon: ShieldCheck },
                  { id: 'pr', label: 'GitHub Pull Request', icon: GitPullRequest },
                ].map((tab) => {
                  const isSelected = activeTab === tab.id;
                  const TabIcon = tab.icon;
                  return (
                    <button
                      key={tab.id}
                      type="button"
                      onClick={() => setActiveTab(tab.id as StudioTab)}
                      className={cn(
                        'flex items-center gap-1.5 px-3.5 py-2 text-xs font-medium border-b-2 transition-colors shrink-0 cursor-pointer',
                        isSelected
                          ? 'border-primary text-primary font-semibold'
                          : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'
                      )}
                    >
                      <TabIcon className="h-3.5 w-3.5" />
                      <span>{tab.label}</span>
                    </button>
                  );
                })}
              </div>

              {/* ------------------------------------------------------------ */}
              {/* TAB 1: Plan & Scope                                          */}
              {/* ------------------------------------------------------------ */}
              {activeTab === 'plan' && (
                <div className="space-y-4 animate-in fade-in duration-150">
                  {/* Approval / Review Action Box (when pending approval) */}
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

                  {/* Structured Plan Summary & Steps */}
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

                      {/* Implementation Steps Checklist */}
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
                                  <span className="font-semibold text-foreground">
                                    {s.description}
                                  </span>
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

                  {/* Requirements & Protected Constraints */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="rounded-xl border border-border bg-card p-4 space-y-2">
                      <div className="text-[11px] font-mono uppercase text-primary font-bold">
                        Requirements ({taskDetail.requirements?.length ?? 0})
                      </div>
                      <div className="space-y-1 text-xs">
                        {taskDetail.requirements && taskDetail.requirements.length > 0 ? (
                          taskDetail.requirements.map((r) => (
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
                          <span className="px-2 py-0.5 rounded bg-rose-500/10 border border-rose-500/30">.github/workflows/deploy.yml</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* ------------------------------------------------------------ */}
              {/* TAB 2: Workspace Sandbox & Live Execution                    */}
              {/* ------------------------------------------------------------ */}
              {activeTab === 'workspace' && (
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
                          <div className="font-mono text-[11px] text-muted-foreground truncate" title={workspaceMeta.workspace_path}>
                            {workspaceMeta.workspace_path}
                          </div>
                        </div>
                      </div>

                      {/* Step Execution Telemetry */}
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
                                <span className="font-semibold text-foreground">Step {i + 1}: {s.description}</span>
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
              )}

              {/* ------------------------------------------------------------ */}
              {/* TAB 3: Automated Tests & Self-Repair                         */}
              {/* ------------------------------------------------------------ */}
              {activeTab === 'tests' && (
                <div className="space-y-4 animate-in fade-in duration-150">
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div>
                      <h3 className="text-xs font-bold uppercase tracking-wider text-foreground">
                        Automated Test Suite & Self-Healing Loop
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
                        disabled={
                          actionBusy !== null ||
                          repairAttemptsUsed >= repairAttemptsMax
                        }
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

                  <TestExecutionPanel
                    taskId={taskDetail.task_id}
                    testResults={testResults}
                  />
                </div>
              )}

              {/* ------------------------------------------------------------ */}
              {/* TAB 4: Code Changes (Diff)                                   */}
              {/* ------------------------------------------------------------ */}
              {activeTab === 'changes' && (
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
                    taskId={taskDetail.task_id}
                    repositoryId={repoId}
                    plannedTargetFiles={latestPlan?.expected_files ?? []}
                  />
                </div>
              )}

              {/* ------------------------------------------------------------ */}
              {/* TAB 5: Independent Verification Gates                        */}
              {/* ------------------------------------------------------------ */}
              {activeTab === 'verification' && (
                <div className="space-y-4 animate-in fade-in duration-150">
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div>
                      <h3 className="text-xs font-bold uppercase tracking-wider text-foreground">
                        Independent Quality & Security Verification
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

                  <VerificationPanel
                    taskId={taskDetail.task_id}
                    currentRevision={taskDetail.base_revision}
                  />
                </div>
              )}

              {/* ------------------------------------------------------------ */}
              {/* TAB 6: GitHub Draft PR & Publication                         */}
              {/* ------------------------------------------------------------ */}
              {activeTab === 'pr' && (
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
              )}
            </div>
          )}
        </main>

        {/* Right Sidebar: Activity Timeline */}
        <aside className="w-80 shrink-0 border-l border-border bg-card/20 flex flex-col min-h-0 hidden xl:flex">
          <div className="p-3 border-b border-border/60 flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-xs font-bold text-foreground">
              <History className="h-3.5 w-3.5 text-primary" />
              <span>Agent Activity Feed</span>
            </div>
            <span className="text-[10px] font-mono text-muted-foreground">
              {events.length} events
            </span>
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto p-3">
            {activeTaskId ? (
              <ExecutionTimeline taskId={activeTaskId} events={events} />
            ) : (
              <div className="p-6 text-center text-xs text-muted-foreground">
                Select a task to inspect timeline.
              </div>
            )}
          </div>
        </aside>
      </div>

      {/* -------------------------------------------------------------------- */}
      {/* 3. Sleek "New Task" Creation Modal                                   */}
      {/* -------------------------------------------------------------------- */}
      {showNewTaskModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-background/80 backdrop-blur-sm animate-in fade-in duration-150">
          <div className="w-full max-w-lg rounded-2xl border border-border bg-card p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="h-8 w-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
                  <Bot className="h-4 w-4" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-foreground">Launch Autonomous AI Task</h3>
                  <p className="text-[11px] text-muted-foreground">Write only what you want done. The agent handles planning and execution.</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowNewTaskModal(false)}
                className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <form onSubmit={handleCreateNewTask} className="space-y-4">
              <div>
                <label className="text-xs font-semibold text-foreground block mb-1.5">
                  What do you want the AI to build or fix?
                </label>
                <textarea
                  rows={4}
                  required
                  autoFocus
                  value={newTaskPrompt}
                  onChange={(e) => setNewTaskPrompt(e.target.value)}
                  placeholder="e.g. Change page background color to white and update CSS styling..."
                  className="w-full px-3.5 py-2.5 text-xs rounded-xl border border-border bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/40 leading-relaxed font-normal"
                />
              </div>

              {/* Starter Quick Tags */}
              <div className="space-y-1.5">
                <span className="text-[10px] font-mono text-muted-foreground uppercase font-bold">
                  Quick Starter Examples:
                </span>
                <div className="flex items-center gap-1.5 flex-wrap">
                  {STARTER_PROMPTS.map((starter) => (
                    <button
                      key={starter.label}
                      type="button"
                      onClick={() => setNewTaskPrompt(starter.text)}
                      className="px-2 py-1 rounded-md bg-muted/40 hover:bg-primary/10 hover:text-primary text-[11px] text-muted-foreground border border-border/50 transition-colors cursor-pointer"
                    >
                      {starter.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="pt-2 border-t border-border/60 flex items-center justify-between gap-3">
                <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer">
                  <input
                    type="checkbox"
                    checked={autoPilotOnCreate}
                    onChange={(e) => setAutoPilotOnCreate(e.target.checked)}
                    className="rounded border-border text-primary focus:ring-primary/40"
                  />
                  <span>Run on <strong>⚡ Auto-Pilot</strong> (Plan + Execute + Verify)</span>
                </label>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setShowNewTaskModal(false)}
                    className="px-3 py-1.5 text-xs font-medium rounded-lg border border-border hover:bg-accent cursor-pointer"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={actionBusy !== null || !newTaskPrompt.trim()}
                    className="px-4 py-1.5 text-xs font-bold rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-all shadow-sm cursor-pointer disabled:opacity-40"
                  >
                    {actionBusy === 'create' ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <span>Launch Agent</span>
                    )}
                  </button>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* -------------------------------------------------------------------- */}
      {/* 4. Import GitHub Issue Modal                                         */}
      {/* -------------------------------------------------------------------- */}
      {showImportIssueModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-background/80 backdrop-blur-sm animate-in fade-in duration-150">
          <div className="w-full max-w-sm rounded-2xl border border-border bg-card p-5 shadow-2xl space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold text-foreground">Import GitHub Issue</h3>
              <button
                type="button"
                onClick={() => setShowImportIssueModal(false)}
                className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <form onSubmit={handleImportIssue} className="space-y-3">
              <div>
                <label className="text-xs font-semibold text-foreground block mb-1">
                  GitHub Issue Number
                </label>
                <input
                  type="number"
                  min={1}
                  required
                  autoFocus
                  placeholder="e.g. 42"
                  value={issueNumberInput}
                  onChange={(e) => setIssueNumberInput(e.target.value)}
                  className="w-full px-3 py-2 text-xs rounded-lg border border-border bg-background text-foreground font-mono focus:outline-none focus:ring-2 focus:ring-primary/40"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-border/60">
                <button
                  type="button"
                  onClick={() => setShowImportIssueModal(false)}
                  className="px-3 py-1.5 text-xs font-medium rounded-lg border border-border hover:bg-accent cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionBusy !== null || !issueNumberInput.trim()}
                  className="px-4 py-1.5 text-xs font-bold rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-all cursor-pointer disabled:opacity-40"
                >
                  {actionBusy === 'import' ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <span>Import & Plan</span>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

export default RepositoryTaskStudio;
