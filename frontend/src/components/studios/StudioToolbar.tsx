import { type ReactNode } from 'react';
import { FolderOpen, History, Hash } from 'lucide-react';
import type { RepositoryFile } from '../../types/api';
import type { AnalysisTarget } from '../../types/analysis';
import { TargetFilePicker } from './TargetFilePicker';
import { StudioMobileTabs } from './StudioMobileTabs';

export interface StudioToolbarProps {
  files: RepositoryFile[];
  filesLoading?: boolean;
  selectedFile: RepositoryFile | null;
  onSelectFile: (file: RepositoryFile) => void;
  showFilePicker: boolean;
  onToggleFilePicker: (open: boolean) => void;
  activeTarget?: AnalysisTarget;
  activeMobileTab: 'source' | 'results';
  onMobileTabChange: (tab: 'source' | 'results') => void;
  onOpenHistory?: () => void;
  historyTitle?: string;
  actionButton: ReactNode;
  extraControls?: ReactNode;
}

export function StudioToolbar({
  files,
  filesLoading = false,
  selectedFile,
  onSelectFile,
  showFilePicker,
  onToggleFilePicker,
  activeTarget,
  activeMobileTab,
  onMobileTabChange,
  onOpenHistory,
  historyTitle = 'View analysis history',
  actionButton,
  extraControls,
}: StudioToolbarProps) {
  return (
    <div className="flex-shrink-0 bg-card border-b border-border px-4 py-2.5 flex items-center justify-between gap-3 min-w-0">
      <div className="flex items-center gap-2.5 min-w-0">
        {/* Anchored Target File Picker (F-09) */}
        <div className="relative">
          <button
            onClick={() => onToggleFilePicker(!showFilePicker)}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border border-border bg-background hover:bg-accent text-xs font-medium text-foreground transition-colors shadow-xs"
            title="Switch target file"
            aria-expanded={showFilePicker}
            aria-haspopup="dialog"
          >
            <FolderOpen className="h-3.5 w-3.5 text-primary" />
            <span className="truncate max-w-[140px] sm:max-w-[200px]">
              {selectedFile?.path ?? 'Select File'}
            </span>
          </button>

          {showFilePicker && (
            <>
              <div
                className="fixed inset-0 z-20"
                onClick={() => onToggleFilePicker(false)}
                aria-hidden="true"
              />
              <div className="absolute left-0 top-full mt-1.5 z-30 w-80 sm:w-96 shadow-xl animate-in fade-in-50 zoom-in-95">
                <TargetFilePicker
                  files={files}
                  isLoading={filesLoading}
                  selectedFile={selectedFile}
                  onSelectFile={(file) => {
                    onSelectFile(file);
                    onToggleFilePicker(false);
                  }}
                />
              </div>
            </>
          )}
        </div>

        {activeTarget?.start_line && activeTarget?.end_line && (
          <div className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-accent text-[11px] font-mono text-muted-foreground border border-border">
            <Hash className="h-3 w-3" />
            <span>L{activeTarget.start_line}–L{activeTarget.end_line}</span>
          </div>
        )}

        {extraControls}

        {/* Responsive Mobile / Tablet Tab Switcher (F-09) */}
        <StudioMobileTabs
          activeTab={activeMobileTab}
          onTabChange={onMobileTabChange}
        />
      </div>

      <div className="flex items-center gap-2 shrink-0">
        {onOpenHistory && (
          <button
            onClick={onOpenHistory}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border border-border bg-background hover:bg-accent text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
            title={historyTitle}
            aria-label={historyTitle}
          >
            <History className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">History</span>
          </button>
        )}

        {actionButton}
      </div>
    </div>
  );
}

export default StudioToolbar;
