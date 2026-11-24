/**
 * AUTO-GENERATED FILE — DO NOT EDIT DIRECTLY.
 * Generated from FastAPI OpenAPI schema via backend/scripts/generate_openapi_types.py (OPT-03).
 */

/**
 * Request schema for creating an agent execution branch.
 */
export interface AgentBranchRequest {
  /** Task ID transitioning to EXECUTING */
  task_id: string;
  /** Optional base branch (defaults to repo default) */
  base_branch?: string | null;
}

/**
 * Response schema for agent branch creation/reuse.
 */
export interface AgentBranchResponse {
  branch_name: string;
  base_branch: string;
  base_sha: string;
  status: string;
}

/**
 * Bounded execution and context options shared by intelligence endpoints.
 */
export interface AnalysisOptions {
  /** Whether to enrich analysis with related symbols and RAG chunks. */
  include_context?: boolean;
  /** Maximum token budget allocated for intelligence context. */
  max_context_tokens?: number;
  /** Whether to record the analysis run in history persistence. */
  persist_run?: boolean;
}

/**
 * Detailed record for `GET /api/v1/analysis-runs/{run_id}`.
 */
export interface AnalysisRunDetailResponse {
  id: string;
  repository_id: string;
  user_id?: string | null;
  feature_type: "explain" | "detect_bugs" | "generate_tests" | "review" | "bugs" | "tests";
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
  target_path?: string | null;
  target_symbol?: string | null;
  start_line?: number | null;
  end_line?: number | null;
  source_revision?: string | null;
  findings_count?: number;
  result_payload?: Record<string, unknown> | null;
  test_output?: string | null;
  findings?: (BugFinding | ReviewFinding)[];
  error_message?: string | null;
  created_at: string;
  completed_at?: string | null;
}

/**
 * Repository-scoped Day 7 summary, integrity, and retention metrics (`GET /repositories/{id}/analysis-runs/summary`).
 */
export interface AnalysisRunMetricsSummaryResponse {
  repository_id: string;
  total_runs?: number;
  by_feature?: Record<string, number>;
  by_status?: Record<string, number>;
  total_findings?: number;
  integrity_status?: string;
  integrity_issues_count?: number;
  retention?: Record<string, unknown>;
}

/**
 * Summary item for `GET /api/v1/repositories/{repository_id}/analysis-runs`.
 */
export interface AnalysisRunSummary {
  id: string;
  repository_id: string;
  user_id?: string | null;
  feature_type: "explain" | "detect_bugs" | "generate_tests" | "review" | "bugs" | "tests";
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
  target_path?: string | null;
  target_symbol?: string | null;
  start_line?: number | null;
  end_line?: number | null;
  source_revision?: string | null;
  findings_count?: number;
  error_message?: string | null;
  created_at: string;
  completed_at?: string | null;
}

/**
 * Consistent representation for source evidence across all Week 2 features.
 * 
 * Line ranges (`start_line`, `end_line`) are 1-indexed and inclusive.
 * When an exact line mapping is unavailable, `start_line` and `end_line` must
 * remain `None` rather than inventing line numbers.
 */
export interface AnalysisSourceReference {
  /** UUID of the repository, if bound to a persisted record. */
  repository_id?: string | null;
  /** Repository-relative file path, e.g. 'backend/app/main.py'. */
  file_path: string;
  /** 1-indexed inclusive start line, or None if unavailable. */
  start_line?: number | null;
  /** 1-indexed inclusive end line, or None if unavailable. */
  end_line?: number | null;
  /** Git commit SHA or branch revision analysed. */
  revision?: string | null;
  /** Optional function, class, or method name at this location. */
  symbol_name?: string | null;
}

/**
 * Identifies the file, symbol, or line range within an authorized repository.
 */
export interface AnalysisTarget {
  /** Target granularity: 'file', 'symbol', or 'range'. */
  type?: "file" | "symbol" | "range";
  /** Repository-relative file path, e.g. 'src/example.py'. */
  path: string;
  /** 1-indexed inclusive start line. */
  start_line?: number | null;
  /** 1-indexed inclusive end line. */
  end_line?: number | null;
  /** Target function, method, or class name when type='symbol'. */
  symbol?: string | null;
  /** Optional source revision / commit SHA. */
  revision?: string | null;
}

export interface AuthenticatedUser {
  id: string;
  login: string;
  name?: string | null;
  email?: string | null;
  avatar_url?: string | null;
  role?: string;
}

/**
 * A repository accessible via the user's GitHub App installation.
 */
export interface AvailableRepository {
  github_repo_id: string;
  owner: string;
  name: string;
  full_name: string;
  default_branch: string;
  language: string | null;
  is_connected?: boolean;
}

/**
 * Request body for `POST /api/v1/repositories/{repository_id}/detect-bugs`.
 */
export interface BugDetectionRequest {
  target: AnalysisTarget;
  options?: AnalysisOptions;
  /** Run configured static analysis adapters (Ruff/Bandit/secret checks). */
  include_static?: boolean;
  /** Run AI-assisted defect reasoning. */
  include_ai?: boolean;
  /** Minimum finding severity threshold to include. */
  min_severity?: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";
  /** Scan mode: 'quick', 'standard', 'deep', or 'change'. */
  scan_mode?: string;
  /** Optional list of changed files for change/regression scan scope. */
  changed_files?: string[];
}

/**
 * Envelope returned by `POST /api/v1/repositories/{repository_id}/detect-bugs`.
 */
export interface BugDetectionResponse {
  run_id: string;
  repository_id: string;
  status?: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
  target: AnalysisTarget;
  revision?: string | null;
  findings?: BugFinding[];
  total_findings?: number;
  static_findings_count?: number;
  ai_findings_count?: number;
  missing_context?: string[];
  created_at?: string;
  stage_metrics?: Record<string, unknown> | null;
}

/**
 * A single static, AI, or combined defect finding (Docs/week2.md §4.4 & §7).
 */
export interface BugFinding {
  id: string;
  /** Defect class, e.g. 'off_by_one', 'null_safety', 'unhandled_exception'. */
  category: "off_by_one" | "null_safety" | "unhandled_exception" | "boundary_condition" | "resource_leak" | "race_condition" | "logic_error" | "security" | "supply_chain" | "secrets" | "other" | string;
  /** Finding severity: CRITICAL, HIGH, MEDIUM, LOW, or INFO. */
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";
  title: string;
  /** What may be wrong and why the pattern may be defective. */
  description: string;
  source_reference: AnalysisSourceReference;
  /** Concrete code or static-rule evidence supporting the finding. */
  evidence: string;
  /** Suggested remediation when justified by evidence. */
  suggested_fix?: string | null;
  confidence?: "high" | "medium" | "low";
  /** True when runtime defect confirmation requires external context. */
  is_uncertain?: boolean;
  /** Origin of finding: STATIC, AI, or COMBINED. */
  source_type?: "STATIC" | "AI" | "COMBINED" | "HYBRID";
  /** Static analyzer rule identifier (e.g. 'F821', 'B105') when applicable. */
  rule_id?: string | null;
  /** Finding origin provenance: 'static_rule', 'llm', or 'combined'. */
  provenance?: string | null;
  /** Static rule or analyzer version. */
  rule_version?: string | null;
  /** LLM provider or model name when AI-generated. */
  model_version?: string | null;
  /** Stable deduplication key across runs and engines. */
  deduplication_key?: string | null;
  /** Cryptographic SHA-256 hash of the evidence snippet. */
  evidence_hash?: string | null;
  /** Calculated 0-100 bug priority based on severity, reachability, exploitability, blast radius, confidence. */
  priority_score?: number | null;
  /** Validation evidence level: PROVEN, STRONG, SUSPECTED, or NEEDS_CONTEXT. */
  evidence_level?: string;
  /** Cross-file caller/callee trace connecting source to sink. */
  dependency_trace?: string[];
  /** Guards, tests, or sanitizers inspected during counterevidence validation. */
  counterevidence?: string[];
  /** Reproduction status: NOT_TESTED, REPRODUCED, or REPRODUCTION_FAILED. */
  reproduction_status?: string;
}

/**
 * A prior user or assistant turn supplied with a repository chat request.
 */
export interface ChatHistoryMessage {
  role: "user" | "assistant";
  content: string;
}

/**
 * Structured explanation output validated against Dev's CodeExplanationService.
 */
export interface CodeExplanation {
  /** What the selected code is intended to do. */
  purpose: string;
  /** Major execution steps in chronological order. */
  logic_flow?: string[];
  /** Important functions, classes, variables, and types. */
  key_symbols?: SymbolSummary[];
  /** Parameters, return values, and side effects. */
  inputs_and_outputs: string;
  /** Imports, callers, and related components grounded in context. */
  dependencies?: string[];
  /** What cannot be confirmed from the available repository context. */
  assumptions_and_limitations?: string[];
  /** Grounded file and line citations supporting the explanation. */
  sources?: AnalysisSourceReference[];
  /** Grounding confidence level ('high', 'medium', 'low'). */
  confidence?: "high" | "medium" | "low";
  /** Explicit list of unavailable files, callers, or context items. */
  missing_context?: string[];
  /** Runtime execution flow across repository components. */
  execution_flow?: string[];
  /** Related repository files utilized in context assembly. */
  related_files?: string[];
  /** In-depth technical and algorithmic explanation of how the code operates. */
  detailed_explanation?: string | null;
  /** Detailed breakdown of code outputs, calculation formulas, field meanings, and concrete examples. */
  code_output_explanation?: string | null;
  /** Identified flaws, bugs, vulnerabilities, or edge cases and proposed solutions. */
  code_issues_and_solutions?: string[];
  /** Corrected, production-grade refactoring of the code solving identified issues. */
  corrected_code?: string | null;
  /** True when reconstructed source chunks contained [REDACTED] secret/config placeholders. */
  has_redacted_content?: boolean;
  /** Number of [REDACTED] placeholders detected in reconstructed target or context source. */
  redacted_occurrences?: number;
  /** Human-readable security notice surfaced in the UI when source contains [REDACTED] tokens. */
  redaction_notice?: string | null;
  /** True when 'Explain at depth' mode traversed 1-hop callers and callees in the call graph. */
  call_graph_depth_expanded?: boolean;
  /** 1-hop caller symbols included during depth-mode call graph expansion. */
  expanded_callers?: string[];
  /** 1-hop callee symbols included during depth-mode call graph expansion. */
  expanded_callees?: string[];
}

