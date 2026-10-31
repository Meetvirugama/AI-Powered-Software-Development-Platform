import { useState, useMemo, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import {
  FileCheck,
  RefreshCw,
  ShieldCheck,
  PlusCircle,
} from 'lucide-react';
import { useRepositoryFiles } from '../hooks/useRepositories';
import { useReviewCode } from '../hooks/useAnalysis';
import { useStudioFile } from '../hooks/useStudioFile';
import { CodeViewer } from '../components/explorer/CodeViewer';
import { CodeReviewView } from '../components/explorer/CodeReviewView';
import { AnalysisHistoryDrawer } from '../components/explorer/AnalysisHistoryDrawer';
import { CreateIssueModal, type FindingForIssue } from '../components/explorer/CreateIssueModal';
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
  const [issueFinding, setIssueFinding] = useState<FindingForIssue | null>(null);

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
      target: activeTarget,
    });
  }, [selectedFile, activeTarget, reviewMutation]);

  const handleSelectSourceReference = useCallback(
    (source: SourceReference) => {
      setActiveSourceReference(source);
      setActiveMobileTab('source');
      if (source.file_path && selectedFile && source.file_path !== selectedFile.path) {
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
    },
    [files, selectedFile, handleSelectFile, handleTargetChange]
  );

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
        historyTitle="View review history"
        extraControls={
          reviewResult?.report ? (
            <div className="flex items-center gap-2">
              <div className="hidden sm:inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-500 border border-emerald-500/20 text-[11px] font-mono">
                <ShieldCheck className="h-3 w-3" />
                <span>Risk: {reviewResult.report.risk_level}</span>
                <span className="text-muted-foreground/60">·</span>
                <span>{reviewResult.report.total_findings} findings</span>
              </div>
              {reviewResult.report.findings && reviewResult.report.findings.length > 0 && (
                <button
                  type="button"
                  onClick={() => setIssueFinding(reviewResult.report.findings[0])}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border border-primary/40 bg-primary/10 hover:bg-primary/20 text-xs font-semibold text-primary transition-colors"
                  title="Create GitHub Issue & Task from top finding"
                >
                  <PlusCircle className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">Create Issue</span>
                </button>
              )}
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
                <h3 className="text-sm font-semibold text-foreground">Analyzing code quality & patterns...</h3>
                <p className="text-xs text-muted-foreground max-w-sm">
                  Synthesizing AST syntax metrics, complexity factors, and LLM architectural patterns.
                </p>
              </div>
            ) : reviewMutation.isError ? (
              <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
                <ErrorMessage
                  message={reviewMutation.error instanceof Error ? reviewMutation.error.message : 'Code review failed.'}
                />
                <button
                  onClick={handleRunReview}
                  className="mt-4 px-3 py-1.5 rounded-md bg-primary text-primary-foreground text-xs font-medium"
                >
                  Retry Review
                </button>
              </div>
            ) : reviewResult ? (
              <div className="max-w-4xl w-full mx-auto space-y-4">
                <CodeReviewView
                  result={reviewResult}
                  activeSourceReference={activeSourceReference}
                  onSelectSourceReference={handleSelectSourceReference}
                  repositoryId={repoId}
                />
              </div>
            ) : (
              <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-muted-foreground space-y-3">
                <FileCheck className="h-10 w-10 opacity-30 text-primary" />
                <h3 className="text-sm font-semibold text-foreground">Ready for Review</h3>
                <p className="text-xs max-w-sm">
                  Select a target file and trigger an intelligent architectural code review.
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
            initialFeature="review"
            currentFilePath={selectedFile?.path}
            onReopenReview={(review, target) => {
              setReviewResult(review);
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
        sourceType="REVIEW_FINDING"
      />
    </>
  );
}

export default RepositoryReviewStudio;
