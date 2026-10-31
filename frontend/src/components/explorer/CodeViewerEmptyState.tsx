import { FileCode, Code } from 'lucide-react';
import { LoadingSpinner } from '../shared/LoadingSpinner';

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

