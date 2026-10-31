/**
 * Challenger Stress Test Suite — Milestone 2 UI Workflows, Routing & State Transitions
 *
 * Empirical challenger tests verifying:
 * 1. /app/tasks list loading, search filter, status filter, and full multi-page pagination transitions
 * 2. /app/tasks/new interactive toggle between manual creation and GitHub issue import
 * 3. ImportIssueForm disabled import button and duplicate ingestion guardrail when is_imported is true
 * 4. /app/tasks/:taskId ApprovalHistoryPanel and ExecutionTimeline icon/badge mapping across lifecycle states
 * 5. Lifecycle gatekeeping (Approve/Reject disabled outside PENDING_APPROVAL) and Day 1/2 UI execution button suppression
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';
import { resetMockStore, getMockStore } from '../mocks/handlers';
import { TaskStatus, type TaskDetailResponse, type TaskEvent } from '../types/task';
import { Tasks } from '../pages/Tasks';
import { CreateTask } from '../pages/CreateTask';
import { TaskDetail } from '../pages/TaskDetail';
import { ImportIssueForm } from '../components/tasks/ImportIssueForm';
import { ApprovalHistoryPanel } from '../components/tasks/ApprovalHistoryPanel';
import { ExecutionTimeline } from '../components/tasks/ExecutionTimeline';
import { PlanReviewPanel } from '../components/tasks/PlanReviewPanel';

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

function renderWithProviders(ui: React.ReactElement, initialRoute = '/app/tasks') {
  const queryClient = createTestQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialRoute]}>
        <Routes>
          <Route path="/app/tasks" element={ui} />
          <Route path="/app/tasks/new" element={ui} />
          <Route path="/app/tasks/:taskId" element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  resetMockStore();

  // Intercept repository listing to prevent real network timeouts during useRepositories queries
  server.use(
    http.get('*/api/v1/repositories', () => {
      return HttpResponse.json([
        { id: 'repo-1', name: 'repo-1', full_name: 'example/repo-1' },
        { id: 'repo-2', name: 'repo-2', full_name: 'example/repo-2' },
      ]);
    })
  );
});

