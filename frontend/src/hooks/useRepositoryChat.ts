/**
 * useRepositoryChat — repository chat state, streaming and server-side history.
 *
 * Architecture:
 *
 * 1. Server-side history.
 *    Each repository has saved conversations on the backend. The first question of a new
 *    chat creates one; later questions send only `conversation_id` and the backend loads the
 *    history itself and stores every exchange. The active conversation id is remembered in
 *    localStorage, so a reload (or another tab) restores the conversation.
 *    If conversations cannot be created (older backend, offline), the hook falls back to the
 *    previous behaviour: history is kept in memory and sent with each request.
 *
 * 2. Streaming.
 *    Answers are requested from POST /chat/stream. The assistant bubble shows the text as it
 *    is generated plus the current stage (retrieving → generating → grounding). Citations
 *    arrive with the final `done` event, after grounding validation. If streaming is not
 *    available the hook falls back to POST /chat (one complete response).
 *
 * 3. Cancellation.
 *    Switching repositories, starting a new chat or unmounting aborts the in-flight request.
 */
import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import axios from 'axios';
import {
  askRepositoryQuestion,
  streamRepositoryQuestion,
  ChatStreamUnavailableError,
  listConversations,
  createConversation,
  getConversation,
  deleteConversation as deleteConversationApi,
} from '../services/chat';
import type {
  ChatMessage,
  ChatHistoryMessage,
  ChatMode,
  ChatConversationSummary,
  RepositoryChatRequest,
  RepositoryChatResponse,
  StoredChatMessage,
} from '../types/api';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function newMessageId(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2);
}

/**
 * Convert completed UI messages into the history format expected by the backend.
 * Only used when no server-side conversation is available.
 */
function buildHistory(messages: ChatMessage[]): ChatHistoryMessage[] {
  const completed = messages.filter((m) => !m.isStreaming && m.content.trim().length > 0);
  let validTurns = completed;
  while (validTurns.length > 0 && validTurns[validTurns.length - 1].role === 'user') {
    validTurns = validTurns.slice(0, -1);
  }
  return validTurns.slice(-50).map((m) => ({ role: m.role, content: m.content }));
}

function fromStored(m: StoredChatMessage): ChatMessage {
  return {
    id: m.id,
    role: m.role,
    content: m.content,
    timestamp: m.created_at ?? new Date().toISOString(),
    sources: m.sources ?? [],
    confidence: m.confidence ?? undefined,
    isStreaming: false,
    mode: m.mode ?? 'normal',
    agentMetadata: m.agent_metadata ?? null,
  };
}

const STORAGE_PREFIX = 'repo-chat:conversation:';

function readActiveConversation(repositoryId: string): string | null {
  try {
    return localStorage.getItem(STORAGE_PREFIX + repositoryId);
  } catch {
    return null;
  }
}

function writeActiveConversation(repositoryId: string, conversationId: string | null): void {
  try {
    if (conversationId) localStorage.setItem(STORAGE_PREFIX + repositoryId, conversationId);
    else localStorage.removeItem(STORAGE_PREFIX + repositoryId);
  } catch {
    // storage unavailable (private mode, tests) — history still works for this session
  }
}

function errorMessage(err: unknown): string {
  if (err instanceof Error && err.message) return err.message;
  if (typeof err === 'object' && err !== null && 'message' in err) {
    const msg = (err as { message?: unknown }).message;
    if (typeof msg === 'string' && msg) return msg;
  }
  return 'The assistant could not complete the response. Please try again.';
}

function isCancellation(err: unknown, signal: AbortSignal): boolean {
  return (
    signal.aborted ||
    axios.isCancel(err) ||
    (err instanceof Error && (err.name === 'CanceledError' || err.name === 'AbortError')) ||
    (typeof err === 'object' && err !== null && 'message' in err && (err as { message?: string }).message === 'canceled')
  );
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
  /** Currently selected chat mode ('normal' or 'agentic'). */
  mode: ChatMode;
  setMode: (mode: ChatMode) => void;
  /** Send a question. No-op while isPending. Optional mode override. */
  sendMessage: (question: string, overrideMode?: ChatMode) => void;
  /** Start a new, empty conversation (the old one stays saved on the server). */
  clearConversation: () => void;
  /** Saved conversations for this repository, newest first. */
  conversations: ChatConversationSummary[];
  /** Server-side id of the conversation being shown, or null for a new/unsaved chat. */
  activeConversationId: string | null;
  /** True while a saved conversation's messages are loading. */
  isLoadingHistory: boolean;
  /** Open a saved conversation. */
  selectConversation: (conversationId: string) => void;
  /** Delete a saved conversation. */
  deleteConversation: (conversationId: string) => void;
}

