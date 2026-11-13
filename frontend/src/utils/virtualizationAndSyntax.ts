import { useMemo, useState, useCallback, useEffect, type UIEvent } from 'react';

export const TOKEN_COLOR_CLASS: Record<SyntaxTokenKind, string> = {
  keyword: "text-purple-400 font-medium",
  string: "text-emerald-400",
  comment: "text-muted-foreground/70 italic",
  number: "text-blue-400",
  type: "text-amber-400",
  function: "text-cyan-400",
  operator: "text-pink-400",
  plain: "text-foreground",
};

export interface VirtualWindow {
  startIndex: number;
  endIndex: number;
  topPaddingPx: number;
  bottomPaddingPx: number;
  totalHeightPx: number;
  clampedScrollTopPx: number;
}

export function computeVirtualWindow(params: {
  totalCount: number;
  itemHeightPx: number;
  viewportHeightPx: number;
  scrollTopPx: number;
  overscan?: number;
}): VirtualWindow {
  const { totalCount, itemHeightPx, viewportHeightPx, scrollTopPx, overscan = 8 } = params;
  if (totalCount <= 0 || itemHeightPx <= 0) {
    return {
      startIndex: 0,
      endIndex: 0,
      topPaddingPx: 0,
      bottomPaddingPx: 0,
      totalHeightPx: 0,
      clampedScrollTopPx: 0,
    };
  }
  const totalHeightPx = totalCount * itemHeightPx;
  const maxScrollTop = Math.max(0, totalHeightPx - Math.max(1, viewportHeightPx));
  const clampedScrollTopPx = Math.max(0, Math.min(scrollTopPx, maxScrollTop));

  const rawStart = Math.floor(clampedScrollTopPx / itemHeightPx);
  const visibleCount = Math.ceil(Math.max(1, viewportHeightPx) / itemHeightPx);
  const startIndex = Math.max(0, rawStart - overscan);
  const endIndex = Math.min(totalCount, rawStart + visibleCount + overscan);
  const topPaddingPx = startIndex * itemHeightPx;
  const bottomPaddingPx = Math.max(0, (totalCount - endIndex) * itemHeightPx);

  return {
    startIndex,
    endIndex,
    topPaddingPx,
    bottomPaddingPx,
    totalHeightPx,
    clampedScrollTopPx,
  };
}

export function useVirtualRange(params: {
  totalCount: number;
  itemHeightPx: number;
  viewportHeightPx: number;
  overscan?: number;
  resetKey?: string | number;
  virtualizeThreshold?: number;
}) {
  const [scrollTopPx, setScrollTopPx] = useState(0);

  useEffect(() => {
    setScrollTopPx(0);
  }, [params.resetKey]);

  const onScroll = useCallback((event: UIEvent<HTMLElement>) => {
    setScrollTopPx(event.currentTarget.scrollTop);
  }, []);

  const windowSlice = useMemo(
    () => {
      if (params.virtualizeThreshold && params.totalCount <= params.virtualizeThreshold) {
        return {
          startIndex: 0,
          endIndex: params.totalCount,
          topPaddingPx: 0,
          bottomPaddingPx: 0,
          totalHeightPx: params.totalCount * params.itemHeightPx,
          clampedScrollTopPx: 0,
        };
      }
      return computeVirtualWindow({
        totalCount: params.totalCount,
        itemHeightPx: params.itemHeightPx,
        viewportHeightPx: params.viewportHeightPx,
        scrollTopPx,
        overscan: params.overscan,
      });
    },
    [params.totalCount, params.itemHeightPx, params.viewportHeightPx, params.overscan, params.virtualizeThreshold, scrollTopPx],
  );

  return { windowSlice, onScroll, scrollTopPx: windowSlice.clampedScrollTopPx };
}

export type SyntaxTokenKind =
  | 'keyword'
  | 'string'
  | 'comment'
  | 'number'
  | 'type'
  | 'function'
  | 'operator'
  | 'plain';

export interface SyntaxToken {
  text: string;
  kind: SyntaxTokenKind;
}

const MAX_HIGHLIGHT_LINE_LENGTH = 2048;
const MAX_TOKEN_CACHE_ENTRIES = 4096;
const _TOKEN_CACHE = new Map<string, SyntaxToken[]>();

const KEYWORDS = new Set([
  'async', 'await', 'break', 'case', 'catch', 'class', 'const', 'continue', 'def', 'default',
  'delete', 'do', 'elif', 'else', 'enum', 'export', 'extends', 'false', 'finally', 'fn', 'for',
  'from', 'func', 'function', 'if', 'impl', 'import', 'in', 'interface', 'is', 'lambda', 'let',
  'match', 'mod', 'mut', 'new', 'nil', 'None', 'not', 'null', 'or', 'package', 'pass', 'pub',
  'raise', 'return', 'self', 'static', 'struct', 'super', 'switch', 'this', 'throw', 'trait',
  'true', 'True', 'False', 'try', 'type', 'typeof', 'use', 'var', 'void', 'where', 'while',
  'with', 'yield',
]);

