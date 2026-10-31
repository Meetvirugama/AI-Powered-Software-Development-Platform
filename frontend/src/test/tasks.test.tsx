import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';
import { resetMockStore } from '../mocks/handlers';
import { TaskStatus, type TaskDetailResponse, type TaskEvent } from '../types/task';
import { TaskStatusBadge } from '../components/tasks/TaskStatusBadge';
import { TaskCard } from '../components/tasks/TaskCard';
import { Tasks } from '../pages/Tasks';
import { CreateTask } from '../pages/CreateTask';
import { CreateTaskForm } from '../components/tasks/CreateTaskForm';
import { ImportIssueForm } from '../components/tasks/ImportIssueForm';
import { PlanReviewPanel } from '../components/tasks/PlanReviewPanel';
import { ApprovalHistoryPanel } from '../components/tasks/ApprovalHistoryPanel';
import { getDecisionPlanVersion } from '../lib/taskUtils';
import { ExecutionTimeline } from '../components/tasks/ExecutionTimeline';
import { TaskDetail } from '../pages/TaskDetail';

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

const mockSampleTask: TaskDetailResponse = {
  task_id: 'task-test-sample',
  repository_id: 'repo-1',
  title: 'Implement Exponential Backoff',
  description: 'Add jittered exponential backoff logic to API client.',
  status: TaskStatus.PENDING_APPROVAL,
  source: {
    type: 'GITHUB_ISSUE',
    issue_number: 99,
    repository_id: 'repo-1',
  },
  requirements: [
    {
      id: 'req-1',
      description: 'Backoff duration doubles with each attempt',
      category: 'functional',
      target_files: ['src/services/api.ts'],
      acceptance_criteria: ['Max retry limit 3'],
    },
  ],
  assumptions: [
    {
      id: 'asm-1',
      description: 'Axios interceptor available',
      unresolved: false,
      risk_level: 'low',
    },
  ],
  constraints: [
    {
      id: 'cst-1',
      description: 'Do not modify auth headers',
      constraint_type: 'protected_file',
      forbidden_files: ['src/services/auth.ts'],
      forbidden_packages: [],
    },
  ],
  base_revision: 'c1d2e3f4a5b6',
  plan_version: 1,
  approved_plan_version: null,
  repair_attempts_used: 0,
  repair_attempts_max: 3,
  created_at: '2026-10-30T08:00:00.000Z',
  updated_at: '2026-10-30T08:30:00.000Z',
};

beforeEach(() => {
  resetMockStore();
});

// ============================================================================
// 1. TaskStatusBadge Tests
// ============================================================================
describe('TaskStatusBadge', () => {
  const ALL_STATUSES = [
    TaskStatus.CREATED,
    TaskStatus.PLANNING,
    TaskStatus.PENDING_APPROVAL,
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

  it('renders all 17 canonical statuses with correct data-status and badge class', () => {
    for (const status of ALL_STATUSES) {
      const { unmount } = render(<TaskStatusBadge status={status} />);
      const badge = screen.getByTestId('status-badge');
      expect(badge).toHaveAttribute('data-status', status);
      expect(badge.className).toContain(`badge-${status.toLowerCase()}`);
      expect(badge.textContent).toBe(status.replace(/_/g, ' '));
      unmount();
    }
  });

  it('renders fallback badge safely for unknown custom status string', () => {
    render(<TaskStatusBadge status="CUSTOM_NEW_STATUS" />);
    const badge = screen.getByTestId('status-badge');
    expect(badge).toHaveAttribute('data-status', 'CUSTOM_NEW_STATUS');
    expect(badge.className).toContain('badge-neutral-fallback');
    expect(badge.textContent).toBe('CUSTOM NEW STATUS');
  });

  it('handles null or undefined status without throwing', () => {
    render(<TaskStatusBadge status={null} />);
    const badge = screen.getByTestId('status-badge');
    expect(badge).toHaveAttribute('data-status', 'UNKNOWN');
    expect(badge.className).toContain('badge-neutral-fallback');
  });
});

// ============================================================================
// 2. TaskCard Tests
// ============================================================================
describe('TaskCard', () => {
  it('renders task card with title, repository, status, requirements, and plan version', () => {
    renderWithProviders(<TaskCard task={mockSampleTask} />);

    expect(screen.getByText('Implement Exponential Backoff')).toBeInTheDocument();
    expect(screen.getByText('repo-1')).toBeInTheDocument();
    expect(screen.getByTestId('status-badge')).toHaveTextContent('PENDING APPROVAL');
    expect(screen.getByText(/1 req/)).toBeInTheDocument();
    expect(screen.getByText('v1')).toBeInTheDocument();
    expect(screen.getByText('Issue #99')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /View Plan/i })).toHaveAttribute(
      'href',
      '/app/tasks/task-test-sample'
    );
  });
});

