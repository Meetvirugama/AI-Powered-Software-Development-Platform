import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';
import { resetMockStore } from '../mocks/handlers';
import { TaskStatus, type TaskDetailResponse, type TaskPlan } from '../types/task';
import { TaskStatusBadge } from '../components/tasks/TaskStatusBadge';
import { CreateTaskForm } from '../components/tasks/CreateTaskForm';
import { PlanReviewPanel } from '../components/tasks/PlanReviewPanel';
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
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[initialRoute]}>
          <Routes>
            <Route path="/app/tasks" element={ui} />
            <Route path="/app/tasks/new" element={ui} />
            <Route path="/app/tasks/:taskId" element={ui} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    ),
  };
}

const ALL_17_CANONICAL_STATUSES: TaskStatus[] = [
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

const mockBaseTask: TaskDetailResponse = {
  task_id: 'task-seed-1',
  repository_id: 'repo-1',
  title: 'Adversarial Challenge Verification Task',
  description: 'Stress-testing lifecycle gates and form validation.',
  status: TaskStatus.PENDING_APPROVAL,
  source: {
    type: 'USER_PROMPT',
    repository_id: 'repo-1',
  },
  requirements: [
    {
      id: 'req-1',
      description: 'Requirement 1 for testing',
      category: 'functional',
      target_files: ['src/services/api.ts'],
      acceptance_criteria: ['Must not fail'],
    },
  ],
  assumptions: [],
  constraints: [],
  base_revision: 'abcdef123456',
  plan_version: 1,
  approved_plan_version: null,
  repair_attempts_used: 0,
  repair_attempts_max: 3,
  created_at: '2026-10-30T09:00:00.000Z',
  updated_at: '2026-10-30T09:00:00.000Z',
};

const mockPlanPayload: TaskPlan = {
  task_id: 'task-seed-1',
  plan_version: 1,
  status: 'PENDING_APPROVAL',
  summary: 'Adversarial test structured plan summary',
  problem_statement: 'Validate empirical gates across all canonical statuses',
  base_revision: 'abcdef123456',
  assumptions: [],
  unresolved_questions: [],
  relevant_files: ['src/analyzer/ast.ts'],
  expected_files_to_modify: ['src/analyzer/ast.ts'],
  tests_to_add: ['tests/test_ast.py'],
  steps: [
    {
      step_id: 'step-1',
      title: 'Step 1: Core AST Limit',
      description: 'Implement AST limit check',
      step_type: 'edit',
      expected_files: ['src/analyzer/ast.ts'],
      verification: ['Run ast unit test'],
      risk_level: 'low',
    },
  ],
  validation_strategy: 'Run vitest and static analysis',
  risks: [
    {
      risk_id: 'r-1',
      description: 'Low risk of regression',
      severity: 'low',
      mitigation: 'Full regression test suite',
    },
  ],
  created_at: '2026-10-30T09:00:00.000Z',
  updated_at: '2026-10-30T09:00:00.000Z',
};

beforeEach(() => {
  resetMockStore();
});

// ============================================================================
// 1. TaskStatusBadge Stress Test
// ============================================================================
describe('Empirical Challenge: TaskStatusBadge', () => {
  it('renders all 17 canonical statuses without throwing errors and applies specialized classes', () => {
    for (const status of ALL_17_CANONICAL_STATUSES) {
      const { unmount } = render(<TaskStatusBadge status={status} />);
      const badge = screen.getByTestId('status-badge');
      expect(badge).toBeInTheDocument();
      expect(badge.getAttribute('data-status')).toBe(status);
      expect(badge.className).toContain(`badge-${status.toLowerCase()}`);
      unmount();
    }
  });

  it('renders arbitrary unknown strings, null, undefined, and malformed inputs gracefully with fallback', () => {
    const unknownCases = [
      { input: 'CUSTOM_UNKNOWN_STATE', expectedStatus: 'CUSTOM_UNKNOWN_STATE' },
      { input: null, expectedStatus: 'UNKNOWN' },
      { input: undefined, expectedStatus: 'UNKNOWN' },
      { input: '', expectedStatus: '' },
      { input: '   ', expectedStatus: '   ' },
      { input: 'SPECIAL_!@#$%^&*()_+', expectedStatus: 'SPECIAL_!@#$%^&*()_+' },
      { input: 'lowercase_status', expectedStatus: 'lowercase_status' },
      { input: '99999', expectedStatus: '99999' },
    ];

    for (const { input, expectedStatus } of unknownCases) {
      const { unmount } = render(<TaskStatusBadge status={input as unknown as TaskStatus} />);
      const badge = screen.getByTestId('status-badge');
      expect(badge).toBeInTheDocument();
      expect(badge.getAttribute('data-status')).toBe(expectedStatus);
      expect(badge.className).toContain('badge-neutral-fallback');
      unmount();
    }
  });
});

// ============================================================================
// 2. CreateTaskForm Validation & Disjointness Stress Test
// ============================================================================
describe('Empirical Challenge: CreateTaskForm Validation & Disjointness', () => {
  it('prevents submission when title is completely blank', async () => {
    renderWithProviders(<CreateTaskForm />, '/app/tasks/new');

    const submitBtn = screen.getByRole('button', { name: /create task/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText(/title must contain non-whitespace characters/i)).toBeInTheDocument();
    });
  });

  it('prevents submission when title contains only whitespace', async () => {
    renderWithProviders(<CreateTaskForm />, '/app/tasks/new');

    const titleInput = screen.getByPlaceholderText(/e\.g\. Fix Token Budget Overflow in AST Analyzer/i);
    fireEvent.change(titleInput, { target: { value: '     ' } });

    const submitBtn = screen.getByRole('button', { name: /create task/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText(/title must contain non-whitespace characters/i)).toBeInTheDocument();
    });
  });

  it('prevents submission when title is shorter than 3 characters (1 or 2 characters)', async () => {
    renderWithProviders(<CreateTaskForm />, '/app/tasks/new');

    const titleInput = screen.getByPlaceholderText(/e\.g\. Fix Token Budget Overflow in AST Analyzer/i);
    fireEvent.change(titleInput, { target: { value: 'ab' } });

    const submitBtn = screen.getByRole('button', { name: /create task/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText(/title must be between 3 and 256 characters/i)).toBeInTheDocument();
    });

    // Test single character
    fireEvent.change(titleInput, { target: { value: 'a' } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText(/title must be between 3 and 256 characters/i)).toBeInTheDocument();
    });
  });

  it('prevents submission when title exceeds 256 characters', async () => {
    renderWithProviders(<CreateTaskForm />, '/app/tasks/new');

    const titleInput = screen.getByPlaceholderText(/e\.g\. Fix Token Budget Overflow in AST Analyzer/i);
    const overlyLongTitle = 'x'.repeat(257);
    fireEvent.change(titleInput, { target: { value: overlyLongTitle } });

    const submitBtn = screen.getByRole('button', { name: /create task/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText(/title must be between 3 and 256 characters/i)).toBeInTheDocument();
    });
  });

  it('prevents submission when requirement target_files overlap with constraint forbidden_files', async () => {
    renderWithProviders(<CreateTaskForm />, '/app/tasks/new');

    // Fill valid title and description
    const titleInput = screen.getByPlaceholderText(/e\.g\. Fix Token Budget Overflow in AST Analyzer/i);
    fireEvent.change(titleInput, { target: { value: 'Valid Title for Overlap Test' } });

    const descInput = screen.getByPlaceholderText(/provide a detailed description/i);
    fireEvent.change(descInput, { target: { value: 'Valid description for overlap test.' } });

    // Set requirement description and target files
    const reqDesc = screen.getByPlaceholderText(/e\.g\. Cap AST symbol extraction depth/i);
    fireEvent.change(reqDesc, { target: { value: 'Update authentication middleware' } });

    const reqFiles = screen.getByPlaceholderText(/src\/analyzer\/ast_walker\.py/i);
    fireEvent.change(reqFiles, { target: { value: 'src/config/keys.py, src/middleware/auth.py' } });

    // Add constraint
    const addConstraintBtn = screen.getByRole('button', { name: /add constraint/i });
    fireEvent.click(addConstraintBtn);

    const forbiddenInput = screen.getByPlaceholderText(/src\/parser\/grammar\.py/i);
    // Overlap on src/config/keys.py with whitespace padding
    fireEvent.change(forbiddenInput, { target: { value: '  src/config/keys.py , src/other.py' } });

    const submitBtn = screen.getByRole('button', { name: /create task/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(
        screen.getByText(/conflict: target file "src\/config\/keys\.py"/i)
      ).toBeInTheDocument();
    });
  });

  it('allows submission when requirement target_files and constraint forbidden_files are completely disjoint', async () => {
    renderWithProviders(<CreateTaskForm />, '/app/tasks/new');

    const titleInput = screen.getByPlaceholderText(/e\.g\. Fix Token Budget Overflow in AST Analyzer/i);
    fireEvent.change(titleInput, { target: { value: 'Disjoint Files Task' } });

    const descInput = screen.getByPlaceholderText(/provide a detailed description/i);
    fireEvent.change(descInput, { target: { value: 'Valid description.' } });

    const reqDesc = screen.getByPlaceholderText(/e\.g\. Cap AST symbol extraction depth/i);
    fireEvent.change(reqDesc, { target: { value: 'Update client' } });

    const reqFiles = screen.getByPlaceholderText(/src\/analyzer\/ast_walker\.py/i);
    fireEvent.change(reqFiles, { target: { value: 'src/client.ts' } });

    const addConstraintBtn = screen.getByRole('button', { name: /add constraint/i });
    fireEvent.click(addConstraintBtn);

    const forbiddenInput = screen.getByPlaceholderText(/src\/parser\/grammar\.py/i);
    fireEvent.change(forbiddenInput, { target: { value: 'src/server.ts' } });

    const submitBtn = screen.getByRole('button', { name: /create task/i });
    fireEvent.click(submitBtn);

    // Verify disjointness error does NOT appear
    await waitFor(() => {
      expect(screen.queryByText(/conflict: target file/i)).not.toBeInTheDocument();
    });
  });
});

