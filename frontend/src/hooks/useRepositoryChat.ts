/**
 * useRepositoryChat — chat hook for Day 6 (streaming-capable).
 *
 * Architecture:
 *
 * 1. Conversation state is LOCAL (useState in this hook).
 *    Messages are ephemeral for Week 1. If server-side history is added later,
 *    a TanStack Query layer can wrap this without rewriting the UI.
 *
 * 2. STREAMING via streamRepositoryQuestion() in services/chat.ts.
 *    The page and components do not know about the transport.
 *    The hook mediates between the streaming adapter and the message list.
 *
 * 3. Message lifecycle:
 *    PENDING    → network request in flight, no content yet
 *    STREAMING  → chunks arriving, content growing (isStreaming=true)
 *    COMPLETE   → final response received (isStreaming=false, sources set)
 *    ERROR      → request or stream failed
 *
 * 4. Repository data is NOT duplicated.
 *    Callers use useRepository(id) separately for repository metadata.
 *
 * 5. Cancel on unmount.
 *    The hook stores the streaming cancel function and calls it in cleanup.
 */
import { useState, useCallback, useRef, useEffect } from 'react';
import { streamRepositoryQuestion } from '../services/chat';
import type { ChatMessage, ChatResponse } from '../types/api';

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function newMessageId(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2);
}

// ---------------------------------------------------------------------------
// Hook public interface
// ---------------------------------------------------------------------------

export interface UseRepositoryChatReturn {
  /** Ordered list of messages in the current conversation. */
  messages: ChatMessage[];
  /**
   * True while a question is in flight (either fetching or actively streaming).
   * Blocks duplicate sends.
   */
  isPending: boolean;
  /** Error message from the last failed request, or null. */
  error: string | null;
  /** Send a question. No-op while isPending is true. */
  sendMessage: (question: string) => void;
  /** Clear all messages and reset state. */
  clearConversation: () => void;
}

// ---------------------------------------------------------------------------
// Hook implementation
// ---------------------------------------------------------------------------

export function useRepositoryChat(
  repositoryId: string | undefined,
): UseRepositoryChatReturn {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Store the cancel function returned by streamRepositoryQuestion so we can
  // clean up if the component unmounts mid-stream or sendMessage is recalled.
  const cancelRef = useRef<(() => void) | null>(null);

  // Cancel any in-flight stream when the hook unmounts.
  useEffect(() => {
    return () => {
      cancelRef.current?.();
    };
  }, []);

  const sendMessage = useCallback(
    (question: string) => {
      const trimmed = question.trim();
      if (!trimmed || isPending || !repositoryId) return;

      // Cancel any previous stream (defensive; isPending guard should prevent this).
      cancelRef.current?.();
      cancelRef.current = null;

      setError(null);
      setIsPending(true);

      // 1. Optimistically add the user message.
      const userMessage: ChatMessage = {
        id: newMessageId(),
        role: 'user',
        content: trimmed,
        timestamp: new Date().toISOString(),
        sources: [],
        isStreaming: false,
      };

      // 2. Add a placeholder assistant message in streaming state.
      const assistantId = newMessageId();
      const assistantPlaceholder: ChatMessage = {
        id: assistantId,
        role: 'assistant',
        content: '',
        timestamp: new Date().toISOString(),
        sources: [],
        isStreaming: true,
      };

      setMessages((prev) => [...prev, userMessage, assistantPlaceholder]);

      // 3. Start streaming.
      const cancel = streamRepositoryQuestion(
        repositoryId,
        { question: trimmed },
        {
          // Each chunk: append delta to the active assistant message content.
          onChunk: (delta: string) => {
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantId
                  ? { ...msg, content: msg.content + delta, isStreaming: true }
                  : msg,
              ),
            );
          },

          // Completion: finalise the message, attach sources.
          onComplete: (response: ChatResponse) => {
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantId
                  ? {
                      ...msg,
                      content: response.answer, // use full canonical answer
                      sources: response.sources ?? [],
                      isStreaming: false,
                    }
                  : msg,
              ),
            );
            setIsPending(false);
            cancelRef.current = null;
          },

          // Error: mark the assistant placeholder as failed, keep conversation.
          onError: (err: Error) => {
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantId
                  ? { ...msg, isStreaming: false }
                  : msg,
              ),
            );
            setError(
              err.message ||
                'The assistant could not complete the response. Please try again.',
            );
            setIsPending(false);
            cancelRef.current = null;
          },
        },
      );

      cancelRef.current = cancel;
    },
    [isPending, repositoryId],
  );

  const clearConversation = useCallback(() => {
    cancelRef.current?.();
    cancelRef.current = null;
    setMessages([]);
    setError(null);
    setIsPending(false);
  }, []);

  return { messages, isPending, error, sendMessage, clearConversation };
}
