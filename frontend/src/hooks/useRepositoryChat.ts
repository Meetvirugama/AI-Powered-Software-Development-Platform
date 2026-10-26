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
import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import axios from 'axios';
import { askRepositoryQuestion } from '../services/chat';
import type {
  ChatMessage,
  ChatHistoryMessage,
  RepositoryChatResponse,
} from '../types/api';

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

/**
 * Generate a unique ID for chat messages.
 * Uses crypto.randomUUID when available, falling back to Math.random.
 */
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
 *  - Excludes any trailing unanswered user turn so history strictly contains completed dialog turns.
 *  - Enforces the backend max-50-messages constraint (most-recent 50).
 */
function buildHistory(messages: ChatMessage[]): ChatHistoryMessage[] {
  const completed = messages.filter(
    (m) => !m.isStreaming && m.content.trim().length > 0,
  );
  let validTurns = completed;
  while (validTurns.length > 0 && validTurns[validTurns.length - 1].role === 'user') {
    validTurns = validTurns.slice(0, -1);
  }
  const limited = validTurns.slice(-50); // backend max: 50
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

/**
 * Manage separate, in-memory conversations for each repository in this hook instance.
 * Switching repositories preserves messages and errors but aborts the previous
 * repository's request; unmounting aborts all active requests.
 *
 * @param repositoryId Repository to display, or undefined for an empty, inactive view.
 * @returns Current repository's messages, pending status, error, and send/reset actions.
 * Request failures remove the assistant placeholder and populate error; cancellation
 * due to repo switch retains the user message and sets a retryable error.
 */
export function useRepositoryChat(
  repositoryId: string | undefined,
): UseRepositoryChatReturn {
  // Key state by repositoryId for immediate isolation across navigation
  const [conversations, setConversations] = useState<Record<string, ChatMessage[]>>({});
  const [pendingRepos, setPendingRepos] = useState<Record<string, boolean>>({});
  const [errorMap, setErrorMap] = useState<Record<string, string | null>>({});

  // Active AbortControllers per repository
  const abortControllersRef = useRef<Record<string, AbortController>>({});
  // Track specific abort reason per repository to distinguish intentional clear vs repo switch
  const abortReasonsRef = useRef<Record<string, 'repo_switch' | 'clear' | 'unmount' | 'superseded'>>({});

  // Cleanly derive current repository view with zero transient leakage
  const messages = useMemo(() => {
    if (!repositoryId) return [];
    return conversations[repositoryId] ?? [];
  }, [repositoryId, conversations]);

  const isPending = Boolean(repositoryId && pendingRepos[repositoryId]);
  const error = repositoryId ? (errorMap[repositoryId] ?? null) : null;

  // Track repositoryId changes: abort previous repository request if navigating away
  const prevRepoIdRef = useRef<string | undefined>(repositoryId);
  useEffect(() => {
    if (prevRepoIdRef.current && prevRepoIdRef.current !== repositoryId) {
      const prevId = prevRepoIdRef.current;
      if (abortControllersRef.current[prevId]) {
        abortReasonsRef.current[prevId] = 'repo_switch';
        abortControllersRef.current[prevId].abort();
        delete abortControllersRef.current[prevId];
      }
      setPendingRepos((prev) => ({ ...prev, [prevId]: false }));
    }
    prevRepoIdRef.current = repositoryId;
  }, [repositoryId]);

  // Abort all active requests on hook unmount
  useEffect(() => {
    const reasons = abortReasonsRef.current;
    const controllers = abortControllersRef.current;
    return () => {
      Object.entries(controllers).forEach(([id, ctrl]) => {
        try {
          reasons[id] = 'unmount';
          ctrl.abort();
        } catch {
          // ignore
        }
      });
      Object.keys(controllers).forEach((id) => {
        delete controllers[id];
      });
    };
  }, []);

  /**
   * Submit a trimmed question with up to 50 prior completed messages, immediately
   * adding the user message and a pending assistant placeholder. Ignore blank
   * questions, a missing repository ID, or sends while this view is pending.
   * If retrying an unanswered user question, reuses the existing user turn.
   */
  const sendMessage = useCallback(
    (question: string) => {
      const trimmed = question.trim();
      if (!trimmed || isPending || !repositoryId) return;

      // Abort any existing in-flight request for this repository
      if (abortControllersRef.current[repositoryId]) {
        abortReasonsRef.current[repositoryId] = 'superseded';
        abortControllersRef.current[repositoryId].abort();
        delete abortControllersRef.current[repositoryId];
      }

      const controller = new AbortController();
      abortControllersRef.current[repositoryId] = controller;

      // Check whether the current conversation ends with an unanswered user message
      const currentMessages = conversations[repositoryId] ?? [];
      const lastMessage = currentMessages[currentMessages.length - 1];
      const isLastUnansweredUser = Boolean(lastMessage && lastMessage.role === 'user');

      // 1. Capture history BEFORE adding the new user message, excluding any trailing unanswered user turn
      const currentHistory = buildHistory(
        isLastUnansweredUser ? currentMessages.slice(0, -1) : currentMessages,
      );

      // 2. Optimistic user message and assistant placeholder
      const userMessage: ChatMessage = {
        id: newMessageId(),
        role: 'user',
        content: trimmed,
        timestamp: new Date().toISOString(),
        sources: [],
        isStreaming: false,
      };

      const assistantId = newMessageId();
      const assistantPlaceholder: ChatMessage = {
        id: assistantId,
        role: 'assistant',
        content: '',
        timestamp: new Date().toISOString(),
        sources: [],
        isStreaming: true,
      };

      // 3. Update state synchronously — pure state update, NO API calls inside updater.
      // If retrying the same unanswered question, preserve the user bubble and append the assistant placeholder.
      setConversations((prev) => {
        const existing = prev[repositoryId] ?? [];
        const last = existing[existing.length - 1];
        if (last && last.role === 'user') {
          if (last.content === trimmed) {
            return {
              ...prev,
              [repositoryId]: [...existing, assistantPlaceholder],
            };
          }
          return {
            ...prev,
            [repositoryId]: [...existing.slice(0, -1), userMessage, assistantPlaceholder],
          };
        }
        return {
          ...prev,
          [repositoryId]: [...existing, userMessage, assistantPlaceholder],
        };
      });

      setPendingRepos((prev) => ({
        ...prev,
        [repositoryId]: true,
      }));
      setErrorMap((prev) => ({
        ...prev,
        [repositoryId]: null,
      }));

      // 4. Fire API request outside the state setter
      askRepositoryQuestion(
        repositoryId,
        { question: trimmed, history: currentHistory },
        controller.signal,
      )
        .then((response: RepositoryChatResponse) => {
          // Ignore if request was aborted or superseded
          if (controller.signal.aborted || abortControllersRef.current[repositoryId] !== controller) {
            return;
          }
          delete abortControllersRef.current[repositoryId];
          delete abortReasonsRef.current[repositoryId];

          setConversations((prev) => {
            const repoMsgs = prev[repositoryId] ?? [];
            return {
              ...prev,
              [repositoryId]: repoMsgs.map((msg) =>
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
            };
          });
          setPendingRepos((prev) => ({
            ...prev,
            [repositoryId]: false,
          }));
        })
        .catch((err: unknown) => {
          const reason = abortReasonsRef.current[repositoryId];
          const isCancelled =
            controller.signal.aborted ||
            axios.isCancel(err) ||
            (err instanceof Error && (err.name === 'CanceledError' || err.name === 'AbortError')) ||
            (typeof err === 'object' &&
              err !== null &&
              'message' in err &&
              (err as { message?: string }).message === 'canceled');

          if (isCancelled) {
            // Remove the pending placeholder so no hanging bubble is left
            setConversations((prev) => {
              const repoMsgs = prev[repositoryId] ?? [];
              return {
                ...prev,
                [repositoryId]: repoMsgs.filter((msg) => msg.id !== assistantId),
              };
            });
            if (abortControllersRef.current[repositoryId] === controller) {
              delete abortControllersRef.current[repositoryId];
              setPendingRepos((prev) => ({
                ...prev,
                [repositoryId]: false,
              }));
            }

            // If cancelled due to repo switch, provide retryable error for the unanswered question
            if (reason === 'repo_switch') {
              delete abortReasonsRef.current[repositoryId];
              setErrorMap((prev) => ({
                ...prev,
                [repositoryId]:
                  'Request was interrupted because you switched repositories. Click Retry to continue.',
              }));
            } else {
              delete abortReasonsRef.current[repositoryId];
            }
            return;
          }

          // If a newer request was already started, let it control state
          if (abortControllersRef.current[repositoryId] !== controller) {
            return;
          }
          delete abortControllersRef.current[repositoryId];
          delete abortReasonsRef.current[repositoryId];

          const message =
            err instanceof Error
              ? err.message
              : typeof err === 'object' && err !== null && 'message' in err && typeof (err as any).message === 'string'
              ? (err as any).message
              : 'The assistant could not complete the response. Please try again.';

          // Remove the failed placeholder message
          setConversations((prev) => {
            const repoMsgs = prev[repositoryId] ?? [];
            return {
              ...prev,
              [repositoryId]: repoMsgs.filter((msg) => msg.id !== assistantId),
            };
          });
          setErrorMap((prev) => ({
            ...prev,
            [repositoryId]: message,
          }));
          setPendingRepos((prev) => ({
            ...prev,
            [repositoryId]: false,
          }));
        });
    },
    [conversations, isPending, repositoryId],
  );

  /** Abort the current repository's request and clear its messages, error, and pending status. */
  const clearConversation = useCallback(() => {
    if (!repositoryId) return;

    if (abortControllersRef.current[repositoryId]) {
      abortReasonsRef.current[repositoryId] = 'clear';
      abortControllersRef.current[repositoryId].abort();
      delete abortControllersRef.current[repositoryId];
    }

    setConversations((prev) => ({
      ...prev,
      [repositoryId]: [],
    }));
    setErrorMap((prev) => ({
      ...prev,
      [repositoryId]: null,
    }));
    setPendingRepos((prev) => ({
      ...prev,
      [repositoryId]: false,
    }));
  }, [repositoryId]);

  return { messages, isPending, error, sendMessage, clearConversation };
}