// ============================================================================
// 3. Tasks List Page Tests
// ============================================================================
describe('Tasks Page', () => {
  it('renders task list header and fetches seeded tasks', async () => {
    renderWithProviders(<Tasks />);

    expect(screen.getByRole('heading', { name: 'Tasks' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /New Task/i })).toBeInTheDocument();

    // Verify seeded task renders
    await waitFor(() => {
      expect(
        screen.getByText(/Fix Token Budget Overflow in AST Analyzer/i)
      ).toBeInTheDocument();
    });
  });

  it('filters task list by search query', async () => {
    renderWithProviders(<Tasks />);

    await waitFor(() => {
      expect(
        screen.getByText(/Fix Token Budget Overflow in AST Analyzer/i)
      ).toBeInTheDocument();
    });

    const searchInput = screen.getByRole('searchbox');
    fireEvent.change(searchInput, { target: { value: 'Decorator' } });

    await waitFor(() => {
      expect(
        screen.getByText(/Add TypeScript 5.4 Decorator AST Metadata/i)
      ).toBeInTheDocument();
      expect(
        screen.queryByText(/Fix Token Budget Overflow in AST Analyzer/i)
      ).toBeNull();
    });
  });

  it('displays empty state when search matches no tasks', async () => {
    renderWithProviders(<Tasks />);

    await waitFor(() => {
      expect(
        screen.getByText(/Fix Token Budget Overflow in AST Analyzer/i)
      ).toBeInTheDocument();
    });

    const searchInput = screen.getByRole('searchbox');
    fireEvent.change(searchInput, { target: { value: 'non_existent_query_xyz_999' } });

    await waitFor(() => {
      expect(screen.getByText(/No tasks found/i)).toBeInTheDocument();
    });
  });
});

