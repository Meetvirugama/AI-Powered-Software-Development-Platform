import { useState, useMemo, useCallback, useEffect } from 'react';
import { useParams, useSearchParams, useNavigate } from 'react-router-dom';
import {
  Sparkles,
  BookOpen,
  History,
  FolderOpen,
  MessageSquare,
  ArrowRight,
  RefreshCw,
  Hash,
} from 'lucide-react';
import { useRepositoryFiles } from '../hooks/useRepositories';
import { useExplainCode } from '../hooks/useAnalysis';
import { CodeViewer } from '../components/explorer/CodeViewer';
import { ExplanationResultView } from '../components/explorer/ExplanationResultView';
import { AnalysisHistoryDrawer } from '../components/explorer/AnalysisHistoryDrawer';
import { TargetFilePicker } from '../components/studios/TargetFilePicker';
import { ErrorMessage } from '../components/shared/ErrorMessage';
import type { RepositoryFile } from '../types/api';
import type {
  AnalysisTarget,
  SourceReference,
  CodeExplanation,
  CodeExplanationResponse,
} from '../types/analysis';

export function RepositoryExplainStudio() {
  const { id } = useParams<{ id: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

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
  const [explanationResult, setExplanationResult] = useState<CodeExplanation | null>(null);
  const [runId, setRunId] = useState<string | null>(null);

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

  // Explain mutation
  const explainMutation = useExplainCode(repoId, {
    onSuccess: (data: CodeExplanationResponse) => {
      setExplanationResult(data.explanation);
      setRunId(data.run_id);
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

  const handleAskFollowUp = () => {
    if (!selectedFile) return;
    navigate(`/app/repositories/${repoId}/chat?file=${encodeURIComponent(selectedFile.path)}`);
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

          {activeTarget.start_line && activeTarget.end_line && (
            <div className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-accent text-[11px] font-mono text-muted-foreground border border-border">
              <Hash className="h-3 w-3" />
              <span>L{activeTarget.start_line}–L{activeTarget.end_line}</span>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => setHistoryOpen(true)}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border border-border bg-background hover:bg-accent text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
            title="View explanation history"
          >
            <History className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">History</span>
          </button>

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
              onTriggerExplain={handleRunExplain}
              isAnalyzing={explainMutation.isPending}
            />
          ) : (
            <div className="flex-1 flex items-center justify-center p-8 text-center text-muted-foreground text-xs">
              Select a file to inspect its source code.
            </div>
          )}
        </div>

        {/* Right Pane: Explanation Canvas */}
        <div className="flex-1 h-full flex flex-col min-h-0 overflow-y-auto bg-card/30 p-4 lg:p-6">
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
              <ErrorMessage
                error={explainMutation.error}
              />
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
      </div>

      {/* History Drawer */}
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
          setHistoryOpen(false);
        }}
      />
    </div>
  );
}

export default RepositoryExplainStudio;