const TOKEN_REGEX =
  /(\/\/.*$|#.*$|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|\b\d+(?:\.\d+)?\b|\b[A-Z][A-Za-z0-9_]*\b|\b[a-zA-Z_][a-zA-Z0-9_]*(?=\s*\()|\b[a-zA-Z_][a-zA-Z0-9_]*\b|[===!<>+\-*/%&|^~?:]+|\s+|.)/g;

export function tokenizeCodeLine(line: string): SyntaxToken[] {
  if (!line) {
    return [{ text: '', kind: 'plain' }];
  }
  const cached = _TOKEN_CACHE.get(line);
  if (cached) {
    return cached;
  }

  const prefix = line.length > MAX_HIGHLIGHT_LINE_LENGTH ? line.slice(0, MAX_HIGHLIGHT_LINE_LENGTH) : line;
  const overflow = line.length > MAX_HIGHLIGHT_LINE_LENGTH ? line.slice(MAX_HIGHLIGHT_LINE_LENGTH) : '';

  const matches = prefix.match(TOKEN_REGEX) ?? [prefix];
  const tokens: SyntaxToken[] = matches.map((segment): SyntaxToken => {
    if (segment.startsWith('//') || segment.startsWith('#')) {
      return { text: segment, kind: 'comment' };
    }
    if (
      (segment.startsWith('"') && segment.endsWith('"')) ||
      (segment.startsWith("'") && segment.endsWith("'")) ||
      (segment.startsWith('`') && segment.endsWith('`'))
    ) {
      return { text: segment, kind: 'string' };
    }
    if (/^\d/.test(segment)) {
      return { text: segment, kind: 'number' };
    }
    if (KEYWORDS.has(segment)) {
      return { text: segment, kind: 'keyword' };
    }
    if (/^[A-Z][A-Za-z0-9_]*$/.test(segment)) {
      return { text: segment, kind: 'type' };
    }
    if (/^[===!<>+\-*/%&|^~?:]+$/.test(segment)) {
      return { text: segment, kind: 'operator' };
    }
    return { text: segment, kind: 'plain' };
  });

  if (overflow) {
    tokens.push({ text: overflow, kind: 'plain' });
  }

  if (_TOKEN_CACHE.size >= MAX_TOKEN_CACHE_ENTRIES) {
    const oldestKey = _TOKEN_CACHE.keys().next().value;
    if (oldestKey !== undefined) {
      _TOKEN_CACHE.delete(oldestKey);
    }
  }
  _TOKEN_CACHE.set(line, tokens);
  return tokens;
}

export interface ParsedDiffLine {
  type: 'add' | 'del' | 'context' | 'hunk';
  oldLineNumber: number | null;
  newLineNumber: number | null;
  content: string;
  tokens: SyntaxToken[];
}

export function parseUnifiedDiffWithTokens(unifiedDiff: string): ParsedDiffLine[] {
  const rawLines = unifiedDiff.split(/\r?\n/);
  const result: ParsedDiffLine[] = [];
  let oldLine = 0;
  let newLine = 0;

  for (const raw of rawLines) {
    if (raw.startsWith('---') || raw.startsWith('+++')) {
      continue;
    }
    const hunkMatch = /^@@\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@/.exec(raw);
    if (hunkMatch) {
      oldLine = parseInt(hunkMatch[1], 10);
      newLine = parseInt(hunkMatch[2], 10);
      result.push({
        type: 'hunk',
        oldLineNumber: null,
        newLineNumber: null,
        content: raw,
        tokens: [{ text: raw, kind: 'comment' }],
      });
      continue;
    }
    if (raw.startsWith('+')) {
      const body = raw.slice(1);
      result.push({
        type: 'add',
        oldLineNumber: null,
        newLineNumber: newLine++,
        content: body,
        tokens: tokenizeCodeLine(body),
      });
    } else if (raw.startsWith('-')) {
      const body = raw.slice(1);
      result.push({
        type: 'del',
        oldLineNumber: oldLine++,
        newLineNumber: null,
        content: body,
        tokens: tokenizeCodeLine(body),
      });
    } else {
      const body = raw.startsWith(' ') ? raw.slice(1) : raw;
      result.push({
        type: 'context',
        oldLineNumber: oldLine ? oldLine++ : null,
        newLineNumber: newLine ? newLine++ : null,
        content: body,
        tokens: tokenizeCodeLine(body),
      });
    }
  }
  return result;
}
