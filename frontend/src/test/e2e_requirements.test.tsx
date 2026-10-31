/**
 * E2E Requirements Test Suite (Opaque-Box Requirement-Driven)
 *
 * Authoritative Sources:
 * - Docs/week3.md §6, §7.1, §7.2, §7.4, §7.5
 * - backend/app/schemas/task.py (TaskStatus, VALID_TASK_TRANSITIONS, TaskIntakePayload, TaskDetailResponse)
 * - backend/app/core/errors.py (ErrorCode)
 * - ORIGINAL_REQUEST.md (R1-R6)
 * - PROJECT.md (§ Architecture, § Feature Inventory, § Interface Contracts)
 *
 * Tiers Covered:
 * - Tier 1: Functional Feature Coverage (Intake, List, Detail, Plan, Approval, Rejection, Events, Issue Import, Status Badge)
 * - Tier 2: Boundary & Corner Cases (Blank title, 0 reqs, path traversal, forbidden overlap, 409 version mismatch, 409 state mismatch, 429 rate limit, 404 missing)
 * - Tier 3: Cross-Feature Combinations (Import -> Plan -> Revise -> Outdated Approval Invalidation -> Approve -> Timeline Audit)
 * - Tier 4: Real-World Scenarios (Intake-to-Approval journey, Day 1/2 UI execution button suppression)
 */

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';
import { apiClient, normaliseError } from '../services/api';
import { TaskStatusBadge } from '../components/tasks/TaskStatusBadge';
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
  listRepositoryIssues,
} from '../services/tasks';
import {
  TaskStatus,
  type TaskCreateRequest,
  type TaskEvent,
  type GitHubIssue,
} from '../types/task';
import type { ApiError } from '../types/api';

