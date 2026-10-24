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
  PaginatedAnalysisRunResponse,
  AnalysisRunDetailResponse,
  AnalysisFeatureType,
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
 * List historical analysis runs (e.g. explanation runs) for an authorized repository.
 *
 * @param repositoryId The UUID of the authorized repository.
 * @param params Query filtering and pagination options.
 * @returns Paginated list of analysis run summaries.
 */
export async function getAnalysisRuns(
  repositoryId: string,
  params?: {
    feature_type?: AnalysisFeatureType;
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
 * Reopen a specific analysis run (e.g. past explanation) from persistent history.
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

