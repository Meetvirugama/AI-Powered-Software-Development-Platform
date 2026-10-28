import { useState, useMemo, useEffect } from 'react';
import { useParams, Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  useRepository,
  useRepositoryFiles,
  useRepositoryDependencies,
  useSyncRepository,
  useDeleteRepository,
  syncProgressFromStatus,
} from '../hooks/useRepositories';
import { getRepositoryFiles, lookupRepositoryFileByPath } from '../services/repositories';
import { checkProposedTestPath } from '../lib/testPath';
import { normalizeFilePath, findMatchingRepositoryFile } from '../lib/sourceReference';
import { LoadingSpinner } from '../components/shared/LoadingSpinner';
import { ErrorMessage } from '../components/shared/ErrorMessage';
import { FileTree } from '../components/explorer/FileTree';
import { CodeViewer } from '../components/explorer/CodeViewer';
import { AnalysisActionBar } from '../components/explorer/AnalysisActionBar';
import { AnalysisResultPanel } from '../components/explorer/AnalysisResultPanel';
import { AnalysisHistoryDrawer } from '../components/explorer/AnalysisHistoryDrawer';
import { RepositoryHeader } from '../components/explorer/RepositoryHeader';
import { RepositorySyncCard } from '../components/explorer/RepositorySyncCard';
import { RepositoryMetricsSidebar } from '../components/explorer/RepositoryMetricsSidebar';
import { WorkbenchHeader } from '../components/explorer/WorkbenchHeader';
import { CodeViewerEmptyState } from '../components/explorer/CodeViewerEmptyState';
import { FilePreviewModal } from '../components/explorer/FilePreviewModal';
import { ArrowLeft } from 'lucide-react';
import {
  useExplainCode,
  useDetectBugs,
  useGenerateTests,
  useReviewCode,
} from '../hooks/useAnalysis';
import { useAnalysisState } from '../hooks/useAnalysisState';
import type { RepositoryFile } from '../types/api';
import type {
  AnalysisFeatureType,
  AnalysisTarget,
  SourceReference,
  CodeExplanation,
  BugDetectionResponse,
  TestGenerationResponse,
  ReviewReportResponse,
  ReviewTarget,
  SupportedTestFramework,
  SymbolSummary,
} from '../types/analysis';

const SYNC_POLL_INTERVAL_MS = 3000;

/**
 * Render the route's repository explorer and analysis workbench.
 * Decomposed into focused modular components:
 * - RepositoryHeader: metadata, resync, delete alert, chat action
 * - RepositorySyncCard: sync progress stages and retry
 * - RepositoryMetricsSidebar: codebase metrics and searchable dependencies
 * - WorkbenchHeader: path, metrics, analysis toggles, fullscreen
 * - FileTree & CodeViewer: file navigation and syntax-highlighted code inspection
 * - CodeViewerEmptyState: cited file loading, missing, and empty selection states
 * - AnalysisResultPanel & AnalysisActionBar: deep-dive developer intelligence
 * - AnalysisHistoryDrawer & FilePreviewModal: overlay drawers and modals
 */