// ============================================================================
// 4. CreateTask & Intake Forms Tests
// ============================================================================
describe('CreateTask & CreateTaskForm', () => {
  it('switches between Manual Task Creation and GitHub Issue Import tabs', () => {
    renderWithProviders(<CreateTask />, '/app/tasks/new');

    expect(screen.getByText('Manual Task Creation')).toBeInTheDocument();
    expect(screen.getByText('Import from GitHub Issue')).toBeInTheDocument();

    // Default tab is Manual
    expect(screen.getByText('General Task Information')).toBeInTheDocument();

    // Switch to GitHub Issue tab
    fireEvent.click(screen.getByText('Import from GitHub Issue'));
    expect(screen.getByText('Select GitHub Repository')).toBeInTheDocument();

    // Switch back to Manual tab
    fireEvent.click(screen.getByText('Manual Task Creation'));
    expect(screen.getByText('General Task Information')).toBeInTheDocument();
  });

  it('validates blank title and requires at least one requirement', async () => {
    renderWithProviders(<CreateTaskForm />, '/app/tasks/new');

    const submitBtn = screen.getByRole('button', { name: /Create Task/i });
    fireEvent.click(submitBtn);

    // Should display validation errors
    await waitFor(() => {
      expect(
        screen.getByText(/Title must contain non-whitespace characters/i)
      ).toBeInTheDocument();
    });
  });

  it('adds and removes dynamic requirements with monotonic unique IDs in CreateTaskForm', () => {
    renderWithProviders(<CreateTaskForm />, '/app/tasks/new');

    expect(screen.getByText('req-1')).toBeInTheDocument();

    const addReqBtn = screen.getByRole('button', { name: /Add Requirement/i });
    fireEvent.click(addReqBtn);
    expect(screen.getByText('req-2')).toBeInTheDocument();

    // Adding another requirement produces req-3 monotonically
    fireEvent.click(addReqBtn);
    expect(screen.getByText('req-3')).toBeInTheDocument();
  });

  it('validates HTTPS issue URL when intake source is GITHUB_ISSUE', async () => {
    renderWithProviders(<CreateTaskForm />, '/app/tasks/new');

    // Select GitHub Issue source type
    const sourceSelect = screen.getByLabelText(/Intake Source Type/i);
    fireEvent.change(sourceSelect, { target: { value: 'GITHUB_ISSUE' } });

    // Enter non-HTTPS URL
    const issueUrlInput = screen.getByPlaceholderText('https://github.com/...');
    fireEvent.change(issueUrlInput, { target: { value: 'http://insecure-site.com/issue/1' } });

    const submitBtn = screen.getByRole('button', { name: /Create Task/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText(/Issue URL must be a valid HTTPS URL/i)).toBeInTheDocument();
    });
  });

  it('adds and removes dynamic assumptions in CreateTaskForm', () => {
    renderWithProviders(<CreateTaskForm />, '/app/tasks/new');

    const addAsmBtn = screen.getByRole('button', { name: /Add Assumption/i });
    fireEvent.click(addAsmBtn);

    expect(screen.getByPlaceholderText(/Existing symbol table format/i)).toBeInTheDocument();
  });

  it('adds and removes dynamic constraints in CreateTaskForm', () => {
    renderWithProviders(<CreateTaskForm />, '/app/tasks/new');

    const addCstBtn = screen.getByRole('button', { name: /Add Constraint/i });
    fireEvent.click(addCstBtn);

    expect(screen.getByText('cst-1')).toBeInTheDocument();
  });

  it('detects disjointness conflict when target file is also in forbidden files', async () => {
    renderWithProviders(<CreateTaskForm />, '/app/tasks/new');

    // Add constraint
    fireEvent.click(screen.getByRole('button', { name: /Add Constraint/i }));

    // Set title
    const titleInput = screen.getByPlaceholderText(/Fix Token Budget Overflow/i);
    fireEvent.change(titleInput, { target: { value: 'Valid Task Title' } });

    // Set description
    const descInput = screen.getByPlaceholderText(/Provide a detailed description/i);
    fireEvent.change(descInput, { target: { value: 'Valid description text' } });

    // Set target file in requirement
    const targetFileInput = screen.getByPlaceholderText(/ast_walker\.py/i);
    fireEvent.change(targetFileInput, { target: { value: 'src/forbidden/file.py' } });

    // Set req description
    const reqDesc = screen.getByPlaceholderText(/Cap AST symbol/i);
    fireEvent.change(reqDesc, { target: { value: 'Valid req' } });

    // Set forbidden file in constraint to same file
    const forbiddenFileInput = screen.getByPlaceholderText(/grammar\.py/i);
    fireEvent.change(forbiddenFileInput, { target: { value: 'src/forbidden/file.py' } });

    // Submit
    const submitBtn = screen.getByRole('button', { name: /Create Task/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText(/Conflict: Target file/i)).toBeInTheDocument();
    });
  });
});

// ============================================================================
// 5. ImportIssueForm Tests
// ============================================================================
describe('ImportIssueForm', () => {
  it('loads candidate GitHub issues and displays preview when issue is clicked', async () => {
    renderWithProviders(<ImportIssueForm />);

    await waitFor(() => {
      expect(screen.getByText(/Add support for Python 3.12 type parameter syntax/i)).toBeInTheDocument();
    });

    // Click on unimported issue #55
    const issue55 = screen.getByText(/Add support for Python 3.12 type parameter syntax/i);
    fireEvent.click(issue55);

    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /Import Issue as Task/i })
      ).toBeEnabled();
    });
  });

  it('disables import button when selecting an already-imported issue', async () => {
    renderWithProviders(<ImportIssueForm />);

    await waitFor(() => {
      expect(screen.getByText(/Fix Token Budget Overflow in AST Analyzer/i)).toBeInTheDocument();
    });

    // Click on issue #42 which is already imported in seed data
    const issue42 = screen.getByText(/Fix Token Budget Overflow in AST Analyzer/i);
    fireEvent.click(issue42);

    await waitFor(() => {
      expect(
        screen.getByText(/This issue has already been imported into an active task/i)
      ).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: /Import Issue as Task/i })
      ).toBeDisabled();
    });
  });
});

