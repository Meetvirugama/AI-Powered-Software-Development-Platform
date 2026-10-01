/**
 * useRepositoryChat — Day 7.
 *
 * Manages conversation state for the repository chat feature and calls the
 * real backend API.
 *
 * Architecture:
 *
 * 1. Conversation state is LOCAL (useState in this hook).
 *    Messages are ephemeral for Week 1. If server-side history is added later
 *    a TanStack Query layer can wrap this without rewriting the UI.
 *
 * 2. History building.
 *    Before each request the hook converts completed ChatMessage[] turns into
 *    ChatHistoryMessage[] (role + content only) — no UI-only fields are sent.
 *    The current question is NOT included in history.
 *
 * 3. Request flow (real backend, non-streaming):
 *    a. User question appended to local messages immediately (optimistic).
 *    b. Assistant placeholder added with isStreaming: true / empty content.
 *    c. POST /repositories/:id/chat issued with question + history.
 *    d. On success: placeholder replaced with answer, sources, confidence.
 *    e. On error:  placeholder finalised (isStreaming: false), error string set.
 *
 * 4. Repository data is NOT duplicated.
 *    Callers use useRepository(id) separately for repository metadata.
 *
 * 5. Cancellation.
 *    A cancelled flag is set on component unmount so in-flight responses
 *    do not update unmounted state.
 *
 * 6. No Zustand.
 *    Conversation state is local to this hook. No global store is introduced.
 */
import { useState, useCallback, useRef, useEffect } from 'react';
import { askRepositoryQuestion } from '../services/chat';
import type {
  ChatMessage,
  ChatHistoryMessage,
  RepositoryChatResponse,
} from '../types/api';

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function newMessageId(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2);
}

/**
 * Convert completed UI messages into the history format expected by the backend.
 *
 * Rules:
 *  - Only completed (non-streaming, non-empty) messages are included.
 *  - Strips UI-only fields: id, timestamp, sources, confidence, isStreaming.
 *  - Enforces the backend max-50-messages constraint (most-recent 50).
 */
function buildHistory(messages: ChatMessage[]): ChatHistoryMessage[] {
  const completed = messages.filter(
    (m) => !m.isStreaming && m.content.trim().length > 0,
  );
  const limited = completed.slice(-50); // backend max: 50
  return limited.map((m) => ({ role: m.role, content: m.content }));
}

// ---------------------------------------------------------------------------
// Hook public interface
// ---------------------------------------------------------------------------

export interface UseRepositoryChatReturn {
  messages: ChatMessage[];
  /** True while a request is in flight. Blocks duplicate sends. */
  isPending: boolean;
  /** Error string from the last failed request, or null. */
  error: string | null;
  /** Send a question. No-op while isPending. */
  sendMessage: (question: string) => void;
  /** Clear all messages and reset state. */
  clearConversation: () => void;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useRepositoryChat(
  repositoryId: string | undefined,
): UseRepositoryChatReturn {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Prevent state updates after unmount.
  const cancelledRef = useRef(false);
  useEffect(() => {
    cancelledRef.current = false;
    return () => {
      cancelledRef.current = true;
    };
  }, []);

  const sendMessage = useCallback(
    (question: string) => {
      const trimmed = question.trim();
      if (!trimmed || isPending || !repositoryId) return;

      setError(null);
      setIsPending(true);

      // 1. Capture history BEFORE adding the new user message.
      //    The current question must NOT appear in history.
      setMessages((prev) => {
        const history = buildHistory(prev);

        // 2. Optimistically add the user message.
        const userMessage: ChatMessage = {
          id: newMessageId(),
          role: 'user',
          content: trimmed,
          timestamp: new Date().toISOString(),
          sources: [],
          isStreaming: false,
        };

        // 3. Add an assistant placeholder in pending state.
        const assistantId = newMessageId();
        const assistantPlaceholder: ChatMessage = {
          id: assistantId,
          role: 'assistant',
          content: '',
          timestamp: new Date().toISOString(),
          sources: [],
          isStreaming: true,
        };

        const next = [...prev, userMessage, assistantPlaceholder];

        // 4. Fire the real API request.
        askRepositoryQuestion(repositoryId, { question: trimmed, history })
          .then((response: RepositoryChatResponse) => {
            if (cancelledRef.current) return;
            setMessages((current) =>
              current.map((msg) =>
                msg.id === assistantId
                  ? {
                      ...msg,
                      content: response.answer,
                      sources: response.sources ?? [],
                      confidence: response.confidence,
                      isStreaming: false,
                    }
                  : msg,
              ),
            );
            setIsPending(false);
          })
          .catch((err: unknown) => {
            if (cancelledRef.current) return;
            const message =
              err instanceof Error
                ? err.message
                : 'The assistant could not complete the response. Please try again.';
            // Finalise the placeholder so it renders a stable empty state.
            setMessages((current) =>
              current.map((msg) =>
                msg.id === assistantId
                  ? { ...msg, isStreaming: false }
                  : msg,
              ),
            );
            setError(message);
            setIsPending(false);
          });

        return next;
      });
    },
    [isPending, repositoryId],
  );

  const clearConversation = useCallback(() => {
    setMessages([]);
    setError(null);
    setIsPending(false);
  }, []);

  return { messages, isPending, error, sendMessage, clearConversation };
}