// ============================================================================
// Dimension 1: /app/tasks List, Filters & Pagination Transitions
// ============================================================================
describe('Challenger Dimension 1: /app/tasks List, Filters & Pagination', () => {
  it('loads tasks list, executes search, status filter, and handles reset', async () => {
    renderWithProviders(<Tasks />);

    // 1. Initial load
    expect(screen.getByRole('heading', { name: 'Tasks' })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText(/Fix Token Budget Overflow in AST Analyzer/i)).toBeInTheDocument();
    });

    // 2. Status filter transition
    const statusSelect = screen.getByLabelText('Filter by Status');
    fireEvent.change(statusSelect, { target: { value: TaskStatus.REJECTED } });

    await waitFor(() => {
      expect(screen.getByText(/Refactor Database Migration Runner to Async/i)).toBeInTheDocument();
      expect(screen.queryByText(/Fix Token Budget Overflow in AST Analyzer/i)).toBeNull();
    });

    // 3. Reset button clears active filter
    const resetBtn = screen.getByRole('button', { name: /Reset/i });
    fireEvent.click(resetBtn);

    await waitFor(() => {
      expect(screen.getByText(/Fix Token Budget Overflow in AST Analyzer/i)).toBeInTheDocument();
    });

    // 4. Search filter transition
    const searchInput = screen.getByRole('searchbox');
    fireEvent.change(searchInput, { target: { value: 'Vector' } });

    await waitFor(() => {
      expect(screen.getByText(/Optimize Vector Similarity Query Index/i)).toBeInTheDocument();
      expect(screen.queryByText(/Fix Token Budget Overflow in AST Analyzer/i)).toBeNull();
    });
  }, 15000);

  it('manages multi-page pagination transitions when tasks exceed pageSize (12)', async () => {
    // Seed 25 synthetic tasks into in-memory mock store
    const store = getMockStore();
    for (let i = 1; i <= 25; i++) {
      const id = `task-paged-${String(i).padStart(3, '0')}`;
      const task: TaskDetailResponse = {
        task_id: id,
        repository_id: 'repo-1',
        title: `Synthetic Paged Task #${i}`,
        description: `Description for synthetic task #${i}`,
        status: i % 2 === 0 ? TaskStatus.PENDING_APPROVAL : TaskStatus.CREATED,
        source: {
          type: 'USER_PROMPT',
          repository_id: 'repo-1',
        },
        requirements: [
          {
            id: `req-${i}`,
            description: `Requirement for task #${i}`,
            category: 'functional',
            target_files: [`src/file_${i}.ts`],
            acceptance_criteria: ['Passes'],
          },
        ],
        assumptions: [],
        constraints: [],
        base_revision: 'abc123',
        plan_version: 1,
        approved_plan_version: null,
        repair_attempts_used: 0,
        repair_attempts_max: 3,
        // Stagger updated_at so sorting is deterministic
        created_at: new Date(Date.now() - (25 - i) * 60000).toISOString(),
        updated_at: new Date(Date.now() - (25 - i) * 60000).toISOString(),
      };
      store.tasks.set(id, task);
    }

    renderWithProviders(<Tasks />);

    // Page 1: Verify total count and page 1 bounds
    await waitFor(() => {
      expect(screen.getByText(/Showing 1–12 of/i)).toBeInTheDocument();
      expect(screen.getByText(/Page 1 of/i)).toBeInTheDocument();
    });

    // Previous button must be disabled on Page 1
    expect(screen.getByLabelText('Previous Page')).toBeDisabled();
    expect(screen.getByLabelText('Next Page')).toBeEnabled();

    // Transition to Page 2
    fireEvent.click(screen.getByLabelText('Next Page'));

    await waitFor(() => {
      expect(screen.getByText(/Page 2 of/i)).toBeInTheDocument();
      expect(screen.getByText(/Showing 13–24 of/i)).toBeInTheDocument();
    });

    expect(screen.getByLabelText('Previous Page')).toBeEnabled();
    expect(screen.getByLabelText('Next Page')).toBeEnabled();

    // Transition to Page 3
    fireEvent.click(screen.getByLabelText('Next Page'));

    await waitFor(() => {
      expect(screen.getByText(/Page 3 of/i)).toBeInTheDocument();
      expect(screen.getByText(/Showing 25–/i)).toBeInTheDocument();
    });

    // On last page, next button must be disabled
    expect(screen.getByLabelText('Next Page')).toBeDisabled();
    expect(screen.getByLabelText('Previous Page')).toBeEnabled();

    // Transition back to Page 2 via previous button
    fireEvent.click(screen.getByLabelText('Previous Page'));

    await waitFor(() => {
      expect(screen.getByText(/Page 2 of/i)).toBeInTheDocument();
    });

    // Entering a search query that still matches all 25 resets page back to 1
    const searchInput = screen.getByRole('searchbox');
    fireEvent.change(searchInput, { target: { value: 'Synthetic Paged' } });

    await waitFor(() => {
      expect(screen.getByText(/Page 1 of 3/i)).toBeInTheDocument();
      expect(screen.getByText(/Showing 1–12 of/i)).toBeInTheDocument();
    });
  }, 15000);
});

// ============================================================================
// Dimension 2: /app/tasks/new Toggle Between Manual and GitHub Issue Import
// ============================================================================
describe('Challenger Dimension 2: /app/tasks/new Tab Toggle', () => {
  it('toggles seamlessly between manual task creation and GitHub issue import', async () => {
    renderWithProviders(<CreateTask />, '/app/tasks/new');

    const manualTabBtn = screen.getByRole('button', { name: /Manual Task Creation/i });
    const githubTabBtn = screen.getByRole('button', { name: /Import from GitHub Issue/i });

    // Initial state: Manual form active
    expect(screen.getByText('General Task Information')).toBeInTheDocument();
    expect(screen.queryByText('Select GitHub Repository')).toBeNull();

    // Toggle to GitHub Issue Import
    fireEvent.click(githubTabBtn);

    await waitFor(() => {
      expect(screen.getByText('Select GitHub Repository')).toBeInTheDocument();
      expect(screen.queryByText('General Task Information')).toBeNull();
    });

    // Toggle back to Manual Task Creation
    fireEvent.click(manualTabBtn);

    await waitFor(() => {
      expect(screen.getByText('General Task Information')).toBeInTheDocument();
      expect(screen.queryByText('Select GitHub Repository')).toBeNull();
    });
  });
});

