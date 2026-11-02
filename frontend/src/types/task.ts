/**
 * Task Domain Type Definitions and Schemas.
 *
 * Source of truth:
 * - Docs/week3.md §6 & §7
 * - backend/app/schemas/task.py (VERIFIED)
 * - backend/app/schemas/verification.py (VERIFIED)
 * - origin/dev/w3-planner-schema & origin/yug (VERIFIED)
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
 * Explicit state transition graph per Docs/week3.md §7.2 & backend/app/schemas/task.py
 */
export const VALID_TASK_TRANSITIONS: Readonly<Record<TaskStatus, readonly TaskStatus[]>> = {
  [TaskStatus.CREATED]: [TaskStatus.PLANNING, TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.BLOCKED],
  [TaskStatus.PLANNING]: [TaskStatus.PENDING_APPROVAL, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.BLOCKED],
  // STRICT GUARDRAIL: PENDING_APPROVAL cannot transition directly to EXECUTING (Docs/week3.md §7.2)
  [TaskStatus.PENDING_APPROVAL]: [TaskStatus.APPROVED, TaskStatus.REJECTED, TaskStatus.PLANNING, TaskStatus.CANCELLED],
  [TaskStatus.APPROVED]: [TaskStatus.WORKSPACE_SETUP, TaskStatus.EXECUTING, TaskStatus.PLANNING, TaskStatus.CANCELLED, TaskStatus.BLOCKED],
  // STRICT GUARDRAIL: Rejected plan can NEVER be executed directly
  [TaskStatus.REJECTED]: [TaskStatus.PLANNING, TaskStatus.CANCELLED],
  [TaskStatus.WORKSPACE_SETUP]: [TaskStatus.EXECUTING, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.RECOVERY_REQUIRED, TaskStatus.BLOCKED],
  [TaskStatus.EXECUTING]: [TaskStatus.TESTING, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.BLOCKED, TaskStatus.RECOVERY_REQUIRED],
  [TaskStatus.TESTING]: [TaskStatus.VERIFYING, TaskStatus.REPAIRING, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.RECOVERY_REQUIRED, TaskStatus.BLOCKED],
  [TaskStatus.REPAIRING]: [TaskStatus.TESTING, TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.CANCELLED, TaskStatus.RECOVERY_REQUIRED],
  [TaskStatus.VERIFYING]: [TaskStatus.READY_FOR_PUBLICATION, TaskStatus.REPAIRING, TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.CANCELLED, TaskStatus.RECOVERY_REQUIRED],
  [TaskStatus.READY_FOR_PUBLICATION]: [TaskStatus.PUBLISHING, TaskStatus.VERIFYING, TaskStatus.CANCELLED, TaskStatus.BLOCKED],
  [TaskStatus.PUBLISHING]: [TaskStatus.DRAFT_PR_CREATED, TaskStatus.FAILED, TaskStatus.RECOVERY_REQUIRED, TaskStatus.BLOCKED],
  [TaskStatus.DRAFT_PR_CREATED]: [], // Terminal happy path
  [TaskStatus.FAILED]: [TaskStatus.RECOVERY_REQUIRED, TaskStatus.PLANNING],
  [TaskStatus.CANCELLED]: [], // Terminal
  [TaskStatus.RECOVERY_REQUIRED]: [
    TaskStatus.PLANNING,
    TaskStatus.APPROVED,
    TaskStatus.WORKSPACE_SETUP,
    TaskStatus.EXECUTING,
    TaskStatus.TESTING,
    TaskStatus.VERIFYING,
    TaskStatus.READY_FOR_PUBLICATION,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
  ],
  [TaskStatus.BLOCKED]: [
    TaskStatus.PLANNING,
    TaskStatus.PENDING_APPROVAL,
    TaskStatus.EXECUTING,
    TaskStatus.TESTING,
    TaskStatus.VERIFYING,
    TaskStatus.READY_FOR_PUBLICATION,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
  ],
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

export type TaskSourceType = 'GITHUB_ISSUE' | 'BUG_FINDING' | 'REVIEW_FINDING' | 'USER_PROMPT' | string;

export interface TaskSourceReference {
  type: TaskSourceType;
  issue_number?: number | null;
  issue_url?: string | null;
  url?: string | null;
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
export type CreateTaskPayload = TaskCreateRequest;

export interface TaskDetailResponse {
  task_id: string;
  repository_id: string;
  title: string;
  description: string;
  status: TaskStatus;
  source: TaskSourceReference;
  source_type?: TaskSourceType;
  requirements: TaskRequirement[];
  assumptions: TaskAssumption[];
  constraints: TaskConstraint[];
  base_revision: string | null;
  plan_version: number;
  approved_plan_version: number | null;
  repair_attempts_used: number;
  repair_attempts_max: number;
  latest_plan?: TaskPlan | null;
  approvals?: TaskApproval[];
  created_at: string;
  updated_at: string;
}

export type TaskDetail = TaskDetailResponse;

export interface TaskSummary {
  task_id: string;
  repository_id: string;
  title: string;
  status: TaskStatus;
  source_type?: TaskSourceType;
  source: TaskSourceReference;
  base_revision?: string | null;
  plan_version: number;
  approved_plan_version?: number | null;
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

export type PaginatedTaskListResponse = TaskListResponse;

export interface TaskListFilterParams {
  repository_id?: string;
  status?: TaskStatus | string;
  search?: string;
  page?: number;
  page_size?: number;
}

// ============================================================================
// 5. Structured Plan Models (Week 3 §6 F32)
// ============================================================================

export type PlanStepType =
  | 'inspect'
  | 'edit'
  | 'create'
  | 'delete'
  | 'test'
  | 'verify'
  | 'refactor'
  | 'command';

export type PlanStepActionType = PlanStepType;

export type PlanStepRiskLevel = 'low' | 'medium' | 'high' | 'critical';

export interface PlanStep {
  step_id: string;
  title?: string;
  description: string;
  step_type?: PlanStepType;
  action_type?: string;
  expected_files: string[];
  target_files?: string[];
  dependencies?: string[];
  depends_on?: string[];
  verification: string[];
  risk_level?: PlanStepRiskLevel;
  rollback_hint?: string;
  estimated_duration_s?: number;
}

export interface PlanRisk {
  id?: string;
  risk_id?: string;
  description: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  mitigation: string;
  affected_files?: string[];
}

export interface ValidationStrategy {
  automated_tests: string[];
  manual_checks?: string[];
  verification_suite?: string[];
  rollback_plan?: string;
}

export type TaskPlanStatus = 'PENDING_APPROVAL' | 'APPROVED' | 'REJECTED' | string;

export interface PlanResourceBudget {
  tokens?: number;
  max_tokens?: number;
  max_repair_attempts?: number;
  max_files_modified?: number;
  timeout_seconds?: number;
}

export interface TaskPlan {
  plan_id?: string;
  task_id: string;
  plan_version: number;
  base_revision: string;
  plan_hash?: string;
  summary: string;
  problem_statement?: string;
  assumptions: string[] | TaskAssumption[];
  unresolved_questions?: string[];
  relevant_files?: string[];
  relevant_symbols?: string[];
  steps: PlanStep[];
  expected_files?: string[];
  expected_files_to_modify?: string[];
  tests_to_run?: string[];
  tests_to_add?: string[];
  validation_strategy: string | ValidationStrategy | any;
  risks?: string[] | PlanRisk[] | any;
  required_permissions?: string[];
  resource_budget?: PlanResourceBudget;
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
  revision_notes?: string;
  base_revision?: string;
  custom_plan?: any;
}

export interface PlanApprovalRequest {
  plan_version?: number;
  notes?: string;
  comment?: string;
  base_revision?: string;
  approved_by?: string;
}

export interface PlanRejectionRequest {
  plan_version?: number;
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

export interface TaskApproval {
  id?: string;
  approval_id?: string;
  task_id: string;
  plan_version: number;
  decision: 'APPROVED' | 'REJECTED';
  notes?: string;
  comment?: string;
  user_id?: string;
  created_at: string;
}

// ============================================================================
// 6. Chronological Events & Timeline (Docs/week3.md §6 F38)
// ============================================================================

export interface TaskEvent {
  id?: string;
  event_id?: string;
  task_id?: string;
  event_type: string;
  summary?: string;
  description?: string;
  from_status?: string | null;
  to_status?: string | null;
  details?: Record<string, unknown>;
  created_at: string;
  user_id?: string | null;
}

export interface TaskEventListResponse {
  items: TaskEvent[];
  total: number;
}

// ============================================================================
// 7. GitHub Issue Intake Models (Docs/week3.md §6 F31)
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

export type GitHubIssueItem = GitHubIssue;

export interface GitHubIssueListResponse {
  items: GitHubIssue[];
  total: number;
  page: number;
  page_size: number;
}

export interface IssueImportRequest {
  issue_number: number;
  title?: string;
  source_type?: string;
}

export type ImportIssuePayload = IssueImportRequest;

export interface IssueImportResponse {
  task_id: string;
  source: TaskSourceReference;
  title: string;
  status: TaskStatus;
  issue?: {
    issue_number: number;
    html_url?: string;
    [key: string]: any;
  };
}

export interface CreateIssueFromFindingPayload {
  title: string;
  body: string;
  labels?: string[];
  finding_id?: string;
  source_type?: TaskSourceType;
  create_task?: boolean;
}

// ============================================================================
// 8. Test Telemetry & Independent Verification (VERIFIED: backend/app/schemas/verification.py)
// ============================================================================

export type TestRunStatus =
  | 'PASSED'
  | 'FAILED'
  | 'ERROR'
  | 'TIMEOUT'
  | 'UNSUPPORTED_FRAMEWORK'
  | 'SKIPPED'
  | 'NOT_RUN'
  | 'UNAVAILABLE';

export interface TestRunItem {
  attempt: number;
  command: string;
  status: TestRunStatus;
  exit_code: number;
  duration_ms: number;
  tests_total: number;
  total_count?: number;
  tests_passed: number;
  passed_count?: number;
  tests_failed: number;
  failed_count?: number;
  tests_skipped?: number;
  skipped_count?: number;
  error_count?: number;
  framework?: string;
  classification?: TestFailureClassification | string;
  is_repair_eligible?: boolean;
  failed_test_names?: string[];
  failure_details?: Record<string, any>;
  workspace_revision?: string;
  stdout?: string;
  stderr?: string;
  timed_out?: boolean;
  output_summary?: string;
  executed_at: string;
}

export interface TaskTestResultsResponse {
  task_id: string;
  runs: TestRunItem[];
  repair_attempts_used: number;
  repair_attempts_max: number;
  repair_history?: RepairAttemptRecord[];
  status?: TestOutcomeStatus;
  passed?: number;
  failed?: number;
  errors?: number;
  duration_ms?: number;
  output?: string;
}

export type VerificationCheckStatus = 'PASSED' | 'FAILED' | 'SKIPPED' | 'UNAVAILABLE' | 'COMPLETED';
export type VerificationOverallStatus = 'PASS' | 'FAIL' | 'INCONCLUSIVE' | 'REQUIRES_HUMAN_REVIEW';
export type FindingSeverity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO';

export interface VerificationFinding {
  id: string;
  severity: FindingSeverity;
  category: string;
  title?: string | null;
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
  details?: Record<string, unknown>;
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
  task_status?: TaskStatus | string;
  is_eligible_for_publication?: boolean;
}

// ============================================================================
// 9. Workspace & Execution Lifecycle (VERIFIED: backend/app/schemas/workspace.py)
// ============================================================================

export const WorkspaceStatus = {
  NOT_CREATED: 'NOT_CREATED',
  CREATING: 'CREATING',
  READY: 'READY',
  IN_USE: 'IN_USE',
  STOPPED: 'STOPPED',
  FAILED: 'FAILED',
  CLEANUP_PENDING: 'CLEANUP_PENDING',
  CLEANED: 'CLEANED',
} as const;

export type WorkspaceStatus = (typeof WorkspaceStatus)[keyof typeof WorkspaceStatus];

export interface WorkspaceResourceLimits {
  timeout_seconds?: number;
  max_disk_bytes?: number;
  max_file_size_bytes?: number;
  max_files_modified?: number;
  network_egress_allowed?: boolean;
}

export interface WorkspaceMetadata {
  workspace_id: string;
  task_id: string;
  repository_id: string;
  base_revision: string;
  branch_name: string;
  workspace_path?: string;
  status: WorkspaceStatus;
  isolation_type?: 'git_worktree' | 'directory_copy' | string;
  resource_limits?: WorkspaceResourceLimits;
  created_at?: string;
  updated_at?: string;
  started_at?: string | null;
  stopped_at?: string | null;
  cleaned_at?: string | null;
  error_message?: string | null;
}

// ============================================================================
// 10. Code Changes & Git Diff Telemetry (VERIFIED: backend/app/integrations/github/schemas.py)
// ============================================================================

export type DiffChangeStatus = 'added' | 'removed' | 'modified' | 'renamed' | 'unchanged';

export interface LineRange {
  start_line: number;
  end_line: number;
  change_type?: string;
}

export interface FileDiffRange {
  file_path: string;
  status: DiffChangeStatus;
  diff_ranges?: LineRange[];
  additions: number;
  deletions: number;
  patch?: string | null;
}

export interface TaskDiffRanges {
  task_id: string;
  repository_id?: string | null;
  base_branch?: string;
  head_branch?: string;
  files: FileDiffRange[];
  total_files_changed: number;
  total_additions: number;
  total_deletions: number;
}

// ============================================================================
// 11. Test Runner & Bounded Self-Repair (VERIFIED: backend/sandbox/test_runner.py & schemas/workspace.py)
// ============================================================================

export type TestOutcomeStatus =
  | 'PASSED'
  | 'FAILED'
  | 'ERROR'
  | 'TIMEOUT'
  | 'UNSUPPORTED_FRAMEWORK'
  | 'AMBIGUOUS'
  | 'NO_TESTS_FOUND'
  | 'SKIPPED'
  | 'NOT_RUN'
  | 'UNAVAILABLE';

export type TestFailureClassification =
  | 'NONE'
  | 'TEST_FAILURE'
  | 'INFRASTRUCTURE_ERROR'
  | 'TIMEOUT'
  | 'SECURITY_VIOLATION';

export interface RepairAttemptRecord {
  attempt_number: number;
  task_id: string;
  timestamp: string;
  patch_summary: string;
  patch_hash?: string | null;
  workspace_revision?: string | null;
  test_status_before?: TestOutcomeStatus | string | null;
  test_status_after?: TestOutcomeStatus | string | null;
  success: boolean;
}

export interface WorkspaceRepairBudgetStatus {
  task_id: string;
  repair_attempts_used: number;
  repair_attempts_max: number;
  is_budget_exhausted: boolean;
  is_eligible_for_repair: boolean;
  last_attempt_at?: string | null;
  history?: RepairAttemptRecord[];
}

// ============================================================================
// 12. Day 5–7 Git Commit, Push, Draft PR, Checkpoints & Crash Recovery Models
// ============================================================================

export interface TaskPullRequestResponse {
  pr_id?: string;
  task_id: string;
  repository_id?: string;
  pr_number?: number | null;
  pr_url: string;
  base_branch: string;
  head_branch: string;
  head_sha?: string;
  is_draft: boolean;
  title: string;
  body?: string | null;
  created_at?: string | null;
  status?: string;
  summary?: string;
}

export type TaskPullRequest = TaskPullRequestResponse;

export interface TaskCheckpointResponse {
  checkpoint_id: string;
  task_id: string;
  step_name: string;
  state_data: Record<string, unknown>;
  recovery_instructions?: string | null;
  created_at?: string | null;
}

export interface TaskRecoveryResponse {
  task_id: string;
  previous_status: TaskStatus | string;
  current_status?: TaskStatus | string;
  recovered_status?: string;
  repair_attempts_used?: number;
  repair_attempts_max?: number;
  restored_checkpoint?: TaskCheckpointResponse | null;
  workspace_recovery?: Record<string, unknown> | null;
  reconciliation_action?: string;
  details?: string;
  recovered_at?: string;
  success?: boolean;
  message?: string;
}

// ============================================================================
// 13. Lifecycle Helpers
// ============================================================================

/**
 * Check if the task is actively running execution, testing, self-repair, verification, or publishing.
 */
export function isExecutionActive(status: TaskStatus): boolean {
  return (
    status === TaskStatus.WORKSPACE_SETUP ||
    status === TaskStatus.EXECUTING ||
    status === TaskStatus.TESTING ||
    status === TaskStatus.REPAIRING ||
    status === TaskStatus.VERIFYING ||
    status === TaskStatus.PUBLISHING
  );
}

/**
 * Check if task is in a state eligible for cancellation.
 * Terminal states (CANCELLED, FAILED, DRAFT_PR_CREATED) cannot be cancelled.
 */
export function canCancelTask(status: TaskStatus): boolean {
  return (
    status !== TaskStatus.CANCELLED &&
    status !== TaskStatus.FAILED &&
    status !== TaskStatus.DRAFT_PR_CREATED
  );
}

/**
 * Check if task is eligible for recovery actions.
 */
export function canRecoverTask(status: TaskStatus): boolean {
  return (
    status === TaskStatus.RECOVERY_REQUIRED ||
    status === TaskStatus.FAILED ||
    status === TaskStatus.BLOCKED
  );
}

export interface PublicationEligibilityOptions {
  status: TaskStatus;
  verification?: VerificationResult | null;
  isStale?: boolean;
  isLoadingVerification?: boolean;
  hasVerificationError?: boolean;
  isStaleCheckLoading?: boolean;
  hasStaleCheckError?: boolean;
  hasBranchMetadata?: boolean;
  baseBranch?: string | null;
}

/**
 * Check if task is eligible for publication authorization.
 * Strict fail-closed policy (ADR-010 & Week 3 Day 7):
 * 1. Task status must be strictly READY_FOR_PUBLICATION
 * 2. Independent verification data must be present (missing or loading data blocks publication)
 * 3. Verification API errors strictly block publication
 * 4. Verification overall status must be strictly PASS
 * 5. Zero blocking findings permitted
 * 6. Verified revision must be non-empty and current (not stale)
 * 7. Stale check errors or pending stale check strictly block publication
 * 8. Missing branch metadata or base branch blocks publication
 */
export function isPublicationEligible(
  statusOrContext: TaskStatus | PublicationEligibilityOptions,
  verification?: VerificationResult | null,
  isStale?: boolean,
  isLoadingVerification?: boolean,
  hasVerificationError?: boolean,
  options?: {
    isStaleCheckLoading?: boolean;
    hasStaleCheckError?: boolean;
    hasBranchMetadata?: boolean;
    baseBranch?: string | null;
  }
): boolean {
  let status: TaskStatus;
  let verif: VerificationResult | null | undefined;
  let stale: boolean | undefined;
  let loadingVerif: boolean | undefined;
  let verifError: boolean | undefined;
  let staleLoading: boolean | undefined;
  let staleError: boolean | undefined;
  let branchMeta: boolean | undefined;
  let baseBr: string | null | undefined;

  if (typeof statusOrContext === 'object' && statusOrContext !== null && 'status' in statusOrContext) {
    status = statusOrContext.status;
    verif = statusOrContext.verification;
    stale = statusOrContext.isStale;
    loadingVerif = statusOrContext.isLoadingVerification;
    verifError = statusOrContext.hasVerificationError;
    staleLoading = statusOrContext.isStaleCheckLoading;
    staleError = statusOrContext.hasStaleCheckError;
    branchMeta = statusOrContext.hasBranchMetadata;
    baseBr = statusOrContext.baseBranch;
  } else {
    status = statusOrContext as TaskStatus;
    verif = verification;
    stale = isStale;
    loadingVerif = isLoadingVerification;
    verifError = hasVerificationError;
    staleLoading = options?.isStaleCheckLoading;
    staleError = options?.hasStaleCheckError;
    branchMeta = options?.hasBranchMetadata;
    baseBr = options?.baseBranch;
  }

  // 1. Task status must be strictly READY_FOR_PUBLICATION
  if (status !== TaskStatus.READY_FOR_PUBLICATION) {
    return false;
  }

  // 2. Loading verification data blocks publication
  if (loadingVerif) {
    return false;
  }

  // 3. Loading stale-check blocks publication
  if (staleLoading) {
    return false;
  }

  // 3. Verification API errors block publication
  if (verifError) {
    return false;
  }

  // 4. Missing verification data blocks publication (Fail-closed gate)
  if (!verif) {
    return false;
  }

  // 5. Verification status must be strictly PASS
  if (verif.status !== 'PASS') {
    return false;
  }

  // 6. Blocking findings block publication
  if (verif.blocking_findings && verif.blocking_findings.length > 0) {
    return false;
  }

  // 7. Verified revision must be present and valid
  if (!verif.verified_revision || typeof verif.verified_revision !== 'string' || verif.verified_revision.trim() === '') {
    return false;
  }

  // 8. Stale verification blocks publication
  if (stale) {
    return false;
  }

  // 9. Stale-check error blocks publication (Fail-closed per Requirement 3)
  if (staleError) {
    return false;
  }

  // 10. Missing branch metadata blocks publication if explicitly evaluated
  if (branchMeta === false) {
    return false;
  }

  // 11. Missing base branch blocks publication if evaluated
  if (baseBr === null || baseBr === '') {
    return false;
  }

  return true;
}

// ============================================================================
// 13. GitHub Pull Request & Publication (VERIFIED: backend/app/schemas/workspace.py)
// ============================================================================

// TaskPullRequest unified with TaskPullRequestResponse above

export interface PublishTaskRequest {
  title?: string;
  body?: string;
  publication_authorized: boolean;
  base_branch?: string;
  target_repository?: string;
  authorization_notes?: string;
}

export interface TaskPublicationResponse {
  success: boolean;
  task_id: string;
  pr_number?: number | null;
  pr_url?: string | null;
  head_branch: string;
  base_branch: string;
  is_draft: boolean;
  summary: string;
  created_at: string;
  error?: string | null;
}

// ============================================================================
// 14. Reliability, Recovery & Stale Revision Schemas (Docs/week3.md §8 Day 6)
// ============================================================================

export interface StaleRevisionCheckResult {
  task_id: string;
  is_stale: boolean;
  workspace_base_revision: string;
  current_base_revision: string;
  current_remote_sha: string;
  commits_behind: number;
  remediation_suggestion?: string | null;
  message: string;
  checked_at: string;
}

export interface TaskRecoveryRequest {
  action?: 'retry' | 'reconcile' | 'reset_to_plan' | 'resume';
  reason?: string;
}

// TaskRecoveryResponse unified above

export interface TriggerVerificationRequest {
  force_reverify?: boolean;
  verification_types?: string[];
  run_tests_if_missing?: boolean;
  require_passing_tests?: boolean;
  allow_critical_deletions?: boolean;
  strict_scope?: boolean;
  base_revision?: string;
}

export interface SecurityEventItem {
  id: string;
  task_id: string;
  event_type: string;
  severity: FindingSeverity;
  description: string;
  rule_id?: string | null;
  blocked: boolean;
  sanitized_message: string;
  timestamp: string;
}
