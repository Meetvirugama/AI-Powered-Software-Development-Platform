import { type ReactNode } from 'react';
import type { RepositoryFile } from '../../types/api';
import type { AnalysisTarget } from '../../types/analysis';
import { StudioToolbar } from './StudioToolbar';
import { StudioWorkspace } from './StudioWorkspace';

export interface StudioLayoutProps {
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
  sourcePanel: ReactNode;
  resultsPanel: ReactNode;
  historyDrawer?: ReactNode;
  className?: string;
}

export function StudioLayout({
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
  historyTitle,
  actionButton,
  extraControls,
  sourcePanel,
  resultsPanel,
  historyDrawer,
  className = '',
}: StudioLayoutProps) {
  return (
    <div className={`flex flex-col h-full w-full overflow-hidden bg-background ${className}`}>
      {/* Shared Studio Toolbar */}
      <StudioToolbar
        files={files}
        filesLoading={filesLoading}
        selectedFile={selectedFile}
        onSelectFile={onSelectFile}
        showFilePicker={showFilePicker}
        onToggleFilePicker={onToggleFilePicker}
        activeTarget={activeTarget}
        activeMobileTab={activeMobileTab}
        onMobileTabChange={onMobileTabChange}
        onOpenHistory={onOpenHistory}
        historyTitle={historyTitle}
        actionButton={actionButton}
        extraControls={extraControls}
      />

      {/* Shared Responsive Workspace (Source / Results) */}
      <StudioWorkspace
        activeMobileTab={activeMobileTab}
        sourcePanel={sourcePanel}
        resultsPanel={resultsPanel}
      />

      {/* History Drawer Portal/Slot */}
      {historyDrawer}
    </div>
  );
}

export default StudioLayout;
