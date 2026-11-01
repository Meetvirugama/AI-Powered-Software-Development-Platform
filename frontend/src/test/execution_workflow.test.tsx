import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, fireEvent, waitFor, render } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';
import { resetMockStore } from '../mocks/handlers';
import {
  TaskStatus,
  WorkspaceStatus,
  type TaskDetailResponse,
  type WorkspaceMetadata,
  type TaskDiffRanges,
  type TaskTestResultsResponse,
  type WorkspaceRepairBudgetStatus,
  type TaskEvent,
} from '../types/task';
import { TaskDetail } from '../pages/TaskDetail';
import { TaskCard } from '../components/tasks/TaskCard';
import { WorkspacePanel } from '../components/tasks/WorkspacePanel';
import { CodeChangesPanel } from '../components/tasks/CodeChangesPanel';
import { TestExecutionPanel } from '../components/tasks/TestExecutionPanel';
import { RepairBudgetTracker } from '../components/tasks/RepairBudgetTracker';
import { ExecutionTimeline } from '../components/tasks/ExecutionTimeline';

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
      mutations: {
        retry: false,
      },
    },
  });
}

function renderWithProviders(ui: React.ReactElement, initialRoute = '/app/tasks/task-exec-approved') {
  const queryClient = createTestQueryClient();
  return {
    ...render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[initialRoute]}>
          <Routes>
            <Route path="/app/tasks" element={ui} />
            <Route path="/app/tasks/:taskId" element={ui} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    ),
    queryClient,
  };
}