/**
 * Envelope returned by `POST /api/v1/repositories/{repository_id}/explain`.
 */
export interface CodeExplanationResponse {
  run_id: string;
  repository_id: string;
  status?: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
  target: AnalysisTarget;
  revision?: string | null;
  explanation: CodeExplanation;
  created_at?: string;
  stage_metrics?: Record<string, unknown> | null;
}

/**
 * Request body for `POST /api/v1/repositories/{repository_id}/review`.
 */
export interface CodeReviewRequest {
  target: ReviewTarget;
  options?: AnalysisOptions;
  /** Run static linters and secret checks on reviewed files. */
  include_static?: boolean;
}

export interface CodeSymbolResponse {
  id: string;
  file_id: string;
  name: string;
  kind: string;
  start_line: number;
  end_line: number;
  signature: string | null;
  parent_id: string | null;
}

/**
 * Author or committer identity.
 */
export interface CommitAuthor {
  name: string;
  email?: string | null;
  date?: string | null;
}

/**
 * Metadata for a single commit.
 */
export interface CommitDetail {
  sha: string;
  message: string;
  author: CommitAuthor;
  committer?: CommitAuthor | null;
  date?: string | null;
  parents?: string[];
  files?: CommitFileChange[];
  stats?: Record<string, unknown> | null;
}

/**
 * A file changed in a commit.
 */
export interface CommitFileChange {
  filename: string;
  status: DiffStatus;
  additions?: number;
  deletions?: number;
  changes?: number;
  patch?: string | null;
}

/**
 * Paginated list of commits.
 */
export interface CommitListResponse {
  commits: CommitDetail[];
  total?: number | null;
  page: number;
  per_page: number;
}

/**
 * Request to stage workspace agent changes into a local Git commit.
 */
export interface CommitStagingRequest {
  /** Absolute or relative path to agent workspace */
  workspace_path: string;
  /** Commit message */
  commit_message: string;
  /** Task ID for branch validation */
  task_id?: string | null;
  /** Specific relative file paths to stage */
  files?: string[] | null;
  /** Git author name */
  author_name?: string;
  /** Git author email */
  author_email?: string;
  /** Allow empty commit if no changes exist */
  allow_empty?: boolean;
}

/**
 * Result of a local workspace commit.
 */
export interface CommitStagingResponse {
  commit_sha: string;
  branch: string;
  message: string;
  files_changed: string[];
  insertions?: number;
  deletions?: number;
  pushed?: boolean;
}

export interface ComponentHealth {
  status: string;
  message?: string | null;
}

/**
 * Response after successfully connecting a repository.
 */
export interface ConnectRepositoryResponse {
  repository_id: string;
  job_id: string;
}

/**
 * Runtime coverage delta report (task.md §5).
 */
export interface CoverageReport {
  baseline_line_coverage?: number | null;
  final_line_coverage?: number | null;
  line_coverage_gain?: number | null;
  baseline_branch_coverage?: number | null;
  final_branch_coverage?: number | null;
  branch_coverage_gain?: number | null;
  newly_covered_lines?: number[];
  newly_covered_branches?: number[][];
  coverage_attributable_to_generated_tests?: boolean;
  collection_status?: "SUCCESS" | "PARTIAL" | "FAILED" | "NOT_CONFIGURED";
  warnings?: string[];
}

/**
 * Immutable metadata tracking the origin, lineage, and taint status of data.
 */
export interface DataProvenance {
  /** Globally unique provenance identifier. */
  provenance_id?: string;
  /** Category of origin: github_issue, github_comment, finding_evidence, user_prompt, platform_constraint, etc. */
  source_type: string;
  /** External source identifier (e.g. issue number, finding UUID). */
  source_id?: string | null;
  /** Target repository UUID string when applicable. */
  source_repository_id?: string | null;
  /** Contextual reference descriptor (e.g. URL, file path, commit SHA). */
  source_reference?: string | null;
  /** Platform-assigned trust level. Must never be set directly by LLM content. */
  trust_level: TrustLevel;
  /** True if originated from or influenced by an untrusted external entity. */
  tainted: boolean;
  /** List of parent provenance IDs from which this data was derived. */
  parent_ids?: string[];
  /** Description of the operation that created this entity (e.g. intake_fence, llm_plan, replan_recovery). */
  transformation?: string | null;
  /** UTC timestamp of provenance record creation. */
  created_at?: string;
  /** Additional non-sensitive provenance context (e.g. requirement_id, step_id). */
  metadata?: Record<string, unknown>;
}

/**
 * Status of a file within a diff.
 */
export type DiffStatus = "added" | "removed" | "modified" | "renamed" | "unchanged";

/**
 * A discovered related file with relationship type, weight, PageRank importance, and co-change metrics.
 */
export interface DiscoveredRelatedFile {
  path: string;
  relation: "imported_dependency" | "called_dependency" | "caller" | "type_definition" | "database_model" | "associated_test" | "co_change_coupled" | "indirect_dependency" | "semantic_match";
  relation_label: string;
  weight: number;
  reason: string;
  symbols?: string[];
  is_preselected?: boolean;
  importance_score?: number;
  co_change_score?: number;
}

/**
 * Machine-readable error payload returned on all failure responses.
 */
export interface ErrorDetailSchema {
  /** Machine-readable error code (e.g. UNAUTHORIZED, REPOSITORY_NOT_FOUND). */
  code: string;
  /** Human-readable, secret-redacted error description. */
  message: string;
  /** True when the client may safely retry the request. */
  retryable?: boolean;
}

/**
 * Standardized error envelope across all Developer Intelligence APIs.
 */
export interface ErrorResponseEnvelope {
  error: ErrorDetailSchema;
}

/**
 * Execution policy constraints for a plan step or entire plan (task.md §5 B).
 */
export interface ExecutionPolicy {
  max_attempts?: number;
  timeout_seconds?: number;
  require_approval?: boolean;
  allowed_tools?: string[];
  rollback_on_failure?: boolean;
}

/**
 * Request body for `POST /api/v1/repositories/{repository_id}/explain`.
 */
export interface ExplainCodeRequest {
  target: AnalysisTarget;
  options?: AnalysisOptions;
  context?: ExplainContextOptions;
  explanation_level?: "concise" | "detailed" | "deep_technical";
  /** Call-graph traversal depth mode: 'standard' (signatures) or 'deep' (1-hop caller & callee body snippets). */
  depth_mode?: "standard" | "deep";
  /** When True, follows the call graph one level (callers and callees) with full snippet expansion. */
  explain_at_depth?: boolean;
}

/**
 * Context selection options for Repository Intelligence Explain Studio (task.md §6.3 & Issue 2).
 */
export interface ExplainContextOptions {
  include_graph_context?: boolean;
  include_callers?: boolean;
  include_callees?: boolean;
  include_dependencies?: boolean;
  include_tests?: boolean;
  include_semantic_search?: boolean;
  /** Follow the call graph 1 hop (both callers and callees) and include their source body snippets (F07-C3). */
  explain_at_depth?: boolean;
  /** User-selected related files explicitly added to context. */
  selected_files?: string[];
}

/**
 * Response containing the content of a repository file.
 */
export interface FileContentResponse {
  path: string;
  content: string;
  encoding?: string;
  size_bytes: number;
  line_count: number;
  language?: string | null;
  /** Git blob SHA for cache validation. */
  sha?: string | null;
  /** Exact Git commit SHA corresponding to the retrieved revision. */
  commit_sha?: string | null;
  /** The resolved ref (branch/tag/SHA) used for retrieval. */
  ref?: string | null;
  /** True if the file contains binary content. */
  is_binary?: boolean;
  /** True if the content was served from the revision-safe cache. */
  from_cache?: boolean;
  /** True when the content was truncated to stay within size limits. */
  truncated?: boolean;
  source_reference?: app__integrations__github__schemas__SourceReference | null;
}

/**
 * File-level diff details with exact modified line ranges for AST symbol mapping.
 */
export interface FileDiffRange {
  /** Target file path relative to repo root */
  file_path: string;
  /** Diff change status */
  status?: DiffStatus;
  /** List of inclusive line ranges modified */
  diff_ranges?: LineRange[];
  additions?: number;
  deletions?: number;
  patch?: string | null;
}

/**
 * Response containing the file tree of a repository.
 */
export interface FileTreeResponse {
  ref?: string | null;
  sha?: string | null;
  entries: TreeEntry[];
  truncated?: boolean;
}

