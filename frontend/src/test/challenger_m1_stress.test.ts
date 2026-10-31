/**
 * Empirical Challenger Stress Test Suite for Milestone 1.
 *
 * Focus areas:
 * 1. Plan version mismatch handling (409 PLAN_VERSION_MISMATCH).
 * 2. Strict state transition enforcement for plan approval & rejection (409 INVALID_STATE_TRANSITION).
 * 3. Plan revision lifecycle: version increment, approval invalidation, audit logging.
 * 4. Input validation and security checks in task intake (422 INVALID_REQUEST for traversal & forbidden overlaps).
 * 5. Comprehensive Week 3 and legacy Week 2 error normalization in normaliseError().
 * 6. Concurrency and boundary stress testing (duplicate issue import, boundary title lengths, pagination).
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios';
import { apiClient, normaliseError } from '../services/api';
import {
  createTask,
  listTasks,
  getTask,
  getTaskPlan,
  generateTaskPlan,
  approveTaskPlan,
  rejectTaskPlan,
  getTaskEvents,
  importGitHubIssue,
} from '../services/tasks';
import {
  TaskStatus,
  type TaskCreateRequest,
} from '../types/task';
import type { ApiError } from '../types/api';
import { resetMockStore } from '../mocks/handlers';

const DEFAULT_REPO_ID = 'repo-1';

function toApiError(err: unknown): ApiError {
  if (err && typeof err === 'object' && 'code' in err && 'status' in err) {
    return err as ApiError;
  }
  return normaliseError(err);
}

function createMockAxiosError(
  status?: number,
  data?: unknown,
  code?: string,
  message?: string
): AxiosError {
  const config = { headers: {} } as InternalAxiosRequestConfig;
  const response = status
    ? ({
        data,
        status,
        statusText: String(status),
        headers: {},
        config,
      } as AxiosResponse)
    : undefined;

  return new AxiosError(message || 'Error occurred', code, config, {}, response);
}

describe('Challenger Stress Tests — Milestone 1 MSW Mock Engine', () => {
  beforeEach(() => {
    resetMockStore();
  });

  // ==========================================================================
  // Dimension 1: Stale plan_version and Concurrency Detection
  // ==========================================================================
  describe('Dimension 1: Stale plan_version Verification', () => {
    it('reliably returns 409 PLAN_VERSION_MISMATCH when approving with stale plan_version 0', async () => {
      // task-seed-1 is in PENDING_APPROVAL with plan_version 1
      try {
        await approveTaskPlan('task-seed-1', {
          plan_version: 0,
          notes: 'Attempting to approve with stale version 0',
        });
        expect.unreachable('Expected approveTaskPlan to fail with 409 PLAN_VERSION_MISMATCH');
      } catch (err) {
        const apiError = toApiError(err);
        expect(apiError.status).toBe(409);
        expect(apiError.code).toBe('PLAN_VERSION_MISMATCH');
        expect(apiError.message).toContain('plan has been revised');
        expect(apiError.retryable).toBe(false);
        expect(apiError.details).toBeDefined();
        expect((apiError.details as any).submitted_version).toBe(0);
        expect((apiError.details as any).current_version).toBe(1);
      }
    });

    it('reliably returns 409 PLAN_VERSION_MISMATCH when approving with future plan_version 99', async () => {
      try {
        await approveTaskPlan('task-seed-1', {
          plan_version: 99,
          notes: 'Attempting to approve with future version 99',
        });
        expect.unreachable('Expected approveTaskPlan to fail with 409');
      } catch (err) {
        const apiError = toApiError(err);
        expect(apiError.status).toBe(409);
        expect(apiError.code).toBe('PLAN_VERSION_MISMATCH');
      }
    });

    it('reliably returns 409 PLAN_VERSION_MISMATCH when rejecting with stale plan_version', async () => {
      try {
        await rejectTaskPlan('task-seed-1', {
          plan_version: 42,
          reason: 'Stale version rejection test',
        });
        expect.unreachable('Expected rejectTaskPlan to fail with 409 PLAN_VERSION_MISMATCH');
      } catch (err) {
        const apiError = toApiError(err);
        expect(apiError.status).toBe(409);
        expect(apiError.code).toBe('PLAN_VERSION_MISMATCH');
        expect(apiError.details).toBeDefined();
        expect((apiError.details as any).submitted_version).toBe(42);
        expect((apiError.details as any).current_version).toBe(1);
      }
    });

    it('reliably returns 409 PLAN_VERSION_MISMATCH after plan is revised from v1 to v2 and client submits v1', async () => {
      // 1. Task seed 1 is at v1
      // 2. Revise plan to v2
      const revisedPlan = await generateTaskPlan('task-seed-1', {
        regenerate: true,
        prompt_instructions: 'Add defensive memory limits to AST walker',
      });
      expect(revisedPlan.plan_version).toBe(2);

      // 3. Try to approve with stale v1
      try {
        await approveTaskPlan('task-seed-1', {
          plan_version: 1,
          notes: 'Approving stale v1',
        });
        expect.unreachable('Expected approveTaskPlan to fail with 409 PLAN_VERSION_MISMATCH');
      } catch (err) {
        const apiError = toApiError(err);
        expect(apiError.status).toBe(409);
        expect(apiError.code).toBe('PLAN_VERSION_MISMATCH');
        expect((apiError.details as any).submitted_version).toBe(1);
        expect((apiError.details as any).current_version).toBe(2);
      }

      // 4. Approve with exact v2 succeeds
      const approvedTask = await approveTaskPlan('task-seed-1', {
        plan_version: 2,
        notes: 'Approving fresh v2 plan',
      });
      expect(approvedTask.status).toBe(TaskStatus.APPROVED);
      expect(approvedTask.approved_plan_version).toBe(2);
    });
  });

  // ==========================================================================
  // Dimension 2: State Transitions & Lifecycle Guardrails
  // ==========================================================================
  describe('Dimension 2: State Transition Guardrails', () => {
    it('returns 409 INVALID_STATE_TRANSITION when approving a task in CREATED status', async () => {
      // task-seed-3 is in CREATED status
      const task = await getTask('task-seed-3');
      expect(task.status).toBe(TaskStatus.CREATED);

      try {
        await approveTaskPlan('task-seed-3', { plan_version: 1 });
        expect.unreachable('Expected approveTaskPlan to fail from CREATED status');
      } catch (err) {
        const apiError = toApiError(err);
        expect(apiError.status).toBe(409);
        expect(apiError.code).toBe('INVALID_STATE_TRANSITION');
        expect(apiError.message).toContain("Cannot approve plan from status 'CREATED'");
      }
    });

    it('returns 409 INVALID_STATE_TRANSITION when approving a task in REJECTED status', async () => {
      // task-seed-4 is in REJECTED status
      const task = await getTask('task-seed-4');
      expect(task.status).toBe(TaskStatus.REJECTED);

      try {
        await approveTaskPlan('task-seed-4', { plan_version: 1 });
        expect.unreachable('Expected approveTaskPlan to fail from REJECTED status');
      } catch (err) {
        const apiError = toApiError(err);
        expect(apiError.status).toBe(409);
        expect(apiError.code).toBe('INVALID_STATE_TRANSITION');
        expect(apiError.message).toContain("Cannot approve plan from status 'REJECTED'");
      }
    });

    it('returns 409 INVALID_STATE_TRANSITION when approving a task already in APPROVED status', async () => {
      // task-seed-2 is already APPROVED
      const task = await getTask('task-seed-2');
      expect(task.status).toBe(TaskStatus.APPROVED);

      try {
        await approveTaskPlan('task-seed-2', { plan_version: 1 });
        expect.unreachable('Expected double approval to fail');
      } catch (err) {
        const apiError = toApiError(err);
        expect(apiError.status).toBe(409);
        expect(apiError.code).toBe('INVALID_STATE_TRANSITION');
      }
    });

    it('returns 409 INVALID_STATE_TRANSITION when approving a task in EXECUTING status', async () => {
      // task-seed-5 is in EXECUTING status
      try {
        await approveTaskPlan('task-seed-5', { plan_version: 1 });
        expect.unreachable('Expected approval to fail from EXECUTING status');
      } catch (err) {
        const apiError = toApiError(err);
        expect(apiError.status).toBe(409);
        expect(apiError.code).toBe('INVALID_STATE_TRANSITION');
      }
    });

    it('returns 409 INVALID_STATE_TRANSITION when approving a task in FAILED status', async () => {
      // task-seed-7 is in FAILED status
      try {
        await approveTaskPlan('task-seed-7', { plan_version: 1 });
        expect.unreachable('Expected approval to fail from FAILED status');
      } catch (err) {
        const apiError = toApiError(err);
        expect(apiError.status).toBe(409);
        expect(apiError.code).toBe('INVALID_STATE_TRANSITION');
      }
    });

    it('returns 409 INVALID_STATE_TRANSITION when rejecting a task in CREATED or APPROVED status', async () => {
      try {
        await rejectTaskPlan('task-seed-3', { plan_version: 1, reason: 'Rejecting CREATED task' });
        expect.unreachable('Expected rejectTaskPlan to fail from CREATED status');
      } catch (err) {
        const apiError = toApiError(err);
        expect(apiError.status).toBe(409);
        expect(apiError.code).toBe('INVALID_STATE_TRANSITION');
      }

      try {
        await rejectTaskPlan('task-seed-2', { plan_version: 1, reason: 'Rejecting APPROVED task' });
        expect.unreachable('Expected rejectTaskPlan to fail from APPROVED status');
      } catch (err) {
        const apiError = toApiError(err);
        expect(apiError.status).toBe(409);
        expect(apiError.code).toBe('INVALID_STATE_TRANSITION');
      }
    });

    it('returns 409 APPROVAL_REQUIRED when executing a task in PENDING_APPROVAL status', async () => {
      try {
        await apiClient.post('/tasks/task-seed-1/execute');
        expect.unreachable('Expected execution dispatch to fail for unapproved task');
      } catch (err) {
        const apiError = toApiError(err);
        expect(apiError.status).toBe(409);
        expect(apiError.code).toBe('APPROVAL_REQUIRED');
        expect(apiError.message).toContain('Human approval of the plan is required');
      }
    });

    it('returns 409 INVALID_STATE_TRANSITION when executing a task in CREATED status', async () => {
      try {
        await apiClient.post('/tasks/task-seed-3/execute');
        expect.unreachable('Expected execution dispatch to fail for CREATED task');
      } catch (err) {
        const apiError = toApiError(err);
        expect(apiError.status).toBe(409);
        expect(apiError.code).toBe('INVALID_STATE_TRANSITION');
      }
    });
  });

  // ==========================================================================
  // Dimension 3: Plan Revision Lifecycle & Approval Invalidation
  // ==========================================================================
  describe('Dimension 3: Plan Revision Lifecycle & Approval Invalidation', () => {
    it('revising an APPROVED task resets approved_plan_version, increments plan_version, and records audit event', async () => {
      // 1. task-seed-2 is APPROVED, version 1, approved_plan_version 1
      const initialTask = await getTask('task-seed-2');
      expect(initialTask.status).toBe(TaskStatus.APPROVED);
      expect(initialTask.plan_version).toBe(1);
      expect(initialTask.approved_plan_version).toBe(1);

      // 2. Revise plan
      const revisedPlan = await generateTaskPlan('task-seed-2', {
        prompt_instructions: 'Incorporate decorator argument type checks',
      });
      expect(revisedPlan.plan_version).toBe(2);
      expect(revisedPlan.status).toBe('PENDING_APPROVAL');

      // 3. Inspect updated task state
      const updatedTask = await getTask('task-seed-2');
      expect(updatedTask.status).toBe(TaskStatus.PENDING_APPROVAL);
      expect(updatedTask.plan_version).toBe(2);
      expect(updatedTask.approved_plan_version).toBeNull(); // Approval MUST be invalidated!

      // 4. Verify executing now returns 409 APPROVAL_REQUIRED
      try {
        await apiClient.post('/tasks/task-seed-2/execute');
        expect.unreachable('Expected execution to fail on unapproved revised plan');
      } catch (err) {
        const apiError = toApiError(err);
        expect(apiError.status).toBe(409);
        expect(apiError.code).toBe('APPROVAL_REQUIRED');
      }

      // 5. Verify plan history preservation: version 1 still accessible, active is version 2
      const planV1 = await getTaskPlan('task-seed-2', 1);
      expect(planV1.plan_version).toBe(1);

      const activePlan = await getTaskPlan('task-seed-2');
      expect(activePlan.plan_version).toBe(2);

      // 6. Verify audit timeline includes PLAN_REVISED
      const eventsRes = await getTaskEvents('task-seed-2');
      const revisedEvent = eventsRes.items.find((e) => e.event_type === 'PLAN_REVISED');
      expect(revisedEvent).toBeDefined();
      expect(revisedEvent?.description).toContain('Plan revised to version 2 (prior approvals invalidated)');
    });
  });

  // ==========================================================================
  // Dimension 4: Task Intake Security & Path Validation (POST /api/v1/tasks)
  // ==========================================================================
  describe('Dimension 4: Task Intake Security & Path Validation', () => {
    const baseValidPayload: TaskCreateRequest = {
      repository_id: DEFAULT_REPO_ID,
      title: 'Valid task title for stress testing',
      description: 'Testing intake validation',
      source: {
        type: 'USER_PROMPT',
      },
      requirements: [
        {
          id: 'req-1',
          description: 'Valid requirement targeting a clean path',
          category: 'functional',
          target_files: ['src/utils/math.ts'],
          acceptance_criteria: ['Unit tests pass'],
        },
      ],
      constraints: [],
    };

    it('rejects target_files with path traversal ../secret.txt with HTTP 422', async () => {
      const payload: TaskCreateRequest = {
        ...baseValidPayload,
        requirements: [
          {
            id: 'req-1',
            description: 'Malicious traversal requirement',
            category: 'functional',
            target_files: ['../secret.txt'],
            acceptance_criteria: [],
          },
        ],
      };

      try {
        await createTask(payload);
        expect.unreachable('Expected createTask to fail with 422 for path traversal');
      } catch (err) {
        const apiError = toApiError(err);
        expect(apiError.status).toBe(422);
        expect(apiError.code).toBe('INVALID_REQUEST');
        expect(apiError.message).toContain('Unsafe relative path detected');
      }
    });

    it('rejects target_files with deep traversal ../../etc/passwd with HTTP 422', async () => {
      const payload: TaskCreateRequest = {
        ...baseValidPayload,
        requirements: [
          {
            id: 'req-1',
            description: 'Deep traversal attempt',
            category: 'functional',
            target_files: ['../../etc/passwd'],
            acceptance_criteria: [],
          },
        ],
      };

      try {
        await createTask(payload);
        expect.unreachable('Expected createTask to fail with 422');
      } catch (err) {
        const apiError = toApiError(err);
        expect(apiError.status).toBe(422);
      }
    });

    it('rejects target_files with middle traversal foo/../../bar with HTTP 422', async () => {
      const payload: TaskCreateRequest = {
        ...baseValidPayload,
        requirements: [
          {
            id: 'req-1',
            description: 'Middle traversal attempt',
            category: 'functional',
            target_files: ['src/core/../../secret.ts'],
            acceptance_criteria: [],
          },
        ],
      };

      try {
        await createTask(payload);
        expect.unreachable('Expected createTask to fail with 422');
      } catch (err) {
        const apiError = toApiError(err);
        expect(apiError.status).toBe(422);
      }
    });

    it('rejects target_files with absolute paths /etc/shadow or C:\\Windows with HTTP 422', async () => {
      for (const unsafePath of ['/etc/shadow', 'C:/Windows/System32', '~/.ssh/id_rsa']) {
        const payload: TaskCreateRequest = {
          ...baseValidPayload,
          requirements: [
            {
              id: 'req-1',
              description: 'Absolute path attempt',
              category: 'functional',
              target_files: [unsafePath],
              acceptance_criteria: [],
            },
          ],
        };

        try {
          await createTask(payload);
          expect.unreachable(`Expected createTask to fail for absolute path: ${unsafePath}`);
        } catch (err) {
          const apiError = toApiError(err);
          expect(apiError.status).toBe(422);
        }
      }
    });

    it('rejects target_files targeting . or .. with HTTP 422', async () => {
      for (const unsafePath of ['.', '..', './file.ts']) {
        const payload: TaskCreateRequest = {
          ...baseValidPayload,
          requirements: [
            {
              id: 'req-1',
              description: 'Dot path attempt',
              category: 'functional',
              target_files: [unsafePath],
              acceptance_criteria: [],
            },
          ],
        };

        try {
          await createTask(payload);
          expect.unreachable(`Expected createTask to fail for dot path: ${unsafePath}`);
        } catch (err) {
          const apiError = toApiError(err);
          expect(apiError.status).toBe(422);
        }
      }
    });

    it('rejects forbidden_files with path traversal with HTTP 422', async () => {
      const payload: TaskCreateRequest = {
        ...baseValidPayload,
        constraints: [
          {
            id: 'cst-1',
            description: 'Unsafe forbidden file constraint',
            constraint_type: 'protected_file',
            forbidden_files: ['../escape.txt'],
            forbidden_packages: [],
          },
        ],
      };

      try {
        await createTask(payload);
        expect.unreachable('Expected createTask to fail with 422 for unsafe forbidden file');
      } catch (err) {
        const apiError = toApiError(err);
        expect(apiError.status).toBe(422);
        expect(apiError.message).toContain('Unsafe forbidden_file');
      }
    });

    it('rejects task intake when requirement target_files overlap with forbidden_files with HTTP 422', async () => {
      const payload: TaskCreateRequest = {
        ...baseValidPayload,
        requirements: [
          {
            id: 'req-overlap',
            description: 'Modifies protected security policy',
            category: 'security',
            target_files: ['src/core/security.ts', 'src/safe.ts'],
            acceptance_criteria: [],
          },
        ],
        constraints: [
          {
            id: 'cst-protected',
            description: 'Protect core security module',
            constraint_type: 'protected_file',
            forbidden_files: ['src/core/security.ts'],
            forbidden_packages: [],
          },
        ],
      };

      try {
        await createTask(payload);
        expect.unreachable('Expected createTask to fail with 422 for target/forbidden overlap');
      } catch (err) {
        const apiError = toApiError(err);
        expect(apiError.status).toBe(422);
        expect(apiError.code).toBe('INVALID_REQUEST');
        expect(apiError.message).toContain("Requirement 'req-overlap' targets forbidden file(s): src/core/security.ts");
      }
    });

    it('enforces title boundaries: rejects < 3 chars, > 256 chars, and whitespace only', async () => {
      // 1. Whitespace only
      try {
        await createTask({ ...baseValidPayload, title: '    \t\n  ' });
        expect.unreachable('Expected whitespace title to fail');
      } catch (err) {
        expect(toApiError(err).status).toBe(422);
      }

      // 2. Length 2 (< 3)
      try {
        await createTask({ ...baseValidPayload, title: 'ab' });
        expect.unreachable('Expected 2-char title to fail');
      } catch (err) {
        expect(toApiError(err).status).toBe(422);
      }

      // 3. Length 257 (> 256)
      try {
        await createTask({ ...baseValidPayload, title: 'a'.repeat(257) });
        expect.unreachable('Expected 257-char title to fail');
      } catch (err) {
        expect(toApiError(err).status).toBe(422);
      }

      // 4. Exact boundaries: length 3 and length 256 should succeed
      const task3 = await createTask({ ...baseValidPayload, title: 'abc' });
      expect(task3.title).toBe('abc');

      const task256 = await createTask({ ...baseValidPayload, title: 'a'.repeat(256) });
      expect(task256.title).toHaveLength(256);
    });

    it('rejects task intake with empty requirements array with HTTP 422', async () => {
      try {
        await createTask({ ...baseValidPayload, requirements: [] });
        expect.unreachable('Expected empty requirements to fail');
      } catch (err) {
        const apiError = toApiError(err);
        expect(apiError.status).toBe(422);
        expect(apiError.message).toContain('At least one requirement is required');
      }
    });
  });

  // ==========================================================================
  // Dimension 5: Error Normalizer Decoding (normaliseError)
  // ==========================================================================
  describe('Dimension 5: normaliseError Week 3 & Legacy Code Decoding', () => {
    it('correctly decodes all Week 3 domain error codes with fallback metadata', () => {
      const week3Codes = [
        { code: 'APPROVAL_REQUIRED', expectedStatus: 409, expectedRetryable: false },
        { code: 'PLAN_VERSION_MISMATCH', expectedStatus: 409, expectedRetryable: false },
        { code: 'INVALID_STATE_TRANSITION', expectedStatus: 409, expectedRetryable: false },
        { code: 'TASK_NOT_FOUND', expectedStatus: 404, expectedRetryable: false },
        { code: 'POLICY_VIOLATION', expectedStatus: 403, expectedRetryable: false },
        { code: 'COMMAND_NOT_ALLOWED', expectedStatus: 403, expectedRetryable: false },
        { code: 'RETRY_BUDGET_EXHAUSTED', expectedStatus: 400, expectedRetryable: false },
        { code: 'EXECUTION_TIMEOUT', expectedStatus: 408, expectedRetryable: true },
        { code: 'WORKSPACE_CREATION_FAILED', expectedStatus: 500, expectedRetryable: true },
        { code: 'RECOVERY_REQUIRED', expectedStatus: 500, expectedRetryable: false },
        { code: 'GITHUB_API_ERROR', expectedStatus: 502, expectedRetryable: true },
      ];

      for (const { code, expectedStatus, expectedRetryable } of week3Codes) {
        // Test via structured backend envelope
        const errEnvelope = createMockAxiosError(expectedStatus, {
          error: { code, message: `Custom msg for ${code}` },
        });
        const resEnvelope = normaliseError(errEnvelope);
        expect(resEnvelope.code).toBe(code);
        expect(resEnvelope.message).toBe(`Custom msg for ${code}`);
        expect(resEnvelope.status).toBe(expectedStatus);
        expect(resEnvelope.retryable).toBe(expectedRetryable);

        // Test via FastAPI direct string fallback { detail: code }
        const errDetail = createMockAxiosError(expectedStatus, { detail: code });
        const resDetail = normaliseError(errDetail);
        expect(resDetail.code).toBe(code);
        expect(resDetail.status).toBe(expectedStatus);
        expect(resDetail.retryable).toBe(expectedRetryable);
        expect(resDetail.message.length).toBeGreaterThan(5);
      }
    });

    it('preserves Week 2 legacy errors and network/timeout/cancellation handling without regression', () => {
      // 401 Unauthorized
      expect(normaliseError(createMockAxiosError(401)).code).toBe('UNAUTHORIZED');

      // 403 Forbidden
      expect(normaliseError(createMockAxiosError(403)).code).toBe('FORBIDDEN');

      // 404 Not Found
      expect(normaliseError(createMockAxiosError(404)).code).toBe('NOT_FOUND');

      // 409 Conflict
      expect(normaliseError(createMockAxiosError(409)).code).toBe('CONFLICT');

      // 422 Validation
      const err422 = createMockAxiosError(422, { detail: [{ loc: ['body', 'title'], msg: 'required' }] });
      const res422 = normaliseError(err422);
      expect(res422.code).toBe('INVALID_REQUEST');
      expect(res422.details).toBeDefined();

      // 429 Rate limited
      const res429 = normaliseError(createMockAxiosError(429));
      expect(res429.code).toBe('RATE_LIMITED');
      expect(res429.retryable).toBe(true);

      // 503 Service Unavailable
      const res503 = normaliseError(createMockAxiosError(503));
      expect(res503.code).toBe('SERVICE_UNAVAILABLE');
      expect(res503.retryable).toBe(true);

      // Timeout
      const resTimeout = normaliseError(createMockAxiosError(undefined, undefined, 'ECONNABORTED'));
      expect(resTimeout.code).toBe('REQUEST_TIMEOUT');
      expect(resTimeout.retryable).toBe(true);

      // Network error
      const resNetwork = normaliseError(createMockAxiosError(undefined, undefined, 'ERR_NETWORK'));
      expect(resNetwork.code).toBe('NETWORK_ERROR');
      expect(resNetwork.retryable).toBe(true);
    });
  });

  // ==========================================================================
  // Dimension 6: Issue Import Idempotency & Conflict Guardrails
  // ==========================================================================
  describe('Dimension 6: GitHub Issue Import Concurrency & Conflict Guardrails', () => {
    it('rejects re-import of an already imported issue with HTTP 409 CONFLICT', async () => {
      // Seed issue 42 is already imported as task-seed-1
      try {
        await importGitHubIssue(DEFAULT_REPO_ID, { issue_number: 42 });
        expect.unreachable('Expected import of issue 42 to fail with 409');
      } catch (err) {
        const apiError = toApiError(err);
        expect(apiError.status).toBe(409);
        expect(apiError.code).toBe('CONFLICT');
        expect(apiError.message).toContain('already been imported');
        expect((apiError.details as any).existing_task_id).toBe('task-seed-1');
      }
    });

    it('rejects duplicate import after freshly importing an unimported issue', async () => {
      // Issue 55 is unimported initially
      const firstImport = await importGitHubIssue(DEFAULT_REPO_ID, { issue_number: 55 });
      expect(firstImport.task_id).toBeDefined();
      expect(firstImport.status).toBe(TaskStatus.CREATED);

      // Attempting to import issue 55 a second time MUST yield 409 CONFLICT
      try {
        await importGitHubIssue(DEFAULT_REPO_ID, { issue_number: 55 });
        expect.unreachable('Expected second import of issue 55 to fail with 409');
      } catch (err) {
        const apiError = toApiError(err);
        expect(apiError.status).toBe(409);
        expect(apiError.code).toBe('CONFLICT');
        expect((apiError.details as any).existing_task_id).toBe(firstImport.task_id);
      }
    });

    it('rejects invalid issue numbers with HTTP 422', async () => {
      for (const badNumber of [0, -1, 1_000_001]) {
        try {
          await importGitHubIssue(DEFAULT_REPO_ID, { issue_number: badNumber });
          expect.unreachable(`Expected invalid issue_number ${badNumber} to fail`);
        } catch (err) {
          const apiError = toApiError(err);
          expect(apiError.status).toBe(422);
          expect(apiError.code).toBe('INVALID_REQUEST');
        }
      }
    });

    it('accurately filters task list by repository, status, and search query with proper pagination', async () => {
      const resAll = await listTasks();
      expect(resAll.items.length).toBeGreaterThanOrEqual(7);

      const resFiltered = await listTasks({
        repository_id: DEFAULT_REPO_ID,
        status: TaskStatus.PENDING_APPROVAL,
      });
      expect(resFiltered.items.every((t) => t.status === TaskStatus.PENDING_APPROVAL)).toBe(true);

      const resPaged = await listTasks({ page: 1, page_size: 2 });
      expect(resPaged.items).toHaveLength(2);
      expect(resPaged.page).toBe(1);
      expect(resPaged.page_size).toBe(2);
      expect(resPaged.total_pages).toBeGreaterThanOrEqual(4);
    });
  });
});
