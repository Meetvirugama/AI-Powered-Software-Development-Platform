import { useState, useMemo, useRef, useEffect } from 'react';
import { Copy, Check, Hash, Layers, X, Target, Sparkles, FileCode, Code } from 'lucide-react';
import { LoadingSpinner } from '../shared/LoadingSpinner';
import { useRepositoryFileContent } from '../../hooks/useRepositories';
import { cn } from '../../lib/utils';
import { resolveFileType } from '../../lib/fileLanguage';
import { useVirtualRange } from '../../utils/virtualizationAndSyntax';
import type { RepositoryFile, CodeSymbol } from '../../types/api';
import type { AnalysisTarget, SourceReference } from '../../types/analysis';

export interface CodeViewerAction {
  label: string;
  onClick: () => void;
  isPending?: boolean;
  icon?: React.ReactNode;
  disabled?: boolean;
  disabledReason?: string;
}

export interface CodeViewerProps {
  repositoryId: string;
  file: RepositoryFile;
  activeTarget: AnalysisTarget;
  onTargetChange: (target: AnalysisTarget) => void;
  highlightedSource?: SourceReference | null;
  onClearHighlightedSource?: () => void;
  action?: CodeViewerAction;
  isAnalyzing?: boolean;
  className?: string;
}

// Lightweight, safe syntax tokenizer (pure React text nodes, no raw HTML injection)

type TokenType = 'keyword' | 'type' | 'string' | 'number' | 'comment' | 'function' | 'plain';

interface Token {
  text: string;
  type: TokenType;
}

const JS_TS_KEYWORDS = new Set([
  'function', 'const', 'let', 'var', 'return', 'if', 'else', 'for', 'while',
  'do', 'switch', 'case', 'default', 'break', 'continue', 'try', 'catch',
  'finally', 'throw', 'new', 'typeof', 'instanceof', 'void', 'delete',
  'import', 'export', 'from', 'as', 'class', 'extends', 'implements',
  'interface', 'type', 'enum', 'public', 'private', 'protected', 'static',
  'readonly', 'async', 'await', 'yield', 'true', 'false', 'null', 'undefined',
]);

const PYTHON_KEYWORDS = new Set([
  'def', 'class', 'import', 'from', 'return', 'if', 'elif', 'else', 'while',
  'for', 'in', 'try', 'except', 'finally', 'raise', 'with', 'as', 'assert',
  'pass', 'break', 'continue', 'async', 'await', 'yield', 'lambda', 'global',
  'nonlocal', 'True', 'False', 'None', 'self', 'cls',
]);

const RUST_GO_KEYWORDS = new Set([
  'fn', 'let', 'mut', 'pub', 'struct', 'enum', 'impl', 'trait', 'use', 'mod',
  'match', 'if', 'else', 'for', 'while', 'loop', 'return', 'async', 'await',
  'where', 'type', 'const', 'static', 'ref', 'move', 'self', 'Self', 'crate',
  'super', 'true', 'false', 'package', 'func', 'var', 'interface', 'defer',
  'go', 'chan', 'select', 'switch', 'case', 'default', 'range', 'nil', 'struct',
]);

