import { useState, useMemo, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import {
  ShieldAlert,
  RefreshCw,
  Bug,
  PlusCircle,
  CheckCircle2,
} from 'lucide-react';
import { cn } from '../lib/utils';
import { useRepositoryFiles } from '../hooks/useRepositories';
import { useDetectBugs } from '../hooks/useAnalysis';
import { useStudioFile } from '../hooks/useStudioFile';
import { CodeViewer } from '../components/explorer/CodeViewer';
import { BugScannerView } from '../components/explorer/BugScannerView';
import { AnalysisHistoryDrawer } from '../components/explorer/AnalysisHistoryDrawer';
import { CreateIssueModal, type FindingForIssue } from '../components/explorer/CreateIssueModal';
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
  const [issueFinding, setIssueFinding] = useState<FindingForIssue | null>(null);
  const [scanMode, setScanMode] = useState<'quick' | 'standard' | 'deep' | 'change'>('standard');

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
      scan_mode: scanMode,
    });
  }, [selectedFile, activeTarget, scanMode, bugMutation]);

  const handleSelectSourceReference = (source: SourceReference) => {
    setActiveSourceReference(source);
    setActiveMobileTab('source');
    if (selectedFile && source.file_path && source.file_path !== selectedFile.path) {
      const targetFile = files.find((f) => f.path === source.file_path);
      if (targetFile) {
        handleSelectFile(targetFile, { preserveResults: true });
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
    <>
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
          <div className="flex items-center gap-2 flex-wrap">
            {/* Scan Mode / Scope Selector */}
            <div className="inline-flex items-center p-0.5 rounded-lg bg-muted/40 border border-border/70 text-[11px] font-mono">
              <button
                type="button"
                onClick={() => setScanMode('quick')}
                className={cn(
                  'px-2 py-0.5 rounded-md transition-colors',
                  scanMode === 'quick' ? 'bg-primary/20 text-primary font-bold' : 'text-muted-foreground hover:text-foreground'
                )}
                title="Quick Scan: Targeted AST and security analysis on the selected file"
              >
                Quick
              </button>
              <button
                type="button"
                onClick={() => setScanMode('standard')}
                className={cn(
                  'px-2 py-0.5 rounded-md transition-colors',
                  scanMode === 'standard' ? 'bg-primary/20 text-primary font-bold' : 'text-muted-foreground hover:text-foreground'
                )}
                title="Standard Scan: Target plus callers, callees, guards, and tests"
              >
                Standard
              </button>
              <button
                type="button"
                onClick={() => setScanMode('deep')}
                className={cn(
                  'px-2 py-0.5 rounded-md transition-colors',
                  scanMode === 'deep' ? 'bg-primary/20 text-primary font-bold' : 'text-muted-foreground hover:text-foreground'
                )}
                title="Deep Scan: Complete multi-hop dependency slice and AI counterevidence validation"
              >
                Deep
              </button>
              <button
                type="button"
                onClick={() => setScanMode('change')}
                className={cn(
                  'px-2 py-0.5 rounded-md transition-colors',
                  scanMode === 'change' ? 'bg-primary/20 text-primary font-bold' : 'text-muted-foreground hover:text-foreground'
                )}
                title="Change Scan: Changed files, reverse dependents, and regression risk analysis"
              >
                Change
              </button>
            </div>

            {bugResult && (
              <div className="flex items-center gap-2">
                <span className="hidden sm:inline-flex px-2 py-0.5 rounded-full bg-destructive/10 text-destructive border border-destructive/20 text-[11px] font-mono">
                  {bugResult.total_findings} {bugResult.total_findings === 1 ? 'finding' : 'findings'}
                </span>
                {bugResult.findings.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setIssueFinding(bugResult.findings[0])}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border border-primary/40 bg-primary/10 hover:bg-primary/20 text-xs font-semibold text-primary transition-colors"
                    title="Create GitHub Issue & Task from top finding"
                  >
                    <PlusCircle className="h-3.5 w-3.5" />
                    <span className="hidden sm:inline">Create Issue</span>
                  </button>
                )}
              </div>
            )}
          </div>
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
              action={{
                label: 'Scan for bugs',
                onClick: handleRunScan,
                isPending: bugMutation.isPending,
              }}
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
              <div className="flex-1 flex flex-col items-center justify-center p-8 text-center space-y-4 max-w-md mx-auto">
                <div className="h-12 w-12 rounded-full bg-destructive/10 border border-destructive/20 flex items-center justify-center text-destructive animate-pulse">
                  <ShieldAlert className="h-6 w-6 animate-spin" />
                </div>
                <div className="space-y-1">
                  <h3 className="text-sm font-semibold text-foreground">Repository Bug Intelligence Engine Active</h3>
                  <p className="text-xs text-muted-foreground">
                    Executing multi-phase repository context investigation ({scanMode.toUpperCase()} mode).
                  </p>
                </div>
                <div className="w-full text-left space-y-2 p-3.5 rounded-xl border border-border/70 bg-card/60 backdrop-blur-xs font-mono text-[11px]">
                  <div className="flex items-center gap-2 text-emerald-400">
                    <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                    <span>1. Candidate Discovery (AST & Taint analysis)</span>
                  </div>
                  <div className="flex items-center gap-2 text-cyan-400">
                    <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                    <span>2. Dependency Graph Slicing (2-hop traversal)</span>
                  </div>
                  <div className="flex items-center gap-2 text-purple-400 animate-pulse">
                    <RefreshCw className="h-3.5 w-3.5 shrink-0 animate-spin" />
                    <span>3. AI Investigation & Bug Verification</span>
                  </div>
                  <div className="flex items-center gap-2 text-muted-foreground/70">
                    <div className="h-3.5 w-3.5 rounded-full border border-muted-foreground/40 shrink-0" />
                    <span>4. Counterevidence Validation (Guards & Tests)</span>
                  </div>
                  <div className="flex items-center gap-2 text-muted-foreground/70">
                    <div className="h-3.5 w-3.5 rounded-full border border-muted-foreground/40 shrink-0" />
                    <span>5. Multidimensional Priority Scoring (0-100)</span>
                  </div>
                </div>
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
            currentFilePath={selectedFile?.path}
            onReopenBugs={(reopened, target) => {
              setBugResult(reopened);
              if (target) handleTargetChange(target);
              setActiveMobileTab('results');
              setHistoryOpen(false);
            }}
          />
        }
      />

      {/* Week 3 Day 1 (F31): Create GitHub Issue & Task Modal */}
      <CreateIssueModal
        isOpen={Boolean(issueFinding)}
        onClose={() => setIssueFinding(null)}
        repositoryId={repoId}
        finding={issueFinding}
        sourceType="BUG_FINDING"
      />
    </>
  );
}

export default RepositoryBugStudio;
