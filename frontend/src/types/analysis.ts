/**
 * Analysis UI types for Week 2 — Developer Intelligence Suite.
 *
 * Aligned with shared contracts in Docs/week2.md Section 4:
 *   - 4.1 Shared analysis request & target
 *   - 4.2 Shared source reference
 *   - 4.3 Shared analysis lifecycle
 *   - 4.4 Shared finding structure
 */

export type AnalysisFeatureType = 'explain' | 'bugs' | 'tests' | 'review';

export type AnalysisRunFeatureType =
  | AnalysisFeatureType
  | 'detect_bugs'
  | 'generate_tests';

export type AnalysisTargetType = 'file' | 'symbol' | 'range';

export interface AnalysisTarget {
  type: AnalysisTargetType;
  path: string;
  start_line?: number;
  end_line?: number;
  symbol?: string | null;
  revision?: string | null;
}

export interface AnalysisOptions {
  include_context?: boolean;
  max_context_tokens?: number;
  persist_run?: boolean;
}

export interface ExplainContextOptions {
  include_graph_context?: boolean;
  include_callers?: boolean;
  include_dependencies?: boolean;
  include_tests?: boolean;
  include_semantic_search?: boolean;
  selected_files?: string[];
}

export interface ExplainCodeRequest {
  target: AnalysisTarget;
  options?: AnalysisOptions;
  context?: ExplainContextOptions;
  explanation_level?: string;
}

export interface DiscoveredRelatedFile {
  path: string;
  relation:
    | 'imported_dependency'
    | 'called_dependency'
    | 'caller'
    | 'type_definition'
    | 'database_model'
    | 'associated_test'
    | 'indirect_dependency'
    | 'semantic_match';
  relation_label: string;
  weight: number;
  reason: string;
  symbols: string[];
  is_preselected: boolean;
}

export interface RelatedFilesDiscoveryResponse {
  target_path: string;
  target_symbol?: string | null;
  related_files: DiscoveredRelatedFile[];
  total_discovered: number;
}

export type AnalysisStatus =
  | 'IDLE'
  | 'PENDING'
  | 'RUNNING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED';

export type FindingSeverity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO';

export type FindingSourceType = 'STATIC' | 'AI' | 'COMBINED';

export interface StageMetrics {
  stages_ms: Record<string, number>;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  context_budget_tokens: number;
  context_utilized_tokens: number;
  provider?: string | null;
  model?: string | null;
  estimated_cost_usd: number;
  total_latency_ms: number;
}

export type ConfidenceLevel = 'high' | 'medium' | 'low';

export type BugCategory =
  | 'off_by_one'
  | 'null_safety'
  | 'unhandled_exception'
  | 'boundary_condition'
  | 'resource_leak'
  | 'race_condition'
  | 'logic_error'
  | 'security'
  | 'other'
  | (string & {});

export interface SourceReference {
  repository_id?: string | null;
  file_path: string;
  start_line?: number | null;
  end_line?: number | null;
  revision?: string | null;
  symbol_name?: string | null;
  symbol?: string | null;
}

export interface SymbolSummary {
  name: string;
  kind: string;
  role: string;
  start_line?: number | null;
  end_line?: number | null;
}

export interface BugFinding {
  id: string;
  category: BugCategory | string;
  severity: FindingSeverity;
  title: string;
  description: string;
  source_reference: SourceReference;
  evidence: string;
  suggested_fix?: string | null;
  confidence?: ConfidenceLevel | string;
  is_uncertain?: boolean;
  source_type: FindingSourceType;
  rule_id?: string | null;
  priority_score?: number | null;
  evidence_level?: "PROVEN" | "STRONG" | "SUSPECTED" | "NEEDS_CONTEXT" | string;
  dependency_trace?: string[];
  counterevidence?: string[];
  reproduction_status?: "NOT_TESTED" | "REPRODUCED" | "REPRODUCTION_FAILED" | string;
}

/** Backward-compatible alias for AnalysisFinding */
export type AnalysisFinding = BugFinding;

export interface BugDetectionRequest {
  target: AnalysisTarget;
  options?: AnalysisOptions;
  include_static?: boolean;
  include_ai?: boolean;
  min_severity?: FindingSeverity;
  scan_mode?: "quick" | "standard" | "deep" | "change" | string;
  changed_files?: string[];
}

