/**
 * Pure helper for proposed test path collision checks.
 */
export function checkProposedTestPath(
  proposedPath: string | undefined | null,
  files: Array<{ path: string }> | undefined | null,
  isLoading: boolean = false,
  hasError: boolean = false,
  isListComplete: boolean = true
): 'EXISTS' | 'NEW' | 'UNKNOWN' {
  if (!proposedPath || !proposedPath.trim()) return 'UNKNOWN';
  if (isLoading || hasError || !files) return 'UNKNOWN';

  const normalize = (p: string) =>
    p
      .replace(/\\/g, '/')
      .replace(/^\.?\//, '')
      .toLowerCase()
      .trim();

  const normalizedProposed = normalize(proposedPath);
  if (!normalizedProposed) return 'UNKNOWN';

  const exists = files.some((f) => normalize(f.path) === normalizedProposed);
  if (exists) return 'EXISTS';

  // F-02 fix: If not found in loaded files, it is only confirmed NEW if the file list is complete.
  // If the repository has more unsearched files, we treat it as UNKNOWN rather than falsely claiming NEW.
  return isListComplete ? 'NEW' : 'UNKNOWN';
}
