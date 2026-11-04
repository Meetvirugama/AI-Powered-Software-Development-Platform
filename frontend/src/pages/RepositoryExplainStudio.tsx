import { useState, useMemo, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Sparkles,
  MessageSquare,
  ArrowRight,
  BookOpen,
  RefreshCw,
  GitFork,
  Search,
  Plus,
  X,
  FileCode,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { useRepositoryFiles } from '../hooks/useRepositories';
import { useExplainCode, useRelatedFiles } from '../hooks/useAnalysis';
import { useStudioFile } from '../hooks/useStudioFile';
import { CodeViewer } from '../components/explorer/CodeViewer';
import { ExplanationResultView } from '../components/explorer/ExplanationResultView';
import { AnalysisHistoryDrawer } from '../components/explorer/AnalysisHistoryDrawer';
import { StudioLayout } from '../components/studios/StudioLayout';
import { ErrorMessage } from '../components/shared/ErrorMessage';
import type {
  SourceReference,
  CodeExplanation,
  CodeExplanationResponse,
} from '../types/analysis';

const BADGE_COLOR_MAP: Record<string, string> = {
  imported_dependency: 'bg-blue-500/10 text-blue-400 border-blue-500/30',
  called_dependency: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/30',
  caller: 'bg-purple-500/10 text-purple-400 border-purple-500/30',
  type_definition: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
  database_model: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
  associated_test: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/30',
  indirect_dependency: 'bg-slate-500/10 text-slate-300 border-slate-500/30',
  semantic_match: 'bg-teal-500/10 text-teal-300 border-teal-500/30',
};

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

  // Related files state (Repository Intelligence Engine — task.md §6)
  const [userSelectedRelatedPaths, setUserSelectedRelatedPaths] = useState<Set<string> | null>(null);
  const [customSelectedFiles, setCustomSelectedFiles] = useState<string[]>([]);
  const [fileSearchQuery, setFileSearchQuery] = useState('');
  const [showSearchDropdown, setShowSearchDropdown] = useState(false);
  const [contextPanelExpanded, setContextPanelExpanded] = useState(true);

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
    setUserSelectedRelatedPaths(null);
    setCustomSelectedFiles([]);
  });

  // Automatically discover related files via React Query hook (task.md §6.1)
  const { data: relatedData, isLoading: isDiscovering } = useRelatedFiles(
    repoId,
    selectedFile?.path,
    activeTarget.symbol
  );

  const discoveredFiles = useMemo(() => relatedData?.related_files ?? [], [relatedData]);

  // Derive active selected paths: if user hasn't explicitly toggled, use preselected defaults
  const selectedRelatedPaths = useMemo(() => {
    if (userSelectedRelatedPaths !== null) return userSelectedRelatedPaths;
    return new Set(discoveredFiles.filter((item) => item.is_preselected).map((item) => item.path));
  }, [userSelectedRelatedPaths, discoveredFiles]);

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

    const allSelected = Array.from(
      new Set([...Array.from(selectedRelatedPaths), ...customSelectedFiles])
    );

    explainMutation.mutate({
      target: activeTarget,
      context: {
        include_graph_context: true,
        include_callers: true,
        include_dependencies: true,
        include_tests: true,
        include_semantic_search: true,
        selected_files: allSelected,
      },
    });
  }, [selectedFile, activeTarget, explainMutation, selectedRelatedPaths, customSelectedFiles]);

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

  // Toggle preselected discovered file checkbox
  const handleToggleRelatedFile = (filePath: string) => {
    setUserSelectedRelatedPaths((prev) => {
      const current = prev !== null ? prev : selectedRelatedPaths;
      const next = new Set(current);
      if (next.has(filePath)) {
        next.delete(filePath);
      } else {
        next.add(filePath);
      }
      return next;
    });
  };

  // Add custom file from repository search
  const handleAddCustomFile = (filePath: string) => {
    if (!customSelectedFiles.includes(filePath) && filePath !== selectedFile?.path) {
      setCustomSelectedFiles((prev) => [...prev, filePath]);
    }
    setFileSearchQuery('');
    setShowSearchDropdown(false);
  };

  // Remove custom file
  const handleRemoveCustomFile = (filePath: string) => {
    setCustomSelectedFiles((prev) => prev.filter((p) => p !== filePath));
  };

  // Search filtered files for dropdown
  const filteredRepoFiles = useMemo(() => {
    if (!fileSearchQuery.trim()) return [];
    const q = fileSearchQuery.toLowerCase();
    return files
      .filter(
        (f) =>
          f.path.toLowerCase().includes(q) &&
          f.path !== selectedFile?.path &&
          !customSelectedFiles.includes(f.path) &&
          !discoveredFiles.some((df) => df.path === f.path)
      )
      .slice(0, 8);
  }, [files, fileSearchQuery, selectedFile?.path, customSelectedFiles, discoveredFiles]);

  const totalSelectedCount = 1 + selectedRelatedPaths.size + customSelectedFiles.length;

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
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-primary hover:bg-primary/90 text-primary-foreground text-xs font-medium transition-colors shadow-xs disabled:opacity-50 cursor-pointer"
        >
          {explainMutation.isPending ? (
            <>
              <RefreshCw className="h-3.5 w-3.5 animate-spin" />
              <span>Explaining...</span>
            </>
          ) : (
            <>
              <Sparkles className="h-3.5 w-3.5" />
              <span>Explain with Repository Context</span>
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
            action={{
              label: 'Explain target',
              onClick: handleRunExplain,
              isPending: explainMutation.isPending,
            }}
            isAnalyzing={explainMutation.isPending}
          />
        ) : (
          <div className="flex-1 flex items-center justify-center p-8 text-center text-muted-foreground text-xs">
            Select a file to inspect its source code.
          </div>
        )
      }
      resultsPanel={
        <div className="flex-1 min-w-0 h-full flex flex-col min-h-0 overflow-y-auto bg-card/30 p-4 lg:p-6 space-y-4">
          {/* -------------------------------------------------------- */}
          {/* Repository Intelligence Context Panel (task.md §6)        */}
          {/* -------------------------------------------------------- */}
          {selectedFile && (
            <div className="rounded-xl border border-border/80 bg-background/70 backdrop-blur-xs p-3.5 space-y-3 shadow-xs">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  <GitFork className="h-4 w-4 text-primary shrink-0" />
                  <span className="font-semibold text-xs text-foreground truncate">
                    Repository Intelligence Context
                  </span>
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 shrink-0">
                    Indexed
                  </span>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="text-[11px] font-mono text-muted-foreground hidden sm:inline">
                    {totalSelectedCount} file{totalSelectedCount === 1 ? '' : 's'} in context
                  </span>
                  <button
                    type="button"
                    onClick={() => setContextPanelExpanded((p) => !p)}
                    className="p-1 text-muted-foreground hover:text-foreground rounded hover:bg-muted/30 transition-colors"
                    title={contextPanelExpanded ? 'Collapse context' : 'Expand context'}
                  >
                    {contextPanelExpanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                  </button>
                </div>
              </div>

              {contextPanelExpanded && (
                <div className="space-y-3 pt-1 border-t border-border/50">
                  {/* Selected Target Summary */}
                  <div className="text-[11px] text-muted-foreground flex flex-wrap items-center gap-1.5">
                    <span className="font-semibold text-foreground">Target Scope:</span>
                    <span className="font-mono text-primary bg-primary/10 px-1.5 py-0.5 rounded border border-primary/20">
                      {selectedFile.path}
                    </span>
                    {activeTarget.symbol && (
                      <span className="font-mono text-indigo-400 bg-indigo-500/10 px-1.5 py-0.5 rounded border border-indigo-500/20">
                        ::{activeTarget.symbol}
                      </span>
                    )}
                    {activeTarget.start_line && activeTarget.end_line && (
                      <span className="font-mono text-slate-400 bg-slate-500/10 px-1 py-0.5 rounded">
                        L{activeTarget.start_line}–{activeTarget.end_line}
                      </span>
                    )}
                  </div>

                  {/* Automatically Discovered Related Files (task.md §6.1) */}
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between text-[11px] font-semibold text-muted-foreground">
                      <span>Automatically Related Files</span>
                      {isDiscovering && (
                        <span className="flex items-center gap-1 text-[10px] text-primary">
                          <RefreshCw className="h-2.5 w-2.5 animate-spin" />
                          <span>Traversing graph...</span>
                        </span>
                      )}
                    </div>

                    {discoveredFiles.length > 0 ? (
                      <div className="space-y-1 max-h-36 overflow-y-auto pr-1">
                        {discoveredFiles.map((df) => {
                          const isChecked = selectedRelatedPaths.has(df.path);
                          const badgeColor =
                            BADGE_COLOR_MAP[df.relation] ||
                            'bg-slate-500/10 text-slate-300 border-slate-500/30';
                          return (
                            <label
                              key={df.path}
                              className="flex items-start gap-2 p-1.5 rounded-lg border border-border/50 bg-muted/10 hover:bg-muted/20 text-xs transition-colors cursor-pointer"
                            >
                              <input
                                type="checkbox"
                                checked={isChecked}
                                onChange={() => handleToggleRelatedFile(df.path)}
                                className="mt-0.5 rounded border-border text-primary focus:ring-primary h-3.5 w-3.5"
                              />
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-1.5 flex-wrap">
                                  <span className="font-mono text-[11px] text-foreground truncate">
                                    {df.path}
                                  </span>
                                  <span
                                    className={`px-1.5 py-0.2 rounded text-[10px] font-mono border ${badgeColor}`}
                                  >
                                    {df.relation_label}
                                  </span>
                                </div>
                                <p className="text-[10px] text-muted-foreground truncate mt-0.5">
                                  {df.reason}
                                </p>
                              </div>
                            </label>
                          );
                        })}
                      </div>
                    ) : (
                      <p className="text-[11px] text-muted-foreground italic">
                        {isDiscovering
                          ? 'Analyzing knowledge graph...'
                          : 'No direct callers or dependencies found; use search below to add context files.'}
                      </p>
                    )}
                  </div>

                  {/* Developer-selected custom files (task.md §6) */}
                  <div className="space-y-2 pt-1 border-t border-border/40">
                    <div className="flex items-center justify-between text-[11px] font-semibold text-muted-foreground">
                      <span>Additional Files Selected by Developer</span>
                      <span className="text-[10px] font-mono text-muted-foreground">
                        {customSelectedFiles.length} added
                      </span>
                    </div>

                    {/* Chips for added files */}
                    {customSelectedFiles.length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {customSelectedFiles.map((cp) => (
                          <span
                            key={cp}
                            className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-mono bg-primary/10 border border-primary/20 text-primary"
                          >
                            <FileCode className="h-3 w-3" />
                            <span className="truncate max-w-[200px]">{cp}</span>
                            <button
                              type="button"
                              onClick={() => handleRemoveCustomFile(cp)}
                              className="text-primary hover:text-foreground cursor-pointer"
                            >
                              <X className="h-3 w-3" />
                            </button>
                          </span>
                        ))}
                      </div>
                    )}

                    {/* Search repository files */}
                    <div className="relative">
                      <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-border bg-background text-xs">
                        <Search className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                        <input
                          type="text"
                          value={fileSearchQuery}
                          onChange={(e) => {
                            setFileSearchQuery(e.target.value);
                            setShowSearchDropdown(true);
                          }}
                          onFocus={() => setShowSearchDropdown(true)}
                          placeholder="Search repository files to include..."
                          className="w-full bg-transparent border-0 outline-hidden text-xs text-foreground placeholder:text-muted-foreground"
                        />
                        {fileSearchQuery && (
                          <button
                            type="button"
                            onClick={() => setFileSearchQuery('')}
                            className="text-muted-foreground hover:text-foreground"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        )}
                      </div>

                      {showSearchDropdown && filteredRepoFiles.length > 0 && (
                        <div className="absolute z-20 top-full mt-1 left-0 right-0 max-h-48 overflow-y-auto rounded-lg border border-border bg-popover shadow-lg py-1">
                          {filteredRepoFiles.map((f) => (
                            <button
                              key={f.path}
                              type="button"
                              onClick={() => handleAddCustomFile(f.path)}
                              className="w-full text-left px-2.5 py-1.5 hover:bg-accent text-xs font-mono flex items-center justify-between text-popover-foreground transition-colors cursor-pointer"
                            >
                              <span className="truncate">{f.path}</span>
                              <span className="inline-flex items-center gap-0.5 text-[10px] text-primary shrink-0 ml-2">
                                <Plus className="h-3 w-3" /> Add
                              </span>
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* -------------------------------------------------------- */}
          {/* Explanation Output / Pending / Error Views                */}
          {/* -------------------------------------------------------- */}
          {explainMutation.isPending ? (
            <div className="flex-1 flex flex-col items-center justify-center p-8 text-center space-y-3">
              <div className="h-12 w-12 rounded-full bg-primary/10 border border-primary/20 flex items-center justify-center text-primary animate-pulse">
                <Sparkles className="h-6 w-6 animate-spin" />
              </div>
              <h3 className="text-sm font-semibold text-foreground">
                Synthesizing repository intelligence...
              </h3>
              <p className="text-xs text-muted-foreground max-w-sm">
                Evaluating selected code with {totalSelectedCount} contextual repository files,
                traversing execution dependencies, and generating grounded citations.
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
                    Repository Intelligence Grounded
                  </span>
                  {runId && (
                    <span className="text-[10px] text-muted-foreground font-mono">
                      Run #{runId.slice(0, 8)}
                    </span>
                  )}
                </div>

                <button
                  onClick={handleAskFollowUp}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md border border-border bg-background hover:bg-accent text-foreground transition-colors cursor-pointer"
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
                <h3 className="text-base font-semibold text-foreground tracking-tight">
                  Intelligent Code Explainer Studio
                </h3>
                <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">
                  Deep repository understanding grounded in persistent AST knowledge graphs. Select
                  a file, adjust automatically discovered dependencies above, and click &ldquo;Explain
                  with Repository Context&rdquo;.
                </p>
              </div>

              <div className="w-full pt-2">
                <button
                  onClick={handleRunExplain}
                  disabled={!selectedFile}
                  className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 text-xs font-medium rounded-md bg-primary hover:bg-primary/90 text-primary-foreground transition-colors shadow-xs cursor-pointer"
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  <span>
                    Explain Current File ({selectedFile?.path.split('/').pop() ?? 'None'})
                  </span>
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
