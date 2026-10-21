/**
 * Developer Intelligence Analysis Services.
 *
 * Calls Week 2 API endpoints registered in backend/app/api/v1/analysis.py:
 *   - POST /api/v1/repositories/{repository_id}/explain
 */

import { apiClient } from './api';
import type { ExplainCodeRequest, CodeExplanationResponse } from '../types/analysis';

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
