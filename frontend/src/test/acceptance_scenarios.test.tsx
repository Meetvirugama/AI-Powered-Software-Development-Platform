/**
 * Day 5, Day 6 & Day 7 Final Acceptance Scenarios Test Suite.
 *
 * Covers:
 * - Docs/week3.md §11 Final Acceptance Scenarios (A through J)
 * - Day 5 Independent Verification & GitHub Publication
 * - Day 6 Failure Recovery, Stale Revision Detection, Security Policy Alerts
 * - Day 7 Acceptance & Reliability Verification
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor, render, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';
import { resetMockStore } from '../mocks/handlers';
import {
  TaskStatus,
  type TaskDetailResponse,
  type TaskPullRequest,
} from '../types/task';
import { taskKeys } from '../hooks/useTasks';
import { TaskDetail } from '../pages/TaskDetail';
import { VerificationPanel } from '../components/tasks/VerificationPanel';
import { PublicationPanel } from '../components/tasks/PublicationPanel';
import { RecoveryPanel } from '../components/tasks/RecoveryPanel';
import { SecurityAlertBanner } from '../components/tasks/SecurityAlertBanner';
import { publishDraftPR, recoverTask } from '../services/tasks';

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

function renderWithProviders(ui: React.ReactElement, initialRoute = '/app/tasks/task-scenario-pub-ready') {
  const queryClient = createTestQueryClient();
  return {
    ...render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[initialRoute]}>
          <Routes>
            <Route path="/app/tasks/:taskId" element={ui} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    ),
    queryClient,
  };
}

describe('Final Acceptance Scenarios (Week 3 Days 5–7)', () => {
  beforeEach(() => {
    resetMockStore();
  });

  // ==========================================================================
  // Scenario A — Successful Workflow: Execution -> Verification -> Publication
  // ==========================================================================
  describe('Scenario A — Successful Workflow', () => {
    it('completes verification, authorizes publication, and displays Draft PR result', async () => {
      renderWithProviders(<TaskDetail />, '/app/tasks/task-scenario-pub-ready');

      // 1. Task loads in READY_FOR_PUBLICATION state
      await waitFor(() => {
        expect(screen.getByText('Ready for Publication Authorization')).toBeInTheDocument();
      });

      // 2. Verification Panel displays PASS status and checks
      await waitFor(() => {
        const verifPanel = screen.getByTestId('verification-panel');
        expect(verifPanel).toBeInTheDocument();
        expect(within(verifPanel).getByText('VERIFICATION PASSED')).toBeInTheDocument();
      });

      expect(screen.getByText('All tests passed.')).toBeInTheDocument();
      expect(screen.getByText('0 vulnerabilities detected.')).toBeInTheDocument();

      // 3. Publication Panel displays publication eligibility
      const pubPanel = screen.getByTestId('publication-panel');
      expect(pubPanel).toBeInTheDocument();
      expect(screen.getByText('Explicit Human Publication Authorization')).toBeInTheDocument();

      // 4. Submit button is disabled until explicit human authorization is checked
      const publishBtn = screen.getByRole('button', { name: /authorize & publish draft pr/i });
      expect(publishBtn).toBeDisabled();

      // 5. User checks explicit authorization checkbox
      const authCheckbox = screen.getByRole('checkbox');
      fireEvent.click(authCheckbox);
      expect(publishBtn).not.toBeDisabled();

      // 6. User clicks Publish Draft PR
      fireEvent.click(publishBtn);

      // 7. Draft PR Card is rendered with title, external link, and draft safety badge
      await waitFor(() => {
        expect(screen.getByTestId('draft-pr-card')).toBeInTheDocument();
        expect(screen.getByTestId('open-pr-link')).toBeInTheDocument();
      });

      expect(screen.getByText('Draft Pull Request')).toBeInTheDocument();
      expect(screen.getByText(/ADR-010 Safety Guarantee/i)).toBeInTheDocument();
      expect(screen.getByTestId('open-pr-link')).toHaveAttribute(
        'href',
        expect.stringContaining('https://github.com/example/repo/pull/')
      );
    });
  });

  // ==========================================================================
  // Scenario B — Plan Rejected: Blocked Execution Gate
  // ==========================================================================
  describe('Scenario B — Plan Rejected', () => {
    it('blocks execution when task plan has been rejected', async () => {
      renderWithProviders(<TaskDetail />, '/app/tasks/task-seed-4');

      await waitFor(() => {
        expect(screen.getByText('Refactor Database Migration Runner to Async')).toBeInTheDocument();
      });

      // Status badge shows REJECTED
      expect(screen.getByTestId('status-badge')).toHaveTextContent('REJECTED');

      // Zero execution buttons exist
      expect(screen.queryByRole('button', { name: /start execution/i })).not.toBeInTheDocument();
    });
  });

  // ==========================================================================
  // Scenario D — Test Failure & Repair Budget Exhaustion
  // ==========================================================================
  describe('Scenario D — Test Failure and Repair Budget Exhaustion', () => {
    it('renders retry budget exhausted banner and blocks publication eligibility', async () => {
      renderWithProviders(<TaskDetail />, '/app/tasks/task-exec-budget-exhausted');

      await waitFor(() => {
        expect(screen.getByText('Retry Budget Exhausted')).toBeInTheDocument();
      });

      // Status is FAILED
      expect(screen.getByTestId('status-badge')).toHaveTextContent('FAILED');

      // Repair tracker shows 3/3 exhausted banner
      await waitFor(() => {
        expect(screen.getByTestId('repair-budget-exhausted-banner')).toBeInTheDocument();
        expect(screen.getByText(/Repair Budget Exhausted/i)).toBeInTheDocument();
      });

      // Publication panel indicates publication is blocked
      await waitFor(() => {
        expect(screen.getByText(/Verification must pass before publication is unlocked/i)).toBeInTheDocument();
      });
      const publishBtn = screen.getByRole('button', { name: /authorize & publish draft pr/i });
      expect(publishBtn).toBeDisabled();
    });
  });

  // ==========================================================================
  // Scenario E — Malicious Tool Request / Security Policy Violation
  // ==========================================================================
  describe('Scenario E — Malicious Tool Request and Security Event Visibility', () => {
    it('renders security alert banner with sanitized explanation and no leaked credentials', async () => {
      renderWithProviders(<TaskDetail />, '/app/tasks/task-scenario-sec-alert');

      await waitFor(() => {
        expect(screen.getByText('Blocked Security Policy Violation')).toBeInTheDocument();
      });

      // Security banner appears
      await waitFor(() => {
        expect(screen.getByTestId('security-alert-banner')).toBeInTheDocument();
        expect(screen.getByText('Security Policy Enforcement Blocked Operation')).toBeInTheDocument();
      });

      // Displays sanitized details scoped to security banner
      const secBanner = screen.getByTestId('security-alert-banner');
      expect(within(secBanner).getByText(/Blocked unauthorized write to protected file: infra\/secrets\.env/i)).toBeInTheDocument();

      // Verify no raw passwords or api tokens leaked
      expect(screen.queryByText(/token/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/password/i)).not.toBeInTheDocument();
    });
  });

  // ==========================================================================
  // Scenario F — Verification Failure with Blocking Findings
  // ==========================================================================
  describe('Scenario F — Verification Failure and Publication Blocked', () => {
    it('displays critical security finding and blocks Draft PR publication', async () => {
      renderWithProviders(<TaskDetail />, '/app/tasks/task-scenario-verify-fail');

      await waitFor(() => {
        expect(screen.getByText('Verification Failed with Blocking Finding')).toBeInTheDocument();
      });

      // Verification panel shows FAILED status
      await waitFor(() => {
        const verifPanel = screen.getByTestId('verification-panel');
        expect(verifPanel).toBeInTheDocument();
        expect(within(verifPanel).getByText('VERIFICATION FAILED')).toBeInTheDocument();
      });

      // Shows blocking finding details (CWE-89) scoped to blocking findings section
      const blockingSection = screen.getByTestId('blocking-findings-section');
      expect(within(blockingSection).getByText(/Direct interpolation in vector query bypasses sanitization \(CWE-89\)/i)).toBeInTheDocument();
      expect(within(blockingSection).getByText('backend/app/services/vector_store.py')).toBeInTheDocument();
      expect(within(blockingSection).getByText(':L42')).toBeInTheDocument();

      // Publication panel blocks publication
      await waitFor(() => {
        expect(screen.getByText(/Publication is blocked: 1 blocking finding\(s\) exist/i)).toBeInTheDocument();
      });

      const publishBtn = screen.getByRole('button', { name: /authorize & publish draft pr/i });
      expect(publishBtn).toBeDisabled();

      // Direct API attempt without resolving blocking finding fails with 409
      await expect(
        publishDraftPR('task-scenario-verify-fail', {
          publication_authorized: true,
        })
      ).rejects.toThrow();
    });

    it('allows re-triggering verification from UI', async () => {
      renderWithProviders(<TaskDetail />, '/app/tasks/task-scenario-verify-fail');

      await waitFor(() => {
        expect(screen.getByTestId('verification-panel')).toBeInTheDocument();
      });

      const reverifyBtn = await screen.findByRole('button', { name: /re-run verification/i });
      expect(reverifyBtn).toBeInTheDocument();
      expect(reverifyBtn).not.toBeDisabled();
    });
  });

  // ==========================================================================
  // Scenario G — GitHub API Uncertainty & Idempotency
  // ==========================================================================
  describe('Scenario G — GitHub API Error Handling and Idempotent Publication', () => {
    it('gracefully presents publication failure when GitHub API encounters rate limit or network error', async () => {
      server.use(
        http.post('*/api/v1/tasks/task-scenario-pub-ready/publish', () => {
          return HttpResponse.json(
            {
              error: {
                code: 'PUBLICATION_FAILED',
                message: 'GitHub API rate limit exceeded. Please retry in 1 minute.',
                retryable: true,
              },
            },
            { status: 502 }
          );
        })
      );

      renderWithProviders(<TaskDetail />, '/app/tasks/task-scenario-pub-ready');

      await waitFor(() => {
        expect(screen.getByTestId('publication-panel')).toBeInTheDocument();
      });

      // Authorize and submit
      const authCheckbox = screen.getByRole('checkbox');
      fireEvent.click(authCheckbox);

      const publishBtn = screen.getByRole('button', { name: /authorize & publish draft pr/i });
      fireEvent.click(publishBtn);

      // Displays error alert
      await waitFor(() => {
        expect(screen.getByText(/GitHub API rate limit exceeded/i)).toBeInTheDocument();
      });
    });

    it('returns existing PR idempotently when already published', async () => {
      const res = await publishDraftPR('task-seed-6', {
        publication_authorized: true,
      });

      expect(res.success).toBe(true);
      expect(res.pr_number).toBe(143);
      expect(res.summary).toContain('already published');
    });
  });

  // ==========================================================================
  // Scenario H — Task Recovery from Interrupted / Failed State
  // ==========================================================================
  describe('Scenario H — Failure Recovery and State Reconciliation', () => {
    it('renders recovery panel for RECOVERY_REQUIRED task and dispatches recovery action', async () => {
      renderWithProviders(<TaskDetail />, '/app/tasks/task-scenario-recovery-req');

      await waitFor(() => {
        expect(screen.getByText('Interrupted Execution Recovery Required')).toBeInTheDocument();
      });

      // Recovery panel is visible
      await waitFor(() => {
        expect(screen.getByTestId('recovery-panel')).toBeInTheDocument();
        expect(screen.getByText('State Recovery Required')).toBeInTheDocument();
      });

      expect(screen.getByText(/A worker crash or process interruption was detected/i)).toBeInTheDocument();

      // Shows recovery strategy buttons
      const reconcileBtn = screen.getByRole('button', { name: /reconcile state/i });
      const resetBtn = screen.getByRole('button', { name: /reset to plan/i });

      expect(reconcileBtn).toBeInTheDocument();
      expect(resetBtn).toBeInTheDocument();

      // Trigger reconcile action
      fireEvent.click(reconcileBtn);

      // Task transitions to EXECUTING, recovery panel is dismissed
      await waitFor(() => {
        expect(screen.queryByTestId('recovery-panel')).not.toBeInTheDocument();
      });
    });

    it('supports direct service recovery invocation', async () => {
      const result = await recoverTask('task-scenario-recovery-req', {
        action: 'reset_to_plan',
        reason: 'Reset after container crash',
      });

      expect(result.current_status).toBe(TaskStatus.APPROVED);
      expect(result.details).toContain('reset_to_plan');
    });
  });

  // ==========================================================================
  // Scenario I — Strict Publication Authorization Gate (ADR-010)
  // ==========================================================================
  describe('Scenario I — Publication Authorization Gate (ADR-010)', () => {
    it('strictly prohibits publication without publication_authorized flag in API', async () => {
      await expect(
        publishDraftPR('task-scenario-pub-ready', {
          publication_authorized: false,
        })
      ).rejects.toThrow();
    });

    it('requires user checkbox before allowing submit button click in UI', async () => {
      renderWithProviders(<TaskDetail />, '/app/tasks/task-scenario-pub-ready');

      await waitFor(() => {
        expect(screen.getByTestId('publication-panel')).toBeInTheDocument();
      });

      const publishBtn = screen.getByRole('button', { name: /authorize & publish draft pr/i });
      expect(publishBtn).toBeDisabled();

      // Toggle checkbox on and off
      const authCheckbox = screen.getByRole('checkbox');
      fireEvent.click(authCheckbox);
      expect(publishBtn).not.toBeDisabled();

      fireEvent.click(authCheckbox);
      expect(publishBtn).toBeDisabled();
    });
  });

  // ==========================================================================
  // Scenario J — Stale Revision Drift Detection
  // ==========================================================================
  describe('Scenario J — Revision Drift and Stale Verification', () => {
    it('detects when repository revision differs from verified revision and blocks publication', async () => {
      renderWithProviders(<TaskDetail />, '/app/tasks/task-scenario-stale');

      await waitFor(() => {
        expect(screen.getByText('Stale Revision Drift Detected')).toBeInTheDocument();
      });

      // Verification panel displays Stale Verification warning
      await waitFor(() => {
        const staleWarning = screen.getByTestId('stale-verification-warning');
        expect(staleWarning).toBeInTheDocument();
        expect(screen.getByText(/Stale Verification Detected/i)).toBeInTheDocument();
        expect(within(staleWarning).getByText(/rev-old-in/i)).toBeInTheDocument();
        expect(within(staleWarning).getByText(/rev-drifte/i)).toBeInTheDocument();
      });

      // Publication panel indicates publication is blocked due to stale revision
      await waitFor(() => {
        expect(screen.getByText(/Publication is blocked: Workspace revision has drifted/i)).toBeInTheDocument();
      });

      const publishBtn = screen.getByRole('button', { name: /authorize & publish draft pr/i });
      expect(publishBtn).toBeDisabled();
    });
  });

  // ==========================================================================
  // Component & Unit Level Edge Case Tests
  // ==========================================================================
  describe('Component & Unit Verifications', () => {
    it('VerificationPanel renders empty state when verification is null', async () => {
      const queryClient = createTestQueryClient();
      queryClient.setQueryData(taskKeys.verification('task-nonexistent'), null);
      render(
        <QueryClientProvider client={queryClient}>
          <VerificationPanel taskId="task-nonexistent" />
        </QueryClientProvider>
      );

      await waitFor(() => {
        expect(screen.getByText(/Verification Not Yet Run/i)).toBeInTheDocument();
      });
    });

    it('PublicationPanel renders Draft PR metadata correctly', () => {
      const mockTask: TaskDetailResponse = {
        task_id: 'task-test-pr',
        repository_id: 'repo-test',
        title: 'Add Audit Telemetry Logging',
        description: 'Implement audit logging in telemetry pipeline.',
        status: TaskStatus.DRAFT_PR_CREATED,
        source: { type: 'USER_PROMPT', repository_id: 'repo-test' },
        requirements: [{ id: 'r1', description: 'Log audit', category: 'security', target_files: ['src/audit.ts'], acceptance_criteria: ['Audit logs generated'] }],
        assumptions: [],
        constraints: [],
        base_revision: 'rev-base',
        plan_version: 1,
        approved_plan_version: 1,
        repair_attempts_used: 0,
        repair_attempts_max: 3,
        created_at: '2026-10-20T10:00:00Z',
        updated_at: '2026-10-20T11:00:00Z',
      };

      const mockPR: TaskPullRequest = {
        task_id: 'task-test-pr',
        pr_number: 99,
        pr_url: 'https://github.com/example/repo/pull/99',
        head_branch: 'agent/task-test-pr',
        base_branch: 'main',
        title: 'Add Audit Telemetry Logging',
        is_draft: true,
        created_at: '2026-10-20T11:00:00Z',
        summary: 'Implements comprehensive audit logging across all endpoints.',
      };

      const queryClient = createTestQueryClient();
      queryClient.setQueryData(taskKeys.pullRequest('task-test-pr'), mockPR);

      render(
        <QueryClientProvider client={queryClient}>
          <PublicationPanel task={mockTask} />
        </QueryClientProvider>
      );

      expect(screen.getByTestId('draft-pr-card')).toBeInTheDocument();
      expect(screen.getByText('#99')).toBeInTheDocument();
      expect(screen.getByText('Add Audit Telemetry Logging')).toBeInTheDocument();
      expect(screen.getByText('Implements comprehensive audit logging across all endpoints.')).toBeInTheDocument();
    });

    it('SecurityAlertBanner ignores non-security events and renders nothing', () => {
      const { container } = render(
        <SecurityAlertBanner
          events={[
            {
              id: 'evt-1',
              task_id: 'task-1',
              event_type: 'PLAN_APPROVED',
              description: 'Plan approved',
              created_at: '2026-10-20T10:00:00Z',
            },
            {
              id: 'evt-2',
              task_id: 'task-1',
              event_type: 'WORKSPACE_SETUP',
              description: 'Workspace ready',
              created_at: '2026-10-20T10:05:00Z',
            },
          ]}
        />
      );

      expect(container.firstChild).toBeNull();
    });

    it('RecoveryPanel does not render for non-recoverable tasks', () => {
      const mockTask: TaskDetailResponse = {
        task_id: 'task-approved',
        repository_id: 'repo-test',
        title: 'Task Approved',
        description: 'Ready to execute',
        status: TaskStatus.APPROVED,
        source: { type: 'USER_PROMPT', repository_id: 'repo-test' },
        requirements: [{ id: 'r1', description: 'Test', category: 'test', target_files: ['src/test.ts'], acceptance_criteria: ['Tests pass'] }],
        assumptions: [],
        constraints: [],
        base_revision: 'rev-base',
        plan_version: 1,
        approved_plan_version: 1,
        repair_attempts_used: 0,
        repair_attempts_max: 3,
        created_at: '2026-10-20T10:00:00Z',
        updated_at: '2026-10-20T10:00:00Z',
      };

      const queryClient = createTestQueryClient();
      const { container } = render(
        <QueryClientProvider client={queryClient}>
          <RecoveryPanel task={mockTask} />
        </QueryClientProvider>
      );

      expect(container.firstChild).toBeNull();
    });
  });
});
