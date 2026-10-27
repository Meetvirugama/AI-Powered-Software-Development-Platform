import type { SourceReference } from '../types/analysis';

/**
 * Pure helper for matching source references by path and line bounds.
 */
export function isSourceReferenceEqual(
  a?: SourceReference | null,
  b?: SourceReference | null
): boolean {
  if (!a || !b) return false;

  const normalizePath = (p: string) =>
    p
      .replace(/\\/g, '/')
      .replace(/^\.?\//, '')
      .toLowerCase()
      .trim();

  if (normalizePath(a.file_path) !== normalizePath(b.file_path)) return false;
  if (a.start_line !== b.start_line) return false;
  if (a.end_line !== undefined && b.end_line !== undefined && a.end_line !== b.end_line) {
    return false;
  }
  return true;
}

/**
 * Format a SourceReference as a standard user-facing string "path:start-end"
 */
export function formatSourceRange(ref?: SourceReference | null): string {
  if (!ref || !ref.file_path) return '';
  if (ref.start_line && ref.end_line && ref.start_line !== ref.end_line) {
    return `${ref.file_path}:${ref.start_line}-${ref.end_line}`;
  }
  if (ref.start_line) {
    return `${ref.file_path}:${ref.start_line}`;
  }
  return ref.file_path;
}
