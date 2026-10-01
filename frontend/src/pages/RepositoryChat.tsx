import { useParams, Link } from 'react-router-dom';
import { useRef, useEffect, useState, useCallback, type KeyboardEvent } from 'react';
import { useRepository } from '../hooks/useRepositories';
import { useRepositoryChat } from '../hooks/useRepositoryChat';
import { LoadingSpinner } from '../components/shared/LoadingSpinner';
import { cn } from '../lib/utils';
import {
  ArrowLeft,
  Send,
  Bot,
  User,
  FileCode,
  MessageSquare,
  RefreshCw,
  Trash2,
} from 'lucide-react';
import type { ChatMessage, ChatSource } from '../types/api';

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function RepositoryChat() {
  const { id } = useParams<{ id: string }>();

  // Repository metadata — reuses the existing query, no new API call.
  const { data: repo, isLoading: repoLoading } = useRepository(id);

  // Chat state — conversation messages live in this hook's local state.
  const { messages, isPending, error, sendMessage, clearConversation } =
    useRepositoryChat(id);

  // Input state — local to this component only.
  const [draft, setDraft] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll: always scroll to bottom when a new message is ADDED to the list
  // (user sends a question, or the assistant placeholder appears).
  // During streaming, only keep scrolling if the user is already near the bottom
  // (within 150 px) — so manually scrolling up to read history isn't disrupted.
  const prevMessageCountRef = useRef(0);
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    const messageCount = messages.length;
    const isNewMessage = messageCount > prevMessageCountRef.current;
    prevMessageCountRef.current = messageCount;

    if (isNewMessage) {
      // A new message was added — always scroll to bottom.
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
      return;
    }

    // Chunk update during streaming — only scroll if already near the bottom.
    const { scrollTop, scrollHeight, clientHeight } = container;
    const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
    if (distanceFromBottom <= 150) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  // Auto-resize the textarea as the user types.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }, [draft]);

  const handleSend = useCallback(() => {
    const trimmed = draft.trim();
    if (!trimmed || isPending) return;
    sendMessage(trimmed);
    setDraft('');
    // Reset textarea height after clearing.
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
  }, [draft, isPending, sendMessage]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  // ------------------------------------------------------------------
  // Loading / Error states for repository metadata
  // ------------------------------------------------------------------

  const repoName = repo?.full_name ?? repo?.name ?? id ?? 'Repository';

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------

  return (
    // Use -m-6 to counter-act AppLayout's p-6 padding so we can fill height.
    // The chat interface needs precise height management to keep the composer
    // pinned at the bottom and the message list scrollable.
    <div className="-m-6 flex flex-col h-[calc(100vh-4rem)]">

      {/* ---------------------------------------------------------------- */}
      {/* Header                                                            */}
      {/* ---------------------------------------------------------------- */}
      <header className="flex-shrink-0 bg-card border-b border-border px-4 py-3 flex items-center gap-3 min-w-0">
        <Link
          to={`/app/repositories/${id}`}
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
          aria-label="Back to Repository Explorer"
        >
          <ArrowLeft className="h-4 w-4" />
          <span className="hidden sm:inline">Repository</span>
        </Link>

        <div className="h-4 w-px bg-border shrink-0" aria-hidden="true" />

        <div className="flex items-center gap-2 min-w-0">
          <Bot className="h-4 w-4 text-primary shrink-0" aria-hidden="true" />
          <div className="min-w-0">
            {repoLoading ? (
              <div className="h-4 w-40 bg-muted animate-pulse rounded" />
            ) : (
              <h1 className="text-sm font-semibold text-foreground truncate">
                {repoName}
              </h1>
            )}
            <p className="text-xs text-muted-foreground">Repository Chat</p>
          </div>
        </div>

        <div className="ml-auto flex items-center gap-2 shrink-0">
          {messages.length > 0 && (
            <button
              onClick={clearConversation}
              className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors px-2 py-1 rounded hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label="Clear conversation"
              title="Clear conversation"
            >
              <Trash2 className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Clear</span>
            </button>
          )}
        </div>
      </header>

      {/* ---------------------------------------------------------------- */}
      {/* Accessibility: polite announcement for completed assistant messages */}
      {/* This is separate from the message list so it only announces once   */}
      {/* per completed message, not on every streaming chunk.               */}
      {/* ---------------------------------------------------------------- */}
      <div aria-live="polite" aria-atomic="true" className="sr-only">
        {(() => {
          const last = [...messages].reverse().find(
            (m) => m.role === 'assistant' && !m.isStreaming && m.content,
          );
          return last ? 'Assistant responded.' : '';
        })()}
      </div>

      {/* ---------------------------------------------------------------- */}
      {/* Messages area                                                     */}
      {/* ---------------------------------------------------------------- */}
      <div
        ref={scrollContainerRef}
        className="flex-1 overflow-y-auto px-4 py-6 space-y-6"
        role="log"
        aria-live="off"
        aria-label="Chat conversation"
      >
        {messages.length === 0 && !isPending ? (
          <EmptyState repoName={repoName} repoLoading={repoLoading} />
        ) : (
          <>
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
            ))}

            {/* Inline error beneath the last message */}
            {error && !isPending && (
              <AssistantError
                message={error}
                onRetry={() => {
                  const lastUser = [...messages]
                    .reverse()
                    .find((m) => m.role === 'user');
                  if (lastUser) sendMessage(lastUser.content);
                }}
              />
            )}

            {/* Show the typing indicator only while waiting for the very first chunk.
                Once the assistant placeholder message exists (isStreaming=true),
                the bubble itself renders the cursor — no separate indicator needed. */}
            {isPending && !messages.some((m) => m.role === 'assistant' && m.isStreaming) && (
              <TypingIndicator />
            )}
          </>
        )}

        {/* Sentinel element for auto-scroll */}
        <div ref={bottomRef} aria-hidden="true" />
      </div>

      {/* ---------------------------------------------------------------- */}
      {/* Composer                                                          */}
      {/* ---------------------------------------------------------------- */}
      <div className="flex-shrink-0 bg-card border-t border-border px-4 py-3">
        <div className="max-w-4xl mx-auto flex items-end gap-3">
          <div className="flex-1 relative">
            <label htmlFor="chat-input" className="sr-only">
              Ask a question about {repoName}
            </label>
            <textarea
              id="chat-input"
              ref={textareaRef}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={`Ask a question about ${repo?.name ?? 'this repository'}…`}
              rows={1}
              disabled={isPending}
              className={cn(
                'w-full resize-none rounded-lg border border-border bg-background px-3 py-2.5 text-sm text-foreground placeholder:text-muted-foreground',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                'disabled:opacity-50 disabled:cursor-not-allowed',
                'leading-relaxed overflow-hidden',
              )}
              aria-label={`Ask a question about ${repoName}`}
              aria-describedby="chat-hint"
            />
            <p id="chat-hint" className="sr-only">
              Press Enter to send, Shift+Enter for a new line.
            </p>
          </div>

          <button
            onClick={handleSend}
            disabled={!draft.trim() || isPending}
            className={cn(
              'inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium transition-colors shrink-0',
              'bg-primary text-primary-foreground',
              'hover:bg-primary/90',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              'disabled:pointer-events-none disabled:opacity-50',
            )}
            aria-label="Send message"
          >
            {isPending ? (
              <LoadingSpinner size="sm" label="Sending…" />
            ) : (
              <Send className="h-4 w-4" aria-hidden="true" />
            )}
            <span className="hidden sm:inline">Send</span>
          </button>
        </div>

        <p className="text-center text-xs text-muted-foreground mt-2 select-none">
          Enter to send · Shift+Enter for new line
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// EmptyState
// ---------------------------------------------------------------------------

