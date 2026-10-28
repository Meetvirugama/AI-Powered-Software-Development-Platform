import { useState, useMemo, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import {
  ShieldAlert,
  History,
  FolderOpen,
  RefreshCw,
  Bug,
} from 'lucide-react';
import { useRepositoryFiles } from '../hooks/useRepositories';
import { useDetectBugs } from '../hooks/useAnalysis';
import { useStudioFile } from '../hooks/useStudioFile';
import { CodeViewer } from '../components/explorer/CodeViewer';
import { BugScannerView } from '../components/explorer/BugScannerView';
import { AnalysisHistoryDrawer } from '../components/explorer/AnalysisHistoryDrawer';
import { TargetFilePicker } from '../components/studios/TargetFilePicker';
import { ErrorMessage } from '../components/shared/ErrorMessage';
import { cn } from '../lib/utils';
import type { SourceReference, BugDetectionResponse } from '../types/analysis';

export function RepositoryBugStudio() {
  const { id } = useParams<{ id: string }>();

  const repoId = id ?? '';
  const { data: filesData, isLoading: filesLoading } = useRepositoryFiles(repoId, 1, 500);
  const files = useMemo(() => filesData?.items ?? [], [filesData]);

  const [historyOpen, setHistoryOpen] = useState(false);
  const [activeSourceReference, setActiveSourceReference] = useState<SourceReference | null>(null);
  const [bugResult, setBugResult] = useState<BugDetectionResponse | null>(null);
  const [activeMobileTab, setActiveMobileTab] = useState<'source' | 'results'>('source');

  const {
    selectedFile,
    activeTarget,
    showFilePicker,
    setShowFilePicker,
    handleSelectFile,
    handleTargetChange,
  } = useStudioFile(files, () => {
    setActiveSourceReference(null);
    setBugResult(null);
  });

  // Bug detection mutation
  const bugMutation = useDetectBugs(repoId, {
    onSuccess: (data) => {
      setBugResult(data);
      setActiveMobileTab('results');
    },
  });

  const handleRunScan = useCallback(() => {
    if (!selectedFile || bugMutation.isPending) return;

    bugMutation.mutate({
      target: activeTarget,
    });
  }, [selectedFile, activeTarget, bugMutation]);

  const handleSelectSourceReference = (source: SourceReference) => {
    setActiveSourceReference(source);
    setActiveMobileTab('source');
    if (selectedFile && source.file_path && source.file_path !== selectedFile.path) {
      const targetFile = files.find((f) => f.path === source.file_path);
      if (targetFile) {
        handleSelectFile(targetFile);
        handleTargetChange({
          type: 'range',
          path: source.file_path,
          start_line: source.start_line ?? undefined,
          end_line: source.end_line ?? undefined,
        });
      }
    }
  };

  return (
    <div className="flex flex-col h-full w-full overflow-hidden bg-background">
      {/* Studio Header Toolbar */}
      <div className="flex-shrink-0 bg-card border-b border-border px-4 py-2.5 flex items-center justify-between gap-3 min-w-0">
        <div className="flex items-center gap-2.5 min-w-0">
          {/* Anchored Target File Picker (F-09) */}
          <div className="relative">
            <button
              onClick={() => setShowFilePicker(!showFilePicker)}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border border-border bg-background hover:bg-accent text-xs font-medium text-foreground transition-colors shadow-xs"
              title="Switch target file"
              aria-expanded={showFilePicker}
              aria-haspopup="dialog"
            >
              <FolderOpen className="h-3.5 w-3.5 text-primary" />
              <span className="truncate max-w-[140px] sm:max-w-[200px]">{selectedFile?.path ?? 'Select File'}</span>
            </button>

            {showFilePicker && (
              <>
                <div
                  className="fixed inset-0 z-20"
                  onClick={() => setShowFilePicker(false)}
                  aria-hidden="true"
                />
                <div className="absolute left-0 top-full mt-1.5 z-30 w-80 sm:w-96 shadow-xl animate-in fade-in-50 zoom-in-95">
                  <TargetFilePicker
                    files={files}
                    isLoading={filesLoading}
                    selectedFile={selectedFile}
                    onSelectFile={handleSelectFile}
                  />
                </div>
              </>
            )}
          </div>

          {bugResult && (
            <div className="hidden sm:flex items-center gap-2 text-xs font-mono">
              <span className="px-2 py-0.5 rounded-full bg-destructive/10 text-destructive border border-destructive/20 text-[11px]">
                {bugResult.total_findings} {bugResult.total_findings === 1 ? 'finding' : 'findings'}
              </span>
            </div>
          )}

          {/* Responsive Mobile / Tablet Tab Switcher (F-09) */}
          <div className="flex lg:hidden items-center p-0.5 rounded-lg bg-muted text-xs font-medium">
            <button
              onClick={() => setActiveMobileTab('source')}
              className={cn(
                'px-2.5 py-1 rounded-md transition-colors',
                activeMobileTab === 'source'
                  ? 'bg-background text-foreground shadow-2xs font-semibold'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              Source
            </button>
            <button
              onClick={() => setActiveMobileTab('results')}
              className={cn(
                'px-2.5 py-1 rounded-md transition-colors',
                activeMobileTab === 'results'
                  ? 'bg-background text-foreground shadow-2xs font-semibold'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              Results
              {bugResult && (
                <span className="ml-1 px-1 py-0.2 rounded-full bg-destructive/10 text-destructive text-[10px]">
                  {bugResult.total_findings}
                </span>
              )}
            </button>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => setHistoryOpen(true)}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border border-border bg-background hover:bg-accent text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
            title="View scan history"
            aria-label="View scan history"
          >
            <History className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">History</span>
          </button>

          <button
            onClick={handleRunScan}
            disabled={!selectedFile || bugMutation.isPending}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-destructive hover:bg-destructive/90 text-destructive-foreground text-xs font-medium transition-colors shadow-xs disabled:opacity-50"
          >
            {bugMutation.isPending ? (
              <>
                <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                <span>Scanning...</span>
              </>
            ) : (
              <>
                <ShieldAlert className="h-3.5 w-3.5" />
                <span>Scan for Bugs</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Responsive Split Studio Canvas (F-09) */}
      <div className="flex-1 min-h-0 flex overflow-hidden">
        {/* Left Pane: Code Viewer */}
        <div
          className={cn(
            'w-full lg:w-1/2 min-w-0 h-full lg:border-r border-border flex flex-col min-h-0 overflow-hidden bg-background',
            activeMobileTab !== 'source' && 'hidden lg:flex'
          )}
        >
          {selectedFile ? (
            <CodeViewer
              repositoryId={repoId}
              file={selectedFile}
              activeTarget={activeTarget}
              onTargetChange={handleTargetChange}
              highlightedSource={activeSourceReference}
              onClearHighlightedSource={() => setActiveSourceReference(null)}
              onTriggerExplain={handleRunScan}
              isAnalyzing={bugMutation.isPending}
            />
          ) : (
            <div className="flex-1 flex items-center justify-center p-8 text-center text-muted-foreground text-xs">
              Select a file to inspect its source code.
            </div>
          )}
        </div>

        {/* Right Pane: Bug Findings Canvas */}
        <div
          className={cn(
            'flex-1 lg:w-1/2 min-w-0 h-full flex flex-col min-h-0 overflow-y-auto bg-card/30 p-4 lg:p-6',
            activeMobileTab !== 'results' && 'hidden lg:flex'
          )}
        >
          {bugMutation.isPending ? (
            <div className="flex-1 flex flex-col items-center justify-center p-8 text-center space-y-3">
              <div className="h-12 w-12 rounded-full bg-destructive/10 border border-destructive/20 flex items-center justify-center text-destructive animate-pulse">
                <ShieldAlert className="h-6 w-6 animate-spin" />
              </div>
              <h3 className="text-sm font-semibold text-foreground">Auditing code for bugs & security flaws...</h3>
              <p className="text-xs text-muted-foreground max-w-sm">
                Running static AST security rules combined with LLM vulnerability analysis.
              </p>
            </div>
          ) : bugMutation.isError ? (
            <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
              <ErrorMessage
                message={bugMutation.error instanceof Error ? bugMutation.error.message : 'Bug scan failed.'}
              />
              <button
                onClick={handleRunScan}
                className="mt-4 px-3 py-1.5 rounded-md bg-primary text-primary-foreground text-xs font-medium"
              >
                Retry Scan
              </button>
            </div>
          ) : bugResult ? (
            <div className="max-w-4xl w-full mx-auto space-y-4">
              <BugScannerView
                result={bugResult}
                activeSourceReference={activeSourceReference}
                onSelectSourceReference={handleSelectSourceReference}
              />
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-muted-foreground space-y-3">
              <Bug className="h-10 w-10 opacity-30 text-destructive" />
              <h3 className="text-sm font-semibold text-foreground">Ready to scan</h3>
              <p className="text-xs max-w-sm">
                Select a target file or range and click &quot;Scan for Bugs&quot; to detect potential bugs, antipatterns, and security risks.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* History Drawer */}
      <AnalysisHistoryDrawer
        isOpen={historyOpen}
        onClose={() => setHistoryOpen(false)}
        repositoryId={repoId}
        initialFeature="bugs"
        onReopenBugs={(reopened) => {
          setBugResult(reopened);
          setActiveMobileTab('results');
          setHistoryOpen(false);
        }}
      />
    </div>
  );
}
export default RepositoryBugStudio;