describe('Week 3 Day 3 & Day 4 — Execution Workflow & Telemetry', () => {
  beforeEach(() => {
    resetMockStore();
  });

  // ==========================================================================
  // 1. Start Execution Controls & Approval Gatekeeping
  // ==========================================================================
  describe('Start Execution & Approval Gatekeeping', () => {
    it('renders Start Execution button when task status is APPROVED', async () => {
      renderWithProviders(<TaskDetail />, '/app/tasks/task-exec-approved');

      await waitFor(() => {
        expect(screen.getByRole('heading', { name: 'Ready for Execution Start' })).toBeInTheDocument();
      });

      const startBtn = screen.getByRole('button', { name: /Start Execution/i });
      expect(startBtn).toBeInTheDocument();
      expect(startBtn).toBeEnabled();
    });

    it('does NOT render Start Execution button when task status is PENDING_APPROVAL', async () => {
      renderWithProviders(<TaskDetail />, '/app/tasks/task-seed-1');

      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /Fix Token Budget Overflow/i })).toBeInTheDocument();
      });

      expect(screen.queryByRole('button', { name: /Start Execution/i })).toBeNull();
    });

    it('does NOT render Start Execution button when task is REJECTED or CREATED', async () => {
      renderWithProviders(<TaskDetail />, '/app/tasks/task-seed-4'); // REJECTED

      await waitFor(() => {
        expect(
          screen.getByRole('heading', { name: /Refactor Database Migration Runner to Async/i })
        ).toBeInTheDocument();
      });

      expect(screen.queryByRole('button', { name: /Start Execution/i })).toBeNull();
    });

    it('dispatches execute mutation, shows loading state, and transitions task to WORKSPACE_SETUP', async () => {
      renderWithProviders(<TaskDetail />, '/app/tasks/task-exec-approved');

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Start Execution/i })).toBeInTheDocument();
      });

      const startBtn = screen.getByRole('button', { name: /Start Execution/i });
      fireEvent.click(startBtn);

      // Verify pending/loading state prevents duplicate execution clicks
      await waitFor(() => {
        expect(screen.queryByRole('button', { name: /Start Execution/i })).toBeNull();
      });

      // Verify active execution banner appears
      await waitFor(() => {
        expect(screen.getByTestId('active-execution-indicator')).toBeInTheDocument();
        expect(screen.getByText('Workspace Setup in Progress')).toBeInTheDocument();
      });
    });

    it('displays server error alert when execute fails with APPROVAL_REQUIRED', async () => {
      server.use(
        http.post('*/api/v1/tasks/:taskId/execute', () => {
          return HttpResponse.json(
            {
              error: {
                code: 'APPROVAL_REQUIRED',
                message: 'Human approval of the plan is required before this action can proceed.',
                retryable: false,
              },
            },
            { status: 409 }
          );
        })
      );

      renderWithProviders(<TaskDetail />, '/app/tasks/task-exec-approved');

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Start Execution/i })).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole('button', { name: /Start Execution/i }));

      await waitFor(() => {
        expect(
          screen.getByText(/Human approval of the plan is required before this action can proceed/i)
        ).toBeInTheDocument();
      });
    });

    it('invalidates sub-queries when user clicks manual refresh button in header', async () => {
      const { queryClient } = renderWithProviders(<TaskDetail />, '/app/tasks/task-exec-approved');

      await waitFor(() => {
        expect(screen.getByRole('heading', { name: 'Ready for Execution Start' })).toBeInTheDocument();
      });

      const refreshBtn = screen.getByTitle('Refresh task');
      expect(refreshBtn).toBeInTheDocument();

      const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
      fireEvent.click(refreshBtn);

      expect(invalidateSpy).toHaveBeenCalled();
    });
  });

  // ==========================================================================
  // 2. Cancellation Workflow
  // ==========================================================================
  describe('Task Cancellation', () => {
    it('renders Cancel Task button in non-terminal active execution states', async () => {
      renderWithProviders(<TaskDetail />, '/app/tasks/task-exec-diff'); // EXECUTING

      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /Code Modifications and Diff Inspection/i })).toBeInTheDocument();
      });

      const cancelBtn = screen.getByRole('button', { name: /Cancel Task/i });
      expect(cancelBtn).toBeInTheDocument();
      expect(cancelBtn).toBeEnabled();
    });

    it('does NOT render Cancel Task button for terminal states (CANCELLED, FAILED)', async () => {
      renderWithProviders(<TaskDetail />, '/app/tasks/task-seed-7'); // FAILED

      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /Automate End-to-End Test Container Teardown/i })).toBeInTheDocument();
      });

      expect(screen.queryByRole('button', { name: /Cancel Task/i })).toBeNull();
    });

    it('dispatches cancellation request, disables button during mutation, and updates status to CANCELLED', async () => {
      renderWithProviders(<TaskDetail />, '/app/tasks/task-exec-diff');

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Cancel Task/i })).toBeInTheDocument();
      });

      const cancelBtn = screen.getByRole('button', { name: /Cancel Task/i });
      fireEvent.click(cancelBtn);

      await waitFor(() => {
        // Status should transition to CANCELLED
        const badges = screen.getAllByText(/CANCELLED/i);
        expect(badges.length).toBeGreaterThan(0);
        // Cancel button must disappear once terminal
        expect(screen.queryByRole('button', { name: /Cancel Task/i })).toBeNull();
      });
    });
  });

  // ==========================================================================
  // 3. Workspace Panel Component
  // ==========================================================================
  describe('WorkspacePanel', () => {
    it('renders workspace metadata, branch name, isolation type, and resource limits', () => {
      const workspace: WorkspaceMetadata = {
        workspace_id: 'ws-test-123',
        task_id: 'task-123',
        repository_id: 'repo-1',
        base_revision: 'c1d2e3f4a5b6',
        branch_name: 'agent/task-test-feature',
        workspace_path: '/sandboxes/task-123',
        status: WorkspaceStatus.READY,
        isolation_type: 'git_worktree',
        resource_limits: {
          timeout_seconds: 120,
          max_disk_bytes: 1073741824, // 1 GB
          max_file_size_bytes: 10485760, // 10 MB
          max_files_modified: 100,
          network_egress_allowed: false,
        },
        created_at: '2026-10-20T09:00:00.000Z',
        updated_at: '2026-10-20T09:05:00.000Z',
      };

      renderWithProviders(<WorkspacePanel workspace={workspace} isLoading={false} error={null} />);

      expect(screen.getByText('ws-test-123')).toBeInTheDocument();
      expect(screen.getByText('agent/task-test-feature')).toBeInTheDocument();
      expect(screen.getByText('c1d2e3f4a5b6')).toBeInTheDocument();
      expect(screen.getByText('/sandboxes/task-123')).toBeInTheDocument();
      expect(screen.getByText(/READY/i)).toBeInTheDocument();
      expect(screen.getByText(/Timeout: 120s/i)).toBeInTheDocument();
      expect(screen.getByText(/Disk: 1024 MB/i)).toBeInTheDocument();
      expect(screen.getByText(/Max File: 10 MB/i)).toBeInTheDocument();
      expect(screen.getByText(/Max Files: 100/i)).toBeInTheDocument();
      expect(screen.getByText(/Network Egress:/i)).toBeInTheDocument();
      expect(screen.getByText(/Strictly Blocked/i)).toBeInTheDocument();
    });

    it('renders error banner when workspace status is FAILED and does not show success', () => {
      const failedWs: WorkspaceMetadata = {
        workspace_id: 'ws-fail-999',
        task_id: 'task-fail',
        repository_id: 'repo-1',
        base_revision: 'abc1234',
        branch_name: 'agent/task-fail',
        status: WorkspaceStatus.FAILED,
        error_message: 'Failed to create Git worktree: disk quota exceeded.',
        created_at: '2026-10-20T09:00:00.000Z',
        updated_at: '2026-10-20T09:05:00.000Z',
      };

      renderWithProviders(<WorkspacePanel workspace={failedWs} isLoading={false} error={null} />);

      expect(screen.getByText(/Workspace Allocation or Execution Failed/i)).toBeInTheDocument();
      expect(screen.getByText(/disk quota exceeded/i)).toBeInTheDocument();
    });

    it('handles missing metadata without fabricating fake IDs or hashes', () => {
      const minimalWs: WorkspaceMetadata = {
        workspace_id: 'ws-min',
        task_id: 'task-min',
        repository_id: 'repo-1',
        base_revision: 'base-1',
        branch_name: 'agent/task-min',
        status: WorkspaceStatus.CREATING,
        created_at: '2026-10-20T09:00:00.000Z',
        updated_at: '2026-10-20T09:00:00.000Z',
      };

      renderWithProviders(<WorkspacePanel workspace={minimalWs} isLoading={false} error={null} />);

      expect(screen.getByText('ws-min')).toBeInTheDocument();
      expect(screen.getByText('agent/task-min')).toBeInTheDocument();
      expect(screen.getByText('base-1')).toBeInTheDocument();
      expect(screen.queryByText(/Resource Limits/i)).toBeNull();
      expect(screen.queryByText(/Workspace Filesystem Path/i)).toBeNull();
    });

    it('renders empty notice when workspace has not yet been allocated', () => {
      renderWithProviders(<WorkspacePanel workspace={null} isLoading={false} error={null} />);

      expect(screen.getByText(/Workspace Not Created/i)).toBeInTheDocument();
    });

    it('renders execution started_at and stopped_at timestamps when supplied', () => {
      const timestampWs: WorkspaceMetadata = {
        workspace_id: 'ws-time-1',
        task_id: 'task-time',
        repository_id: 'repo-1',
        base_revision: 'abc1234',
        branch_name: 'agent/task-time',
        status: WorkspaceStatus.STOPPED,
        started_at: '2026-10-20T09:10:00.000Z',
        stopped_at: '2026-10-20T09:40:00.000Z',
      };

      renderWithProviders(<WorkspacePanel workspace={timestampWs} isLoading={false} error={null} />);

      expect(screen.getByText('Started At')).toBeInTheDocument();
      expect(screen.getByText('Stopped At')).toBeInTheDocument();
    });
  });

  // ==========================================================================
  // 4. Code Changes & Diff Inspection Component
  // ==========================================================================
  describe('CodeChangesPanel', () => {
    it('distinguishes planned changes from actual git diff modifications', () => {
      const diffData: TaskDiffRanges = {
        task_id: 'task-diff-1',
        repository_id: 'repo-1',
        base_branch: 'main',
        head_branch: 'agent/task-diff-1',
        total_files_changed: 2,
        total_additions: 15,
        total_deletions: 4,
        files: [
          {
            file_path: 'src/analyzer/ast_walker.py',
            status: 'modified',
            additions: 10,
            deletions: 4,
            patch: '@@ -12,4 +12,10 @@\n- old()\n+ new()',
          },
          {
            file_path: 'tests/test_ast.py',
            status: 'added',
            additions: 5,
            deletions: 0,
            patch: '@@ -0,0 +1,5 @@\n+def test(): pass',
          },
        ],
      };

      const plannedFiles = ['src/analyzer/token_budget.py'];
      const targetFiles = ['src/analyzer/ast_walker.py'];

      renderWithProviders(
        <CodeChangesPanel
          diffData={diffData}
          plannedExpectedFiles={plannedFiles}
          plannedTargetFiles={targetFiles}
          isLoading={false}
          error={null}
        />
      );

      // Verify Planned Changes section
      expect(screen.getByText(/Planned Changes/i)).toBeInTheDocument();
      expect(screen.getByText('src/analyzer/token_budget.py')).toBeInTheDocument();

      // Verify Actual Git Modifications section
      expect(screen.getByText(/Actual Workspace Modifications/i)).toBeInTheDocument();
      expect(screen.getByText('tests/test_ast.py')).toBeInTheDocument();
      expect(screen.getByText('15')).toBeInTheDocument();
      expect(screen.getByText('4')).toBeInTheDocument();

      // Verify patches render in code block
      expect(screen.getByText(/@@ -12,4 \+12,10 @@/i)).toBeInTheDocument();
    });

    it('renders empty diff state when 0 files were changed', () => {
      const emptyDiff: TaskDiffRanges = {
        task_id: 'task-empty',
        repository_id: 'repo-1',
        base_branch: 'main',
        head_branch: 'agent/task-empty',
        total_files_changed: 0,
        total_additions: 0,
        total_deletions: 0,
        files: [],
      };

      renderWithProviders(
        <CodeChangesPanel
          diffData={emptyDiff}
          plannedExpectedFiles={[]}
          plannedTargetFiles={[]}
          isLoading={false}
          error={null}
        />
      );

      expect(screen.getByText(/No Actual Changes Detected/i)).toBeInTheDocument();
    });

    it('renders unavailable notice when diff telemetry has not been generated', () => {
      renderWithProviders(
        <CodeChangesPanel
          diffData={null}
          plannedExpectedFiles={['src/core.py']}
          plannedTargetFiles={['src/core.py']}
          isLoading={false}
          error={null}
        />
      );

      expect(screen.getByText(/Diff Telemetry Unavailable/i)).toBeInTheDocument();
    });
  });

  // ==========================================================================
  // 5. Test Execution Results Component
  // ==========================================================================
  describe('TestExecutionPanel', () => {
    it('displays passing test runs with duration, counts, and exit code', () => {
      const passingTests: TaskTestResultsResponse = {
        task_id: 'task-pass',
        runs: [
          {
            attempt: 1,
            command: 'pytest tests/test_ast.py',
            status: 'PASSED',
            exit_code: 0,
            duration_ms: 1250,
            tests_total: 10,
            tests_passed: 10,
            tests_failed: 0,
            framework: 'pytest',
            stdout: '10 passed in 1.25s',
            executed_at: '2026-10-20T10:10:00.000Z',
          },
        ],
        repair_attempts_used: 0,
        repair_attempts_max: 3,
      };

      renderWithProviders(<TestExecutionPanel testResults={passingTests} isLoading={false} error={null} />);

      expect(screen.getByText('pytest tests/test_ast.py')).toBeInTheDocument();
      expect(screen.getByText('Passed')).toBeInTheDocument();
      expect(screen.getByText('1.25 s')).toBeInTheDocument();
      expect(screen.getAllByText(/10 passed/i).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText(/0 failed/i)).toBeInTheDocument();
    });

    it('distinguishes repair-eligible assertion failure from ineligible failures', () => {
      const failureTests: TaskTestResultsResponse = {
        task_id: 'task-fail-tests',
        runs: [
          {
            attempt: 1,
            command: 'pytest tests/test_budget.py',
            status: 'FAILED',
            classification: 'TEST_FAILURE',
            is_repair_eligible: true,
            exit_code: 1,
            duration_ms: 850,
            tests_total: 5,
            tests_passed: 4,
            tests_failed: 1,
            stderr: 'AssertionError: limit exceeded',
            executed_at: '2026-10-20T10:15:00.000Z',
          },
        ],
        repair_attempts_used: 0,
        repair_attempts_max: 3,
      };

      renderWithProviders(<TestExecutionPanel testResults={failureTests} isLoading={false} error={null} />);

      expect(screen.getByText('Assertion Failure')).toBeInTheDocument();
      expect(screen.getByText('Repair Eligible')).toBeInTheDocument();
      expect(screen.getByText(/AssertionError: limit exceeded/i)).toBeInTheDocument();
    });

    it('distinguishes infrastructure failure and marks as not repair eligible', () => {
      const infraTests: TaskTestResultsResponse = {
        task_id: 'task-infra',
        runs: [
          {
            attempt: 1,
            command: 'pytest',
            status: 'FAILED',
            classification: 'INFRASTRUCTURE_ERROR',
            is_repair_eligible: false,
            exit_code: 2,
            duration_ms: 300,
            tests_total: 0,
            tests_passed: 0,
            tests_failed: 0,
            error_count: 1,
            stderr: 'ModuleNotFoundError: No module named pytest_cov',
            executed_at: '2026-10-20T10:20:00.000Z',
          },
        ],
        repair_attempts_used: 0,
        repair_attempts_max: 3,
      };

      renderWithProviders(<TestExecutionPanel testResults={infraTests} isLoading={false} error={null} />);

      expect(screen.getByText('Infrastructure Failure')).toBeInTheDocument();
      expect(screen.getByText('ModuleNotFoundError: No module named pytest_cov')).toBeInTheDocument();
      expect(screen.getByText('2')).toBeInTheDocument(); // Exit Code
    });

    it('distinguishes timeout outcome and marks as not repair eligible', () => {
      const timeoutTests: TaskTestResultsResponse = {
        task_id: 'task-timeout',
        runs: [
          {
            attempt: 1,
            command: 'pytest --timeout=30',
            status: 'TIMEOUT',
            classification: 'TIMEOUT',
            is_repair_eligible: false,
            exit_code: 124,
            duration_ms: 30000,
            tests_total: 4,
            tests_passed: 2,
            tests_failed: 1,
            skipped_count: 1,
            stderr: 'Execution timed out after 30s',
            executed_at: '2026-10-20T10:25:00.000Z',
          },
        ],
        repair_attempts_used: 0,
        repair_attempts_max: 3,
      };

      renderWithProviders(<TestExecutionPanel testResults={timeoutTests} isLoading={false} error={null} />);

      expect(screen.getByText('Timeout')).toBeInTheDocument();
      expect(screen.getByText('30.00 s')).toBeInTheDocument();
      expect(screen.getByText(/1 skipped/i)).toBeInTheDocument();
    });

    it('CORRECTNESS RULE: Never displays unavailable or missing tests as passed', () => {
      renderWithProviders(<TestExecutionPanel testResults={null} isLoading={false} error={null} />);

      expect(screen.queryByText(/Passed/i)).toBeNull();
      expect(screen.getByText(/No Tests Executed Yet/i)).toBeInTheDocument();
    });

    it('supports count aliases and renders failed test names in expanded view', () => {
      const aliasTests: TaskTestResultsResponse = {
        task_id: 'task-alias',
        runs: [
          {
            attempt: 1,
            command: 'pytest',
            status: 'FAILED',
            classification: 'TEST_FAILURE',
            is_repair_eligible: true,
            exit_code: 1,
            duration_ms: 1500,
            tests_total: 8,
            passed_count: 6,
            failed_count: 2,
            tests_passed: 6,
            tests_failed: 2,
            failed_test_names: ['tests/test_parser.py::test_boundary', 'tests/test_parser.py::test_eof'],
            executed_at: '2026-10-20T10:15:00.000Z',
          },
        ],
        repair_attempts_used: 1,
        repair_attempts_max: 3,
      };

      renderWithProviders(<TestExecutionPanel testResults={aliasTests} isLoading={false} error={null} />);

      expect(screen.getByText('6 passed')).toBeInTheDocument();
      expect(screen.getByText('2 failed')).toBeInTheDocument();
      expect(screen.getByText('tests/test_parser.py::test_boundary')).toBeInTheDocument();
      expect(screen.getByText('tests/test_parser.py::test_eof')).toBeInTheDocument();
    });
  });

  // ==========================================================================
  // 6. Bounded Repair Budget Component
  // ==========================================================================
  describe('RepairBudgetTracker', () => {
    it('renders server-authoritative attempts used (2), max (3), and remaining attempts', () => {
      const budget: WorkspaceRepairBudgetStatus = {
        task_id: 'task-repair',
        repair_attempts_used: 2,
        repair_attempts_max: 3,
        is_budget_exhausted: false,
        is_eligible_for_repair: true,
        last_attempt_at: '2026-10-20T10:25:00.000Z',
        history: [
          {
            attempt_number: 1,
            task_id: 'task-repair',
            timestamp: '2026-10-20T10:15:00.000Z',
            patch_summary: 'Initial recursion depth limit patch',
            test_status_before: 'FAILED',
            test_status_after: 'FAILED',
            success: false,
          },
          {
            attempt_number: 2,
            task_id: 'task-repair',
            timestamp: '2026-10-20T10:25:00.000Z',
            patch_summary: 'Updated boundary condition',
            test_status_before: 'FAILED',
            test_status_after: 'PASSED',
            success: true,
          },
        ],
      };

      renderWithProviders(<RepairBudgetTracker budget={budget} isLoading={false} error={null} />);

      expect(screen.getByTestId('repair-attempts-count')).toHaveTextContent('2 / 3 Attempts Used');
      expect(screen.getByText(/1 attempt remaining/i)).toBeInTheDocument();
      expect(screen.getByText(/Attempt 1/i)).toBeInTheDocument();
      expect(screen.getByText(/Attempt 2/i)).toBeInTheDocument();
      expect(screen.getByText('Initial recursion depth limit patch')).toBeInTheDocument();
    });

    it('renders warning alert and explains automatic repair cannot continue when budget is exhausted', () => {
      const exhaustedBudget: WorkspaceRepairBudgetStatus = {
        task_id: 'task-exhausted',
        repair_attempts_used: 3,
        repair_attempts_max: 3,
        is_budget_exhausted: true,
        is_eligible_for_repair: false,
        last_attempt_at: '2026-10-20T10:30:00.000Z',
        history: [],
      };

      renderWithProviders(<RepairBudgetTracker budget={exhaustedBudget} isLoading={false} error={null} />);

      expect(screen.getByTestId('repair-attempts-count')).toHaveTextContent('3 / 3 Attempts Used');
      expect(screen.getByText(/0 attempts remaining/i)).toBeInTheDocument();
      expect(screen.getByText(/Repair Budget Exhausted/i)).toBeInTheDocument();
      expect(
        screen.getByText(/Maximum repair budget limit reached \(3\/3\)\. Automatic repair cannot continue/i)
      ).toBeInTheDocument();
    });

    it('renders unavailable state when repair telemetry is missing without inventing numbers', () => {
      renderWithProviders(<RepairBudgetTracker budget={null} isLoading={false} error={null} />);

      expect(screen.getByText(/Repair telemetry not available yet/i)).toBeInTheDocument();
    });

    it('queries repair budget via useTaskRepairBudget when taskId is provided', async () => {
      renderWithProviders(<RepairBudgetTracker taskId="task-exec-repair-history" />);

      await waitFor(() => {
        expect(screen.getByTestId('repair-attempts-count')).toHaveTextContent('2 / 3 Attempts Used');
        expect(screen.getByText('Initial recursion depth limit patch')).toBeInTheDocument();
        expect(screen.getByText('Updated token counter boundary condition')).toBeInTheDocument();
      });
    });
  });

  // ==========================================================================
  // 7. Execution Timeline with Day 3/4 Events
  // ==========================================================================
  describe('ExecutionTimeline Day 3/4 Events', () => {
    it('renders chronological Day 3/4 event stream with appropriate labels and descriptions', async () => {
      const mockEvents: TaskEvent[] = [
        {
          id: 'evt-1',
          task_id: 'task-tl',
          event_type: 'WORKSPACE_SETUP',
          description: 'Allocating isolated Git worktree workspace.',
          created_at: '2026-10-20T09:00:00.000Z',
        },
        {
          id: 'evt-2',
          task_id: 'task-tl',
          event_type: 'WORKSPACE_ALLOCATED',
          description: 'Workspace ready on branch agent/task-tl.',
          created_at: '2026-10-20T09:01:00.000Z',
        },
        {
          id: 'evt-3',
          task_id: 'task-tl',
          event_type: 'BRANCH_SETUP',
          description: 'Checked out branch at base revision.',
          created_at: '2026-10-20T09:02:00.000Z',
        },
        {
          id: 'evt-4',
          task_id: 'task-tl',
          event_type: 'EXECUTION_STARTED',
          description: 'Tool router executing plan steps.',
          created_at: '2026-10-20T09:03:00.000Z',
        },
        {
          id: 'evt-5',
          task_id: 'task-tl',
          event_type: 'CODE_MODIFICATION',
          description: 'Applied patch to file.',
          created_at: '2026-10-20T09:04:00.000Z',
        },
        {
          id: 'evt-6',
          task_id: 'task-tl',
          event_type: 'TESTS_EXECUTED',
          description: 'pytest completed: 10 passed.',
          created_at: '2026-10-20T09:05:00.000Z',
        },
        {
          id: 'evt-7',
          task_id: 'task-tl',
          event_type: 'REPAIR_ATTEMPT',
          description: 'Repair attempt 1 completed.',
          created_at: '2026-10-20T09:06:00.000Z',
        },
        {
          id: 'evt-8',
          task_id: 'task-tl',
          event_type: 'RETRY_BUDGET_EXHAUSTED',
          description: 'Repair budget exhausted.',
          created_at: '2026-10-20T09:07:00.000Z',
        },
        {
          id: 'evt-9',
          task_id: 'task-tl',
          event_type: 'TASK_CANCELLED',
          description: 'Task cancelled by user.',
          created_at: '2026-10-20T09:08:00.000Z',
        },
        {
          id: 'evt-10',
          task_id: 'task-tl',
          event_type: 'EXECUTION_TIMED_OUT',
          description: 'Execution exceeded 30 second limit.',
          created_at: '2026-10-20T09:09:00.000Z',
        },
      ];

      server.use(
        http.get('*/api/v1/tasks/:taskId/events', () => {
          return HttpResponse.json({
            items: mockEvents,
            total: mockEvents.length,
          });
        })
      );

      renderWithProviders(<ExecutionTimeline taskId="task-tl" />);

      await waitFor(() => {
        expect(screen.getByText('WORKSPACE SETUP')).toBeInTheDocument();
        expect(screen.getByText('WORKSPACE ALLOCATED')).toBeInTheDocument();
        expect(screen.getByText('BRANCH SETUP')).toBeInTheDocument();
        expect(screen.getByText('EXECUTION STARTED')).toBeInTheDocument();
        expect(screen.getByText('CODE MODIFICATION')).toBeInTheDocument();
        expect(screen.getByText('TESTS EXECUTED')).toBeInTheDocument();
        expect(screen.getByText('REPAIR ATTEMPT')).toBeInTheDocument();
        expect(screen.getByText('RETRY BUDGET EXHAUSTED')).toBeInTheDocument();
        expect(screen.getByText('TASK CANCELLED')).toBeInTheDocument();
        expect(screen.getByText('EXECUTION TIMED OUT')).toBeInTheDocument();
      });
    });

    it('gracefully renders unexpected or unknown event types without crashing', async () => {
      const unknownEvents: TaskEvent[] = [
        {
          id: 'evt-unk',
          task_id: 'task-unk',
          event_type: 'CUSTOM_FUTURE_EVENT' as any,
          description: 'A future event type from an external plugin.',
          created_at: '2026-10-20T09:00:00.000Z',
        },
      ];

      server.use(
        http.get('*/api/v1/tasks/:taskId/events', () => {
          return HttpResponse.json({
            items: unknownEvents,
            total: 1,
          });
        })
      );

      renderWithProviders(<ExecutionTimeline taskId="task-unk" />);

      await waitFor(() => {
        expect(screen.getByText('CUSTOM FUTURE EVENT')).toBeInTheDocument();
        expect(screen.getByText('A future event type from an external plugin.')).toBeInTheDocument();
      });
    });
  });

  // ==========================================================================
  // 8. Task Card Active Execution & Repair Indicators
  // ==========================================================================
  describe('TaskCard Active Execution Indicators', () => {
    it('renders active execution badge and repair counter in TaskCard', () => {
      const executingTask: TaskDetailResponse = {
        task_id: 'task-card-active',
        repository_id: 'repo-1',
        title: 'Active Executing Task with Repairs',
        description: 'Testing task card badges.',
        status: TaskStatus.EXECUTING,
        source: { type: 'USER_PROMPT', repository_id: 'repo-1' },
        requirements: [
          {
            id: 'req-1',
            description: 'R1',
            category: 'functional',
            target_files: ['src/main.ts'],
            acceptance_criteria: ['AC1'],
          },
        ],
        assumptions: [],
        constraints: [],
        base_revision: null,
        plan_version: 1,
        approved_plan_version: 1,
        repair_attempts_used: 1,
        repair_attempts_max: 3,
        created_at: '2026-10-20T09:00:00.000Z',
        updated_at: '2026-10-20T09:00:00.000Z',
      };

      renderWithProviders(<TaskCard task={executingTask} />);

      expect(screen.getByText('Active Executing Task with Repairs')).toBeInTheDocument();
      expect(screen.getByTestId('active-execution-badge-task-card-active')).toHaveTextContent('Executing');
      expect(screen.getByTestId('repair-budget-indicator-task-card-active')).toHaveTextContent('1/3');
    });
  });
});