function EmptyState({
  repoName,
  repoLoading,
}: {
  repoName: string;
  repoLoading: boolean;
}) {
  return (
    <div className="flex flex-col items-center justify-center h-full min-h-[40vh] text-center gap-4 select-none px-4">
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-primary/10 text-primary">
        <MessageSquare className="h-7 w-7" aria-hidden="true" />
      </div>
      <div className="space-y-1.5">
        <h2 className="text-lg font-semibold text-foreground">
          {repoLoading ? (
            <span className="inline-block h-5 w-48 bg-muted animate-pulse rounded" />
          ) : (
            `Ask about ${repoName}`
          )}
        </h2>
        <p className="text-sm text-muted-foreground max-w-sm">
          Ask questions about code, architecture, authentication, dependencies,
          or anything in this repository. Answers are grounded in the indexed
          source files.
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// MessageBubble — renders a single user or assistant message
// ---------------------------------------------------------------------------

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user';

  return (
    <div
      className={cn(
        'flex items-start gap-3',
        isUser ? 'flex-row-reverse' : 'flex-row',
      )}
    >
      {/* Avatar */}
      <div
        className={cn(
          'flex h-8 w-8 shrink-0 items-center justify-center rounded-full border',
          isUser
            ? 'bg-primary text-primary-foreground border-primary'
            : 'bg-muted text-muted-foreground border-border',
        )}
        aria-hidden="true"
      >
        {isUser ? (
          <User className="h-4 w-4" />
        ) : (
          <Bot className="h-4 w-4" />
        )}
      </div>

      {/* Bubble */}
      <div
        className={cn(
          'flex flex-col gap-2 min-w-0 max-w-[85%] sm:max-w-[75%]',
          isUser ? 'items-end' : 'items-start',
        )}
      >
        <div
          className={cn(
            'rounded-2xl px-4 py-2.5 text-sm leading-relaxed',
            isUser
              ? 'bg-primary text-primary-foreground rounded-tr-sm'
              : 'bg-muted text-foreground rounded-tl-sm',
          )}
        >
          {message.content ? (
            <MessageContent content={message.content} />
          ) : (
            // Empty content before first chunk arrives
            <span className="text-muted-foreground/60 text-xs italic">Thinking…</span>
          )}
          {/* Blinking cursor while the assistant is streaming */}
          {message.isStreaming && (
            <span
              className="inline-block ml-0.5 w-0.5 h-4 align-text-bottom bg-current opacity-70 animate-[blink_1s_step-end_infinite]"
              aria-hidden="true"
            />
          )}
        </div>

        {/* Timestamp — hidden while streaming to avoid layout shift */}
        {!message.isStreaming && (
          <time
            dateTime={message.timestamp}
            className="text-xs text-muted-foreground px-1"
          >
            {new Date(message.timestamp).toLocaleTimeString([], {
              hour: '2-digit',
              minute: '2-digit',
            })}
          </time>
        )}

        {/* Sources — only shown for complete (non-streaming) assistant messages */}
        {!isUser && !message.isStreaming && message.sources && message.sources.length > 0 && (
          <SourceList sources={message.sources} />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// MessageContent — minimal Markdown-like rendering without a library
// Handles: inline code, code blocks, paragraphs.
// ---------------------------------------------------------------------------

function MessageContent({ content }: { content: string }) {
  // Split on fenced code blocks (```...```)
  const segments = content.split(/(```[\s\S]*?```)/g);

  return (
    <div className="space-y-2 whitespace-pre-wrap break-words">
      {segments.map((seg, i) => {
        if (seg.startsWith('```') && seg.endsWith('```')) {
          const inner = seg.slice(3, -3);
          const newline = inner.indexOf('\n');
          const code = newline !== -1 ? inner.slice(newline + 1) : inner;
          return (
            <pre
              key={i}
              className="overflow-x-auto rounded-md bg-background/80 border border-border px-3 py-2 text-xs font-mono text-foreground"
            >
              <code>{code}</code>
            </pre>
          );
        }
        // Inline code: wrap `backtick` spans
        const parts = seg.split(/(`[^`]+`)/g);
        return (
          <span key={i}>
            {parts.map((part, j) =>
              part.startsWith('`') && part.endsWith('`') ? (
                <code
                  key={j}
                  className="rounded bg-background/80 border border-border px-1 py-0.5 font-mono text-xs"
                >
                  {part.slice(1, -1)}
                </code>
              ) : (
                <span key={j}>{part}</span>
              ),
            )}
          </span>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SourceList — renders the cited repository sources
// ---------------------------------------------------------------------------

function SourceList({ sources }: { sources: ChatSource[] }) {
  return (
    <div className="w-full space-y-1.5">
      <p className="text-xs font-medium text-muted-foreground px-1">Sources</p>
      <ul className="space-y-1.5" aria-label="Referenced sources">
        {sources.map((src, i) => (
          <li
            key={i}
            className="rounded-md border border-border bg-card px-3 py-2 text-xs space-y-0.5"
          >
            <div className="flex items-start gap-2 min-w-0">
              <FileCode
                className="h-3.5 w-3.5 text-muted-foreground shrink-0 mt-0.5"
                aria-hidden="true"
              />
              <span className="font-mono text-foreground break-all">
                {src.file_path}
              </span>
            </div>
            {src.line_start != null && (
              <p className="text-muted-foreground pl-5.5">
                Lines {src.line_start}
                {src.line_end != null && src.line_end !== src.line_start
                  ? `–${src.line_end}`
                  : ''}
              </p>
            )}
            {src.symbol && (
              <p className="text-muted-foreground pl-5.5 font-mono">
                {src.symbol}
              </p>
            )}
            {src.snippet && (
              <pre className="mt-1 overflow-x-auto rounded bg-muted/50 px-2 py-1 font-mono text-muted-foreground">
                {src.snippet}
              </pre>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// TypingIndicator — animated dots while the assistant is responding
// ---------------------------------------------------------------------------

function TypingIndicator() {
  return (
    <div className="flex items-start gap-3" role="status" aria-label="Assistant is typing">
      <div
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border bg-muted text-muted-foreground border-border"
        aria-hidden="true"
      >
        <Bot className="h-4 w-4" />
      </div>
      <div className="bg-muted rounded-2xl rounded-tl-sm px-4 py-3 flex items-center gap-1.5">
        <span
          className="h-2 w-2 rounded-full bg-muted-foreground/50 animate-bounce"
          style={{ animationDelay: '0ms' }}
        />
        <span
          className="h-2 w-2 rounded-full bg-muted-foreground/50 animate-bounce"
          style={{ animationDelay: '160ms' }}
        />
        <span
          className="h-2 w-2 rounded-full bg-muted-foreground/50 animate-bounce"
          style={{ animationDelay: '320ms' }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AssistantError — shown when a chat request fails
// ---------------------------------------------------------------------------

function AssistantError({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="flex items-start gap-3">
      <div
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-destructive/40 bg-destructive/10 text-destructive"
        aria-hidden="true"
      >
        <Bot className="h-4 w-4" />
      </div>
      <div className="flex flex-col gap-2 min-w-0 max-w-[85%] sm:max-w-[75%]">
        <div
          role="alert"
          className="rounded-2xl rounded-tl-sm border border-destructive/30 bg-destructive/10 px-4 py-2.5 text-sm text-destructive"
        >
          {message}
        </div>
        <button
          onClick={onRetry}
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors px-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
          aria-label="Retry last message"
        >
          <RefreshCw className="h-3 w-3" aria-hidden="true" />
          Retry
        </button>
      </div>
    </div>
  );
}