// ============================================================================
// 3. PlanReviewPanel Gate Enforcement Across All 17 Statuses
// ============================================================================
describe('Empirical Challenge: PlanReviewPanel Gate Enforcement', () => {
  beforeEach(() => {
    // Ensure all plan queries resolve to mockPlanPayload regardless of task id
    server.use(
      http.get('*/api/v1/tasks/:taskId/plan', () => {
        return HttpResponse.json(mockPlanPayload);
      })
    );
  });

  it('strictly enables Approve and Reject when status is PENDING_APPROVAL', async () => {
    const task: TaskDetailResponse = {
      ...mockBaseTask,
      status: TaskStatus.PENDING_APPROVAL,
    };

    renderWithProviders(<PlanReviewPanel task={task} />, `/app/tasks/${task.task_id}`);

    await waitFor(() => {
      expect(screen.getByTestId('approve-button')).toBeInTheDocument();
    });

    const approveBtn = screen.getByTestId('approve-button');
    expect(approveBtn).not.toBeDisabled();

    // Reject toggle is available
    const rejectToggle = screen.getByRole('button', { name: /reject plan/i });
    expect(rejectToggle).toBeInTheDocument();
  });

  it(
    'strictly disables Approve button and hides Reject toggle for all non-PENDING_APPROVAL statuses',
    async () => {
    const nonPendingStatuses = ALL_17_CANONICAL_STATUSES.filter(
      (s) => s !== TaskStatus.PENDING_APPROVAL
    );

    expect(nonPendingStatuses.length).toBe(16);

    for (const status of nonPendingStatuses) {
      const task: TaskDetailResponse = {
        ...mockBaseTask,
        task_id: `task-gate-test-${status.toLowerCase()}`,
        status,
      };

      const { unmount } = renderWithProviders(
        <PlanReviewPanel task={task} />,
        `/app/tasks/${task.task_id}`
      );

      await waitFor(() => {
        expect(screen.getByTestId('approve-button')).toBeInTheDocument();
      });

      const approveBtn = screen.getByTestId('approve-button');
      expect(approveBtn).toBeDisabled();

      // Reject toggle must NOT be rendered when not PENDING_APPROVAL
      expect(screen.queryByRole('button', { name: /reject plan/i })).not.toBeInTheDocument();

      unmount();
    }
  }, 30000);
});

