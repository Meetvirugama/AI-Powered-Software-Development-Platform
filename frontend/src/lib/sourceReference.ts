import type { SourceReference } from '../types/analysis';
import type { RepositoryFile } from '../types/api';

/**
 * Canonical path normalization helper shared between Explorer and studios (F-05).
 */
export function normalizeFilePath(p: string | null | undefined): string {
  if (!p) return '';
  return p
    .trim()
    .replace(/\\/g, '/')
    .replace(/^\.?\//, '')
    .toLowerCase();
}

/**
 * Find a repository file matching the requested path.
 * Searches for an exact normalized path match first, and falls back to
 * a suffix match at path boundaries only if no exact match is found.
 */
export function findMatchingRepositoryFile(
  files: RepositoryFile[],
  requestedPath: string | null | undefined
): RepositoryFile | undefined {
  if (!requestedPath || !files || files.length === 0) return undefined;
  const targetNorm = normalizeFilePath(requestedPath);
  if (!targetNorm) return undefined;

  // 1. Exact normalized path match has strict priority
  const exact = files.find((f) => normalizeFilePath(f.path) === targetNorm);
  if (exact) return exact;

  // 2. Suffix match at path segment boundary only if no exact match exists
  return files.find((f) => {
    const fileNorm = normalizeFilePath(f.path);
    return fileNorm.endsWith('/' + targetNorm) || targetNorm.endsWith('/' + fileNorm);
  });
}

/**
 * Pure helper for matching source references by path and line bounds.
 */
export function isSourceReferenceEqual(
  a?: SourceReference | null,
  b?: SourceReference | null
): boolean {
  if (!a || !b) return false;

  if (normalizeFilePath(a.file_path) !== normalizeFilePath(b.file_path)) return false;
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
