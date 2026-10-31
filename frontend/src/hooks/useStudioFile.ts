/**
 * useStudioFile — shared file-selection logic for all four analysis studios.
 *
 * Consolidates the identical file-selection pattern that previously existed
 * in RepositoryExplainStudio, RepositoryBugStudio, RepositoryTestStudio,
 * and RepositoryReviewStudio (~30 duplicate lines each).
 */

import { useState, useMemo } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import type { RepositoryFile } from '../types/api';
import type { AnalysisTarget } from '../types/analysis';
import { findMatchingRepositoryFile } from '../lib/sourceReference';

export interface TargetRange {
  start_line?: number;
  end_line?: number;
  symbol?: string | null;
}

export interface UseStudioFileReturn {
  /** The currently selected repository file, or null if none loaded yet. */
  selectedFile: RepositoryFile | null;
  /** Optional line/symbol narrowing within the selected file. */
  targetRange: TargetRange;
  /** The fully composed AnalysisTarget ready to send to the backend. */
  activeTarget: AnalysisTarget;
  /** Whether the file picker popover is visible. */
  showFilePicker: boolean;
  /** Show or hide the file picker popover. */
  setShowFilePicker: (visible: boolean) => void;
  /**
   * Called when the user selects a file in the file picker.
   * Resets target range, updates the URL search param, and hides the picker.
   */
  handleSelectFile: (file: RepositoryFile) => void;
  /**
   * Called when the code viewer emits a new range selection.
   * Narrows the analysis target to the specified lines or symbol.
   */
  handleTargetChange: (target: AnalysisTarget) => void;
  /** Reset the target range (e.g. when clearing a selection). */
  resetTargetRange: () => void;
}

/**
 * Shared file-selection hook for all four developer studio pages (F-05).
 *
 * Guarantees:
 * - Selection state is scoped to current repository ID and reset upon switching.
 * - Deep-link query parameters are resolved with normalized path comparison.
 * - Overrides are validated against the active repository's file list.
 * - Non-target search parameters are preserved upon file selection.
 *
 * @param files         The list of indexed repository files (from useRepositoryFiles).
 * @param onFileChange  Optional callback invoked after file selection changes.
 */
export function useStudioFile(
  files: RepositoryFile[],
  onFileChange?: () => void
): UseStudioFileReturn {
  const { id: repoId } = useParams<{ id: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const [fileOverride, setFileOverride] = useState<{ repoId?: string; file: RepositoryFile } | null>(null);
  const [showFilePicker, setShowFilePicker] = useState(false);
  const [targetRange, setTargetRange] = useState<TargetRange>({});
  const [prevRepoId, setPrevRepoId] = useState(repoId);

  if (prevRepoId !== repoId) {
    setPrevRepoId(repoId);
    setTargetRange({});
  }

  const fileQuery = searchParams.get('file');

  // Validated override scoped strictly to current repoId and verified to exist in files
  const validOverride = useMemo(() => {
    if (!fileOverride) return null;
    if (fileOverride.repoId && repoId && fileOverride.repoId !== repoId) return null;
    return findMatchingRepositoryFile(files, fileOverride.file.path) ?? null;
  }, [fileOverride, repoId, files]);

  const selectedFile: RepositoryFile | null = useMemo(() => {
    // 1. Deep link query parameter matching
    if (fileQuery && files.length > 0) {
      const match = findMatchingRepositoryFile(files, fileQuery);
      if (match) return match;
    }
    // 2. Active user selection override belonging to current repo
    if (validOverride) return validOverride;

    // 3. Fallback to default index file
    if (files.length > 0) {
      return files.find((f) => !f.path.startsWith('.') && f.size_bytes > 0) ?? files[0];
    }
    return null;
  }, [validOverride, fileQuery, files]);

  const activeTarget: AnalysisTarget = useMemo(
    () => ({
      type: targetRange.start_line && targetRange.end_line ? 'range' : 'file',
      path: selectedFile?.path ?? '',
      start_line: targetRange.start_line,
      end_line: targetRange.end_line,
      symbol: targetRange.symbol,
    }),
    [selectedFile, targetRange]
  );

  const handleSelectFile = (file: RepositoryFile) => {
    setFileOverride({ repoId, file });
    setTargetRange({});
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set('file', file.path);
      return next;
    });
    setShowFilePicker(false);
    onFileChange?.();
  };

  const handleTargetChange = (target: AnalysisTarget) => {
    setTargetRange({
      start_line: target.start_line,
      end_line: target.end_line,
      symbol: target.symbol,
    });
  };

  const resetTargetRange = () => setTargetRange({});

  return {
    selectedFile,
    targetRange,
    activeTarget,
    showFilePicker,
    setShowFilePicker,
    handleSelectFile,
    handleTargetChange,
    resetTargetRange,
  };
}