// ============================================================================
// 4. PlanReviewPanel 409 Version Mismatch Alert & Refresh Action
// ============================================================================
describe('Empirical Challenge: 409 Version Mismatch and Refresh Handling', () => {
  beforeEach(() => {
    server.use(
      http.get('*/api/v1/tasks/:taskId/plan', () => {
        return HttpResponse.json(mockPlanPayload);
      })
    );
  });

  it('displays clear 409 PLAN_VERSION_MISMATCH warning and triggers refresh action on click', async () => {
    server.use(
      http.post('*/api/v1/tasks/:taskId/approve', () => {
        return HttpResponse.json(
          {
            error: {
              code: 'PLAN_VERSION_MISMATCH',
              message: 'The plan was revised in the background. Your submitted version 1 is stale.',
              retryable: false,
              details: { submitted_version: 1, current_version: 2 },
            },
          },
          { status: 409 }
        );
      })
    );

    const task: TaskDetailResponse = {
      ...mockBaseTask,
      task_id: 'task-seed-1',
      status: TaskStatus.PENDING_APPROVAL,
    };

    const { queryClient } = renderWithProviders(
      <PlanReviewPanel task={task} />,
      `/app/tasks/${task.task_id}`
    );

    await waitFor(() => {
      expect(screen.getByTestId('approve-button')).toBeEnabled();
    });

    const approveBtn = screen.getByTestId('approve-button');
    fireEvent.click(approveBtn);

    // Verify 409 warning alert appears
    await waitFor(() => {
      expect(screen.getByText(/Plan Version Mismatch/i)).toBeInTheDocument();
      expect(
        screen.getAllByText(/the plan was revised in the background/i).length
      ).toBeGreaterThanOrEqual(1);
    });

    const refreshBtn = screen.getByRole('button', {
      name: /refresh plan to current version/i,
    });
    expect(refreshBtn).toBeInTheDocument();

    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

    // Click refresh
    fireEvent.click(refreshBtn);

    // Alert title is dismissed and query cache invalidated
    expect(screen.queryByText(/Plan Version Mismatch/i)).not.toBeInTheDocument();
    expect(invalidateSpy).toHaveBeenCalled();
  });
});

