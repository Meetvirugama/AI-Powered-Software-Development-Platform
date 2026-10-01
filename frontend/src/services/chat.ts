/**
 * Chat API service — Day 7.
 *
 * Connects to the real backend repository chat endpoint.
 *
 * Backend endpoint (confirmed):
 *   POST /api/v1/repositories/{repository_id}/chat
 *
 * Request  — RepositoryChatRequest  (backend/app/schemas/repository.py)
 * Response — RepositoryAnswer       (backend/ai/schemas/output.py)
 *
 * Authentication:
 *   The existing Axios instance is configured with withCredentials: true,
 *   which sends the httpOnly auth cookie automatically. No token injection
 *   is required or allowed here.
 *
 * Streaming:
 *   The backend currently returns a single complete RepositoryAnswer.
 *   No token-by-token streaming is performed. The hook (useRepositoryChat)
 *   manages a pending/loading state while this request is in flight.
 *
 *   When the backend adds a real streaming endpoint in a future sprint,
 *   only this file needs to change — the hook and UI remain stable.
 *
 * Error handling:
 *   All errors pass through the existing Axios response interceptor
 *   (src/services/api.ts), which normalises them into the project ApiError
 *   shape. The hook converts ApiError.message into a user-readable string.
 *
 * NOTE: The Day 6 mock streaming adapter (streamRepositoryQuestion) has been
 * removed from the production path. It is no longer needed because:
 *   a) The real backend returns a complete response — not chunks.
 *   b) The UI correctly shows a pending state while the request is in flight.
 */
import { apiClient } from './api';
import type { RepositoryChatRequest, RepositoryChatResponse } from '../types/api';

/**
 * Ask a question about a repository and receive a grounded answer.
 *
 * POST /api/v1/repositories/{repositoryId}/chat
 *
 * @param repositoryId  Internal UUID of the target repository (from route params).
 * @param payload       The validated request payload (question + history).
 * @returns             RepositoryChatResponse with answer, sources, and confidence.
 *
 * History note:
 *   The caller (useRepositoryChat hook) is responsible for building the history
 *   array from the current conversation state. This function does not inspect
 *   or modify the history — it sends it verbatim to the backend.
 */
export async function askRepositoryQuestion(
  repositoryId: string,
  payload: RepositoryChatRequest,
): Promise<RepositoryChatResponse> {
  const response = await apiClient.post<RepositoryChatResponse>(
    `/repositories/${repositoryId}/chat`,
    payload,
  );
  return response.data;
}