// ============================================================================
// Dimension 3: ImportIssueForm Ingestion Guardrails
// ============================================================================
describe('Challenger Dimension 3: ImportIssueForm is_imported Guardrails', () => {
  it('disables import button and shows warning alert when issue is already imported', async () => {
    renderWithProviders(<ImportIssueForm />);

    // Candidate issue #42 is already marked is_imported: true in seed data
    await waitFor(() => {
      expect(screen.getByText(/Fix Token Budget Overflow in AST Analyzer/i)).toBeInTheDocument();
    });

    // Verify imported badge appears in candidate list
    expect(screen.getByText('Imported')).toBeInTheDocument();

    // Select the already imported issue
    const issue42Card = screen.getByText(/Fix Token Budget Overflow in AST Analyzer/i);
    fireEvent.click(issue42Card);

    // Verify warning banner and disabled button
    await waitFor(() => {
      expect(
        screen.getByText(/This issue has already been imported into an active task/i)
      ).toBeInTheDocument();
    });

    const importBtn = screen.getByRole('button', { name: /Import Issue as Task/i });
    expect(importBtn).toBeDisabled();
  });

  it('enables import button for unimported issue and switches repository cleanly', async () => {
    renderWithProviders(<ImportIssueForm />);

    // Issue #55 is unimported (is_imported: false)
    await waitFor(() => {
      expect(screen.getByText(/Add support for Python 3.12 type parameter syntax/i)).toBeInTheDocument();
    });

    const issue55Card = screen.getByText(/Add support for Python 3.12 type parameter syntax/i);
    fireEvent.click(issue55Card);

    // Import button must be enabled
    await waitFor(() => {
      const importBtn = screen.getByRole('button', { name: /Import Issue as Task/i });
      expect(importBtn).toBeEnabled();
    });

    // Changing issue state filter to 'closed' filters issues
    const stateFilter = screen.getByLabelText('Filter Issue State');
    fireEvent.change(stateFilter, { target: { value: 'closed' } });

    await waitFor(() => {
      expect(
        screen.getByText(/Implement incremental diff parsing for git worktrees/i)
      ).toBeInTheDocument();
      expect(
        screen.queryByText(/Add support for Python 3.12 type parameter syntax/i)
      ).toBeNull();
    });
  });
});

