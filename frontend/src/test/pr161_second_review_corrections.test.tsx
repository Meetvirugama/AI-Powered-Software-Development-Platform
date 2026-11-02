/**
 * PR #161 Second CodeRabbit Review Corrections Test Suite
 *
 * Verifies all 7 actionable findings from the second CodeRabbit review:
 * A. Publication response without PR URL (reconciles or surfaces clear error)
 * B. Repository metadata fallback (no task.repository_id fallback, disabled when unavailable)
 * C. Repair budget exhaustion banner (authoritative counts from repairBudget)
 * D. Security message redaction for JSON-serialized secrets
 * E. Authorization scheme redaction (no corruption of prose containing 'token')
 * F. VerificationPanel fail-closed behavior
 * G. isPublicationEligible stale-check loading enforcement
 *
 * Plus Mock Handler verifications:
 * H. Verification revision matches workspace base_revision
 * I. Reject stale revisions in /create-pr
 * J. Reject retries after repair budget exhaustion
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor, render } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse, delay } from 'msw';
import { server } from '../mocks/server';
import { resetMockStore, getMockStore, getTaskFromStore } from '../mocks/handlers/task';
import {
  TaskStatus,
  WorkspaceStatus,
  isPublicationEligible,
  type TaskDetailResponse,
  type VerificationResult,
  type WorkspaceMetadata,
  type WorkspaceRepairBudgetStatus,
} from '../types/task';
import { repositoryKeys } from '../hooks/useRepositories';
import { taskKeys } from '../hooks/useTasks';
import { PublicationPanel } from '../components/tasks/PublicationPanel';
import { RecoveryPanel } from '../components/tasks/RecoveryPanel';
import { VerificationPanel } from '../components/tasks/VerificationPanel';
import { SecurityAlertBanner, sanitizeSecurityMessage } from '../components/tasks/SecurityAlertBanner';
import { executeApprovedTask, triggerVerification, recoverTask } from '../services/tasks';
import { apiClient } from '../services/api';

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

function renderWithClient(ui: React.ReactElement, client: QueryClient) {
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const baseTask: TaskDetailResponse = {
  task_id: 'task-test-review-2',
  repository_id: 'repo-test-2',
  title: 'Test Verification & Publication Workflow',
  description: 'Implement secure publication flow',
  status: TaskStatus.READY_FOR_PUBLICATION,
  source: { type: 'USER_PROMPT', repository_id: 'repo-test-2' },
  requirements: [
    {
      id: 'r1',
      description: 'Enforce publication gates',
      category: 'security',
      target_files: ['src/pub.ts'],
      acceptance_criteria: ['PASS verification', 'zero blocking findings'],
    },
  ],
  assumptions: [],
  constraints: [],
  base_revision: 'rev-verified-12345',
  plan_version: 1,
  approved_plan_version: 1,
  repair_attempts_used: 1,
  repair_attempts_max: 3,
  created_at: '2026-11-01T12:00:00Z',
  updated_at: '2026-11-01T12:30:00Z',
};

const passingVerification: VerificationResult = {
  task_id: 'task-test-review-2',
  verified_revision: 'rev-verified-12345',
  status: 'PASS',
  checks: [
    { name: 'test_suite', status: 'PASSED', duration_ms: 500, findings_count: 0, message: 'All tests passed' },
  ],
  blocking_findings: [],
  warnings: [],
  pr_summary: 'All checks passed cleanly.',
  created_at: '2026-11-01T12:30:00Z',
};

const activeWorkspace: WorkspaceMetadata = {
  workspace_id: 'ws-review-2',
  task_id: 'task-test-review-2',
  repository_id: 'repo-test-2',
  branch_name: 'feature/task-review-2',
  base_revision: 'rev-verified-12345',
  workspace_path: '/workspaces/task-review-2',
  status: WorkspaceStatus.READY,
  created_at: '2026-11-01T12:05:00Z',
  updated_at: '2026-11-01T12:30:00Z',
};

describe('PR #161 Second CodeRabbit Review Corrections', () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    resetMockStore();
    queryClient = createTestQueryClient();
    const db = getMockStore();
    db.tasks.set(baseTask.task_id, baseTask);
    db.workspaces.set(baseTask.task_id, activeWorkspace);
    db.verifications.set(baseTask.task_id, passingVerification);
  });

  // ==========================================================================
  // Finding A: Publication response without PR URL
  // ==========================================================================
  describe('A. Publication response without PR URL', () => {
    it('1. Successful response containing pr_url displays Draft PR card', async () => {
      queryClient.setQueryData(taskKeys.verification(baseTask.task_id), passingVerification);
      queryClient.setQueryData(taskKeys.workspace(baseTask.task_id), activeWorkspace);
      queryClient.setQueryData(taskKeys.staleCheck(baseTask.task_id), { is_stale: false, task_id: baseTask.task_id });
      queryClient.setQueryData(repositoryKeys.detail(baseTask.repository_id), {
        id: baseTask.repository_id,
        full_name: 'test-org/test-repo',
        default_branch: 'main',
      });

      server.use(
        http.post('*/api/v1/tasks/:taskId/publish', () => {
          return HttpResponse.json({
            success: true,
            task_id: baseTask.task_id,
            pr_number: 101,
            pr_url: 'https://github.com/test-org/test-repo/pull/101',
            head_branch: 'feature/task-review-2',
            base_branch: 'main',
            is_draft: true,
            summary: 'Publication successful',
          });
        })
      );

      renderWithClient(
        <PublicationPanel task={baseTask} workspace={activeWorkspace} verification={passingVerification} />,
        queryClient
      );

      const checkbox = await screen.findByTestId('authorize-publication-checkbox');
      fireEvent.click(checkbox);

      const button = await screen.findByTestId('authorize-publish-button');
      fireEvent.click(button);

      await waitFor(() => {
        expect(screen.getByTestId('draft-pr-card')).toBeInTheDocument();
      });
      expect(screen.getByText('#101')).toBeInTheDocument();
    });

    it('2. Successful response without pr_url reconciles PR via getTaskPullRequest', async () => {
      queryClient.setQueryData(taskKeys.verification(baseTask.task_id), passingVerification);
      queryClient.setQueryData(taskKeys.workspace(baseTask.task_id), activeWorkspace);
      queryClient.setQueryData(taskKeys.staleCheck(baseTask.task_id), { is_stale: false, task_id: baseTask.task_id });
      queryClient.setQueryData(repositoryKeys.detail(baseTask.repository_id), {
        id: baseTask.repository_id,
        full_name: 'test-org/test-repo',
        default_branch: 'main',
      });

      let published = false;
      server.use(
        http.get('*/api/v1/tasks/:taskId/pull-request', () => {
          if (!published) {
            return HttpResponse.json({ error: { message: 'Not found' } }, { status: 404 });
          }
          return HttpResponse.json({
            task_id: baseTask.task_id,
            pr_number: 202,
            pr_url: 'https://github.com/test-org/test-repo/pull/202',
            title: '[AI Task] Reconciled PR',
            head_branch: 'feature/task-review-2',
            base_branch: 'main',
            is_draft: true,
          });
        }),
        http.post('*/api/v1/tasks/:taskId/publish', () => {
          published = true;
          return HttpResponse.json({
            success: true,
            task_id: baseTask.task_id,
          });
        })
      );

      renderWithClient(
        <PublicationPanel task={baseTask} workspace={activeWorkspace} verification={passingVerification} />,
        queryClient
      );

      const checkbox = await screen.findByTestId('authorize-publication-checkbox');
      fireEvent.click(checkbox);

      const button = await screen.findByTestId('authorize-publish-button');
      fireEvent.click(button);

      await waitFor(() => {
        expect(screen.getByTestId('draft-pr-card')).toBeInTheDocument();
      });
      expect(screen.getByText('#202')).toBeInTheDocument();
    });

    it('3. Successful response without pr_url with no reconciled PR displays clear error', async () => {
      queryClient.setQueryData(taskKeys.verification(baseTask.task_id), passingVerification);
      queryClient.setQueryData(taskKeys.workspace(baseTask.task_id), activeWorkspace);
      queryClient.setQueryData(taskKeys.staleCheck(baseTask.task_id), { is_stale: false, task_id: baseTask.task_id });
      queryClient.setQueryData(repositoryKeys.detail(baseTask.repository_id), {
        id: baseTask.repository_id,
        full_name: 'test-org/test-repo',
        default_branch: 'main',
      });

      server.use(
        http.post('*/api/v1/tasks/:taskId/publish', () => {
          return HttpResponse.json({ success: true, task_id: baseTask.task_id });
        }),
        http.get('*/api/v1/tasks/:taskId/pull-request', () => {
          return HttpResponse.json(
            { error: { code: 'PR_NOT_FOUND', message: 'No PR found' } },
            { status: 404 }
          );
        })
      );

      renderWithClient(
        <PublicationPanel task={baseTask} workspace={activeWorkspace} verification={passingVerification} />,
        queryClient
      );

      const checkbox = await screen.findByTestId('authorize-publication-checkbox');
      fireEvent.click(checkbox);

      const button = await screen.findByTestId('authorize-publish-button');
      fireEvent.click(button);

      await waitFor(() => {
        expect(screen.getByTestId('publication-error-alert')).toBeInTheDocument();
      });
      expect(
        screen.getByText(/Publication request completed without returning a Pull Request URL/i)
      ).toBeInTheDocument();
    });

    it('4. Failed reconciliation request displays clear error alert', async () => {
      queryClient.setQueryData(taskKeys.verification(baseTask.task_id), passingVerification);
      queryClient.setQueryData(taskKeys.workspace(baseTask.task_id), activeWorkspace);
      queryClient.setQueryData(taskKeys.staleCheck(baseTask.task_id), { is_stale: false, task_id: baseTask.task_id });
      queryClient.setQueryData(repositoryKeys.detail(baseTask.repository_id), {
        id: baseTask.repository_id,
        full_name: 'test-org/test-repo',
        default_branch: 'main',
      });

      server.use(
        http.post('*/api/v1/tasks/:taskId/publish', () => {
          return HttpResponse.json({ success: true });
        }),
        http.get('*/api/v1/tasks/:taskId/pull-request', () => {
          return HttpResponse.json({ error: { message: 'Network error during reconciliation' } }, { status: 500 });
        })
      );

      renderWithClient(
        <PublicationPanel task={baseTask} workspace={activeWorkspace} verification={passingVerification} />,
        queryClient
      );

      const checkbox = await screen.findByTestId('authorize-publication-checkbox');
      fireEvent.click(checkbox);

      const button = await screen.findByTestId('authorize-publish-button');
      fireEvent.click(button);

      await waitFor(() => {
        expect(screen.getByTestId('publication-error-alert')).toBeInTheDocument();
      });
    });
  });

  // ==========================================================================
  // Finding B: Repository metadata fallback
  // ==========================================================================
  describe('B. Repository metadata fallback', () => {
    it('1. Derives target repo from repository.full_name without falling back to repository_id', async () => {
      queryClient.setQueryData(taskKeys.verification(baseTask.task_id), passingVerification);
      queryClient.setQueryData(taskKeys.workspace(baseTask.task_id), activeWorkspace);
      queryClient.setQueryData(taskKeys.staleCheck(baseTask.task_id), { is_stale: false, task_id: baseTask.task_id });
      queryClient.setQueryData(repositoryKeys.detail(baseTask.repository_id), {
        id: baseTask.repository_id,
        full_name: 'acme-corp/quantum-compiler',
        default_branch: 'develop',
      });

      renderWithClient(
        <PublicationPanel task={baseTask} workspace={activeWorkspace} verification={passingVerification} />,
        queryClient
      );

      const repoDisplay = await screen.findByTestId('target-repo-display');
      expect(repoDisplay).toHaveTextContent('acme-corp/quantum-compiler');
      expect(repoDisplay).not.toHaveTextContent(baseTask.repository_id);
    });

    it('2. When repository metadata is unavailable, displays Unavailable and keeps controls disabled', async () => {
      queryClient.setQueryData(taskKeys.verification(baseTask.task_id), passingVerification);
      queryClient.setQueryData(taskKeys.workspace(baseTask.task_id), activeWorkspace);
      queryClient.setQueryData(taskKeys.staleCheck(baseTask.task_id), { is_stale: false, task_id: baseTask.task_id });

      server.use(
        http.get('*/api/v1/repositories/:repoId', () => {
          return HttpResponse.json({ error: { message: 'Repository not found' } }, { status: 404 });
        })
      );

      renderWithClient(
        <PublicationPanel task={baseTask} workspace={activeWorkspace} verification={passingVerification} />,
        queryClient
      );

      await waitFor(() => {
        expect(screen.getByTestId('missing-metadata-alert')).toBeInTheDocument();
      });

      const repoDisplay = screen.getByTestId('target-repo-display');
      await waitFor(() => {
        expect(repoDisplay).toHaveTextContent('Unavailable');
      });
      expect(repoDisplay).not.toHaveTextContent(baseTask.repository_id);

      const checkbox = screen.getByTestId('authorize-publication-checkbox');
      expect(checkbox).toBeDisabled();

      const button = screen.getByTestId('authorize-publish-button');
      expect(button).toBeDisabled();
    });

    it('3. Delayed repository metadata loading shows loading state and keeps controls disabled', async () => {
      queryClient.setQueryData(taskKeys.verification(baseTask.task_id), passingVerification);
      queryClient.setQueryData(taskKeys.workspace(baseTask.task_id), activeWorkspace);
      queryClient.setQueryData(taskKeys.staleCheck(baseTask.task_id), { is_stale: false, task_id: baseTask.task_id });

      server.use(
        http.get('*/api/v1/repositories/:repoId', async () => {
          await delay(200);
          return HttpResponse.json({
            id: baseTask.repository_id,
            full_name: 'delayed-org/delayed-repo',
            default_branch: 'main',
          });
        })
      );

      renderWithClient(
        <PublicationPanel task={baseTask} workspace={activeWorkspace} verification={passingVerification} />,
        queryClient
      );

      // Loading state in target repo display
      const repoDisplay = screen.getByTestId('target-repo-display');
      expect(repoDisplay).toHaveTextContent(/Loading/i);

      const checkbox = screen.getByTestId('authorize-publication-checkbox');
      expect(checkbox).toBeDisabled();

      // After resolving, displays repository name
      await waitFor(() => {
        expect(screen.getByTestId('target-repo-display')).toHaveTextContent('delayed-org/delayed-repo');
      });
    });
  });

  // ==========================================================================
  // Finding C: Repair budget exhaustion message
  // ==========================================================================
  describe('C. Repair budget exhaustion message', () => {
    it('prefers authoritative repairBudget counts over task counts when they differ', async () => {
      const taskWithLowCount: TaskDetailResponse = {
        ...baseTask,
        status: TaskStatus.FAILED,
        repair_attempts_used: 1,
        repair_attempts_max: 3,
      };

      const authoritativeBudget: WorkspaceRepairBudgetStatus = {
        task_id: taskWithLowCount.task_id,
        repair_attempts_used: 5,
        repair_attempts_max: 5,
        is_budget_exhausted: true,
        is_eligible_for_repair: false,
      };

      queryClient.setQueryData(taskKeys.repairBudget(taskWithLowCount.task_id), authoritativeBudget);

      renderWithClient(<RecoveryPanel task={taskWithLowCount} />, queryClient);

      const banner = await screen.findByTestId('recovery-budget-exhausted-banner');
      expect(banner).toHaveTextContent('Automated repair attempts limit reached (5/5). Retrying is unavailable.');
      expect(banner).not.toHaveTextContent('1/3');
      expect(screen.queryByTestId('retry-execution-button')).not.toBeInTheDocument();
    });

    it('falls back to task counts when repairBudget is unavailable', async () => {
      const taskExhausted: TaskDetailResponse = {
        ...baseTask,
        status: TaskStatus.FAILED,
        repair_attempts_used: 4,
        repair_attempts_max: 4,
      };

      server.use(
        http.get('*/api/v1/tasks/:taskId/repair-budget', () => {
          return HttpResponse.json({ error: { message: 'Not found' } }, { status: 404 });
        })
      );

      renderWithClient(<RecoveryPanel task={taskExhausted} />, queryClient);

      const banner = await screen.findByTestId('recovery-budget-exhausted-banner');
      expect(banner).toHaveTextContent('Automated repair attempts limit reached (4/4). Retrying is unavailable.');
    });
  });

  // ==========================================================================
  // Finding D & E: Security message redaction
  // ==========================================================================
  describe('D & E. Security message redaction', () => {
    it('D1. Redacts JSON-serialized secrets properly', () => {
      expect(sanitizeSecurityMessage('{"password":"secretPassword123"}')).toBe('{"password":"[REDACTED]"}');
      expect(sanitizeSecurityMessage('{"token":"sensitiveTokenXYZ"}')).toBe('{"token":"[REDACTED]"}');
      expect(sanitizeSecurityMessage('{"api_key":"super-secret-key-456"}')).toBe('{"api_key":"[REDACTED]"}');
      expect(sanitizeSecurityMessage('{"access_token":"tokenA","private_key":"keyB"}')).toBe(
        '{"access_token":"[REDACTED]","private_key":"[REDACTED]"}'
      );
    });

    it('D2. Unquoted values stop at JSON closing braces and brackets', () => {
      expect(sanitizeSecurityMessage('{"token":123456}')).toBe('{"token":[REDACTED]}');
      expect(sanitizeSecurityMessage('{"password":secretValue}')).toBe('{"password":[REDACTED]}');
      expect(sanitizeSecurityMessage('{"token":unquotedSecret, "other":1}')).toBe('{"token":[REDACTED], "other":1}');
    });

    it('E1. Does not corrupt ordinary prose mentioning token', () => {
      const prose = 'Blocked token exfiltration attempt during test execution';
      expect(sanitizeSecurityMessage(prose)).toBe(prose);
    });

    it('E2. Redacts Bearer and Basic authentication headers accurately', () => {
      expect(sanitizeSecurityMessage('Authorization: Bearer my-jwt-secret-token')).toBe(
        'Authorization: Bearer [REDACTED_TOKEN]'
      );
      expect(sanitizeSecurityMessage('Authorization: Basic dXNlcjpwYXNzd29yZA==')).toBe(
        'Authorization: Basic [REDACTED_TOKEN]'
      );
    });

    it('E3. SecurityAlertBanner renders sanitized JSON secret safely', () => {
      render(
        <SecurityAlertBanner
          events={[
            {
              id: 'sec-1',
              task_id: 't-1',
              event_type: 'UNAUTHORIZED_OPERATION',
              description: 'Blocked unauthorized payload containing {"password":"mySecret123"}',
              created_at: '2026-11-01T12:00:00Z',
            },
          ]}
        />
      );

      const banner = screen.getByTestId('security-alert-banner');
      expect(banner).toHaveTextContent('{"password":"[REDACTED]"}');
      expect(banner).not.toHaveTextContent('mySecret123');
    });

    describe('Compound secret-key redaction (10 mandatory test scenarios)', () => {
      it('1. Redacts unquoted refresh_token', () => {
        expect(sanitizeSecurityMessage('refresh_token=abc')).toBe('refresh_token=[REDACTED]');
      });

      it('2. Redacts quoted client_secret', () => {
        expect(sanitizeSecurityMessage('client_secret: "abc"')).toBe('client_secret: "[REDACTED]"');
      });

      it('3. Redacts JSON-serialized secret_key', () => {
        expect(sanitizeSecurityMessage('{"secret_key":"abc"}')).toBe('{"secret_key":"[REDACTED]"}');
      });

      it('4. Redacts JSON-serialized refresh_token', () => {
        expect(sanitizeSecurityMessage('{"refresh_token":"abc"}')).toBe('{"refresh_token":"[REDACTED]"}');
      });

      it('5. Redacts access_token key-value pair', () => {
        expect(sanitizeSecurityMessage('access_token=abc')).toBe('access_token=[REDACTED]');
      });

      it('6. Redacts private_key key-value pair', () => {
        expect(sanitizeSecurityMessage('private_key=abc')).toBe('private_key=[REDACTED]');
      });

      it('7. Redacts multiple compound secrets in one message preserving delimiters', () => {
        expect(
          sanitizeSecurityMessage('refresh_token=123, client_secret="456", secret_key=789')
        ).toBe('refresh_token=[REDACTED], client_secret="[REDACTED]", secret_key=[REDACTED]');
      });

      it('8. Preserves ordinary prose containing the word token', () => {
        expect(sanitizeSecurityMessage('Blocked token exfiltration attempt')).toBe(
          'Blocked token exfiltration attempt'
        );
        expect(sanitizeSecurityMessage('The user requested a token refresh cycle')).toBe(
          'The user requested a token refresh cycle'
        );
      });

      it('9. Redacts Bearer and Basic authorization credentials accurately', () => {
        expect(sanitizeSecurityMessage('Authorization: Bearer secretTokenABC')).toBe(
          'Authorization: Bearer [REDACTED_TOKEN]'
        );
        expect(sanitizeSecurityMessage('Authorization: Basic dXNlcjpwYXNz')).toBe(
          'Authorization: Basic [REDACTED_TOKEN]'
        );
      });

      it('10. Handles malformed or incomplete inputs safely without crashing', () => {
        expect(sanitizeSecurityMessage(null)).toBe(
          'Security policy enforcement blocked the requested operation.'
        );
        expect(sanitizeSecurityMessage(undefined)).toBe(
          'Security policy enforcement blocked the requested operation.'
        );
        expect(sanitizeSecurityMessage('')).toBe(
          'Security policy enforcement blocked the requested operation.'
        );
        expect(sanitizeSecurityMessage('   ')).toBe(
          'Security policy enforcement blocked the requested operation.'
        );
        expect(sanitizeSecurityMessage('malformed refresh_token=')).toBe('malformed refresh_token=');
      });
    });
  });

  // ==========================================================================
  // Finding F: VerificationPanel must fail closed
  // ==========================================================================
  describe('F. VerificationPanel must fail closed', () => {
    it('1. Shows checking state and never Publication Eligible while stale-check is loading', async () => {
      queryClient.setQueryData(taskKeys.verification(baseTask.task_id), passingVerification);

      server.use(
        http.get('*/api/v1/tasks/:taskId/stale-check', async () => {
          await delay(200);
          return HttpResponse.json({ is_stale: false, task_id: baseTask.task_id });
        })
      );

      renderWithClient(<VerificationPanel taskId={baseTask.task_id} />, queryClient);

      const verdict = await screen.findByTestId('publication-eligibility-verdict');
      expect(verdict).toHaveTextContent(/Publication Eligibility Pending — Checking Revision Freshness/i);
      expect(verdict).not.toHaveTextContent('Publication Eligible — Independent Verification Passed');
    });

    it('2. Shows blocked state when stale-check API encounters an error', async () => {
      queryClient.setQueryData(taskKeys.verification(baseTask.task_id), passingVerification);

      server.use(
        http.get('*/api/v1/tasks/:taskId/stale-check', () => {
          return HttpResponse.json({ error: { message: 'Internal Server Error' } }, { status: 500 });
        })
      );

      renderWithClient(<VerificationPanel taskId={baseTask.task_id} />, queryClient);

      const verdict = await screen.findByTestId('publication-eligibility-verdict');
      await waitFor(() => {
        expect(verdict).toHaveTextContent(/Publication Blocked — Revision Freshness Check Failed/i);
      });
      expect(verdict).not.toHaveTextContent('Publication Eligible — Independent Verification Passed');
    });

    it('3. Shows blocked state when verification is stale', async () => {
      server.use(
        http.get('*/api/v1/tasks/:taskId/stale-check', () => {
          return HttpResponse.json({ is_stale: true, task_id: baseTask.task_id, reason: 'Drift detected' });
        }),
        http.get('*/api/v1/tasks/:taskId/verification', () => {
          return HttpResponse.json(passingVerification);
        })
      );

      queryClient.setQueryData(taskKeys.verification(baseTask.task_id), passingVerification);
      queryClient.setQueryData(taskKeys.staleCheck(baseTask.task_id), { is_stale: true, task_id: baseTask.task_id });

      renderWithClient(<VerificationPanel taskId={baseTask.task_id} />, queryClient);

      const verdict = await screen.findByTestId('publication-eligibility-verdict');
      await waitFor(() => {
        expect(verdict).toHaveTextContent(/Publication Blocked — Verification Incomplete or Failed/i);
      });
      expect(verdict).not.toHaveTextContent('Publication Eligible — Independent Verification Passed');
    });

    it('4. Shows Publication Eligible on fresh result with passing verification', async () => {
      server.use(
        http.get('*/api/v1/tasks/:taskId/verification', () => {
          return HttpResponse.json(passingVerification);
        }),
        http.get('*/api/v1/tasks/:taskId/stale-check', () => {
          return HttpResponse.json({ is_stale: false, task_id: baseTask.task_id });
        })
      );

      queryClient.setQueryData(taskKeys.verification(baseTask.task_id), passingVerification);
      queryClient.setQueryData(taskKeys.staleCheck(baseTask.task_id), { is_stale: false, task_id: baseTask.task_id });

      renderWithClient(<VerificationPanel taskId={baseTask.task_id} />, queryClient);

      const verdict = await screen.findByTestId('publication-eligibility-verdict');
      await waitFor(() => {
        expect(verdict).toHaveTextContent('Publication Eligible — Independent Verification Passed');
      });
    });

    it('5. Shows empty state when verification is missing', async () => {
      server.use(
        http.get('*/api/v1/tasks/:taskId/verification', () => {
          return HttpResponse.json({ error: { message: 'Not found' } }, { status: 404 });
        }),
        http.get('*/api/v1/tasks/:taskId/stale-check', () => {
          return HttpResponse.json({ is_stale: false, task_id: baseTask.task_id });
        })
      );

      renderWithClient(<VerificationPanel taskId="task-nonexistent-999" />, queryClient);

      await waitFor(() => {
        expect(screen.getByText('Verification Not Yet Run')).toBeInTheDocument();
      });
      expect(screen.queryByTestId('publication-eligibility-verdict')).not.toBeInTheDocument();
    });

    it('6. Shows blocked state when blocking findings exist', async () => {
      const verifWithBlocking: VerificationResult = {
        ...passingVerification,
        blocking_findings: [
          {
            id: 'b-1',
            severity: 'CRITICAL',
            category: 'security',
            blocking: true,
            message: 'SQL Injection detected',
          },
        ],
      };

      server.use(
        http.get('*/api/v1/tasks/:taskId/verification', () => {
          return HttpResponse.json(verifWithBlocking);
        }),
        http.get('*/api/v1/tasks/:taskId/stale-check', () => {
          return HttpResponse.json({ is_stale: false, task_id: baseTask.task_id });
        })
      );

      queryClient.setQueryData(taskKeys.verification(baseTask.task_id), verifWithBlocking);
      queryClient.setQueryData(taskKeys.staleCheck(baseTask.task_id), { is_stale: false, task_id: baseTask.task_id });

      renderWithClient(<VerificationPanel taskId={baseTask.task_id} />, queryClient);

      const verdict = await screen.findByTestId('publication-eligibility-verdict');
      await waitFor(() => {
        expect(verdict).toHaveTextContent(/Publication Blocked — Verification Incomplete or Failed/i);
      });
      expect(verdict).not.toHaveTextContent('Publication Eligible — Independent Verification Passed');
    });
  });

  // Finding G: isPublicationEligible stale-check loading enforcement
  // ==========================================================================
  describe('G. isPublicationEligible stale-check loading enforcement', () => {
    it('returns false when isStaleCheckLoading is true in object form', () => {
      const eligible = isPublicationEligible({
        status: TaskStatus.READY_FOR_PUBLICATION,
        verification: passingVerification,
        isStale: false,
        isStaleCheckLoading: true,
      });
      expect(eligible).toBe(false);
    });

    it('returns true when isStaleCheckLoading is false in object form', () => {
      const eligible = isPublicationEligible({
        status: TaskStatus.READY_FOR_PUBLICATION,
        verification: passingVerification,
        isStale: false,
        isStaleCheckLoading: false,
      });
      expect(eligible).toBe(true);
    });

    it('returns false when isStaleCheckLoading is true in options argument form', () => {
      const eligible = isPublicationEligible(
        TaskStatus.READY_FOR_PUBLICATION,
        passingVerification,
        false,
        false,
        false,
        { isStaleCheckLoading: true }
      );
      expect(eligible).toBe(false);
    });

    it('returns true when isStaleCheckLoading is false in options argument form', () => {
      const eligible = isPublicationEligible(
        TaskStatus.READY_FOR_PUBLICATION,
        passingVerification,
        false,
        false,
        false,
        { isStaleCheckLoading: false }
      );
      expect(eligible).toBe(true);
    });
  });

  // ==========================================================================
  // Mock Handlers: Findings H, I, J
  // ==========================================================================
  describe('Mock Handlers H, I, J', () => {
    it('H1. /verify derives verified_revision from workspace base_revision when task base_revision is null', async () => {
      const task = getTaskFromStore('task-seed-2');
      if (task) {
        task.base_revision = undefined as any;
      }
      const db = getMockStore();
      db.workspaces.delete('task-seed-2');

      // Execute approved task task-seed-2 (which now has null base_revision)
      await executeApprovedTask('task-seed-2');

      // Trigger verification
      const verifyRes = await triggerVerification('task-seed-2', { force_reverify: true });
      expect(verifyRes?.verified_revision).toBe('a1b2c3d4e5f6');
    });

    it('H2. /verify uses explicitly provided base_revision', async () => {
      const db = getMockStore();
      const workspace = db.workspaces.get('task-scenario-pub-ready');
      if (workspace) {
        workspace.base_revision = 'rev-explicit-888';
      }

      const verifyRes = await triggerVerification('task-scenario-pub-ready', { force_reverify: true });
      expect(verifyRes?.verified_revision).toBe('rev-explicit-888');

      // Also verify task-level fallback when workspace is absent
      const task = getTaskFromStore('task-test-review-2');
      if (task) {
        task.base_revision = 'rev-task-fallback-999';
      }
      db.workspaces.delete('task-test-review-2');
      const verifyRes2 = await triggerVerification('task-test-review-2', { force_reverify: true });
      expect(verifyRes2?.verified_revision).toBe('rev-task-fallback-999');
    });

    it('I1. /create-pr rejects stale revisions with 409 STALE_REVISION and creates no PR', async () => {
      let threw = false;
      try {
        await apiClient.post('/tasks/task-scenario-stale/create-pr', {
          publication_authorized: true,
        });
      } catch (err: any) {
        threw = true;
        expect(err.response?.status || err.status_code || err.status).toBe(409);
        expect(err.response?.data?.error?.code || err.error?.code || err.code).toBe('STALE_REVISION');
      }
      expect(threw).toBe(true);

      const db = getMockStore();
      expect(db.pullRequests.get('task-scenario-stale')).toBeUndefined();
    });

    it('I2. /create-pr succeeds on fresh revisions with authorized flag', async () => {
      const res = await apiClient.post<any>('/tasks/task-scenario-pub-ready/create-pr', {
        publication_authorized: true,
      });
      expect([200, 201]).toContain(res.status);
      expect(res.data.success).toBe(true);
      expect(res.data.pr_url).toBeDefined();
    });

    it('J1. /recover allows retry when repair attempts remain', async () => {
      const task = getTaskFromStore('task-exec-repair-history');
      if (task) {
        task.status = TaskStatus.FAILED;
      }

      const res = await recoverTask('task-exec-repair-history', { action: 'retry', reason: 'User retry' });
      expect(res.current_status).toBe(TaskStatus.EXECUTING);
    });

    it('J2. /recover rejects retry when attempt count is exhausted', async () => {
      const task = getTaskFromStore('task-exec-budget-exhausted');
      if (task) {
        task.status = TaskStatus.FAILED;
        task.repair_attempts_used = 3;
        task.repair_attempts_max = 3;
      }

      let threw = false;
      try {
        await recoverTask('task-exec-budget-exhausted', { action: 'retry', reason: 'User retry' });
      } catch (err: any) {
        threw = true;
        expect(err.status_code || err.response?.status || err.status).toBe(409);
      }
      expect(threw).toBe(true);
    });

    it('J3. /recover rejects retry when is_budget_exhausted is true', async () => {
      const task = getTaskFromStore('task-exec-budget-exhausted');
      if (task) {
        task.status = TaskStatus.FAILED;
      }
      let threw = false;
      try {
        await recoverTask('task-exec-budget-exhausted', { action: 'retry' });
      } catch (err: any) {
        threw = true;
        expect(err.status_code || err.response?.status || err.status).toBe(409);
      }
      expect(threw).toBe(true);
    });

    it('J4. /recover rejects retry when is_eligible_for_repair is false and leaves task status unchanged', async () => {
      const task = getTaskFromStore('task-exec-budget-exhausted');
      if (task) {
        task.status = TaskStatus.FAILED;
      }
      const initialStatus = task?.status;

      let threw = false;
      try {
        await recoverTask('task-exec-budget-exhausted', { action: 'retry' });
      } catch (err: any) {
        threw = true;
        expect(err.status_code || err.response?.status || err.status).toBe(409);
      }
      expect(threw).toBe(true);
      expect(task?.status).toBe(initialStatus);
    });

    it('J5. Non-retry recovery actions (reconcile, reset_to_plan) remain functional when budget exhausted', async () => {
      const task = getTaskFromStore('task-exec-budget-exhausted');
      if (task) {
        task.status = TaskStatus.FAILED;
      }

      const resReconcile = await recoverTask('task-exec-budget-exhausted', { action: 'reconcile' });
      expect(resReconcile.current_status).toBe(TaskStatus.EXECUTING);

      // Reset another failed task
      const task2 = getTaskFromStore('task-scenario-recovery-req');
      if (task2) {
        task2.status = TaskStatus.RECOVERY_REQUIRED;
      }

      const resReset = await recoverTask('task-scenario-recovery-req', { action: 'reset_to_plan' });
      expect(resReset.current_status).toBe(TaskStatus.APPROVED);
    });
  });
});