export interface BugDetectionResponse {
  run_id: string;
  repository_id: string;
  status: AnalysisStatus;
  target: AnalysisTarget;
  revision?: string | null;
  findings: BugFinding[];
  total_findings: number;
  static_findings_count: number;
  ai_findings_count: number;
  missing_context: string[];
  error_message?: string | null;
  stage_metrics?: StageMetrics | null;
  created_at: string;
  completed_at?: string | null;
}

/** Backward-compatible alias for BugDetectionResult */
export type BugDetectionResult = BugDetectionResponse;

export interface CodeExplanation {
  purpose: string;
  logic_flow: string[];
  key_symbols: SymbolSummary[];
  inputs_and_outputs: string;
  dependencies: string[];
  assumptions_and_limitations: string[];
  sources: SourceReference[];
  confidence: ConfidenceLevel;
  missing_context: string[];
  execution_flow?: string[];
  related_files?: string[];
  detailed_explanation?: string;
  code_output_explanation?: string;
  code_issues_and_solutions?: string[];
  corrected_code?: string;
}

/** Backward-compatible alias for CodeExplanation */
export type CodeExplanationResult = CodeExplanation;

export interface CodeExplanationResponse {
  run_id: string;
  repository_id: string;
  status: AnalysisStatus;
  target: AnalysisTarget;
  revision?: string | null;
  explanation: CodeExplanation;
  stage_metrics?: StageMetrics | null;
  created_at: string;
}

export type SupportedTestFramework = 'pytest' | 'unittest' | 'jest';

export type TestScenarioCategory = 'normal' | 'edge_case' | 'failure_path';

export type TestRequirementCategory =
  | 'functional'
  | 'boundary'
  | 'negative'
  | 'exception_handling'
  | 'integration'
  | 'api_contract'
  | 'security'
  | 'state_lifecycle'
  | 'concurrency'
  | 'regression'
  | 'performance'
  | 'configuration'
  | 'frontend'
  | 'end_to_end';

export type TestRequirementStatus = 'COVERED' | 'PARTIAL' | 'MISSING' | 'BLOCKED' | 'NOT_APPLICABLE';

export type TestRequirementPriority = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';

export interface TestRequirement {
  requirement_id: string;
  title: string;
  category: TestRequirementCategory | string;
  priority: TestRequirementPriority | string;
  source_files: string[];
  source_symbols: string[];
  expected_behavior: string;
  evidence: string[];
  status: TestRequirementStatus | string;
  target_line?: number | null;
  reason?: string | null;
}

export interface TestQualityReport {
  requirement_coverage_percent?: number | null;
  line_coverage_percent?: number | null;
  branch_coverage_percent?: number | null;
  mutation_score_percent?: number | null;
  duplicate_test_count: number;
  flaky_test_count: number;
  weak_assertion_count: number;
  untested_critical_requirements: string[];
  quality_score?: number | null;
  summary_notes: string[];
}

export interface TestScenario {
  name: string;
  category: TestScenarioCategory;
  description: string;
}

export interface TestGenerationRequest {
  target: AnalysisTarget;
  options?: AnalysisOptions;
  framework?: SupportedTestFramework | null;
  generation_mode?: 'full_repository' | 'targeted' | 'change_based';
  changed_files?: string[];
  focus_categories?: string[];
  commit_sha?: string | null;
  run_isolated_execution?: boolean;
}

export interface TestGenerationResult {
  detected_framework: SupportedTestFramework;
  framework?: SupportedTestFramework | string;
  proposed_test_path: string;
  test_file_path?: string;
  test_content: string;
  code?: string;
  covered_scenarios: TestScenario[];
  scenarios_covered?: string[];
  assumptions_and_warnings: string[];
  assumptions?: string[];
  syntax_valid: boolean;
  validation_errors: string[];
  validation_warnings?: string[];
  sources?: SourceReference[];
  requirements?: TestRequirement[];
  quality_report?: TestQualityReport | null;
  generated_test_files?: string[];
  missing_requirements?: string[];
  unsupported_requirements?: string[];
  execution_summary?: Record<string, any>;
  execution_status?: string;
  execution_attempted?: boolean;
}