type AbortReason = 'repo_switch' | 'clear' | 'unmount' | 'superseded';

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useRepositoryChat(repositoryId: string | undefined): UseRepositoryChatReturn {
  const [threads, setThreads] = useState<Record<string, ChatMessage[]>>({});
  const [pendingRepos, setPendingRepos] = useState<Record<string, boolean>>({});
  const [errorMap, setErrorMap] = useState<Record<string, string | null>>({});
  const [mode, setMode] = useState<ChatMode>('normal');
  const [conversationIds, setConversationIds] = useState<Record<string, string | null>>({});
  const [conversationLists, setConversationLists] = useState<Record<string, ChatConversationSummary[]>>({});
  const [loadingHistory, setLoadingHistory] = useState<Record<string, boolean>>({});

  const abortControllersRef = useRef<Record<string, AbortController>>({});
  const abortReasonsRef = useRef<Record<string, AbortReason>>({});
  // Repositories whose saved state was already restored in this hook instance.
  const restoredRef = useRef<Set<string>>(new Set());
  // Whether the server supports conversations; false after the first failure.
  const conversationsSupportedRef = useRef<boolean>(true);

  const messages = useMemo(
    () => (repositoryId ? threads[repositoryId] ?? [] : []),
    [repositoryId, threads],
  );
  const isPending = Boolean(repositoryId && pendingRepos[repositoryId]);
  const error = repositoryId ? errorMap[repositoryId] ?? null : null;
  const activeConversationId = repositoryId ? conversationIds[repositoryId] ?? null : null;
  const conversations = useMemo(
    () => (repositoryId ? conversationLists[repositoryId] ?? [] : []),
    [repositoryId, conversationLists],
  );
  const isLoadingHistory = Boolean(repositoryId && loadingHistory[repositoryId]);

  const setActiveConversation = useCallback((repoId: string, conversationId: string | null) => {
    setConversationIds((prev) => ({ ...prev, [repoId]: conversationId }));
    writeActiveConversation(repoId, conversationId);
  }, []);

  const refreshConversationList = useCallback(async (repoId: string) => {
    if (!conversationsSupportedRef.current) return;
    try {
      const items = await listConversations(repoId);
      setConversationLists((prev) => ({ ...prev, [repoId]: items }));
    } catch {
      // History list is a convenience; chat keeps working without it.
    }
  }, []);

  const loadConversation = useCallback(
    async (repoId: string, conversationId: string) => {
      setLoadingHistory((prev) => ({ ...prev, [repoId]: true }));
      try {
        const detail = await getConversation(repoId, conversationId);
        setThreads((prev) => ({ ...prev, [repoId]: detail.messages.map(fromStored) }));
        setActiveConversation(repoId, detail.id);
        setErrorMap((prev) => ({ ...prev, [repoId]: null }));
      } catch {
        // Deleted or not ours any more: forget it and start fresh.
        setActiveConversation(repoId, null);
      } finally {
        setLoadingHistory((prev) => ({ ...prev, [repoId]: false }));
      }
    },
    [setActiveConversation],
  );

  // Restore the last active conversation and load the list when a repository is opened.
  useEffect(() => {
    if (!repositoryId || restoredRef.current.has(repositoryId)) return;
    restoredRef.current.add(repositoryId);
    void refreshConversationList(repositoryId);
    const saved = readActiveConversation(repositoryId);
    if (saved) void loadConversation(repositoryId, saved);
  }, [repositoryId, refreshConversationList, loadConversation]);

  // Abort the previous repository's request when navigating to another repository.
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

  // Abort all active requests on unmount.
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
      Object.keys(controllers).forEach((id) => delete controllers[id]);
    };
  }, []);

  const sendMessage = useCallback(
    (question: string, overrideMode?: ChatMode) => {
      const trimmed = question.trim();
      if (!trimmed || isPending || !repositoryId) return;
      const repoId = repositoryId;
      const activeMode = overrideMode ?? mode;

      if (abortControllersRef.current[repoId]) {
        abortReasonsRef.current[repoId] = 'superseded';
        abortControllersRef.current[repoId].abort();
        delete abortControllersRef.current[repoId];
      }
      const controller = new AbortController();
      abortControllersRef.current[repoId] = controller;

      const currentMessages = threads[repoId] ?? [];
      const lastMessage = currentMessages[currentMessages.length - 1];
      const isLastUnansweredUser = Boolean(lastMessage && lastMessage.role === 'user');
      const clientHistory = buildHistory(isLastUnansweredUser ? currentMessages.slice(0, -1) : currentMessages);

      const userMessage: ChatMessage = {
        id: newMessageId(),
        role: 'user',
        content: trimmed,
        timestamp: new Date().toISOString(),
        sources: [],
        isStreaming: false,
        mode: activeMode,
      };
      const assistantId = newMessageId();
      const assistantPlaceholder: ChatMessage = {
        id: assistantId,
        role: 'assistant',
        content: '',
        timestamp: new Date().toISOString(),
        sources: [],
        isStreaming: true,
        mode: activeMode,
        streamStage: null,
      };

      setThreads((prev) => {
        const existing = prev[repoId] ?? [];
        const last = existing[existing.length - 1];
        if (last && last.role === 'user') {
          if (last.content === trimmed) {
            return { ...prev, [repoId]: [...existing, assistantPlaceholder] };
          }
          return { ...prev, [repoId]: [...existing.slice(0, -1), userMessage, assistantPlaceholder] };
        }
        return { ...prev, [repoId]: [...existing, userMessage, assistantPlaceholder] };
      });
      setPendingRepos((prev) => ({ ...prev, [repoId]: true }));
      setErrorMap((prev) => ({ ...prev, [repoId]: null }));

      const patchAssistant = (patch: Partial<ChatMessage>) => {
        if (controller.signal.aborted || abortControllersRef.current[repoId] !== controller) return;
        setThreads((prev) => ({
          ...prev,
          [repoId]: (prev[repoId] ?? []).map((msg) => (msg.id === assistantId ? { ...msg, ...patch } : msg)),
        }));
      };

      const run = async (): Promise<RepositoryChatResponse> => {
        // 1. Make sure the exchange has a server-side conversation to be saved in.
        let conversationId = conversationIds[repoId] ?? null;
        if (!conversationId && conversationsSupportedRef.current) {
          try {
            const created = await createConversation(repoId);
            conversationId = created.id;
            setActiveConversation(repoId, created.id);
          } catch {
            conversationsSupportedRef.current = false; // fall back to client-side history
          }
        }
        if (controller.signal.aborted) throw new DOMException('Aborted', 'AbortError');

        const payload: RepositoryChatRequest = conversationId
          ? { question: trimmed, history: [], mode: activeMode, conversation_id: conversationId }
          : { question: trimmed, history: clientHistory, mode: activeMode };

        // 2. Stream the answer; fall back to the complete-response endpoint if streaming is unavailable.
        try {
          return await streamRepositoryQuestion(
            repoId,
            payload,
            {
              onStatus: (stage) => patchAssistant({ streamStage: stage }),
              onAnswer: (text) => patchAssistant({ content: text }),
            },
            controller.signal,
          );
        } catch (err) {
          if (err instanceof ChatStreamUnavailableError) {
            return askRepositoryQuestion(repoId, payload, controller.signal);
          }
          throw err;
        }
      };

      run()
        .then((response) => {
          if (controller.signal.aborted || abortControllersRef.current[repoId] !== controller) return;
          delete abortControllersRef.current[repoId];
          delete abortReasonsRef.current[repoId];
          setThreads((prev) => ({
            ...prev,
            [repoId]: (prev[repoId] ?? []).map((msg) =>
              msg.id === assistantId
                ? {
                    ...msg,
                    content: response.answer,
                    sources: response.sources ?? [],
                    confidence: response.confidence,
                    isStreaming: false,
                    streamStage: null,
                    mode: response.agent_metadata?.mode ?? activeMode,
                    agentMetadata: response.agent_metadata ?? null,
                  }
                : msg,
            ),
          }));
          setPendingRepos((prev) => ({ ...prev, [repoId]: false }));
          void refreshConversationList(repoId);
        })
        .catch((err: unknown) => {
          const reason = abortReasonsRef.current[repoId];
          if (isCancellation(err, controller.signal)) {
            setThreads((prev) => ({
              ...prev,
              [repoId]: (prev[repoId] ?? []).filter((msg) => msg.id !== assistantId),
            }));
            if (abortControllersRef.current[repoId] === controller) {
              delete abortControllersRef.current[repoId];
              setPendingRepos((prev) => ({ ...prev, [repoId]: false }));
            }
            delete abortReasonsRef.current[repoId];
            if (reason === 'repo_switch') {
              setErrorMap((prev) => ({
                ...prev,
                [repoId]: 'Request was interrupted because you switched repositories. Click Retry to continue.',
              }));
            }
            return;
          }
          if (abortControllersRef.current[repoId] !== controller) return;
          delete abortControllersRef.current[repoId];
          delete abortReasonsRef.current[repoId];
          setThreads((prev) => ({
            ...prev,
            [repoId]: (prev[repoId] ?? []).filter((msg) => msg.id !== assistantId),
          }));
          setErrorMap((prev) => ({ ...prev, [repoId]: errorMessage(err) }));
          setPendingRepos((prev) => ({ ...prev, [repoId]: false }));
        });
    },
    [threads, isPending, repositoryId, mode, conversationIds, setActiveConversation, refreshConversationList],
  );

  const abortCurrent = useCallback((repoId: string, reason: AbortReason) => {
    if (abortControllersRef.current[repoId]) {
      abortReasonsRef.current[repoId] = reason;
      abortControllersRef.current[repoId].abort();
      delete abortControllersRef.current[repoId];
    }
    setPendingRepos((prev) => ({ ...prev, [repoId]: false }));
  }, []);

  /** Start a new chat. The previous conversation stays saved and can be reopened. */
  const clearConversation = useCallback(() => {
    if (!repositoryId) return;
    abortCurrent(repositoryId, 'clear');
    setThreads((prev) => ({ ...prev, [repositoryId]: [] }));
    setErrorMap((prev) => ({ ...prev, [repositoryId]: null }));
    setActiveConversation(repositoryId, null);
  }, [repositoryId, abortCurrent, setActiveConversation]);

  const selectConversation = useCallback(
    (conversationId: string) => {
      if (!repositoryId || conversationId === conversationIds[repositoryId]) return;
      abortCurrent(repositoryId, 'clear');
      void loadConversation(repositoryId, conversationId);
    },
    [repositoryId, conversationIds, abortCurrent, loadConversation],
  );

  const deleteConversation = useCallback(
    (conversationId: string) => {
      if (!repositoryId) return;
      const repoId = repositoryId;
      void (async () => {
        try {
          await deleteConversationApi(repoId, conversationId);
        } catch (err) {
          setErrorMap((prev) => ({ ...prev, [repoId]: errorMessage(err) }));
          return;
        }
        setConversationLists((prev) => ({
          ...prev,
          [repoId]: (prev[repoId] ?? []).filter((c) => c.id !== conversationId),
        }));
        if (conversationIds[repoId] === conversationId) {
          abortCurrent(repoId, 'clear');
          setThreads((prev) => ({ ...prev, [repoId]: [] }));
          setActiveConversation(repoId, null);
        }
      })();
    },
    [repositoryId, conversationIds, abortCurrent, setActiveConversation],
  );

  return {
    messages,
    isPending,
    error,
    mode,
    setMode,
    sendMessage,
    clearConversation,
    conversations,
    activeConversationId,
    isLoadingHistory,
    selectConversation,
    deleteConversation,
  };
}
