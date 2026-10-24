/**
 * Developer Intelligence Analysis Services.
 *
 * Calls Week 2 API endpoints registered in backend/app/api/v1/analysis.py:
 *   - POST /api/v1/repositories/{repository_id}/explain
 */

import { apiClient } from './api';
import type {
  ExplainCodeRequest,
  CodeExplanationResponse,
  BugDetectionRequest,
  BugDetectionResponse,
  TestGenerationRequest,
  TestGenerationResponse,
  PaginatedAnalysisRunResponse,
  AnalysisRunDetailResponse,
  AnalysisRunFeatureType,
} from '../types/analysis';

/**
 * Request an AI-powered explanation for a file, symbol, or line range.
 *
 * @param repositoryId The UUID of the authorized repository.
 * @param payload The validated target and execution options.
 * @returns The structured explanation response envelope.
 */
export async function explainCode(
  repositoryId: string,
  payload: ExplainCodeRequest
): Promise<CodeExplanationResponse> {
  const response = await apiClient.post<CodeExplanationResponse>(
    `/repositories/${repositoryId}/explain`,
    payload
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
 * @returns The structured bug detection response envelope.
 */
export async function detectBugs(
  repositoryId: string,
  payload: BugDetectionRequest
): Promise<BugDetectionResponse> {
  const response = await apiClient.post<BugDetectionResponse>(
    `/repositories/${repositoryId}/detect-bugs`,
    payload
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
 * @returns The structured test generation response envelope.
 */
export async function generateTests(
  repositoryId: string,
  payload: TestGenerationRequest
): Promise<TestGenerationResponse> {
  const response = await apiClient.post<TestGenerationResponse>(
    `/repositories/${repositoryId}/generate-tests`,
    payload
  );
  return response.data;
}

/**
 * List historical analysis runs (e.g. explanation runs, bug scans) for an authorized repository.
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
 * List historical bug detection scans for an authorized repository.
 *
 * @param repositoryId The UUID of the authorized repository.
 * @param params Query filtering and pagination options.
 * @returns Paginated list of analysis run summaries.
 */
export async function getBugScanHistory(
  repositoryId: string,
  params?: {
    status?: string;
    target_path?: string;
    source_revision?: string;
    page?: number;
    page_size?: number;
  }
): Promise<PaginatedAnalysisRunResponse> {
  return getAnalysisRuns(repositoryId, {
    ...params,
    feature_type: 'detect_bugs',
  });
}

/**
 * Reopen a specific analysis run (e.g. past explanation or bug scan) from persistent history.
 *
 * @param runId The UUID of the analysis run.
 * @returns Detailed record with target coordinates and structured result payload.
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
 * Reopen a specific bug detection scan run from persistent history.
 *
 * @param runId The UUID of the bug detection analysis run.
 * @returns Detailed record with findings and structured result payload.
 */
export async function reopenBugScan(
  runId: string
): Promise<AnalysisRunDetailResponse> {
  return getAnalysisRun(runId);
}

