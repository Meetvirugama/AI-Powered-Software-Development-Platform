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
  canTransition,
  canCancelTask,
  WorkspaceStatus,
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
  type WorkspaceMetadata,
  type TaskDiffRanges,
  type WorkspaceRepairBudgetStatus,
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
  workspaces: Map<string, WorkspaceMetadata>;
  diffs: Map<string, TaskDiffRanges>;
  repairBudgets: Map<string, WorkspaceRepairBudgetStatus>;
  scenarioTasks: Map<string, TaskDetailResponse>;
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
  const workspaces = new Map<string, WorkspaceMetadata>();
  const diffs = new Map<string, TaskDiffRanges>();
  const repairBudgets = new Map<string, WorkspaceRepairBudgetStatus>();
  const scenarioTasks = new Map<string, TaskDetailResponse>();

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

  // --------------------------------------------------------------------------
  // Seed Workspaces, Diffs and Repair Budgets for Existing Tasks
  // --------------------------------------------------------------------------

  // task-seed-5: Active execution workspace and diff
  workspaces.set(task5.task_id, {
    workspace_id: 'ws-seed-5',
    task_id: task5.task_id,
    repository_id: DEFAULT_REPO_ID,
    base_revision: 'e5f6a1b2c3d4',
    branch_name: 'agent/task-seed-5',
    workspace_path: '/sandboxes/task-seed-5',
    status: WorkspaceStatus.IN_USE,
    isolation_type: 'git_worktree',
    resource_limits: {
      timeout_seconds: 60,
      max_disk_bytes: 524288000,
      max_file_size_bytes: 5242880,
      max_files_modified: 50,
      network_egress_allowed: false,
    },
    created_at: '2026-10-29T11:30:00.000Z',
    updated_at: '2026-10-29T11:45:00.000Z',
  });

  diffs.set(task5.task_id, {
    task_id: task5.task_id,
    repository_id: DEFAULT_REPO_ID,
    base_branch: 'main',
    head_branch: 'agent/task-seed-5',
    total_files_changed: 1,
    total_additions: 12,
    total_deletions: 2,
    files: [
      {
        file_path: 'backend/app/db/indexes.sql',
        status: 'modified',
        additions: 12,
        deletions: 2,
        patch:
          '@@ -45,2 +45,12 @@\n-CREATE INDEX idx_vec ON embeddings (vector);\n+CREATE INDEX idx_vec_hnsw ON embeddings USING hnsw (vector vector_cosine_ops)\n+WITH (m = 16, ef_construction = 64);',
        diff_ranges: [{ start_line: 45, end_line: 57, change_type: 'modified' }],
      },
    ],
  });

  // task-seed-7: Stopped workspace and exhausted repair budget
  workspaces.set(task7.task_id, {
    workspace_id: 'ws-seed-7',
    task_id: task7.task_id,
    repository_id: DEFAULT_REPO_ID,
    base_revision: '0a1b2c3d4e5f',
    branch_name: 'agent/task-seed-7',
    workspace_path: '/sandboxes/task-seed-7',
    status: WorkspaceStatus.STOPPED,
    isolation_type: 'git_worktree',
    created_at: '2026-10-25T16:10:00.000Z',
    updated_at: '2026-10-25T17:30:00.000Z',
    cleaned_at: '2026-10-25T17:30:00.000Z',
  });

  repairBudgets.set(task7.task_id, {
    task_id: task7.task_id,
    repair_attempts_used: 3,
    repair_attempts_max: 3,
    is_budget_exhausted: true,
    is_eligible_for_repair: false,
    last_attempt_at: '2026-10-25T17:30:00.000Z',
    history: [
      {
        attempt_number: 1,
        task_id: task7.task_id,
        timestamp: '2026-10-25T16:30:00.000Z',
        patch_summary: 'Add SIGTERM signal traps in entrypoint script',
        patch_hash: 'patch-001',
        workspace_revision: 'rev-001',
        test_status_before: 'FAILED',
        test_status_after: 'FAILED',
        success: false,
      },
      {
        attempt_number: 2,
        task_id: task7.task_id,
        timestamp: '2026-10-25T17:00:00.000Z',
        patch_summary: 'Increase container stop timeout to 15s',
        patch_hash: 'patch-002',
        workspace_revision: 'rev-002',
        test_status_before: 'FAILED',
        test_status_after: 'FAILED',
        success: false,
      },
      {
        attempt_number: 3,
        task_id: task7.task_id,
        timestamp: '2026-10-25T17:25:00.000Z',
        patch_summary: 'Prune orphaned container network namespaces',
        patch_hash: 'patch-003',
        workspace_revision: 'rev-003',
        test_status_before: 'FAILED',
        test_status_after: 'FAILED',
        success: false,
      },
    ],
  });

  // --------------------------------------------------------------------------
  // Deterministic Scenarios (Docs/week3.md §11 & Day 3/4 Workflow Requirements)
  // --------------------------------------------------------------------------

  // Scenario 1: Approved task starting execution
  const taskExecApproved: TaskDetailResponse = {
    task_id: 'task-exec-approved',
    repository_id: DEFAULT_REPO_ID,
    title: 'Ready for Execution Start',
    description: 'Approved task ready to start execution and allocate workspace sandbox.',
    status: TaskStatus.APPROVED,
    source: { type: 'USER_PROMPT', repository_id: DEFAULT_REPO_ID, base_revision: 'base-rev-1' },
    requirements: [
      {
        id: 'req-1',
        description: 'Verify execution start transitions task to WORKSPACE_SETUP.',
        category: 'functional',
        target_files: ['src/core/engine.py'],
        acceptance_criteria: ['Workspace created with status READY or CREATING.'],
      },
    ],
    assumptions: [],
    constraints: [],
    base_revision: 'base-rev-1',
    plan_version: 1,
    approved_plan_version: 1,
    repair_attempts_used: 0,
    repair_attempts_max: 3,
    created_at: '2026-10-20T09:00:00.000Z',
    updated_at: '2026-10-20T09:15:00.000Z',
  };
  scenarioTasks.set(taskExecApproved.task_id, taskExecApproved);
  const planExecApproved: TaskPlan = {
    task_id: taskExecApproved.task_id,
    plan_version: 1,
    base_revision: 'base-rev-1',
    summary: 'Plan for approved execution test.',
    assumptions: [],
    unresolved_questions: [],
    relevant_files: ['src/core/engine.py'],
    steps: [
      {
        step_id: 'step-1',
        title: 'Initial step',
        description: 'Modify engine.py',
        step_type: 'edit',
        expected_files: ['src/core/engine.py'],
        verification: ['pytest'],
      },
    ],
    expected_files_to_modify: ['src/core/engine.py'],
    tests_to_add: [],
    validation_strategy: 'Automated tests',
    risks: [],
    status: 'APPROVED',
  };
  const taskExecApprovedPlans = new Map<number, TaskPlan>();
  taskExecApprovedPlans.set(1, planExecApproved);
  plans.set(taskExecApproved.task_id, taskExecApprovedPlans);
  events.set(taskExecApproved.task_id, [
    {
      id: 'evt-ea-1',
      task_id: taskExecApproved.task_id,
      event_type: 'PLAN_APPROVED',
      description: 'Plan approved by reviewer.',
      created_at: '2026-10-20T09:15:00.000Z',
    },
  ]);

  // Scenario 2: Workspace setup in progress
  const taskExecSetup: TaskDetailResponse = {
    ...taskExecApproved,
    task_id: 'task-exec-setup',
    title: 'Workspace Setup In Progress',
    status: TaskStatus.WORKSPACE_SETUP,
    updated_at: '2026-10-20T09:20:00.000Z',
  };
  scenarioTasks.set(taskExecSetup.task_id, taskExecSetup);
  workspaces.set(taskExecSetup.task_id, {
    workspace_id: 'ws-setup-1',
    task_id: taskExecSetup.task_id,
    repository_id: DEFAULT_REPO_ID,
    base_revision: 'base-rev-1',
    branch_name: 'agent/task-exec-setup',
    status: WorkspaceStatus.CREATING,
    isolation_type: 'git_worktree',
    created_at: '2026-10-20T09:20:00.000Z',
    updated_at: '2026-10-20T09:20:00.000Z',
  });
  events.set(taskExecSetup.task_id, [
    {
      id: 'evt-es-1',
      task_id: taskExecSetup.task_id,
      event_type: 'WORKSPACE_SETUP',
      description: 'Allocating isolated Git worktree workspace.',
      created_at: '2026-10-20T09:20:00.000Z',
    },
  ]);

  // Scenario 3: Workspace ready and branch available
  const taskExecReady: TaskDetailResponse = {
    ...taskExecApproved,
    task_id: 'task-exec-ready',
    title: 'Workspace Ready and Branch Available',
    status: TaskStatus.WORKSPACE_SETUP,
    updated_at: '2026-10-20T09:25:00.000Z',
  };
  scenarioTasks.set(taskExecReady.task_id, taskExecReady);
  workspaces.set(taskExecReady.task_id, {
    workspace_id: 'ws-ready-1',
    task_id: taskExecReady.task_id,
    repository_id: DEFAULT_REPO_ID,
    base_revision: 'base-rev-1',
    branch_name: 'agent/task-exec-ready',
    workspace_path: '/sandboxes/task-exec-ready',
    status: WorkspaceStatus.READY,
    isolation_type: 'git_worktree',
    resource_limits: {
      timeout_seconds: 60,
      max_disk_bytes: 524288000,
      max_file_size_bytes: 5242880,
      max_files_modified: 50,
      network_egress_allowed: false,
    },
    created_at: '2026-10-20T09:20:00.000Z',
    updated_at: '2026-10-20T09:25:00.000Z',
  });
  events.set(taskExecReady.task_id, [
    {
      id: 'evt-er-1',
      task_id: taskExecReady.task_id,
      event_type: 'WORKSPACE_ALLOCATED',
      description: 'Workspace worktree ready on branch agent/task-exec-ready.',
      created_at: '2026-10-20T09:25:00.000Z',
    },
    {
      id: 'evt-er-2',
      task_id: taskExecReady.task_id,
      event_type: 'BRANCH_SETUP',
      description: 'Checked out agent/task-exec-ready at base revision base-rev-1.',
      created_at: '2026-10-20T09:25:00.000Z',
    },
  ]);

  // Scenario 4: Workspace creation failure
  const taskExecFailedWs: TaskDetailResponse = {
    ...taskExecApproved,
    task_id: 'task-exec-failed-ws',
    title: 'Workspace Allocation Failed',
    status: TaskStatus.FAILED,
    updated_at: '2026-10-20T09:30:00.000Z',
  };
  scenarioTasks.set(taskExecFailedWs.task_id, taskExecFailedWs);
  workspaces.set(taskExecFailedWs.task_id, {
    workspace_id: 'ws-fail-1',
    task_id: taskExecFailedWs.task_id,
    repository_id: DEFAULT_REPO_ID,
    base_revision: 'base-rev-1',
    branch_name: 'agent/task-exec-failed-ws',
    status: WorkspaceStatus.FAILED,
    error_message: 'Failed to create Git worktree: permission denied or disk quota exceeded.',
    created_at: '2026-10-20T09:20:00.000Z',
    updated_at: '2026-10-20T09:30:00.000Z',
  });
  events.set(taskExecFailedWs.task_id, [
    {
      id: 'evt-ef-1',
      task_id: taskExecFailedWs.task_id,
      event_type: 'WORKSPACE_CREATION_FAILED',
      description: 'Failed to create Git worktree: permission denied or disk quota exceeded.',
      created_at: '2026-10-20T09:30:00.000Z',
    },
  ]);

  // Scenario 5: Execution in progress
  const taskExecInProgress: TaskDetailResponse = {
    ...taskExecApproved,
    task_id: 'task-exec-in-progress',
    title: 'Execution In Progress',
    status: TaskStatus.EXECUTING,
    updated_at: '2026-10-20T09:45:00.000Z',
  };
  scenarioTasks.set(taskExecInProgress.task_id, taskExecInProgress);
  workspaces.set(taskExecInProgress.task_id, {
    workspace_id: 'ws-in-progress-1',
    task_id: taskExecInProgress.task_id,
    repository_id: DEFAULT_REPO_ID,
    base_revision: 'base-rev-1',
    branch_name: 'agent/task-exec-in-progress',
    workspace_path: '/sandboxes/task-exec-in-progress',
    status: WorkspaceStatus.IN_USE,
    created_at: '2026-10-20T09:30:00.000Z',
    updated_at: '2026-10-20T09:45:00.000Z',
  });
  events.set(taskExecInProgress.task_id, [
    {
      id: 'evt-eip-1',
      task_id: taskExecInProgress.task_id,
      event_type: 'EXECUTION_STARTED',
      description: 'Automated workspace tool operations in progress.',
      created_at: '2026-10-20T09:45:00.000Z',
    },
  ]);

  // Scenario 6: Execution cancellation
  const taskExecCancelled: TaskDetailResponse = {
    ...taskExecApproved,
    task_id: 'task-exec-cancelled',
    title: 'Execution Cancelled by User',
    status: TaskStatus.CANCELLED,
    updated_at: '2026-10-20T09:50:00.000Z',
  };
  scenarioTasks.set(taskExecCancelled.task_id, taskExecCancelled);
  workspaces.set(taskExecCancelled.task_id, {
    workspace_id: 'ws-cancelled-1',
    task_id: taskExecCancelled.task_id,
    repository_id: DEFAULT_REPO_ID,
    base_revision: 'base-rev-1',
    branch_name: 'agent/task-exec-cancelled',
    workspace_path: '/sandboxes/task-exec-cancelled',
    status: WorkspaceStatus.STOPPED,
    created_at: '2026-10-20T09:30:00.000Z',
    updated_at: '2026-10-20T09:50:00.000Z',
    cleaned_at: '2026-10-20T09:50:00.000Z',
  });
  events.set(taskExecCancelled.task_id, [
    {
      id: 'evt-ec-1',
      task_id: taskExecCancelled.task_id,
      event_type: 'TASK_CANCELLED',
      description: 'Task execution cancelled by user.',
      created_at: '2026-10-20T09:50:00.000Z',
    },
  ]);

  // Scenario 7: Actual file modifications and diff hunks
  const taskExecDiff: TaskDetailResponse = {
    ...taskExecApproved,
    task_id: 'task-exec-diff',
    title: 'Code Modifications and Diff Inspection',
    status: TaskStatus.EXECUTING,
    updated_at: '2026-10-20T10:00:00.000Z',
  };
  scenarioTasks.set(taskExecDiff.task_id, taskExecDiff);
  workspaces.set(taskExecDiff.task_id, {
    workspace_id: 'ws-diff-1',
    task_id: taskExecDiff.task_id,
    repository_id: DEFAULT_REPO_ID,
    base_revision: 'base-rev-1',
    branch_name: 'agent/task-exec-diff',
    workspace_path: '/sandboxes/task-exec-diff',
    status: WorkspaceStatus.IN_USE,
    created_at: '2026-10-20T09:30:00.000Z',
    updated_at: '2026-10-20T10:00:00.000Z',
  });
  diffs.set(taskExecDiff.task_id, {
    task_id: taskExecDiff.task_id,
    repository_id: DEFAULT_REPO_ID,
    base_branch: 'main',
    head_branch: 'agent/task-exec-diff',
    total_files_changed: 2,
    total_additions: 15,
    total_deletions: 4,
    files: [
      {
        file_path: 'src/analyzer/ast_walker.py',
        status: 'modified',
        additions: 10,
        deletions: 4,
        patch:
          '@@ -12,4 +12,10 @@\n- old_call()\n+ new_bounded_call(depth=4)\n+ assert token_budget < 20000',
        diff_ranges: [{ start_line: 12, end_line: 22, change_type: 'modified' }],
      },
      {
        file_path: 'tests/test_ast_walker.py',
        status: 'added',
        additions: 5,
        deletions: 0,
        patch: '@@ -0,0 +1,5 @@\n+def test_depth_cap():\n+    assert True',
        diff_ranges: [{ start_line: 1, end_line: 5, change_type: 'added' }],
      },
    ],
  });
  events.set(taskExecDiff.task_id, [
    {
      id: 'evt-ed-1',
      task_id: taskExecDiff.task_id,
      event_type: 'CODE_MODIFICATION',
      description: 'Applied patch to src/analyzer/ast_walker.py.',
      created_at: '2026-10-20T10:00:00.000Z',
    },
  ]);

  // Scenario 8: Successful test execution
  const taskExecTestsPass: TaskDetailResponse = {
    ...taskExecApproved,
    task_id: 'task-exec-tests-pass',
    title: 'Successful Test Execution',
    status: TaskStatus.TESTING,
    updated_at: '2026-10-20T10:10:00.000Z',
  };
  scenarioTasks.set(taskExecTestsPass.task_id, taskExecTestsPass);
  tests.set(taskExecTestsPass.task_id, {
    task_id: taskExecTestsPass.task_id,
    runs: [
      {
        attempt: 1,
        command: 'pytest tests/test_ast_walker.py',
        status: 'PASSED',
        exit_code: 0,
        duration_ms: 1250,
        tests_total: 10,
        tests_passed: 10,
        tests_failed: 0,
        framework: 'pytest',
        stdout: '================ 10 passed in 1.25s ================',
        output_summary: '10 passed in 1.25s',
        executed_at: '2026-10-20T10:10:00.000Z',
      },
    ],
    repair_attempts_used: 0,
    repair_attempts_max: 3,
  });
  events.set(taskExecTestsPass.task_id, [
    {
      id: 'evt-tp-1',
      task_id: taskExecTestsPass.task_id,
      event_type: 'TESTS_EXECUTED',
      description: 'pytest tests/test_ast_walker.py completed: 10 passed.',
      created_at: '2026-10-20T10:10:00.000Z',
    },
  ]);

  // Scenario 9: Assertion failure eligible for repair
  const taskExecTestsFailRepairable: TaskDetailResponse = {
    ...taskExecApproved,
    task_id: 'task-exec-tests-fail-repairable',
    title: 'Assertion Failure Eligible for Self-Repair',
    status: TaskStatus.TESTING,
    updated_at: '2026-10-20T10:15:00.000Z',
  };
  scenarioTasks.set(taskExecTestsFailRepairable.task_id, taskExecTestsFailRepairable);
  tests.set(taskExecTestsFailRepairable.task_id, {
    task_id: taskExecTestsFailRepairable.task_id,
    runs: [
      {
        attempt: 1,
        command: 'pytest tests/test_token_budget.py',
        status: 'FAILED',
        classification: 'TEST_FAILURE',
        is_repair_eligible: true,
        exit_code: 1,
        duration_ms: 850,
        tests_total: 10,
        tests_passed: 9,
        tests_failed: 1,
        framework: 'pytest',
        stderr: 'AssertionError: token count 25000 exceeded max budget 20000',
        output_summary: 'FAILED tests/test_token_budget.py::test_cap - AssertionError: 25000 > 20000',
        executed_at: '2026-10-20T10:15:00.000Z',
      },
    ],
    repair_attempts_used: 0,
    repair_attempts_max: 3,
  });
  events.set(taskExecTestsFailRepairable.task_id, [
    {
      id: 'evt-tr-1',
      task_id: taskExecTestsFailRepairable.task_id,
      event_type: 'TESTS_EXECUTED',
      description: 'pytest tests/test_token_budget.py completed: 9 passed, 1 failed.',
      created_at: '2026-10-20T10:15:00.000Z',
    },
  ]);

  // Scenario 10: Infrastructure failure not eligible for repair
  const taskExecTestsFailInfra: TaskDetailResponse = {
    ...taskExecApproved,
    task_id: 'task-exec-tests-fail-infra',
    title: 'Infrastructure Failure (Not Repair Eligible)',
    status: TaskStatus.FAILED,
    updated_at: '2026-10-20T10:20:00.000Z',
  };
  scenarioTasks.set(taskExecTestsFailInfra.task_id, taskExecTestsFailInfra);
  tests.set(taskExecTestsFailInfra.task_id, {
    task_id: taskExecTestsFailInfra.task_id,
    runs: [
      {
        attempt: 1,
        command: 'pytest',
        status: 'FAILED',
        classification: 'INFRASTRUCTURE_ERROR',
        is_repair_eligible: false,
        exit_code: 2,
        duration_ms: 320,
        tests_total: 0,
        tests_passed: 0,
        tests_failed: 0,
        error_count: 1,
        framework: 'pytest',
        stderr: 'Traceback (most recent call last):\nModuleNotFoundError: No module named pytest_cov',
        output_summary: 'ModuleNotFoundError: No module named pytest_cov',
        executed_at: '2026-10-20T10:20:00.000Z',
      },
    ],
    repair_attempts_used: 0,
    repair_attempts_max: 3,
  });
  events.set(taskExecTestsFailInfra.task_id, [
    {
      id: 'evt-ti-1',
      task_id: taskExecTestsFailInfra.task_id,
      event_type: 'TEST_INFRASTRUCTURE_FAILURE',
      description: 'Runner crashed with exit code 2 (missing dependency).',
      created_at: '2026-10-20T10:20:00.000Z',
    },
  ]);

  // Scenario 11: Timeout not eligible for repair
  const taskExecTestsTimeout: TaskDetailResponse = {
    ...taskExecApproved,
    task_id: 'task-exec-tests-timeout',
    title: 'Test Timeout Failure (Not Repair Eligible)',
    status: TaskStatus.FAILED,
    updated_at: '2026-10-20T10:25:00.000Z',
  };
  scenarioTasks.set(taskExecTestsTimeout.task_id, taskExecTestsTimeout);
  tests.set(taskExecTestsTimeout.task_id, {
    task_id: taskExecTestsTimeout.task_id,
    runs: [
      {
        attempt: 1,
        command: 'pytest --timeout=30',
        status: 'TIMEOUT',
        timed_out: true,
        classification: 'TIMEOUT',
        is_repair_eligible: false,
        exit_code: 124,
        duration_ms: 30000,
        tests_total: 5,
        tests_passed: 2,
        tests_failed: 1,
        skipped_count: 2,
        framework: 'pytest',
        stderr: 'Command timed out after 30.0 seconds.',
        output_summary: 'Test execution timed out after 30.0 seconds.',
        executed_at: '2026-10-20T10:25:00.000Z',
      },
    ],
    repair_attempts_used: 0,
    repair_attempts_max: 3,
  });
  events.set(taskExecTestsTimeout.task_id, [
    {
      id: 'evt-to-1',
      task_id: taskExecTestsTimeout.task_id,
      event_type: 'EXECUTION_TIMED_OUT',
      description: 'Execution exceeded 30 second limit.',
      created_at: '2026-10-20T10:25:00.000Z',
    },
  ]);

  // Scenario 12: Repair attempt history
  const taskExecRepairHistory: TaskDetailResponse = {
    ...taskExecApproved,
    task_id: 'task-exec-repair-history',
    title: 'Bounded Repair Attempt History',
    status: TaskStatus.REPAIRING,
    repair_attempts_used: 2,
    repair_attempts_max: 3,
    updated_at: '2026-10-20T10:30:00.000Z',
  };
  scenarioTasks.set(taskExecRepairHistory.task_id, taskExecRepairHistory);
  repairBudgets.set(taskExecRepairHistory.task_id, {
    task_id: taskExecRepairHistory.task_id,
    repair_attempts_used: 2,
    repair_attempts_max: 3,
    is_budget_exhausted: false,
    is_eligible_for_repair: true,
    last_attempt_at: '2026-10-20T10:25:00.000Z',
    history: [
      {
        attempt_number: 1,
        task_id: taskExecRepairHistory.task_id,
        timestamp: '2026-10-20T10:15:00.000Z',
        patch_summary: 'Initial recursion depth limit patch',
        patch_hash: 'hash-001',
        workspace_revision: 'rev-001',
        test_status_before: 'FAILED',
        test_status_after: 'FAILED',
        success: false,
      },
      {
        attempt_number: 2,
        task_id: taskExecRepairHistory.task_id,
        timestamp: '2026-10-20T10:25:00.000Z',
        patch_summary: 'Updated token counter boundary condition',
        patch_hash: 'hash-002',
        workspace_revision: 'rev-002',
        test_status_before: 'FAILED',
        test_status_after: 'PASSED',
        success: true,
      },
    ],
  });
  events.set(taskExecRepairHistory.task_id, [
    {
      id: 'evt-rh-1',
      task_id: taskExecRepairHistory.task_id,
      event_type: 'REPAIR_ATTEMPT',
      description: 'Repair attempt 1 completed.',
      created_at: '2026-10-20T10:15:00.000Z',
    },
    {
      id: 'evt-rh-2',
      task_id: taskExecRepairHistory.task_id,
      event_type: 'REPAIR_ATTEMPT',
      description: 'Repair attempt 2 completed.',
      created_at: '2026-10-20T10:25:00.000Z',
    },
  ]);

  // Scenario 13: Retry budget exhausted after three attempts
  const taskExecBudgetExhausted: TaskDetailResponse = {
    ...taskExecApproved,
    task_id: 'task-exec-budget-exhausted',
    title: 'Retry Budget Exhausted',
    status: TaskStatus.FAILED,
    repair_attempts_used: 3,
    repair_attempts_max: 3,
    updated_at: '2026-10-20T10:30:00.000Z',
  };
  scenarioTasks.set(taskExecBudgetExhausted.task_id, taskExecBudgetExhausted);
  workspaces.set(taskExecBudgetExhausted.task_id, {
    workspace_id: 'ws-exhausted-1',
    task_id: taskExecBudgetExhausted.task_id,
    repository_id: DEFAULT_REPO_ID,
    base_revision: 'base-rev-1',
    branch_name: 'agent/task-exec-budget-exhausted',
    workspace_path: '/sandboxes/task-exec-budget-exhausted',
    status: WorkspaceStatus.STOPPED,
    created_at: '2026-10-20T09:30:00.000Z',
    updated_at: '2026-10-20T10:30:00.000Z',
    cleaned_at: '2026-10-20T10:30:00.000Z',
  });
  repairBudgets.set(taskExecBudgetExhausted.task_id, {
    task_id: taskExecBudgetExhausted.task_id,
    repair_attempts_used: 3,
    repair_attempts_max: 3,
    is_budget_exhausted: true,
    is_eligible_for_repair: false,
    last_attempt_at: '2026-10-20T10:30:00.000Z',
    history: [
      {
        attempt_number: 1,
        task_id: taskExecBudgetExhausted.task_id,
        timestamp: '2026-10-20T10:15:00.000Z',
        patch_summary: 'Initial attempt',
        patch_hash: 'hash-ex-1',
        test_status_before: 'FAILED',
        test_status_after: 'FAILED',
        success: false,
      },
      {
        attempt_number: 2,
        task_id: taskExecBudgetExhausted.task_id,
        timestamp: '2026-10-20T10:20:00.000Z',
        patch_summary: 'Second attempt',
        patch_hash: 'hash-ex-2',
        test_status_before: 'FAILED',
        test_status_after: 'FAILED',
        success: false,
      },
      {
        attempt_number: 3,
        task_id: taskExecBudgetExhausted.task_id,
        timestamp: '2026-10-20T10:30:00.000Z',
        patch_summary: 'Third attempt',
        patch_hash: 'hash-ex-3',
        test_status_before: 'FAILED',
        test_status_after: 'FAILED',
        success: false,
      },
    ],
  });
  events.set(taskExecBudgetExhausted.task_id, [
    {
      id: 'evt-rbe-1',
      task_id: taskExecBudgetExhausted.task_id,
      event_type: 'RETRY_BUDGET_EXHAUSTED',
      description: 'Repair attempts ceiling (3/3) reached. Auto-repair terminated.',
      created_at: '2026-10-20T10:30:00.000Z',
    },
  ]);

  // Scenario 14: Empty and unavailable telemetry
  const taskExecEmptyTelemetry: TaskDetailResponse = {
    ...taskExecApproved,
    task_id: 'task-exec-telemetry-empty',
    title: 'Empty and Unavailable Telemetry',
    status: TaskStatus.CREATED,
    repair_attempts_used: 0,
    repair_attempts_max: 3,
    updated_at: '2026-10-20T10:35:00.000Z',
  };
  scenarioTasks.set(taskExecEmptyTelemetry.task_id, taskExecEmptyTelemetry);

  return {
    tasks,
    plans,
    approvals,
    events,
    tests,
    verifications,
    issues,
    workspaces,
    diffs,
    repairBudgets,
    scenarioTasks,
  };
}

