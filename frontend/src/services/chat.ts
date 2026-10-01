/**
 * Chat API service — Day 6.
 *
 * All chat API calls go through this module.
 * Components and hooks must NOT call apiClient directly for chat operations.
 *
 * Current assumed endpoint (backed by MSW, not yet confirmed with backend):
 *   POST /api/v1/repositories/:id/chat
 *   Body:    { "question": string }
 *   Returns: ChatResponse { answer: string, sources: ChatSource[] }
 *
 * Streaming readiness:
 *   The function signature and return type are designed so that when the
 *   backend confirms a streaming/SSE contract, ONLY this file needs updating.
 *   The hook (useRepositoryChat) and the UI (RepositoryChat.tsx) consume
 *   ChatResponse and ChatMessage — they do not depend on the transport.
 *
 *   To add SSE streaming later:
 *     1. Replace the Axios POST here with a fetch() + ReadableStream reader.
 *     2. Emit chunk events via a provided callback (onChunk: (delta: string) => void).
 *     3. Update the hook to set isStreaming=true on the placeholder message,
 *        then set it to false when streaming is complete.
 *     4. No changes are required in RepositoryChat.tsx or api.ts.
 */
import { apiClient } from './api';
import type { ChatRequest, ChatResponse } from '../types/api';

/**
 * Send a question about a repository and receive an assistant response.
 *
 * POST /api/v1/repositories/:repositoryId/chat
 *
 * @param repositoryId  Our internal repository UUID.
 * @param request       The chat request payload containing the user's question.
 * @returns             ChatResponse with the assistant's answer and sources.
 *
 * BACKEND ASSUMPTION (unconfirmed):
 *   - Endpoint path: /api/v1/repositories/:id/chat
 *   - Request body field name: "question"
 *   - Response field names: "answer", "sources"
 *   Update only this function when the backend confirms the contract.
 */
export async function askRepositoryQuestion(
  repositoryId: string,
  request: ChatRequest,
): Promise<ChatResponse> {
  const response = await apiClient.post<ChatResponse>(
    `/repositories/${repositoryId}/chat`,
    request,
  );
  return response.data;
}