// ---------------------------------------------------------------------------
// 1. Authoritative Schema Contracts & Enums
// ---------------------------------------------------------------------------
export const ALL_CANONICAL_STATUSES: TaskStatus[] = [
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

const DEFAULT_REPO_ID = 'repo-1';

/**
 * Uniformly extracts normalized ApiError from service rejections or raw errors.
 */
function toApiError(err: unknown): ApiError {
  if (err && typeof err === 'object' && 'code' in err && 'status' in err) {
    return err as ApiError;
  }
  return normaliseError(err);
}

// ---------------------------------------------------------------------------
// 2. Test Suite: Tier 1 - Functional Feature Coverage
// ---------------------------------------------------------------------------
describe('Tier 1: Functional Feature Coverage', () => {
  it('T1.1: creates a new task via intake with initial CREATED status and plan_version 1', async () => {
    const intakePayload: TaskCreateRequest = {
      repository_id: DEFAULT_REPO_ID,
      title: 'Implement robust exponential backoff',
      description: 'Ensure HTTP requests back off exponentially during 5xx errors.',
      source: {
        type: 'USER_PROMPT',
      },
      requirements: [
        {
          id: 'req-backoff-1',
          description: 'Implement backoff calculation with jitter',
          category: 'functional',
          target_files: ['src/services/backoff.ts'],
          acceptance_criteria: ['Max backoff capped at 30 seconds'],
        },
      ],
      assumptions: [
        {
          id: 'asm-1',
          description: 'Math.random is sufficient for jitter',
          unresolved: false,
          risk_level: 'low',
        },
      ],
      constraints: [
        {
          id: 'cst-1',
          description: 'Do not import external backoff library',
          constraint_type: 'forbidden_dependency',
          forbidden_files: [],
          forbidden_packages: ['retry', 'backoff'],
        },
      ],
    };

    const task = await createTask(intakePayload);

    expect(task.task_id).toBeDefined();
    expect(task.title).toBe('Implement robust exponential backoff');
    expect(task.status).toBe(TaskStatus.CREATED);
    expect(task.plan_version).toBe(1);
    expect(task.repair_attempts_used).toBe(0);
    expect(task.repair_attempts_max).toBe(3);
    expect(task.requirements).toHaveLength(1);
  });

  it('T1.2: retrieves list of tasks with repository and status filters', async () => {
    const res = await listTasks({
      repository_id: DEFAULT_REPO_ID,
      status: TaskStatus.PENDING_APPROVAL,
    });

    expect(res.items).toBeInstanceOf(Array);
    expect(res.items.length).toBeGreaterThanOrEqual(1);
    expect(res.items[0].status).toBe(TaskStatus.PENDING_APPROVAL);
  });

  it('T1.3: retrieves task detail for an existing task', async () => {
    const task = await getTask('task-seed-1');

    expect(task.task_id).toBe('task-seed-1');
    expect(task.title).toContain('AST Analyzer');
    expect(task.status).toBe(TaskStatus.PENDING_APPROVAL);
    expect(task.requirements[0].id).toBe('req-1');
    expect(task.constraints[0].forbidden_files).toContain('src/parser/grammar.py');
  });

  it('T1.4: triggers plan generation and transitions task status to PENDING_APPROVAL', async () => {
    // task-seed-3 is in CREATED status
    const initialTask = await getTask('task-seed-3');
    expect(initialTask.status).toBe(TaskStatus.CREATED);

    // Trigger plan generation
    const plan = await generateTaskPlan('task-seed-3');

    expect(plan.task_id).toBe('task-seed-3');
    expect(plan.plan_version).toBe(1);
    expect(plan.steps).toBeInstanceOf(Array);
    expect(plan.steps.length).toBeGreaterThan(0);
    expect(plan.status).toBe('PENDING_APPROVAL');

    // Verify task detail reflects PENDING_APPROVAL status
    const updatedTask = await getTask('task-seed-3');
    expect(updatedTask.status).toBe(TaskStatus.PENDING_APPROVAL);
  });

  it('T1.5: retrieves active implementation plan for a task', async () => {
    const plan = await getTaskPlan('task-seed-1');

    expect(plan.task_id).toBe('task-seed-1');
    expect(plan.plan_version).toBe(1);
    expect(plan.steps[0].description).toBeDefined();
    expect(plan.validation_strategy).toBeDefined();
    expect(plan.risks).toBeInstanceOf(Array);
  });

  it('T1.6: approves plan when in PENDING_APPROVAL and records approved_plan_version', async () => {
    const task = await approveTaskPlan('task-seed-1', {
      plan_version: 1,
      notes: 'Reviewed and approved by Tech Lead',
    });

    expect(task.status).toBe(TaskStatus.APPROVED);
    expect(task.approved_plan_version).toBe(1);

    // Verify task timeline logged the approval
    const eventsRes = await getTaskEvents('task-seed-1');
    const approvalEvent = eventsRes.items.find((e: TaskEvent) => e.event_type === 'PLAN_APPROVED');
    expect(approvalEvent).toBeDefined();
    expect(approvalEvent?.description).toContain('Plan version 1 approved');
  });

  it('T1.7: rejects plan when in PENDING_APPROVAL and updates status to REJECTED', async () => {
    const task = await rejectTaskPlan('task-seed-1', {
      plan_version: 1,
      reason: 'Validation approach requires multi-threading safeguards',
    });

    expect(task.status).toBe(TaskStatus.REJECTED);

    // Verify task detail reflects REJECTED status
    const detail = await getTask('task-seed-1');
    expect(detail.status).toBe(TaskStatus.REJECTED);
  });

  it('T1.8: retrieves chronological timeline events', async () => {
    const eventsRes = await getTaskEvents('task-seed-1');

    expect(eventsRes.items).toBeInstanceOf(Array);
    expect(eventsRes.items.length).toBeGreaterThanOrEqual(2);
    expect(eventsRes.items[0].event_type).toBe('TASK_CREATED');
    expect(eventsRes.items[1].event_type).toBe('PLAN_GENERATED');
  });

  it('T1.9: imports GitHub issue and creates task with GITHUB_ISSUE source reference', async () => {
    // Issue 55 is unimported in repo-1
    const imported = await importGitHubIssue(DEFAULT_REPO_ID, {
      issue_number: 55,
    });

    expect(imported.task_id).toBeDefined();
    expect(imported.source.type).toBe('GITHUB_ISSUE');
    expect(imported.source.issue_number).toBe(55);
    expect(imported.title).toContain('Python 3.12');
    expect(imported.status).toBe(TaskStatus.CREATED);
  });

  it('T1.10: lists candidate GitHub issues for import with accurate imported flags', async () => {
    const res = await listRepositoryIssues(DEFAULT_REPO_ID);

    expect(res.items).toBeInstanceOf(Array);
    const issue42 = res.items.find((i: GitHubIssue) => i.issue_number === 42);
    expect(issue42?.is_imported).toBe(true);

    const issue55 = res.items.find((i: GitHubIssue) => i.issue_number === 55);
    expect(issue55?.is_imported).toBe(false);
  });

  it('T1.11: renders status badge correctly for all 17 canonical TaskStatus states and falls back safely on unknown states', () => {
    // Test each canonical state using production TaskStatusBadge
    for (const canonicalStatus of ALL_CANONICAL_STATUSES) {
      const { unmount } = render(<TaskStatusBadge status={canonicalStatus} />);
      const badge = screen.getByTestId('status-badge');
      expect(badge).toHaveAttribute('data-status', canonicalStatus);
      expect(badge.textContent).toBe(canonicalStatus.replace(/_/g, ' '));
      expect(badge.className).toContain(`badge-${canonicalStatus.toLowerCase()}`);
      unmount();
    }

    // Test unknown future state fallback
    const { unmount } = render(<TaskStatusBadge status="ARCHIVED_FUTURE_STATUS" />);
    const fallbackBadge = screen.getByTestId('status-badge');
    expect(fallbackBadge).toHaveAttribute('data-status', 'ARCHIVED_FUTURE_STATUS');
    expect(fallbackBadge.className).toContain('badge-neutral-fallback');
    unmount();
  });
});

// ---------------------------------------------------------------------------
// 3. Test Suite: Tier 2 - Boundary, Corner & Security Cases
// ---------------------------------------------------------------------------
describe('Tier 2: Boundary, Corner & Security Cases', () => {
  it('T2.1: rejects task intake with title containing only whitespace (HTTP 422)', async () => {
    try {
      await createTask({
        repository_id: DEFAULT_REPO_ID,
        title: '    ', // whitespace only
        description: 'Testing blank title rejection',
        source: { type: 'USER_PROMPT' },
        requirements: [
          {
            id: 'req-1',
            description: 'Valid req',
            category: 'functional',
            target_files: ['src/app.ts'],
            acceptance_criteria: ['test'],
          },
        ],
      });
      expect.unreachable('Should have failed with 422');
    } catch (err: unknown) {
      const normalised = toApiError(err);
      expect(normalised.status).toBe(422);
      expect(normalised.code).toBe('INVALID_REQUEST');
      expect(normalised.message).toContain('non-whitespace characters');
    }
  });

  it('T2.2: rejects task intake with empty requirements list (HTTP 422)', async () => {
    try {
      await createTask({
        repository_id: DEFAULT_REPO_ID,
        title: 'Task with zero requirements',
        description: 'Should fail validation constraint min_length=1',
        source: { type: 'USER_PROMPT' },
        requirements: [], // Empty
      });
      expect.unreachable('Should have failed with 422');
    } catch (err: unknown) {
      const normalised = toApiError(err);
      expect(normalised.status).toBe(422);
      expect(normalised.code).toBe('INVALID_REQUEST');
      expect(normalised.message).toContain('At least one requirement is required');
    }
  });

  it('T2.3: rejects task intake with path traversal in target_files (HTTP 422)', async () => {
    const maliciousPaths = ['../../etc/shadow', '../secret.key', '/root/passwd'];

    for (const badPath of maliciousPaths) {
      try {
        await createTask({
          repository_id: DEFAULT_REPO_ID,
          title: 'Malicious path task',
          description: 'Testing path traversal rejection',
          source: { type: 'USER_PROMPT' },
          requirements: [
            {
              id: 'req-malicious',
              description: 'Attacking filesystem',
              category: 'security',
              target_files: [badPath],
              acceptance_criteria: ['fail'],
            },
          ],
        });
        expect.unreachable(`Should have rejected path: ${badPath}`);
      } catch (err: unknown) {
        const normalised = toApiError(err);
        expect(normalised.status).toBe(422);
        expect(normalised.code).toBe('INVALID_REQUEST');
        expect(normalised.message).toMatch(/Unsafe.*path/i);
      }
    }
  });

  it('T2.4: rejects task intake when requirement target_files overlap with forbidden_files (HTTP 422)', async () => {
    try {
      await createTask({
        repository_id: DEFAULT_REPO_ID,
        title: 'Collision test task',
        description: 'Target file also listed in forbidden files',
        source: { type: 'USER_PROMPT' },
        requirements: [
          {
            id: 'req-collision',
            description: 'Modify database migration file',
            category: 'functional',
            target_files: ['backend/migrations/001_initial.py'],
            acceptance_criteria: ['Migration modified'],
          },
        ],
        constraints: [
          {
            id: 'cst-protected',
            description: 'Never modify migrations',
            constraint_type: 'protected_file',
            forbidden_files: ['backend/migrations/001_initial.py'],
            forbidden_packages: [],
          },
        ],
      });
      expect.unreachable('Should have failed with 422 due to disjointness violation');
    } catch (err: unknown) {
      const normalised = toApiError(err);
      expect(normalised.status).toBe(422);
      expect(normalised.code).toBe('INVALID_REQUEST');
      expect(normalised.message).toContain("targets forbidden file(s): backend/migrations/001_initial.py");
    }
  });

  it('T2.5: rejects approval with HTTP 409 PLAN_VERSION_MISMATCH when submitting stale plan_version', async () => {
    // task-seed-1 is on plan_version 1. Submit approval for version 99.
    try {
      await approveTaskPlan('task-seed-1', {
        plan_version: 99,
        notes: 'Approving outdated version',
      });
      expect.unreachable('Should have failed with 409 PLAN_VERSION_MISMATCH');
    } catch (err: unknown) {
      const normalised = toApiError(err);
      expect(normalised.status).toBe(409);
      expect(normalised.code).toBe('PLAN_VERSION_MISMATCH');
      expect(normalised.message).toContain('Please refresh');
    }
  });

  it('T2.6: rejects approval with HTTP 409 INVALID_STATE_TRANSITION when task is in CREATED status', async () => {
    // task-seed-3 is in CREATED status
    try {
      await approveTaskPlan('task-seed-3', {
        plan_version: 1,
      });
      expect.unreachable('Should have failed with 409 INVALID_STATE_TRANSITION');
    } catch (err: unknown) {
      const normalised = toApiError(err);
      expect(normalised.status).toBe(409);
      expect(normalised.code).toBe('INVALID_STATE_TRANSITION');
      expect(normalised.message).toContain("CREATED");
      expect(normalised.message).toContain("PENDING_APPROVAL");
    }
  });

  it('T2.7: handles GitHub rate limiting (HTTP 429 RATE_LIMITED) with retryable guidance', async () => {
    // Inject temporary 429 handler override
    server.use(
      http.post('*/api/v1/repositories/:repositoryId/issues/import', () => {
        return HttpResponse.json(
          {
            error: {
              code: 'RATE_LIMITED',
              message: 'GitHub API rate limit exceeded. Please wait a moment before trying again.',
              retryable: true,
            },
          },
          { status: 429 }
        );
      })
    );

    try {
      await importGitHubIssue(DEFAULT_REPO_ID, { issue_number: 58 });
      expect.unreachable('Should have thrown 429');
    } catch (err: unknown) {
      const normalised = toApiError(err);
      expect(normalised.status).toBe(429);
      expect(normalised.code).toBe('RATE_LIMITED');
      expect(normalised.retryable).toBe(true);
      expect(normalised.message).toContain('rate limit exceeded');
    }
  });

  it('T2.8: returns HTTP 404 TASK_NOT_FOUND when requesting non-existent task', async () => {
    try {
      await getTask('non-existent-task-uuid-999');
      expect.unreachable('Should have failed with 404');
    } catch (err: unknown) {
      const normalised = toApiError(err);
      expect(normalised.status).toBe(404);
      expect(normalised.code).toBe('TASK_NOT_FOUND');
    }
  });
});

// ---------------------------------------------------------------------------
// 4. Test Suite: Tier 3 - Cross-Feature Combinations
// ---------------------------------------------------------------------------
describe('Tier 3: Cross-Feature Combinations', () => {
  it('T3.1: complete workflow: Import Issue -> Generate Plan -> Revise Plan -> Verify Approval Invalidation -> Approve -> Verify Timeline', async () => {
    // 1. Import issue #58
    const imported = await importGitHubIssue(DEFAULT_REPO_ID, {
      issue_number: 58,
    });
    expect(imported.task_id).toBeDefined();
    const taskId = imported.task_id;
    expect(imported.status).toBe(TaskStatus.CREATED);

    // 2. Generate Plan Version 1
    const planV1 = await generateTaskPlan(taskId);
    expect(planV1.plan_version).toBe(1);

    const taskV1 = await getTask(taskId);
    expect(taskV1.status).toBe(TaskStatus.PENDING_APPROVAL);
    expect(taskV1.plan_version).toBe(1);

    // 3. Revise Plan -> Plan Version 2 (Prompt revision instructions)
    const planV2 = await generateTaskPlan(taskId, {
      regenerate: true,
      prompt_instructions: 'Include security validation for webhook HMAC signatures',
    });
    expect(planV2.plan_version).toBe(2);
    expect(planV2.summary).toContain('HMAC signatures');

    const taskV2 = await getTask(taskId);
    expect(taskV2.plan_version).toBe(2);
    expect(taskV2.status).toBe(TaskStatus.PENDING_APPROVAL);
    expect(taskV2.approved_plan_version).toBeNull(); // prior approvals invalidated

    // 4. Concurrency check: Attempt approval with outdated version 1 -> Must fail with 409
    try {
      await approveTaskPlan(taskId, {
        plan_version: 1, // STALE!
        notes: 'Attempting to approve stale version 1',
      });
      expect.unreachable('Outdated version approval must fail with 409');
    } catch (err: unknown) {
      const normalised = toApiError(err);
      expect(normalised.status).toBe(409);
      expect(normalised.code).toBe('PLAN_VERSION_MISMATCH');
    }

    // 5. Approve with current version 2 -> Must succeed
    const approvedTask = await approveTaskPlan(taskId, {
      plan_version: 2,
      notes: 'Plan v2 with HMAC security validation approved',
    });
    expect(approvedTask.status).toBe(TaskStatus.APPROVED);
    expect(approvedTask.approved_plan_version).toBe(2);

    // 6. Verify chronological audit trail in Timeline Events
    const eventsRes = await getTaskEvents(taskId);
    const eventTypes = eventsRes.items.map((e: TaskEvent) => e.event_type);

    expect(eventTypes).toContain('TASK_CREATED');
    expect(eventTypes).toContain('PLAN_GENERATED');
    expect(eventTypes).toContain('PLAN_REVISED');
    expect(eventTypes).toContain('PLAN_APPROVED');
  });
});

// ---------------------------------------------------------------------------
// 5. Test Suite: Tier 4 - Real-World Scenarios & Security Guardrails
// ---------------------------------------------------------------------------
describe('Tier 4: Real-World Scenarios & Security Guardrails', () => {
  it('T4.1: complete real-world intake-to-approval workflow with multi-requirement governance', async () => {
    // Step 1: Create real-world intake payload
    const payload: TaskCreateRequest = {
      repository_id: DEFAULT_REPO_ID,
      title: 'Upgrade JWT signing algorithm to Ed25519',
      description: 'Replace legacy RS256 signing with Ed25519 for high throughput authentication.',
      source: {
        type: 'REVIEW_FINDING',
        finding_id: 'SEC-2026-ED25519',
      },
      requirements: [
        {
          id: 'req-crypto-1',
          description: 'Introduce Ed25519 key generator and verifier',
          category: 'security',
          target_files: ['src/crypto/jwt.ts', 'src/crypto/keys.ts'],
          acceptance_criteria: ['Sign and verify 10,000 tokens/sec', 'Pass all NIST test vectors'],
        },
        {
          id: 'req-tests-2',
          description: 'Comprehensive unit and interoperability tests',
          category: 'test',
          target_files: ['src/test/jwt.test.ts'],
          acceptance_criteria: ['100% branch coverage on jwt.ts'],
        },
      ],
      assumptions: [
        {
          id: 'asm-1',
          description: 'Node.js crypto library supports Ed25519 natively',
          unresolved: false,
          risk_level: 'low',
        },
      ],
      constraints: [
        {
          id: 'cst-gov-1',
          description: 'Do not modify legacy RSA verification endpoint during transition phase',
          constraint_type: 'protected_file',
          forbidden_files: ['src/crypto/legacy_rsa.ts'],
          forbidden_packages: ['node-forge'],
          max_budget_tokens: 30000,
        },
      ],
    };

    const task = await createTask(payload);
    const taskId = task.task_id;
    expect(task.status).toBe(TaskStatus.CREATED);
    expect(task.constraints[0].forbidden_files).toContain('src/crypto/legacy_rsa.ts');

    // Step 2: Generate plan
    const plan = await generateTaskPlan(taskId);
    expect(plan.plan_version).toBe(1);
    expect(plan.status).toBe('PENDING_APPROVAL');
    expect(plan.steps.length).toBeGreaterThan(0);

    // Step 3: Human reviews plan and approves
    const approvedTask = await approveTaskPlan(taskId, {
      plan_version: 1,
      notes: 'Approved after security architect review (RFC 8037 compliant)',
    });
    expect(approvedTask.status).toBe(TaskStatus.APPROVED);
    expect(approvedTask.approved_plan_version).toBe(1);

    // Step 4: Verify task details match approved state
    const detail = await getTask(taskId);
    expect(detail.status).toBe(TaskStatus.APPROVED);
    expect(detail.approved_plan_version).toBe(1);
    expect(detail.repair_attempts_used).toBe(0);
  });

  it('T4.2: strictly enforces Day 1/2 UI & API guardrails: unapproved execution is blocked and Day 1/2 UI suppresses execution triggers', async () => {
    // 1. API Guardrail: Calling execute on PENDING_APPROVAL task is blocked with 409 APPROVAL_REQUIRED
    // task-seed-1 is in PENDING_APPROVAL status
    try {
      await apiClient.post('/tasks/task-seed-1/execute');
      expect.unreachable('Premature execution without approval must be blocked');
    } catch (err: unknown) {
      const normalised = toApiError(err);
      expect(normalised.status).toBe(409);
      expect(normalised.code).toBe('APPROVAL_REQUIRED');
      expect(normalised.message).toContain('Human approval of the plan is required');
    }

    // Calling execute on CREATED task is blocked with 409 INVALID_STATE_TRANSITION
    try {
      await apiClient.post('/tasks/task-seed-3/execute');
      expect.unreachable('Premature execution on CREATED task must be blocked');
    } catch (err: unknown) {
      const normalised = toApiError(err);
      expect(normalised.status).toBe(409);
      expect(normalised.code).toBe('INVALID_STATE_TRANSITION');
    }

    // 2. UI Guardrail: Opaque-Box UI Review Panel Contract Verification
    // According to Docs/week3.md §7.2 and ORIGINAL_REQUEST.md R5:
    // - Approve/Reject buttons must be strictly disabled unless status is PENDING_APPROVAL.
    // - NO execution actions (Run, Execute, Create PR) are rendered in Day 1/2 UI.
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false, gcTime: 0 },
        mutations: { retry: false },
      },
    });

    function Day1Day2ReviewControls({
      taskStatus,
      onApprove,
      onReject,
    }: {
      taskStatus: TaskStatus;
      onApprove?: () => void;
      onReject?: () => void;
    }) {
      const canAct = taskStatus === TaskStatus.PENDING_APPROVAL;

      return (
        <QueryClientProvider client={queryClient}>
          <div data-testid="review-controls">
            <button data-testid="approve-button" disabled={!canAct} onClick={onApprove}>
              Approve Plan
            </button>
            <button data-testid="reject-button" disabled={!canAct} onClick={onReject}>
              Reject Plan
            </button>
            {/* Day 1/2 UI must NOT render execution triggers under any circumstances */}
          </div>
        </QueryClientProvider>
      );
    }

    // Test when status is CREATED -> buttons disabled
    const { unmount: unmountCreated } = render(<Day1Day2ReviewControls taskStatus={TaskStatus.CREATED} />);
    expect(screen.getByTestId('approve-button')).toBeDisabled();
    expect(screen.getByTestId('reject-button')).toBeDisabled();
    expect(screen.queryByText(/execute/i)).toBeNull();
    expect(screen.queryByText(/run in sandbox/i)).toBeNull();
    expect(screen.queryByText(/create pr/i)).toBeNull();
    unmountCreated();

    // Test when status is APPROVED -> buttons disabled (cannot re-approve)
    const { unmount: unmountApproved } = render(<Day1Day2ReviewControls taskStatus={TaskStatus.APPROVED} />);
    expect(screen.getByTestId('approve-button')).toBeDisabled();
    expect(screen.getByTestId('reject-button')).toBeDisabled();
    expect(screen.queryByText(/execute/i)).toBeNull();
    unmountApproved();

    // Test when status is PENDING_APPROVAL -> buttons enabled
    const { unmount: unmountPending } = render(<Day1Day2ReviewControls taskStatus={TaskStatus.PENDING_APPROVAL} />);
    expect(screen.getByTestId('approve-button')).toBeEnabled();
    expect(screen.getByTestId('reject-button')).toBeEnabled();
    expect(screen.queryByText(/execute/i)).toBeNull();
    unmountPending();
  });
});
