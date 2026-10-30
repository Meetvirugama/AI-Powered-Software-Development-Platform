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
import { findMatchingRepositoryFile } from '../lib/sourceReference';
import { LoadingSpinner } from '../components/shared/LoadingSpinner';
import { ErrorMessage } from '../components/shared/ErrorMessage';
import { FileTree } from '../components/explorer/FileTree';
import { CodeViewer } from '../components/explorer/CodeViewer';
import { AnalysisHistoryDrawer } from '../components/explorer/AnalysisHistoryDrawer';
import { RepositoryHeader } from '../components/explorer/RepositoryHeader';
import { RepositorySyncCard } from '../components/explorer/RepositorySyncCard';
import { RepositoryMetricsSidebar } from '../components/explorer/RepositoryMetricsSidebar';
import { WorkbenchHeader } from '../components/explorer/WorkbenchHeader';
import { CodeViewerEmptyState } from '../components/explorer/CodeViewerEmptyState';
import { FilePreviewModal } from '../components/explorer/FilePreviewModal';
import { ArrowLeft } from 'lucide-react';
import type { RepositoryFile } from '../types/api';
import type { AnalysisTarget, SourceReference } from '../types/analysis';

const SYNC_POLL_INTERVAL_MS = 3000;

/**
 * Repository overview and code explorer.
 * Focuses on codebase browsing, file inspection, dependencies, and repository metrics.
 * AI analysis workflows are canonically housed in their dedicated studios:
 * /explain, /bugs, /tests, /review, and /chat.
 */
export function RepositoryDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const fileParam = searchParams.get('file');
  const startParam = searchParams.get('start');
  const endParam = searchParams.get('end');

  const [userSelectedFile, setUserSelectedFile] = useState<RepositoryFile | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [isHistoryDrawerOpen, setIsHistoryDrawerOpen] = useState(false);
  const [customTarget, setCustomTarget] = useState<AnalysisTarget | null>(null);
  const [userHighlightedSource, setUserHighlightedSource] = useState<SourceReference | null>(null);

  // ------------------------------------------------------------------
  // Data Fetching
  // ------------------------------------------------------------------
  const {
    data: repo,
    isLoading: repoLoading,
    isError: repoError,
    error: repoErrorData,
  } = useRepository(id, {
    refetchInterval: (query: { state: { data?: { sync_status?: string } } }) => {
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
  const queryMatchedFile = useMemo(() => {
    if (!fileParam || !isReady) return null;
    return findMatchingRepositoryFile(loadedFiles, fileParam);
  }, [fileParam, isReady, loadedFiles]);

  // Effect: perform explicit path lookup if not in initial 500
  useEffect(() => {
    if (!id || !fileParam || !isReady || filesLoading || queryMatchedFile) return;
    if (lookupAttemptedPath === fileParam) return;

    let cancelled = false;

    lookupRepositoryFileByPath(id, fileParam)
      .then((file) => {
        if (!cancelled) {
          setLookupAttemptedPath(fileParam);
          if (file) {
            setExtraLoadedFiles((prev) => (prev.some((f) => f.id === file.id) ? prev : [...prev, file]));
          }
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setLookupAttemptedPath(fileParam);
        }
        console.debug(`Path lookup for ${fileParam} unsuccessful:`, err);
      });

    return () => {
      cancelled = true;
    };
  }, [id, fileParam, isReady, filesLoading, queryMatchedFile, lookupAttemptedPath]);

  const citedFileUnavailable = useMemo(() => {
    return fileParam && !filesLoading && !isLookingUpPath && !queryMatchedFile ? fileParam : null;
  }, [fileParam, filesLoading, isLookingUpPath, queryMatchedFile]);

  const selectedFile = useMemo(() => {
    if (userSelectedFile) return userSelectedFile;
    if (queryMatchedFile) return queryMatchedFile;
    return loadedFiles.length > 0 ? loadedFiles[0] : null;
  }, [userSelectedFile, queryMatchedFile, loadedFiles]);

  // Active target range derived from selection or custom range
  const activeTarget: AnalysisTarget = useMemo(() => {
    if (customTarget) return customTarget;
    if (startParam && endParam && selectedFile) {
      return {
        type: 'range',
        path: selectedFile.path,
        start_line: Number(startParam),
        end_line: Number(endParam),
      };
    }
    return {
      type: 'file',
      path: selectedFile ? selectedFile.path : '',
    };
  }, [customTarget, startParam, endParam, selectedFile]);

  // Synchronize target line highlight when query params exist
  const initialHighlightedSource: SourceReference | null = useMemo(() => {
    if (startParam && endParam && selectedFile) {
      return {
        file_path: selectedFile.path,
        start_line: Number(startParam),
        end_line: Number(endParam),
      };
    }
    return null;
  }, [startParam, endParam, selectedFile]);

  const highlightedSource = userHighlightedSource ?? initialHighlightedSource;

  // Dependencies
  const {
    data: dependencies = [],
    isLoading: depsLoading,
    isError: depsError,
  } = useRepositoryDependencies(id, { enabled: isReady });

  // Mutations
  const { mutate: triggerSync, isPending: isSyncPending } = useSyncRepository();
  const { mutate: deleteRepo, isPending: isDeletePending } = useDeleteRepository();

  function handleSync() {
    if (id) triggerSync(id);
  }

  function handleDelete() {
    if (!id) return;
    deleteRepo(id, {
      onSuccess: () => navigate('/app/dashboard'),
    });
  }

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
              {/* Workbench Header with quick action links */}
              <WorkbenchHeader
                repositoryId={repo.id}
                selectedFile={selectedFile}
                onOpenHistory={() => setIsHistoryDrawerOpen(true)}
                onOpenFullscreen={() => setShowModal(true)}
              />

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
                      isAnalyzing={false}
                      onTriggerExplain={() => {
                        navigate(`/app/repositories/${id}/explain`);
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
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Universal Analysis History & Reopen Drawer */}
      <AnalysisHistoryDrawer
        isOpen={isHistoryDrawerOpen}
        onClose={() => setIsHistoryDrawerOpen(false)}
        repositoryId={id ?? ''}
        initialFeature="all"
        currentFilePath={selectedFile?.path}
        onReopenExplain={(_explanation, _target, _runId) => {
          setIsHistoryDrawerOpen(false);
          navigate(`/app/repositories/${id}/explain`);
        }}
        onReopenBugs={(_result, _target, _runId) => {
          setIsHistoryDrawerOpen(false);
          navigate(`/app/repositories/${id}/bugs`);
        }}
        onReopenTests={(_result, _target, _runId) => {
          setIsHistoryDrawerOpen(false);
          navigate(`/app/repositories/${id}/tests`);
        }}
        onReopenReview={(_result) => {
          setIsHistoryDrawerOpen(false);
          navigate(`/app/repositories/${id}/review`);
        }}
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

export default RepositoryDetail;