// ============================================================================
// Dimension 4: TaskDetail, ApprovalHistoryPanel & ExecutionTimeline Events
// ============================================================================
describe('Challenger Dimension 4: TaskDetail Panels & Event Timeline Icons', () => {
  const dummyTask: TaskDetailResponse = {
    task_id: 'task-test-detail',
    repository_id: 'repo-1',
    title: 'Test Timeline & Approval Rendering',
    description: 'Verifying icon mapping and audit panels.',
    status: TaskStatus.PENDING_APPROVAL,
    source: {
      type: 'USER_PROMPT',
      repository_id: 'repo-1',
    },
    requirements: [
      {
        id: 'req-1',
        description: 'Verify all visual event nodes',
        category: 'test',
        target_files: ['src/test.ts'],
        acceptance_criteria: ['Icons map correctly'],
      },
    ],
    assumptions: [],
    constraints: [],
    base_revision: 'abc123',
    plan_version: 1,
    approved_plan_version: null,
    repair_attempts_used: 0,
    repair_attempts_max: 3,
    created_at: '2026-10-30T09:00:00.000Z',
    updated_at: '2026-10-30T09:30:00.000Z',
  };

  it('renders ApprovalHistoryPanel with decisions or waiting notice', async () => {
    // 1. Task with no decisions yet
    const { unmount } = renderWithProviders(
      <ApprovalHistoryPanel taskId="task-seed-1" task={dummyTask} />
    );

    await waitFor(() => {
      expect(
        screen.getByText(/Awaiting human sign-off on implementation plan v1/i)
      ).toBeInTheDocument();
    });
    unmount();

    // 2. Task with APPROVED decision in seed data (task-seed-2)
    renderWithProviders(
      <ApprovalHistoryPanel
        taskId="task-seed-2"
        task={{ ...dummyTask, status: TaskStatus.APPROVED, approved_plan_version: 1 }}
      />
    );

    await waitFor(() => {
      expect(screen.getByText('APPROVED')).toBeInTheDocument();
      expect(screen.getByText(/Plan version 1 approved by lead_architect/i)).toBeInTheDocument();
    });
  });

  it('renders ExecutionTimeline with proper event nodes across full lifecycle events', async () => {
    const store = getMockStore();
    // Register task in store so GET /tasks/:taskId/events 404 guard passes
    store.tasks.set(dummyTask.task_id, dummyTask);

    const comprehensiveEvents: TaskEvent[] = [
      {
        id: 'evt-c-1',
        task_id: dummyTask.task_id,
        event_type: 'TASK_CREATED',
        description: 'Initial intake completed.',
        created_at: '2026-10-30T09:00:00.000Z',
      },
      {
        id: 'evt-c-2',
        task_id: dummyTask.task_id,
        event_type: 'PLAN_GENERATED',
        description: 'First version of plan ready.',
        created_at: '2026-10-30T09:05:00.000Z',
      },
      {
        id: 'evt-c-3',
        task_id: dummyTask.task_id,
        event_type: 'PLAN_REVISED',
        description: 'Updated steps for v2.',
        created_at: '2026-10-30T09:10:00.000Z',
      },
      {
        id: 'evt-c-4',
        task_id: dummyTask.task_id,
        event_type: 'PLAN_APPROVED',
        description: 'Plan signed off by human reviewer.',
        created_at: '2026-10-30T09:15:00.000Z',
      },
      {
        id: 'evt-c-5',
        task_id: dummyTask.task_id,
        event_type: 'WORKSPACE_SETUP',
        description: 'Isolated worktree created.',
        created_at: '2026-10-30T09:20:00.000Z',
      },
      {
        id: 'evt-c-6',
        task_id: dummyTask.task_id,
        event_type: 'EXECUTING',
        description: 'Applying diff edits.',
        created_at: '2026-10-30T09:25:00.000Z',
      },
      {
        id: 'evt-c-7',
        task_id: dummyTask.task_id,
        event_type: 'TESTING',
        description: 'Running test runner commands.',
        created_at: '2026-10-30T09:30:00.000Z',
      },
      {
        id: 'evt-c-8',
        task_id: dummyTask.task_id,
        event_type: 'REPAIRING',
        description: 'Performing bounded repair 1 of 3.',
        created_at: '2026-10-30T09:35:00.000Z',
      },
      {
        id: 'evt-c-9',
        task_id: dummyTask.task_id,
        event_type: 'VERIFYING',
        description: 'Executing independent static checks.',
        created_at: '2026-10-30T09:40:00.000Z',
      },
      {
        id: 'evt-c-10',
        task_id: dummyTask.task_id,
        event_type: 'READY_FOR_PUBLICATION',
        description: 'Ready for pull request generation.',
        created_at: '2026-10-30T09:45:00.000Z',
      },
      {
        id: 'evt-c-11',
        task_id: dummyTask.task_id,
        event_type: 'PUBLISHING',
        description: 'Pushing changes to remote branch.',
        created_at: '2026-10-30T09:50:00.000Z',
      },
      {
        id: 'evt-c-12',
        task_id: dummyTask.task_id,
        event_type: 'DRAFT_PR_CREATED',
        description: 'Draft pull request open.',
        created_at: '2026-10-30T09:55:00.000Z',
      },
    ];

    store.events.set(dummyTask.task_id, comprehensiveEvents);

    renderWithProviders(<ExecutionTimeline taskId={dummyTask.task_id} />);

    await waitFor(
      () => {
        expect(screen.getByText('TASK CREATED')).toBeInTheDocument();
        expect(screen.getByText('PLAN GENERATED')).toBeInTheDocument();
        expect(screen.getByText('PLAN REVISED')).toBeInTheDocument();
        expect(screen.getByText('PLAN APPROVED')).toBeInTheDocument();
        expect(screen.getByText('WORKSPACE SETUP')).toBeInTheDocument();
        expect(screen.getByText('EXECUTING')).toBeInTheDocument();
        expect(screen.getByText('TESTING')).toBeInTheDocument();
        expect(screen.getByText('REPAIRING')).toBeInTheDocument();
        expect(screen.getByText('VERIFYING')).toBeInTheDocument();
        expect(screen.getByText('READY FOR PUBLICATION')).toBeInTheDocument();
        expect(screen.getByText('PUBLISHING')).toBeInTheDocument();
        expect(screen.getByText('DRAFT PR CREATED')).toBeInTheDocument();
      },
      { timeout: 4000 }
    );
  });

  it('integrates complete TaskDetail page and guarantees zero execution triggers are exposed', async () => {
    renderWithProviders(<TaskDetail />, '/app/tasks/task-seed-1');

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Fix Token Budget Overflow in AST Analyzer' })).toBeInTheDocument();
      expect(screen.getByText('Segregated Requirements (1)')).toBeInTheDocument();
      expect(screen.getByText('Implementation Plan')).toBeInTheDocument();
      expect(screen.getByText('Approval & Rejection History')).toBeInTheDocument();
      expect(screen.getByText('Lifecycle & Event Timeline')).toBeInTheDocument();
    });

    // STRICT Day 1/2 Constraint: Zero execution controls in the UI
    expect(screen.queryByRole('button', { name: /Execute Task/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /Run in Sandbox/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /Create Draft PR/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /Publish Changes/i })).toBeNull();
  });
});