let db = createInitialSeedData();

let eventSeq = 0;
let approvalSeq = 0;
let taskSeq = 0;

function nextEventId(): string {
  return `evt-${++eventSeq}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

function nextApprovalId(): string {
  return `appr-${++approvalSeq}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

function nextTaskId(prefix = 'task'): string {
  return `${prefix}-${++taskSeq}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

/**
 * Reset mock store to initial seed state. Useful for test isolation.
 */
export function resetMockStore(): void {
  db = createInitialSeedData();
  eventSeq = 0;
  approvalSeq = 0;
  taskSeq = 0;
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

export function getTaskFromStore(taskId: string): TaskDetailResponse | undefined {
  return db.tasks.get(taskId) || db.scenarioTasks?.get(taskId);
}

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

    const taskId = nextTaskId();
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
      id: nextEventId(),
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

    if (search) {
      const scenarioItems = Array.from(db.scenarioTasks?.values() || []);
      items = [...items, ...scenarioItems];
    }

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
    const task = getTaskFromStore(taskId);

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
    const task = getTaskFromStore(taskId);

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

    // Plan synthesis / revision guard: allow PENDING_APPROVAL, APPROVED, or valid transition to PLANNING
    if (
      task.status !== TaskStatus.PENDING_APPROVAL &&
      task.status !== TaskStatus.APPROVED &&
      !canTransition(task.status, TaskStatus.PLANNING)
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
      id: nextEventId(),
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
    const task = getTaskFromStore(taskId);

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
    const task = getTaskFromStore(taskId);

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
      id: nextApprovalId(),
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
      id: nextEventId(),
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
    const task = getTaskFromStore(taskId);

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
      id: nextApprovalId(),
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
      id: nextEventId(),
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
    const task = getTaskFromStore(taskId);

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

    // Allocate workspace in mock store
    const branchName = `agent/task-${taskId.replace(/^task-/, '')}`;
    const workspace: WorkspaceMetadata = {
      workspace_id: `ws-${taskId}`,
      task_id: taskId,
      repository_id: task.repository_id,
      base_revision: task.base_revision || 'a1b2c3d4e5f6',
      branch_name: branchName,
      workspace_path: `/sandboxes/${taskId}`,
      status: WorkspaceStatus.CREATING,
      isolation_type: 'git_worktree',
      resource_limits: {
        timeout_seconds: 60,
        max_disk_bytes: 524288000,
        max_file_size_bytes: 5242880,
        max_files_modified: 50,
        network_egress_allowed: false,
      },
      created_at: now,
      updated_at: now,
    };
    db.workspaces.set(taskId, workspace);

    const taskEvents = db.events.get(taskId) || [];
    taskEvents.push({
      id: nextEventId(),
      task_id: taskId,
      event_type: 'WORKSPACE_SETUP',
      description: 'Workspace allocation initiated.',
      created_at: now,
    });
    db.events.set(taskId, taskEvents);

    return HttpResponse.json(task, { status: 200 });
  }),

  // --------------------------------------------------------------------------
  // 8B. POST /api/v1/tasks/:taskId/cancel — Cancel Active or Pending Task
  // --------------------------------------------------------------------------
  http.post('*/api/v1/tasks/:taskId/cancel', ({ params }) => {
    const taskId = String(params.taskId);
    const task = getTaskFromStore(taskId);

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

    if (!canCancelTask(task.status)) {
      return HttpResponse.json(
        {
          error: {
            code: 'INVALID_STATE_TRANSITION',
            message: `Task in terminal status '${task.status}' cannot be cancelled.`,
            retryable: false,
          },
        },
        { status: 409 }
      );
    }

    const now = new Date().toISOString();
    task.status = TaskStatus.CANCELLED;
    task.updated_at = now;

    // Update workspace if exists
    const ws = db.workspaces.get(taskId);
    if (ws) {
      ws.status = WorkspaceStatus.STOPPED;
      ws.updated_at = now;
      ws.cleaned_at = now;
    }

    const taskEvents = db.events.get(taskId) || [];
    taskEvents.push({
      id: nextEventId(),
      task_id: taskId,
      event_type: 'TASK_CANCELLED',
      description: 'Task cancelled by user.',
      created_at: now,
    });
    db.events.set(taskId, taskEvents);

    return HttpResponse.json(task, { status: 200 });
  }),

  // --------------------------------------------------------------------------
  // 8C. GET /api/v1/tasks/:taskId/workspace — Workspace Metadata
  // --------------------------------------------------------------------------
  http.get('*/api/v1/tasks/:taskId/workspace', ({ params }) => {
    const taskId = String(params.taskId);
    const workspace = db.workspaces.get(taskId);

    if (!workspace) {
      return HttpResponse.json(
        {
          error: {
            code: 'WORKSPACE_NOT_FOUND',
            message: `Workspace for task '${taskId}' not found.`,
            retryable: false,
          },
        },
        { status: 404 }
      );
    }

    return HttpResponse.json(workspace, { status: 200 });
  }),

  // --------------------------------------------------------------------------
  // 8D. GET /api/v1/tasks/:taskId/diff & Repository-scoped Diff Telemetry
  // --------------------------------------------------------------------------
  http.get('*/api/v1/tasks/:taskId/diff', ({ params }) => {
    const taskId = String(params.taskId);
    const diff = db.diffs.get(taskId);

    if (!diff) {
      return HttpResponse.json(
        {
          error: {
            code: 'DIFF_NOT_FOUND',
            message: `Diff telemetry for task '${taskId}' not found.`,
            retryable: false,
          },
        },
        { status: 404 }
      );
    }

    return HttpResponse.json(diff, { status: 200 });
  }),

  http.get('*/api/v1/repositories/:repositoryId/source/diff-ranges/task/:taskId', ({ params }) => {
    const taskId = String(params.taskId);
    const diff = db.diffs.get(taskId);

    if (!diff) {
      return HttpResponse.json(
        {
          error: {
            code: 'DIFF_NOT_FOUND',
            message: `Diff telemetry for task '${taskId}' not found.`,
            retryable: false,
          },
        },
        { status: 404 }
      );
    }

    return HttpResponse.json(diff, { status: 200 });
  }),

  // --------------------------------------------------------------------------
  // 8E. GET /api/v1/tasks/:taskId/repair-budget — Repair Budget Status
  // --------------------------------------------------------------------------
  http.get('*/api/v1/tasks/:taskId/repair-budget', ({ params }) => {
    const taskId = String(params.taskId);
    const task = getTaskFromStore(taskId);
    const budget = db.repairBudgets.get(taskId);

    if (budget) {
      return HttpResponse.json(budget, { status: 200 });
    }

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

    // Default derived from task
    const used = task.repair_attempts_used ?? 0;
    const max = task.repair_attempts_max ?? 3;
    const defaultBudget: WorkspaceRepairBudgetStatus = {
      task_id: taskId,
      repair_attempts_used: used,
      repair_attempts_max: max,
      is_budget_exhausted: used >= max,
      is_eligible_for_repair: used < max,
      last_attempt_at: task.updated_at,
    };
    return HttpResponse.json(defaultBudget, { status: 200 });
  }),

  // --------------------------------------------------------------------------
  // 9. GET /api/v1/tasks/:taskId/events — Chronological Timeline Events
  // --------------------------------------------------------------------------
  http.get('*/api/v1/tasks/:taskId/events', ({ params, request }) => {
    const taskId = String(params.taskId);
    const task = getTaskFromStore(taskId);

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
    const task = getTaskFromStore(taskId);

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
    const task = getTaskFromStore(taskId);

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

    const taskId = nextTaskId(`task-issue-${issueNumber}`);
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
      id: nextEventId(),
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
