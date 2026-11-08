/**
 * Developer Intelligence Analysis Services.
 *
 * Calls Week 2 API endpoints registered in backend/app/api/v1/analysis.py:
 *   - POST /api/v1/repositories/{repository_id}/explain
 *   - POST /api/v1/repositories/{repository_id}/detect-bugs
 *   - POST /api/v1/repositories/{repository_id}/generate-tests
 *   - POST /api/v1/repositories/{repository_id}/review
 *   - GET  /api/v1/repositories/{repository_id}/analysis-runs
 *   - GET  /api/v1/analysis-runs/{run_id}
 */

import { apiClient } from './api';
import type {
  ExplainCodeRequest,
  CodeExplanationResponse,
  RelatedFilesDiscoveryResponse,
  BugDetectionRequest,
  BugDetectionResponse,
  TestGenerationRequest,
  TestGenerationResponse,
  CodeReviewRequest,
  ReviewReportResponse,
  PaginatedAnalysisRunResponse,
  AnalysisRunDetailResponse,
  AnalysisRunFeatureType,
  AnalysisRunMetricsSummaryResponse,
} from '../types/analysis';

/**
 * Request an AI-powered explanation for a file, symbol, or line range.
 *
 * @param repositoryId The UUID of the authorized repository.
 * @param payload The validated target and execution options.
 * @returns The structured explanation response envelope.
 */
export interface AnalysisRequestOptions {
  signal?: AbortSignal;
  timeout?: number;
}

export async function explainCode(
  repositoryId: string,
  payload: ExplainCodeRequest,
  options?: AnalysisRequestOptions
): Promise<CodeExplanationResponse> {
  const response = await apiClient.post<CodeExplanationResponse>(
    `/repositories/${repositoryId}/explain`,
    payload,
    { signal: options?.signal, timeout: options?.timeout }
  );
  return response.data;
}

/**
 * Discover related files and graph neighbors for a code explanation target (RIE).
 */
export async function getRelatedFiles(
  repositoryId: string,
  path: string,
  symbol?: string
): Promise<RelatedFilesDiscoveryResponse> {
  const params = new URLSearchParams({ path });
  if (symbol) params.set('symbol', symbol);
  const response = await apiClient.get<RelatedFilesDiscoveryResponse>(
    `/repositories/${repositoryId}/explain/related-files?${params.toString()}`
  );
  return response.data;
}

/**
 * Scan for bugs using static analysis rules and AI reasoning (Week 2 — Day 3).
 *
 * Calls POST /api/v1/repositories/{repository_id}/detect-bugs
 *
 * @param repositoryId The UUID of the authorized repository.
 * @param payload Target, options, and engine flags.
 * @param options Request options including optional cancellation signal and timeout.
 * @returns The structured bug detection response envelope.
 */
export async function detectBugs(
  repositoryId: string,
  payload: BugDetectionRequest,
  options?: AnalysisRequestOptions
): Promise<BugDetectionResponse> {
  const response = await apiClient.post<BugDetectionResponse>(
    `/repositories/${repositoryId}/detect-bugs`,
    payload,
    { signal: options?.signal, timeout: options?.timeout }
  );
  return response.data;
}

/**
 * Generate a framework-aware test file following repository conventions (Week 2 — Day 4).
 *
 * Calls POST /api/v1/repositories/{repository_id}/generate-tests
 *
 * @param repositoryId The UUID of the authorized repository.
 * @param payload Target, options, and optional framework override.
 * @param options Request options including optional cancellation signal and timeout.
 * @returns The structured test generation response envelope.
 */
export async function generateTests(
  repositoryId: string,
  payload: TestGenerationRequest,
  options?: AnalysisRequestOptions
): Promise<TestGenerationResponse> {
  const response = await apiClient.post<TestGenerationResponse>(
    `/repositories/${repositoryId}/generate-tests`,
    payload,
    { signal: options?.signal, timeout: options?.timeout }
  );
  return response.data;
}

/**
 * Run a standalone AI and static code review on a file, commit, PR, or diff (Week 2 — Day 5).
 *
 * Calls POST /api/v1/repositories/{repository_id}/review
 *
 * @param repositoryId The UUID of the authorized repository.
 * @param payload Review target (file, commit, pr, or diff) and options.
 * @param options Request options including optional cancellation signal and timeout.
 * @returns The structured review report response envelope.
 */
export async function reviewCode(
  repositoryId: string,
  payload: CodeReviewRequest,
  options?: AnalysisRequestOptions
): Promise<ReviewReportResponse> {
  const response = await apiClient.post<ReviewReportResponse>(
    `/repositories/${repositoryId}/review`,
    payload,
    { signal: options?.signal, timeout: options?.timeout }
  );
  return response.data;
}

/**
 * List historical analysis runs (e.g. explanation runs, bug scans, test generation, code reviews)
 * for an authorized repository.
 *
 * @param repositoryId The UUID of the authorized repository.
 * @param params Query filtering and pagination options.
 * @returns Paginated list of analysis run summaries.
 */
