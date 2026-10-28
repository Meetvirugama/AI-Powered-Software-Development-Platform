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
import { useSearchParams } from 'react-router-dom';
import type { RepositoryFile } from '../types/api';
import type { AnalysisTarget } from '../types/analysis';

export interface TargetRange {
  start_line?: number;
  end_line?: number;
  symbol?: string | null;
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

export function useStudioFile(
  files: RepositoryFile[],
  onFileChange?: () => void
): UseStudioFileReturn {
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedFileOverride, setSelectedFileOverride] = useState<RepositoryFile | null>(null);
  const [showFilePicker, setShowFilePicker] = useState(false);
  const [targetRange, setTargetRange] = useState<TargetRange>({});

  const fileQuery = searchParams.get('file');

  const selectedFile: RepositoryFile | null = useMemo(() => {
    if (selectedFileOverride) return selectedFileOverride;
    if (fileQuery && files.length > 0) {
      const match = files.find((f) => f.path === fileQuery);
      if (match) return match;
    }
    if (files.length > 0) {
      return files.find((f) => !f.path.startsWith('.') && f.size_bytes > 0) ?? files[0];
    }
    return null;
  }, [selectedFileOverride, fileQuery, files]);

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

  const handleSelectFile = (file: RepositoryFile, options?: SelectFileOptions) => {
    setSelectedFileOverride(file);
    setTargetRange({});
    setSearchParams({ file: file.path });
    setShowFilePicker(false);
    if (!options?.preserveResults) {
      onFileChange?.();
    }
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