// ============================================================================
// 6. PlanReviewPanel & Approval Gate Tests
// ============================================================================
describe('PlanReviewPanel', () => {
  it('displays structured plan summary, version, steps, and validation strategy', async () => {
    const taskPendingApproval: TaskDetailResponse = {
      ...mockSampleTask,
      task_id: 'task-seed-1',
      status: TaskStatus.PENDING_APPROVAL,
      plan_version: 1,
    };

    renderWithProviders(
      <PlanReviewPanel task={taskPendingApproval} />,
      '/app/tasks/task-seed-1'
    );

    await waitFor(() => {
      expect(screen.getByText(/Implement bounded recursion with depth threshold/i)).toBeInTheDocument();
      expect(screen.getByText(/Add depth counter to AstWalker/i)).toBeInTheDocument();
      expect(screen.getByText(/Integrate TokenBudgetManager check/i)).toBeInTheDocument();
    });
  });

  it('strictly disables approve and reject buttons when task status is NOT PENDING_APPROVAL', async () => {
    const taskApproved: TaskDetailResponse = {
      ...mockSampleTask,
      task_id: 'task-seed-2',
      status: TaskStatus.APPROVED,
      plan_version: 1,
    };

    renderWithProviders(
      <PlanReviewPanel task={taskApproved} />,
      '/app/tasks/task-seed-2'
    );

    await waitFor(() => {
      expect(screen.getByTestId('approve-button')).toBeDisabled();
    });

    // Verify rejection controls are also disabled/inactive
    expect(screen.queryByTestId('reject-button')).toBeNull();
  });

  it('enables approve button and submits exact plan_version when status is PENDING_APPROVAL', async () => {
    const taskPending: TaskDetailResponse = {
      ...mockSampleTask,
      task_id: 'task-seed-1',
      status: TaskStatus.PENDING_APPROVAL,
      plan_version: 1,
    };

    renderWithProviders(
      <PlanReviewPanel task={taskPending} />,
      '/app/tasks/task-seed-1'
    );

    await waitFor(() => {
      expect(screen.getByTestId('approve-button')).toBeEnabled();
    });

    // Enter approval notes
    const notesInput = screen.getByPlaceholderText(/Approved\. Proceed/i);
    fireEvent.change(notesInput, { target: { value: 'Lead architect approval notes' } });

    // Click approve
    fireEvent.click(screen.getByTestId('approve-button'));

    // Wait for approval completion and disabled state
    await waitFor(() => {
      expect(screen.getByTestId('approve-button')).toBeDisabled();
    });
  });

  it('displays 409 version mismatch warning alert with refresh button when version conflicts', async () => {
    // Override MSW approve handler to simulate 409 PLAN_VERSION_MISMATCH
    server.use(
      http.post('*/api/v1/tasks/:taskId/approve', () => {
        return HttpResponse.json(
          {
            error: {
              code: 'PLAN_VERSION_MISMATCH',
              message: 'The plan has been revised. Please refresh and review the updated plan version.',
              retryable: false,
            },
          },
          { status: 409 }
        );
      })
    );

    const taskPending: TaskDetailResponse = {
      ...mockSampleTask,
      task_id: 'task-seed-1',
      status: TaskStatus.PENDING_APPROVAL,
      plan_version: 1,
    };

    renderWithProviders(
      <PlanReviewPanel task={taskPending} />,
      '/app/tasks/task-seed-1'
    );

    await waitFor(() => {
      expect(screen.getByTestId('approve-button')).toBeEnabled();
    });

    fireEvent.click(screen.getByTestId('approve-button'));

    await waitFor(() => {
      expect(screen.getByText(/Plan Version Mismatch/i)).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: /Refresh Plan to Current Version/i })
      ).toBeInTheDocument();
    });
  });

  it('strictly adheres to Day 1/2 UI constraints by NOT rendering any execution triggers', async () => {
    renderWithProviders(
      <PlanReviewPanel task={mockSampleTask} />,
      '/app/tasks/task-test-sample'
    );

    await waitFor(() => {
      expect(screen.getByText('Implementation Plan')).toBeInTheDocument();
    });

    expect(screen.queryByText(/execute task/i)).toBeNull();
    expect(screen.queryByText(/run in sandbox/i)).toBeNull();
    expect(screen.queryByText(/create draft pr/i)).toBeNull();
  });
});

