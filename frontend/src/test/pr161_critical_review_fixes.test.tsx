/**
 * PR #161 Critical Review & Reliability Fixes Test Suite
 *
 * Covers the 15 mandatory regression tests required by the review:
 * 1. Missing verification blocks publication
 * 2. Verification API failure blocks publication
 * 3. Verification status FAIL blocks publication
 * 4. Blocking findings block publication
 * 5. Stale verification blocks publication
 * 6. Non-default base branch is used correctly
 * 7. Missing branch metadata blocks publication
 * 8. Workspace revision drift invalidates verification
 * 9. Stale-check API failure does not appear successful
 * 10. Security event with a token does not expose the token
 * 11. Malformed security event is handled safely
 * 12. Duplicate publication clicks do not create duplicate requests
 * 13. Uncertain publication outcome is handled without blind retries
 * 14. Recovery is unavailable when repair budget is exhausted
 * 15. Unsupported recovery actions are not displayed
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor, render } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse, delay } from 'msw';
import { server } from '../mocks/server';
import { resetMockStore } from '../mocks/handlers';
import {
  TaskStatus,
  WorkspaceStatus,
  isPublicationEligible,
  type TaskDetailResponse,
  type VerificationResult,
  type WorkspaceMetadata,
} from '../types/task';
import { repositoryKeys } from '../hooks/useRepositories';
import { taskKeys } from '../hooks/useTasks';
import { PublicationPanel } from '../components/tasks/PublicationPanel';
import { RecoveryPanel } from '../components/tasks/RecoveryPanel';
import { SecurityAlertBanner, sanitizeSecurityMessage } from '../components/tasks/SecurityAlertBanner';

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

function renderWithClient(ui: React.ReactElement, client?: QueryClient) {
  const queryClient = client || createTestQueryClient();
  return {
    ...render(
      <QueryClientProvider client={queryClient}>
        {ui}
      </QueryClientProvider>
    ),
    queryClient,
  };
}

const mockBaseTask: TaskDetailResponse = {
  task_id: 'task-test-review',
  repository_id: 'repo-test-1',
  title: 'Implement Tenant Security Policies',
  description: 'Enforce tenant isolation across all endpoints.',
  status: TaskStatus.READY_FOR_PUBLICATION,
  source: { type: 'USER_PROMPT', repository_id: 'repo-test-1' },
  requirements: [{ id: 'r1', description: 'Enforce isolation', category: 'security', target_files: ['src/tenant.py'], acceptance_criteria: ['Isolated'] }],
  assumptions: [],
  constraints: [],
  base_revision: 'rev-base-100',
  plan_version: 1,
  approved_plan_version: 1,
  repair_attempts_used: 0,
  repair_attempts_max: 3,
  created_at: '2026-10-20T10:00:00Z',
  updated_at: '2026-10-20T11:00:00Z',
};

const mockValidWorkspace: WorkspaceMetadata = {
  workspace_id: 'ws-review-1',
  task_id: 'task-test-review',
  repository_id: 'repo-test-1',
  base_revision: 'rev-base-100',
  branch_name: 'agent/task-test-review',
  status: WorkspaceStatus.READY,
};

const mockPassingVerification: VerificationResult = {
  task_id: 'task-test-review',
  verified_revision: 'rev-base-100',
  status: 'PASS',
  checks: [
    { name: 'test_suite', status: 'PASSED', duration_ms: 500, message: 'All tests pass.', findings_count: 0 },
    { name: 'security_checks', status: 'PASSED', duration_ms: 200, message: '0 vulnerabilities.', findings_count: 0 },
  ],
  blocking_findings: [],
  warnings: [],
  pr_summary: 'Fully verified.',
  created_at: '2026-10-20T11:00:00Z',
};

const mockPassingStaleCheck = {
  task_id: 'task-test-review',
  is_stale: false,
  workspace_base_revision: 'rev-base-100',
  current_base_revision: 'rev-base-100',
  current_remote_sha: 'rev-base-100',
  commits_behind: 0,
  message: 'Current',
  checked_at: new Date().toISOString(),
};

describe('PR #161 Critical Review & Reliability Fixes', () => {
  beforeEach(() => {
    resetMockStore();
  });

  // ==========================================================================
  // 1. Missing verification blocks publication
  // ==========================================================================
  describe('1. Missing verification blocks publication', () => {
    it('isPublicationEligible returns false when verification is missing or null (fail-closed)', () => {
      expect(isPublicationEligible(TaskStatus.READY_FOR_PUBLICATION, null, false)).toBe(false);
      expect(isPublicationEligible(TaskStatus.READY_FOR_PUBLICATION, undefined, false)).toBe(false);
    });

    it('PublicationPanel blocks publication controls when verification data is missing', async () => {
      const client = createTestQueryClient();
      client.setQueryData(taskKeys.verification(mockBaseTask.task_id), null);
      client.setQueryData(repositoryKeys.detail(mockBaseTask.repository_id), {
        id: mockBaseTask.repository_id,
        name: 'test-repo',
        default_branch: 'main',
      });

      renderWithClient(
        <PublicationPanel task={mockBaseTask} workspace={mockValidWorkspace} />,
        client
      );

      const checkbox = screen.getByTestId('authorize-publication-checkbox');
      const publishBtn = screen.getByTestId('authorize-publish-button');

      expect(checkbox).toBeDisabled();
      expect(publishBtn).toBeDisabled();
      expect(screen.getByText(/Verification must pass before publication is unlocked/i)).toBeInTheDocument();
    });
  });

  // ==========================================================================
  // 2. Verification API failure blocks publication
  // ==========================================================================
  describe('2. Verification API failure blocks publication', () => {
    it('isPublicationEligible returns false when hasVerificationError is true', () => {
      const eligible = isPublicationEligible({
        status: TaskStatus.READY_FOR_PUBLICATION,
        verification: mockPassingVerification,
        hasVerificationError: true,
      });
      expect(eligible).toBe(false);
    });

    it('PublicationPanel displays verification error alert and disables controls', async () => {
      server.use(
        http.get('*/api/v1/tasks/:taskId/verification', () => {
          return HttpResponse.json({ error: { message: 'Database connection failed' } }, { status: 500 });
        })
      );

      renderWithClient(
        <PublicationPanel task={mockBaseTask} workspace={mockValidWorkspace} />
      );

      await waitFor(() => {
        expect(screen.getByTestId('verification-error-alert')).toBeInTheDocument();
      });

      expect(screen.getByTestId('authorize-publication-checkbox')).toBeDisabled();
      expect(screen.getByTestId('authorize-publish-button')).toBeDisabled();
    });
  });

  // ==========================================================================
  // 3. Verification status FAIL blocks publication
  // ==========================================================================
  describe('3. Verification status FAIL blocks publication', () => {
    it('isPublicationEligible returns false when verification status is FAIL', () => {
      const failVerif: VerificationResult = {
        ...mockPassingVerification,
        status: 'FAIL',
      };
      expect(isPublicationEligible(TaskStatus.READY_FOR_PUBLICATION, failVerif, false)).toBe(false);
    });

    it('PublicationPanel prevents publication when verification overall status is FAIL', async () => {
      const client = createTestQueryClient();
      client.setQueryData(taskKeys.verification(mockBaseTask.task_id), {
        ...mockPassingVerification,
        status: 'FAIL',
      });
      client.setQueryData(repositoryKeys.detail(mockBaseTask.repository_id), {
        id: mockBaseTask.repository_id,
        name: 'test-repo',
        default_branch: 'main',
      });

      renderWithClient(
        <PublicationPanel task={mockBaseTask} workspace={mockValidWorkspace} />,
        client
      );

      expect(screen.getByTestId('authorize-publish-button')).toBeDisabled();
      expect(screen.getByText(/Verification must pass before publication is unlocked/i)).toBeInTheDocument();
    });
  });

  // ==========================================================================
  // 4. Blocking findings block publication
  // ==========================================================================
  describe('4. Blocking findings block publication', () => {
    it('isPublicationEligible returns false when blocking_findings exist even if status is PASS', () => {
      const verifWithFinding: VerificationResult = {
        ...mockPassingVerification,
        status: 'PASS',
        blocking_findings: [
          {
            id: 'block-1',
            severity: 'CRITICAL',
            category: 'security',
            message: 'SQL Injection detected in repository query.',
            blocking: true,
          },
        ],
      };
      expect(isPublicationEligible(TaskStatus.READY_FOR_PUBLICATION, verifWithFinding, false)).toBe(false);
    });

    it('PublicationPanel displays blocking findings alert and blocks publication', async () => {
      const client = createTestQueryClient();
      client.setQueryData(taskKeys.verification(mockBaseTask.task_id), {
        ...mockPassingVerification,
        blocking_findings: [
          {
            id: 'block-1',
            severity: 'CRITICAL',
            category: 'security',
            message: 'Unauthorized credential exposure.',
            blocking: true,
          },
        ],
      });
      client.setQueryData(repositoryKeys.detail(mockBaseTask.repository_id), {
        id: mockBaseTask.repository_id,
        name: 'test-repo',
        default_branch: 'main',
      });

      renderWithClient(
        <PublicationPanel task={mockBaseTask} workspace={mockValidWorkspace} />,
        client
      );

      expect(screen.getByTestId('blocking-findings-alert')).toBeInTheDocument();
      expect(screen.getByText(/1 blocking finding\(s\) exist/i)).toBeInTheDocument();
      expect(screen.getByTestId('authorize-publish-button')).toBeDisabled();
    });
  });

  // ==========================================================================
  // 5. Stale verification blocks publication
  // ==========================================================================
  describe('5. Stale verification blocks publication', () => {
    it('isPublicationEligible returns false when isStale is true', () => {
      expect(isPublicationEligible(TaskStatus.READY_FOR_PUBLICATION, mockPassingVerification, true)).toBe(false);
    });

    it('PublicationPanel displays stale revision alert and blocks publication', async () => {
      const client = createTestQueryClient();
      client.setQueryData(taskKeys.verification(mockBaseTask.task_id), mockPassingVerification);
      client.setQueryData(taskKeys.staleCheck(mockBaseTask.task_id), {
        task_id: mockBaseTask.task_id,
        is_stale: true,
        workspace_base_revision: 'rev-base-100',
        current_base_revision: 'rev-base-100',
        current_remote_sha: 'rev-remote-drifted',
        commits_behind: 4,
        message: 'Remote repository has advanced by 4 commits.',
        checked_at: new Date().toISOString(),
      });
      client.setQueryData(repositoryKeys.detail(mockBaseTask.repository_id), {
        id: mockBaseTask.repository_id,
        name: 'test-repo',
        default_branch: 'main',
      });

      renderWithClient(
        <PublicationPanel task={mockBaseTask} workspace={mockValidWorkspace} />,
        client
      );

      expect(screen.getByTestId('stale-revision-alert')).toBeInTheDocument();
      expect(screen.getByText(/Remote repository has advanced by 4 commits/i)).toBeInTheDocument();
      expect(screen.getByTestId('authorize-publish-button')).toBeDisabled();
    });
  });

  // ==========================================================================
  // 6. Non-default base branch is used correctly
  // ==========================================================================
  describe('6. Non-default base branch is used correctly', () => {
    it('resolves non-default base branch (develop) from repository metadata and submits it in payload', async () => {
      let capturedBaseBranch = '';
      server.use(
        http.post('*/api/v1/tasks/:taskId/publish', async ({ request }) => {
          const body = (await request.json()) as any;
          capturedBaseBranch = body.base_branch;
          return HttpResponse.json({
            success: true,
            task_id: 'task-test-review',
            pr_number: 201,
            pr_url: 'https://github.com/example/repo/pull/201',
            head_branch: 'agent/task-test-review',
            base_branch: body.base_branch,
            is_draft: true,
            summary: 'Draft PR created.',
            created_at: new Date().toISOString(),
          });
        })
      );

      const client = createTestQueryClient();
      client.setQueryData(taskKeys.verification(mockBaseTask.task_id), mockPassingVerification);
      client.setQueryData(taskKeys.staleCheck(mockBaseTask.task_id), {
        task_id: mockBaseTask.task_id,
        is_stale: false,
        workspace_base_revision: 'rev-base-100',
        current_base_revision: 'rev-base-100',
        current_remote_sha: 'rev-base-100',
        commits_behind: 0,
        message: 'Current',
        checked_at: new Date().toISOString(),
      });
      client.setQueryData(repositoryKeys.detail(mockBaseTask.repository_id), {
        id: mockBaseTask.repository_id,
        name: 'enterprise-core',
        default_branch: 'develop',
      });

      renderWithClient(
        <PublicationPanel task={mockBaseTask} workspace={mockValidWorkspace} />,
        client
      );

      // Verify the UI displays 'develop' instead of hardcoded 'main'
      expect(screen.getByText('develop')).toBeInTheDocument();

      // Check authorization and publish
      fireEvent.click(screen.getByTestId('authorize-publication-checkbox'));
      fireEvent.click(screen.getByTestId('authorize-publish-button'));

      await waitFor(() => {
        expect(capturedBaseBranch).toBe('develop');
      });
    });
  });

  // ==========================================================================
  // 7. Missing branch metadata blocks publication
  // ==========================================================================
  describe('7. Missing branch metadata blocks publication', () => {
    it('shows unavailable state and blocks publication when workspace branch is missing', async () => {
      const client = createTestQueryClient();
      client.setQueryData(taskKeys.verification(mockBaseTask.task_id), mockPassingVerification);
      client.setQueryData(taskKeys.staleCheck(mockBaseTask.task_id), mockPassingStaleCheck);
      client.setQueryData(repositoryKeys.detail(mockBaseTask.repository_id), {
        id: mockBaseTask.repository_id,
        name: 'test-repo',
        default_branch: 'main',
      });

      // Workspace with no allocated branch
      const workspaceNoBranch: WorkspaceMetadata = {
        ...mockValidWorkspace,
        branch_name: '',
      };

      renderWithClient(
        <PublicationPanel task={mockBaseTask} workspace={workspaceNoBranch} />,
        client
      );

      expect(screen.getByTestId('missing-metadata-alert')).toBeInTheDocument();
      expect(screen.getByTestId('authorize-publication-checkbox')).toBeDisabled();
      expect(screen.getByTestId('authorize-publish-button')).toBeDisabled();
    });
  });

  // ==========================================================================
  // 8. Workspace revision drift invalidates verification
  // ==========================================================================
  describe('8. Workspace revision drift invalidates verification', () => {
    it('detects when workspace base revision differs from verified revision', async () => {
      const client = createTestQueryClient();
      client.setQueryData(taskKeys.verification(mockBaseTask.task_id), {
        ...mockPassingVerification,
        verified_revision: 'rev-verified-old',
      });
      client.setQueryData(repositoryKeys.detail(mockBaseTask.repository_id), {
        id: mockBaseTask.repository_id,
        name: 'test-repo',
        default_branch: 'main',
      });

      const driftedWorkspace: WorkspaceMetadata = {
        ...mockValidWorkspace,
        base_revision: 'rev-workspace-mutated-new',
      };

      renderWithClient(
        <PublicationPanel task={mockBaseTask} workspace={driftedWorkspace} />,
        client
      );

      expect(screen.getByTestId('stale-revision-alert')).toBeInTheDocument();
      expect(screen.getByTestId('authorize-publish-button')).toBeDisabled();
    });
  });

  // ==========================================================================
  // 9. Stale-check API failure does not appear successful
  // ==========================================================================
  describe('9. Stale-check API failure does not appear successful', () => {
    it('blocks publication when stale-check API encounters 500 error', async () => {
      server.use(
        http.get('*/api/v1/tasks/:taskId/stale-check', () => {
          return HttpResponse.json({ error: { message: 'Git remote unreachable' } }, { status: 500 });
        })
      );

      const client = createTestQueryClient();
      client.setQueryData(taskKeys.verification(mockBaseTask.task_id), mockPassingVerification);
      client.setQueryData(taskKeys.staleCheck(mockBaseTask.task_id), mockPassingStaleCheck);
      client.setQueryData(repositoryKeys.detail(mockBaseTask.repository_id), {
        id: mockBaseTask.repository_id,
        name: 'test-repo',
        default_branch: 'main',
      });

      renderWithClient(
        <PublicationPanel task={mockBaseTask} workspace={mockValidWorkspace} />,
        client
      );

      await waitFor(() => {
        expect(screen.getByTestId('stale-check-error-alert')).toBeInTheDocument();
      });

      expect(screen.getByTestId('authorize-publish-button')).toBeDisabled();
    });
  });

  // ==========================================================================
  // 10. Security event with a token does not expose the token
  // ==========================================================================
  describe('10. Security event with a token does not expose the token', () => {
    it('redacts tokens, API keys, passwords, and authorization headers in SecurityAlertBanner', () => {
      const sensitiveEvents = [
        {
          id: 'evt-sec-leak',
          task_id: 'task-sec-1',
          event_type: 'SECURITY_POLICY_VIOLATION',
          description: 'Blocked unauthorized curl with Authorization: Bearer ghp_secretToken1234567890abcdef12345678901234 and password="super_secret_password_abc"',
          created_at: new Date().toISOString(),
        },
      ];

      render(<SecurityAlertBanner events={sensitiveEvents} />);

      const banner = screen.getByTestId('security-alert-banner');
      expect(banner).toBeInTheDocument();

      // Ensure raw credentials never leak into rendered DOM
      expect(screen.queryByText(/ghp_secretToken/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/super_secret_password_abc/i)).not.toBeInTheDocument();

      // Confirm redaction tokens are present
      expect(banner.textContent).toContain('[REDACTED');
    });

    it('sanitizeSecurityMessage utility handles OpenAI, AWS, and Bearer tokens', () => {
      const raw = 'Config sk-1234567890abcdef1234567890 and AWS AKIAIOSFODNN7EXAMPLE with Bearer jwt.token.here';
      const sanitized = sanitizeSecurityMessage(raw);

      expect(sanitized).not.toContain('sk-1234567890abcdef1234567890');
      expect(sanitized).not.toContain('AKIAIOSFODNN7EXAMPLE');
      expect(sanitized).not.toContain('jwt.token.here');
      expect(sanitized).toContain('[REDACTED_CREDENTIAL]');
      expect(sanitized).toContain('Bearer [REDACTED_TOKEN]');
    });
  });

  // ==========================================================================
  // 11. Malformed security event is handled safely
  // ==========================================================================
  describe('11. Malformed security event is handled safely', () => {
    it('renders safely without throwing errors on null, missing, or malformed fields', () => {
      const malformedEvents: any[] = [
        null,
        undefined,
        {},
        { event_type: null },
        { event_type: 'SECURITY_POLICY_VIOLATION', description: null, details: undefined },
        { event_type: 'COMMAND_BLOCKED', description: { error: 'nested object' } },
      ];

      const { container } = render(<SecurityAlertBanner events={malformedEvents} />);
      expect(container).toBeInTheDocument();
      expect(screen.getByTestId('security-alert-banner')).toBeInTheDocument();
    });
  });

  // ==========================================================================
  // 12. Duplicate publication clicks do not create duplicate requests
  // ==========================================================================
  describe('12. Duplicate publication clicks do not create duplicate requests', () => {
    it('prevents multiple in-flight publish mutations on rapid double click', async () => {
      let callCount = 0;
      server.use(
        http.post('*/api/v1/tasks/:taskId/publish', async () => {
          callCount++;
          await delay(200);
          return HttpResponse.json({
            success: true,
            task_id: 'task-test-review',
            pr_number: 777,
            pr_url: 'https://github.com/example/repo/pull/777',
            head_branch: 'agent/task-test-review',
            base_branch: 'main',
            is_draft: true,
            summary: 'Created',
            created_at: new Date().toISOString(),
          });
        })
      );

      const client = createTestQueryClient();
      client.setQueryData(taskKeys.verification(mockBaseTask.task_id), mockPassingVerification);
      client.setQueryData(taskKeys.staleCheck(mockBaseTask.task_id), mockPassingStaleCheck);
      client.setQueryData(repositoryKeys.detail(mockBaseTask.repository_id), {
        id: mockBaseTask.repository_id,
        name: 'test-repo',
        default_branch: 'main',
      });

      renderWithClient(
        <PublicationPanel task={mockBaseTask} workspace={mockValidWorkspace} />,
        client
      );

      fireEvent.click(screen.getByTestId('authorize-publication-checkbox'));
      const publishBtn = screen.getByTestId('authorize-publish-button');

      // Click rapidly twice
      fireEvent.click(publishBtn);
      fireEvent.click(publishBtn);

      await waitFor(() => {
        expect(screen.getByTestId('draft-pr-card')).toBeInTheDocument();
      });

      expect(callCount).toBe(1);
    });
  });

  // ==========================================================================
  // 13. Uncertain publication outcome is handled without blind retries
  // ==========================================================================
  describe('13. Uncertain publication outcome is handled without blind retries', () => {
    it('reconciles existing PR before surfacing retry on uncertain timeout error', async () => {
      // Simulate publish timing out with 504
      server.use(
        http.post('*/api/v1/tasks/:taskId/publish', () => {
          return HttpResponse.json({ error: { message: '504 Gateway Timeout' } }, { status: 504 });
        }),
        // But the PR was actually created on the backend
        http.get('*/api/v1/tasks/:taskId/pull-request', () => {
          return HttpResponse.json({
            task_id: 'task-test-review',
            pr_number: 888,
            pr_url: 'https://github.com/example/repo/pull/888',
            head_branch: 'agent/task-test-review',
            base_branch: 'main',
            is_draft: true,
            created_at: new Date().toISOString(),
            summary: 'Reconciled PR after timeout',
          });
        })
      );

      const client = createTestQueryClient();
      client.setQueryData(taskKeys.verification(mockBaseTask.task_id), mockPassingVerification);
      client.setQueryData(taskKeys.staleCheck(mockBaseTask.task_id), mockPassingStaleCheck);
      client.setQueryData(repositoryKeys.detail(mockBaseTask.repository_id), {
        id: mockBaseTask.repository_id,
        name: 'test-repo',
        default_branch: 'main',
      });

      renderWithClient(
        <PublicationPanel task={mockBaseTask} workspace={mockValidWorkspace} />,
        client
      );

      fireEvent.click(screen.getByTestId('authorize-publication-checkbox'));
      fireEvent.click(screen.getByTestId('authorize-publish-button'));

      // Component reconciles the PR created behind the scenes instead of blindly failing
      await waitFor(() => {
        expect(screen.getByTestId('draft-pr-card')).toBeInTheDocument();
        expect(screen.getByText('#888')).toBeInTheDocument();
      });
    });
  });

  // ==========================================================================
  // 14. Recovery is unavailable when repair budget is exhausted
  // ==========================================================================
  describe('14. Recovery is unavailable when repair budget is exhausted', () => {
    it('hides retry execution button when repair attempts reach max limit', () => {
      const exhaustedTask: TaskDetailResponse = {
        ...mockBaseTask,
        status: TaskStatus.FAILED,
        repair_attempts_used: 3,
        repair_attempts_max: 3,
      };

      const client = createTestQueryClient();
      client.setQueryData(taskKeys.repairBudget(exhaustedTask.task_id), {
        task_id: exhaustedTask.task_id,
        repair_attempts_used: 3,
        repair_attempts_max: 3,
        is_budget_exhausted: true,
        is_eligible_for_repair: false,
      });

      renderWithClient(<RecoveryPanel task={exhaustedTask} />, client);

      expect(screen.getByTestId('recovery-budget-exhausted-banner')).toBeInTheDocument();
      expect(screen.queryByTestId('retry-execution-button')).not.toBeInTheDocument();
      // Reconcile and reset to plan remain available
      expect(screen.getByTestId('reconcile-state-button')).toBeInTheDocument();
      expect(screen.getByTestId('reset-plan-button')).toBeInTheDocument();
    });
  });

  // ==========================================================================
  // 15. Unsupported recovery actions are not displayed
  // ==========================================================================
  describe('15. Unsupported recovery actions are not displayed', () => {
    it('shows only reconcile action for BLOCKED status (no retry, no reset to plan)', () => {
      const blockedTask: TaskDetailResponse = {
        ...mockBaseTask,
        status: TaskStatus.BLOCKED,
      };

      renderWithClient(<RecoveryPanel task={blockedTask} />);

      expect(screen.getByTestId('reconcile-state-button')).toBeInTheDocument();
      expect(screen.queryByTestId('retry-execution-button')).not.toBeInTheDocument();
      expect(screen.queryByTestId('reset-plan-button')).not.toBeInTheDocument();
    });

    it('shows reconcile and reset_to_plan for RECOVERY_REQUIRED status (no retry)', () => {
      const recoveryTask: TaskDetailResponse = {
        ...mockBaseTask,
        status: TaskStatus.RECOVERY_REQUIRED,
      };

      renderWithClient(<RecoveryPanel task={recoveryTask} />);

      expect(screen.getByTestId('reconcile-state-button')).toBeInTheDocument();
      expect(screen.getByTestId('reset-plan-button')).toBeInTheDocument();
      expect(screen.queryByTestId('retry-execution-button')).not.toBeInTheDocument();
    });
  });
});
