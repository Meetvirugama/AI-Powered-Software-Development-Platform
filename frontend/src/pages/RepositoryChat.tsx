import { useParams, Link, useSearchParams } from 'react-router-dom';
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
  Copy,
  Check,
  ExternalLink,
  Layers,
  X,
} from 'lucide-react';
import type { ChatMessage, ChatSource, ChatConfidence } from '../types/api';

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

/**
 * Render chat for the route's repository, with cited sources linked to explorer
 * files and line ranges. A nonempty `file` query parameter prefills and focuses
 * the composer on arrival or change; removing it leaves the draft unchanged.
 */
export function RepositoryChat() {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();

  // Repository metadata — reuses the existing query, no new API call.
  const { data: repo, isLoading: repoLoading } = useRepository(id);

  // Chat state — conversation messages live in this hook's local state.
  const { messages, isPending, error, sendMessage, clearConversation } =
    useRepositoryChat(id);

  const fileParam = searchParams.get('file');

  // Input state — initialized with ?file= query parameter if present.
  const [draft, setDraft] = useState(() => {
    return fileParam ? `Can you explain the structure and logic of \`${fileParam}\`?` : '';
  });
  const [prevFileParam, setPrevFileParam] = useState(fileParam);
  if (fileParam !== prevFileParam) {
    setPrevFileParam(fileParam);
    if (fileParam) {
      setDraft(`Can you explain the structure and logic of \`${fileParam}\`?`);
    }
  }

  const [activeSource, setActiveSource] = useState<ChatSource | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (fileParam) {
      textareaRef.current?.focus();
    }
  }, [fileParam]);



  // Auto-scroll: always scroll to bottom when a new message is ADDED to the list
  const prevMessageCountRef = useRef(0);
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    const messageCount = messages.length;
    const isNewMessage = messageCount > prevMessageCountRef.current;
    prevMessageCountRef.current = messageCount;

    if (isNewMessage) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
      return;
    }

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

  const repoName = repo?.full_name ?? repo?.name ?? id ?? 'Repository';

  // Gather all sources across conversation for reference
  const allSources = messages
    .filter((m) => m.role === 'assistant' && m.sources && m.sources.length > 0)
    .flatMap((m) => m.sources ?? []);

  return (
    <div className="flex flex-col h-full w-full bg-background overflow-hidden relative">
      {/* ---------------------------------------------------------------- */}
      {/* Header                                                            */}
      {/* ---------------------------------------------------------------- */}
      <header className="flex-shrink-0 bg-card border-b border-border px-4 py-3 flex items-center gap-3 min-w-0">
        <Link
          to={`/app/repositories/${id}`}
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded px-2 py-1 hover:bg-accent"
          aria-label="Back to Repository Explorer"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Explorer</span>
        </Link>

        <div className="h-4 w-px bg-border shrink-0" aria-hidden="true" />

        <div className="flex items-center gap-2 min-w-0">
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-primary/10 text-primary shrink-0">
            <Bot className="h-3.5 w-3.5" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            {repoLoading ? (
              <div className="h-4 w-36 bg-muted animate-pulse rounded" />
            ) : (
              <h1 className="text-sm font-semibold text-foreground truncate">
                {repoName}
              </h1>
            )}
            <p className="text-[10px] text-muted-foreground font-mono">Grounded Code Conversation</p>
          </div>
        </div>

        <div className="ml-auto flex items-center gap-2 shrink-0">
          {allSources.length > 0 && (
            <button
              onClick={() => setActiveSource(allSources[0])}
              className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors px-2 py-1 rounded border border-border hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              title="Inspect cited sources"
            >
              <Layers className="h-3.5 w-3.5 text-primary" />
              <span className="hidden sm:inline">Evidence ({allSources.length})</span>
            </button>
          )}

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
              <MessageBubble
                key={msg.id}
                message={msg}
                onSelectSource={(src) => setActiveSource(src)}
              />
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

            {isPending && !messages.some((m) => m.role === 'assistant' && m.isStreaming) && (
              <TypingIndicator />
            )}
          </>
        )}

        {/* Sentinel element for auto-scroll */}
        <div ref={bottomRef} aria-hidden="true" />
      </div>

      {/* ---------------------------------------------------------------- */}
      {/* Evidence Side Drawer / Inspector                                  */}
      {/* ---------------------------------------------------------------- */}
      {activeSource && (
        <div className="absolute right-0 top-14 bottom-0 w-80 sm:w-96 bg-card border-l border-border shadow-2xl z-30 flex flex-col animate-in slide-in-from-right duration-200">
          <div className="flex items-center justify-between px-4 py-3 border-b border-border">
            <div className="flex items-center gap-2">
              <Layers className="h-4 w-4 text-primary" />
              <h3 className="text-xs font-semibold uppercase tracking-wider text-foreground">Cited Evidence</h3>
            </div>
            <button
              onClick={() => setActiveSource(null)}
              className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
              aria-label="Close evidence panel"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="p-4 flex-1 overflow-y-auto space-y-4">
            <div className="space-y-1">
              <span className="text-[10px] text-muted-foreground uppercase font-mono">File Path</span>
              <p className="font-mono text-xs text-foreground bg-muted p-2 rounded border border-border break-all">
                {activeSource.file}
              </p>
            </div>

            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="space-y-1">
                <span className="text-[10px] text-muted-foreground uppercase font-mono">Lines</span>
                <p className="font-mono text-foreground font-semibold">
                  {activeSource.start_line} – {activeSource.end_line}
                </p>
              </div>
              {activeSource.symbol && (
                <div className="space-y-1">
                  <span className="text-[10px] text-muted-foreground uppercase font-mono">Symbol</span>
                  <p className="font-mono text-primary truncate" title={activeSource.symbol}>
                    {activeSource.symbol}
                  </p>
                </div>
              )}
            </div>

            <div className="pt-3 border-t border-border">
              <Link
                to={`/app/repositories/${id}?file=${encodeURIComponent(activeSource.file)}&start=${activeSource.start_line}&end=${activeSource.end_line}${activeSource.symbol ? `&symbol=${encodeURIComponent(activeSource.symbol)}` : ''}`}
                className="w-full inline-flex items-center justify-center gap-2 px-3 py-2 text-xs font-medium rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
              >
                <ExternalLink className="h-3.5 w-3.5" />
                View in Repository Explorer
              </Link>
            </div>
          </div>
        </div>
      )}

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
      <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 border border-primary/20 text-primary">
        <MessageSquare className="h-6 w-6" aria-hidden="true" />
      </div>
      <div className="space-y-1.5">
        <h2 className="text-base font-semibold text-foreground">
          {repoLoading ? (
            <span className="inline-block h-5 w-48 bg-muted animate-pulse rounded" />
          ) : (
            `Ask about ${repoName}`
          )}
        </h2>
        <p className="text-xs text-muted-foreground max-w-sm">
          Ask questions about code, architecture, authentication, dependencies,
          or symbols. Answers are grounded in the indexed source files.
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// MessageBubble — renders a single user or assistant message
// ---------------------------------------------------------------------------

