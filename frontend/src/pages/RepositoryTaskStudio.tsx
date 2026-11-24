/**
 * RepositoryTaskStudio — Autonomous AI Developer Studio
 *
 * Professional, intuitive, and modern engineering sub-application:
 * - Visual interactive 6-stage workflow pipeline (Plan -> Execute -> Test -> Diff -> Verify -> Ship PR)
 * - Hero Next-Step Action Bar with plain-English guidance and one-click primary CTAs
 * - Tabbed workspace views eliminating clutter and cognitive overload
 * - Sleek prompt-driven Task Intake modal with quick starter templates
 * - Comprehensive code diff inspector, test runner, quality gates, and GitHub PR integration
 */

import { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Clock,
  ExternalLink,
  FileDiff,
  FlaskConical,
  GitBranch,
  GitPullRequest,
  History,
  ListChecks,
  Loader2,
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
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { cn } from '../lib/utils';
import { useRepository } from '../hooks/useRepositories';
import { apiClient } from '../services/api';
import {
  useTasks,
  useTask,
  useTaskPlan,
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
  authorizeTaskPublication,
  cancelTask,
  commitTaskChanges,
  createTaskDraftPR,
  executeTask,
  generateTaskPlan,
  getWorkflowStatus,
  importGitHubIssue,
  pauseTask,
  recoverTask,
  rejectTaskPlan,
  resumeTask,
  startAutonomousWorkflow,
  submitTaskPrompt,
  type PromptToPlanResponse,
  triggerTaskRepair,
  triggerTaskTests,
  triggerTaskVerification,
} from '../services/tasks';
import type {
  TaskDetail,
  TaskEvent,
  TaskPullRequestResponse,
  TaskSummary,
} from '../types/task';
import { isExecutionActive } from '../types/task';
import { ExecutionTimeline } from '../components/tasks/ExecutionTimeline';
import {
  RepositoryTaskChangesTab,
  RepositoryTaskPlanTab,
  RepositoryTaskPrTab,
  RepositoryTaskTestsTab,
  RepositoryTaskVerificationTab,
  RepositoryTaskWorkspaceTab,
} from '../components/taskStudio/TaskPhasePanels';

const STATUS_BADGE_MAP: Record<
  string,
  { label: string; className: string; icon: typeof CheckCircle2 }
> = {
  CREATED: {
    label: 'Created',
    className: 'bg-muted text-muted-foreground border-border',
    icon: Clock,
  },
  PLANNING: {
    label: 'Planning…',
    className: 'bg-sky-500/10 text-sky-700 dark:text-sky-400 border-sky-500/25',
    icon: Bot,
  },
  PENDING_APPROVAL: {
    label: 'Pending Approval',
    className: 'bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/25',
    icon: Clock,
  },
  APPROVED: {
    label: 'Plan Approved',
    className: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/25',
    icon: CheckCircle2,
  },
  REJECTED: {
    label: 'Plan Rejected',
    className: 'bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-500/25',
    icon: XCircle,
  },
  WORKSPACE_SETUP: {
    label: 'Setting Up Sandbox',
    className: 'bg-sky-500/10 text-sky-700 dark:text-sky-400 border-sky-500/25',
    icon: Terminal,
  },
  EXECUTING: {
    label: 'Agent Executing',
    className: 'bg-sky-500/10 text-sky-700 dark:text-sky-400 border-sky-500/25',
    icon: Zap,
  },
  TESTING: {
    label: 'Running Tests',
    className: 'bg-teal-500/10 text-teal-700 dark:text-teal-400 border-teal-500/25',
    icon: FlaskConical,
  },
  REPAIRING: {
    label: 'Self-Repairing',
    className: 'bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/25',
    icon: Wrench,
  },
  VERIFYING: {
    label: 'Verifying Quality',
    className: 'bg-teal-500/10 text-teal-700 dark:text-teal-400 border-teal-500/25',
    icon: ShieldCheck,
  },
  READY_FOR_PUBLICATION: {
    label: 'Ready to Ship',
    className: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/25',
    icon: CheckCircle2,
  },
  PUBLISHING: {
    label: 'Publishing PR…',
    className: 'bg-teal-500/10 text-teal-700 dark:text-teal-400 border-teal-500/25',
    icon: GitPullRequest,
  },
  DRAFT_PR_CREATED: {
    label: 'Draft PR Created',
    className: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/25',
    icon: GitPullRequest,
  },
  RECOVERY_REQUIRED: {
    label: 'Recovery Needed',
    className: 'bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/25',
    icon: AlertTriangle,
  },
  BLOCKED: {
    label: 'Blocked',
    className: 'bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-500/25',
    icon: XCircle,
  },
  FAILED: {
    label: 'Failed',
    className: 'bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-500/25',
    icon: XCircle,
  },
  CANCELLED: {
    label: 'Cancelled',
    className: 'bg-muted text-muted-foreground border-border',
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
  { label: 'Refine theme & styling', text: 'Update page background colors and refine light/dark mode styling' },
  { label: 'Fix validation bug', text: 'Fix negative amount validation in checkout and add unit test coverage' },
  { label: 'Add rate limiting', text: 'Add token bucket rate limiting middleware for public endpoints' },
  { label: 'Generate unit tests', text: 'Generate comprehensive unit tests for core validation services' },
];

function resolveTestRunner(
  language?: string | null,
  fallbackFramework?: string | null
): {
  apiFramework: string | undefined;
  repairFramework: string;
  runLabel: string;
  runningName: string;
} {
  const lang = (language ?? '').trim().toLowerCase();
  if (lang === 'python' || lang === 'py') {
    return { apiFramework: 'pytest', repairFramework: 'pytest', runLabel: 'Run Pytest', runningName: 'pytest' };
  }
  if (lang === 'typescript' || lang === 'javascript' || lang === 'tsx' || lang === 'jsx' || lang === 'ts' || lang === 'js') {
    return { apiFramework: 'vitest', repairFramework: 'jest', runLabel: 'Run Vitest', runningName: 'vitest' };
  }
  if (lang === 'rust' || lang === 'rs') {
    return { apiFramework: 'cargo test', repairFramework: 'pytest', runLabel: 'Run Cargo Test', runningName: 'cargo test' };
  }
  if (lang === 'go' || lang === 'golang') {
    return { apiFramework: 'go test', repairFramework: 'pytest', runLabel: 'Run Go Test', runningName: 'go test' };
  }
  if (lang === 'java' || lang === 'kotlin') {
    return { apiFramework: 'junit', repairFramework: 'pytest', runLabel: 'Run Tests', runningName: 'test suite' };
  }

  const fb = (fallbackFramework ?? '').trim().toLowerCase();
  if (fb === 'pytest' || fb === 'unittest') {
    return { apiFramework: fb, repairFramework: 'pytest', runLabel: 'Run Pytest', runningName: fb };
  }
  if (fb === 'vitest' || fb === 'jest') {
    return { apiFramework: fb, repairFramework: 'jest', runLabel: fb === 'vitest' ? 'Run Vitest' : 'Run Jest', runningName: fb };
  }
  if (fb === 'cargo test' || fb === 'cargo') {
    return { apiFramework: 'cargo test', repairFramework: 'pytest', runLabel: 'Run Cargo Test', runningName: 'cargo test' };
  }
  if (fb === 'go test' || fb === 'go') {
    return { apiFramework: 'go test', repairFramework: 'pytest', runLabel: 'Run Go Test', runningName: 'go test' };
  }

  return { apiFramework: undefined, repairFramework: 'pytest', runLabel: 'Run Tests', runningName: 'automated test' };
}

export function RepositoryTaskStudio() {
  const { id } = useParams<{ id: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const repoId = id ?? '';

  const queryClient = useQueryClient();
  const { data: repository } = useRepository(repoId);
  const planPanel = useRef<HTMLDivElement>(null);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState<string | null>(null);

  // Active studio tab & mobile drawers
  const [userSelectedTab, setUserSelectedTab] = useState<StudioTab | null>(null);
  const [taskSearchFilter, setTaskSearchFilter] = useState('');
  const [showActivityFeed, setShowActivityFeed] = useState(false);
  const [mobileTaskListOpen, setMobileTaskListOpen] = useState(false);

  // New Task Modal State
  const [showNewTaskModal, setShowNewTaskModal] = useState(false);
  const [newTaskPrompt, setNewTaskPrompt] = useState('');
  const [promptReview, setPromptReview] = useState<PromptToPlanResponse | null>(null);

  // Import Issue Form State
  const [showImportIssueModal, setShowImportIssueModal] = useState(false);
  const [issueNumberInput, setIssueNumberInput] = useState('');

  // Human Review Input State
  const [approvalComment, setApprovalComment] = useState('');
  const [revisionNotes, setRevisionNotes] = useState('');
  const [showRevisionInput, setShowRevisionInput] = useState(false);
  const [rejectionReason, setRejectionReason] = useState('');
  const [showRejectionInput, setShowRejectionInput] = useState(false);
  const [publicationApproval, setPublicationApproval] = useState<{ taskId: string; sha: string } | null>(null);
  const [startedWorkflowTask, setStartedWorkflowTask] = useState<string | null>(null);

  // Query: Repository Task List
  const {
    data: taskListData,
    isLoading: loadingTasks,
    error: taskListError,
  } = useTasks({ repository_id: repoId });
  const tasks: TaskSummary[] = useMemo(() => taskListData?.items ?? [], [taskListData?.items]);

  // Task Selection
  const urlTaskId = searchParams.get('taskId');
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(urlTaskId);
  const [prevUrlTaskId, setPrevUrlTaskId] = useState<string | null>(urlTaskId);

  if (urlTaskId !== prevUrlTaskId) {
    setPrevUrlTaskId(urlTaskId);
    setSelectedTaskId(urlTaskId);
    setUserSelectedTab(null);
    setPublicationApproval(null);
    setPromptReview(null);
    setShowRevisionInput(false);
    setShowRejectionInput(false);
    setApprovalComment('');
    setRevisionNotes('');
    setRejectionReason('');
  }

  const activeTaskId = selectedTaskId || (tasks.length > 0 ? tasks[0].task_id : null);
  const isTaskActive = Boolean(activeTaskId);

  const handleSelectTask = useCallback(
    (taskId: string) => {
      setUserSelectedTab(null);
      setSelectedTaskId(taskId);
      setPublicationApproval(null);
      setShowRevisionInput(false);
      setShowRejectionInput(false);
      setApprovalComment('');
      setRevisionNotes('');
      setRejectionReason('');
      setMobileTaskListOpen(false);
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set('taskId', taskId);
        return next;
      });
      setErrorBanner(null);
    },
    [setSearchParams]
  );

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      if (showNewTaskModal) {
        setShowNewTaskModal(false);
      } else if (showImportIssueModal) {
        setShowImportIssueModal(false);
      } else if (mobileTaskListOpen) {
        setMobileTaskListOpen(false);
      } else if (showActivityFeed) {
        setShowActivityFeed(false);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [showNewTaskModal, showImportIssueModal, mobileTaskListOpen, showActivityFeed]);

  // Query: Active Task Detail
  const {
    data: taskDetailData,
    isLoading: loadingDetail,
    error: taskDetailError,
  } = useTask(activeTaskId ?? undefined, { enabled: isTaskActive });
  const taskDetail = (isTaskActive ? taskDetailData : null) as TaskDetail | null;
  const { data: workflow } = useQuery({
    queryKey: [...taskKeys.detail(activeTaskId ?? ''), 'workflow'],
    queryFn: () => getWorkflowStatus(activeTaskId!),
    enabled: isTaskActive && (startedWorkflowTask === activeTaskId || isExecutionActive(taskDetail?.status ?? 'CREATED')),
    refetchInterval: (query) => ['COMPLETED', 'FAILED', 'CANCELLED'].includes(query.state.data?.status ?? '') ? false : 2000,
  });

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
  const testRunner = useMemo(
    () => resolveTestRunner(repository?.language, testResults?.runs?.[0]?.framework),
    [repository?.language, testResults?.runs]
  );

  const { data: repairBudgetData } = useTaskRepairBudget(activeTaskId ?? undefined, {
    enabled: isTaskActive,
  });
  const repairAttemptsUsed = repairBudgetData?.repair_attempts_used ?? taskDetail?.repair_attempts_used ?? 0;
  const repairAttemptsMax = repairBudgetData?.repair_attempts_max ?? taskDetail?.repair_attempts_max ?? 3;

  const { data: verificationData } = useTaskVerification(activeTaskId ?? undefined, {
    enabled: isTaskActive,
  });
  const verificationResult = isTaskActive ? (verificationData ?? null) : null;
  const publicationAuthorized = Boolean(
    taskDetail?.status === 'PUBLISHING' ||
    (publicationApproval && publicationApproval.taskId === activeTaskId && publicationApproval.sha === verificationResult?.verified_revision),
  );
  const setPublicationAuthorized = (authorized: boolean) => {
    const sha = verificationResult?.verified_revision;
    setPublicationApproval(authorized && activeTaskId && sha ? { taskId: activeTaskId, sha } : null);
  };

  const { data: draftPRData } = useTaskPullRequest(activeTaskId ?? undefined, {
    enabled: isTaskActive && taskDetail?.status === 'DRAFT_PR_CREATED',
  });
  const draftPR = (isTaskActive ? (draftPRData ?? null) : null) as TaskPullRequestResponse | null;

  // Active studio tab: defaults to recommended tab for current status, but preserves user click
  const activeTab: StudioTab = userSelectedTab ?? getRecommendedTabForStatus(taskDetail?.status);
  const setActiveTab = (tab: StudioTab) => setUserSelectedTab(tab);

  const savedPlanVersion = taskDetail?.latest_plan?.plan_version ?? taskDetail?.plan_version;
  const planQuery = useTaskPlan(activeTaskId ?? undefined, savedPlanVersion || undefined, {
    enabled: activeTab === 'plan' && Boolean(savedPlanVersion),
  });
  const latestPlan = planQuery.data ?? taskDetail?.latest_plan ?? null;

  const readinessQuery = useQuery({
    queryKey: ['task-planner-readiness'],
    queryFn: async () => {
      const response = await apiClient.get<{ operations?: { sandbox_backend_ok?: boolean } }>('/health/ready', {
        timeout: 15000,
      });
      return response.data;
    },
    enabled: taskDetail?.status === 'APPROVED',
    staleTime: 15000,
    refetchInterval: 30000,
    retry: false,
  });
  const planRevision = latestPlan?.base_revision ?? taskDetail?.base_revision;
  const needsPinnedPlan = (taskDetail?.status === 'PENDING_APPROVAL' || taskDetail?.status === 'APPROVED') &&
    Boolean(latestPlan) && !/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(planRevision ?? '');
  const sandboxUnavailable = readinessQuery.data?.operations?.sandbox_backend_ok === false;
  const executionBlocker = needsPinnedPlan
    ? 'This plan needs a full indexed commit. Sync the repository if needed, then regenerate and review the new plan.'
    : sandboxUnavailable
      ? 'The execution sandbox is unavailable. Plan review is available while the runner is being restored.'
      : null;

  // Update active queries in the background so a failed refresh cannot hold a completed action open.
  const refreshTasksAndCurrentDetail = useCallback(
    (targetTaskId?: string) => {
      const tid = targetTaskId || activeTaskId;
      void queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
      if (tid) {
        void queryClient.invalidateQueries({
          queryKey: taskKeys.detail(tid),
          predicate: (query) => query.queryKey.at(-1) !== 'workflow',
        });
      }
    },
    [activeTaskId, queryClient]
  );
  const workflowUpdatedAt = workflow?.updated_at;
  useEffect(() => {
    if (workflowUpdatedAt) void refreshTasksAndCurrentDetail();
  }, [workflowUpdatedAt, refreshTasksAndCurrentDetail]);

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

    setActionBusy('create');
    setErrorBanner(null);
    setPromptReview(null);
    try {
      const result = await submitTaskPrompt(repoId, prompt);
      setPromptReview(result);
      if (result.task_id) {
        setShowNewTaskModal(false);
        setNewTaskPrompt('');
        handleSelectTask(result.task_id);
      }
    } catch (err: any) {
      setErrorBanner(err?.code === 'NETWORK_ERROR' || err?.code === 'REQUEST_TIMEOUT'
        ? 'The task request could not be confirmed. Check the task list before submitting again.'
        : err?.message || 'Failed to create task.');
    } finally {
      refreshTasksAndCurrentDetail();
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
      refreshTasksAndCurrentDetail();
      setActionBusy(null);
    }
  }

  async function handleApprovePlan() {
    if (!taskDetail || !latestPlan || needsPinnedPlan) return;
    setActionBusy('approve');
    setErrorBanner(null);
    try {
      await approveTaskPlan(taskDetail.task_id, {
        plan_version: latestPlan.plan_version,
        base_revision: latestPlan.base_revision || undefined,
        comment: approvalComment.trim() || 'Plan approved by user via Studio.',
      });
      setApprovalComment('');
    } catch (err: any) {
      setErrorBanner(err?.message || 'Failed to approve plan.');
    } finally {
      refreshTasksAndCurrentDetail(taskDetail.task_id);
      setActionBusy(null);
    }
  }

  async function handleExecuteTask(runSteps = true) {
    if (!taskDetail) return;
    const tid = taskDetail.task_id;
    setActionBusy('execute');
    setErrorBanner(null);
    try {
      if (taskDetail.status === 'FAILED' || taskDetail.status === 'RECOVERY_REQUIRED') {
        await recoverTask(tid);
      }
      setActiveTab('workspace');
      await executeTask(tid, { run_steps: runSteps });
    } catch (err: any) {
      setErrorBanner(err?.message || 'Execution blocked by approval gate.');
    } finally {
      refreshTasksAndCurrentDetail(tid);
      setActionBusy(null);
    }
  }

  async function handleRunWorkflow() {
    if (!taskDetail || taskDetail.status !== 'APPROVED' || executionBlocker) return;
    const tid = taskDetail.task_id;
    setActionBusy('execute');
    setErrorBanner(null);
    try {
      await startAutonomousWorkflow(tid, { run_tests: true, auto_repair: true });
      setStartedWorkflowTask(tid);
      setActiveTab('workspace');
    } catch (err: any) {
      setErrorBanner(err?.message || 'Failed to start the approved workflow.');
    } finally {
      refreshTasksAndCurrentDetail(tid);
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
      refreshTasksAndCurrentDetail(taskDetail.task_id);
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
      refreshTasksAndCurrentDetail(taskDetail.task_id);
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
      refreshTasksAndCurrentDetail(taskDetail.task_id);
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
      refreshTasksAndCurrentDetail(taskDetail.task_id);
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
      refreshTasksAndCurrentDetail(taskDetail.task_id);
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
      await triggerTaskTests(tid, testRunner.apiFramework ? { framework: testRunner.apiFramework } : {});
    } catch (err: any) {
      setErrorBanner(err?.message || 'Failed to run workspace tests.');
    } finally {
      refreshTasksAndCurrentDetail(tid);
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
      await triggerTaskRepair(tid, { framework: testRunner.repairFramework });
    } catch (err: any) {
      setErrorBanner(err?.message || 'Bounded self-repair failed or budget exhausted.');
    } finally {
      refreshTasksAndCurrentDetail(tid);
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
      refreshTasksAndCurrentDetail(tid);
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
      refreshTasksAndCurrentDetail(taskDetail.task_id);
      setActionBusy(null);
    }
  }

  async function handleCreateDraftPR() {
    if (!taskDetail || !publicationAuthorized || !verificationResult?.verified_revision) return;
    setActionBusy('create-pr');
    setErrorBanner(null);
    try {
      if (taskDetail.status !== 'PUBLISHING') {
        await authorizeTaskPublication(taskDetail.task_id, {
          head_sha: verificationResult.verified_revision,
          notes: 'User authorized Draft PR publication via Studio',
        });
      }

      const pr = await createTaskDraftPR(taskDetail.task_id, {
        publication_authorized: true,
        title: `feat: ${taskDetail.title}`,
      });
      queryClient.setQueryData(taskKeys.pullRequest(taskDetail.task_id), pr);
    } catch (err: any) {
      setErrorBanner(
        err?.message || 'Publication blocked: Independent verification and authorization are required.'
      );
    } finally {
      refreshTasksAndCurrentDetail(taskDetail.task_id);
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
      refreshTasksAndCurrentDetail(taskDetail.task_id);
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
        description: 'Review the planned steps, files, and risks before approving this version.',
        actionLabel: 'Review Plan',
        actionIcon: Play,
        actionType: 'review_plan',
        color: 'emerald',
      };
    }
    if (st === 'APPROVED') {
      return {
        stage: 'Execution',
        headline: 'Plan Approved — Ready to Launch Autonomous Agent',
        description: 'Sandbox workspace will be provisioned on an isolated git branch.',
        actionLabel: 'Run Approved Plan',
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
        description: `Running ${testRunner.runningName} verification to ensure zero regressions.`,
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
        color: 'emerald',
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
        color: 'emerald',
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
    testRunner.runningName,
  ]);

  const handlePrimaryStepAction = () => {
    if (!nextStepInfo) return;
    switch (nextStepInfo.actionType) {
      case 'generate_plan':
        handleGenerateOrRevisePlan();
        break;
      case 'review_plan':
        setActiveTab('plan');
        void planQuery.refetch({ cancelRefetch: false });
        requestAnimationFrame(() => planPanel.current?.scrollIntoView?.({ block: 'start' }));
        break;
      case 'execute':
        handleRunWorkflow();
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
        if (draftPR?.pr_url) window.open(draftPR.pr_url, '_blank', 'noopener,noreferrer');
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
    <div className="flex flex-col h-full bg-background text-foreground overflow-hidden font-sans">
      {/* Studio Toolbar */}
      <header className="min-h-12 py-2 shrink-0 border-b border-border bg-card px-3 sm:px-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-xs font-semibold text-foreground min-w-0">
          <button
            type="button"
            onClick={() =>
              setMobileTaskListOpen((v) => {
                const next = !v;
                if (next) setShowActivityFeed(false);
                return next;
              })
            }
            aria-expanded={mobileTaskListOpen}
            aria-controls="task-studio-sidebar"
            aria-label="Toggle task list"
            className="lg:hidden inline-flex items-center gap-1.5 px-2 py-1.5 text-xs font-medium rounded-md border border-border bg-background text-foreground hover:bg-accent transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ListChecks className="h-3.5 w-3.5" />
            <span>Tasks</span>
          </button>
          <ListChecks className="hidden lg:block h-4 w-4 text-muted-foreground shrink-0" />
          <span className="truncate">Task Planner</span>
          {repository?.name && (
            <span className="hidden sm:inline text-[11px] font-mono text-muted-foreground font-normal truncate">
              · {repository.name}
              {repository.default_branch ? ` (${repository.default_branch})` : ''}
            </span>
          )}
          <span className="text-[11px] font-mono text-muted-foreground font-normal shrink-0">
            {tasks.length} {tasks.length === 1 ? 'task' : 'tasks'}
          </span>
        </div>

        <div className="flex items-center gap-1.5 sm:gap-2 flex-wrap">
          <button
            type="button"
            onClick={() =>
              setShowActivityFeed((v) => {
                const next = !v;
                if (next) setMobileTaskListOpen(false);
                return next;
              })
            }
            aria-pressed={showActivityFeed}
            className={cn(
              'inline-flex items-center gap-1.5 px-2 sm:px-2.5 py-1.5 text-xs font-medium rounded-md border transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              showActivityFeed
                ? 'bg-accent text-foreground border-border'
                : 'border-border bg-background text-muted-foreground hover:text-foreground hover:bg-accent'
            )}
            title="Toggle Activity Feed"
          >
            <History className="h-3.5 w-3.5" />
            <span>Activity</span>
            {events.length > 0 && (
              <span className="font-mono text-[10px] text-muted-foreground">{events.length}</span>
            )}
          </button>

          <button
            type="button"
            onClick={() => setShowImportIssueModal(true)}
            aria-label="Import GitHub Issue"
            className="inline-flex items-center gap-1.5 px-2 sm:px-2.5 py-1.5 text-xs font-medium rounded-md border border-border bg-background hover:bg-accent text-muted-foreground hover:text-foreground transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <GitPullRequest className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Import Issue</span>
            <span className="sm:hidden">Import</span>
          </button>

          <button
            type="button"
            onClick={() => refreshTasksAndCurrentDetail()}
            disabled={actionBusy !== null}
            aria-label="Refresh Studio State"
            className="p-1.5 rounded-md border border-border bg-background hover:bg-accent text-muted-foreground hover:text-foreground transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            title="Refresh Studio State"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', actionBusy && 'animate-spin')} />
          </button>

          <button
            type="button"
            onClick={() => setShowNewTaskModal(true)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Plus className="h-3.5 w-3.5" />
            <span>New Task</span>
          </button>
        </div>
      </header>

      {/* Error Alert Banner */}
      {(errorBanner || taskListError || taskDetailError) && (
        <div
          role="alert"
          className="shrink-0 bg-destructive/10 border-b border-destructive/25 px-4 py-2.5 text-xs text-destructive flex items-center justify-between gap-3"
        >
          <div className="flex items-center gap-2 min-w-0">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span className="break-words">
              {errorBanner ??
                (taskDetailError
                  ? `Could not load the task. ${taskDetailError.message}`
                  : `Could not load repository tasks. ${taskListError?.message ?? ''}`)}
            </span>
          </div>
          <button
            type="button"
            onClick={() => (errorBanner ? setErrorBanner(null) : refreshTasksAndCurrentDetail())}
            className="text-xs font-medium underline shrink-0 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
          >
            {errorBanner ? 'Dismiss' : 'Retry'}
          </button>
        </div>
      )}

      {/* -------------------------------------------------------------------- */}
      {/* 2. Main Studio Workspace Layout                                      */}
      {/* -------------------------------------------------------------------- */}
      <div className="flex-1 min-h-0 flex relative overflow-hidden">
        {mobileTaskListOpen && (
          <div
            className="absolute inset-0 z-30 bg-background/80 backdrop-blur-sm lg:hidden"
            aria-hidden="true"
            onClick={() => setMobileTaskListOpen(false)}
          />
        )}

        {/* Left Sidebar: Task List */}
        <aside
          id="task-studio-sidebar"
          className={cn(
            'absolute inset-y-0 left-0 z-40 w-72 sm:w-80 shrink-0 border-r border-border bg-card flex flex-col min-h-0 transition-transform duration-200 ease-out shadow-xl',
            'lg:static lg:z-auto lg:translate-x-0 lg:bg-card/30 lg:shadow-none',
            mobileTaskListOpen ? 'translate-x-0' : '-translate-x-full'
          )}
        >
          <div className="lg:hidden px-3 py-2 border-b border-border flex items-center justify-between">
            <span className="text-xs font-semibold text-foreground">Tasks</span>
            <button
              type="button"
              onClick={() => setMobileTaskListOpen(false)}
              aria-label="Close task list"
              className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-accent cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          <div className="p-3 border-b border-border/60 flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <input
                type="text"
                aria-label="Search tasks"
                placeholder="Search tasks..."
                value={taskSearchFilter}
                onChange={(e) => setTaskSearchFilter(e.target.value)}
                className="w-full pl-8 pr-2.5 py-1 text-xs rounded-md border border-border bg-background text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
                  className="px-3 py-1.5 rounded-md bg-primary/10 hover:bg-primary/20 text-primary text-xs font-medium transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
                      'w-full text-left p-2.5 rounded-lg border transition-all cursor-pointer space-y-1.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
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
        <main className="flex-1 min-w-0 min-h-0 flex flex-col overflow-hidden bg-background/50">
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
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-xs font-semibold shadow-md shadow-primary/20 hover:bg-primary/90 transition-all cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
                      <span className="inline-flex items-center gap-1 text-[11px] font-mono text-foreground bg-muted px-2 py-0.5 rounded border border-border">
                        <GitBranch className="h-3 w-3 text-muted-foreground" />
                        <span>{workspaceMeta.branch_name}</span>
                      </span>
                    )}

                    {draftPR && (
                      <a
                        href={draftPR.pr_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/25 text-xs font-mono text-emerald-700 dark:text-emerald-400 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <GitPullRequest className="h-3 w-3" />
                        <span>Draft PR #{draftPR.pr_number}</span>
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    )}
                  </div>

                  {/* Secondary control actions */}
                  <div className="flex items-center gap-2 flex-wrap">
                    {taskDetail.status !== 'CANCELLED' &&
                      taskDetail.status !== 'FAILED' &&
                      taskDetail.status !== 'DRAFT_PR_CREATED' && (
                        <button
                          type="button"
                          disabled={actionBusy !== null}
                          onClick={handleCancelTask}
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-border hover:bg-destructive/10 hover:border-destructive/30 text-muted-foreground hover:text-destructive text-xs font-medium transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400 text-xs font-medium hover:bg-amber-500/20 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <RotateCcw className="h-3 w-3" />
                        <span>Recover</span>
                      </button>
                    )}
                  </div>
                </div>

                {loadingDetail && (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground font-mono">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    <span>Synchronizing task details...</span>
                  </div>
                )}

                <h2 className="text-lg font-semibold tracking-tight text-foreground break-words leading-snug">
                  {taskDetail.title}
                </h2>
              </div>

              {/* Next-Step Action Card */}
              {nextStepInfo && (
                <div className="rounded-xl border border-border bg-card p-4 flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4">
                  <div className="space-y-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-mono uppercase font-semibold tracking-wider px-2 py-0.5 rounded bg-muted text-muted-foreground">
                        Next: {nextStepInfo.stage}
                      </span>
                      {nextStepInfo.inProgress && (
                        <span className="inline-flex items-center gap-1 text-[11px] font-medium text-sky-700 dark:text-sky-400">
                          <Loader2 className="h-3 w-3 animate-spin" />
                          <span>In progress</span>
                        </span>
                      )}
                    </div>
                    <div className="text-sm font-semibold text-foreground leading-snug">
                      {nextStepInfo.headline}
                    </div>
                    <div className="text-xs text-muted-foreground leading-relaxed">
                      {nextStepInfo.description}
                    </div>
                  </div>

                  {/* Primary CTA Button */}
                  <div className="flex items-center gap-2 shrink-0 flex-wrap">
                    <button
                      type="button"
                      disabled={nextStepInfo.actionType === 'review_plan'
                        ? planQuery.isFetching && !latestPlan
                        : actionBusy !== null || (nextStepInfo.actionType === 'execute' && Boolean(executionBlocker))}
                      onClick={handlePrimaryStepAction}
                      className="inline-flex items-center justify-center gap-1.5 px-4 py-2 rounded-lg text-xs font-medium bg-primary hover:bg-primary/90 text-primary-foreground transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      {(nextStepInfo.actionType === 'review_plan' ? planQuery.isFetching : actionBusy) ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <nextStepInfo.actionIcon className="h-3.5 w-3.5" />
                      )}
                      <span>{nextStepInfo.actionLabel}</span>
                    </button>
                  </div>
                </div>
              )}

              {/* Unified Step & Tab Navigation Bar */}
              <div
                role="tablist"
                aria-label="Task workflow phases"
                className="border-b border-border flex items-center gap-1 overflow-x-auto scrollbar-none"
              >
                {[
                  { id: 'plan', label: '1. Plan', icon: ListChecks, activeStages: ['CREATED', 'PLANNING', 'PENDING_APPROVAL', 'APPROVED'] },
                  { id: 'workspace', label: '2. Sandbox', icon: Terminal, activeStages: ['WORKSPACE_SETUP', 'EXECUTING'] },
                  { id: 'tests', label: '3. Tests', icon: FlaskConical, activeStages: ['TESTING', 'REPAIRING'] },
                  { id: 'changes', label: '4. Diff', icon: FileDiff, activeStages: [] },
                  { id: 'verification', label: '5. Verify', icon: ShieldCheck, activeStages: ['VERIFYING'] },
                  { id: 'pr', label: '6. Pull Request', icon: GitPullRequest, activeStages: ['READY_FOR_PUBLICATION', 'PUBLISHING', 'DRAFT_PR_CREATED'] },
                ].map((tab) => {
                  const isSelected = activeTab === tab.id;
                  const isCurrentStage = tab.activeStages.includes(taskDetail.status);
                  const TabIcon = tab.icon;
                  return (
                    <button
                      key={tab.id}
                      id={`studio-tab-${tab.id}`}
                      type="button"
                      role="tab"
                      aria-selected={isSelected}
                      aria-controls={`studio-tabpanel-${tab.id}`}
                      onClick={() => setActiveTab(tab.id as StudioTab)}
                      className={cn(
                        'flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 transition-colors shrink-0 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                        isSelected
                          ? 'border-foreground text-foreground font-semibold'
                          : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'
                      )}
                    >
                      <TabIcon className="h-3.5 w-3.5" />
                      <span>{tab.label}</span>
                      {isCurrentStage && (
                        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 ml-0.5" />
                      )}
                    </button>
                  );
                })}
              </div>

              {/* ------------------------------------------------------------ */}
              {/* Decomposed Per-Phase Studio Subcomponents (Issue 2 — C.3)    */}
              {/* ------------------------------------------------------------ */}
              <div
                role="tabpanel"
                id={`studio-tabpanel-${activeTab}`}
                aria-labelledby={`studio-tab-${activeTab}`}
                className="space-y-4"
              >
                {activeTab === 'plan' && promptReview?.task_id === taskDetail.task_id && latestPlan?.plan_version === 1 && (
                  <section aria-label="Prompt analysis" className="rounded-lg border border-border bg-card p-3 space-y-1.5 text-xs text-muted-foreground">
                    <p className="text-foreground">
                      Detected intent:{' '}
                      {[promptReview.intent_analysis.primary_intent, ...promptReview.intent_analysis.secondary_intents]
                        .map((intent) => intent.replaceAll('_', ' '))
                        .join(', ')}
                    </p>
                    {promptReview.critic_review.issues.map((issue, index) => (
                      <p key={index}>{issue.message}</p>
                    ))}
                  </section>
                )}

                {(needsPinnedPlan || taskDetail.status === 'APPROVED') && executionBlocker && (
                  <div
                    role="status"
                    className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-800 dark:text-amber-300 space-y-1.5"
                  >
                    <p>{executionBlocker}</p>
                    {needsPinnedPlan ? (
                      <button
                        type="button"
                        className="font-medium underline cursor-pointer disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
                        disabled={actionBusy !== null}
                        onClick={() => void handleGenerateOrRevisePlan()}
                      >
                        Regenerate plan
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="font-medium underline cursor-pointer disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
                        disabled={readinessQuery.isFetching}
                        onClick={() => void readinessQuery.refetch()}
                      >
                        Check sandbox again
                      </button>
                    )}
                  </div>
                )}

                {activeTab === 'plan' && (
                  <div ref={planPanel}>
                    {planQuery.isError && (
                      <p role="alert" className="mb-3 text-xs text-destructive">
                        Could not refresh the saved plan. {planQuery.error.message}
                      </p>
                    )}
                    {planQuery.isFetching && !latestPlan ? (
                      <p role="status" className="text-xs text-muted-foreground">
                        Loading saved plan…
                      </p>
                    ) : (
                      <RepositoryTaskPlanTab
                        taskDetail={taskDetail}
                        latestPlan={latestPlan}
                        showRevisionInput={showRevisionInput}
                        setShowRevisionInput={setShowRevisionInput}
                        showRejectionInput={showRejectionInput}
                        setShowRejectionInput={setShowRejectionInput}
                        revisionNotes={revisionNotes}
                        setRevisionNotes={setRevisionNotes}
                        rejectionReason={rejectionReason}
                        setRejectionReason={setRejectionReason}
                        approvalComment={approvalComment}
                        approvalBlocked={needsPinnedPlan}
                        setApprovalComment={setApprovalComment}
                        actionBusy={actionBusy}
                        handleGenerateOrRevisePlan={handleGenerateOrRevisePlan}
                        handleRejectPlan={handleRejectPlan}
                        handleApprovePlan={handleApprovePlan}
                      />
                    )}
                  </div>
                )}

                {activeTab === 'workspace' && workflow?.status && workflow.status !== 'IDLE' && (
                  <section
                    aria-label="Workflow status"
                    role="status"
                    className="rounded-lg border border-border bg-card p-3 space-y-1 text-xs text-muted-foreground"
                  >
                    <p className="font-medium text-foreground">
                      {(workflow.current_step || workflow.status).replaceAll('_', ' ')}
                    </p>
                    <p>
                      {workflow.durability_mode === 'DBOS_DURABLE'
                        ? 'DBOS workflow'
                        : 'Runs on the current API process'}
                    </p>
                    {workflow.error_summary && (
                      <p className="text-destructive">{workflow.error_summary}</p>
                    )}
                  </section>
                )}

                {activeTab === 'workspace' && (
                  <RepositoryTaskWorkspaceTab
                    hasWorkspace={hasWorkspace}
                    workspaceMeta={workspaceMeta}
                    latestPlan={latestPlan}
                    actionBusy={actionBusy}
                    handlePauseTask={handlePauseTask}
                    handleResumeTask={handleResumeTask}
                    handleCommitChanges={handleCommitChanges}
                    handleExecuteTask={handleExecuteTask}
                    taskStatus={taskDetail.status}
                    handleRecoverTask={handleRecoverTask}
                  />
                )}

                {activeTab === 'tests' && (
                  <RepositoryTaskTestsTab
                    taskId={taskDetail.task_id}
                    testResults={testResults}
                    actionBusy={actionBusy}
                    repairAttemptsUsed={repairAttemptsUsed}
                    repairAttemptsMax={repairAttemptsMax}
                    handleRunTests={handleRunTests}
                    handleRunRepair={handleRunRepair}
                    testRunnerLabel={testRunner.runLabel}
                  />
                )}

                {activeTab === 'changes' && (
                  <RepositoryTaskChangesTab
                    taskId={taskDetail.task_id}
                    repositoryId={repoId}
                    plannedTargetFiles={latestPlan?.expected_files ?? []}
                  />
                )}

                {activeTab === 'verification' && (
                  <RepositoryTaskVerificationTab
                    taskId={taskDetail.task_id}
                    currentRevision={taskDetail.base_revision}
                    actionBusy={actionBusy}
                    handleRunVerification={handleRunVerification}
                  />
                )}

                {activeTab === 'pr' && (
                  <RepositoryTaskPrTab
                    draftPR={draftPR}
                    verificationResult={verificationResult}
                    publicationAuthorized={publicationAuthorized}
                    setPublicationAuthorized={setPublicationAuthorized}
                    actionBusy={actionBusy}
                    handleCreateDraftPR={handleCreateDraftPR}
                  />
                )}
              </div>
            </div>
          )}
        </main>

        {/* Right Sidebar: Activity Timeline (collapsible) */}
        {showActivityFeed && (
          <>
            <div
              className="absolute inset-0 z-30 bg-background/80 backdrop-blur-sm lg:hidden"
              aria-hidden="true"
              onClick={() => setShowActivityFeed(false)}
            />
            <aside
              aria-label="Activity Feed"
              className="absolute inset-y-0 right-0 z-40 w-full max-w-xs sm:w-80 shrink-0 border-l border-border bg-card shadow-xl flex flex-col min-h-0 lg:static lg:z-auto lg:shadow-none lg:bg-card/40"
            >
              <div className="p-3 border-b border-border flex items-center justify-between">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
                  <History className="h-3.5 w-3.5 text-muted-foreground" />
                  <span>Activity Feed</span>
                </div>
                <button
                  type="button"
                  onClick={() => setShowActivityFeed(false)}
                  className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-accent cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  aria-label="Close activity feed"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
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
          </>
        )}
      </div>

      {/* -------------------------------------------------------------------- */}
      {/* 3. Sleek "New Task" Creation Modal                                   */}
      {/* -------------------------------------------------------------------- */}
      {showNewTaskModal && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="new-task-modal-title"
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowNewTaskModal(false);
          }}
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-background/80 backdrop-blur-sm animate-in fade-in duration-150"
        >
          <div className="w-full max-w-lg rounded-2xl border border-border bg-card p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <div className="h-8 w-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center text-primary shrink-0">
                  <Bot className="h-4 w-4" />
                </div>
                <div className="min-w-0">
                  <h3 id="new-task-modal-title" className="text-sm font-bold text-foreground">
                    Launch Autonomous AI Task
                  </h3>
                  <p className="text-[11px] text-muted-foreground">Write only what you want done. The agent handles planning and execution.</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowNewTaskModal(false)}
                aria-label="Close new task modal"
                className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted cursor-pointer shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <form onSubmit={handleCreateNewTask} className="space-y-4">
              <div>
                <label htmlFor="new-task-prompt" className="text-xs font-semibold text-foreground block mb-1.5">
                  What do you want the AI to build or fix?
                </label>
                <textarea
                  id="new-task-prompt"
                  rows={4}
                  minLength={3}
                  maxLength={10000}
                  required
                  autoFocus
                  value={newTaskPrompt}
                  onChange={(e) => setNewTaskPrompt(e.target.value)}
                  placeholder="e.g. Change page background color to white and update CSS styling..."
                  className="w-full px-3.5 py-2.5 text-xs rounded-xl border border-border bg-background text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring leading-relaxed font-normal"
                />
              </div>

              {promptReview?.ambiguity_detected && (
                <ul aria-label="Clarification questions" className="list-disc pl-4 text-xs text-amber-300">
                  {promptReview.clarifications.map((question) => <li key={question}>{question}</li>)}
                </ul>
              )}

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
                      className="px-2 py-1 rounded-md bg-muted/40 hover:bg-primary/10 hover:text-primary text-[11px] text-muted-foreground border border-border/50 transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      {starter.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="pt-2 border-t border-border/60 flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <ShieldCheck className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400 shrink-0" />
                  <span>Mandatory Review: Plan will be presented for your approval</span>
                </div>

                <div className="flex items-center gap-2 ml-auto">
                  <button
                    type="button"
                    onClick={() => setShowNewTaskModal(false)}
                    className="px-3 py-1.5 text-xs font-medium rounded-lg border border-border hover:bg-accent cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={actionBusy !== null || !newTaskPrompt.trim()}
                    className="px-4 py-1.5 text-xs font-bold rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-all shadow-sm cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="import-issue-modal-title"
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowImportIssueModal(false);
          }}
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-background/80 backdrop-blur-sm animate-in fade-in duration-150"
        >
          <div className="w-full max-w-sm rounded-2xl border border-border bg-card p-5 shadow-2xl space-y-4">
            <div className="flex items-center justify-between gap-2">
              <h3 id="import-issue-modal-title" className="text-sm font-bold text-foreground">
                Import GitHub Issue
              </h3>
              <button
                type="button"
                onClick={() => setShowImportIssueModal(false)}
                aria-label="Close import issue modal"
                className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <form onSubmit={handleImportIssue} className="space-y-3">
              <div>
                <label htmlFor="import-issue-number" className="text-xs font-semibold text-foreground block mb-1">
                  GitHub Issue Number
                </label>
                <input
                  id="import-issue-number"
                  type="number"
                  min={1}
                  required
                  autoFocus
                  placeholder="e.g. 42"
                  value={issueNumberInput}
                  onChange={(e) => setIssueNumberInput(e.target.value)}
                  className="w-full px-3 py-2 text-xs rounded-lg border border-border bg-background text-foreground font-mono focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-border/60">
                <button
                  type="button"
                  onClick={() => setShowImportIssueModal(false)}
                  className="px-3 py-1.5 text-xs font-medium rounded-lg border border-border hover:bg-accent cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionBusy !== null || !issueNumberInput.trim()}
                  className="px-4 py-1.5 text-xs font-bold rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-all cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {actionBusy === 'import' ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <span>Import &amp; Plan</span>
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
