import { useState, useMemo, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import {
  ShieldAlert,
  RefreshCw,
  Bug,
} from 'lucide-react';
import { useRepositoryFiles } from '../hooks/useRepositories';
import { useDetectBugs } from '../hooks/useAnalysis';
import { useStudioFile } from '../hooks/useStudioFile';
import { CodeViewer } from '../components/explorer/CodeViewer';
import { BugScannerView } from '../components/explorer/BugScannerView';
import { AnalysisHistoryDrawer } from '../components/explorer/AnalysisHistoryDrawer';
import { StudioLayout } from '../components/studios/StudioLayout';
import { ErrorMessage } from '../components/shared/ErrorMessage';
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
    <StudioLayout
      files={files}
      filesLoading={filesLoading}
      selectedFile={selectedFile}
      onSelectFile={handleSelectFile}
      showFilePicker={showFilePicker}
      onToggleFilePicker={setShowFilePicker}
      activeTarget={activeTarget}
      activeMobileTab={activeMobileTab}
      onMobileTabChange={setActiveMobileTab}
      onOpenHistory={() => setHistoryOpen(true)}
      historyTitle="View scan history"
      extraControls={
        bugResult ? (
          <div className="hidden sm:flex items-center gap-2 text-xs font-mono">
            <span className="px-2 py-0.5 rounded-full bg-destructive/10 text-destructive border border-destructive/20 text-[11px]">
              {bugResult.total_findings} {bugResult.total_findings === 1 ? 'finding' : 'findings'}
            </span>
          </div>
        ) : undefined
      }
      actionButton={
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
      }
      sourcePanel={
        selectedFile ? (
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
        )
      }
      resultsPanel={
        <div className="flex-1 min-w-0 h-full flex flex-col min-h-0 overflow-y-auto bg-card/30 p-4 lg:p-6">
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
      }
      historyDrawer={
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
      }
    />
  );
}

export default RepositoryBugStudio;
