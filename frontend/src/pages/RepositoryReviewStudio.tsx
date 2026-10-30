import { useState, useMemo, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import {
  FileCheck,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react';
import { useRepositoryFiles } from '../hooks/useRepositories';
import { useReviewCode } from '../hooks/useAnalysis';
import { useStudioFile } from '../hooks/useStudioFile';
import { CodeViewer } from '../components/explorer/CodeViewer';
import { CodeReviewView } from '../components/explorer/CodeReviewView';
import { AnalysisHistoryDrawer } from '../components/explorer/AnalysisHistoryDrawer';
import { StudioLayout } from '../components/studios/StudioLayout';
import { ErrorMessage } from '../components/shared/ErrorMessage';
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
      historyTitle="View review history"
      extraControls={
        reviewResult?.report ? (
          <div className="hidden sm:inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-500 border border-emerald-500/20 text-[11px] font-mono">
            <ShieldCheck className="h-3 w-3" />
            <span>Risk: {reviewResult.report.risk_level}</span>
            <span className="text-muted-foreground/60">·</span>
            <span>{reviewResult.report.total_findings} findings</span>
          </div>
        ) : undefined
      }
      actionButton={
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
            onTriggerExplain={handleRunReview}
            isAnalyzing={reviewMutation.isPending}
          />
        ) : (
          <div className="flex-1 flex items-center justify-center p-8 text-center text-muted-foreground text-xs">
            Select a file to inspect its source code.
          </div>
        )
      }
      resultsPanel={
        <div className="flex-1 min-w-0 h-full flex flex-col min-h-0 overflow-y-auto bg-card/30 p-4 lg:p-6">
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
              <ErrorMessage error={reviewMutation.error} />
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
      }
      historyDrawer={
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
      }
    />
  );
}

export default RepositoryReviewStudio;
