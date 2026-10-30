/**
 * MSW v2 Mock Handlers & In-Memory Stateful Store for Week 3 Task Planning & Approval.
 *
 * Source of truth:
 * - Docs/week3.md §6 & §7
 * - backend/app/schemas/task.py
 * - backend/app/core/errors.py
 */

import { http, HttpResponse } from 'msw';
import {
  TaskStatus,
  type TaskCreateRequest,
  type TaskDetailResponse,
  type TaskListResponse,
  type TaskPlan,
  type PlanApproval,
  type TaskEvent,
  type TaskEventListResponse,
  type GitHubIssue,
  type GitHubIssueListResponse,
  type IssueImportRequest,
  type IssueImportResponse,
  type TaskTestResultsResponse,
  type VerificationResult,
} from '../../types/task';

// ============================================================================
// In-Memory Stateful Store
// ============================================================================

interface MockDatabase {
  tasks: Map<string, TaskDetailResponse>;
  plans: Map<string, Map<number, TaskPlan>>;
  approvals: Map<string, PlanApproval[]>;
  events: Map<string, TaskEvent[]>;
  tests: Map<string, TaskTestResultsResponse>;
  verifications: Map<string, VerificationResult>;
  issues: Map<string, GitHubIssue[]>;
}

const DEFAULT_REPO_ID = 'repo-1';