/**
 * Request payload for POST /api/v1/repositories/{repository_id}/issues.
 */
export interface GitHubIssueCreateRequest {
  /** Optional Week 2 AnalysisFinding ID (bug or review finding) to convert into an issue. */
  finding_id?: string | null;
  /** Issue title (auto-generated from finding if finding_id is provided). */
  title?: string | null;
  /** Issue body markdown (auto-generated from finding if finding_id is provided). */
  body?: string | null;
  /** Labels to attach to the created GitHub issue (e.g. ['bug', 'ai-finding']). */
  labels?: string[];
  /** If True, also normalizes the created issue into an internal development task. */
  create_task?: boolean;
}

/**
 * Request payload for POST /api/v1/repositories/{repository_id}/issues/import.
 */
export interface GitHubIssueImportRequest {
  /** GitHub issue number to import. */
  issue_number: number;
  /** Optional base commit SHA or branch ref for the imported task. */
  base_revision?: string | null;
  /** Optional fallback issue title when importing in offline/local mode. */
  title?: string | null;
  /** Optional fallback issue body when importing in offline/local mode. */
  body?: string | null;
  /** Optional issue labels. */
  labels?: string[];
}

/**
 * Normalized GitHub issue record returned by the API.
 */
export interface GitHubIssueResponse {
  id: string;
  repository_id: string;
  issue_number: number;
  title: string;
  body?: string;
  state?: string;
  labels?: string[];
  html_url: string;
  url?: string;
  author?: string | null;
  origin_finding_id?: string | null;
  task_id?: string | null;
  is_imported?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface HTTPValidationError {
  detail?: ValidationError[];
}

export interface HealthResponse {
  status?: string;
  version?: string;
}

/**
 * Normalized response for issue import & issue creation (Docs/week3.md §6 F31).
 */
export interface IssueImportResponse {
  task_id: string;
  repository_id: string;
  source: TaskSourceReference;
  title: string;
  status?: TaskStatus;
  issue: GitHubIssueResponse;
  duplicate_reused?: boolean;
}

/**
 * Report on coverage-guided iterative test generation rounds (task.md §6).
 */
export interface IterationReport {
  total_rounds?: number;
  rounds?: IterationRound[];
  stopping_reason?: string;
  final_coverage_achieved?: number | null;
}

/**
 * Information about a single iteration round in coverage-guided feedback (task.md §6).
 */
export interface IterationRound {
  round_number: number;
  scenarios_targeted?: string[];
  uncovered_lines_addressed?: number[];
  tests_added?: number;
  line_coverage_after?: number | null;
  tokens_used?: number | null;
}

/**
 * Inclusive 1-indexed line range affected by a diff hunk.
 * 
 * Used by AST symbol mappers (Prit Day 2) to match diff hunks with symbols:
 * code_symbols.start_line <= range.end_line AND code_symbols.end_line >= range.start_line.
 */
export interface LineRange {
  /** First modified line in new file (1-indexed, inclusive) */
  start_line: number;
  /** Last modified line in new file (1-indexed, inclusive) */
  end_line: number;
  /** Type of change: added, modified, deleted */
  change_type?: string;
}

export interface LinkInstallationRequest {
  installation_id: string;
}

/**
 * Agentless-style 3-stage hierarchical localization target (File -> Symbol -> Line Range) [Issue 3 / P-17].
 */
export interface LocalizationTarget {
  /** Repository-relative file path. */
  file_path: string;
  /** Localized class, method, or function name (Stage 2). */
  symbol_name?: string | null;
  /** Symbol category: function, method, class, module, etc. */
  symbol_kind?: string;
  /** 1-indexed inclusive start line of the localized edit region (Stage 3). */
  start_line?: number | null;
  /** 1-indexed inclusive end line of the localized edit region (Stage 3). */
  end_line?: number | null;
  /** Localization confidence score in [0.0, 1.0]. */
  confidence?: number;
  /** Deepest completed localization stage ('file', 'symbol', or 'line_range'). */
  localization_stage?: "file" | "symbol" | "line_range";
  /** Evidence explaining why this file/symbol/line-range was selected. */
  rationale?: string;
  /** PageRank importance score of the localized symbol or file (F05-C3). */
  importance_score?: number;
  /** Optional short code snippet preview for human plan review and edit synthesis. */
  snippet_preview?: string | null;
}

/**
 * Cancellation of a pending MCP elicitation.
 */
export interface MCPElicitationCancelRequest {
  session_id: string;
  reason?: string | null;
}

/**
 * Request from an external MCP server for structured user elicitation.
 */
export interface MCPElicitationRequest {
  session_id: string;
  elicitation_type: "form" | "url";
  prompt?: string | null;
  schema?: Record<string, unknown> | null;
  url?: string | null;
  purpose?: string | null;
  expires_in_seconds?: number | null;
}

/**
 * User response to a pending MCP elicitation.
 */
export interface MCPElicitationResponseSubmit {
  session_id: string;
  /** submit or cancel */
  action?: string;
  data?: Record<string, unknown> | null;
}

/**
 * MCP 2025-11-25 resource model exposing project memory.
 */
export interface MCPMemoryResource {
  uri: string;
  name: string;
  mimeType?: string;
  description?: string | null;
  text: string;
  entries_count?: number;
  metadata?: Record<string, unknown> | null;
}

export interface MCPMemoryResourcesListResponse {
  resources: MCPMemoryResource[];
}

export interface MCPServerSchema {
  id: string;
  name: string;
  transport?: string;
  endpointOrCommand: string;
  enabled?: boolean;
  status?: "connected" | "degraded" | "offline";
  protocolVersion?: string;
  lastLatencyMs?: number | null;
  tools?: MCPToolItemSchema[];
}

export interface MCPToolItemSchema {
  name: string;
  description: string;
  riskTier?: "low" | "medium" | "high" | "critical";
  requiresApproval?: boolean;
  inputSchemaJson: string;
}

export interface MemoryEntryCreate {
  /** Category of memory entry */
  type?: MemoryType;
  /** Content of the memory entry */
  content: string;
  /** Origin of the memory entry */
  source?: string;
  /** Lifecycle status */
  status?: MemoryStatus;
  /** Optional 768-dim vector embedding */
  embedding?: number[] | null;
}

export interface MemoryEntryResponse {
  id: string;
  repository_id: string;
  type: MemoryType;
  content: string;
  source: string;
  status: MemoryStatus;
  created_at: string;
  updated_at: string;
  embedding?: number[] | null;
}

export interface MemoryEntryUpdate {
  content?: string | null;
  status?: MemoryStatus | null;
  type?: MemoryType | null;
  source?: string | null;
  embedding?: number[] | null;
}

export type MemoryStatus = "active" | "stale" | "archived";

export type MemoryType = "project" | "decision" | "rule" | "task_summary" | "failure";

export interface OperationalReadinessMetrics {
  sync_worker_heartbeat_age_s?: number | null;
  webhook_backlog?: number | null;
  scanner_availability?: Record<string, boolean>;
  sandbox_backend_ok?: boolean;
}

/**
 * PR Metadata collected for Week 3 GitHub PR opening (week2.md Day 5).
 */
export interface PRMetadata {
  task_id: string;
  branch: string;
  base_branch?: string;
  changed_files: string[];
  commit_message: string;
  test_summary: string;
  verification_summary: string;
  repository_id?: string | null;
  pr_number?: number | null;
  pr_url?: string | null;
  status?: string;
}

/**
 * Paginated list of analysis runs for a repository.
 */
export interface PaginatedAnalysisRunResponse {
  page: number;
  page_size: number;
  total: number;
  items?: AnalysisRunSummary[];
}

/**
 * Paginated list of repositories discoverable via GitHub App.
 */
export interface PaginatedAvailableRepositoryResponse {
  items: AvailableRepository[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface PaginatedMemoryEntriesResponse {
  page: number;
  page_size: number;
  total: number;
  items: MemoryEntryResponse[];
}

export interface PaginatedResponse {
  page: number;
  page_size: number;
  total: number;
  items: RepositoryFileResponse[] | CodeSymbolResponse[];
}

/**
 * Paginated task list response.
 */
export interface PaginatedTaskListResponse {
  items?: TaskSummaryResponse[];
  total?: number;
  page?: number;
  page_size?: number;
}

/**
 * Request payload for POST /api/v1/tasks/{task_id}/approve.
 */
export interface PlanApprovalRequest {
  /** Explicit plan_version being approved. Must match the task's latest plan_version. */
  plan_version?: number | null;
  /** Optional base_revision assertion. If provided, must match the plan's base_revision. */
  base_revision?: string | null;
  /** Optional approver comment or sign-off note. */
  comment?: string | null;
  /** Alias for comment (used by frontend PlanReviewPanel). */
  notes?: string | null;
  /** Optional approver username or identifier. */
  approved_by?: string | null;
}

/**
 * Request payload for POST /api/v1/tasks/{task_id}/reject.
 */
export interface PlanRejectionRequest {
  /** Optional plan_version being rejected. */
  plan_version?: number | null;
  /** Reason for rejecting the plan. */
  reason?: string;
  /** Optional reviewer username or identifier. */
  rejected_by?: string | null;
}

/**
 * Resource budget limits enforced during plan execution (Docs/week3.md §6 F32 & F34).
 */
export interface PlanResourceBudget {
  max_tokens?: number;
  max_repair_attempts?: number;
  max_execution_seconds?: number;
  max_files_modified?: number;
}

/**
 * Identified architectural, regression, or security risk in an implementation plan.
 */
export interface PlanRisk {
  /** Risk identifier, e.g. 'risk_1'. */
  id?: string;
  /** Unique risk ID, e.g. 'rsk-1'. */
  risk_id?: string;
  severity?: string;
  /** Risk and potential side effect. */
  description?: string;
  /** How the plan mitigates or tests for this risk. */
  mitigation?: string;
  affected_files?: string[];
}

/**
 * A single ordered implementation step in a structured task plan (Docs/week3.md §6 F32).
 */
export interface PlanStep {
  /** Unique step identifier within the plan, e.g. 'step_1'. */
  step_id: string;
  /** Concise step title. */
  title?: string;
  /** Detailed explanation of the implementation action for this step. */
  description: string;
  /** Step category: inspect, modify, create, delete, test, verify, edit, refactor, or command. */
  action_type?: string;
  /** Category of action: inspect, edit, create, test, verify, refactor, or command. */
  step_type?: string;
  /** Repository-relative file paths read or modified during this step. */
  expected_files?: string[];
  /** Functions, classes, or symbols affected in this step. */
  target_symbols?: string[];
  /** Agentless 3-stage localized file/symbol/line-range targets for this step (Issue 3). */
  localization_targets?: LocalizationTarget[];
  /** Prerequisite step_ids that must complete before this step runs. */
  depends_on?: string[];
  /** List of step_ids that must complete successfully before this step can run. */
  dependencies?: string[];
  /** Requirement IDs satisfied or verified by this step. */
  requirement_ids?: string[];
  /** Concrete verification checks with evidence requirements. */
  step_verifications?: StepVerification[];
  /** Dynamic outcome routing transitions. */
  transitions?: PlanTransition[];
  /** Step-specific execution policy and timeout constraints. */
  execution_policy?: ExecutionPolicy | null;
  /** Permitted test files or test commands to execute for this step. */
  tests_to_run?: string[];
  /** Concrete verification criteria proving this step succeeded. */
  verification?: string[];
  /** Risk level of this specific step. */
  risk_level?: string;
  /** Estimated risk severity level. */
  estimated_risk?: string;
  /** Instructions or git commands to revert this step if it fails. */
  rollback_hint?: string | null;
  /** Instructions to revert this step. */
  rollback_instructions?: string | null;
  /** Estimated execution time in seconds. */
  estimated_duration_s?: number | null;
  /** Metadata tracking the origin and trust level of this step. */
  provenance?: DataProvenance | null;
  /** Parent provenance IDs from which this step was derived. */
  provenance_ids?: string[];
  /** True if this step is derived from untrusted input. */
  taint_status?: boolean;
  /** Field-level provenance mapping (e.g. {'description': 'prov-1', 'command': 'prov-2'}). */
  field_provenance?: Record<string, string>;
  /** True if execution policy mandates explicit human approval before running this step. */
  approval_required?: boolean;
  /** ID of associated ExecutionApproval record if approved. */
  approval_id?: string | null;
}

/**
 * Dynamic outcome routing transition for adaptive plan execution (task.md §3, §5 B).
 */
export interface PlanTransition {
  /** Outcome trigger: success, failure, blocked, or timeout. */
  outcome?: string;
  /** Next step to execute upon this outcome. */
  next_step_id?: string | null;
  /** Targeted recovery step if this step fails. */
  recovery_step_id?: string | null;
}

/**
 * Payload to pin an architectural convention or project rule.
 */
export interface ProjectRuleCreateRequest {
  rule: string;
  source?: string;
}

/**
 * Request model for authorizing branch publication and PR creation (Day 5).
 */
export interface PublicationAuthorizationRequest {
  head_sha: string;
  notes?: string | null;
}

/**
 * Response envelope confirming publication authorization (Day 5).
 */
export interface PublicationAuthorizationResponse {
  task_id: string;
  status: string;
  head_sha: string;
  authorized?: boolean;
  user_id?: string | null;
  authorized_at?: string | null;
}

/**
 * Full diff information for a pull request.
 */
export interface PullRequestDiffResponse {
  pull_request: PullRequestInfo;
  files: PullRequestFile[];
  total_additions?: number;
  total_deletions?: number;
  total_changes?: number;
}

/**
 * A file changed in a pull request.
 */
export interface PullRequestFile {
  filename: string;
  status: DiffStatus;
  additions?: number;
  deletions?: number;
  changes?: number;
  patch?: string | null;
  previous_filename?: string | null;
  sha?: string | null;
  contents_url?: string | null;
}

/**
 * Metadata about a pull request.
 */
export interface PullRequestInfo {
  number: number;
  title: string;
  state: string;
  draft?: boolean;
  author?: string | null;
  base_ref?: string | null;
  head_ref?: string | null;
  base_sha?: string | null;
  head_sha?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  merged_at?: string | null;
  body?: string | null;
}

export interface ReadinessResponse {
  status: string;
  version?: string;
  database: ComponentHealth;
  redis: ComponentHealth;
  llm_gateway: ComponentHealth;
  rag_pipeline: ComponentHealth;
  services: Record<string, string>;
  operations?: OperationalReadinessMetrics | null;
}

/**
 * Response containing discovered related files for an explanation target.
 */
export interface RelatedFilesDiscoveryResponse {
  target_path: string;
  target_symbol?: string | null;
  related_files?: DiscoveredRelatedFile[];
  total_discovered?: number;
}

/**
 * Metadata about a remote GitHub issue for source browsing.
 */
export interface RemoteIssueInfo {
  number: number;
  title: string;
  state?: string;
  body?: string | null;
  author?: string | null;
  labels?: string[];
  html_url?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  closed_at?: string | null;
  comments_count?: number;
  is_pull_request?: boolean;
}

/**
 * Bounded repair cycle attempt outcome (Day 4).
 */
export interface RepairAttemptResponse {
  repair_id: string;
  task_id: string;
  attempt_number: number;
  failure_classification?: string | null;
  diagnosis?: string | null;
  applied_patch?: string | null;
  result: string;
  created_at?: string | null;
}

export interface RepositoryAnswer {
}

export interface RepositoryAutomationSettingsResponse {
  github_repo_id: string;
  auto_sync_enabled?: boolean;
  pr_review_enabled?: boolean;
  pr_review_drafts?: boolean;
  last_indexed_commit_sha?: string | null;
}

/**
 * Question and optional conversation context for repository-aware chat.
 */
export interface RepositoryChatRequest {
  question: string;
  history?: ChatHistoryMessage[];
  /** Chat execution mode: 'normal' for fast standard RAG, 'agentic' for multi-step bounded investigation. */
  mode?: "normal" | "agentic";
}

export interface RepositoryDependencyResponse {
  name: string;
  version: string;
  ecosystem: string;
}

export interface RepositoryFileContentResponse {
  id: string;
  path: string;
  language: string | null;
  size_bytes: number;
  line_count: number;
  content: string;
  symbols?: CodeSymbolResponse[];
}

export interface RepositoryFileResponse {
  id: string;
  path: string;
  language: string | null;
  size_bytes: number;
  line_count: number;
  content_hash: string;
  last_indexed_at: string | null;
}

export interface RepositoryResponse {
  id: string;
  github_repo_id: string;
  owner: string;
  name: string;
  full_name: string;
  default_branch: string;
  language: string | null;
  sync_status: string;
  last_synced_at: string | null;
  description?: string | null;
  framework?: string | null;
  file_count?: number | null;
  symbol_count?: number | null;
  chunk_count?: number | null;
}

/**
 * A repository-scoped hybrid-search request (supports both query/top_k and q/limit aliases).
 */
export interface RepositorySearchRequest {
  q: string;
  limit?: number;
}

/**
 * Hybrid-search results in descending relevance order.
 */
export interface RepositorySearchResponse {
  query: string;
  results: RepositorySearchResult[];
}

/**
 * A code chunk returned by the RAG retrieval pipeline.
 */
export interface RepositorySearchResult {
  id: string;
  file_path: string;
  start_line: number;
  end_line: number;
  content: string;
  score: number;
}

/**
 * Developer feedback on an individual review finding (AutoCommenter).
 */
export interface ReviewFeedbackRequest {
  feedback_type: "useful" | "not_useful" | "false_positive" | "already_fixed" | "dismissed";
  comment?: string | null;
}

/**
 * Feedback submission outcome with updated repository stats.
 */
export interface ReviewFeedbackResponse {
  finding_id: string;
  feedback_type: string;
  user_id?: string | null;
  comment?: string | null;
  updated_at: string;
  repository_stats?: Record<string, unknown> | null;
}

/**
 * A single categorized finding within a standalone AI code review (Docs/week2.md §9).
 */
export interface ReviewFinding {
  id: string;
  /** Review dimension: correctness, security, performance, reliability, maintainability. */
  category: "correctness" | "security" | "performance" | "reliability" | "maintainability";
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";
  title: string;
  description: string;
  source_reference: AnalysisSourceReference;
  evidence: string;
  suggested_fix?: string | null;
  confidence?: "high" | "medium" | "low";
  is_uncertain?: boolean;
  /** True when evidence indicates the issue was introduced by the target change. */
  is_new_in_change?: boolean;
  source_type?: "STATIC" | "AI" | "COMBINED" | "HYBRID";
  rule_id?: string | null;
  /** Finding origin provenance: 'static_rule', 'llm', or 'combined'. */
  provenance?: string | null;
  /** Static rule or analyzer version. */
  rule_version?: string | null;
  /** LLM provider or model name when AI-generated. */
  model_version?: string | null;
  /** Stable deduplication key across runs and engines. */
  deduplication_key?: string | null;
  /** Cryptographic SHA-256 hash of the evidence snippet. */
  evidence_hash?: string | null;
  /** Calculated 0-100 bug priority based on severity, reachability, exploitability, blast radius, confidence. */
  priority_score?: number | null;
  /** Validation evidence level: PROVEN, STRONG, SUSPECTED, or NEEDS_CONTEXT. */
  evidence_level?: string;
  /** Cross-file caller/callee trace connecting source to sink. */
  dependency_trace?: string[];
  /** Guards, tests, or sanitizers inspected during counterevidence validation. */
  counterevidence?: string[];
  /** Reproduction status: NOT_TESTED, REPRODUCED, or REPRODUCTION_FAILED. */
  reproduction_status?: string;
}

/**
 * Payload to trigger manual publication of a code review run to a GitHub PR.
 */
export interface ReviewPublicationRequest {
  run_id?: string | null;
  pr_number: number;
  commit_sha?: string | null;
  force_publish?: boolean;
  max_comments?: number;
  min_confidence?: string;
  changed_lines_only?: boolean;
}

/**
 * Result of publishing a code review run to a GitHub PR.
 */
export interface ReviewPublicationResponse {
  status: string;
  review_id?: number | null;
  pr_number?: number | null;
  commit_sha?: string | null;
  published_comments_count?: number;
  skipped_reason?: string | null;
  error_message?: string | null;
  published_at?: string | null;
}

/**
 * Structured review report returned by Dev's AICodeReviewEngine.
 */
export interface ReviewReport {
  summary: string;
  risk_level?: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "NONE";
  findings?: ReviewFinding[];
  total_findings?: number;
  category_counts?: Record<string, number>;
  missing_context?: string[];
}

/**
 * Envelope returned by `POST /api/v1/repositories/{repository_id}/review`.
 */
export interface ReviewReportResponse {
  run_id: string;
  repository_id: string;
  status?: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
  target: ReviewTarget;
  report: ReviewReport;
  created_at?: string;
  stage_metrics?: Record<string, unknown> | null;
}

/**
 * Repository-level code review and publication configuration.
 */
export interface ReviewSettingsResponse {
  repository_id: string;
  pr_review_enabled?: boolean;
  pr_review_drafts?: boolean;
  min_confidence?: string;
  max_comments?: number;
  changed_lines_only?: boolean;
}

/**
 * Identifies a single file, commit SHA, unified diff, or GitHub PR for review.
 */
export interface ReviewTarget {
  /** Review target kind: 'file', 'commit', 'diff', or 'pr'. */
  type?: "file" | "commit" | "diff" | "pr";
  /** Repository-relative file path when type='file'. */
  path?: string | null;
  /** Git commit SHA when type='commit'. */
  commit_sha?: string | null;
  /** GitHub Pull Request number when type='pr'. */
  pr_number?: number | null;
  /** Unified diff text when type='diff'. */
  diff?: string | null;
  base_revision?: string | null;
  head_revision?: string | null;
}

/**
 * Payload to query memory entries via pgvector semantic similarity.
 */
export interface SemanticSearchRequest {
  /** Embedding vector to query against */
  query_vector: number[];
  type?: MemoryType | null;
  status?: MemoryStatus | null;
  limit?: number;
  min_similarity?: number;
}

export interface SemanticSearchResponse {
  query_limit: number;
  total_results: number;
  results: SemanticSearchResultItem[];
}

export interface SemanticSearchResultItem {
  entry: MemoryEntryResponse;
  similarity: number;
}

/**
 * Three-run stability report for flakiness filtering (task.md §4.6).
 */
export interface StabilityReport {
  total_runs?: number;
  passed_runs?: number;
  classification?: "STABLE" | "UNSTABLE" | "FAILED";
  is_stable?: boolean;
  runs?: StabilityRunResult[];
}

/**
 * Detailed result for an individual stability execution run (Phase 3).
 */
export interface StabilityRunResult {
  run_number: number;
  passed: boolean;
  exit_code?: number;
  duration_seconds?: number;
  passed_count?: number;
  failed_count?: number;
  error_message?: string | null;
}

/**
 * Specific verification check with observable pass criteria (task.md §5 B).
 */
export interface StepVerification {
  /** Unique criterion ID, e.g. 'crit-1'. */
  criterion_id?: string;
  /** What this check proves. */
  description?: string;
  /** Verification type: test, syntax, diff, command, or static. */
  verification_type?: string;
  /** Executable command or assertion rule. */
  command_or_check?: string | null;
  /** Expected outcome string or exit code. */
  expected_result?: string;
  /** Whether output evidence must be captured. */
  evidence_required?: boolean;
}

/**
 * Structured LLM / TaskPlanner output schema with step dependency DAG validation (Dev & Meet W3 Day 2).
 */
export interface StructuredPlan {
  /** Associated task identifier. */
  task_id?: string | null;
  /** Sequential version number of this plan. */
  plan_version?: number;
  /** Commit SHA from which this plan was generated. */
  base_revision?: string | null;
  /** Concise description of the proposed implementation. */
  summary: string;
  /** Detailed description of the issue or feature requirement being addressed. */
  problem_statement?: string;
  /** Technical and architectural assumptions underlying the plan. */
  assumptions?: unknown[];
  /** Open questions requiring clarification during human review. */
  unresolved_questions?: string[];
  /** Repository-relative file paths referenced by or relevant to the plan. */
  relevant_files?: string[];
  /** Key classes, methods, or functions relevant to the plan. */
  relevant_symbols?: string[];
  /** Agentless 3-stage localized candidate files, symbols, and 1-indexed line ranges (Issue 3 / P-17). */
  localization_targets?: LocalizationTarget[];
  /** Ordered list of atomic implementation steps. */
  steps: PlanStep[];
  /** All repository-relative files expected to be created or modified. */
  expected_files?: string[];
  /** Consolidated repository-relative file paths that will be created or edited. */
  expected_files_to_modify?: string[];
  /** Tests to add or execute to verify the implementation. */
  tests_to_run?: string[];
  /** Test commands or test files that must be executed. */
  tests_to_add_or_run?: string[];
  /** Strategy for testing, verification gates, and rollback. */
  validation_strategy?: unknown;
  /** Identified risks and their mitigations. */
  risks?: PlanRisk[];
  /** Identified risks and their mitigations. */
  risks_and_side_effects?: PlanRisk[];
  /** Tool and execution capabilities needed by the agent. */
  required_permissions?: string[];
  /** Discovered task requirements matrix (task.md §2, §5 B). */
  requirements?: unknown[];
  /** Summary of requirement coverage status and gaps. */
  requirement_coverage?: Record<string, unknown>;
  /** Repository Intelligence snapshot ID from which this plan was grounded. */
  context_snapshot_id?: string | null;
  /** Verification report certifying completeness against mandatory requirements. */
  completeness_report?: Record<string, unknown>;
  /** Execution limits, tool permissions, and timeout policies. */
  execution_policy?: ExecutionPolicy;
  /** Final acceptance and regression tests required before marking task complete. */
  final_validation_strategy?: string[];
  /** Resource budget for executing this plan. */
  resource_budget?: PlanResourceBudget;
  /** Estimated token consumption for planning and execution. */
  estimated_tokens?: number | null;
  /** Governance status: PENDING_APPROVAL, APPROVED, or REJECTED. */
  status?: string;
  /** Identifier of the user who approved this plan. */
  approved_by?: string | null;
  /** ISO timestamp when approval was granted. */
  approved_at?: string | null;
  /** Optional reviewer remarks. */
  approval_notes?: string | null;
  /** Explanation provided if the plan was rejected. */
  rejection_reason?: string | null;
  /** Identifier of the user who rejected this plan. */
  rejected_by?: string | null;
  /** ISO timestamp when rejection occurred. */
  rejected_at?: string | null;
  created_at?: string;
  updated_at?: string;
}

/**
 * Description of an important symbol within an explained code target.
 */
export interface SymbolSummary {
  name: string;
  /** Symbol kind, e.g. 'function', 'class', 'method', 'variable', 'type'. */
  kind?: string;
  /** How this symbol contributes to the code. */
  role?: string;
  start_line?: number | null;
  end_line?: number | null;
}

export interface SyncJobResponse {
  job_id: string;
  status?: string;
}

/**
 * An environment, dependency, or architectural assumption.
 */
export interface TaskAssumption {
  /** Assumption identifier, e.g. 'asm-1'. */
  id: string;
  /** What is assumed about existing code or behavior. */
  description: string;
  /** True if human confirmation is required during plan approval. */
  unresolved?: boolean;
  /** Risk of failure if assumption proves false. */
  risk_level?: "low" | "medium" | "high";
  /** Provenance metadata for this assumption. */
  provenance?: DataProvenance | null;
  /** Parent provenance IDs from which this assumption was derived. */
  provenance_ids?: string[];
}

/**
 * Optional parameters for POST /api/v1/tasks/{task_id}/run-workflow.
 */
export interface TaskAutonomousWorkflowRequest {
  step_payloads?: Record<string, unknown>;
  run_tests?: boolean;
  auto_repair?: boolean;
  publication_authorized?: boolean;
  pr_title?: string | null;
  pr_body?: string | null;
  /** Run workflow asynchronously via durable DBOS workflow and return HTTP 202. */
  async_execution?: boolean;
}

/**
 * Optional parameters for POST /api/v1/tasks/{task_id}/branch.
 */
export interface TaskBranchSetupRequest {
  /** Optional custom feature branch name (protected branches like main/master are strictly blocked). */
  branch_name?: string | null;
}

/**
 * Request payload for POST /api/v1/tasks/{task_id}/checkpoints.
 */
export interface TaskCheckpointCreateRequest {
  /** Execution step or phase name. */
  step_name: string;
  /** Checkpoint state dictionary (secret-scrubbed prior to storage). */
  state_data?: Record<string, unknown>;
  recovery_instructions?: string | null;
}

/**
 * Sanitized checkpoint for worker failure recovery.
 */
export interface TaskCheckpointResponse {
  checkpoint_id: string;
  task_id: string;
  step_name: string;
  state_data: Record<string, unknown>;
  recovery_instructions?: string | null;
  created_at?: string | null;
}

/**
 * Request payload for POST /api/v1/tasks/{task_id}/commit.
 */
export interface TaskCommitTriggerRequest {
  /** Commit message. */
  message?: string | null;
  /** Target feature branch. */
  branch_name?: string | null;
  /** Optional list of specific relative file paths to stage. */
  files?: string[] | null;
  author_name?: string;
  author_email?: string;
}

/**
 * Non-negotiable boundaries, forbidden files, and policy constraints.
 */
export interface TaskConstraint {
  /** Constraint identifier, e.g. 'cst-1'. */
  id: string;
  /** Policy boundary or forbidden action. */
  description: string;
  constraint_type: "protected_file" | "forbidden_dependency" | "backward_compatibility" | "resource_limit" | "security_policy";
  /** Repository-relative file paths that MUST NOT be modified. */
  forbidden_files?: string[];
  /** External package names that MUST NOT be added. */
  forbidden_packages?: string[];
  /** Token budget cap for agent planning and execution. */
  max_budget_tokens?: number | null;
  /** Provenance metadata for this constraint. */
  provenance?: DataProvenance | null;
  /** Parent provenance IDs from which this constraint was derived. */
  provenance_ids?: string[];
}

/**
 * Canonical task response envelope matching Docs/week3.md §7.3.
 */
export interface TaskDetailResponse {
  /** Unique task identifier. */
  task_id: string;
  /** Target repository UUID. */
  repository_id: string;
  title: string;
  description: string;
  status?: TaskStatus;
  source_type?: "GITHUB_ISSUE" | "BUG_FINDING" | "REVIEW_FINDING" | "USER_PROMPT";
  source: TaskSourceReference;
  requirements: TaskRequirement[];
  assumptions?: TaskAssumption[];
  constraints?: TaskConstraint[];
  base_revision?: string | null;
  plan_version?: number;
  approved_plan_version?: number | null;
  repair_attempts_used?: number;
  repair_attempts_max?: number;
  latest_plan?: Record<string, unknown> | null;
  approvals?: (Record<string, unknown>)[];
  created_at?: string;
  updated_at?: string;
}

/**
 * Collection of modified files and line ranges for an agent task, consumed by BlastRadiusEngine.
 */
export interface TaskDiffRanges {
  task_id: string;
  repository_id?: string | null;
  base_branch?: string;
  head_branch?: string;
  files?: FileDiffRange[];
  total_files_changed?: number;
  total_additions?: number;
  total_deletions?: number;
}

/**
 * Request payload for POST /api/v1/tasks/{task_id}/create-pr (and /publish).
 */
export interface TaskDraftPRCreateRequest {
  /** Mandatory explicit human publication authorization flag (ADR-010). */
  publication_authorized?: boolean;
  /** Alias for publication_authorized. */
  human_authorized?: boolean;
  /** Optional custom PR title. */
  title?: string | null;
  /** Optional custom PR body markdown. */
  body?: string | null;
  /** Target base branch (defaults to repository default_branch or 'main'). */
  base_branch?: string | null;
  /** Source feature branch (defaults to agent/task-<id>). */
  head_branch?: string | null;
  current_remote_head_sha?: string | null;
  authorization_notes?: string | null;
  target_repository?: string | null;
}

/**
 * Optional parameters for POST /api/v1/tasks/{task_id}/execute.
 */
export interface TaskExecuteRequest {
  /** If True, provisions workspace in READY state without starting IN_USE. */
  dry_run?: boolean;
  /** If True, immediately executes approved plan steps in the workspace. */
  run_steps?: boolean;
  /** Optional per-step input payloads keyed by step_id. */
  step_payloads?: Record<string, unknown>;
  /** If True, executes workspace test suite after plan steps. */
  run_tests_after?: boolean;
  /** If True, triggers bounded self-repair if post-step tests fail. */
  auto_repair?: boolean;
}

/**
 * Task worker execution attempt status (Day 3).
 */
export interface TaskExecutionResponse {
  execution_id: string;
  task_id: string;
  attempt_number: number;
  worker_id?: string | null;
  status: string;
  started_at?: string | null;
  completed_at?: string | null;
  error_message?: string | null;
  created_at?: string | null;
}

/**
 * Validated task intake payload separating requirements, assumptions, and constraints.
 */
export interface TaskIntakePayload {
  /** Target repository ID. */
  repository_id: string;
  /** Concise task title. */
  title: string;
  /** Detailed problem or requirement statement. */
  description: string;
  /** Originating source metadata. */
  source: TaskSourceReference;
  /** List of functional requirements. At least one requirement is mandatory. */
  requirements: TaskRequirement[];
  /** Explicit technical and environment assumptions. */
  assumptions?: TaskAssumption[];
  /** Non-negotiable security boundaries and forbidden files/dependencies. */
  constraints?: TaskConstraint[];
  /** Git commit SHA or branch ref to branch from. If omitted, uses default branch HEAD. */
  base_revision?: string | null;
  /** Aggregate provenance metadata for the task intake payload. */
  provenance?: DataProvenance | null;
  /** Collection of parent provenance IDs across requirements, assumptions, and source. */
  provenance_ids?: string[];
}

/**
 * Optional parameters for POST /api/v1/tasks/{task_id}/pause.
 */
export interface TaskPauseRequest {
  reason?: string;
}

/**
 * Optional parameters for POST /api/v1/tasks/{task_id}/plan.
 */
export interface TaskPlanGenerateRequest {
  /** Optional updated base revision SHA or branch ref. */
  base_revision?: string | null;
  /** Flag indicating explicit plan regeneration. */
  regenerate?: boolean;
  /** Optional human feedback or instructions for revising the plan. */
  revision_notes?: string | null;
  /** Alias for revision_notes (used by frontend PlanReviewPanel). */
  prompt_instructions?: string | null;
  /** Optional user-edited structured plan to validate and save as a new plan version. */
  custom_plan?: StructuredPlan | null;
}

/**
 * Created GitHub Draft PR details.
 */
export interface TaskPullRequestResponse {
  pr_id: string;
  task_id: string;
  repository_id: string;
  pr_number?: number | null;
  pr_url: string;
  base_branch: string;
  head_branch: string;
  head_sha: string;
  is_draft: boolean;
  title: string;
  body?: string | null;
  created_at?: string | null;
  success?: boolean;
  summary?: string | null;
}

/**
 * Request payload for POST /api/v1/tasks/{task_id}/push.
 */
export interface TaskPushTriggerRequest {
  /** Mandatory explicit human publication authorization flag (ADR-010). */
  publication_authorized?: boolean;
  /** Alias for publication_authorized. */
  human_authorized?: boolean;
  branch_name?: string | null;
  remote_name?: string;
  /** Optional remote base branch HEAD SHA for stale base-revision detection. */
  current_remote_head_sha?: string | null;
  strict_remote?: boolean;
}

/**
 * Optional parameters for POST /api/v1/tasks/{task_id}/recover.
 */
export interface TaskRecoverTriggerRequest {
  /** Optional target status after reconciliation (defaults to APPROVED if plan approved, else PLANNING). */
  target_status?: TaskStatus | null;
  /** Optional recovery action hint ('retry', 'reconcile', 'reset_to_plan', 'resume'). */
  action?: string | null;
  /** Optional recovery reason. */
  reason?: string | null;
}

/**
 * Request payload for POST /api/v1/tasks/{task_id}/repair.
 */
export interface TaskRepairTriggerRequest {
  framework?: string;
  test_path?: string | null;
  /** Optional explicit unified diff to validate and apply. */
  patch_diff?: string | null;
  patch_explanation?: string | null;
  target_files?: string[];
}

/**
 * A concrete functional requirement or defect resolution objective.
 */
export interface TaskRequirement {
  /** Requirement identifier, e.g. 'req-1'. */
  id: string;
  /** What must be built, changed, or fixed. */
  description: string;
  category?: "functional" | "bug_fix" | "refactor" | "security" | "test";
  /** Expected repository-relative file paths for this requirement. */
  target_files?: string[];
  /** Conditions that must pass for this requirement to be satisfied. */
  acceptance_criteria?: string[];
  /** Provenance metadata tracking the origin and taint status of this requirement. */
  provenance?: DataProvenance | null;
  /** Parent provenance IDs from which this requirement was derived. */
  provenance_ids?: string[];
}

/**
 * Canonical task response envelope for database and persistence operations.
 */
export interface TaskResponse {
  task_id: string;
  repository_id: string;
  user_id?: string | null;
  title: string;
  description?: string | null;
  status: string;
  source_type: string;
  source_id?: string | null;
  source_metadata?: Record<string, unknown> | null;
  finding_id?: string | null;
  base_revision: string;
  plan_version: number;
  approved_plan_version?: number | null;
  repair_attempts_used: number;
  repair_attempts_max: number;
  context_summary?: string | null;
  error_message?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

/**
 * Traceability link connecting task to GitHub issues or Week 2 findings.
 */
export interface TaskSourceReference {
  /** Source type: GITHUB_ISSUE, BUG_FINDING, REVIEW_FINDING, or USER_PROMPT. */
  type: "GITHUB_ISSUE" | "BUG_FINDING" | "REVIEW_FINDING" | "USER_PROMPT";
  /** GitHub issue number when type='GITHUB_ISSUE'. */
  issue_number?: number | null;
  /** HTTP URL for the imported GitHub issue. */
  issue_url?: string | null;
  /** Direct URL alias for imported issue or finding. */
  url?: string | null;
  /** Week 2 BugFinding.id or ReviewFinding.id when type is a finding. */
  finding_id?: string | null;
  /** UUID string of the target repository. */
  repository_id?: string | null;
  /** Git commit SHA from which the task branches. */
  base_revision?: string | null;
}

/**
 * Canonical task lifecycle states matching Docs/week3.md §7.1.
 */
export type TaskStatus = "CREATED" | "PLANNING" | "PENDING_APPROVAL" | "APPROVED" | "REJECTED" | "WORKSPACE_SETUP" | "EXECUTING" | "TESTING" | "REPAIRING" | "VERIFYING" | "READY_FOR_PUBLICATION" | "PUBLISHING" | "DRAFT_PR_CREATED" | "FAILED" | "CANCELLED" | "RECOVERY_REQUIRED" | "BLOCKED";

/**
 * Compact summary item for task list views (Docs/week3.md §6 F38 & §7.3).
 */
export interface TaskSummaryResponse {
  task_id: string;
  repository_id: string;
  title: string;
  description?: string;
  status: TaskStatus;
  source_type: "GITHUB_ISSUE" | "BUG_FINDING" | "REVIEW_FINDING" | "USER_PROMPT";
  source: TaskSourceReference;
  requirements?: TaskRequirement[];
  assumptions?: TaskAssumption[];
  constraints?: TaskConstraint[];
  base_revision?: string | null;
  plan_version?: number;
  approved_plan_version?: number | null;
  repair_attempts_used?: number;
  repair_attempts_max?: number;
  created_at: string;
  updated_at: string;
}

/**
 * Request payload for POST /api/v1/tasks/{task_id}/tests.
 */
export interface TaskTestTriggerRequest {
  test_path?: string | null;
  framework?: string | null;
  arguments?: string[];
  timeout_seconds?: number;
}

/**
 * Request payload for POST /api/v1/tasks/{task_id}/tools/{tool_name}.
 */
export interface TaskToolInvokeRequest {
  arguments?: Record<string, unknown>;
}

/**
 * Complete end-to-end audit traceability from finding/issue to draft PR (Days 5-7).
 */
export interface TaskTraceabilityResponse {
  task: TaskResponse;
  finding?: Record<string, unknown> | null;
  latest_plan?: app__schemas__task__TaskPlanResponse | null;
  latest_approval?: app__schemas__task__TaskApprovalResponse | null;
  workspace?: WorkspaceResponse | null;
  latest_execution?: TaskExecutionResponse | null;
  latest_test_run?: TestRunResponse | null;
  repair_attempts_used?: number;
  latest_repair?: RepairAttemptResponse | null;
  latest_verification?: VerificationResultResponse | null;
  pull_request?: TaskPullRequestResponse | null;
  timeline?: app__schemas__task__TaskEventResponse[];
  tool_invocations?: ToolInvocationResponse[];
  test_runs?: TestRunResponse[];
  repair_attempts?: RepairAttemptResponse[];
  traceability_status: string;
  is_complete_workflow?: boolean;
}

/**
 * Optional parameters for POST /api/v1/tasks/{task_id}/verify.
 */
export interface TaskVerifyTriggerRequest {
  /** If True and no test runs exist yet, runs the workspace test suite before verification. */
  run_tests_if_missing?: boolean;
  /** If True, treats passing test execution or clean baseline as mandatory for PASS. */
  require_passing_tests?: boolean;
  /** If True, permits deletion of critical project manifests with a warning instead of blocking. */
  allow_critical_deletions?: boolean;
  /** If True, rejects modifications to files outside the approved plan and requirement target_files. */
  strict_scope?: boolean;
}

/**
 * Request body for `POST /api/v1/repositories/{repository_id}/generate-tests`.
 */
export interface TestGenerationRequest {
  target: AnalysisTarget;
  options?: AnalysisOptions;
  /** Optional explicit test framework override ('pytest', 'unittest', 'jest'). */
  framework?: "pytest" | "unittest" | "jest" | "vitest" | null;
  /** Test generation scope: 'full_repository', 'targeted', or 'change_based'. */
  generation_mode?: "full_repository" | "targeted" | "change_based";
  /** Changed files to evaluate for 'change_based' mode. */
  changed_files?: string[];
  /** Optional filter for specific requirement categories (e.g. security, boundary). */
  focus_categories?: string[];
  /** Specific commit SHA to pin analysis context. */
  commit_sha?: string | null;
  /** Whether to execute generated tests in isolated sandbox runner. */
  run_isolated_execution?: boolean;
}

/**
 * Envelope returned by `POST /api/v1/repositories/{repository_id}/generate-tests`.
 */
export interface TestGenerationResponse {
  run_id: string;
  repository_id: string;
  status?: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
  target: AnalysisTarget;
  revision?: string | null;
  result: TestGenerationResult;
  created_at?: string;
  stage_metrics?: Record<string, unknown> | null;
}

/**
 * Structured test generation output (Docs/week2.md §8).
 */
export interface TestGenerationResult {
  /** Detected or selected test runner ('pytest', 'unittest', 'jest'). */
  detected_framework: "pytest" | "unittest" | "jest" | "vitest";
  /** Safe repository-relative path for the proposed test file. */
  proposed_test_path: string;
  /** Complete generated test file source code. */
  test_content: string;
  /** Normal, edge-case, and failure-path scenarios covered. */
  covered_scenarios?: TestScenario[];
  /** Assumptions, missing fixtures, or existing-file overwrite warnings. */
  assumptions_and_warnings?: string[];
  /** Whether static syntax/structural validation succeeded. */
  syntax_valid?: boolean;
  /** Normalized syntax or structural validation errors, if any. */
  validation_errors?: string[];
  /** Truthful validation status: e.g. 'generated and statically validated', 'not executed', or 'verified passing' if sandboxed. */
  validation_stage?: string;
  /** Whether the generated output strictly conforms to the expected schema. */
  schema_valid?: boolean;
  /** Whether the generated test source parses cleanly without syntax errors. */
  code_syntactically_valid?: boolean;
  /** Whether test runner conventions and imports match the detected repository framework. */
  framework_recognized?: boolean;
  /** Whether sandboxed test execution was attempted. */
  execution_attempted?: boolean;
  /** Outcome of execution: 'NOT_EXECUTED', 'PASSED', 'FAILED', or 'TIMED_OUT'. */
  execution_status?: string;
  /** Source references used to construct the test suite. */
  sources?: AnalysisSourceReference[];
  /** Discovered test requirements and coverage traceability (task.md §2, §6). */
  requirements?: TestRequirement[];
  /** Quality scorecard evaluating requirement, assertion, and execution coverage (task.md §8). */
  quality_report?: TestQualityReport | null;
  /** All generated test file paths. */
  generated_test_files?: string[];
  /** Requirements remaining uncovered after generation. */
  missing_requirements?: string[];
  /** Requirements unsupported by current framework or runtime. */
  unsupported_requirements?: string[];
  /** Detailed execution statistics from restricted test runner. */
  execution_summary?: Record<string, unknown>;
  /** Execution-verified status: 'VERIFIED', 'UNVERIFIED', 'REJECTED', or 'EXECUTION_ERROR'. */
  verification_status?: "VERIFIED" | "UNVERIFIED" | "REJECTED" | "EXECUTION_ERROR";
  /** Specific reasons explaining the verification classification. */
  verification_reasons?: string[];
  /** Three-consecutive-run stability and flakiness report (task.md §4.6). */
  stability_report?: StabilityReport | null;
  /** Runtime coverage delta report comparing baseline to post-generation (task.md §5). */
  coverage_report?: CoverageReport | null;
  /** Report on coverage-guided iterative test generation rounds (task.md §6). */
  iteration_report?: IterationReport | null;
  /** Sanitized and redacted terminal output from sandboxed test execution. */
  raw_execution_output?: string | null;
}

/**
 * Quality scorecard for generated and existing repository tests (task.md §8).
 */
export interface TestQualityReport {
  requirement_coverage_percent?: number | null;
  line_coverage_percent?: number | null;
  branch_coverage_percent?: number | null;
  mutation_score_percent?: number | null;
  duplicate_test_count?: number;
  flaky_test_count?: number;
  weak_assertion_count?: number;
  untested_critical_requirements?: string[];
  quality_score?: number | null;
  summary_notes?: string[];
}

/**
 * Repository-wide discovered test requirement (task.md §2, §3).
 */
export interface TestRequirement {
  /** Unique requirement ID, e.g. REQ-AUTH-001 */
  requirement_id: string;
  title: string;
  category?: "functional" | "boundary" | "negative" | "exception_handling" | "integration" | "api_contract" | "security" | "state_lifecycle" | "concurrency" | "regression" | "performance" | "configuration" | "frontend" | "end_to_end" | string;
  priority?: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | string;
  source_files?: string[];
  source_symbols?: string[];
  /** Expected normal or failure behavior */
  expected_behavior: string;
  /** Evidence supporting discovery or coverage */
  evidence?: string[];
  /** Requirement coverage status (COVERED, PARTIAL, MISSING, BLOCKED, NOT_APPLICABLE) */
  status?: "COVERED" | "PARTIAL" | "MISSING" | "BLOCKED" | "NOT_APPLICABLE" | string;
  /** Relevant source line number if applicable */
  target_line?: number | null;
  /** Explanation for status or exclusion */
  reason?: string | null;
}

export interface TestRunResponse {
  test_run_id: string;
  task_id: string;
  command: string;
  status: string;
  exit_code?: number | null;
  duration_ms?: number | null;
  tests_total?: number;
  tests_passed?: number;
  tests_failed?: number;
  sanitized_output?: string | null;
  target_revision?: string | null;
  created_at?: string | null;
}

/**
 * Summary of a single test scenario included in the generated test file.
 */
export interface TestScenario {
  name: string;
  category?: "normal" | "edge_case" | "failure_path";
  description: string;
}

export interface TokenResponse {
  access_token: string;
  token_type?: string;
  expires_in: number;
  user: AuthenticatedUser;
}

/**
 * Decision payload to approve or reject a pending tool approval.
 */
export interface ToolApprovalDecisionRequest {
  feedback?: string | null;
  reason?: string | null;
}

/**
 * Request to authorize execution of a high-risk tool.
 */
export interface ToolApprovalRequest {
  tool_name: string;
  arguments?: Record<string, unknown>;
  risk_tier?: string | null;
  expires_in_seconds?: number | null;
}

/**
 * Audit log of operations routed through ToolRouter (Day 3 & F21).
 */
export interface ToolInvocationResponse {
  invocation_id: string;
  task_id: string;
  tool_name: string;
  sanitized_arguments?: Record<string, unknown> | null;
  status: string;
  duration_ms?: number | null;
  output_summary?: string | null;
  tool_version?: string | null;
  tool_source?: string | null;
  provider_id?: string | null;
  risk_tier?: string | null;
  schema_fingerprint?: string | null;
  execution_timeout_s?: number | null;
  execution_timed_out?: boolean;
  rate_limit_status?: string | null;
  error_category?: string | null;
  created_at?: string | null;
}

/**
 * A single entry in a repository's file tree.
 */
export interface TreeEntry {
  path: string;
  /** 'blob' (file) or 'tree' (directory) */
  type: string;
  size?: number | null;
  sha?: string | null;
}

/**
 * Trust tier classifications assigned by trusted backend platform code.
 */
export type TrustLevel = "SYSTEM" | "PLATFORM" | "USER_APPROVED" | "USER_PROVIDED" | "EXTERNAL_UNTRUSTED" | "MODEL_GENERATED";

export interface UpdateRepositoryAutomationSettingsRequest {
  auto_sync_enabled?: boolean | null;
  pr_review_enabled?: boolean | null;
  pr_review_drafts?: boolean | null;
}

/**
 * Update repository-level review configuration.
 */
export interface UpdateReviewSettingsRequest {
  pr_review_enabled?: boolean | null;
  pr_review_drafts?: boolean | null;
  min_confidence?: "high" | "medium" | "low" | null;
  max_comments?: number | null;
  changed_lines_only?: boolean | null;
}

export interface ValidationError {
  loc: (string | number)[];
  msg: string;
  type: string;
  input?: unknown;
  ctx?: Record<string, unknown>;
}

/**
 * Independent verification check outcome.
 */
export interface VerificationResultResponse {
  verification_id: string;
  task_id: string;
  verified_revision: string;
  status: string;
  checks?: (Record<string, unknown>)[] | null;
  blocking_findings?: (Record<string, unknown>)[] | null;
  warnings?: (Record<string, unknown>)[] | null;
  summary?: string | null;
  created_at?: string | null;
}

/**
 * Isolated task execution environment details (Day 3).
 */
export interface WorkspaceResponse {
  workspace_id: string;
  task_id: string;
  workspace_path: string;
  task_branch: string;
  base_revision: string;
  current_revision?: string | null;
  status: string;
  cleanup_at?: string | null;
  created_at?: string | null;
}

/**
 * A citation pointing to a specific location in the repository.
 * 
 * Used inside RepositoryAnswer.sources so the user can trace every
 * claim back to the exact file and lines it came from.
 */
export interface ai__schemas__output__SourceReference {
  /** Repository-relative file path, e.g. 'src/auth/service.ts' */
  file: string;
  /** First line of the cited range (1-indexed). */
  start_line: number;
  /** Last line of the cited range (inclusive). */
  end_line: number;
  /** Name of the symbol (class/function) at this location, if known. */
  symbol?: string | null;
}

/**
 * Uniquely identifies a piece of source code within a repository.
 * 
 * This is the shared contract described in Section 4.2 of the Week 2 plan.
 * All line ranges are **inclusive** (start_line and end_line are both included).
 */
export interface app__integrations__github__schemas__SourceReference {
  repository_id: string;
  file_path: string;
  /** First included line (1-indexed, inclusive). */
  start_line?: number | null;
  /** Last included line (1-indexed, inclusive). */
  end_line?: number | null;
  /** Git SHA or branch name at the time of retrieval. */
  revision?: string | null;
  /** Exact Git commit SHA for immutable revision identification. */
  commit_sha?: string | null;
  /** Optional symbol (function/class) name for targeted retrieval. */
  symbol_name?: string | null;
}

/**
 * Immutable audit record of a plan approval or rejection decision.
 */
export interface app__schemas__plan__TaskApprovalResponse {
  id?: string;
  approval_id: string;
  task_id: string;
  plan_id: string;
  plan_version: number;
  approver_id: string;
  user_id?: string | null;
  decision: "APPROVED" | "REJECTED";
  comment?: string | null;
  notes?: string | null;
  reason?: string | null;
  title?: string | null;
  description?: string | null;
  repository_id?: string | null;
  base_revision?: string | null;
  plan_hash: string;
  task_status: TaskStatus;
  status?: TaskStatus | null;
  approved_plan_version?: number | null;
  created_at?: string;
}

/**
 * Ordered timeline & audit event record (Docs/week3.md §6 F38 & F39).
 */
export interface app__schemas__plan__TaskEventResponse {
  id?: string;
  event_id: string;
  task_id: string;
  event_type: string;
  actor_id?: string | null;
  user_id?: string | null;
  from_status?: string | null;
  to_status?: string | null;
  summary: string;
  description?: string;
  payload?: Record<string, unknown>;
  details?: Record<string, unknown>;
  created_at: string;
}

/**
 * Persisted structured implementation plan response (Docs/week3.md §6 F32).
 */
export interface app__schemas__plan__TaskPlanResponse {
  plan_id: string;
  task_id: string;
  plan_version: number;
  base_revision?: string | null;
  plan_hash: string;
  summary: string;
  problem_statement: string;
  assumptions?: TaskAssumption[];
  relevant_files?: string[];
  relevant_symbols?: string[];
  /** Agentless 3-stage localized candidate files, symbols, and line ranges (Issue 3). */
  localization_targets?: LocalizationTarget[];
  steps: PlanStep[];
  expected_files?: string[];
  expected_files_to_modify?: string[];
  tests_to_run?: string[];
  tests_to_add?: string[];
  validation_strategy?: string[];
  risks?: PlanRisk[];
  required_permissions?: string[];
  resource_budget?: PlanResourceBudget;
  status?: string;
  approved_plan_version?: number | null;
  is_approved?: boolean;
  created_at?: string;
  updated_at?: string;
}

/**
 * Immutable task approval outcome for plans, tools, and MCP elicitations.
 */
export interface app__schemas__task__TaskApprovalResponse {
  approval_id: string;
  id?: string | null;
  task_id: string;
  plan_version?: number | null;
  user_id?: string | null;
  decision: string;
  feedback?: string | null;
  created_at?: string | null;
  approval_type?: string;
  tool_name?: string | null;
  argument_hash?: string | null;
  sanitized_arguments?: Record<string, unknown> | null;
  risk_level?: string | null;
  status?: string | null;
  expires_at?: string | null;
  consumed_at?: string | null;
  session_id?: string | null;
  elicitation_type?: string | null;
  elicitation_payload?: Record<string, unknown> | null;
  elicitation_response?: Record<string, unknown> | null;
}

/**
 * Ordered event item for dashboard timeline.
 */
export interface app__schemas__task__TaskEventResponse {
  event_id: string;
  task_id: string;
  event_type: string;
  event_data?: Record<string, unknown> | null;
  user_id?: string | null;
  created_at?: string | null;
}

/**
 * Structured implementation plan response.
 */
export interface app__schemas__task__TaskPlanResponse {
  plan_id: string;
  task_id: string;
  version: number;
  base_revision: string;
  summary: string;
  problem_statement?: string | null;
  steps: (Record<string, unknown>)[];
  expected_files?: string[] | null;
  tests_to_run?: string[] | null;
  validation_strategy?: string | null;
  risks?: unknown[] | null;
  status: string;
  created_at?: string | null;
}
