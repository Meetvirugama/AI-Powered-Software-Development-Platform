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


export interface TestGenerationResult {
  framework: string;
  test_file_path: string;
  code: string;
  scenarios_covered?: string[];
  assumptions?: string[];
  validation_warnings?: string[];
}

export interface CodeReviewResult {
  summary: string;
  findings: BugFinding[];
  overall_status?: 'APPROVED' | 'CHANGES_REQUESTED' | 'COMMENT';
}

export type AnalysisResult =
  | { type: 'explain'; data: CodeExplanation }
  | { type: 'bugs'; data: BugDetectionResponse }
  | { type: 'tests'; data: TestGenerationResult }
  | { type: 'review'; data: CodeReviewResult };

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
  findings?: AnalysisFinding[];
  error_message?: string | null;
  created_at: string;
  completed_at?: string | null;
}