export interface TestGenerationResponse {
  run_id: string;
  repository_id: string;
  status: AnalysisStatus;
  target: AnalysisTarget;
  revision?: string | null;
  result: TestGenerationResult;
  test_output?: string | null;
  error_message?: string | null;
  stage_metrics?: StageMetrics | null;
  created_at: string;
  completed_at?: string | null;
}

export type ReviewTargetType = 'file' | 'commit' | 'diff' | 'pr';

export type ReviewCategory =
  | 'correctness'
  | 'security'
  | 'performance'
  | 'reliability'
  | 'maintainability';

export type ReviewRiskLevel = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'NONE';

export interface ReviewTarget {
  type: ReviewTargetType;
  path?: string | null;
  commit_sha?: string | null;
  pr_number?: number | null;
  diff?: string | null;
  base_revision?: string | null;
  head_revision?: string | null;
}

export interface CodeReviewRequest {
  target: ReviewTarget;
  options?: AnalysisOptions;
  include_static?: boolean;
}

export interface ReviewFinding {
  id: string;
  category: ReviewCategory;
  severity: FindingSeverity;
  title: string;
  description: string;
  source_reference: SourceReference;
  evidence: string;
  suggested_fix?: string | null;
  confidence?: ConfidenceLevel;
  is_uncertain?: boolean;
  is_new_in_change?: boolean;
  source_type: FindingSourceType;
  rule_id?: string | null;
}

export interface ReviewReport {
  summary: string;
  risk_level: ReviewRiskLevel;
  findings: ReviewFinding[];
  total_findings: number;
  category_counts: Record<string, number>;
  missing_context: string[];
}

export interface ReviewReportResponse {
  run_id: string;
  repository_id: string;
  status: AnalysisStatus;
  target: ReviewTarget;
  report: ReviewReport;
  stage_metrics?: StageMetrics | null;
  created_at: string;
  completed_at?: string | null;
}

/** Backward-compatible alias for legacy CodeReviewResult */
export interface CodeReviewResult {
  summary: string;
  findings: (BugFinding | ReviewFinding)[];
  risk_level?: ReviewRiskLevel;
  total_findings?: number;
  category_counts?: Record<string, number>;
  missing_context?: string[];
  overall_status?: 'APPROVED' | 'CHANGES_REQUESTED' | 'COMMENT';
}

export type AnalysisResult =
  | { type: 'explain'; data: CodeExplanation }
  | { type: 'bugs'; data: BugDetectionResponse }
  | { type: 'tests'; data: TestGenerationResponse }
  | { type: 'review'; data: ReviewReportResponse };

export interface AnalysisRunSummary {
  id: string;
  repository_id: string;
  user_id?: string | null;
  feature_type: AnalysisRunFeatureType;
  status: AnalysisStatus;
  target_path?: string | null;
  target_symbol?: string | null;
  start_line?: number | null;
  end_line?: number | null;
  source_revision?: string | null;
  findings_count: number;
  error_message?: string | null;
  created_at: string;
  completed_at?: string | null;
}

export interface PaginatedAnalysisRunResponse {
  page: number;
  page_size: number;
  total: number;
  items: AnalysisRunSummary[];
}

export interface AnalysisRunDetailResponse {
  id: string;
  repository_id: string;
  user_id?: string | null;
  feature_type: AnalysisRunFeatureType;
  status: AnalysisStatus;
  target_path?: string | null;
  target_symbol?: string | null;
  start_line?: number | null;
  end_line?: number | null;
  source_revision?: string | null;
  findings_count: number;
  result_payload?: Record<string, any> | null;
  test_output?: string | null;
  findings?: (AnalysisFinding | ReviewFinding)[];
  error_message?: string | null;
  created_at: string;
  completed_at?: string | null;
}

export interface AnalysisRunMetricsSummaryResponse {
  repository_id: string;
  total_runs: number;
  by_feature: Record<string, number>;
  by_status: Record<string, number>;
  total_findings: number;
  integrity_status: string;
  integrity_issues_count: number;
  retention?: Record<string, any>;
  completed_runs?: number;
  failed_runs?: number;
  running_runs?: number;
  feature_counts?: Record<string, number>;
  severity_counts?: Record<string, number>;
  latest_run_at?: string | null;
}
