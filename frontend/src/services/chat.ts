/**
 * Chat API service.
 *
 * Backend endpoints (backend/app/api/v1/chat.py):
 *   POST   /repositories/{id}/chat                       complete answer (JSON)
 *   POST   /repositories/{id}/chat/stream                answer streamed as Server-Sent Events
 *   GET    /repositories/{id}/chat/conversations         saved conversations
 *   POST   /repositories/{id}/chat/conversations         start a conversation
 *   GET    /repositories/{id}/chat/conversations/{cid}   conversation + messages
 *   PATCH  /repositories/{id}/chat/conversations/{cid}   rename
 *   DELETE /repositories/{id}/chat/conversations/{cid}   delete
 *
 * Streaming uses `fetch` because EventSource cannot POST a body. Auth matches the shared
 * Axios client: the httpOnly cookie (credentials: 'include') plus the stored bearer token
 * for cross-site deployments where third-party cookies are blocked.
 */
import { apiClient, API_BASE_URL, getStoredToken } from './api';
import type {
  ApiError,
  ChatConversationDetail,
  ChatConversationSummary,
  ChatStreamStage,
  RepositoryChatRequest,
  RepositoryChatResponse,
} from '../types/api';

/**
 * Ask a question and receive the complete grounded answer in one response.
 *
 * POST /api/v1/repositories/{repositoryId}/chat
 */
export async function askRepositoryQuestion(
  repositoryId: string,
  payload: RepositoryChatRequest,
  signal?: AbortSignal,
): Promise<RepositoryChatResponse> {
  const response = await apiClient.post<RepositoryChatResponse>(
    `/repositories/${repositoryId}/chat`,
    payload,
    { signal },
  );
  return response.data;
}

// ---------------------------------------------------------------------------
// Streaming
// ---------------------------------------------------------------------------

export interface ChatStreamHandlers {
  onMeta?: (meta: { conversation_id: string | null; mode: string }) => void;
  onStatus?: (stage: ChatStreamStage) => void;
  /** Answer text generated so far — replace the displayed text, do not append. */
  onAnswer?: (text: string) => void;
}

/**
 * Thrown when the stream endpoint cannot be used at all (network error, 404/405 from an
 * older backend). Nothing was generated, so the caller may safely fall back to
 * {@link askRepositoryQuestion}.
 */
export class ChatStreamUnavailableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ChatStreamUnavailableError';
  }
}

function chatError(message: string, status: number, code = 'CHAT_STREAM_ERROR', retryable = true): ApiError {
  return { message, status, code, retryable } as ApiError;
}

/**
 * Ask a question and receive the answer as it is generated.
 *
 * Resolves with the final, grounded answer (the `done` event). Rejects with an ApiError-shaped
 * object for server errors, or {@link ChatStreamUnavailableError} when streaming is unavailable.
 */
export async function streamRepositoryQuestion(
  repositoryId: string,
  payload: RepositoryChatRequest,
  handlers: ChatStreamHandlers = {},
  signal?: AbortSignal,
): Promise<RepositoryChatResponse> {
  if (typeof fetch !== 'function' || typeof TextDecoder === 'undefined') {
    throw new ChatStreamUnavailableError('Streaming is not supported in this environment.');
  }

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  };
  const token = getStoredToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/repositories/${repositoryId}/chat/stream`, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
      credentials: 'include',
      signal,
    });
  } catch (err) {
    if (signal?.aborted) throw err;
    throw new ChatStreamUnavailableError(err instanceof Error ? err.message : 'Network error');
  }

  // 401: the Axios client knows how to refresh the session and retry, so let the caller fall
  // back to it. 404/405/501: an older backend without the stream endpoint. Nothing was
  // generated in either case, so falling back cannot produce a duplicate answer.
  if ([401, 404, 405, 501].includes(response.status)) {
    throw new ChatStreamUnavailableError(`Streaming endpoint unavailable (HTTP ${response.status}).`);
  }
  if (!response.ok) {
    // Ordinary API error before streaming started (401, 403, 404 conversation, 429, 503...).
    let message = `Request failed (HTTP ${response.status}).`;
    let code = 'HTTP_ERROR';
    let retryable = response.status >= 500 || response.status === 429;
    try {
      const body = await response.json();
      message = body?.error?.message ?? body?.detail ?? message;
      code = body?.error?.code ?? code;
      retryable = body?.error?.retryable ?? retryable;
    } catch {
      // keep defaults
    }
    throw chatError(message, response.status, code, retryable);
  }
  if (!response.body) {
    throw new ChatStreamUnavailableError('Response has no body to stream.');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let final: RepositoryChatResponse | null = null;

  const handleEvent = (eventName: string, dataText: string) => {
    let data: unknown;
    try {
      data = JSON.parse(dataText);
    } catch {
      return;
    }
    const obj = (data ?? {}) as Record<string, unknown>;
    switch (eventName) {
      case 'meta':
        handlers.onMeta?.({
          conversation_id: (obj.conversation_id as string | null) ?? null,
          mode: String(obj.mode ?? 'normal'),
        });
        break;
      case 'status':
        handlers.onStatus?.(obj.stage as ChatStreamStage);
        break;
      case 'answer':
        handlers.onAnswer?.(String(obj.text ?? ''));
        break;
      case 'done':
        final = data as RepositoryChatResponse;
        break;
      case 'error':
        throw chatError(
          String(obj.message ?? 'The answer could not be generated.'),
          500,
          String(obj.code ?? 'CHAT_STREAM_ERROR'),
          Boolean(obj.retryable ?? true),
        );
      default:
        break;
    }
  };

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');
      let sep: number;
      while ((sep = buffer.indexOf('\n\n')) !== -1) {
        const rawEvent = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        let eventName = 'message';
        const dataLines: string[] = [];
        for (const line of rawEvent.split('\n')) {
          if (line.startsWith('event:')) eventName = line.slice(6).trim();
          else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
        }
        if (dataLines.length) handleEvent(eventName, dataLines.join('\n'));
      }
    }
  } finally {
    reader.releaseLock?.();
  }

  if (!final) {
    throw chatError('The connection closed before the answer was complete.', 502, 'CHAT_STREAM_INCOMPLETE', true);
  }
  return final;
}

// ---------------------------------------------------------------------------
// Conversations (server-side history)
// ---------------------------------------------------------------------------

export async function listConversations(repositoryId: string): Promise<ChatConversationSummary[]> {
  const response = await apiClient.get<{ items: ChatConversationSummary[]; total: number }>(
    `/repositories/${repositoryId}/chat/conversations`,
  );
  return response.data.items;
}

export async function createConversation(
  repositoryId: string,
  title?: string,
): Promise<ChatConversationSummary> {
  const response = await apiClient.post<ChatConversationSummary>(
    `/repositories/${repositoryId}/chat/conversations`,
    title ? { title } : {},
  );
  return response.data;
}

export async function getConversation(
  repositoryId: string,
  conversationId: string,
): Promise<ChatConversationDetail> {
  const response = await apiClient.get<ChatConversationDetail>(
    `/repositories/${repositoryId}/chat/conversations/${conversationId}`,
  );
  return response.data;
}

export async function renameConversation(
  repositoryId: string,
  conversationId: string,
  title: string,
): Promise<ChatConversationSummary> {
  const response = await apiClient.patch<ChatConversationSummary>(
    `/repositories/${repositoryId}/chat/conversations/${conversationId}`,
    { title },
  );
  return response.data;
}

export async function deleteConversation(repositoryId: string, conversationId: string): Promise<void> {
  await apiClient.delete(`/repositories/${repositoryId}/chat/conversations/${conversationId}`);
}