function createInitialSeedData(): MockDatabase {
  const tasks = new Map<string, TaskDetailResponse>();
  const plans = new Map<string, Map<number, TaskPlan>>();
  const approvals = new Map<string, PlanApproval[]>();
  const events = new Map<string, TaskEvent[]>();
  const tests = new Map<string, TaskTestResultsResponse>();
  const verifications = new Map<string, VerificationResult>();
  const issues = new Map<string, GitHubIssue[]>();

  // Seed 1: Task in PENDING_APPROVAL state (Ready for human review & approval)
  const task1: TaskDetailResponse = {
    task_id: 'task-seed-1',
    repository_id: DEFAULT_REPO_ID,
    title: 'Fix Token Budget Overflow in AST Analyzer',
    description:
      'The AST recursive symbol traversal causes token exhaustion when analyzing modules with more than 500 export statements.',
    status: TaskStatus.PENDING_APPROVAL,
    source: {
      type: 'GITHUB_ISSUE',
      issue_number: 42,
      issue_url: 'https://github.com/example/repo/issues/42',
      repository_id: DEFAULT_REPO_ID,
      base_revision: 'a1b2c3d4e5f6',
    },
    requirements: [
      {
        id: 'req-1',
        description: 'Cap AST symbol extraction depth to 4 levels and summarize nested symbols.',
        category: 'bug_fix',
        target_files: ['src/analyzer/ast_walker.py', 'src/analyzer/token_budget.py'],
        acceptance_criteria: [
          'Budget cannot exceed 20,000 tokens during deep AST walking.',
          'Summary metadata emitted for truncated symbols.',
        ],
      },
    ],
    assumptions: [
      {
        id: 'asm-1',
        description: 'Existing symbol table format remains backward-compatible.',
        unresolved: false,
        risk_level: 'low',
      },
    ],
    constraints: [
      {
        id: 'cst-1',
        description: 'Do not modify core parser grammar files.',
        constraint_type: 'protected_file',
        forbidden_files: ['src/parser/grammar.py'],
        forbidden_packages: [],
        max_budget_tokens: 20000,
      },
    ],
    base_revision: 'a1b2c3d4e5f6',
    plan_version: 1,
    approved_plan_version: null,
    repair_attempts_used: 0,
    repair_attempts_max: 3,
    created_at: '2026-10-29T10:00:00.000Z',
    updated_at: '2026-10-29T10:15:00.000Z',
  };
  tasks.set(task1.task_id, task1);

  const plan1: TaskPlan = {
    task_id: task1.task_id,
    plan_version: 1,
    base_revision: 'a1b2c3d4e5f6',
    summary: 'Implement bounded recursion with depth threshold in AST walker and token counter check.',
    problem_statement: 'High memory and token consumption during deep symbol tree parsing.',
    assumptions: ['Module export count does not affect token cap validation logic.'],
    unresolved_questions: [],
    relevant_files: ['src/analyzer/ast_walker.py', 'src/analyzer/token_budget.py'],
    steps: [
      {
        step_id: 'step-1',
        title: 'Add depth counter to AstWalker',
        description: 'Introduce max_depth parameter in AstWalker.visit_exports() defaulting to 4.',
        step_type: 'edit',
        expected_files: ['src/analyzer/ast_walker.py'],
        verification: ['Unit test verifying traversal halts at depth 4.'],
        risk_level: 'low',
      },
      {
        step_id: 'step-2',
        title: 'Integrate TokenBudgetManager check',
        description: 'Assert token threshold before serializing large symbol lists.',
        step_type: 'edit',
        expected_files: ['src/analyzer/token_budget.py'],
        verification: ['Boundary condition test exceeding 20k token limit.'],
        risk_level: 'medium',
      },
    ],
    expected_files_to_modify: ['src/analyzer/ast_walker.py', 'src/analyzer/token_budget.py'],
    tests_to_add: ['tests/test_token_budget_overflow.py'],
    validation_strategy: 'Automated test suite with synthetic 1,000 export mock files.',
    risks: ['Truncated symbol summaries may omit deep private helper classes.'],
    status: 'PENDING_APPROVAL',
    created_at: '2026-10-29T10:15:00.000Z',
    updated_at: '2026-10-29T10:15:00.000Z',
  };
  const task1Plans = new Map<number, TaskPlan>();
  task1Plans.set(1, plan1);
  plans.set(task1.task_id, task1Plans);

  events.set(task1.task_id, [
    {
      id: 'evt-101',
      task_id: task1.task_id,
      event_type: 'TASK_CREATED',
      description: 'Task intake created from GitHub Issue #42.',
      created_at: '2026-10-29T10:00:00.000Z',
    },
    {
      id: 'evt-102',
      task_id: task1.task_id,
      event_type: 'PLAN_GENERATED',
      description: 'Structured plan version 1 generated by AI Planner.',
      created_at: '2026-10-29T10:15:00.000Z',
    },
  ]);

  // Seed 2: Task in APPROVED state
  const task2: TaskDetailResponse = {
    task_id: 'task-seed-2',
    repository_id: DEFAULT_REPO_ID,
    title: 'Add TypeScript 5.4 Decorator AST Metadata',
    description: 'Support Stage 3 decorators in the symbol extractor and call graph builder.',
    status: TaskStatus.APPROVED,
    source: {
      type: 'USER_PROMPT',
      repository_id: DEFAULT_REPO_ID,
      base_revision: 'b2c3d4e5f6a1',
    },
    requirements: [
      {
        id: 'req-1',
        description: 'Parse decorator AST nodes and extract metadata attributes.',
        category: 'functional',
        target_files: ['src/extractor/ts_decorator.py'],
        acceptance_criteria: ['Decorator names, targets, and arguments extracted into symbol metadata.'],
      },
    ],
    assumptions: [],
    constraints: [],
    base_revision: 'b2c3d4e5f6a1',
    plan_version: 1,
    approved_plan_version: 1,
    repair_attempts_used: 0,
    repair_attempts_max: 3,
    created_at: '2026-10-28T09:00:00.000Z',
    updated_at: '2026-10-28T09:30:00.000Z',
  };
  tasks.set(task2.task_id, task2);

  const plan2: TaskPlan = {
    task_id: task2.task_id,
    plan_version: 1,
    base_revision: 'b2c3d4e5f6a1',
    summary: 'Add decorator visitor in ts_decorator.py and update symbol schema.',
    assumptions: [],
    unresolved_questions: [],
    relevant_files: ['src/extractor/ts_decorator.py'],
    steps: [
      {
        step_id: 'step-1',
        title: 'Add decorator AST visitor',
        description: 'Implement visit_Decorator node handler.',
        step_type: 'edit',
        expected_files: ['src/extractor/ts_decorator.py'],
        verification: ['ts_decorator unit tests.'],
      },
    ],
    expected_files_to_modify: ['src/extractor/ts_decorator.py'],
    tests_to_add: ['tests/test_ts_decorator.py'],
    validation_strategy: 'Run ts_decorator test fixtures.',
    risks: [],
    status: 'APPROVED',
    approved_by: 'lead_architect',
    approved_at: '2026-10-28T09:30:00.000Z',
    created_at: '2026-10-28T09:10:00.000Z',
    updated_at: '2026-10-28T09:30:00.000Z',
  };
  const task2Plans = new Map<number, TaskPlan>();
  task2Plans.set(1, plan2);
  plans.set(task2.task_id, task2Plans);

  approvals.set(task2.task_id, [
    {
      id: 'appr-201',
      task_id: task2.task_id,
      plan_version: 1,
      decision: 'APPROVED',
      user_id: 'lead_architect',
      notes: 'Approved without objections. Proceed with workspace setup.',
      created_at: '2026-10-28T09:30:00.000Z',
    },
  ]);

  events.set(task2.task_id, [
    {
      id: 'evt-201',
      task_id: task2.task_id,
      event_type: 'TASK_CREATED',
      description: 'Task intake created.',
      created_at: '2026-10-28T09:00:00.000Z',
    },
    {
      id: 'evt-202',
      task_id: task2.task_id,
      event_type: 'PLAN_GENERATED',
      description: 'Plan version 1 generated.',
      created_at: '2026-10-28T09:10:00.000Z',
    },
    {
      id: 'evt-203',
      task_id: task2.task_id,
      event_type: 'PLAN_APPROVED',
      description: 'Plan version 1 approved by lead_architect.',
      created_at: '2026-10-28T09:30:00.000Z',
    },
  ]);

  // Seed 3: Task in CREATED state (intake complete, no plan generated yet)
  const task3: TaskDetailResponse = {
    task_id: 'task-seed-3',
    repository_id: 'repo-2',
    title: 'Implement Strict Sandbox Policy for Docker Execution',
    description: 'Configure seccomp profile and disable unprivileged user namespaces in worker containers.',
    status: TaskStatus.CREATED,
    source: {
      type: 'BUG_FINDING',
      finding_id: 'sec-finding-901',
      repository_id: 'repo-2',
      base_revision: 'c3d4e5f6a1b2',
    },
    requirements: [
      {
        id: 'req-1',
        description: 'Enforce seccomp json profile in docker daemon startup config.',
        category: 'security',
        target_files: ['infra/docker/daemon.json', 'infra/docker/security.profile'],
        acceptance_criteria: ['Container denied sys_admin capabilities.'],
      },
    ],
    assumptions: [],
    constraints: [],
    base_revision: 'c3d4e5f6a1b2',
    plan_version: 1,
    approved_plan_version: null,
    repair_attempts_used: 0,
    repair_attempts_max: 3,
    created_at: '2026-10-29T14:00:00.000Z',
    updated_at: '2026-10-29T14:00:00.000Z',
  };
  tasks.set(task3.task_id, task3);
  events.set(task3.task_id, [
    {
      id: 'evt-301',
      task_id: task3.task_id,
      event_type: 'TASK_CREATED',
      description: 'Task intake created from security scan finding.',
      created_at: '2026-10-29T14:00:00.000Z',
    },
  ]);

  // Seed 4: Task in REJECTED state
  const task4: TaskDetailResponse = {
    task_id: 'task-seed-4',
    repository_id: DEFAULT_REPO_ID,
    title: 'Refactor Database Migration Runner to Async',
    description: 'Replace Alembic synchronous runner with custom asyncio task runner.',
    status: TaskStatus.REJECTED,
    source: {
      type: 'USER_PROMPT',
      repository_id: DEFAULT_REPO_ID,
      base_revision: 'd4e5f6a1b2c3',
    },
    requirements: [
      {
        id: 'req-1',
        description: 'Rewrite migration scripts to use asyncpg directly.',
        category: 'refactor',
        target_files: ['backend/migrations/env.py'],
        acceptance_criteria: ['Migrations run under asyncio loop.'],
      },
    ],
    assumptions: [],
    constraints: [],
    base_revision: 'd4e5f6a1b2c3',
    plan_version: 1,
    approved_plan_version: null,
    repair_attempts_used: 0,
    repair_attempts_max: 3,
    created_at: '2026-10-27T08:00:00.000Z',
    updated_at: '2026-10-27T08:45:00.000Z',
  };
  tasks.set(task4.task_id, task4);

  const plan4: TaskPlan = {
    task_id: task4.task_id,
    plan_version: 1,
    base_revision: 'd4e5f6a1b2c3',
    summary: 'Replace standard Alembic workflow with custom async runner.',
    assumptions: [],
    unresolved_questions: [],
    relevant_files: ['backend/migrations/env.py'],
    steps: [
      {
        step_id: 'step-1',
        title: 'Rewrite env.py for async',
        description: 'Bypass Alembic online migrations and use raw async connections.',
        step_type: 'edit',
        expected_files: ['backend/migrations/env.py'],
        verification: ['Run test migrations.'],
      },
    ],
    expected_files_to_modify: ['backend/migrations/env.py'],
    tests_to_add: [],
    validation_strategy: 'Run migration suite.',
    risks: ['Alembic autogenerate features will break.'],
    status: 'REJECTED',
    rejection_reason: 'Too risky for production: breaks Alembic autogenerate tooling.',
    created_at: '2026-10-27T08:15:00.000Z',
    updated_at: '2026-10-27T08:45:00.000Z',
  };
  const task4Plans = new Map<number, TaskPlan>();
  task4Plans.set(1, plan4);
  plans.set(task4.task_id, task4Plans);

  approvals.set(task4.task_id, [
    {
      id: 'appr-401',
      task_id: task4.task_id,
      plan_version: 1,
      decision: 'REJECTED',
      user_id: 'reviewer_1',
      reason: 'Too risky for production: breaks Alembic autogenerate tooling.',
      created_at: '2026-10-27T08:45:00.000Z',
    },
  ]);

  events.set(task4.task_id, [
    {
      id: 'evt-401',
      task_id: task4.task_id,
      event_type: 'TASK_CREATED',
      description: 'Task intake created.',
      created_at: '2026-10-27T08:00:00.000Z',
    },
    {
      id: 'evt-402',
      task_id: task4.task_id,
      event_type: 'PLAN_GENERATED',
      description: 'Plan version 1 generated.',
      created_at: '2026-10-27T08:15:00.000Z',
    },
    {
      id: 'evt-403',
      task_id: task4.task_id,
      event_type: 'PLAN_REJECTED',
      description: 'Plan version 1 rejected: Too risky for production.',
      created_at: '2026-10-27T08:45:00.000Z',
    },
  ]);

  // Seed 5: Task in EXECUTING state
  const task5: TaskDetailResponse = {
    task_id: 'task-seed-5',
    repository_id: DEFAULT_REPO_ID,
    title: 'Optimize Vector Similarity Query Index',
    description: 'Add HNSW indexing parameters for cosine distance on code snippet embeddings.',
    status: TaskStatus.EXECUTING,
    source: {
      type: 'USER_PROMPT',
      repository_id: DEFAULT_REPO_ID,
      base_revision: 'e5f6a1b2c3d4',
    },
    requirements: [
      {
        id: 'req-1',
        description: 'Configure HNSW index parameters (m=16, ef_construction=64).',
        category: 'functional',
        target_files: ['backend/app/db/indexes.sql'],
        acceptance_criteria: ['Index created without locking writes.'],
      },
    ],
    assumptions: [],
    constraints: [],
    base_revision: 'e5f6a1b2c3d4',
    plan_version: 1,
    approved_plan_version: 1,
    repair_attempts_used: 0,
    repair_attempts_max: 3,
    created_at: '2026-10-29T11:00:00.000Z',
    updated_at: '2026-10-29T11:45:00.000Z',
  };
  tasks.set(task5.task_id, task5);

  events.set(task5.task_id, [
    {
      id: 'evt-501',
      task_id: task5.task_id,
      event_type: 'TASK_CREATED',
      description: 'Task intake created.',
      created_at: '2026-10-29T11:00:00.000Z',
    },
    {
      id: 'evt-502',
      task_id: task5.task_id,
      event_type: 'PLAN_APPROVED',
      description: 'Plan version 1 approved.',
      created_at: '2026-10-29T11:20:00.000Z',
    },
    {
      id: 'evt-503',
      task_id: task5.task_id,
      event_type: 'WORKSPACE_ALLOCATED',
      description: 'Isolated workspace worktree prepared.',
      created_at: '2026-10-29T11:30:00.000Z',
    },
    {
      id: 'evt-504',
      task_id: task5.task_id,
      event_type: 'EXECUTION_STARTED',
      description: 'Code modification loop active.',
      created_at: '2026-10-29T11:45:00.000Z',
    },
  ]);

  // Seed 6: Task in DRAFT_PR_CREATED state (terminal happy path)
  const task6: TaskDetailResponse = {
    task_id: 'task-seed-6',
    repository_id: 'repo-2',
    title: 'Support Multi-Tenant Context Isolation in Vector DB',
    description: 'Partition vector collections by workspace ID to prevent cross-tenant data leakage.',
    status: TaskStatus.DRAFT_PR_CREATED,
    source: {
      type: 'GITHUB_ISSUE',
      issue_number: 89,
      issue_url: 'https://github.com/example/repo/issues/89',
      repository_id: 'repo-2',
      base_revision: 'f6a1b2c3d4e5',
    },
    requirements: [
      {
        id: 'req-1',
        description: 'Append tenant_id filter to all query payloads.',
        category: 'security',
        target_files: ['backend/app/services/vector_store.py'],
        acceptance_criteria: ['Queries without tenant_id rejected by store client.'],
      },
    ],
    assumptions: [],
    constraints: [],
    base_revision: 'f6a1b2c3d4e5',
    plan_version: 2,
    approved_plan_version: 2,
    repair_attempts_used: 1,
    repair_attempts_max: 3,
    created_at: '2026-10-26T07:00:00.000Z',
    updated_at: '2026-10-26T12:00:00.000Z',
  };
  tasks.set(task6.task_id, task6);

  tests.set(task6.task_id, {
    task_id: task6.task_id,
    runs: [
      {
        attempt: 1,
        command: 'pytest tests/test_vector_store.py',
        status: 'PASSED',
        exit_code: 0,
        duration_ms: 1240,
        tests_total: 12,
        tests_passed: 12,
        tests_failed: 0,
        output_summary: '12 passed in 1.24s',
        executed_at: '2026-10-26T11:15:00.000Z',
      },
    ],
    repair_attempts_used: 1,
    repair_attempts_max: 3,
  });

  verifications.set(task6.task_id, {
    task_id: task6.task_id,
    verified_revision: 'f6a1b2c3d4e5',
    status: 'PASS',
    checks: [
      {
        name: 'test_suite',
        status: 'PASSED',
        duration_ms: 1240,
        message: 'All unit & integration tests passed.',
        findings_count: 0,
        details: {},
      },
      {
        name: 'static_analysis',
        status: 'PASSED',
        duration_ms: 350,
        message: '0 lint or typing violations.',
        findings_count: 0,
        details: {},
      },
    ],
    blocking_findings: [],
    warnings: [],
    pr_summary: 'Tenant isolation enforced across all vector retrieval endpoints.',
    created_at: '2026-10-26T11:30:00.000Z',
  });

  events.set(task6.task_id, [
    {
      id: 'evt-601',
      task_id: task6.task_id,
      event_type: 'TASK_CREATED',
      description: 'Task intake created from GitHub Issue #89.',
      created_at: '2026-10-26T07:00:00.000Z',
    },
    {
      id: 'evt-602',
      task_id: task6.task_id,
      event_type: 'VERIFICATION_PASSED',
      description: 'Independent verification completed with PASS status.',
      created_at: '2026-10-26T11:30:00.000Z',
    },
    {
      id: 'evt-603',
      task_id: task6.task_id,
      event_type: 'DRAFT_PR_PUBLISHED',
      description: 'Draft Pull Request #143 published to GitHub.',
      created_at: '2026-10-26T12:00:00.000Z',
      details: { pr_url: 'https://github.com/example/repo/pull/143' },
    },
  ]);

  // Seed 7: Task in FAILED state
  const task7: TaskDetailResponse = {
    task_id: 'task-seed-7',
    repository_id: DEFAULT_REPO_ID,
    title: 'Automate End-to-End Test Container Teardown',
    description: 'Gracefully SIGTERM containers and prune orphaned volumes on test completion.',
    status: TaskStatus.FAILED,
    source: {
      type: 'USER_PROMPT',
      repository_id: DEFAULT_REPO_ID,
      base_revision: '0a1b2c3d4e5f',
    },
    requirements: [
      {
        id: 'req-1',
        description: 'Register cleanup signal handlers in runner entrypoint.',
        category: 'test',
        target_files: ['scripts/test_runner.sh'],
        acceptance_criteria: ['Zero leftover docker volumes after test crash.'],
      },
    ],
    assumptions: [],
    constraints: [],
    base_revision: '0a1b2c3d4e5f',
    plan_version: 1,
    approved_plan_version: 1,
    repair_attempts_used: 3,
    repair_attempts_max: 3,
    created_at: '2026-10-25T16:00:00.000Z',
    updated_at: '2026-10-25T17:30:00.000Z',
  };
  tasks.set(task7.task_id, task7);

  tests.set(task7.task_id, {
    task_id: task7.task_id,
    runs: [
      {
        attempt: 3,
        command: 'bash scripts/test_runner.sh',
        status: 'FAILED',
        exit_code: 137,
        duration_ms: 45000,
        tests_total: 8,
        tests_passed: 5,
        tests_failed: 3,
        output_summary: '3 tests failed. OOM killed runner container.',
        executed_at: '2026-10-25T17:25:00.000Z',
      },
    ],
    repair_attempts_used: 3,
    repair_attempts_max: 3,
  });

  events.set(task7.task_id, [
    {
      id: 'evt-701',
      task_id: task7.task_id,
      event_type: 'TASK_CREATED',
      description: 'Task intake created.',
      created_at: '2026-10-25T16:00:00.000Z',
    },
    {
      id: 'evt-702',
      task_id: task7.task_id,
      event_type: 'RETRY_BUDGET_EXHAUSTED',
      description: 'Repair attempts (3/3) exhausted without resolving test failures.',
      created_at: '2026-10-25T17:30:00.000Z',
    },
  ]);

  // Seed candidate GitHub issues for import
  issues.set(DEFAULT_REPO_ID, [
    {
      issue_number: 42,
      title: 'Fix Token Budget Overflow in AST Analyzer',
      body: 'AST recursive symbol traversal causes token exhaustion when analyzing modules with more than 500 export statements.',
      state: 'open',
      url: 'https://github.com/example/repo/issues/42',
      labels: ['bug', 'ast'],
      author: 'alice',
      created_at: '2026-10-28T09:00:00.000Z',
      is_imported: true, // Already imported as task-seed-1
    },
    {
      issue_number: 55,
      title: 'Add support for Python 3.12 type parameter syntax',
      body: 'Support PEP 695 type parameter syntax: type Alias[T] = list[T] and generic functions/classes in parser.',
      state: 'open',
      url: 'https://github.com/example/repo/issues/55',
      labels: ['enhancement', 'python312'],
      author: 'bob',
      created_at: '2026-10-29T08:30:00.000Z',
      is_imported: false,
    },
    {
      issue_number: 58,
      title: 'Memory leak in long-lived language server daemon',
      body: 'Heap profiling indicates LSP connection handler retains AST node caches across document close events.',
      state: 'open',
      url: 'https://github.com/example/repo/issues/58',
      labels: ['bug', 'performance'],
      author: 'charlie',
      created_at: '2026-10-29T12:00:00.000Z',
      is_imported: false,
    },
    {
      issue_number: 61,
      title: 'Implement incremental diff parsing for git worktrees',
      body: 'Parse only modified AST subtrees based on git diff line ranges instead of re-parsing whole files.',
      state: 'closed',
      url: 'https://github.com/example/repo/issues/61',
      labels: ['enhancement', 'git'],
      author: 'david',
      created_at: '2026-10-20T10:00:00.000Z',
      is_imported: false,
    },
  ]);

  return { tasks, plans, approvals, events, tests, verifications, issues };
}

