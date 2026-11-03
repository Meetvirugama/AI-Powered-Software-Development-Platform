/**
 * useStudioFile — shared file-selection logic for all four analysis studios.
 *
 * Consolidates the identical file-selection pattern that previously existed
 * in RepositoryExplainStudio, RepositoryBugStudio, RepositoryTestStudio,
 * and RepositoryReviewStudio (~30 duplicate lines each).
 *
 * BUG-W3-05 Fix:
 * `handleSelectFile` accepts an optional `{ preserveResults?: boolean }` flag
 * so cross-file source reference navigation in BugScannerView / ExplanationResultView
 * switches the code viewer file without wiping the active analysis result!
 */

import { useState, useMemo } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import type { RepositoryFile } from '../types/api';
import type { AnalysisTarget, AnalysisTargetType } from '../types/analysis';
import { findMatchingRepositoryFile } from '../lib/sourceReference';

export interface TargetRange {
  start_line?: number;
  end_line?: number;
  symbol?: string | null;
}

interface StoredTargetDescriptor {
  type: AnalysisTargetType;
  start_line?: number;
  end_line?: number;
  symbol?: string | null;
  revision?: string | null;
}

export interface SelectFileOptions {
  preserveResults?: boolean;
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
   * Called when the user selects a file in the file picker or via citation click.
   * Resets target range, updates the URL search param, and hides the picker.
   */
  handleSelectFile: (file: RepositoryFile, options?: SelectFileOptions) => void;
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
  const [storedTarget, setStoredTarget] = useState<StoredTargetDescriptor | null>(null);
  const [prevRepoId, setPrevRepoId] = useState(repoId);

  if (prevRepoId !== repoId) {
    setPrevRepoId(repoId);
    setStoredTarget(null);
    setFileOverride(null);
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

  const activeTarget: AnalysisTarget = useMemo(() => {
    const path = selectedFile?.path ?? '';
    if (!storedTarget || storedTarget.type === 'file') {
      return { type: 'file', path };
    }
    if (storedTarget.type === 'symbol') {
      return {
        type: 'symbol',
        path,
        symbol: storedTarget.symbol ?? null,
        start_line: typeof storedTarget.start_line === 'number' ? storedTarget.start_line : undefined,
        end_line: typeof storedTarget.end_line === 'number' ? storedTarget.end_line : undefined,
        revision: storedTarget.revision ?? null,
      };
    }
    if (storedTarget.type === 'range') {
      const start = storedTarget.start_line;
      const end = storedTarget.end_line;
      const hasValidLines =
        typeof start === 'number' &&
        typeof end === 'number' &&
        start >= 0 &&
        end >= start;
      if (hasValidLines) {
        return {
          type: 'range',
          path,
          start_line: start,
          end_line: end,
          symbol: storedTarget.symbol ?? null,
          revision: storedTarget.revision ?? null,
        };
      }
    }
    return { type: 'file', path };
  }, [selectedFile, storedTarget]);

  const targetRange: TargetRange = useMemo(
    () => ({
      start_line: typeof activeTarget.start_line === 'number' ? activeTarget.start_line : undefined,
      end_line: typeof activeTarget.end_line === 'number' ? activeTarget.end_line : undefined,
      symbol: activeTarget.symbol ?? null,
    }),
    [activeTarget]
  );

  const handleSelectFile = (file: RepositoryFile, options?: SelectFileOptions) => {
    setFileOverride({ repoId, file });
    setStoredTarget({ type: 'file' });
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set('file', file.path);
      return next;
    });
    setShowFilePicker(false);
    if (!options?.preserveResults) {
      onFileChange?.();
    }
  };

  const handleTargetChange = (target: AnalysisTarget) => {
    if (target.type === 'symbol') {
      setStoredTarget({
        type: 'symbol',
        start_line: typeof target.start_line === 'number' ? target.start_line : undefined,
        end_line: typeof target.end_line === 'number' ? target.end_line : undefined,
        symbol: target.symbol ?? null,
        revision: target.revision ?? null,
      });
    } else if (target.type === 'range') {
      const start = typeof target.start_line === 'number' ? target.start_line : undefined;
      const end = typeof target.end_line === 'number' ? target.end_line : undefined;
      if (start !== undefined && end !== undefined && start >= 0 && end >= start) {
        setStoredTarget({
          type: 'range',
          start_line: start,
          end_line: end,
          symbol: target.symbol ?? null,
          revision: target.revision ?? null,
        });
      } else {
        setStoredTarget({ type: 'file' });
      }
    } else {
      setStoredTarget({ type: 'file' });
    }
  };

  const resetTargetRange = () => setStoredTarget({ type: 'file' });

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
