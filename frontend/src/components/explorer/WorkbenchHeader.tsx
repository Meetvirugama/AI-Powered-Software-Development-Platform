import { Link } from 'react-router-dom';
import { FileCode, Sparkles, History, MessageSquare, Maximize2 } from 'lucide-react';
import { cn } from '../../lib/utils';
import type { RepositoryFile } from '../../types/api';
import type { AnalysisFeatureType } from '../../types/analysis';

export interface WorkbenchHeaderProps {
  repositoryId: string;
  selectedFile: RepositoryFile | null;
  activeFeature: AnalysisFeatureType | null;
  onToggleAnalysisPanel: () => void;
  onOpenHistory: () => void;
  onOpenFullscreen: () => void;
}

export function WorkbenchHeader({
  repositoryId,
  selectedFile,
  activeFeature,
  onToggleAnalysisPanel,
  onOpenHistory,
  onOpenFullscreen,
}: WorkbenchHeaderProps) {
  return (
    <div className="h-11 bg-muted/30 px-3 sm:px-4 border-b border-border flex items-center justify-between shrink-0">
      <div className="flex items-center gap-2 min-w-0">
        <FileCode className="h-4 w-4 text-primary shrink-0" />
        <span className="font-semibold text-xs text-foreground truncate">
          {selectedFile ? selectedFile.path : 'Code Intelligence Explorer'}
        </span>
        {selectedFile && (
          <span className="hidden sm:inline-block text-[10px] text-muted-foreground font-mono bg-muted/40 px-1.5 py-0.5 rounded border border-border/40 shrink-0">
            {selectedFile.line_count} lines · {(selectedFile.size_bytes / 1024).toFixed(1)} KB
          </span>
        )}
      </div>

      <div className="flex items-center gap-1.5 shrink-0">
        {selectedFile && (
          <>
            {/* Analysis Panel Toggle */}
            <button
              type="button"
              onClick={onToggleAnalysisPanel}
              className={cn(
                'inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md transition-colors',
                activeFeature
                  ? 'bg-primary text-primary-foreground shadow-xs'
                  : 'bg-primary/10 text-primary hover:bg-primary hover:text-primary-foreground'
              )}
              title="Toggle Analysis Result Panel"
            >
              <Sparkles className="h-3 w-3" />
              <span className="hidden sm:inline">
                {activeFeature ? 'Hide Analysis' : 'Analysis Panel'}
              </span>
            </button>

            {/* Universal Analysis History Trigger */}
            <button
              type="button"
              onClick={onOpenHistory}
              className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md bg-muted text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
              title="View Analysis History & Reopen Past Runs"
            >
              <History className="h-3 w-3 text-primary" />
              <span className="hidden sm:inline">History</span>
            </button>

            <Link
              to={`/app/repositories/${repositoryId}/chat?file=${encodeURIComponent(selectedFile.path)}`}
              className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md bg-muted text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
              title="Ask AI about this file"
            >
              <MessageSquare className="h-3 w-3" />
              <span className="hidden sm:inline">Ask AI</span>
            </Link>

            <button
              onClick={onOpenFullscreen}
              className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
              title="Fullscreen preview"
              aria-label="Fullscreen preview"
            >
              <Maximize2 className="h-3.5 w-3.5" />
            </button>
          </>
        )}
      </div>
    </div>
  );
}