// ============================================================================
// 7. ApprovalHistoryPanel & ExecutionTimeline Tests
// ============================================================================
describe('ApprovalHistoryPanel & ExecutionTimeline', () => {
  it('correctly resolves decision plan version using explicit precedence', () => {
    // 1. Explicit event.details.plan_version takes precedence
    const evtWithDetail: TaskEvent = {
      id: 'evt-1',
      task_id: 'task-1',
      event_type: 'PLAN_APPROVED',
      description: 'Plan version 1 approved',
      created_at: new Date().toISOString(),
      details: { plan_version: 1 },
    };
    const taskMultiRev: TaskDetailResponse = {
      ...mockSampleTask,
      plan_version: 3,
      approved_plan_version: 2,
    };
    expect(getDecisionPlanVersion(evtWithDetail, taskMultiRev)).toBe(1);

    // 2. Fallback to task.approved_plan_version when detail is absent
    const evtNoDetail: TaskEvent = {
      id: 'evt-2',
      task_id: 'task-1',
      event_type: 'PLAN_APPROVED',
      description: 'Plan approved',
      created_at: new Date().toISOString(),
    };
    expect(getDecisionPlanVersion(evtNoDetail, taskMultiRev)).toBe(2);

    // 3. Fallback to task.plan_version when approved_plan_version is null
    const taskNoApproved: TaskDetailResponse = {
      ...mockSampleTask,
      plan_version: 3,
      approved_plan_version: null,
    };
    expect(getDecisionPlanVersion(evtNoDetail, taskNoApproved)).toBe(3);
  });

  it('handles query error state and renders retry button in ApprovalHistoryPanel', async () => {
    server.use(
      http.get('*/api/v1/tasks/:taskId/events', () => {
        return HttpResponse.json(
          { error: { code: 'INTERNAL_ERROR', message: 'Database connection failed' } },
          { status: 500 }
        );
      })
    );

    renderWithProviders(
      <ApprovalHistoryPanel taskId="task-err" task={mockSampleTask} />,
      '/app/tasks/task-err'
    );

    await waitFor(() => {
      expect(screen.getByText(/Database connection failed/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Retry/i })).toBeInTheDocument();
    });
  });

  it('handles query error state and renders retry button in ExecutionTimeline', async () => {
    server.use(
      http.get('*/api/v1/tasks/:taskId/events', () => {
        return HttpResponse.json(
          { error: { code: 'INTERNAL_ERROR', message: 'Database connection failed' } },
          { status: 500 }
        );
      })
    );

    renderWithProviders(
      <ExecutionTimeline taskId="task-err" />,
      '/app/tasks/task-err'
    );

    await waitFor(() => {
      expect(screen.getByText(/Database connection failed/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Retry/i })).toBeInTheDocument();
    });
  });

  it('renders approval decisions history', async () => {
    // task-seed-2 has a PLAN_APPROVED event in seed
    const taskApproved: TaskDetailResponse = {
      ...mockSampleTask,
      task_id: 'task-seed-2',
      status: TaskStatus.APPROVED,
      approved_plan_version: 1,
    };

    renderWithProviders(
      <ApprovalHistoryPanel taskId="task-seed-2" task={taskApproved} />,
      '/app/tasks/task-seed-2'
    );

    await waitFor(() => {
      expect(screen.getByText('APPROVED')).toBeInTheDocument();
      expect(screen.getByText(/Plan version 1 approved by lead_architect/i)).toBeInTheDocument();
    });
  });

  it('renders chronological stream of lifecycle events in ExecutionTimeline', async () => {
    renderWithProviders(
      <ExecutionTimeline taskId="task-seed-1" />,
      '/app/tasks/task-seed-1'
    );

    await waitFor(() => {
      expect(screen.getByText(/TASK CREATED/i)).toBeInTheDocument();
      expect(screen.getByText(/PLAN GENERATED/i)).toBeInTheDocument();
    });
  });
});

// ============================================================================
// 8. TaskDetail Integration Tests
// ============================================================================
describe('TaskDetail Page', () => {
  it('integrates header, intake metadata, plan review, history, and timeline', async () => {
    renderWithProviders(<TaskDetail />, '/app/tasks/task-seed-1');

    await waitFor(() => {
      expect(
        screen.getByRole('heading', { name: 'Fix Token Budget Overflow in AST Analyzer' })
      ).toBeInTheDocument();
      expect(screen.getByTestId('status-badge')).toHaveTextContent('PENDING APPROVAL');
      expect(screen.getByText('Implementation Plan')).toBeInTheDocument();
      expect(screen.getByText('Approval & Rejection History')).toBeInTheDocument();
      expect(screen.getByText('Lifecycle & Event Timeline')).toBeInTheDocument();
    });

    // Confirm no execution triggers on the page
    expect(screen.queryByText(/execute task/i)).toBeNull();
    expect(screen.queryByText(/run in sandbox/i)).toBeNull();
  });
});