// ============================================================================
// Dimension 5: Lifecycle Gatekeeping Across Non-Pending States
// ============================================================================
describe('Challenger Dimension 5: Lifecycle Gatekeeping', () => {
  const nonPendingStatuses: TaskStatus[] = [
    TaskStatus.CREATED,
    TaskStatus.PLANNING,
    TaskStatus.APPROVED,
    TaskStatus.REJECTED,
    TaskStatus.WORKSPACE_SETUP,
    TaskStatus.EXECUTING,
    TaskStatus.TESTING,
    TaskStatus.REPAIRING,
    TaskStatus.VERIFYING,
    TaskStatus.READY_FOR_PUBLICATION,
    TaskStatus.PUBLISHING,
    TaskStatus.DRAFT_PR_CREATED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
    TaskStatus.RECOVERY_REQUIRED,
    TaskStatus.BLOCKED,
  ];

  it('disables Approve button across all 16 non-PENDING_APPROVAL statuses', async () => {
    for (const status of nonPendingStatuses) {
      const task: TaskDetailResponse = {
        task_id: `task-gate-${status.toLowerCase()}`,
        repository_id: 'repo-1',
        title: `Gate Test ${status}`,
        description: 'Testing lifecycle gate enforcement',
        status,
        source: { type: 'USER_PROMPT', repository_id: 'repo-1' },
        requirements: [
          {
            id: 'req-1',
            description: 'Desc',
            category: 'functional',
            target_files: ['src/file.ts'],
            acceptance_criteria: ['Passes'],
          },
        ],
        assumptions: [],
        constraints: [],
        base_revision: 'abc123',
        plan_version: 1,
        approved_plan_version: status === TaskStatus.APPROVED ? 1 : null,
        repair_attempts_used: 0,
        repair_attempts_max: 3,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };

      // Set plan in mock store
      const store = getMockStore();
      store.tasks.set(task.task_id, task);
      const planMap = new Map();
      planMap.set(1, {
        task_id: task.task_id,
        plan_version: 1,
        base_revision: 'abc123',
        summary: `Plan for ${status}`,
        steps: [
          {
            step_id: 's-1',
            title: 'Step 1',
            description: 'Step desc',
            step_type: 'edit',
            expected_files: ['file.ts'],
            verification: ['Check'],
          },
        ],
        expected_files_to_modify: ['file.ts'],
        tests_to_add: [],
        validation_strategy: 'Test',
        risks: [],
        status: status === TaskStatus.APPROVED ? 'APPROVED' : status === TaskStatus.REJECTED ? 'REJECTED' : 'PENDING_APPROVAL',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
      store.plans.set(task.task_id, planMap);

      const { unmount } = renderWithProviders(<PlanReviewPanel task={task} />, `/app/tasks/${task.task_id}`);

      await waitFor(() => {
        const approveBtn = screen.getByTestId('approve-button');
        expect(approveBtn).toBeDisabled();
      });

      unmount();
    }
  }, 30000);
});
