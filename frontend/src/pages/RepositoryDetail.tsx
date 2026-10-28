import { useState, useMemo, useEffect } from 'react';
import { useParams, Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  useRepository,
  useRepositoryFiles,
  useRepositoryDependencies,
  useSyncRepository,
  useDeleteRepository,
  useRepositoryFileContent,
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
import { cn } from '../lib/utils';
import {
  MessageSquare,
  ArrowLeft,
  CheckCircle2,
  RefreshCw,
  XCircle,
  Clock,
  History,
  FileText,
  FileCode,
  Box,
  Database,
  Code,
  Trash2,
  RotateCw,
  X,
  Search,
  Copy,
  Check,
  Maximize2,
  GitBranch,
  Layers,
  Sparkles,
} from 'lucide-react';
import {
  useExplainCode,
  useDetectBugs,
  useGenerateTests,
  useReviewCode,
} from '../hooks/useAnalysis';
import { useAnalysisState } from '../hooks/useAnalysisState';
import type { SyncStage, RepositoryFile } from '../types/api';
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

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SYNC_POLL_INTERVAL_MS = 3000;

/**
 * Normalize a repository file path for consistent matching across platforms:
 * - Trims leading and trailing whitespace
 * - Converts backslashes to forward slashes
 * - Strips leading relative prefixes ('./' or '/')
 * - Normalizes to lowercase for case-insensitive lookup
// ---------------------------------------------------------------------------
// Repository Detail Page (Code Intelligence Workbench)
// ---------------------------------------------------------------------------

/**
 * Render the route's repository explorer and analysis workbench.
 * The `file` query parameter selects a matching path among the first 100 fetched
 * files unless the user has selected a file. Matching ignores case, normalizes
 * separators and a leading `/` or `./`, and accepts suffixes at path boundaries.
 * Without a user selection, an unmatched citation shows an unavailable-file
 * message after files load; no `file` defaults to README.md or the first file.
 *
 * With a matching file, `start` supplies a positive, 1-based line number parsed
 * as an integer; `end` is inclusive and defaults to start if absent, invalid, or
 * earlier. `symbol` optionally labels the citation. Explicit highlight selection
 * or clearing takes precedence over this query-derived highlight.
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
  const [showConfirmDelete, setShowConfirmDelete] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [dependencyFilter, setDependencyFilter] = useState('');

  // ------------------------------------------------------------------
  // ------------------------------------------------------------------
  // Week 2 Developer Intelligence State (F-03, F-05)
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
      failAnalysis(
        'explain',
        err,
        variables.target
      );
    },
  });

  const { mutate: triggerDetectBugs, isPending: isDetectBugsPending } = useDetectBugs(id || '', {
    onSuccess: (data, variables) => {
      completeAnalysis('bugs', data, variables.target, data.run_id);
    },
    onError: (err, variables) => {
      failAnalysis(
        'bugs',
        err,
        variables.target
      );
    },
  });

  const { mutate: triggerGenerateTests, isPending: isGenerateTestsPending } = useGenerateTests(id || '', {
    onSuccess: (data, variables) => {
      completeAnalysis('tests', data, variables.target, data.run_id);
    },
    onError: (err, variables) => {
      failAnalysis(
        'tests',
        err,
        variables.target
      );
    },
  });

  const { mutate: triggerReview, isPending: isReviewPending } = useReviewCode(id || '', {
    onSuccess: (data, variables) => {
      completeAnalysis('review', data, variables.target, data.run_id);
    },
    onError: (err, variables) => {
      failAnalysis(
        'review',
        err,
        variables.target
      );
    },
  });

  // Reopen callbacks for universal history drawer (F-03)
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

  // Loaded files state supporting server-side pagination and load-more (F-02)
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

  // Reset extra pages when repository ID changes (render-phase state adjustment per React guidelines)
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

  // Check if cited file from query parameters is already loaded or needs direct backend path lookup (F-02)
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

  // Check if cited file from query parameters is unavailable in indexed files (F-02)
  const citedFileUnavailable = useMemo(() => {
    if (!fileParam || filesLoading || isLookingUpPath) return null;
    const matching = findMatchingRepositoryFile(loadedFiles, fileParam);
    if (matching) return null;

    const isListComplete = (filesData?.total ?? loadedFiles.length) <= loadedFiles.length;
    if (lookupAttemptedPath === fileParam || isListComplete) {
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

  // Filter dependencies
  const filteredDependencies = useMemo(() => {
    if (!dependencies) return [];
    if (!dependencyFilter.trim()) return dependencies;
    const q = dependencyFilter.toLowerCase();
    return dependencies.filter(
      (dep) => dep.name.toLowerCase().includes(q) || dep.ecosystem?.toLowerCase().includes(q)
    );
  }, [dependencies, dependencyFilter]);

  // Detect whether proposed test path collides with an existing file in the repository or is unverified (F-02)
  const isListComplete = (filesData?.total ?? loadedFiles.length) <= loadedFiles.length;
  const [asyncPathCollision, setAsyncPathCollision] = useState<Record<string, 'EXISTS' | 'NEW'>>({});

  useEffect(() => {
    const proposed = analysisStates.tests.result?.result?.proposed_test_path;
    if (!proposed || !id || isListComplete) return;

    // If already known from loaded files, no need for async lookup
    const localStatus = checkProposedTestPath(proposed, loadedFiles, false, false, false);
    if (localStatus === 'EXISTS') return;

    // List is incomplete and not in loadedFiles: perform backend lookup
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
    if (isAnalysisPending) {
      // Guard against duplicate simultaneous requests
      return;
    }

    if (!target.path && feature !== 'review') {
      failAnalysis(feature, 'Please select a source file from the explorer before requesting an analysis.');
      return;
    }

    startAnalysis(feature, target);

    // Stable revision resolution (F-06): use stable file content_hash or branch ref
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

  /**
   * Highlight a citation in the selected file or switch to the first matching
   * loaded file, storing its actual path. Missing or unmatched paths clear the
   * highlight without changing the selected file or restoring the URL highlight.
   */
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

    // Target file is unavailable in the file tree; do not highlight unrelated lines in current file
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
  // Main Render (Fixed Workbench Layout)
  // ------------------------------------------------------------------

  return (
    <div className="h-full flex flex-col min-h-0 gap-3 md:gap-4 overflow-hidden">
      {/* -------------------------------------------------------------- */}
      {/* Docked Repository Header                                        */}
      {/* -------------------------------------------------------------- */}
      <header className="shrink-0 space-y-2.5 bg-card/50 border border-border/80 rounded-xl p-3 sm:p-4 shadow-sm">
        {/* Navigation & Header Actions */}
        <div className="flex items-center justify-between gap-3">
          <Link
            to="/app/dashboard"
            className="inline-flex items-center gap-2 text-xs sm:text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            <span>Back to Dashboard</span>
          </Link>

          <div className="flex items-center gap-2 shrink-0">
            {/* Re-sync Button */}
            <button
              onClick={handleSync}
              disabled={isSyncActive}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-background px-2.5 py-1.5 text-xs font-medium text-foreground hover:bg-accent transition-colors disabled:opacity-50"
              title="Re-synchronize repository"
              aria-label="Re-synchronize repository"
            >
              <RotateCw className={cn('h-3.5 w-3.5', isSyncActive && 'animate-spin text-primary')} />
              <span className="hidden sm:inline">{isSyncActive ? 'Syncing…' : 'Re-sync'}</span>
            </button>

            {/* Disconnect Button */}
            <button
              onClick={() => setShowConfirmDelete(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-destructive/30 bg-destructive/5 px-2.5 py-1.5 text-xs font-medium text-destructive hover:bg-destructive/10 transition-colors"
              title="Disconnect repository"
              aria-label="Disconnect repository"
            >
              <Trash2 className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Disconnect</span>
            </button>

            {/* Chat with Repository Button */}
            <Link
              to={`/app/repositories/${repo.id}/chat`}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring shrink-0 shadow-sm',
                !progress.isComplete || progress.isFailed
                  ? 'pointer-events-none opacity-50'
                  : 'hover:bg-primary/90'
              )}
              aria-disabled={!progress.isComplete || progress.isFailed}
              tabIndex={!progress.isComplete || progress.isFailed ? -1 : undefined}
            >
              <MessageSquare className="h-3.5 w-3.5" />
              <span>Chat with this repository</span>
            </Link>
          </div>
        </div>

        {/* Repository Meta Details */}
        <div className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-2 pt-1 border-t border-border/50">
          <div className="flex flex-wrap items-baseline gap-2 min-w-0">
            <h1 className="text-lg sm:text-xl font-bold text-foreground tracking-tight truncate">
              {repo.name}
            </h1>
            <span className="text-xs text-muted-foreground font-mono truncate">
              {repo.full_name}
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-2 sm:gap-3 text-xs text-muted-foreground shrink-0">
            <div className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-muted/40 border border-border/60">
              <GitBranch className="h-3 w-3 text-muted-foreground" />
              <span className="font-mono">{repo.default_branch || 'main'}</span>
            </div>

            {repo.language && (
              <div className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-muted/40 border border-border/60">
                <Code className="h-3 w-3 text-primary" />
                <span>{repo.language}</span>
              </div>
            )}

            {repo.framework && (
              <div className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-muted/40 border border-border/60">
                <Box className="h-3 w-3 text-emerald-500" />
                <span>{repo.framework}</span>
              </div>
            )}

            <div
              className={cn(
                'inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-xs font-medium',
                isReady
                  ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                  : isSyncActive
                  ? 'bg-blue-500/10 border-blue-500/30 text-blue-400'
                  : 'bg-muted/40 border-border text-muted-foreground'
              )}
            >
              {isReady ? (
                <CheckCircle2 className="h-3 w-3" />
              ) : (
                <RefreshCw className={cn('h-3 w-3', isSyncActive && 'animate-spin')} />
              )}
              <span>{isSyncActive ? 'Syncing…' : progress.label}</span>
            </div>

            {repo.last_synced_at && (
              <div className="hidden md:inline-flex items-center gap-1 text-[11px] text-muted-foreground">
                <Clock className="h-3 w-3" />
                <span>Synced {new Date(repo.last_synced_at).toLocaleDateString()}</span>
              </div>
            )}
          </div>
        </div>

        {/* Optional Description */}
        {repo.description && (
          <p className="text-xs text-muted-foreground line-clamp-1 italic">
            {repo.description}
          </p>
        )}
      </header>

      {/* Disconnect Confirmation Alert */}
      {showConfirmDelete && (
        <div
          role="alert"
          className="shrink-0 rounded-xl border border-destructive/30 bg-destructive/10 p-3 sm:p-4 space-y-2 animate-in fade-in duration-200"
        >
          <div className="flex items-start justify-between">
            <div>
              <h3 className="font-semibold text-foreground text-sm">Disconnect {repo.name}?</h3>
              <p className="text-xs text-muted-foreground mt-0.5">
                This will delete repository indexing data, symbols, and vector chunks from this workspace.
              </p>
            </div>
            <button
              onClick={() => setShowConfirmDelete(false)}
              className="text-muted-foreground hover:text-foreground"
              aria-label="Cancel disconnect"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="flex items-center gap-2 justify-end">
            <button
              onClick={() => setShowConfirmDelete(false)}
              className="px-3 py-1 rounded-lg border border-border bg-background text-xs font-medium text-foreground hover:bg-accent"
            >
              Cancel
            </button>
            <button
              onClick={handleDelete}
              disabled={isDeletePending}
              className="px-3 py-1 rounded-lg bg-destructive text-destructive-foreground text-xs font-medium hover:bg-destructive/90 disabled:opacity-50"
            >
              {isDeletePending ? 'Deleting…' : 'Confirm Disconnect'}
            </button>
          </div>
        </div>
      )}

      {/* -------------------------------------------------------------- */}
      {/* Workbench Content Area                                         */}
      {/* -------------------------------------------------------------- */}
      {!isReady ? (
        <div className="flex-1 min-h-0 flex items-center justify-center p-4">
          <div className="w-full max-w-xl rounded-xl border border-border bg-card p-6 shadow-sm space-y-6">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div>
                <h2 className="text-base font-semibold text-foreground">
                  {progress.isFailed
                    ? 'Synchronization Failed'
                    : isSyncActive
                    ? 'Repository Synchronization in Progress'
                    : 'Repository Not Synced'}
                </h2>
                <p className="text-xs text-muted-foreground mt-1">
                  {progress.isFailed
                    ? 'An issue occurred during repository indexing. Click Retry to re-run the sync process.'
                    : isSyncActive
                    ? 'Files are being cloned, scanned, and indexed into the AI vector database.'
                    : 'This repository has not been indexed yet. Start synchronization to enable file explorer and AI chat.'}
                </p>
              </div>

              {(progress.isFailed || repo.sync_status === 'NOT_SYNCED') && (
                <button
                  onClick={handleSync}
                  disabled={isSyncActive}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50 shrink-0"
                >
                  <RefreshCw className={cn('h-3.5 w-3.5', isSyncActive && 'animate-spin')} />
                  <span>{isSyncActive ? 'Starting…' : 'Retry Sync'}</span>
                </button>
              )}
            </div>

            <SyncProgressIndicator
              currentStage={progress.stage}
              isFailed={progress.isFailed}
            />
          </div>
        </div>
      ) : (
        <div className="flex-1 min-h-0 grid grid-cols-1 md:grid-cols-12 gap-3 md:gap-4 h-full">
          {/* ---------------------------------------------------------- */}
          {/* Left Column: Metrics & Dependencies Explorer                */}
          {/* ---------------------------------------------------------- */}
          <div className="md:col-span-4 lg:col-span-3 flex flex-col gap-3 min-h-0 h-full">
            {/* Box A: Quick Statistics */}
            <div className="shrink-0 rounded-xl border border-border bg-card shadow-sm p-3.5 space-y-3">
              <div className="flex items-center justify-between border-b border-border/60 pb-2">
                <span className="font-semibold text-xs text-foreground uppercase tracking-wider flex items-center gap-1.5">
                  <Database className="h-3.5 w-3.5 text-primary" />
                  Codebase Metrics
                </span>
                <span className="text-[10px] text-muted-foreground font-mono">Live Index</span>
              </div>

              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="rounded-lg bg-muted/20 border border-border/50 p-2">
                  <div className="flex items-center justify-center gap-1 text-[11px] text-muted-foreground">
                    <FileText className="h-3 w-3" />
                    <span>Files</span>
                  </div>
                  <div className="font-bold text-base text-foreground mt-0.5">
                    {repo.file_count ?? filesData?.total ?? '-'}
                  </div>
                </div>

                <div className="rounded-lg bg-muted/20 border border-border/50 p-2">
                  <div className="flex items-center justify-center gap-1 text-[11px] text-muted-foreground">
                    <Code className="h-3 w-3" />
                    <span>Symbols</span>
                  </div>
                  <div className="font-bold text-base text-foreground mt-0.5">
                    {repo.symbol_count ?? '-'}
                  </div>
                </div>

                <div className="rounded-lg bg-muted/20 border border-border/50 p-2">
                  <div className="flex items-center justify-center gap-1 text-[11px] text-muted-foreground">
                    <Layers className="h-3 w-3" />
                    <span>Chunks</span>
                  </div>
                  <div className="font-bold text-base text-foreground mt-0.5">
                    {repo.chunk_count ?? '-'}
                  </div>
                </div>
              </div>
            </div>

            {/* Box B: Dependencies Explorer (Scrollable Box) */}
            <div className="flex-1 min-h-0 flex flex-col rounded-xl border border-border bg-card shadow-sm overflow-hidden">
              {/* Header */}
              <div className="bg-muted/30 px-3.5 py-2.5 border-b border-border flex items-center justify-between shrink-0">
                <span className="font-semibold text-xs text-foreground flex items-center gap-1.5">
                  <Box className="h-3.5 w-3.5 text-primary" />
                  Dependencies
                </span>
                <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-medium bg-primary/10 text-primary border border-primary/20">
                  {dependencies?.length ?? 0}
                </span>
              </div>

              {/* Filter input */}
              <div className="p-2 border-b border-border/60 bg-background/50 shrink-0">
                <div className="relative flex items-center">
                  <Search className="h-3 w-3 absolute left-2.5 text-muted-foreground pointer-events-none" />
                  <input
                    type="text"
                    value={dependencyFilter}
                    onChange={(e) => setDependencyFilter(e.target.value)}
                    placeholder="Filter dependencies…"
                    className="w-full pl-7 pr-7 py-1 text-xs rounded-md bg-muted/20 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary transition-colors"
                  />
                  {dependencyFilter && (
                    <button
                      onClick={() => setDependencyFilter('')}
                      className="absolute right-2 text-muted-foreground hover:text-foreground"
                      aria-label="Clear filter"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  )}
                </div>
              </div>

              {/* Scrollable dependencies list */}
              <div className="flex-1 min-h-0 overflow-y-auto p-2 space-y-1.5">
                {depsLoading ? (
                  <div className="flex justify-center py-8">
                    <LoadingSpinner size="sm" label="Loading dependencies…" />
                  </div>
                ) : depsError ? (
                  <p className="text-xs text-destructive p-2">Failed to load dependencies.</p>
                ) : !dependencies || dependencies.length === 0 ? (
                  <p className="text-xs text-muted-foreground italic p-2 text-center">
                    No dependencies discovered in manifests.
                  </p>
                ) : filteredDependencies.length === 0 ? (
                  <p className="text-xs text-muted-foreground italic p-2 text-center">
                    No dependencies matching "{dependencyFilter}".
                  </p>
                ) : (
                  filteredDependencies.map((dep, idx) => (
                    <div
                      key={idx}
                      className="flex items-center justify-between gap-2 p-2 rounded-lg border border-border/50 bg-background/40 hover:bg-accent/40 transition-colors"
                    >
                      <div className="min-w-0">
                        <p className="text-xs font-medium text-foreground truncate" title={dep.name}>
                          {dep.name}
                        </p>
                        <span className="text-[10px] text-muted-foreground uppercase font-mono">
                          {dep.ecosystem}
                        </span>
                      </div>
                      <span className="text-[11px] font-mono text-muted-foreground px-1.5 py-0.5 rounded bg-muted/40 border border-border/40 shrink-0">
                        {dep.version}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>

          {/* ---------------------------------------------------------- */}
          {/* Right Column: Code Intelligence Workbench (Split View)      */}
          {/* ---------------------------------------------------------- */}
          <div className="md:col-span-8 lg:col-span-9 flex flex-col min-h-0 h-full">
            <div className="h-full min-h-0 flex flex-col rounded-xl border border-border bg-card shadow-sm overflow-hidden">
              {/* Workbench Header */}
              <div className="h-11 bg-muted/30 px-3 sm:px-4 border-b border-border flex items-center justify-between shrink-0">
                <div className="flex items-center gap-2 min-w-0">
                  <FileCode className="h-4 w-4 text-primary shrink-0" />
                  <span className="font-semibold text-xs text-foreground truncate">
                    {selectedFile ? selectedFile.path : 'Code Intelligence Explorer'}
                  </span>
                  {selectedFile && (
                    <span className="hidden sm:inline-block text-[10px] text-muted-foreground font-mono bg-muted/40 px-1.5 py-0.5 rounded border border-border/40 shrink-0">
                      {selectedFile.line_count} lines · {(selectedFile.size_bytes / 1024).toFixed(1)} KB
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-1.5 shrink-0">
                  {selectedFile && (
                    <>
                      {/* Analysis Panel Toggle */}
                      <button
                        type="button"
                        onClick={() => {
                          setActiveFeature((prev) => (prev ? null : 'explain'));
                        }}
                        className={cn(
                          'inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md transition-colors',
                          activeFeature
                            ? 'bg-primary text-primary-foreground shadow-xs'
                            : 'bg-primary/10 text-primary hover:bg-primary hover:text-primary-foreground'
                        )}
                        title="Toggle Analysis Result Panel"
                      >
                        <Sparkles className="h-3 w-3" />
                        <span className="hidden sm:inline">
                          {activeFeature ? 'Hide Analysis' : 'Analysis Panel'}
                        </span>
                      </button>

                      {/* Universal Analysis History Trigger (F-03) */}
                      <button
                        type="button"
                        onClick={() => setIsHistoryDrawerOpen(true)}
                        className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md bg-muted text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
                        title="View Analysis History & Reopen Past Runs"
                      >
                        <History className="h-3 w-3 text-primary" />
                        <span className="hidden sm:inline">History</span>
                      </button>

                      <Link
                        to={`/app/repositories/${repo.id}/chat?file=${encodeURIComponent(selectedFile.path)}`}
                        className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md bg-muted text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
                        title="Ask AI about this file"
                      >
                        <MessageSquare className="h-3 w-3" />
                        <span className="hidden sm:inline">Ask AI</span>
                      </Link>

                      <button
                        onClick={() => setShowModal(true)}
                        className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                        title="Fullscreen preview"
                        aria-label="Fullscreen preview"
                      >
                        <Maximize2 className="h-3.5 w-3.5" />
                      </button>
                    </>
                  )}
                </div>
              </div>

              {/* Developer Intelligence Action Bar (F-03, F-05) */}
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
                {/* Sub-pane 1: Interactive File Tree (Scrollable) */}
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

                {/* Sub-pane 2: Code Viewer & Symbols (Scrollable) */}
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
                  ) : isLookingUpPath ? (
                    <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-muted-foreground">
                      <LoadingSpinner size="md" label={`Locating cited file "${fileParam}" in repository...`} />
                    </div>
                  ) : citedFileUnavailable ? (
                    <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-muted-foreground">
                      <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-6 max-w-md">
                        <FileCode className="h-8 w-8 mb-2 mx-auto text-amber-500" />
                        <h4 className="text-sm font-semibold text-foreground">Cited File Unavailable</h4>
                        <p className="text-xs text-muted-foreground mt-1 break-all">
                          The cited file <code className="font-mono text-primary px-1 bg-muted/60 rounded">{citedFileUnavailable}</code> was not found in the indexed repository files.
                        </p>
                        <p className="text-[11px] text-muted-foreground mt-2">
                          Please select an available file from the explorer tree on the left.
                        </p>
                        {filesData?.total && loadedFiles.length < filesData.total && (
                          <button
                            onClick={handleLoadMoreFiles}
                            disabled={isLoadingMore}
                            className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-amber-500/20 text-amber-400 hover:bg-amber-500/30 transition-colors"
                          >
                            {isLoadingMore ? 'Loading files...' : `Load more files (${loadedFiles.length}/${filesData.total})`}
                          </button>
                        )}
                      </div>
                    </div>
                  ) : fileParam && !filesLoading ? (
                    <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-muted-foreground">
                      <div className="rounded-xl border border-blue-500/30 bg-blue-500/10 p-6 max-w-md">
                        <FileCode className="h-8 w-8 mb-2 mx-auto text-blue-400" />
                        <h4 className="text-sm font-semibold text-foreground">Cited File Not in Loaded Preview</h4>
                        <p className="text-xs text-muted-foreground mt-1 break-all">
                          The cited file <code className="font-mono text-primary px-1 bg-muted/60 rounded">{fileParam}</code> was not found in the first {loadedFiles.length} loaded files (total: {filesData?.total ?? 'unknown'}).
                        </p>
                        <div className="mt-3 flex items-center justify-center gap-2">
                          {filesData?.total && loadedFiles.length < filesData.total && (
                            <button
                              onClick={handleLoadMoreFiles}
                              disabled={isLoadingMore}
                              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
                            >
                              {isLoadingMore ? 'Loading files...' : `Load next 500 files`}
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-muted-foreground">
                      <Code className="h-8 w-8 mb-2 opacity-40 text-primary" />
                      <p className="text-xs font-medium text-foreground">No file selected</p>
                      <p className="text-[11px] text-muted-foreground mt-0.5">
                        Select a file from the explorer on the left to inspect code and symbols.
                      </p>
                    </div>
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

      {/* Universal Analysis History & Reopen Drawer (F-03) */}
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


// ---------------------------------------------------------------------------
// File Preview Modal (Inspect Code & Extracted Symbols Fullscreen)
// ---------------------------------------------------------------------------

function FilePreviewModal({
  repositoryId,
  file,
  onClose,
}: {
  repositoryId: string;
  file: RepositoryFile;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const { data: fileData, isLoading, isError } = useRepositoryFileContent(repositoryId, file.id);
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    if (!fileData?.content) return;
    try {
      await navigator.clipboard.writeText(fileData.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Ignore
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-in fade-in duration-200"
    >
      <div className="relative flex flex-col w-full max-w-5xl max-h-[90vh] rounded-xl border border-border bg-card shadow-2xl overflow-hidden">
        {/* Modal Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3 bg-muted/20">
          <div className="flex items-center gap-3 min-w-0">
            <FileCode className="h-5 w-5 text-primary shrink-0" />
            <div className="min-w-0">
              <h3 className="font-mono text-sm font-semibold text-foreground truncate">
                {file.path}
              </h3>
              <p className="text-xs text-muted-foreground">
                {file.line_count} lines · {(file.size_bytes / 1024).toFixed(1)} KB
                {file.language && ` · ${file.language}`}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {fileData?.content && (
              <button
                onClick={handleCopy}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border bg-background text-xs font-mono text-foreground hover:bg-accent transition-colors"
                title="Copy code"
              >
                {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                <span>{copied ? 'Copied' : 'Copy'}</span>
              </button>
            )}

            <button
              onClick={() => {
                onClose();
                navigate(`/app/repositories/${repositoryId}/chat?file=${encodeURIComponent(file.path)}`);
              }}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary/10 text-primary px-3 py-1.5 text-xs font-medium hover:bg-primary hover:text-primary-foreground transition-colors"
            >
              <MessageSquare className="h-3.5 w-3.5" />
              <span>Ask AI About File</span>
            </button>

            <button
              onClick={onClose}
              className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
              aria-label="Close preview"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* Modal Body */}
        <div className="flex-1 overflow-auto p-5 font-mono text-xs">
          {isLoading ? (
            <div className="flex flex-col items-center justify-center py-20 gap-3">
              <LoadingSpinner size="md" label="Loading code content…" />
              <span className="text-muted-foreground text-xs font-mono">Loading file content…</span>
            </div>
          ) : isError ? (
            <p className="text-destructive py-8 font-sans">
              Could not load file content. Chunks might still be indexing.
            </p>
          ) : (
            <div className="space-y-4">
              {fileData?.symbols && fileData.symbols.length > 0 && (
                <div className="rounded-lg border border-border bg-muted/20 p-3 space-y-2">
                  <span className="font-sans text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                    Extracted Symbols ({fileData.symbols.length})
                  </span>
                  <div className="flex flex-wrap gap-2">
                    {fileData.symbols.map((sym) => (
                      <span
                        key={sym.id}
                        className="inline-flex items-center gap-1.5 rounded bg-background border border-border px-2 py-1 text-xs text-foreground"
                      >
                        <span className="text-primary font-bold">{sym.kind}</span>
                        <span>{sym.name}</span>
                        <span className="text-muted-foreground text-[10px]">
                          L{sym.start_line}–{sym.end_line}
                        </span>
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div className="rounded-lg border border-border bg-background p-4 overflow-x-auto text-foreground font-mono text-xs leading-relaxed whitespace-pre">
                {fileData?.content ? (
                  fileData.content
                ) : (
                  <span className="text-muted-foreground italic font-sans">
                    Empty file or non-indexed binary content.
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sync Progress Indicator Component
// ---------------------------------------------------------------------------

const STAGES: Array<{ id: SyncStage; label: string }> = [
  { id: 'CLONING', label: 'Cloning' },
  { id: 'SCANNING', label: 'Scanning' },
  { id: 'INDEXING', label: 'Indexing' },
  { id: 'READY', label: 'Ready' },
];

function SyncProgressIndicator({
  currentStage,
  isFailed,
}: {
  currentStage: SyncStage;
  isFailed: boolean;
}) {
  let currentIndex = STAGES.findIndex((s) => s.id === currentStage);
  if (currentIndex === -1) {
    currentIndex = isFailed ? 0 : -1;
  }

  return (
    <div className="relative">
      <div className="flex items-center justify-between">
        {STAGES.map((step, index) => {
          const isCompleted = index < currentIndex || currentStage === 'READY';
          const isCurrent = index === currentIndex && !isFailed;
          const isCurrentFailed = index === currentIndex && isFailed;

          return (
            <div key={step.id} className="relative z-10 flex flex-col items-center gap-2">
              <div
                className={cn(
                  'flex h-9 w-9 items-center justify-center rounded-full border-2 bg-background transition-colors',
                  isCompleted
                    ? 'border-emerald-600 text-emerald-600'
                    : isCurrent
                    ? 'border-blue-600 text-blue-600 shadow-sm'
                    : isCurrentFailed
                    ? 'border-destructive text-destructive'
                    : 'border-muted-foreground/30 text-muted-foreground'
                )}
              >
                {isCompleted ? (
                  <CheckCircle2 className="h-4 w-4" />
                ) : isCurrent ? (
                  <RefreshCw className="h-4 w-4 animate-spin" />
                ) : isCurrentFailed ? (
                  <XCircle className="h-4 w-4" />
                ) : (
                  <Clock className="h-4 w-4 opacity-50" />
                )}
              </div>

              <span
                className={cn(
                  'text-xs font-medium transition-colors',
                  isCompleted
                    ? 'text-foreground'
                    : isCurrent
                    ? 'text-blue-500'
                    : isCurrentFailed
                    ? 'text-destructive'
                    : 'text-muted-foreground'
                )}
              >
                {step.label}
              </span>
            </div>
          );
        })}
      </div>

      <div className="absolute left-0 top-4.5 -z-10 h-[2px] w-full -translate-y-1/2 bg-muted-foreground/20" />

      <div
        className="absolute left-0 top-4.5 -z-10 h-[2px] -translate-y-1/2 bg-emerald-600 transition-all duration-500 ease-in-out"
        style={{
          width:
            currentIndex > 0
              ? `${(currentIndex / (STAGES.length - 1)) * 100}%`
              : currentStage === 'READY'
              ? '100%'
              : '0%',
        }}
      />
    </div>
  );
}