export function RepositoryDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const fileParam = searchParams.get('file');
  const startParam = searchParams.get('start');
  const endParam = searchParams.get('end');
  const symbolParam = searchParams.get('symbol');

  const [userSelectedFile, setUserSelectedFile] = useState<RepositoryFile | null>(null);
  const [showModal, setShowModal] = useState(false);

  // ------------------------------------------------------------------
  // Developer Intelligence State (F-03, F-05)
  // ------------------------------------------------------------------
  const {
    activeFeature,
    setActiveFeature,
    states: analysisStates,
    currentStatus: analysisStatus,
    currentError: analysisError,
    isAnyAnalysisPending,
    startAnalysis,
    completeAnalysis,
    failAnalysis,
    resetFileFeatures,
    reopenFeature,
  } = useAnalysisState(null);

  const [isHistoryDrawerOpen, setIsHistoryDrawerOpen] = useState(false);
  const [customTarget, setCustomTarget] = useState<AnalysisTarget | null>(null);
  const [reviewTarget, setReviewTarget] = useState<ReviewTarget>({
    type: 'file',
    path: '',
  });
  const [selectedFrameworkOverride, setSelectedFrameworkOverride] = useState<SupportedTestFramework | null>(null);
  const [explainedFile, setExplainedFile] = useState<RepositoryFile | null>(null);
  const [userHighlightedSource, setUserHighlightedSource] = useState<SourceReference | null | undefined>(undefined);

  // ------------------------------------------------------------------
  // Mutations with per-feature state isolation & stale response protection
  // ------------------------------------------------------------------
  const { mutate: triggerSync, isPending: isSyncPending } = useSyncRepository();
  const { mutate: deleteRepo, isPending: isDeletePending } = useDeleteRepository();

  const { mutate: triggerExplain, isPending: isExplainPending } = useExplainCode(id || '', {
    onSuccess: (data, variables) => {
      completeAnalysis('explain', data.explanation, variables.target, data.run_id);
    },
    onError: (err, variables) => {
      failAnalysis('explain', err, variables.target);
    },
  });

  const { mutate: triggerDetectBugs, isPending: isDetectBugsPending } = useDetectBugs(id || '', {
    onSuccess: (data, variables) => {
      completeAnalysis('bugs', data, variables.target, data.run_id);
    },
    onError: (err, variables) => {
      failAnalysis('bugs', err, variables.target);
    },
  });

  const { mutate: triggerGenerateTests, isPending: isGenerateTestsPending } = useGenerateTests(id || '', {
    onSuccess: (data, variables) => {
      completeAnalysis('tests', data, variables.target, data.run_id);
    },
    onError: (err, variables) => {
      failAnalysis('tests', err, variables.target);
    },
  });

  const { mutate: triggerReview, isPending: isReviewPending } = useReviewCode(id || '', {
    onSuccess: (data, variables) => {
      completeAnalysis('review', data, variables.target, data.run_id);
    },
    onError: (err, variables) => {
      failAnalysis('review', err, variables.target);
    },
  });

  // Reopen callbacks for universal history drawer
  function handleReopenExplain(explanation: CodeExplanation, target: AnalysisTarget, runId: string) {
    reopenFeature('explain', explanation, target, runId);
    setCustomTarget(target);
  }

  function handleReopenBugs(result: BugDetectionResponse, target: AnalysisTarget, runId: string) {
    reopenFeature('bugs', result, target, runId);
    setCustomTarget(target);
  }

  function handleReopenTests(result: TestGenerationResponse, target: AnalysisTarget, runId: string) {
    reopenFeature('tests', result, target, runId);
    setCustomTarget(target);
  }

  function handleReopenReview(result: ReviewReportResponse) {
    reopenFeature('review', result, result.target, result.run_id);
    if (result.target) {
      setReviewTarget(result.target);
    }
  }

  // ------------------------------------------------------------------
  // Data Fetching
  // ------------------------------------------------------------------
  const {
    data: repo,
    isLoading: repoLoading,
    isError: repoError,
    error: repoErrorData,
  } = useRepository(id, {
    refetchInterval: (query: any) => {
      const status = query.state.data?.sync_status;
      return status === 'SYNCING' ? SYNC_POLL_INTERVAL_MS : false;
    },
  });

  const progress = repo ? syncProgressFromStatus(repo.sync_status) : null;
  const isReady = progress?.isComplete ?? false;

  // Loaded files state supporting server-side pagination and load-more
  const [extraLoadedFiles, setExtraLoadedFiles] = useState<RepositoryFile[]>([]);
  const [currentPage, setCurrentPage] = useState(1);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [lookupAttemptedPath, setLookupAttemptedPath] = useState<string | null>(null);

  // Only fetch files and dependencies if the repository is successfully synced
  const {
    data: filesData,
    isLoading: filesLoading,
    isError: filesError,
  } = useRepositoryFiles(id, 1, 500, { enabled: isReady });

  // Reset extra pages when repository ID changes
  const [prevId, setPrevId] = useState(id);
  if (prevId !== id) {
    setPrevId(id);
    setExtraLoadedFiles([]);
    setCurrentPage(1);
    setLookupAttemptedPath(null);
  }

  // Merge page 1 items with extraLoadedFiles (deduplicated by id)
  const loadedFiles = useMemo(() => {
    const base = filesData?.items ?? [];
    if (extraLoadedFiles.length === 0) return base;
    const map = new Map(base.map((f) => [f.id, f]));
    for (const f of extraLoadedFiles) {
      map.set(f.id, f);
    }
    return Array.from(map.values());
  }, [filesData?.items, extraLoadedFiles]);

  async function handleLoadMoreFiles() {
    if (!id || isLoadingMore) return;
    const nextPage = currentPage + 1;
    setIsLoadingMore(true);
    try {
      const res = await getRepositoryFiles(id, { page: nextPage, pageSize: 500 });
      if (res.items.length > 0) {
        setExtraLoadedFiles((prev) => {
          const map = new Map(prev.map((f) => [f.id, f]));
          for (const item of res.items) {
            map.set(item.id, item);
          }
          return Array.from(map.values());
        });
        setCurrentPage(nextPage);
      }
    } catch (err) {
      console.error('Failed to load more repository files', err);
    } finally {
      setIsLoadingMore(false);
    }
  }

  // Derive whether an active async lookup is underway
  const isLookingUpPath = useMemo(() => {
    if (!id || !fileParam || !isReady || filesLoading) return false;
    const alreadyLoaded = findMatchingRepositoryFile(loadedFiles, fileParam);
    if (alreadyLoaded) return false;
    return lookupAttemptedPath !== fileParam;
  }, [id, fileParam, isReady, filesLoading, loadedFiles, lookupAttemptedPath]);

  // Check if cited file from query parameters is already loaded or needs direct backend path lookup
  useEffect(() => {
    if (!id || !fileParam || !isReady || filesLoading) return;
    const alreadyLoaded = findMatchingRepositoryFile(loadedFiles, fileParam);
    if (alreadyLoaded) return;
    if (lookupAttemptedPath === fileParam) return;

    let cancelled = false;
    lookupRepositoryFileByPath(id, fileParam)
      .then((file) => {
        if (!cancelled) {
          setLookupAttemptedPath(fileParam);
          if (file) {
            setExtraLoadedFiles((prev) => {
              if (prev.some((f) => f.id === file.id)) return prev;
              return [...prev, file];
            });
          }
        }
      })
      .catch(() => {
        if (!cancelled) setLookupAttemptedPath(fileParam);
      });

    return () => {
      cancelled = true;
    };
  }, [id, fileParam, isReady, filesLoading, loadedFiles, lookupAttemptedPath]);

  const {
    data: dependencies,
    isLoading: depsLoading,
    isError: depsError,
  } = useRepositoryDependencies(id, { enabled: isReady });

  // Check if cited file from query parameters is unavailable in indexed files
  const citedFileUnavailable = useMemo(() => {
    if (!fileParam || filesLoading || isLookingUpPath) return null;
    const matching = findMatchingRepositoryFile(loadedFiles, fileParam);
    if (matching) return null;

    const isListComp = (filesData?.total ?? loadedFiles.length) <= loadedFiles.length;
    if (lookupAttemptedPath === fileParam || isListComp) {
      return fileParam;
    }
    return null;
  }, [fileParam, loadedFiles, filesLoading, isLookingUpPath, lookupAttemptedPath, filesData]);

  // Deep-linked cited source reference computed declaratively from searchParams
  const deepLinkedHighlight = useMemo<SourceReference | null>(() => {
    if (!fileParam || !startParam || loadedFiles.length === 0) return null;
    const start = parseInt(startParam, 10);
    if (isNaN(start) || start <= 0) return null;
    const end = endParam ? parseInt(endParam, 10) : start;
    const validEnd = !isNaN(end) && end >= start ? end : start;

    const matching = findMatchingRepositoryFile(loadedFiles, fileParam);
    if (!matching) return null;

    return {
      file_path: matching.path,
      start_line: start,
      end_line: validEnd,
      symbol_name: symbolParam || undefined,
      symbol: symbolParam || undefined,
    };
  }, [fileParam, startParam, endParam, symbolParam, loadedFiles]);

  // Active highlighted source: uses explicit user interaction if set, otherwise deep-linked citation
  const highlightedSource =
    userHighlightedSource !== undefined ? userHighlightedSource : deepLinkedHighlight;

  // Auto-select initial file (prefer user-selected, query param file, README.md, or first file) once files load
  const selectedFile = useMemo(() => {
    if (userSelectedFile) return userSelectedFile;
    if (fileParam && loadedFiles.length > 0) {
      const matching = findMatchingRepositoryFile(loadedFiles, fileParam);
      if (matching) return matching;
      if (isLookingUpPath) return null;
      return null;
    }
    if (citedFileUnavailable) return null;
    if (loadedFiles.length === 0) return null;
    const readme = loadedFiles.find((f) => f.path.toLowerCase().endsWith('readme.md'));
    return readme ?? loadedFiles[0];
  }, [userSelectedFile, fileParam, citedFileUnavailable, loadedFiles, isLookingUpPath]);

  // Derived active target: defaults to full file unless user targeted a symbol/range on current file
  const activeTarget: AnalysisTarget = useMemo(() => {
    if (customTarget && customTarget.path === selectedFile?.path) {
      return customTarget;
    }
    return {
      type: 'file',
      path: selectedFile?.path ?? '',
    };
  }, [customTarget, selectedFile]);

  function handleSync() {
    if (id) triggerSync(id);
  }

  function handleDelete() {
    if (id) {
      deleteRepo(id, {
        onSuccess: () => {
          navigate('/app/dashboard');
        },
      });
    }
  }

  // Detect whether proposed test path collides with an existing file in the repository or is unverified
  const isListComplete = (filesData?.total ?? loadedFiles.length) <= loadedFiles.length;
  const [asyncPathCollision, setAsyncPathCollision] = useState<Record<string, 'EXISTS' | 'NEW'>>({});

  useEffect(() => {
    const proposed = analysisStates.tests.result?.result?.proposed_test_path;
    if (!proposed || !id || isListComplete) return;

    const localStatus = checkProposedTestPath(proposed, loadedFiles, false, false, false);
    if (localStatus === 'EXISTS') return;

    let cancelled = false;
    lookupRepositoryFileByPath(id, proposed)
      .then((file) => {
        if (!cancelled) {
          setAsyncPathCollision((prev) => ({
            ...prev,
            [proposed]: file ? 'EXISTS' : 'NEW',
          }));
        }
      })
      .catch(() => {
        // Leave as UNKNOWN if network fails
      });

    return () => {
      cancelled = true;
    };
  }, [analysisStates.tests.result?.result?.proposed_test_path, id, isListComplete, loadedFiles]);

  const proposedTestPathStatus = useMemo<'EXISTS' | 'NEW' | 'UNKNOWN'>(() => {
    const proposed = analysisStates.tests.result?.result?.proposed_test_path;
    if (!proposed) return 'UNKNOWN';
    if (asyncPathCollision[proposed]) return asyncPathCollision[proposed];
    return checkProposedTestPath(
      proposed,
      loadedFiles,
      filesLoading,
      filesError,
      isListComplete
    );
  }, [analysisStates.tests.result, loadedFiles, filesLoading, filesError, isListComplete, asyncPathCollision]);

  const proposedTestPathExists = proposedTestPathStatus === 'EXISTS';

  const isAnalysisPending =
    isAnyAnalysisPending ||
    isExplainPending ||
    isDetectBugsPending ||
    isGenerateTestsPending ||
    isReviewPending;

  function handleRunAnalysis(
    feature: AnalysisFeatureType,
    target: AnalysisTarget,
    frameworkOverride?: SupportedTestFramework | null
  ) {
    if (isAnalysisPending) return;

    if (!target.path && feature !== 'review') {
      failAnalysis(feature, 'Please select a source file from the explorer before requesting an analysis.');
      return;
    }

    startAnalysis(feature, target);
    const targetRevision = selectedFile?.content_hash || repo?.default_branch || 'main';

    if (feature === 'explain') {
      setExplainedFile(selectedFile);
      triggerExplain({
        target: {
          type: target.type,
          path: target.path,
          start_line: target.start_line,
          end_line: target.end_line,
          symbol: target.symbol,
          revision: targetRevision,
        },
        options: {
          include_context: true,
          max_context_tokens: 10000,
          persist_run: true,
        },
      });
      return;
    }

    if (feature === 'bugs') {
      triggerDetectBugs({
        target: {
          type: target.type,
          path: target.path,
          start_line: target.start_line,
          end_line: target.end_line,
          symbol: target.symbol,
          revision: targetRevision,
        },
        options: {
          include_context: true,
          max_context_tokens: 10000,
          persist_run: true,
        },
        include_static: true,
        include_ai: true,
        min_severity: 'LOW',
      });
      return;
    }

    if (feature === 'tests') {
      const activeRunner =
        frameworkOverride !== undefined ? frameworkOverride : selectedFrameworkOverride;
      triggerGenerateTests({
        target: {
          type: target.type,
          path: target.path,
          start_line: target.start_line,
          end_line: target.end_line,
          symbol: target.symbol,
          revision: targetRevision,
        },
        options: {
          include_context: true,
          max_context_tokens: 10000,
          persist_run: true,
        },
        framework: activeRunner || undefined,
      });
      return;
    }

    if (feature === 'review') {
      const activeReviewTarget: ReviewTarget =
        reviewTarget && (reviewTarget.path || reviewTarget.commit_sha || reviewTarget.pr_number || reviewTarget.diff)
          ? reviewTarget
          : {
              type: 'file',
              path: target.path,
            };
      setReviewTarget(activeReviewTarget);
      triggerReview({
        target: activeReviewTarget,
        options: {
          include_context: true,
          max_context_tokens: 10000,
          persist_run: true,
        },
        include_static: true,
      });
      return;
    }
  }

  function handleRunReviewTarget(t: ReviewTarget) {
    if (isAnalysisPending) return;
    setReviewTarget(t);
    startAnalysis('review', t);
    triggerReview({
      target: t,
      options: {
        include_context: true,
        max_context_tokens: 10000,
        persist_run: true,
      },
      include_static: true,
    });
  }

  function handleFrameworkChange(framework: SupportedTestFramework | null) {
    setSelectedFrameworkOverride(framework);
    if (activeFeature === 'tests' && activeTarget.path && analysisStates.tests.result) {
      handleRunAnalysis('tests', activeTarget, framework);
    }
  }

  function handleRetry() {
    if (activeFeature === 'review') {
      handleRunReviewTarget(reviewTarget);
      return;
    }
    if (activeFeature) {
      handleRunAnalysis(activeFeature, activeTarget, selectedFrameworkOverride || undefined);
    }
  }

  function handleSelectSourceReference(source: SourceReference) {
    if (!source.file_path) {
      setUserHighlightedSource(null);
      return;
    }

    const targetNorm = normalizeFilePath(source.file_path);

    // If currently selected file matches
    if (selectedFile && normalizeFilePath(selectedFile.path) === targetNorm) {
      setUserHighlightedSource({
        ...source,
        file_path: selectedFile.path,
      });
      return;
    }

    // If cited reference points to a different file in the repository, navigate to it
    if (filesData?.items) {
      const matchingFile = findMatchingRepositoryFile(filesData.items, source.file_path);
      if (matchingFile) {
        setUserSelectedFile(matchingFile);
        setUserHighlightedSource({
          ...source,
          file_path: matchingFile.path,
        });
        return;
      }
    }

    // Target file is unavailable in the file tree
    setUserHighlightedSource(null);
  }

  function handleSelectSymbolFromExplanation(sym: SymbolSummary) {
    const targetFile = explainedFile || selectedFile;
    if (!targetFile) return;
    if (selectedFile?.id !== targetFile.id) {
      setUserSelectedFile(targetFile);
    }
    setCustomTarget({
      type: 'symbol',
      path: targetFile.path,
      symbol: sym.name,
      start_line: sym.start_line ?? undefined,
      end_line: sym.end_line ?? undefined,
    });
  }

  // ------------------------------------------------------------------
  // Loading & Error States
  // ------------------------------------------------------------------
  if (repoLoading) {
    return (
      <div className="flex h-[50vh] flex-col items-center justify-center gap-4">
        <LoadingSpinner size="lg" label="Loading repository details…" />
      </div>
    );
  }

  if (repoError || !repo || !progress) {
    return (
      <div className="flex flex-col items-start gap-4 p-4">
        <Link
          to="/app/dashboard"
          className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Dashboard
        </Link>
        <ErrorMessage
          message={repoErrorData instanceof Error ? repoErrorData.message : 'Repository not found.'}
        />
      </div>
    );
  }

  const isSyncActive = repo.sync_status === 'SYNCING' || isSyncPending;

  // ------------------------------------------------------------------
  // Main Render (Decomposed Fixed Workbench Layout)
  // ------------------------------------------------------------------
  return (
    <div className="h-full flex flex-col min-h-0 gap-3 md:gap-4 overflow-hidden">
      {/* Docked Repository Header with Disconnect Alert */}
      <RepositoryHeader
        repo={repo}
        progress={progress}
        isReady={isReady}
        isSyncActive={isSyncActive}
        isDeletePending={isDeletePending}
        onSync={handleSync}
        onDelete={handleDelete}
      />

      {/* Workbench Content Area */}
      {!isReady ? (
        <RepositorySyncCard
          repo={repo}
          progress={progress}
          isSyncActive={isSyncActive}
          onSync={handleSync}
        />
      ) : (
        <div className="flex-1 min-h-0 grid grid-cols-1 md:grid-cols-12 gap-3 md:gap-4 h-full">
          {/* Left Column: Metrics & Dependencies Explorer */}
          <div className="md:col-span-4 lg:col-span-3 min-h-0 h-full">
            <RepositoryMetricsSidebar
              repo={repo}
              totalFiles={filesData?.total}
              dependencies={dependencies}
              depsLoading={depsLoading}
              depsError={depsError}
            />
          </div>

          {/* Right Column: Code Intelligence Workbench */}
          <div className="md:col-span-8 lg:col-span-9 flex flex-col min-h-0 h-full">
            <div className="h-full min-h-0 flex flex-col rounded-xl border border-border bg-card shadow-sm overflow-hidden">
              {/* Workbench Header */}
              <WorkbenchHeader
                repositoryId={repo.id}
                selectedFile={selectedFile}
                activeFeature={activeFeature}
                onToggleAnalysisPanel={() => {
                  setActiveFeature((prev) => (prev ? null : 'explain'));
                }}
                onOpenHistory={() => setIsHistoryDrawerOpen(true)}
                onOpenFullscreen={() => setShowModal(true)}
              />

              {/* Developer Intelligence Action Bar */}
              {selectedFile && (
                <AnalysisActionBar
                  activeFeature={activeFeature}
                  activeTarget={activeTarget}
                  disabled={isAnalysisPending}
                  onOpenHistory={() => setIsHistoryDrawerOpen(true)}
                  onSelectFeature={(feat) => {
                    setActiveFeature((prev) => (prev === feat ? null : feat));
                  }}
                />
              )}

              {/* Workbench Split Workspace */}
              <div className="flex-1 min-h-0 flex flex-col sm:flex-row overflow-hidden">
                {/* Sub-pane 1: Interactive File Tree */}
                <div className="w-full sm:w-56 lg:w-64 border-b sm:border-b-0 sm:border-r border-border flex flex-col shrink-0 min-h-0 bg-muted/10">
                  <FileTree
                    files={loadedFiles}
                    totalFiles={filesData?.total}
                    hasMore={Boolean(filesData?.total && loadedFiles.length < filesData.total)}
                    isLoadingMore={isLoadingMore}
                    onLoadMore={handleLoadMoreFiles}
                    isLoading={filesLoading && loadedFiles.length === 0}
                    isError={filesError && loadedFiles.length === 0}
                    selectedFile={selectedFile}
                    onSelectFile={(file) => {
                      setUserSelectedFile(file);
                      setUserHighlightedSource(null);
                      resetFileFeatures(file.path);
                      setReviewTarget((prev) =>
                        prev.type === 'file' ? { type: 'file', path: file.path } : prev
                      );
                      setExplainedFile(null);
                    }}
                  />
                </div>

                {/* Sub-pane 2: Code Viewer & Symbols */}
                <div className="flex-1 min-w-0 flex flex-col min-h-0 bg-background/40">
                  {selectedFile && id ? (
                    <CodeViewer
                      key={selectedFile.id}
                      repositoryId={id}
                      file={selectedFile}
                      activeTarget={activeTarget}
                      onTargetChange={setCustomTarget}
                      highlightedSource={highlightedSource}
                      onClearHighlightedSource={() => setUserHighlightedSource(null)}
                      isAnalyzing={isAnalysisPending}
                      onTriggerExplain={() => {
                        setActiveFeature('explain');
                        handleRunAnalysis('explain', activeTarget);
                      }}
                    />
                  ) : (
                    <CodeViewerEmptyState
                      isLookingUpPath={isLookingUpPath}
                      fileParam={fileParam}
                      citedFileUnavailable={citedFileUnavailable}
                      filesLoading={filesLoading}
                      loadedFilesCount={loadedFiles.length}
                      totalFiles={filesData?.total}
                      isLoadingMore={isLoadingMore}
                      onLoadMoreFiles={handleLoadMoreFiles}
                    />
                  )}
                </div>

                {/* Sub-pane 3: Reusable Analysis Result Panel */}
                {activeFeature && (selectedFile || activeFeature === 'review') && (
                  <div className="w-full sm:w-80 lg:w-96 border-t sm:border-t-0 sm:border-l border-border flex flex-col shrink-0 min-h-0">
                    <AnalysisResultPanel
                      feature={activeFeature}
                      target={activeTarget}
                      status={analysisStatus}
                      error={analysisError}
                      errorCode={activeFeature ? analysisStates[activeFeature].errorCode : null}
                      explanation={activeFeature === 'explain' ? analysisStates.explain.result : null}
                      bugResult={activeFeature === 'bugs' ? analysisStates.bugs.result : null}
                      testResult={activeFeature === 'tests' ? analysisStates.tests.result : null}
                      reviewResult={activeFeature === 'review' ? analysisStates.review.result : null}
                      reviewTarget={reviewTarget}
                      repositoryId={id}
                      onOpenHistory={() => setIsHistoryDrawerOpen(true)}
                      onReopenReview={handleReopenReview}
                      onRunReviewTarget={handleRunReviewTarget}
                      activeFileTreePaths={loadedFiles.map((f) => f.path)}
                      proposedPathStatus={proposedTestPathStatus}
                      proposedPathExists={proposedTestPathExists}
                      sources={
                        activeFeature === 'explain'
                          ? analysisStates.explain.result?.sources || []
                          : activeFeature === 'tests'
                          ? analysisStates.tests.result?.result?.sources || []
                          : []
                      }
                      activeSourceReference={highlightedSource}
                      onSelectSourceReference={handleSelectSourceReference}
                      onSelectSymbol={handleSelectSymbolFromExplanation}
                      onSelectFramework={handleFrameworkChange}
                      selectedFrameworkOverride={selectedFrameworkOverride}
                      onClose={() => setActiveFeature(null)}
                      onRunAnalysis={handleRunAnalysis}
                      onRetry={handleRetry}
                    />
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Universal Analysis History & Reopen Drawer */}
      <AnalysisHistoryDrawer
        isOpen={isHistoryDrawerOpen}
        onClose={() => setIsHistoryDrawerOpen(false)}
        repositoryId={id}
        initialFeature={activeFeature || 'all'}
        currentFilePath={selectedFile?.path}
        onReopenExplain={handleReopenExplain}
        onReopenBugs={handleReopenBugs}
        onReopenTests={handleReopenTests}
        onReopenReview={handleReopenReview}
      />

      {/* Fullscreen Code Preview Modal */}
      {showModal && selectedFile && id && (
        <FilePreviewModal
          repositoryId={id}
          file={selectedFile}
          onClose={() => setShowModal(false)}
        />
      )}
    </div>
  );
}
