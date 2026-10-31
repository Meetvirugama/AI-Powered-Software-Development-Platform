/**
 * Week 3 Day 1 & Day 2 Frontend TypeScript Contracts:
 * - F31 GitHub Issue Integration (import issue, list issues, create issue from finding)
 * - F32 Task Intake, Structured Implementation Plan & Human Approval Gate
 * - F38 Task Dashboard & Ordered Execution Timeline
 */

export type TaskStatus =
  | 'CREATED'
  | 'PLANNING'
  | 'PENDING_APPROVAL'
  | 'APPROVED'
  | 'REJECTED'
  | 'WORKSPACE_SETUP'
  | 'EXECUTING'
  | 'TESTING'
  | 'REPAIRING'
  | 'VERIFYING'
  | 'READY_FOR_PUBLICATION'
  | 'PUBLISHING'
  | 'DRAFT_PR_CREATED'
  | 'FAILED'
  | 'CANCELLED'
  | 'RECOVERY_REQUIRED'
  | 'BLOCKED';

export type TaskSourceType = 'GITHUB_ISSUE' | 'BUG_FINDING' | 'REVIEW_FINDING' | 'USER_PROMPT';

export interface TaskSourceReference {
  type: TaskSourceType;
  issue_number?: number | null;
  issue_url?: string | null;
  url?: string | null;
  finding_id?: string | null;
  repository_id?: string | null;
  base_revision?: string | null;
}

export type TaskRequirementCategory = 'functional' | 'bug_fix' | 'refactor' | 'security' | 'test';

export interface TaskRequirement {
  id: string;
  description: string;
  category: TaskRequirementCategory;
  target_files: string[];
  acceptance_criteria: string[];
}

export interface TaskAssumption {
  id: string;
  description: string;
  unresolved: boolean;
  risk_level: 'low' | 'medium' | 'high';
}

export type TaskConstraintType =
  | 'protected_file'
  | 'forbidden_dependency'
  | 'backward_compatibility'
  | 'resource_limit'
  | 'security_policy';

export interface TaskConstraint {
  id: string;
  description: string;
  constraint_type: TaskConstraintType;
  forbidden_files: string[];
  forbidden_packages: string[];
  max_budget_tokens?: number | null;
}

export type PlanStepActionType = 'inspect' | 'modify' | 'create' | 'delete' | 'test' | 'verify';

export interface PlanStep {
  step_id: string;
  title: string;
  description: string;
  action_type: PlanStepActionType;
  expected_files: string[];
  target_symbols: string[];
  depends_on: string[];
  tests_to_run: string[];
  verification: string[];
}

export interface PlanRisk {
  id: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  description: string;
  mitigation: string;
  affected_files: string[];
}

export interface PlanResourceBudget {
  max_tokens: number;
  max_repair_attempts: number;
  max_execution_seconds: number;
  max_files_modified: number;
}

export interface TaskPlan {
  plan_id: string;
  task_id: string;
  plan_version: number;
  base_revision?: string | null;
  plan_hash: string;
  summary: string;
  problem_statement: string;
  assumptions: TaskAssumption[];
  relevant_files: string[];
  relevant_symbols: string[];
  steps: PlanStep[];
  expected_files: string[];
  tests_to_run: string[];
  validation_strategy: string[];
  risks: PlanRisk[];
  required_permissions: string[];
  resource_budget: PlanResourceBudget;
  status: string;
  approved_plan_version?: number | null;
  is_approved: boolean;
  created_at: string;
  updated_at: string;
}

export interface TaskApproval {
  approval_id: string;
  task_id: string;
  plan_id: string;
  plan_version: number;
  approver_id: string;
  decision: 'APPROVED' | 'REJECTED';
  comment?: string | null;
  base_revision?: string | null;
  plan_hash: string;
  task_status: TaskStatus;
  approved_plan_version?: number | null;
  created_at: string;
}

export interface TaskEvent {
  event_id: string;
  task_id: string;
  event_type: string;
  actor_id?: string | null;
  from_status?: string | null;
  to_status?: string | null;
  summary: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface TaskSummary {
  task_id: string;
  repository_id: string;
  title: string;
  status: TaskStatus;
  source_type: TaskSourceType;
  source: TaskSourceReference;
  base_revision?: string | null;
  plan_version: number;
  approved_plan_version?: number | null;
  repair_attempts_used: number;
  repair_attempts_max: number;
  created_at: string;
  updated_at: string;
}

export interface TaskDetail extends TaskSummary {
  description: string;
  requirements: TaskRequirement[];
  assumptions: TaskAssumption[];
  constraints: TaskConstraint[];
  latest_plan?: TaskPlan | null;
  approvals: TaskApproval[];
}

export interface PaginatedTaskListResponse {
  items: TaskSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface GitHubIssueItem {
  id: string;
  repository_id: string;
  issue_number: number;
  title: string;
  body: string;
  state: string;
  labels: string[];
  html_url: string;
  author?: string | null;
  origin_finding_id?: string | null;
  task_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface IssueImportResponse {
  task_id: string;
  repository_id: string;
  source: TaskSourceReference;
  title: string;
  status: TaskStatus;
  issue: GitHubIssueItem;
  duplicate_reused: boolean;
}

export interface CreateIssueFromFindingPayload {
  finding_id?: string;
  title?: string;
  body?: string;
  labels?: string[];
  create_task?: boolean;
}

export interface ImportIssuePayload {
  issue_number: number;
  base_revision?: string;
  title?: string;
  body?: string;
  labels?: string[];
}

export interface CreateTaskPayload {
  repository_id: string;
  title: string;
  description: string;
  source: TaskSourceReference;
  requirements: TaskRequirement[];
  assumptions?: TaskAssumption[];
  constraints?: TaskConstraint[];
  base_revision?: string;
}
