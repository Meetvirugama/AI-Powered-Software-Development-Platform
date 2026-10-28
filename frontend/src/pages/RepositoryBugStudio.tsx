import { useState, useMemo, useCallback } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import {
  ShieldAlert,
  History,
  FolderOpen,
  RefreshCw,
  Bug,
} from 'lucide-react';
import { useRepositoryFiles } from '../hooks/useRepositories';
import { useDetectBugs } from '../hooks/useAnalysis';
import { CodeViewer } from '../components/explorer/CodeViewer';
import { BugScannerView } from '../components/explorer/BugScannerView';
import { AnalysisHistoryDrawer } from '../components/explorer/AnalysisHistoryDrawer';
import { TargetFilePicker } from '../components/studios/TargetFilePicker';
import { ErrorMessage } from '../components/shared/ErrorMessage';
import type { RepositoryFile } from '../types/api';
import type {
  AnalysisTarget,
  SourceReference,
  BugDetectionResponse,
} from '../types/analysis';

export function RepositoryBugStudio() {
  const { id } = useParams<{ id: string }>();
  const [searchParams, setSearchParams] = useSearchParams();

  const repoId = id ?? '';
  const { data: filesData, isLoading: filesLoading } = useRepositoryFiles(repoId, 1, 100);

  const files: RepositoryFile[] = useMemo(() => filesData?.items ?? [], [filesData]);
  const fileQuery = searchParams.get('file');

  const [selectedFileOverride, setSelectedFileOverride] = useState<RepositoryFile | null>(null);
  const [showFilePicker, setShowFilePicker] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [targetRange, setTargetRange] = useState<{ start_line?: number; end_line?: number; symbol?: string | null }>({});

  const selectedFile: RepositoryFile | null = useMemo(() => {
    if (selectedFileOverride) return selectedFileOverride;
    if (fileQuery && files.length > 0) {
      const match = files.find((f: RepositoryFile) => f.path === fileQuery);
      if (match) return match;
    }
    if (files.length > 0) {
      return files.find((f: RepositoryFile) => !f.path.startsWith('.') && f.size_bytes > 0) ?? files[0];
    }
    return null;
  }, [selectedFileOverride, fileQuery, files]);

  const activeTarget: AnalysisTarget = useMemo(() => ({
    type: targetRange.start_line && targetRange.end_line ? 'range' : 'file',
    path: selectedFile?.path ?? '',
    start_line: targetRange.start_line,
    end_line: targetRange.end_line,
    symbol: targetRange.symbol,
  }), [selectedFile, targetRange]);

  const [activeSourceReference, setActiveSourceReference] = useState<SourceReference | null>(null);
  const [bugResult, setBugResult] = useState<BugDetectionResponse | null>(null);

  const handleSelectFile = (file: RepositoryFile) => {
    setSelectedFileOverride(file);
    setTargetRange({});
    setSearchParams({ file: file.path });
    setShowFilePicker(false);
    setActiveSourceReference(null);
  };

  const handleTargetChange = (target: AnalysisTarget) => {
    setTargetRange({
      start_line: target.start_line,
      end_line: target.end_line,
      symbol: target.symbol,
    });
  };

  // Bug detection mutation
  const bugMutation = useDetectBugs(repoId, {
    onSuccess: (data) => {
      setBugResult(data);
    },
  });

  const handleRunScan = useCallback(() => {
    if (!selectedFile || bugMutation.isPending) return;

    bugMutation.mutate({
      target: activeTarget,
    });
  }, [selectedFile, activeTarget, bugMutation]);

  // Jump to citation source in code viewer
  const handleSelectSourceReference = (source: SourceReference) => {
    setActiveSourceReference(source);
    if (selectedFile && source.file_path && source.file_path !== selectedFile.path) {
      const targetFile = files.find((f: RepositoryFile) => f.path === source.file_path);
      if (targetFile) {
        setSelectedFileOverride(targetFile);
        setTargetRange({
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
          <button
            onClick={() => setShowFilePicker(!showFilePicker)}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border border-border bg-background hover:bg-accent text-xs font-medium text-foreground transition-colors shadow-xs"
            title="Switch target file"
          >
            <FolderOpen className="h-3.5 w-3.5 text-primary" />
            <span className="truncate max-w-[200px]">{selectedFile?.path ?? 'Select File'}</span>
          </button>

          {bugResult && (
            <div className="hidden sm:flex items-center gap-2 text-xs font-mono">
              <span className="px-2 py-0.5 rounded-full bg-destructive/10 text-destructive border border-destructive/20 text-[11px]">
                {bugResult.total_findings} {bugResult.total_findings === 1 ? 'finding' : 'findings'}
              </span>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => setHistoryOpen(true)}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border border-border bg-background hover:bg-accent text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
            title="View scan history"
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

      {/* Popover File Picker */}
      {showFilePicker && (
        <div className="absolute left-4 top-24 z-30 w-96 shadow-xl animate-in fade-in-50 zoom-in-95">
          <TargetFilePicker
            files={files}
            isLoading={filesLoading}
            selectedFile={selectedFile}
            onSelectFile={handleSelectFile}
          />
        </div>
      )}

      {/* 2-Pane Split Studio Canvas */}
      <div className="flex-1 min-h-0 flex overflow-hidden">
        {/* Left Pane: Code Viewer */}
        <div className="w-1/2 min-w-[360px] h-full border-r border-border flex flex-col min-h-0 overflow-hidden bg-background">
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
        <div className="flex-1 h-full flex flex-col min-h-0 overflow-y-auto bg-card/30 p-4 lg:p-6">
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
            <div className="p-4">
              <ErrorMessage
                error={bugMutation.error}
              />
            </div>
          ) : bugResult ? (
            <div className="space-y-4">
              <BugScannerView
                result={bugResult}
                activeSourceReference={activeSourceReference}
                onSelectSourceReference={handleSelectSourceReference}
              />
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center p-8 text-center max-w-md mx-auto space-y-4">
              <div className="h-12 w-12 rounded-2xl bg-destructive/10 border border-destructive/20 flex items-center justify-center text-destructive shadow-xs">
                <Bug className="h-6 w-6" />
              </div>
              <div>
                <h3 className="text-base font-semibold text-foreground tracking-tight">Bug Hunter & Security Auditor</h3>
                <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">
                  Identify logical defects, security vulnerabilities, edge-case crashes, and race conditions with source-grounded evidence and remediation patches.
                </p>
              </div>

              <div className="w-full pt-2">
                <button
                  onClick={handleRunScan}
                  disabled={!selectedFile}
                  className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 text-xs font-medium rounded-md bg-destructive hover:bg-destructive/90 text-destructive-foreground transition-colors shadow-xs"
                >
                  <ShieldAlert className="h-3.5 w-3.5" />
                  <span>Scan Current File ({selectedFile?.path.split('/').pop() ?? 'None'})</span>
                </button>
              </div>
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
        currentFilePath={selectedFile?.path}
        onReopenBugs={(bugs, target) => {
          setBugResult(bugs);
          handleTargetChange(target);
          setHistoryOpen(false);
        }}
      />
    </div>
  );
}

export default RepositoryBugStudio;
