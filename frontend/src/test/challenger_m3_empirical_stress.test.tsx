/**
 * Empirical Challenger M3 Stress Test Suite
 *
 * Rigorously challenges:
 * 1. Race conditions & concurrent plan mutations (concurrent approvals, re-plan during approval)
 * 2. 409 PLAN_VERSION_MISMATCH and INVALID_STATE_TRANSITION under adverse scenarios
 * 3. Cache consistency in React Query when mutations fail or conflict
 * 4. Boundary inputs: extreme pagination, XSS strings, negative/float/NaN plan versions
 * 5. Rate limits (429), not found (404), and error normalization resiliency
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { normaliseError } from '../services/api';
import {
  createTask,
  listTasks,
  getTask,
  getTaskPlan,
  generateTaskPlan,
  approveTaskPlan,
  rejectTaskPlan,
  getTaskEvents,
} from '../services/tasks';
import { TaskStatus, type TaskCreateRequest } from '../types/task';
import { resetMockStore } from '../mocks/handlers';
import { taskKeys } from '../hooks/useTasks';
import type { ApiError } from '../types/api';

function toApiError(err: unknown): ApiError {
  if (err && typeof err === 'object' && 'code' in err && 'status' in err) {
    return err as ApiError;
  }
  return normaliseError(err);
}

describe('Empirical Challenger M3: Advanced Adversarial & Stress Harness', () => {
  beforeEach(() => {
    resetMockStore();
  });

  // ==========================================================================
  // Section 1: Concurrent Plan Mutations & Version Race Conditions
  // ==========================================================================
  describe('1. Concurrency & Race Conditions', () => {
    it('handles two simultaneous approvals for the same task: exactly one succeeds, one gets 409', async () => {
      // task-seed-1 is PENDING_APPROVAL with plan_version 1
      const approval1 = approveTaskPlan('task-seed-1', {
        plan_version: 1,
        notes: 'Reviewer A approval',
        approved_by: 'Reviewer A',
      });
      const approval2 = approveTaskPlan('task-seed-1', {
        plan_version: 1,
        notes: 'Reviewer B approval',
        approved_by: 'Reviewer B',
      });

      const results = await Promise.allSettled([approval1, approval2]);

      const fulfilled = results.filter((r) => r.status === 'fulfilled');
      const rejected = results.filter((r) => r.status === 'rejected');

      // In a strict state machine, once the first approval transitions state to APPROVED,
      // the second approval must fail with 409 INVALID_STATE_TRANSITION because status is no longer PENDING_APPROVAL.
      expect(fulfilled.length).toBe(1);
      expect(rejected.length).toBe(1);

      const rejectedError = toApiError((rejected[0] as PromiseRejectedResult).reason);
      expect(rejectedError.status).toBe(409);
      expect(rejectedError.code).toBe('INVALID_STATE_TRANSITION');
      expect(rejectedError.message).toContain('PENDING_APPROVAL');

      // Verify the task in store is in APPROVED state
      const task = await getTask('task-seed-1');
      expect(task.status).toBe(TaskStatus.APPROVED);
      expect(task.approved_plan_version).toBe(1);
    });

    it('rejects stale approval if plan revision is completed just prior to approval submission', async () => {
      // Step 1: Revise plan to version 2
      const revisedPlan = await generateTaskPlan('task-seed-1', {
        prompt_instructions: 'Add defensive memory limits',
      });
      expect(revisedPlan.plan_version).toBe(2);

      // Step 2: Attempt approval with stale version 1
      try {
        await approveTaskPlan('task-seed-1', {
          plan_version: 1,
          notes: 'Approving stale version 1',
        });
        expect.unreachable('Should have failed with 409 PLAN_VERSION_MISMATCH');
      } catch (err) {
        const error = toApiError(err);
        expect(error.status).toBe(409);
        expect(error.code).toBe('PLAN_VERSION_MISMATCH');
        expect(error.details).toEqual({
          submitted_version: 1,
          current_version: 2,
        });
      }

      // Step 3: Approve with correct version 2 succeeds
      const approvedTask = await approveTaskPlan('task-seed-1', {
        plan_version: 2,
        notes: 'Approving active version 2',
      });
      expect(approvedTask.status).toBe(TaskStatus.APPROVED);
      expect(approvedTask.approved_plan_version).toBe(2);
    });

    it('handles rapid sequential plan generations (v1 -> v5) maintaining strict monotonic versioning and audit trail', async () => {
      // Rapidly revise plan 4 times
      for (let i = 2; i <= 5; i++) {
        const plan = await generateTaskPlan('task-seed-1', {
          prompt_instructions: `Revision ${i}`,
        });
        expect(plan.plan_version).toBe(i);
        expect(plan.status).toBe('PENDING_APPROVAL');
      }

      // Check current task state
      const task = await getTask('task-seed-1');
      expect(task.plan_version).toBe(5);
      expect(task.approved_plan_version).toBeNull();
      expect(task.status).toBe(TaskStatus.PENDING_APPROVAL);

      // Verify historical retrieval of any version
      for (let v = 1; v <= 5; v++) {
        const historical = await getTaskPlan('task-seed-1', v);
        expect(historical.plan_version).toBe(v);
      }

      // Requesting non-existent version 6 returns 404
      await expect(getTaskPlan('task-seed-1', 6)).rejects.toMatchObject({
        status: 404,
      });

      // Events audit trail must reflect all 4 revisions
      const eventsRes = await getTaskEvents('task-seed-1');
      const revisionEvents = eventsRes.items.filter((e) => e.event_type === 'PLAN_REVISED');
      expect(revisionEvents.length).toBe(4);
    });
  });

  // ==========================================================================
  // Section 2: Malformed & Boundary Version Inputs in Approval/Rejection
  // ==========================================================================
  describe('2. Boundary & Adversarial Version Inputs', () => {
    it('rejects approval when plan_version is NaN, float, negative, or missing', async () => {
      const invalidVersions = [-1, 0, 1.5, NaN, undefined, null];

      for (const invalidVer of invalidVersions) {
        try {
          await approveTaskPlan('task-seed-1', {
            plan_version: invalidVer as any,
          });
          expect.unreachable(`Expected approval with version ${invalidVer} to fail`);
        } catch (err) {
          const error = toApiError(err);
          expect(error.status).toBe(409);
          expect(error.code).toBe('PLAN_VERSION_MISMATCH');
        }
      }
    });

    it('rejects rejection when plan_version is invalid or mismatched', async () => {
      try {
        await rejectTaskPlan('task-seed-1', {
          plan_version: 999,
          reason: 'Mismatched version test',
        });
        expect.unreachable('Expected rejection with mismatched version to fail');
      } catch (err) {
        const error = toApiError(err);
        expect(error.status).toBe(409);
        expect(error.code).toBe('PLAN_VERSION_MISMATCH');
      }
    });
  });

  // ==========================================================================
  // Section 3: React Query Cache Invalidation & Consistency Simulation
  // ==========================================================================
  describe('3. React Query Cache Invalidation & Consistency', () => {
    it('maintains intact cache when mutation fails with 409 mismatch and does not corrupt local state', async () => {
      const queryClient = new QueryClient();

      // Seed cache with active task
      const initialTask = await getTask('task-seed-1');
      queryClient.setQueryData(taskKeys.detail('task-seed-1'), initialTask);

      // Simulate a failed approval mutation attempt
      let caughtError: ApiError | null = null;
      try {
        await approveTaskPlan('task-seed-1', { plan_version: 999 });
      } catch (err) {
        caughtError = toApiError(err);
      }

      expect(caughtError).not.toBeNull();
      expect(caughtError?.status).toBe(409);

      // Verify cached data was NOT modified or corrupted by the failed mutation
      const cached = queryClient.getQueryData(taskKeys.detail('task-seed-1'));
      expect(cached).toEqual(initialTask);
    });

    it('correctly invalidates and synchronizes queryClient cache on successful approval', async () => {
      const queryClient = new QueryClient();

      const initialTask = await getTask('task-seed-1');
      queryClient.setQueryData(taskKeys.detail('task-seed-1'), initialTask);

      // Perform valid approval
      const updatedTask = await approveTaskPlan('task-seed-1', { plan_version: 1, notes: 'Approved' });

      // Emulate hook onSuccess behavior
      queryClient.invalidateQueries({ queryKey: taskKeys.detail('task-seed-1') });
      queryClient.setQueryData(taskKeys.detail('task-seed-1'), updatedTask);

      const cached = queryClient.getQueryData<any>(taskKeys.detail('task-seed-1'));
      expect(cached.status).toBe(TaskStatus.APPROVED);
      expect(cached.approved_plan_version).toBe(1);
    });
  });

  // ==========================================================================
  // Section 4: Boundary Inputs & Search/Pagination Robustness
  // ==========================================================================
  describe('4. Search, Filter & Pagination Boundary Robustness', () => {
    it('handles SQL-like injections, XSS payloads, and unicode in search query safely', async () => {
      const adversarialQueries = [
        "' OR '1'='1",
        '<script>alert(1)</script>',
        '${7*7}',
        '../../etc/passwd',
        '🚀🔥 Unicode Symbols ℵ 𝄞',
        'null',
        'undefined',
      ];

      for (const query of adversarialQueries) {
        const res = await listTasks({ search: query });
        expect(res).toBeDefined();
        expect(Array.isArray(res.items)).toBe(true);
        expect(typeof res.total).toBe('number');
      }
    });

    it('gracefully handles astronomical page and page_size numbers without crashing', async () => {
      const res = await listTasks({ page: 999999, page_size: 1000000 });
      expect(res.page).toBe(999999);
      expect(res.items).toEqual([]);
      expect(res.total).toBeGreaterThan(0);
    });

    it('rejects task intake with malicious target_file containing backslash traversal or null bytes', async () => {
      const maliciousPayload: TaskCreateRequest = {
        title: 'Malicious Traversal Attempt',
        description: 'Attempting to inject backslash path traversal',
        repository_id: 'repo-1',
        source: {
          type: 'USER_PROMPT',
          repository_id: 'repo-1',
        },
        requirements: [
          {
            id: 'req-bad',
            description: 'Bad requirement',
            category: 'functional',
            target_files: ['..\\..\\windows\\system32\\cmd.exe'],
            acceptance_criteria: ['Fail'],
          },
        ],
      };

      try {
        await createTask(maliciousPayload);
        expect.unreachable('Should have rejected backslash traversal');
      } catch (err) {
        const error = toApiError(err);
        expect(error.status).toBe(422);
        expect(error.code).toBe('INVALID_REQUEST');
        expect(error.message).toContain('Unsafe relative path');
      }
    });
  });

  // ==========================================================================
  // Section 5: Rate Limiting & Error Normalization
  // ==========================================================================
  describe('5. Error Normalization Resilience', () => {
    it('normalizes HTTP 429 RATE_LIMITED with retryable: true', () => {
      const fakeAxiosError = {
        isAxiosError: true,
        response: {
          status: 429,
          data: {
            error: {
              code: 'RATE_LIMITED',
              message: 'GitHub API rate limit exceeded.',
              retryable: true,
              details: { reset_at: 1730000000 },
            },
          },
        },
      };

      const norm = normaliseError(fakeAxiosError);
      expect(norm.status).toBe(429);
      expect(norm.code).toBe('RATE_LIMITED');
      expect(norm.retryable).toBe(true);
      expect(norm.message).toContain('GitHub API rate limit exceeded');
    });

    it('normalizes 404 TASK_NOT_FOUND with human-friendly message', () => {
      const fakeAxiosError = {
        isAxiosError: true,
        response: {
          status: 404,
          data: {
            error: {
              code: 'TASK_NOT_FOUND',
            },
          },
        },
      };

      const norm = normaliseError(fakeAxiosError);
      expect(norm.status).toBe(404);
      expect(norm.code).toBe('TASK_NOT_FOUND');
      expect(norm.message).toContain('Task not found');
    });

    it('normalizes 409 APPROVAL_REQUIRED with non-retryable flag', () => {
      const fakeAxiosError = {
        isAxiosError: true,
        response: {
          status: 409,
          data: {
            error: {
              code: 'APPROVAL_REQUIRED',
            },
          },
        },
      };

      const norm = normaliseError(fakeAxiosError);
      expect(norm.status).toBe(409);
      expect(norm.code).toBe('APPROVAL_REQUIRED');
      expect(norm.retryable).toBe(false);
      expect(norm.message).toContain('Human approval of the plan is required');
    });
  });
});
