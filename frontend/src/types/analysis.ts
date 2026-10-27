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

export interface ExplainCodeRequest {
  target: AnalysisTarget;
  options?: AnalysisOptions;
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
}

/** Backward-compatible alias for AnalysisFinding */
export type AnalysisFinding = BugFinding;

export interface BugDetectionRequest {
  target: AnalysisTarget;
  options?: AnalysisOptions;
  include_static?: boolean;
  include_ai?: boolean;
  min_severity?: FindingSeverity;
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
  created_at: string;
}

export type SupportedTestFramework = 'pytest' | 'unittest' | 'jest';

export type TestScenarioCategory = 'normal' | 'edge_case' | 'failure_path';

export interface TestScenario {
  name: string;
  category: TestScenarioCategory;
  description: string;
}

export interface TestGenerationRequest {
  target: AnalysisTarget;
  options?: AnalysisOptions;
  framework?: SupportedTestFramework | null;
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
  total: int | number;
  items: AnalysisRunSummary[];
}

type int = number;

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