let db = createInitialSeedData();

/**
 * Reset mock store to initial seed state. Useful for test isolation.
 */
export function resetMockStore(): void {
  db = createInitialSeedData();
}

/**
 * Access in-memory store for test verification.
 */
export function getMockStore(): MockDatabase {
  return db;
}

// ============================================================================
// Helper Validation Functions
// ============================================================================

function isPathUnsafe(path: string): boolean {
  if (!path || typeof path !== 'string') return true;
  const normalized = path.replace(/\\/g, '/');
  // Check for traversal or absolute paths
  if (normalized.startsWith('/') || normalized.startsWith('~') || /^[a-zA-Z]:/.test(normalized)) {
    return true;
  }
  const parts = normalized.split('/');
  return parts.includes('..') || parts.includes('.');
}

// ============================================================================
// MSW Handlers for All 13 Endpoints
// ============================================================================

export const taskHandlers = [
  // --------------------------------------------------------------------------
  // 1. POST /api/v1/tasks — Task Intake with segregated requirements
  // --------------------------------------------------------------------------
  http.post('*/api/v1/tasks', async ({ request }) => {
    const payload = (await request.json().catch(() => null)) as Partial<TaskCreateRequest> | null;

    if (!payload) {
      return HttpResponse.json(
        {
          error: {
            code: 'INVALID_REQUEST',
            message: 'Invalid JSON request payload.',
            retryable: false,
          },
        },
        { status: 422 }
      );
    }

    // Title validation: non-blank and length between 3 and 256
    const title = typeof payload.title === 'string' ? payload.title.trim() : '';
    if (!title || title.length < 3 || title.length > 256) {
      return HttpResponse.json(
        {
          error: {
            code: 'INVALID_REQUEST',
            message: 'Task title must contain non-whitespace characters and be between 3 and 256 characters.',
            retryable: false,
            details: { field: 'title', value: payload.title },
          },
        },
        { status: 422 }
      );
    }

    // Requirements validation: mandatory and min_length=1
    if (!Array.isArray(payload.requirements) || payload.requirements.length === 0) {
      return HttpResponse.json(
        {
          error: {
            code: 'INVALID_REQUEST',
            message: 'At least one requirement is required.',
            retryable: false,
            details: { field: 'requirements', value: payload.requirements },
          },
        },
        { status: 422 }
      );
    }

    // Unsafe path check in requirements and constraints
    for (const req of payload.requirements) {
      if (Array.isArray(req.target_files)) {
        for (const f of req.target_files) {
          if (isPathUnsafe(f)) {
            return HttpResponse.json(
              {
                error: {
                  code: 'INVALID_REQUEST',
                  message: `Unsafe relative path detected in target_file '${f}': path traversal or absolute paths are prohibited.`,
                  retryable: false,
                  details: { field: 'target_files', file: f },
                },
              },
              { status: 422 }
            );
          }
        }
      }
    }

    const forbiddenFiles = new Set<string>();
    if (Array.isArray(payload.constraints)) {
      for (const cst of payload.constraints) {
        if (Array.isArray(cst.forbidden_files)) {
          for (const f of cst.forbidden_files) {
            if (isPathUnsafe(f)) {
              return HttpResponse.json(
                {
                  error: {
                    code: 'INVALID_REQUEST',
                    message: `Unsafe forbidden_file '${f}': path traversal is prohibited.`,
                    retryable: false,
                  },
                },
                { status: 422 }
              );
            }
            forbiddenFiles.add(f);
          }
        }
      }
    }

    // Disjointness validation: target files must not overlap with forbidden files
    for (const req of payload.requirements) {
      if (Array.isArray(req.target_files)) {
        for (const f of req.target_files) {
          if (forbiddenFiles.has(f)) {
            return HttpResponse.json(
              {
                error: {
                  code: 'INVALID_REQUEST',
                  message: `Requirement '${req.id}' targets forbidden file(s): ${f}`,
                  retryable: false,
                  details: { requirement_id: req.id, file: f },
                },
              },
              { status: 422 }
            );
          }
        }
      }
    }

    const taskId = `task-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
    const now = new Date().toISOString();

    const newTask: TaskDetailResponse = {
      task_id: taskId,
      repository_id: payload.repository_id || DEFAULT_REPO_ID,
      title,
      description: payload.description || '',
      status: TaskStatus.CREATED,
      source: payload.source || {
        type: 'USER_PROMPT',
        repository_id: payload.repository_id || DEFAULT_REPO_ID,
      },
      requirements: payload.requirements,
      assumptions: payload.assumptions || [],
      constraints: payload.constraints || [],
      base_revision: payload.base_revision || null,
      plan_version: 1,
      approved_plan_version: null,
      repair_attempts_used: 0,
      repair_attempts_max: 3,
      created_at: now,
      updated_at: now,
    };

    db.tasks.set(taskId, newTask);

    const initialEvent: TaskEvent = {
      id: `evt-${Date.now()}`,
      task_id: taskId,
      event_type: 'TASK_CREATED',
      description: `Task intake registered: "${title}".`,
      created_at: now,
    };
    db.events.set(taskId, [initialEvent]);

    return HttpResponse.json(newTask, { status: 201 });
  }),

  // --------------------------------------------------------------------------
  // 2. GET /api/v1/tasks — Task Listing with filters
  // --------------------------------------------------------------------------
  http.get('*/api/v1/tasks', ({ request }) => {
    const url = new URL(request.url);
    const repoId = url.searchParams.get('repository_id');
    const status = url.searchParams.get('status') as TaskStatus | null;
    const search = url.searchParams.get('search')?.toLowerCase();
    const page = Math.max(1, parseInt(url.searchParams.get('page') || '1', 10));
    const pageSize = Math.max(1, parseInt(url.searchParams.get('page_size') || '20', 10));

    let items = Array.from(db.tasks.values());

    if (repoId) {
      items = items.filter((t) => t.repository_id === repoId);
    }
    if (status) {
      items = items.filter((t) => t.status === status);
    }
    if (search) {
      items = items.filter(
        (t) =>
          t.title.toLowerCase().includes(search) ||
          t.description.toLowerCase().includes(search) ||
          t.task_id.toLowerCase().includes(search)
      );
    }

    // Sort by updated_at descending
    items.sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());

    const total = items.length;
    const totalPages = Math.ceil(total / pageSize);
    const startIndex = (page - 1) * pageSize;
    const paginatedItems = items.slice(startIndex, startIndex + pageSize);

    const response: TaskListResponse = {
      items: paginatedItems,
      total,
      page,
      page_size: pageSize,
      total_pages: totalPages,
    };

    return HttpResponse.json(response, { status: 200 });
  }),

  // --------------------------------------------------------------------------
  // 3. GET /api/v1/tasks/:taskId — Single Task Detail
  // --------------------------------------------------------------------------
  http.get('*/api/v1/tasks/:taskId', ({ params }) => {
    const taskId = String(params.taskId);
    const task = db.tasks.get(taskId);

    if (!task) {
      return HttpResponse.json(
        {
          error: {
            code: 'TASK_NOT_FOUND',
            message: `Task '${taskId}' not found.`,
            retryable: false,
          },
        },
        { status: 404 }
      );
    }

    return HttpResponse.json(task, { status: 200 });
  }),

  // --------------------------------------------------------------------------
  // 4. POST /api/v1/tasks/:taskId/plan — Plan Synthesis / Re-planning
  // --------------------------------------------------------------------------
  http.post('*/api/v1/tasks/:taskId/plan', async ({ params, request }) => {
    const taskId = String(params.taskId);
    const task = db.tasks.get(taskId);

    if (!task) {
      return HttpResponse.json(
        {
          error: {
            code: 'TASK_NOT_FOUND',
            message: `Task '${taskId}' not found.`,
            retryable: false,
          },
        },
        { status: 404 }
      );
    }

    // Cannot generate plan if task is in active execution or finished
    if (
      task.status === TaskStatus.EXECUTING ||
      task.status === TaskStatus.PUBLISHING ||
      task.status === TaskStatus.DRAFT_PR_CREATED
    ) {
      return HttpResponse.json(
        {
          error: {
            code: 'INVALID_STATE_TRANSITION',
            message: `Cannot generate or revise plan while task is in '${task.status}' status.`,
            retryable: false,
          },
        },
        { status: 409 }
      );
    }

    const payload = (await request.json().catch(() => ({}))) as {
      regenerate?: boolean;
      prompt_instructions?: string;
    };

    const taskPlans = db.plans.get(taskId) || new Map<number, TaskPlan>();
    const nextVersion = taskPlans.size > 0 ? Math.max(...Array.from(taskPlans.keys())) + 1 : 1;
    const now = new Date().toISOString();

    const newPlan: TaskPlan = {
      task_id: taskId,
      plan_version: nextVersion,
      base_revision: task.base_revision || 'main-head-sha',
      summary: payload.prompt_instructions
        ? `Custom plan synthesized: ${payload.prompt_instructions}`
        : `Structured implementation plan version ${nextVersion} for: ${task.title}`,
      problem_statement: task.description,
      assumptions: task.assumptions.map((a) => a.description),
      unresolved_questions: task.assumptions.filter((a) => a.unresolved).map((a) => a.description),
      relevant_files: task.requirements.flatMap((r) => r.target_files),
      steps: task.requirements.map((req, idx) => ({
        step_id: `step-${idx + 1}`,
        title: `Implement ${req.id}: ${req.description.slice(0, 40)}...`,
        description: req.description,
        step_type: req.category === 'bug_fix' ? 'edit' : 'create',
        expected_files: req.target_files,
        verification: req.acceptance_criteria,
        risk_level: 'low',
      })),
      expected_files_to_modify: task.requirements.flatMap((r) => r.target_files),
      tests_to_add: [`tests/test_${taskId.replace(/[^a-zA-Z0-9]/g, '_')}.py`],
      validation_strategy: 'Automated test suite execution and AST verification.',
      risks: ['Edge case input variation may require supplementary repair iterations.'],
      status: 'PENDING_APPROVAL',
      created_at: now,
      updated_at: now,
    };

    taskPlans.set(nextVersion, newPlan);
    db.plans.set(taskId, taskPlans);

    // Update task lifecycle state:
    // Plan revision invalidates prior approvals and updates task to PENDING_APPROVAL
    task.status = TaskStatus.PENDING_APPROVAL;
    task.plan_version = nextVersion;
    task.approved_plan_version = null;
    task.updated_at = now;

    // Record audit event
    const taskEvents = db.events.get(taskId) || [];
    taskEvents.push({
      id: `evt-${Date.now()}`,
      task_id: taskId,
      event_type: nextVersion > 1 ? 'PLAN_REVISED' : 'PLAN_GENERATED',
      description:
        nextVersion > 1
          ? `Plan revised to version ${nextVersion} (prior approvals invalidated).`
          : `Implementation plan version 1 generated and submitted for approval.`,
      created_at: now,
    });
    db.events.set(taskId, taskEvents);

    return HttpResponse.json(newPlan, { status: 201 });
  }),

  // --------------------------------------------------------------------------
  // 5. GET /api/v1/tasks/:taskId/plan — Retrieve Active or Specified Plan Version
  // --------------------------------------------------------------------------
  http.get('*/api/v1/tasks/:taskId/plan', ({ params, request }) => {
    const taskId = String(params.taskId);
    const task = db.tasks.get(taskId);

    if (!task) {
      return HttpResponse.json(
        {
          error: {
            code: 'TASK_NOT_FOUND',
            message: `Task '${taskId}' not found.`,
            retryable: false,
          },
        },
        { status: 404 }
      );
    }

    const url = new URL(request.url);
    const versionParam = url.searchParams.get('version');
    const taskPlans = db.plans.get(taskId);

    if (!taskPlans || taskPlans.size === 0) {
      return HttpResponse.json(
        {
          error: {
            code: 'NOT_FOUND',
            message: `No plan has been generated yet for task '${taskId}'.`,
            retryable: false,
          },
        },
        { status: 404 }
      );
    }

    if (versionParam) {
      const requestedVersion = parseInt(versionParam, 10);
      const plan = taskPlans.get(requestedVersion);
      if (!plan) {
        return HttpResponse.json(
          {
            error: {
              code: 'NOT_FOUND',
              message: `Plan version ${requestedVersion} not found for task '${taskId}'.`,
              retryable: false,
            },
          },
          { status: 404 }
        );
      }
      return HttpResponse.json(plan, { status: 200 });
    }

    // Default: return the plan matching current task.plan_version or highest version
    const activePlan = taskPlans.get(task.plan_version) || taskPlans.get(Math.max(...Array.from(taskPlans.keys())));
    if (!activePlan) {
      return HttpResponse.json(
        {
          error: {
            code: 'NOT_FOUND',
            message: 'Active plan not found.',
            retryable: false,
          },
        },
        { status: 404 }
      );
    }

    return HttpResponse.json(activePlan, { status: 200 });
  }),

  // --------------------------------------------------------------------------
  // 6. POST /api/v1/tasks/:taskId/approve — Plan Approval Gate
  // --------------------------------------------------------------------------
  http.post('*/api/v1/tasks/:taskId/approve', async ({ params, request }) => {
    const taskId = String(params.taskId);
    const task = db.tasks.get(taskId);

    if (!task) {
      return HttpResponse.json(
        {
          error: {
            code: 'TASK_NOT_FOUND',
            message: `Task '${taskId}' not found.`,
            retryable: false,
          },
        },
        { status: 404 }
      );
    }

    const payload = (await request.json().catch(() => ({}))) as {
      plan_version?: number;
      notes?: string;
      approved_by?: string;
    };

    // Strict Lifecycle Guardrail: Must be in PENDING_APPROVAL status
    if (task.status !== TaskStatus.PENDING_APPROVAL) {
      return HttpResponse.json(
        {
          error: {
            code: 'INVALID_STATE_TRANSITION',
            message: `Cannot approve plan from status '${task.status}'. Approval is only permitted when status is 'PENDING_APPROVAL'.`,
            retryable: false,
          },
        },
        { status: 409 }
      );
    }

    // Concurrency / Version Mismatch Check
    if (typeof payload.plan_version !== 'number' || payload.plan_version !== task.plan_version) {
      return HttpResponse.json(
        {
          error: {
            code: 'PLAN_VERSION_MISMATCH',
            message: `The plan has been revised. Submitted version is ${payload.plan_version}, but current active plan is version ${task.plan_version}. Please refresh and review the updated plan.`,
            retryable: false,
            details: {
              submitted_version: payload.plan_version,
              current_version: task.plan_version,
            },
          },
        },
        { status: 409 }
      );
    }

    const now = new Date().toISOString();

    // Transition task to APPROVED
    task.status = TaskStatus.APPROVED;
    task.approved_plan_version = payload.plan_version;
    task.updated_at = now;

    // Update active plan status
    const taskPlans = db.plans.get(taskId);
    if (taskPlans) {
      const activePlan = taskPlans.get(payload.plan_version);
      if (activePlan) {
        activePlan.status = 'APPROVED';
        activePlan.approved_by = payload.approved_by || 'Human Reviewer';
        activePlan.approved_at = now;
        activePlan.updated_at = now;
      }
    }

    // Record approval audit record
    const taskApprovals = db.approvals.get(taskId) || [];
    taskApprovals.push({
      id: `appr-${Date.now()}`,
      task_id: taskId,
      plan_version: payload.plan_version,
      decision: 'APPROVED',
      user_id: payload.approved_by || 'Human Reviewer',
      notes: payload.notes || 'Plan approved.',
      created_at: now,
    });
    db.approvals.set(taskId, taskApprovals);

    // Record timeline event
    const taskEvents = db.events.get(taskId) || [];
    taskEvents.push({
      id: `evt-${Date.now()}`,
      task_id: taskId,
      event_type: 'PLAN_APPROVED',
      description: payload.notes
        ? `Plan version ${payload.plan_version} approved: ${payload.notes}`
        : `Plan version ${payload.plan_version} approved by ${payload.approved_by || 'reviewer'}.`,
      details: { notes: payload.notes },
      created_at: now,
    });
    db.events.set(taskId, taskEvents);

    return HttpResponse.json(task, { status: 200 });
  }),

  // --------------------------------------------------------------------------
  // 7. POST /api/v1/tasks/:taskId/reject — Plan Rejection Gate
  // --------------------------------------------------------------------------
  http.post('*/api/v1/tasks/:taskId/reject', async ({ params, request }) => {
    const taskId = String(params.taskId);
    const task = db.tasks.get(taskId);

    if (!task) {
      return HttpResponse.json(
        {
          error: {
            code: 'TASK_NOT_FOUND',
            message: `Task '${taskId}' not found.`,
            retryable: false,
          },
        },
        { status: 404 }
      );
    }

    const payload = (await request.json().catch(() => ({}))) as {
      plan_version?: number;
      reason?: string;
      rejected_by?: string;
    };

    // Strict Lifecycle Guardrail: Must be in PENDING_APPROVAL status
    if (task.status !== TaskStatus.PENDING_APPROVAL) {
      return HttpResponse.json(
        {
          error: {
            code: 'INVALID_STATE_TRANSITION',
            message: `Cannot reject plan from status '${task.status}'. Rejection is only permitted when status is 'PENDING_APPROVAL'.`,
            retryable: false,
          },
        },
        { status: 409 }
      );
    }

    // Concurrency / Version Mismatch Check
    if (typeof payload.plan_version !== 'number' || payload.plan_version !== task.plan_version) {
      return HttpResponse.json(
        {
          error: {
            code: 'PLAN_VERSION_MISMATCH',
            message: `The plan has been revised. Submitted version is ${payload.plan_version}, but current active plan is version ${task.plan_version}. Please refresh and review the updated plan.`,
            retryable: false,
            details: {
              submitted_version: payload.plan_version,
              current_version: task.plan_version,
            },
          },
        },
        { status: 409 }
      );
    }

    const now = new Date().toISOString();

    // Transition task to REJECTED
    task.status = TaskStatus.REJECTED;
    task.updated_at = now;

    // Update plan status
    const taskPlans = db.plans.get(taskId);
    if (taskPlans) {
      const activePlan = taskPlans.get(payload.plan_version);
      if (activePlan) {
        activePlan.status = 'REJECTED';
        activePlan.rejection_reason = payload.reason || 'Rejected by reviewer.';
        activePlan.updated_at = now;
      }
    }

    // Record audit record
    const taskApprovals = db.approvals.get(taskId) || [];
    taskApprovals.push({
      id: `appr-${Date.now()}`,
      task_id: taskId,
      plan_version: payload.plan_version,
      decision: 'REJECTED',
      user_id: payload.rejected_by || 'Human Reviewer',
      reason: payload.reason || 'Plan rejected.',
      created_at: now,
    });
    db.approvals.set(taskId, taskApprovals);

    // Record timeline event
    const taskEvents = db.events.get(taskId) || [];
    taskEvents.push({
      id: `evt-${Date.now()}`,
      task_id: taskId,
      event_type: 'PLAN_REJECTED',
      description: `Plan version ${payload.plan_version} rejected: ${payload.reason || 'No reason provided'}.`,
      details: { reason: payload.reason },
      created_at: now,
    });
    db.events.set(taskId, taskEvents);

    return HttpResponse.json(task, { status: 200 });
  }),

  // --------------------------------------------------------------------------
  // 8. POST /api/v1/tasks/:taskId/execute — Backend Execution Dispatch
  // --------------------------------------------------------------------------
  http.post('*/api/v1/tasks/:taskId/execute', ({ params }) => {
    const taskId = String(params.taskId);
    const task = db.tasks.get(taskId);

    if (!task) {
      return HttpResponse.json(
        {
          error: {
            code: 'TASK_NOT_FOUND',
            message: `Task '${taskId}' not found.`,
            retryable: false,
          },
        },
        { status: 404 }
      );
    }

    // Docs/week3.md §7.2: PENDING_APPROVAL cannot transition directly to EXECUTING
    if (task.status === TaskStatus.PENDING_APPROVAL) {
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
    }

    if (task.status !== TaskStatus.APPROVED) {
      return HttpResponse.json(
        {
          error: {
            code: 'INVALID_STATE_TRANSITION',
            message: `Cannot execute task in status '${task.status}'. Status must be 'APPROVED'.`,
            retryable: false,
          },
        },
        { status: 409 }
      );
    }

    const now = new Date().toISOString();
    task.status = TaskStatus.WORKSPACE_SETUP;
    task.updated_at = now;

    const taskEvents = db.events.get(taskId) || [];
    taskEvents.push({
      id: `evt-${Date.now()}`,
      task_id: taskId,
      event_type: 'WORKSPACE_SETUP',
      description: 'Workspace allocation initiated.',
      created_at: now,
    });
    db.events.set(taskId, taskEvents);

    return HttpResponse.json(task, { status: 200 });
  }),

  // --------------------------------------------------------------------------
  // 9. GET /api/v1/tasks/:taskId/events — Chronological Timeline Events
  // --------------------------------------------------------------------------
  http.get('*/api/v1/tasks/:taskId/events', ({ params, request }) => {
    const taskId = String(params.taskId);
    const task = db.tasks.get(taskId);

    if (!task) {
      return HttpResponse.json(
        {
          error: {
            code: 'TASK_NOT_FOUND',
            message: `Task '${taskId}' not found.`,
            retryable: false,
          },
        },
        { status: 404 }
      );
    }

    const url = new URL(request.url);
    const limit = url.searchParams.get('limit') ? parseInt(url.searchParams.get('limit')!, 10) : undefined;
    const since = url.searchParams.get('since');

    let events = db.events.get(taskId) || [];

    if (since) {
      const sinceTime = new Date(since).getTime();
      events = events.filter((e) => new Date(e.created_at).getTime() >= sinceTime);
    }

    // Sort chronologically (oldest to newest for timeline)
    events = [...events].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());

    if (limit && limit > 0) {
      events = events.slice(-limit);
    }

    const response: TaskEventListResponse = {
      items: events,
      total: events.length,
    };

    return HttpResponse.json(response, { status: 200 });
  }),

  // --------------------------------------------------------------------------
  // 10. GET /api/v1/tasks/:taskId/tests — Test Telemetry & Repair Attempts
  // --------------------------------------------------------------------------
  http.get('*/api/v1/tasks/:taskId/tests', ({ params }) => {
    const taskId = String(params.taskId);
    const task = db.tasks.get(taskId);

    if (!task) {
      return HttpResponse.json(
        {
          error: {
            code: 'TASK_NOT_FOUND',
            message: `Task '${taskId}' not found.`,
            retryable: false,
          },
        },
        { status: 404 }
      );
    }

    const testResults = db.tests.get(taskId) || {
      task_id: taskId,
      runs: [],
      repair_attempts_used: task.repair_attempts_used,
      repair_attempts_max: task.repair_attempts_max,
    };

    return HttpResponse.json(testResults, { status: 200 });
  }),

  // --------------------------------------------------------------------------
  // 11. GET /api/v1/tasks/:taskId/verification — Verification Outcome
  // --------------------------------------------------------------------------
  http.get('*/api/v1/tasks/:taskId/verification', ({ params }) => {
    const taskId = String(params.taskId);
    const task = db.tasks.get(taskId);

    if (!task) {
      return HttpResponse.json(
        {
          error: {
            code: 'TASK_NOT_FOUND',
            message: `Task '${taskId}' not found.`,
            retryable: false,
          },
        },
        { status: 404 }
      );
    }

    const verification = db.verifications.get(taskId);
    if (!verification) {
      return HttpResponse.json(
        {
          error: {
            code: 'NOT_FOUND',
            message: `Independent verification has not yet run for task '${taskId}'.`,
            retryable: false,
          },
        },
        { status: 404 }
      );
    }

    return HttpResponse.json(verification, { status: 200 });
  }),

  // --------------------------------------------------------------------------
  // 12. POST /api/v1/repositories/:repositoryId/issues/import — GitHub Issue Import
  // --------------------------------------------------------------------------
  http.post('*/api/v1/repositories/:repositoryId/issues/import', async ({ params, request }) => {
    const repoId = String(params.repositoryId);
    const payload = (await request.json().catch(() => ({}))) as Partial<IssueImportRequest>;

    const issueNumber = payload.issue_number;
    if (typeof issueNumber !== 'number' || issueNumber < 1 || issueNumber > 1_000_000) {
      return HttpResponse.json(
        {
          error: {
            code: 'INVALID_REQUEST',
            message: 'Valid issue_number between 1 and 1,000,000 is required.',
            retryable: false,
          },
        },
        { status: 422 }
      );
    }

    // Check if issue is already imported across tasks
    const existingTask = Array.from(db.tasks.values()).find(
      (t) =>
        t.repository_id === repoId &&
        t.source.type === 'GITHUB_ISSUE' &&
        t.source.issue_number === issueNumber
    );

    if (existingTask) {
      return HttpResponse.json(
        {
          error: {
            code: 'CONFLICT',
            message: `Issue #${issueNumber} has already been imported into task '${existingTask.task_id}'.`,
            retryable: false,
            details: { existing_task_id: existingTask.task_id },
          },
        },
        { status: 409 }
      );
    }

    // Look up or synthesize issue details
    const repoIssues = db.issues.get(repoId) || [];
    const issue = repoIssues.find((i) => i.issue_number === issueNumber);

    const title = issue?.title || `Imported Issue #${issueNumber}`;
    const description = issue?.body || `Imported from GitHub repository issue #${issueNumber}`;
    const issueUrl = issue?.url || `https://github.com/example/repo/issues/${issueNumber}`;

    if (issue) {
      issue.is_imported = true;
    }

    const taskId = `task-issue-${issueNumber}-${Date.now()}`;
    const now = new Date().toISOString();

    const importedTask: TaskDetailResponse = {
      task_id: taskId,
      repository_id: repoId,
      title,
      description,
      status: TaskStatus.CREATED,
      source: {
        type: 'GITHUB_ISSUE',
        issue_number: issueNumber,
        issue_url: issueUrl,
        repository_id: repoId,
      },
      requirements: [
        {
          id: 'req-1',
          description: `Resolve GitHub Issue #${issueNumber}: ${title}`,
          category: 'functional',
          target_files: ['src/index.ts'],
          acceptance_criteria: ['Implementation addresses issue criteria and passes test suite.'],
        },
      ],
      assumptions: [],
      constraints: [],
      base_revision: null,
      plan_version: 1,
      approved_plan_version: null,
      repair_attempts_used: 0,
      repair_attempts_max: 3,
      created_at: now,
      updated_at: now,
    };

    db.tasks.set(taskId, importedTask);

    const importEvent: TaskEvent = {
      id: `evt-${Date.now()}`,
      task_id: taskId,
      event_type: 'TASK_CREATED',
      description: `Task created from imported GitHub Issue #${issueNumber}.`,
      created_at: now,
    };
    db.events.set(taskId, [importEvent]);

    const response: IssueImportResponse = {
      task_id: taskId,
      source: importedTask.source,
      title,
      status: TaskStatus.CREATED,
    };

    return HttpResponse.json(response, { status: 201 });
  }),

  // --------------------------------------------------------------------------
  // 13. GET /api/v1/repositories/:repositoryId/issues — Candidate GitHub Issues
  // --------------------------------------------------------------------------
  http.get('*/api/v1/repositories/:repositoryId/issues', ({ params, request }) => {
    const repoId = String(params.repositoryId);
    const url = new URL(request.url);
    const stateFilter = url.searchParams.get('state') || 'open';
    const page = Math.max(1, parseInt(url.searchParams.get('page') || '1', 10));
    const pageSize = Math.max(1, parseInt(url.searchParams.get('page_size') || '20', 10));

    let issues = db.issues.get(repoId) || [];

    // Ensure is_imported flag is kept up to date against current tasks
    const importedIssueNumbers = new Set(
      Array.from(db.tasks.values())
        .filter((t) => t.repository_id === repoId && t.source.type === 'GITHUB_ISSUE')
        .map((t) => t.source.issue_number)
    );

    issues = issues.map((i) => ({
      ...i,
      is_imported: importedIssueNumbers.has(i.issue_number),
    }));

    if (stateFilter !== 'all') {
      issues = issues.filter((i) => i.state === stateFilter);
    }

    const total = issues.length;
    const startIndex = (page - 1) * pageSize;
    const paginatedIssues = issues.slice(startIndex, startIndex + pageSize);

    const response: GitHubIssueListResponse = {
      items: paginatedIssues,
      total,
      page,
      page_size: pageSize,
    };

    return HttpResponse.json(response, { status: 200 });
  }),

  // 14. GET /api/v1/repositories - Repository List for Task Forms & Filters
  // --------------------------------------------------------------------------
  http.get('*/api/v1/repositories', () => {
    return HttpResponse.json([
      {
        id: 'repo-1',
        name: 'ai-platform',
        full_name: 'acme/ai-platform',
        owner: 'acme',
        description: 'AI platform core repo',
        default_branch: 'main',
        is_private: false,
        status: 'READY',
      },
      {
        id: 'repo-2',
        name: 'web-frontend',
        full_name: 'acme/web-frontend',
        owner: 'acme',
        description: 'Frontend client',
        default_branch: 'main',
        is_private: false,
        status: 'READY',
      },
    ]);
  }),
];
