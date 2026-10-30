/**
 * Task Domain Type Definitions and Schemas.
 *
 * Source of truth:
 * - Docs/week3.md §6 & §7
 * - backend/app/schemas/task.py (VERIFIED)
 * - backend/app/schemas/verification.py (VERIFIED)
 * - origin/dev/w3-planner-schema & origin/yug (PROVISIONAL)
 */

// ============================================================================
// 1. Task Lifecycle State Machine (VERIFIED: backend/app/schemas/task.py:34-115)
// ============================================================================

export const TaskStatus = {
  CREATED: 'CREATED',
  PLANNING: 'PLANNING',
  PENDING_APPROVAL: 'PENDING_APPROVAL',
  APPROVED: 'APPROVED',
  REJECTED: 'REJECTED',
  WORKSPACE_SETUP: 'WORKSPACE_SETUP',
  EXECUTING: 'EXECUTING',
  TESTING: 'TESTING',
  REPAIRING: 'REPAIRING',
  VERIFYING: 'VERIFYING',
  READY_FOR_PUBLICATION: 'READY_FOR_PUBLICATION',
  PUBLISHING: 'PUBLISHING',
  DRAFT_PR_CREATED: 'DRAFT_PR_CREATED',
  // Terminal / Exceptional states
  FAILED: 'FAILED',
  CANCELLED: 'CANCELLED',
  RECOVERY_REQUIRED: 'RECOVERY_REQUIRED',
  BLOCKED: 'BLOCKED',
} as const;

export type TaskStatus = (typeof TaskStatus)[keyof typeof TaskStatus];

/**
 * Explicit state transition graph per Docs/week3.md §7.2 & backend/app/schemas/task.py:59-107
 */
export const VALID_TASK_TRANSITIONS: Readonly<Record<TaskStatus, readonly TaskStatus[]>> = {
  [TaskStatus.CREATED]: [TaskStatus.PLANNING, TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.BLOCKED],
  [TaskStatus.PLANNING]: [TaskStatus.PENDING_APPROVAL, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.BLOCKED],
  // STRICT GUARDRAIL: PENDING_APPROVAL cannot transition directly to EXECUTING (Docs/week3.md §7.2)
  [TaskStatus.PENDING_APPROVAL]: [TaskStatus.APPROVED, TaskStatus.REJECTED, TaskStatus.PLANNING, TaskStatus.CANCELLED],
  [TaskStatus.APPROVED]: [TaskStatus.WORKSPACE_SETUP, TaskStatus.EXECUTING, TaskStatus.CANCELLED, TaskStatus.BLOCKED],
  // STRICT GUARDRAIL: Rejected plan can NEVER be executed directly
  [TaskStatus.REJECTED]: [TaskStatus.PLANNING, TaskStatus.CANCELLED],
  [TaskStatus.WORKSPACE_SETUP]: [TaskStatus.EXECUTING, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.BLOCKED],
  [TaskStatus.EXECUTING]: [TaskStatus.TESTING, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.BLOCKED, TaskStatus.RECOVERY_REQUIRED],
  [TaskStatus.TESTING]: [TaskStatus.VERIFYING, TaskStatus.REPAIRING, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.BLOCKED],
  [TaskStatus.REPAIRING]: [TaskStatus.TESTING, TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.CANCELLED],
  [TaskStatus.VERIFYING]: [TaskStatus.READY_FOR_PUBLICATION, TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.CANCELLED],
  [TaskStatus.READY_FOR_PUBLICATION]: [TaskStatus.PUBLISHING, TaskStatus.CANCELLED, TaskStatus.BLOCKED],
  [TaskStatus.PUBLISHING]: [TaskStatus.DRAFT_PR_CREATED, TaskStatus.FAILED, TaskStatus.BLOCKED],
  [TaskStatus.DRAFT_PR_CREATED]: [], // Terminal happy path
  [TaskStatus.FAILED]: [TaskStatus.RECOVERY_REQUIRED, TaskStatus.PLANNING],
  [TaskStatus.CANCELLED]: [], // Terminal
  [TaskStatus.RECOVERY_REQUIRED]: [TaskStatus.PLANNING, TaskStatus.APPROVED, TaskStatus.WORKSPACE_SETUP, TaskStatus.FAILED, TaskStatus.CANCELLED],
  [TaskStatus.BLOCKED]: [TaskStatus.PLANNING, TaskStatus.PENDING_APPROVAL, TaskStatus.CANCELLED],
};

