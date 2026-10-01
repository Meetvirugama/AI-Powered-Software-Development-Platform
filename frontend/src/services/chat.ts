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
 * Streaming architecture:
 *
 *   streamRepositoryQuestion() — mock streaming adapter.
 *
 *   This function calls the Axios endpoint (which hits MSW in dev) to get the
 *   full response, then replays it word-by-word using setTimeout to simulate
 *   a streaming UX. The hook receives incremental chunks via the onChunk
 *   callback and the complete payload via onComplete.
 *
 *   When the backend implements real streaming (SSE or fetch ReadableStream):
 *     1. Replace the setTimeout simulation below with a real fetch + stream reader.
 *     2. Pipe each decoded text delta to onChunk.
 *     3. Signal completion (with sources) via onComplete.
 *     4. The hook (useRepositoryChat) and UI (RepositoryChat.tsx) stay unchanged.
 *
 *   The AbortSignal parameter is wired so that the real implementation can
 *   cancel inflight network requests when the user navigates away.
 */
import { apiClient } from './api';
import type { ChatRequest, ChatResponse } from '../types/api';

// ---------------------------------------------------------------------------
// Non-streaming helper (kept for internal use in the streaming adapter)
// ---------------------------------------------------------------------------

async function fetchChatResponse(
  repositoryId: string,
  request: ChatRequest,
): Promise<ChatResponse> {
  const response = await apiClient.post<ChatResponse>(
    `/repositories/${repositoryId}/chat`,
    request,
  );
  return response.data;
}

// ---------------------------------------------------------------------------
// Streaming adapter
// ---------------------------------------------------------------------------

export interface StreamCallbacks {
  /** Called with each incremental text chunk. */
  onChunk: (delta: string) => void;
  /** Called when streaming is complete. Receives the full final response. */
  onComplete: (response: ChatResponse) => void;
  /** Called if the request or stream fails. */
  onError: (error: Error) => void;
}

/**
 * Send a question and simulate a streaming response.
 *
 * In development/MSW, this fetches the complete response and replays it
 * chunk-by-chunk via setTimeout to provide a realistic streaming UX.
 *
 * Returns a cancel function. Call it to abort an in-flight simulation.
 * When real backend streaming is implemented, this cancel function will
 * call AbortController.abort() on the underlying fetch.
 *
 * MOCK BEHAVIOUR (to replace with real streaming later):
 *   - Full response is fetched from MSW.
 *   - Answer is split on whitespace into word-level tokens.
 *   - Each token is emitted with a ~30ms delay to simulate token generation.
 *   - Sources are delivered via onComplete at the end.
 */
export function streamRepositoryQuestion(
  repositoryId: string,
  request: ChatRequest,
  callbacks: StreamCallbacks,
): () => void {
  let cancelled = false;
  const timers: ReturnType<typeof setTimeout>[] = [];

  // Kick off the actual HTTP request immediately.
  fetchChatResponse(repositoryId, request)
    .then((response) => {
      if (cancelled) return;

      // Split answer into tokens (words + trailing spaces preserved).
      const tokens = response.answer.match(/(\S+\s*)/g) ?? [response.answer];
      const CHUNK_DELAY_MS = 30;

      tokens.forEach((token, i) => {
        const t = setTimeout(() => {
          if (!cancelled) {
            callbacks.onChunk(token);
          }
        }, i * CHUNK_DELAY_MS);
        timers.push(t);
      });

      // Signal completion after all chunks have been emitted.
      const completionDelay = tokens.length * CHUNK_DELAY_MS + 80;
      const finalTimer = setTimeout(() => {
        if (!cancelled) {
          callbacks.onComplete(response);
        }
      }, completionDelay);
      timers.push(finalTimer);
    })
    .catch((err: unknown) => {
      if (!cancelled) {
        callbacks.onError(
          err instanceof Error ? err : new Error(String(err)),
        );
      }
    });

  // Return a cancel function.
  return () => {
    cancelled = true;
    timers.forEach(clearTimeout);
  };
}
