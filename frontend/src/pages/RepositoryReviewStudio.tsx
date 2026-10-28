import { useState, useMemo, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import {
  FileCheck,
  History,
  FolderOpen,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react';
import { useRepositoryFiles } from '../hooks/useRepositories';
import { useReviewCode } from '../hooks/useAnalysis';
import { useStudioFile } from '../hooks/useStudioFile';
import { CodeViewer } from '../components/explorer/CodeViewer';
import { CodeReviewView } from '../components/explorer/CodeReviewView';
import { AnalysisHistoryDrawer } from '../components/explorer/AnalysisHistoryDrawer';
import { TargetFilePicker } from '../components/studios/TargetFilePicker';
import { ErrorMessage } from '../components/shared/ErrorMessage';
import { cn } from '../lib/utils';
import type { SourceReference, ReviewReportResponse } from '../types/analysis';

export function RepositoryReviewStudio() {
  const { id } = useParams<{ id: string }>();

  const repoId = id ?? '';
  const { data: filesData, isLoading: filesLoading } = useRepositoryFiles(repoId, 1, 500);
  const files = useMemo(() => filesData?.items ?? [], [filesData]);

  const [historyOpen, setHistoryOpen] = useState(false);
  const [activeSourceReference, setActiveSourceReference] = useState<SourceReference | null>(null);
  const [reviewResult, setReviewResult] = useState<ReviewReportResponse | null>(null);
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
    setReviewResult(null);
  });

  // Review mutation
  const reviewMutation = useReviewCode(repoId, {
    onSuccess: (data) => {
      setReviewResult(data);
      setActiveMobileTab('results');
    },
  });

  const handleRunReview = useCallback(() => {
    if (!selectedFile || reviewMutation.isPending) return;

    reviewMutation.mutate({
      target: {
        type: 'file',
        path: selectedFile.path,
      },
    });
  }, [selectedFile, reviewMutation]);

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

          {reviewResult?.report && (
            <div className="hidden sm:inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-500 border border-emerald-500/20 text-[11px] font-mono">
              <ShieldCheck className="h-3 w-3" />
              <span>Risk: {reviewResult.report.risk_level}</span>
              <span className="text-muted-foreground/60">·</span>
              <span>{reviewResult.report.total_findings} findings</span>
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
            </button>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => setHistoryOpen(true)}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border border-border bg-background hover:bg-accent text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
            title="View review history"
            aria-label="View review history"
          >
            <History className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">History</span>
          </button>

          <button
            onClick={handleRunReview}
            disabled={!selectedFile || reviewMutation.isPending}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-primary hover:bg-primary/90 text-primary-foreground text-xs font-medium transition-colors shadow-xs disabled:opacity-50"
          >
            {reviewMutation.isPending ? (
              <>
                <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                <span>Reviewing...</span>
              </>
            ) : (
              <>
                <FileCheck className="h-3.5 w-3.5" />
                <span>Run Code Review</span>
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
              onTriggerExplain={handleRunReview}
              isAnalyzing={reviewMutation.isPending}
            />
          ) : (
            <div className="flex-1 flex items-center justify-center p-8 text-center text-muted-foreground text-xs">
              Select a file to inspect its source code.
            </div>
          )}
        </div>

        {/* Right Pane: Code Review Findings Canvas */}
        <div
          className={cn(
            'flex-1 lg:w-1/2 min-w-0 h-full flex flex-col min-h-0 overflow-y-auto bg-card/30 p-4 lg:p-6',
            activeMobileTab !== 'results' && 'hidden lg:flex'
          )}
        >
          {reviewMutation.isPending ? (
            <div className="flex-1 flex flex-col items-center justify-center p-8 text-center space-y-3">
              <div className="h-12 w-12 rounded-full bg-primary/10 border border-primary/20 flex items-center justify-center text-primary animate-pulse">
                <FileCheck className="h-6 w-6 animate-spin" />
              </div>
              <h3 className="text-sm font-semibold text-foreground">Performing comprehensive code review...</h3>
              <p className="text-xs text-muted-foreground max-w-sm">
                Analyzing maintainability, performance bottlenecks, design pattern compliance, and testability.
              </p>
            </div>
          ) : reviewMutation.isError ? (
            <div className="p-4">
              <ErrorMessage
                error={reviewMutation.error}
              />
            </div>
          ) : reviewResult ? (
            <div className="space-y-4">
              <CodeReviewView
                result={reviewResult}
                activeSourceReference={activeSourceReference}
                onSelectSourceReference={(ref) => {
                  setActiveSourceReference(ref);
                  setActiveMobileTab('source');
                }}
                repositoryId={repoId}
              />
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center p-8 text-center max-w-md mx-auto space-y-4">
              <div className="h-12 w-12 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary shadow-xs">
                <FileCheck className="h-6 w-6" />
              </div>
              <div>
                <h3 className="text-base font-semibold text-foreground tracking-tight">Code Review & Quality Auditor</h3>
                <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">
                  Perform automated peer reviews on source files or branches. Receive categorized feedback on performance, security, maintainability, and architectural standards.
                </p>
              </div>

              <div className="w-full pt-2">
                <button
                  onClick={handleRunReview}
                  disabled={!selectedFile}
                  className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 text-xs font-medium rounded-md bg-primary hover:bg-primary/90 text-primary-foreground transition-colors shadow-xs"
                >
                  <FileCheck className="h-3.5 w-3.5" />
                  <span>Review Current File ({selectedFile?.path.split('/').pop() ?? 'None'})</span>
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
        initialFeature="review"
        currentFilePath={selectedFile?.path}
        onReopenReview={(review) => {
          setReviewResult(review);
          setActiveMobileTab('results');
          setHistoryOpen(false);
        }}
      />
    </div>
  );
}

export default RepositoryReviewStudio;
