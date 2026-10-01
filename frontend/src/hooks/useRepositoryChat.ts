/**
 * useRepositoryChat — chat mutation hook for Day 6.
 *
 * Architecture decisions:
 *
 * 1. MUTATION, not query.
 *    Chat is triggered by user action, not auto-fetched on mount.
 *    TanStack Query's useMutation is the correct primitive.
 *
 * 2. Conversation state is LOCAL.
 *    The messages array lives in React component state (useState in the
 *    hook), not in Zustand and not in TanStack Query cache.
 *    Reasons:
 *      - Conversations are ephemeral (not persisted to the server yet).
 *      - There is no cross-component need to share conversation state.
 *      - Using TanStack Query cache for mutable conversation history
 *        would require awkward manual cache updates.
 *    If persistence (chat history API) is added later, a TanStack Query
 *    layer can be introduced without rewriting the UI.
 *
 * 3. Repository data is NOT duplicated.
 *    Callers reuse useRepository(id) for repository metadata.
 *    This hook handles ONLY the chat mutation and conversation state.
 *
 * 4. Streaming readiness.
 *    When the backend adds SSE streaming, only src/services/chat.ts
 *    changes. This hook's sendMessage interface stays the same:
 *    it optimistically appends a placeholder assistant message with
 *    isStreaming=true, then replaces it once complete.
 */
import { useState, useCallback } from 'react';
import { useMutation } from '@tanstack/react-query';
import { askRepositoryQuestion } from '../services/chat';
import type { ChatMessage, ChatResponse } from '../types/api';

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

/** Generate a client-side message ID. Falls back to Math.random if crypto unavailable. */
function newMessageId(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2);
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export interface UseRepositoryChatReturn {
  /** Ordered list of messages in the current conversation. */
  messages: ChatMessage[];
  /** True while a question is in flight. */
  isPending: boolean;
  /** The last error returned by the chat endpoint, or null. */
  error: string | null;
  /**
   * Send a question and append the response to the conversation.
   * Safe to call while isPending is false.
   */
  sendMessage: (question: string) => void;
  /** Clear the current conversation. */
  clearConversation: () => void;
}

/**
 * useRepositoryChat
 *
 * Manages the chat conversation state and mutation for a single repository.
 *
 * @param repositoryId  Our internal repository UUID from the route params.
 *
 * Usage:
 *   const { messages, isPending, error, sendMessage, clearConversation } =
 *     useRepositoryChat(id);
 */
export function useRepositoryChat(
  repositoryId: string | undefined,
): UseRepositoryChatReturn {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation<ChatResponse, Error, string>({
    mutationFn: (question: string) => {
      if (!repositoryId) {
        return Promise.reject(new Error('Repository ID is required.'));
      }
      return askRepositoryQuestion(repositoryId, { question });
    },

    onSuccess: (data, question) => {
      setError(null);

      // The user message was already appended optimistically in sendMessage.
      // Now append the assistant response.
      const assistantMessage: ChatMessage = {
        id: newMessageId(),
        role: 'assistant',
        content: data.answer,
        timestamp: new Date().toISOString(),
        sources: data.sources,
        isStreaming: false,
      };

      setMessages((prev) => {
        // Replace the optimistic placeholder (last message is the user question,
        // which we already added). Append the assistant message after it.
        return [...prev, assistantMessage];
      });

      // Suppress unused variable warning — question is used for context only.
      void question;
    },

    onError: (err) => {
      setError(err.message ?? 'Failed to get a response. Please try again.');

      // Remove the optimistically-added user message on hard failure so the
      // user can retry without a duplicate entry.
      setMessages((prev) => prev.slice(0, -1));
    },
  });

  const sendMessage = useCallback(
    (question: string) => {
      const trimmed = question.trim();
      if (!trimmed || mutation.isPending) return;

      setError(null);

      // Optimistically add the user message immediately so the UI feels
      // responsive before the network round-trip completes.
      const userMessage: ChatMessage = {
        id: newMessageId(),
        role: 'user',
        content: trimmed,
        timestamp: new Date().toISOString(),
        sources: [],
        isStreaming: false,
      };

      setMessages((prev) => [...prev, userMessage]);
      mutation.mutate(trimmed);
    },
    [mutation],
  );

  const clearConversation = useCallback(() => {
    setMessages([]);
    setError(null);
    mutation.reset();
  }, [mutation]);

  return {
    messages,
    isPending: mutation.isPending,
    error,
    sendMessage,
    clearConversation,
  };
}
