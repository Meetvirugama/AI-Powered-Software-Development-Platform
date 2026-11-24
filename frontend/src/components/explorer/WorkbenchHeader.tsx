import { Link } from 'react-router-dom';
import { FileCode, Sparkles, History, MessageSquare, Maximize2, Brain } from 'lucide-react';
import { resolveFileType } from '../../lib/fileLanguage';
import type { RepositoryFile } from '../../types/api';

export interface WorkbenchHeaderProps {
  repositoryId: string;
  selectedFile: RepositoryFile | null;
  onOpenHistory: () => void;
  onOpenFullscreen: () => void;
  onOpenMemory?: () => void;
}

export function WorkbenchHeader({
  repositoryId,
  selectedFile,
  onOpenHistory,
  onOpenFullscreen,
  onOpenMemory,
}: WorkbenchHeaderProps) {
  return (
    <div className="h-11 bg-muted/30 px-3 sm:px-4 border-b border-border flex items-center justify-between shrink-0">
      <div className="flex items-center gap-2 min-w-0">
        <FileCode className="h-4 w-4 text-primary shrink-0" />
        <span className="font-semibold text-xs text-foreground truncate">
          {selectedFile ? selectedFile.path : 'Code Intelligence Explorer'}
        </span>
        {selectedFile && (
          <span className="hidden sm:inline-block text-[10px] text-muted-foreground font-mono bg-muted px-1.5 py-0.5 rounded border border-border/60 shrink-0">
            {resolveFileType(selectedFile.path, selectedFile.language).label} · {selectedFile.line_count} lines · {(selectedFile.size_bytes / 1024).toFixed(1)} KB
          </span>
        )}
      </div>

      <div className="flex items-center gap-1.5 shrink-0">
        {/* Project Memory Drawer Trigger (F36 / Issue #217) */}
        {onOpenMemory && (
          <button
            type="button"
            onClick={onOpenMemory}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md border border-border bg-background text-muted-foreground hover:text-foreground hover:bg-accent transition-colors cursor-pointer"
            title="Project Memory & Knowledge"
          >
            <Brain className="h-3 w-3" />
            <span className="hidden sm:inline">Memory</span>
          </button>
        )}

        {/* Universal Analysis History Trigger */}
        <button
          type="button"
          onClick={onOpenHistory}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md border border-border bg-background text-muted-foreground hover:text-foreground hover:bg-accent transition-colors cursor-pointer"
          title="View Analysis History & Reopen Past Runs"
        >
          <History className="h-3 w-3" />
          <span className="hidden sm:inline">History</span>
        </button>

        {selectedFile && (
          <>
            {/* Quick Open in Explain Studio */}
            <Link
              to={`/app/repositories/${repositoryId}/explain?file=${encodeURIComponent(selectedFile.path)}`}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
              title="Open in Explain Studio"
            >
              <Sparkles className="h-3 w-3" />
              <span className="hidden sm:inline">Explain in Studio</span>
            </Link>

            <Link
              to={`/app/repositories/${repositoryId}/chat?file=${encodeURIComponent(selectedFile.path)}`}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md border border-border bg-background text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
              title="Ask AI about this file"
            >
              <MessageSquare className="h-3 w-3" />
              <span className="hidden sm:inline">Ask AI</span>
            </Link>

            <button
              onClick={onOpenFullscreen}
              className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors cursor-pointer"
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

export default WorkbenchHeader;
