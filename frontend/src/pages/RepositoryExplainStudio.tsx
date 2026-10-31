import { useState, useMemo, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Sparkles,
  MessageSquare,
  ArrowRight,
  BookOpen,
  RefreshCw,
} from 'lucide-react';
import { useRepositoryFiles } from '../hooks/useRepositories';
import { useExplainCode } from '../hooks/useAnalysis';
import { useStudioFile } from '../hooks/useStudioFile';
import { CodeViewer } from '../components/explorer/CodeViewer';
import { ExplanationResultView } from '../components/explorer/ExplanationResultView';
import { AnalysisHistoryDrawer } from '../components/explorer/AnalysisHistoryDrawer';
import { StudioLayout } from '../components/studios/StudioLayout';
import { ErrorMessage } from '../components/shared/ErrorMessage';
import type { SourceReference, CodeExplanation, CodeExplanationResponse } from '../types/analysis';

export function RepositoryExplainStudio() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const repoId = id ?? '';
  const { data: filesData, isLoading: filesLoading } = useRepositoryFiles(repoId, 1, 500);
  const files = useMemo(() => filesData?.items ?? [], [filesData]);

  const [historyOpen, setHistoryOpen] = useState(false);
  const [activeSourceReference, setActiveSourceReference] = useState<SourceReference | null>(null);
  const [explanationResult, setExplanationResult] = useState<CodeExplanation | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
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
    setExplanationResult(null);
    setRunId(null);
  });

  // Explain mutation
  const explainMutation = useExplainCode(repoId, {
    onSuccess: (data: CodeExplanationResponse) => {
      setExplanationResult(data.explanation);
      setRunId(data.run_id);
      setActiveMobileTab('results');
    },
  });

  const handleRunExplain = useCallback(() => {
    if (!selectedFile || explainMutation.isPending) return;

    explainMutation.mutate({
      target: activeTarget,
    });
  }, [selectedFile, activeTarget, explainMutation]);

  // Keyboard shortcut: Cmd/Ctrl + Enter triggers explain
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        handleRunExplain();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleRunExplain]);

  // Jump to citation source in code viewer
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

  const handleAskFollowUp = () => {
    if (!selectedFile) return;
    navigate(`/app/repositories/${repoId}/chat?file=${encodeURIComponent(selectedFile.path)}`);
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
      historyTitle="View explanation history"
      actionButton={
        <button
          onClick={handleRunExplain}
          disabled={!selectedFile || explainMutation.isPending}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-primary hover:bg-primary/90 text-primary-foreground text-xs font-medium transition-colors shadow-xs disabled:opacity-50"
        >
          {explainMutation.isPending ? (
            <>
              <RefreshCw className="h-3.5 w-3.5 animate-spin" />
              <span>Explaining...</span>
            </>
          ) : (
            <>
              <Sparkles className="h-3.5 w-3.5" />
              <span>Explain Code</span>
              <span className="hidden lg:inline text-[10px] opacity-75 font-mono ml-1">⌘↵</span>
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
            onTriggerExplain={handleRunExplain}
            isAnalyzing={explainMutation.isPending}
          />
        ) : (
          <div className="flex-1 flex items-center justify-center p-8 text-center text-muted-foreground text-xs">
            Select a file to inspect its source code.
          </div>
        )
      }
      resultsPanel={
        <div className="flex-1 min-w-0 h-full flex flex-col min-h-0 overflow-y-auto bg-card/30 p-4 lg:p-6">
          {explainMutation.isPending ? (
            <div className="flex-1 flex flex-col items-center justify-center p-8 text-center space-y-3">
              <div className="h-12 w-12 rounded-full bg-primary/10 border border-primary/20 flex items-center justify-center text-primary animate-pulse">
                <Sparkles className="h-6 w-6 animate-spin" />
              </div>
              <h3 className="text-sm font-semibold text-foreground">Analyzing code structure & dependencies...</h3>
              <p className="text-xs text-muted-foreground max-w-sm">
                Generating architectural overview, step-by-step logic flow, key symbols, and grounded citations.
              </p>
            </div>
          ) : explainMutation.isError ? (
            <div className="p-4">
              <ErrorMessage error={explainMutation.error} />
            </div>
          ) : explanationResult ? (
            <div className="space-y-4">
              <div className="flex items-center justify-between pb-3 border-b border-border">
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-primary/10 text-primary border border-primary/20">
                    Grounded Explanation
                  </span>
                  {runId && (
                    <span className="text-[10px] text-muted-foreground font-mono">
                      Run #{runId.slice(0, 8)}
                    </span>
                  )}
                </div>

                <button
                  onClick={handleAskFollowUp}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md border border-border bg-background hover:bg-accent text-foreground transition-colors"
                >
                  <MessageSquare className="h-3.5 w-3.5 text-primary" />
                  <span>Ask Follow-up in Chat</span>
                  <ArrowRight className="h-3 w-3" />
                </button>
              </div>

              <ExplanationResultView
                explanation={explanationResult}
                activeSourceReference={activeSourceReference}
                onSelectSourceReference={handleSelectSourceReference}
              />
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center p-8 text-center max-w-md mx-auto space-y-4">
              <div className="h-12 w-12 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary shadow-xs">
                <BookOpen className="h-6 w-6" />
              </div>
              <div>
                <h3 className="text-base font-semibold text-foreground tracking-tight">Code Explainer Studio</h3>
                <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">
                  Understand architecture, control flow, key interfaces, and edge cases. Select a file or line range on the left and click &ldquo;Explain Code&rdquo;.
                </p>
              </div>

              <div className="w-full pt-2">
                <button
                  onClick={handleRunExplain}
                  disabled={!selectedFile}
                  className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 text-xs font-medium rounded-md bg-primary hover:bg-primary/90 text-primary-foreground transition-colors shadow-xs"
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  <span>Explain Current File ({selectedFile?.path.split('/').pop() ?? 'None'})</span>
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
          initialFeature="explain"
          currentFilePath={selectedFile?.path}
          onReopenExplain={(explanation, target, run) => {
            setExplanationResult(explanation);
            handleTargetChange(target);
            setRunId(run);
            setActiveMobileTab('results');
            setHistoryOpen(false);
          }}
        />
      }
    />
  );
}

export default RepositoryExplainStudio;