/**
 * Returns true if transitioning from `current` to `target` is permitted by policy.
 */
export function canTransition(current: TaskStatus, target: TaskStatus): boolean {
  if (current === target) {
    return true;
  }
  const allowed = VALID_TASK_TRANSITIONS[current];
  return allowed ? allowed.includes(target) : false;
}

// ============================================================================
// 2. Task Source Reference (VERIFIED: backend/app/schemas/task.py:121-177)
// ============================================================================

export type TaskSourceType = 'GITHUB_ISSUE' | 'BUG_FINDING' | 'REVIEW_FINDING' | 'USER_PROMPT';

export interface TaskSourceReference {
  type: TaskSourceType;
  issue_number?: number | null;
  issue_url?: string | null;
  finding_id?: string | null;
  repository_id?: string | null;
  base_revision?: string | null;
}

// ============================================================================
// 3. Segregated Intake Elements (VERIFIED: backend/app/schemas/task.py:182-268)
// ============================================================================

export type TaskRequirementCategory = 'functional' | 'bug_fix' | 'refactor' | 'security' | 'test';

export interface TaskRequirement {
  id: string; // e.g. 'req-1'
  description: string;
  category: TaskRequirementCategory;
  target_files: string[];
  acceptance_criteria: string[];
}

export type TaskRiskLevel = 'low' | 'medium' | 'high';

export interface TaskAssumption {
  id: string; // e.g. 'asm-1'
  description: string;
  unresolved: boolean;
  risk_level: TaskRiskLevel;
}

export type TaskConstraintType =
  | 'protected_file'
  | 'forbidden_dependency'
  | 'backward_compatibility'
  | 'resource_limit'
  | 'security_policy';

export interface TaskConstraint {
  id: string; // e.g. 'cst-1'
  description: string;
  constraint_type: TaskConstraintType;
  forbidden_files: string[];
  forbidden_packages: string[];
  max_budget_tokens?: number | null;
}

// ============================================================================
// 4. Task Intake & Detail Envelopes (VERIFIED: backend/app/schemas/task.py:273-350)
// ============================================================================

export interface TaskCreateRequest {
  repository_id: string;
  title: string;
  description: string;
  source: TaskSourceReference;
  requirements: TaskRequirement[];
  assumptions?: TaskAssumption[];
  constraints?: TaskConstraint[];
  base_revision?: string | null;
}

export type TaskIntakePayload = TaskCreateRequest;

export interface TaskDetailResponse {
  task_id: string;
  repository_id: string;
  title: string;
  description: string;
  status: TaskStatus;
  source: TaskSourceReference;
  requirements: TaskRequirement[];
  assumptions: TaskAssumption[];
  constraints: TaskConstraint[];
  base_revision: string | null;
  plan_version: number;
  approved_plan_version: number | null;
  repair_attempts_used: number;
  repair_attempts_max: number;
  created_at: string;
  updated_at: string;
}

export interface TaskListResponse {
  items: TaskDetailResponse[];
  total: number;
  page: number;
  page_size: number;
  total_pages?: number;
}

export interface TaskListFilterParams {
  repository_id?: string;
  status?: TaskStatus;
  search?: string;
  page?: number;
  page_size?: number;
}

// ============================================================================
// 5. Structured Plan Models (PROVISIONAL: origin/dev/w3-planner-schema & week3.md §6 F32)
// Marked provisional until merged into origin/main backend schemas.
// ============================================================================

export type PlanStepType = 'inspect' | 'edit' | 'create' | 'test' | 'verify' | 'refactor' | 'command';
export type PlanStepRiskLevel = 'low' | 'medium' | 'high' | 'critical';

export interface PlanStep {
  step_id: string;
  title?: string;
  description: string;
  step_type?: PlanStepType;
  expected_files: string[];
  dependencies?: string[];
  verification: string[];
  risk_level?: PlanStepRiskLevel;
  rollback_hint?: string;
  estimated_duration_s?: number;
}

export interface PlanRisk {
  risk_id: string;
  description: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  mitigation: string;
}