export async function getAnalysisRuns(
  repositoryId: string,
  params?: {
    feature_type?: AnalysisRunFeatureType;
    status?: string;
    target_path?: string;
    source_revision?: string;
    user_id?: string;
    page?: number;
    page_size?: number;
  }
): Promise<PaginatedAnalysisRunResponse> {
  const response = await apiClient.get<PaginatedAnalysisRunResponse>(
    `/repositories/${repositoryId}/analysis-runs`,
    { params }
  );
  return response.data;
}

/**
 * Reopen a specific analysis run from persistent history.
 */
export async function getAnalysisRun(
  runId: string
): Promise<AnalysisRunDetailResponse> {
  const response = await apiClient.get<AnalysisRunDetailResponse>(
    `/analysis-runs/${runId}`
  );
  return response.data;
}

/**
 * List historical standalone code review runs for an authorized repository (Scenario D Step 7).
 *
 * @param repositoryId The UUID of the authorized repository.
 * @param params Query filtering and pagination options.
 * @returns Paginated list of analysis run summaries.
 */
export async function getCodeReviewHistory(
  repositoryId: string,
  params?: {
    status?: string;
    target_path?: string;
    source_revision?: string;
    user_id?: string;
    page?: number;
    page_size?: number;
  }
): Promise<PaginatedAnalysisRunResponse> {
  return getAnalysisRuns(repositoryId, {
    ...params,
    feature_type: 'review',
  });
}

/**
 * Reopen a specific standalone code review run from persistent history (Scenario D Step 7).
 *
 * @param runId The UUID of the code review analysis run.
 * @returns Detailed record with findings and structured result payload.
 */
export async function reopenCodeReview(
  runId: string
): Promise<AnalysisRunDetailResponse> {
  return getAnalysisRun(runId);
}


/**
 * Retrieve aggregate run and finding metrics across all 4 Developer Intelligence features
 * for an authorized repository (Week 2 — Day 6/7).
 *
 * Calls GET /api/v1/repositories/{repository_id}/analysis-runs/summary
 */
export async function getAnalysisRunsSummary(
  repositoryId: string
): Promise<AnalysisRunMetricsSummaryResponse> {
  const response = await apiClient.get<AnalysisRunMetricsSummaryResponse>(
    `/repositories/${repositoryId}/analysis-runs/summary`
  );
  return response.data;
}

/**
 * Submit developer feedback for a review finding (useful, not_useful, false_positive, etc.).
 *
 * Calls POST /api/v1/analysis-runs/{run_id}/findings/{finding_id}/feedback
 */
export async function submitFindingFeedback(
  runId: string,
  findingId: string,
  payload: { feedback_type: string; comment?: string }
): Promise<{
  finding_id: string;
  feedback_type: string;
  comment?: string | null;
  repository_stats: {
    useful_count: number;
    not_useful_count: number;
    false_positive_count: number;
    acceptance_rate: number;
    false_positive_rate: number;
  };
}> {
  const response = await apiClient.post(
    `/analysis-runs/${runId}/findings/${findingId}/feedback`,
    payload
  );
  return response.data;
}

/**
 * Trigger manual publication of qualified code review findings to GitHub PR.
 *
 * Calls POST /api/v1/repositories/{repository_id}/review/publish
 */
export async function publishCodeReview(
  repositoryId: string,
  payload: {
    run_id: string;
    pr_number: number;
    commit_sha?: string;
    force_publish?: boolean;
    max_comments?: number;
  }
): Promise<{
  status: string;
  review_id?: number | null;
  pr_number?: number | null;
  commit_sha?: string | null;
  published_comments_count: number;
  skipped_reason?: string | null;
  error_message?: string | null;
  published_at?: string | null;
}> {
  const response = await apiClient.post(
    `/repositories/${repositoryId}/review/publish`,
    payload
  );
  return response.data;
}

/**
 * Retrieve repository review automation settings.
 *
 * Calls GET /api/v1/repositories/{repository_id}/review/settings
 */
export async function getReviewSettings(
  repositoryId: string
): Promise<{
  repository_id: string;
  pr_review_enabled: boolean;
  pr_review_drafts: boolean;
  max_comments: number;
  min_confidence: string;
  changed_lines_only: boolean;
}> {
  const response = await apiClient.get(
    `/repositories/${repositoryId}/review/settings`
  );
  return response.data;
}

/**
 * Update repository review automation settings.
 *
 * Calls PATCH /api/v1/repositories/{repository_id}/review/settings
 */
export async function updateReviewSettings(
  repositoryId: string,
  payload: {
    pr_review_enabled?: boolean;
    pr_review_drafts?: boolean;
    max_comments?: number;
    min_confidence?: string;
    changed_lines_only?: boolean;
  }
): Promise<{
  repository_id: string;
  pr_review_enabled: boolean;
  pr_review_drafts: boolean;
  max_comments: number;
  min_confidence: string;
  changed_lines_only: boolean;
}> {
  const response = await apiClient.patch(
    `/repositories/${repositoryId}/review/settings`,
    payload
  );
  return response.data;
}
