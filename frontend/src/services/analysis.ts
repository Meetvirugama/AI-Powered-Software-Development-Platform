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
 * Scan for bugs using static analysis rules and AI reasoning.
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