// ============================================================================
// 5. Zero Execution Triggers in PlanReviewPanel and TaskDetail
// ============================================================================
describe('Empirical Challenge: No Execution Actions in M2 UI', () => {
  const FORBIDDEN_EXECUTION_PATTERNS = [
    /\bexecute\b/i,
    /\brun\s+task\b/i,
    /\btrigger\s+execution\b/i,
    /\bstart\s+execution\b/i,
    /\bsandbox\b/i,
    /\bcreate\s+pr\b/i,
    /\bcreate\s+draft\s+pr\b/i,
    /\bpublish\s+branch\b/i,
    /\bpush\s+branch\b/i,
  ];

  beforeEach(() => {
    server.use(
      http.get('*/api/v1/tasks/:taskId/plan', () => {
        return HttpResponse.json(mockPlanPayload);
      })
    );
  });

  it('confirms NO execution buttons or links exist in PlanReviewPanel', async () => {
    const task: TaskDetailResponse = {
      ...mockBaseTask,
      status: TaskStatus.PENDING_APPROVAL,
    };

    renderWithProviders(<PlanReviewPanel task={task} />, `/app/tasks/${task.task_id}`);

    await waitFor(() => {
      expect(screen.getByTestId('approve-button')).toBeInTheDocument();
    });

    // Check all interactive elements
    const buttons = screen.queryAllByRole('button');
    const links = screen.queryAllByRole('link');
    const allInteractive = [...buttons, ...links];

    for (const el of allInteractive) {
      const text = el.textContent || '';
      const ariaLabel = el.getAttribute('aria-label') || '';
      for (const pattern of FORBIDDEN_EXECUTION_PATTERNS) {
        expect(text).not.toMatch(pattern);
        expect(ariaLabel).not.toMatch(pattern);
      }
    }
  });

  it('confirms NO execution buttons or links exist in TaskDetail page', async () => {
    renderWithProviders(<TaskDetail />, '/app/tasks/task-seed-1');

    await waitFor(() => {
      expect(screen.getByText(/task-seed-1/i)).toBeInTheDocument();
    });

    const buttons = screen.queryAllByRole('button');
    const links = screen.queryAllByRole('link');
    const allInteractive = [...buttons, ...links];

    for (const el of allInteractive) {
      const text = el.textContent || '';
      const ariaLabel = el.getAttribute('aria-label') || '';
      for (const pattern of FORBIDDEN_EXECUTION_PATTERNS) {
        expect(text).not.toMatch(pattern);
        expect(ariaLabel).not.toMatch(pattern);
      }
    }
  });
});