function tokenizeLine(line: string, language: string | null): Token[] {
  if (!line) return [{ text: '', type: 'plain' }];

  const lang = (language ?? '').toLowerCase();
  const isPython = lang.includes('python') || lang.endsWith('.py');
  const isJsTs =
    lang.includes('typescript') ||
    lang.includes('javascript') ||
    lang.includes('tsx') ||
    lang.includes('jsx');
  const isRustOrGo = lang === 'rust' || lang === 'go' || lang.endsWith('.rs') || lang.endsWith('.go');
  const isHtmlOrXml = lang === 'html' || lang === 'xml' || lang === 'svg' || lang.endsWith('.html');
  const isJson = lang.includes('json');
  const isMarkdown = lang.includes('markdown') || lang.endsWith('.md');

  // Single-line comment check
  const trimmed = line.trimStart();
  if ((isPython || lang === 'yaml' || lang === 'shell' || lang === 'toml') && trimmed.startsWith('#')) {
    return [{ text: line, type: 'comment' }];
  }
  if ((isJsTs || isRustOrGo) && trimmed.startsWith('//')) {
    return [{ text: line, type: 'comment' }];
  }
  if (isMarkdown && trimmed.startsWith('#')) {
    return [{ text: line, type: 'keyword' }];
  }
  if (isHtmlOrXml && trimmed.startsWith('<!--')) {
    return [{ text: line, type: 'comment' }];
  }

  // Tokenize using regex matches
  const tokens: Token[] = [];
  // Tokenizer regex: matches comments, strings, identifiers/words, numbers, symbols
  const regex = isPython
    ? /(#.*$)|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(\b\d+(?:\.\d+)?\b)|(\b[a-zA-Z_]\w*\b)|([^\s\w"']+)|(\s+)/g
    : isJsTs || isRustOrGo
    ? /(\/\/.*$)|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)|(\b\d+(?:\.\d+)?\b)|(\b[a-zA-Z_]\w*\b)|([^\s\w"'`]+)|(\s+)/g
    : isHtmlOrXml
    ? /(<\/?[a-zA-Z][\w:-]*)|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(\/>|>)|(\b[a-zA-Z_:][\w:.-]*(?==))|([^\s<>="']+)|(\s+)/g
    : isJson
    ? /("(?:\\.|[^"\\])*"(?=\s*:))|("(?:\\.|[^"\\])*")|(\b(?:true|false|null|\d+(?:\.\d+)?)\b)|([^\s"':,{}[\]]+)|(\s+)|([:,{}[\]])/g
    : /(\b\w+\b)|([^\w\s]+)|(\s+)/g;

  let match: RegExpExecArray | null;
  let lastIndex = 0;

  while ((match = regex.exec(line)) !== null) {
    if (match.index > lastIndex) {
      tokens.push({ text: line.slice(lastIndex, match.index), type: 'plain' });
    }
    const fullMatch = match[0];

    if (isPython) {
      if (match[1]) {
        tokens.push({ text: fullMatch, type: 'comment' });
      } else if (match[2]) {
        tokens.push({ text: fullMatch, type: 'string' });
      } else if (match[3]) {
        tokens.push({ text: fullMatch, type: 'number' });
      } else if (match[4]) {
        const word = match[4];
        if (PYTHON_KEYWORDS.has(word)) {
          tokens.push({ text: fullMatch, type: 'keyword' });
        } else {
          tokens.push({ text: fullMatch, type: 'plain' });
        }
      } else {
        tokens.push({ text: fullMatch, type: 'plain' });
      }
    } else if (isJsTs || isRustOrGo) {
      if (match[1]) {
        tokens.push({ text: fullMatch, type: 'comment' });
      } else if (match[2]) {
        tokens.push({ text: fullMatch, type: 'string' });
      } else if (match[3]) {
        tokens.push({ text: fullMatch, type: 'number' });
      } else if (match[4]) {
        const word = match[4];
        const keywordSet = isRustOrGo ? RUST_GO_KEYWORDS : JS_TS_KEYWORDS;
        if (keywordSet.has(word)) {
          tokens.push({ text: fullMatch, type: 'keyword' });
        } else {
          tokens.push({ text: fullMatch, type: 'plain' });
        }
      } else {
        tokens.push({ text: fullMatch, type: 'plain' });
      }
    } else if (isHtmlOrXml) {
      if (match[1] || match[3]) {
        tokens.push({ text: fullMatch, type: 'keyword' });
      } else if (match[2]) {
        tokens.push({ text: fullMatch, type: 'string' });
      } else if (match[4]) {
        tokens.push({ text: fullMatch, type: 'type' });
      } else {
        tokens.push({ text: fullMatch, type: 'plain' });
      }
    } else if (isJson) {
      if (match[1]) {
        tokens.push({ text: fullMatch, type: 'type' }); // JSON key
      } else if (match[2]) {
        tokens.push({ text: fullMatch, type: 'string' });
      } else if (match[3]) {
        tokens.push({ text: fullMatch, type: 'number' });
      } else {
        tokens.push({ text: fullMatch, type: 'plain' });
      }
    } else {
      tokens.push({ text: fullMatch, type: 'plain' });
    }

    lastIndex = regex.lastIndex;
  }

  if (lastIndex < line.length) {
    tokens.push({ text: line.slice(lastIndex), type: 'plain' });
  }

  return tokens.length > 0 ? tokens : [{ text: line, type: 'plain' }];
}

function renderToken(token: Token, key: number) {
  switch (token.type) {
    case 'keyword':
      return (
        <span key={key} className="text-rose-700 dark:text-rose-400 font-medium">
          {token.text}
        </span>
      );
    case 'type':
      return (
        <span key={key} className="text-amber-700 dark:text-amber-400">
          {token.text}
        </span>
      );
    case 'string':
      return (
        <span key={key} className="text-emerald-700 dark:text-emerald-400">
          {token.text}
        </span>
      );
    case 'number':
      return (
        <span key={key} className="text-sky-700 dark:text-sky-400">
          {token.text}
        </span>
      );
    case 'comment':
      return (
        <span key={key} className="text-muted-foreground/75 italic">
          {token.text}
        </span>
      );
    case 'function':
      return (
        <span key={key} className="text-teal-700 dark:text-teal-400">
          {token.text}
        </span>
      );
    default:
      return <span key={key}>{token.text}</span>;
  }
}

// ---------------------------------------------------------------------------
// CodeViewer Component
// ---------------------------------------------------------------------------

export function CodeViewer({
  repositoryId,
  file,
  activeTarget,
  onTargetChange,
  highlightedSource,
  onClearHighlightedSource,
  action,
  isAnalyzing = false,
  className,
}: CodeViewerProps) {
  const { data: fileData, isLoading, isError } = useRepositoryFileContent(repositoryId, file.id);
  const [copied, setCopied] = useState(false);
  const copyTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [anchorLine, setAnchorLine] = useState<number | null>(null);
  const codeContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    return () => {
      if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current);
    };
  }, []);

  const resolvedFileType = useMemo(
    () => resolveFileType(file.path, file.language),
    [file.path, file.language]
  );

  const content = fileData?.content;
  const lines = useMemo(() => (content ? content.split('\n') : []), [content]);

  // Pre-tokenize lines for performance
  const tokenizedLines = useMemo(() => {
    return lines.map((line) => tokenizeLine(line, resolvedFileType.id));
  }, [lines, resolvedFileType.id]);

  // Virtualize long code documents (> 200 lines) while rendering <= 200 lines directly
  const { windowSlice, onScroll } = useVirtualRange({
    totalCount: lines.length,
    itemHeightPx: 20,
    viewportHeightPx: 640,
    overscan: 20,
    resetKey: file.id,
    virtualizeThreshold: 200,
  });

  // Auto-scroll to cited reference when set (handles virtualized files where target line may not be mounted yet)
  useEffect(() => {
    if (
      highlightedSource &&
      highlightedSource.file_path === file.path &&
      typeof highlightedSource.start_line === 'number'
    ) {
      const container = codeContainerRef.current;
      const lineEl = container?.querySelector(
        `[data-line="${highlightedSource.start_line}"]`
      );
      if (lineEl) {
        lineEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
      } else if (container && lines.length > 200) {
        const estimatedTop = Math.max(0, (highlightedSource.start_line - 1) * 20 - 200);
        container.scrollTo?.({ top: estimatedTop, behavior: 'smooth' });
      }
    }
  }, [highlightedSource, file.path, lines.length]);

  async function handleCopy() {
    if (!content) return;
    if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current);
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      copyTimeoutRef.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      // Ignore clipboard write failures
    }
  }

  // Handle symbol selection
  function handleSelectSymbol(sym: CodeSymbol) {
    onTargetChange({
      type: 'symbol',
      path: file.path,
      symbol: sym.name,
      start_line: sym.start_line,
      end_line: sym.end_line,
    });
    setAnchorLine(null);
  }

  // Handle line click for range selection
  function handleLineClick(lineNum: number, event: React.MouseEvent) {
    if (event.shiftKey && anchorLine !== null) {
      // Range selection between anchor and clicked line
      const start = Math.min(anchorLine, lineNum);
      const end = Math.max(anchorLine, lineNum);
      onTargetChange({
        type: 'range',
        path: file.path,
        start_line: start,
        end_line: end,
        symbol: null,
      });
    } else {
      // Set new anchor line
      setAnchorLine(lineNum);
      onTargetChange({
        type: 'range',
        path: file.path,
        start_line: lineNum,
        end_line: lineNum,
        symbol: null,
      });
    }
  }

  // Reset target back to entire file
  function handleResetTarget() {
    setAnchorLine(null);
    onTargetChange({
      type: 'file',
      path: file.path,
    });
  }

  const isTargetRange =
    activeTarget.type !== 'file' &&
    typeof activeTarget.start_line === 'number' &&
    typeof activeTarget.end_line === 'number';

  const isCitedSourceActive =
    Boolean(highlightedSource) &&
    highlightedSource?.file_path === file.path &&
    typeof highlightedSource?.start_line === 'number' &&
    typeof highlightedSource?.end_line === 'number';

  return (
    <div className={cn('flex-1 min-h-0 flex flex-col overflow-hidden', className)}>
      {/* Target Status Banner (shows active scope: entire file vs selected symbol/range) */}
      <div className="shrink-0 px-3 py-1.5 border-b border-border/70 bg-muted/30 flex items-center justify-between text-xs font-mono gap-2 flex-wrap">
        <div className="flex items-center gap-2 min-w-0 flex-wrap">
          <Target className="h-3.5 w-3.5 text-primary shrink-0" />
          <span className="text-muted-foreground text-[11px]">Analysis Target:</span>
          {activeTarget.type === 'symbol' && activeTarget.symbol ? (
            <span className="inline-flex items-center gap-1 text-primary font-medium bg-primary/10 px-2 py-0.5 rounded border border-primary/20 truncate">
              <span>{activeTarget.symbol}</span>
              <span className="text-[10px] text-muted-foreground font-mono">
                (L{activeTarget.start_line}–L{activeTarget.end_line})
              </span>
            </span>
          ) : activeTarget.type === 'range' && activeTarget.start_line ? (
            <span className="inline-flex items-center gap-1 text-primary font-medium bg-primary/10 px-2 py-0.5 rounded border border-primary/20">
              <Hash className="h-3 w-3" />
              <span>
                Lines {activeTarget.start_line}
                {activeTarget.end_line && activeTarget.end_line !== activeTarget.start_line
                  ? `–${activeTarget.end_line}`
                  : ''}
              </span>
            </span>
          ) : (
            <span className="text-foreground font-medium truncate">
              Entire file <span className="text-muted-foreground">({lines.length} lines)</span>
            </span>
          )}

          <span className="px-1.5 py-0.5 rounded bg-muted text-muted-foreground border border-border/60 text-[10px] font-mono shrink-0">
            {resolvedFileType.label}
          </span>

          {/* Active Cited Source Badge */}
          {isCitedSourceActive && highlightedSource && (
            <span className="inline-flex items-center gap-1 text-sky-700 dark:text-sky-400 font-medium bg-sky-500/10 px-2 py-0.5 rounded border border-sky-500/25 text-[10px]">
              <span>Cited: L{highlightedSource.start_line}–L{highlightedSource.end_line}</span>
              {onClearHighlightedSource && (
                <button
                  type="button"
                  onClick={onClearHighlightedSource}
                  className="hover:text-foreground ml-0.5"
                  title="Clear cited highlight"
                >
                  <X className="h-2.5 w-2.5" />
                </button>
              )}
            </span>
          )}
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          {action && (
            <button
              type="button"
              disabled={action.disabled || action.isPending || isAnalyzing}
              onClick={action.onClick}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-primary/15 text-primary border border-primary/30 hover:bg-primary hover:text-primary-foreground transition-all shadow-xs disabled:opacity-50 disabled:pointer-events-none"
              title={action.disabledReason || (action.isPending ? `${action.label} in progress…` : action.label)}
            >
              {action.icon ? (
                action.icon
              ) : (
                <Sparkles className={cn('h-3 w-3', (action.isPending || isAnalyzing) && 'animate-spin')} />
              )}
              <span>{action.isPending ? `${action.label}…` : action.label}</span>
            </button>
          )}

          {activeTarget.type !== 'file' && (
            <button
              type="button"
              onClick={handleResetTarget}
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
              title="Reset target to entire file"
            >
              <X className="h-3 w-3" />
              <span>Target Full File</span>
            </button>
          )}
        </div>
      </div>


      {/* Extracted Symbols Strip */}
      {fileData?.symbols && fileData.symbols.length > 0 && (
        <div className="shrink-0 px-3 py-1.5 border-b border-border/60 bg-muted/15 flex items-center gap-1.5 overflow-x-auto text-xs">
          <span className="text-[10px] text-muted-foreground uppercase font-bold tracking-wider shrink-0 flex items-center gap-1">
            <Layers className="h-3 w-3 text-primary" />
            Symbols ({fileData.symbols.length}):
          </span>
          {fileData.symbols.slice(0, 15).map((sym) => {
            const isSelected =
              activeTarget.type === 'symbol' && activeTarget.symbol === sym.name;
            return (
              <button
                key={sym.id}
                type="button"
                onClick={() => handleSelectSymbol(sym)}
                className={cn(
                  'inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-mono shrink-0 transition-colors',
                  isSelected
                    ? 'bg-primary/20 border-primary text-primary font-medium shadow-xs'
                    : 'bg-background/80 border-border/60 text-foreground hover:border-primary/50 hover:bg-accent'
                )}
                title={`Target ${sym.kind} ${sym.name} (Lines ${sym.start_line}-${sym.end_line})`}
              >
                <span className="text-primary font-bold">{sym.kind}</span>
                <span>{sym.name}</span>
                <span className="text-muted-foreground text-[9px]">L{sym.start_line}</span>
              </button>
            );
          })}
          {fileData.symbols.length > 15 && (
            <span className="text-[10px] text-muted-foreground font-mono shrink-0">
              +{fileData.symbols.length - 15} more
            </span>
          )}
        </div>
      )}

      {/* Code Viewer Body */}
      <div ref={codeContainerRef} onScroll={onScroll} className="flex-1 min-h-0 overflow-auto relative font-mono text-xs">
        {/* Floating copy button */}
        {content && (
          <button
            onClick={handleCopy}
            className="absolute top-2 right-3 z-10 inline-flex items-center gap-1 px-2 py-1 rounded bg-card/85 backdrop-blur-sm border border-border text-[11px] font-mono text-muted-foreground hover:text-foreground hover:bg-accent transition-colors shadow-xs"
            title="Copy code to clipboard"
            aria-label="Copy code to clipboard"
          >
            {copied ? (
              <>
                <Check className="h-3 w-3 text-emerald-600 dark:text-emerald-400" />
                <span className="text-emerald-600 dark:text-emerald-400">Copied</span>
              </>
            ) : (
              <>
                <Copy className="h-3 w-3" />
                <span>Copy</span>
              </>
            )}
          </button>
        )}

        {isLoading ? (
          <div className="flex flex-col items-center justify-center py-20 gap-2">
            <LoadingSpinner size="md" label="Loading code…" />
            <span className="text-xs text-muted-foreground font-mono">
              Retrieving indexed chunks…
            </span>
          </div>
        ) : isError ? (
          <div className="p-6 text-center text-xs text-destructive">
            Could not retrieve file content. Chunks might still be indexing.
          </div>
        ) : !content ? (
          <div className="flex flex-col items-center justify-center p-10 text-center gap-2 font-sans">
            <span className="px-2 py-0.5 rounded-md bg-muted border border-border text-[11px] font-mono text-muted-foreground">
              {resolvedFileType.label}
            </span>
            <p className="text-xs text-muted-foreground">
              {resolvedFileType.isBinaryOrMedia
                ? `${resolvedFileType.label} file — binary or media content cannot be rendered as plain source code.`
                : 'Empty file or non-indexed content.'}
            </p>
          </div>
        ) : (
          <div className="flex min-w-full leading-5 select-text py-2">
            {/* Line numbers gutter (clickable for range targeting, virtualized for large files) */}
            <div
              style={{ paddingTop: windowSlice.topPaddingPx, paddingBottom: windowSlice.bottomPaddingPx }}
              className="shrink-0 text-right text-muted-foreground/40 select-none bg-muted/5 border-r border-border/40 font-mono text-[11px]"
            >
              {lines.slice(windowSlice.startIndex, windowSlice.endIndex).map((_, idx) => {
                const i = windowSlice.startIndex + idx;
                const lineNum = i + 1;
                const isInTarget =
                  isTargetRange &&
                  activeTarget.start_line! <= lineNum &&
                  lineNum <= activeTarget.end_line!;

                const isInCited =
                  isCitedSourceActive &&
                  highlightedSource!.start_line! <= lineNum &&
                  lineNum <= highlightedSource!.end_line!;

                return (
                  <button
                    key={lineNum}
                    type="button"
                    onClick={(e) => handleLineClick(lineNum, e)}
                    className={cn(
                      'block w-full px-3 text-right hover:text-foreground hover:bg-accent/40 cursor-pointer transition-colors',
                      isInTarget
                        ? 'bg-primary/20 text-primary font-bold'
                        : isInCited
                        ? 'bg-sky-500/20 text-sky-700 dark:text-sky-300 font-bold border-r-2 border-sky-500'
                        : undefined
                    )}
                    title={`Click to select line ${lineNum} (Shift+click for range)`}
                  >
                    {lineNum}
                  </button>
                );
              })}
            </div>

            {/* Code content with syntax highlighting & virtualized windowing */}
            <div
              style={{ paddingTop: windowSlice.topPaddingPx, paddingBottom: windowSlice.bottomPaddingPx }}
              className="flex-1 px-4 text-foreground whitespace-pre overflow-x-auto min-w-0"
            >
              {tokenizedLines.slice(windowSlice.startIndex, windowSlice.endIndex).map((tokens, idx) => {
                const i = windowSlice.startIndex + idx;
                const lineNum = i + 1;
                const isInTarget =
                  isTargetRange &&
                  activeTarget.start_line! <= lineNum &&
                  lineNum <= activeTarget.end_line!;

                const isInCited =
                  isCitedSourceActive &&
                  highlightedSource!.start_line! <= lineNum &&
                  lineNum <= highlightedSource!.end_line!;

                return (
                  <div
                    key={lineNum}
                    data-line={lineNum}
                    className={cn(
                      'px-1 -mx-1 rounded-xs transition-colors',
                      isInTarget
                        ? 'bg-primary/10 border-l-2 border-primary text-foreground'
                        : isInCited
                        ? 'bg-sky-500/10 border-l-2 border-sky-500 text-foreground'
                        : 'hover:bg-accent/20'
                    )}
                  >
                    {tokens.length === 0 || (tokens.length === 1 && tokens[0].text === '') ? (
                      '\n'
                    ) : (
                      tokens.map((token, tIdx) => renderToken(token, tIdx))
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

    </div>
  );
}

export interface CodeViewerEmptyStateProps {
  isLookingUpPath: boolean;
  fileParam: string | null;
  citedFileUnavailable: string | null;
  filesLoading: boolean;
  loadedFilesCount: number;
  totalFiles?: number;
  isLoadingMore: boolean;
  onLoadMoreFiles: () => void;
}

export function CodeViewerEmptyState({
  isLookingUpPath,
  fileParam,
  citedFileUnavailable,
  filesLoading,
  loadedFilesCount,
  totalFiles,
  isLoadingMore,
  onLoadMoreFiles,
}: CodeViewerEmptyStateProps) {
  if (isLookingUpPath) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-muted-foreground">
        <LoadingSpinner size="md" label={`Locating cited file "${fileParam}" in repository...`} />
      </div>
    );
  }

  if (citedFileUnavailable) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-muted-foreground">
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-6 max-w-md">
          <FileCode className="h-8 w-8 mb-2 mx-auto text-amber-500" />
          <h4 className="text-sm font-semibold text-foreground">Cited File Unavailable</h4>
          <p className="text-xs text-muted-foreground mt-1 break-all">
            The cited file <code className="font-mono text-primary px-1 bg-muted/60 rounded">{citedFileUnavailable}</code> was not found in the indexed repository files.
          </p>
          <p className="text-[11px] text-muted-foreground mt-2">
            Please select an available file from the explorer tree on the left.
          </p>
          {totalFiles && loadedFilesCount < totalFiles && (
            <button
              onClick={onLoadMoreFiles}
              disabled={isLoadingMore}
              className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-amber-500/20 text-amber-400 hover:bg-amber-500/30 transition-colors"
            >
              {isLoadingMore ? 'Loading files...' : `Load more files (${loadedFilesCount}/${totalFiles})`}
            </button>
          )}
        </div>
      </div>
    );
  }

  if (fileParam && !filesLoading) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-muted-foreground">
        <div className="rounded-xl border border-blue-500/30 bg-blue-500/10 p-6 max-w-md">
          <FileCode className="h-8 w-8 mb-2 mx-auto text-blue-400" />
          <h4 className="text-sm font-semibold text-foreground">Cited File Not in Loaded Preview</h4>
          <p className="text-xs text-muted-foreground mt-1 break-all">
            The cited file <code className="font-mono text-primary px-1 bg-muted/60 rounded">{fileParam}</code> was not found in the first {loadedFilesCount} loaded files (total: {totalFiles ?? 'unknown'}).
          </p>
          <div className="mt-3 flex items-center justify-center gap-2">
            {totalFiles && loadedFilesCount < totalFiles && (
              <button
                onClick={onLoadMoreFiles}
                disabled={isLoadingMore}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
              >
                {isLoadingMore ? 'Loading files...' : `Load next 500 files`}
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-muted-foreground">
      <Code className="h-8 w-8 mb-2 opacity-40 text-primary" />
      <p className="text-xs font-medium text-foreground">No file selected</p>
      <p className="text-[11px] text-muted-foreground mt-0.5">
        Select a file from the explorer on the left to inspect code and symbols.
      </p>
    </div>
  );
}