export interface ValidationStrategy {
  automated_tests: string[];
  manual_checks?: string[];
  verification_suite?: string[];
  rollback_plan?: string;
}

export type TaskPlanStatus = 'PENDING_APPROVAL' | 'APPROVED' | 'REJECTED';

export interface TaskPlan {
  task_id: string;
  plan_version: number;
  base_revision: string;
  summary: string;
  problem_statement?: string;
  assumptions: string[];
  unresolved_questions: string[];
  relevant_files: string[];
  steps: PlanStep[];
  expected_files_to_modify: string[];
  tests_to_add: string[];
  validation_strategy: string | ValidationStrategy;
  risks: string[] | PlanRisk[];
  required_permissions?: string[];
  resource_budget?: {
    tokens?: number;
  };
  status: TaskPlanStatus;
  approved_by?: string | null;
  approved_at?: string | null;
  rejection_reason?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface PlanGenerateRequest {
  regenerate?: boolean;
  prompt_instructions?: string;
}

export interface PlanApprovalRequest {
  plan_version: number;
  notes?: string;
  approved_by?: string;
}

export interface PlanRejectionRequest {
  plan_version: number;
  reason?: string;
  rejected_by?: string;
}

export interface PlanApproval {
  id: string;
  task_id: string;
  plan_version: number;
  decision: 'APPROVED' | 'REJECTED';
  user_id?: string;
  notes?: string;
  reason?: string;
  created_at: string;
}

// ============================================================================
// 6. Chronological Events & Timeline (PROVISIONAL: origin/yug & Docs/week3.md §6 F38)
// ============================================================================

export interface TaskEvent {
  id: string;
  task_id: string;
  event_type: string;
  description: string;
  details?: Record<string, unknown>;
  created_at: string;
  user_id?: string | null;
}

export interface TaskEventListResponse {
  items: TaskEvent[];
  total: number;
}

// ============================================================================
// 7. GitHub Issue Intake Models (PROVISIONAL: origin/yug & Docs/week3.md §6 F31)
// ============================================================================

export interface GitHubIssue {
  issue_number: number;
  title: string;
  body: string | null;
  state: 'open' | 'closed';
  url: string;
  labels: string[];
  author: string;
  created_at: string;
  is_imported?: boolean;
}

export interface GitHubIssueListResponse {
  items: GitHubIssue[];
  total: number;
  page: number;
  page_size: number;
}

export interface IssueImportRequest {
  issue_number: number;
}

export interface IssueImportResponse {
  task_id: string;
  source: TaskSourceReference;
  title: string;
  status: TaskStatus;
}

// ============================================================================
// 8. Test Telemetry & Independent Verification (VERIFIED: backend/app/schemas/verification.py)
// ============================================================================

export type TestRunStatus = 'PASSED' | 'FAILED' | 'ERROR' | 'TIMEOUT';

export interface TestRunItem {
  attempt: number;
  command: string;
  status: TestRunStatus;
  exit_code: number;
  duration_ms: number;
  tests_total: number;
  tests_passed: number;
  tests_failed: number;
  output_summary: string;
  executed_at: string;
}

export interface TaskTestResultsResponse {
  task_id: string;
  runs: TestRunItem[];
  repair_attempts_used: number;
  repair_attempts_max: number;
}

export type VerificationCheckStatus = 'PASSED' | 'FAILED' | 'SKIPPED' | 'UNAVAILABLE' | 'COMPLETED';
export type VerificationOverallStatus = 'PASS' | 'FAIL' | 'INCONCLUSIVE' | 'REQUIRES_HUMAN_REVIEW';
export type FindingSeverity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO';

export interface VerificationFinding {
  id: string;
  severity: FindingSeverity;
  category: string;
  message: string;
  file_path?: string | null;
  line_number?: number | null;
  rule_id?: string | null;
  blocking: boolean;
}

export interface VerificationCheckItem {
  name: string;
  status: VerificationCheckStatus;
  duration_ms: number;
  message: string;
  findings_count: number;
  details: Record<string, unknown>;
}

export interface VerificationResult {
  task_id: string;
  verified_revision: string;
  status: VerificationOverallStatus;
  checks: VerificationCheckItem[];
  blocking_findings: VerificationFinding[];
  warnings: VerificationFinding[];
  pr_summary: string;
  created_at: string;
}
