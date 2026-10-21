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

export type AnalysisTargetType = 'file' | 'symbol' | 'range';

export interface AnalysisTarget {
  type: AnalysisTargetType;
  path: string;
  start_line?: number;
  end_line?: number;
  symbol?: string | null;
}

export type AnalysisStatus =
  | 'IDLE'
  | 'PENDING'
  | 'RUNNING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED';

export type FindingSeverity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';

export type FindingSourceType = 'STATIC' | 'AI' | 'COMBINED';

export interface SourceReference {
  repository_id?: string;
  file_path: string;
  start_line: number;
  end_line: number;
  revision?: string;
  symbol_name?: string | null;
}

export interface AnalysisFinding {
  id: string;
  category: string;
  severity: FindingSeverity;
  title: string;
  description: string;
  source_reference: SourceReference;
  evidence?: string;
  suggested_fix?: string;
  confidence?: string;
  source_type: FindingSourceType;
}

export interface CodeExplanationResult {
  purpose: string;
  logic_flow?: string[];
  key_symbols?: string[];
  inputs_outputs?: string;
  dependencies?: string[];
  limitations?: string;
  sources?: SourceReference[];
}

export interface BugDetectionResult {
  findings: AnalysisFinding[];
  summary?: string;
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
  findings: AnalysisFinding[];
  overall_status?: 'APPROVED' | 'CHANGES_REQUESTED' | 'COMMENT';
}

export type AnalysisResult =
  | { type: 'explain'; data: CodeExplanationResult }
  | { type: 'bugs'; data: BugDetectionResult }
  | { type: 'tests'; data: TestGenerationResult }
  | { type: 'review'; data: CodeReviewResult };