function MessageBubble({
  message,
  onSelectSource,
}: {
  message: ChatMessage;
  onSelectSource?: (src: ChatSource) => void;
}) {
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
          'flex h-7 w-7 shrink-0 items-center justify-center rounded-full border',
          isUser
            ? 'bg-primary text-primary-foreground border-primary'
            : 'bg-muted text-muted-foreground border-border',
        )}
        aria-hidden="true"
      >
        {isUser ? (
          <User className="h-3.5 w-3.5" />
        ) : (
          <Bot className="h-3.5 w-3.5" />
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
              : 'bg-card border border-border text-foreground rounded-tl-sm shadow-sm',
          )}
        >
          {message.content ? (
            <MessageContent content={message.content} />
          ) : (
            <span className="text-muted-foreground/60 text-xs italic">Thinking…</span>
          )}
          {message.isStreaming && (
            <span
              className="inline-block ml-0.5 w-0.5 h-4 align-text-bottom bg-current opacity-70 animate-[blink_1s_step-end_infinite]"
              aria-hidden="true"
            />
          )}
        </div>

        {/* Timestamp */}
        {!message.isStreaming && (
          <time
            dateTime={message.timestamp}
            className="text-[11px] text-muted-foreground px-1 font-mono"
          >
            {new Date(message.timestamp).toLocaleTimeString([], {
              hour: '2-digit',
              minute: '2-digit',
            })}
          </time>
        )}

        {/* Confidence badge */}
        {!isUser && !message.isStreaming && message.confidence && (
          <ConfidenceBadge confidence={message.confidence} />
        )}

        {/* Sources */}
        {!isUser && !message.isStreaming && message.sources && message.sources.length > 0 && (
          <SourceList sources={message.sources} onSelectSource={onSelectSource} />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// MessageContent — renders markdown paragraphs and CodeBlock with Copy
// ---------------------------------------------------------------------------

function MessageContent({ content }: { content: string }) {
  const segments = content.split(/(```[\s\S]*?```)/g);

  return (
    <div className="space-y-2 whitespace-pre-wrap break-words">
      {segments.map((seg, i) => {
        if (seg.startsWith('```') && seg.endsWith('```')) {
          const inner = seg.slice(3, -3);
          const newline = inner.indexOf('\n');
          const code = newline !== -1 ? inner.slice(newline + 1) : inner;
          return <CodeBlock key={i} code={code} />;
        }
        const parts = seg.split(/(`[^`]+`)/g);
        return (
          <span key={i}>
            {parts.map((part, j) =>
              part.startsWith('`') && part.endsWith('`') ? (
                <code
                  key={j}
                  className="rounded bg-muted/80 border border-border px-1.5 py-0.5 font-mono text-xs text-primary"
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

/** Render code with a copy action and temporary success or failure feedback. */
function CodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, []);

  /** Copy the code, catching clipboard failures and showing feedback in the button. */
  const handleCopy = async () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setCopyFailed(false);
      timeoutRef.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopyFailed(true);
      timeoutRef.current = setTimeout(() => setCopyFailed(false), 2500);
    }
  };

  return (
    <div className="relative group rounded-lg border border-border bg-background/95 overflow-hidden my-2.5">
      <div className="flex items-center justify-between px-3 py-1.5 bg-muted/40 border-b border-border text-[11px] font-mono text-muted-foreground">
        <span>source code</span>
        <button
          onClick={handleCopy}
          className="inline-flex items-center gap-1 hover:text-foreground transition-colors px-1.5 py-0.5 rounded hover:bg-background/80"
          title="Copy code"
        >
          {copied ? (
            <>
              <Check className="h-3 w-3 text-emerald-400" />
              <span className="text-emerald-400">Copied</span>
            </>
          ) : copyFailed ? (
            <>
              <X className="h-3 w-3 text-destructive" />
              <span className="text-destructive">Failed to copy</span>
            </>
          ) : (
            <>
              <Copy className="h-3 w-3" />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>
      <pre className="overflow-x-auto p-3 text-xs font-mono text-foreground leading-relaxed">
        <code>{code}</code>
      </pre>
    </div>
  );
}


// ---------------------------------------------------------------------------
// ConfidenceBadge — shows backend-provided confidence
// ---------------------------------------------------------------------------

const confidenceConfig: Record<ChatConfidence, { label: string; className: string }> = {
  high:   { label: 'High confidence',   className: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' },
  medium: { label: 'Medium confidence', className: 'bg-amber-500/10  text-amber-400  border-amber-500/30'  },
  low:    { label: 'Low confidence',    className: 'bg-muted         text-muted-foreground border-border'   },
};

function ConfidenceBadge({ confidence }: { confidence: ChatConfidence }) {
  const { label, className } = confidenceConfig[confidence];
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-mono font-medium ${className}`}
      title={`Answer confidence: ${confidence}`}
      aria-label={label}
    >
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// SourceList — renders cited repository sources with click-to-inspect
// ---------------------------------------------------------------------------

function SourceList({
  sources,
  onSelectSource,
}: {
  sources: ChatSource[];
  onSelectSource?: (src: ChatSource) => void;
}) {
  return (
    <div className="w-full space-y-1.5">
      <p className="text-[11px] font-medium text-muted-foreground px-1 uppercase font-mono tracking-wider">
        Cited Sources
      </p>
      <ul className="space-y-1.5" aria-label="Referenced sources">
        {sources.map((src, i) => (
          <li key={i}>
            <button
              onClick={() => onSelectSource?.(src)}
              className="w-full text-left rounded-lg border border-border bg-card/80 hover:bg-accent/60 transition-colors px-3 py-2 text-xs space-y-1 group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <div className="flex items-center justify-between gap-2 min-w-0">
                <div className="flex items-center gap-1.5 min-w-0">
                  <FileCode
                    className="h-3.5 w-3.5 text-primary shrink-0"
                    aria-hidden="true"
                  />
                  <span className="font-mono text-foreground font-medium group-hover:text-primary transition-colors truncate">
                    {src.file}
                  </span>
                </div>
                <ExternalLink className="h-3 w-3 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
              </div>
              <div className="flex items-center gap-2 text-[11px] text-muted-foreground font-mono pl-5">
                <span>Lines {src.start_line}{src.end_line !== src.start_line ? `–${src.end_line}` : ''}</span>
                {src.symbol && (
                  <>
                    <span>·</span>
                    <span className="text-primary truncate">{src.symbol}</span>
                  </>
                )}
              </div>
            </button>
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
