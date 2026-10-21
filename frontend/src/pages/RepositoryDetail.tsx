import { useState, useMemo } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import {
  useRepository,
  useRepositoryFiles,
  useRepositoryDependencies,
  useSyncRepository,
  useDeleteRepository,
  useRepositoryFileContent,
  syncProgressFromStatus,
} from '../hooks/useRepositories';
import { LoadingSpinner } from '../components/shared/LoadingSpinner';
import { ErrorMessage } from '../components/shared/ErrorMessage';
import { cn } from '../lib/utils';
import {
  MessageSquare,
  ArrowLeft,
  CheckCircle2,
  RefreshCw,
  XCircle,
  Clock,
  Folder,
  FolderOpen,
  FileText,
  FileCode,
  Box,
  Database,
  Code,
  File,
  Trash2,
  RotateCw,
  X,
  Search,
  Copy,
  Check,
  Maximize2,
  GitBranch,
  ChevronRight,
  ChevronDown,
  Layers,
} from 'lucide-react';
import type { SyncStage, RepositoryFile } from '../types/api';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SYNC_POLL_INTERVAL_MS = 3000;

// ---------------------------------------------------------------------------
// Repository Detail Page (Code Intelligence Workbench)
// ---------------------------------------------------------------------------

export function RepositoryDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [userSelectedFile, setUserSelectedFile] = useState<RepositoryFile | null>(null);
  const [showConfirmDelete, setShowConfirmDelete] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [dependencyFilter, setDependencyFilter] = useState('');

  // ------------------------------------------------------------------
  // Mutations
  // ------------------------------------------------------------------
  const { mutate: triggerSync, isPending: isSyncPending } = useSyncRepository();
  const { mutate: deleteRepo, isPending: isDeletePending } = useDeleteRepository();

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

  // Only fetch files and dependencies if the repository is successfully synced
  const {
    data: filesData,
    isLoading: filesLoading,
    isError: filesError,
  } = useRepositoryFiles(id, 1, 100, { enabled: isReady });

  const {
    data: dependencies,
    isLoading: depsLoading,
    isError: depsError,
  } = useRepositoryDependencies(id, { enabled: isReady });

  // Auto-select initial file (prefer README.md, or first file) once files load
  const selectedFile = useMemo(() => {
    if (userSelectedFile) return userSelectedFile;
    if (!filesData?.items || filesData.items.length === 0) return null;
    const readme = filesData.items.find((f) => f.path.toLowerCase().endsWith('readme.md'));
    return readme ?? filesData.items[0];
  }, [userSelectedFile, filesData]);

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
                      <Link
                        to={`/app/repositories/${repo.id}/chat?file=${encodeURIComponent(selectedFile.path)}`}
                        className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md bg-primary/10 text-primary hover:bg-primary hover:text-primary-foreground transition-colors"
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

              {/* Workbench Split Workspace */}
              <div className="flex-1 min-h-0 flex flex-col sm:flex-row overflow-hidden">
                {/* Sub-pane 1: Interactive File Tree (Scrollable) */}
                <div className="w-full sm:w-60 lg:w-72 border-b sm:border-b-0 sm:border-r border-border flex flex-col shrink-0 min-h-0 bg-muted/10">
                  <FileExplorerPane
                    files={filesData?.items ?? []}
                    isLoading={filesLoading}
                    isError={filesError}
                    selectedFile={selectedFile}
                    onSelectFile={(file) => setUserSelectedFile(file)}
                  />
                </div>

                {/* Sub-pane 2: Code Viewer & Symbols (Scrollable) */}
                <div className="flex-1 min-w-0 flex flex-col min-h-0 bg-background/40">
                  {selectedFile && id ? (
                    <InlineCodeViewer
                      repositoryId={id}
                      file={selectedFile}
                    />
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
              </div>
            </div>
          </div>
        </div>
      )}

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
// File Explorer Pane (Interactive Search & Collapsible Tree)
// ---------------------------------------------------------------------------

function FileExplorerPane({
  files,
  isLoading,
  isError,
  selectedFile,
  onSelectFile,
}: {
  files: RepositoryFile[];
  isLoading: boolean;
  isError: boolean;
  selectedFile: RepositoryFile | null;
  onSelectFile: (file: RepositoryFile) => void;
}) {
  const [filter, setFilter] = useState('');
  const [collapsedDirs, setCollapsedDirs] = useState<Record<string, boolean>>({});

  function toggleDir(dirName: string) {
    setCollapsedDirs((prev) => ({
      ...prev,
      [dirName]: !prev[dirName],
    }));
  }

  // Filter files
  const filteredFiles = useMemo(() => {
    if (!filter.trim()) return files;
    const q = filter.toLowerCase();
    return files.filter((f) => f.path.toLowerCase().includes(q));
  }, [files, filter]);

  // Group into directories
  const { rootFiles, directories } = useMemo(() => {
    const rf: RepositoryFile[] = [];
    const dirs = new Map<string, RepositoryFile[]>();

    for (const file of filteredFiles) {
      const parts = file.path.split('/').filter(Boolean);
      const isDir = file.path.endsWith('/');

      if (parts.length === 1) {
        if (isDir) {
          if (!dirs.has(parts[0])) dirs.set(parts[0], []);
        } else {
          rf.push(file);
        }
      } else if (parts.length >= 2) {
        const rootDir = parts[0];
        if (!dirs.has(rootDir)) dirs.set(rootDir, []);
        dirs.get(rootDir)!.push(file);
      }
    }

    rf.sort((a, b) => a.path.localeCompare(b.path));
    const sorted = Array.from(dirs.entries()).sort((a, b) => a[0].localeCompare(b[0]));
    return { rootFiles: rf, directories: sorted };
  }, [filteredFiles]);

  const getFileIcon = (filename: string) => {
    if (filename.endsWith('.md')) return <FileText className="h-3.5 w-3.5 text-muted-foreground" />;
    if (filename.match(/\.(js|jsx|ts|tsx)$/)) return <FileCode className="h-3.5 w-3.5 text-blue-400" />;
    if (filename.match(/\.(py)$/)) return <FileCode className="h-3.5 w-3.5 text-amber-400" />;
    if (filename.match(/\.(json|yaml|yml|toml)$/)) return <FileCode className="h-3.5 w-3.5 text-emerald-400" />;
    return <File className="h-3.5 w-3.5 text-muted-foreground" />;
  };

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      {/* Search files header */}
      <div className="p-2 border-b border-border/60 bg-background/50 shrink-0">
        <div className="relative flex items-center">
          <Search className="h-3 w-3 absolute left-2.5 text-muted-foreground pointer-events-none" />
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter files…"
            className="w-full pl-7 pr-7 py-1 text-xs rounded-md bg-muted/20 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary transition-colors font-mono"
          />
          {filter && (
            <button
              onClick={() => setFilter('')}
              className="absolute right-2 text-muted-foreground hover:text-foreground"
              aria-label="Clear file filter"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>

      {/* Tree list */}
      <div className="flex-1 min-h-0 overflow-y-auto p-2 text-xs font-mono select-none space-y-0.5">
        {isLoading ? (
          <div className="flex justify-center py-8">
            <LoadingSpinner size="sm" label="Loading tree…" />
          </div>
        ) : isError ? (
          <p className="text-xs text-destructive p-2">Failed to load files.</p>
        ) : filteredFiles.length === 0 ? (
          <p className="text-xs text-muted-foreground italic p-2 text-center">
            {filter ? `No files matching "${filter}"` : 'No files indexed yet.'}
          </p>
        ) : (
          <>
            {directories.map(([dirName, children]) => {
              const isCollapsed = Boolean(collapsedDirs[dirName]);
              return (
                <div key={dirName} className="mb-0.5">
                  <button
                    type="button"
                    onClick={() => toggleDir(dirName)}
                    className="flex items-center gap-1.5 w-full py-1 px-1.5 hover:bg-accent/60 rounded text-foreground font-medium transition-colors text-left"
                  >
                    {isCollapsed ? (
                      <ChevronRight className="h-3 w-3 text-muted-foreground" />
                    ) : (
                      <ChevronDown className="h-3 w-3 text-muted-foreground" />
                    )}
                    {isCollapsed ? (
                      <Folder className="h-3.5 w-3.5 text-amber-500 fill-amber-500/20" />
                    ) : (
                      <FolderOpen className="h-3.5 w-3.5 text-amber-500 fill-amber-500/20" />
                    )}
                    <span className="truncate flex-1">{dirName}</span>
                    <span className="text-[10px] text-muted-foreground/60 font-mono">
                      {children.length}
                    </span>
                  </button>

                  {!isCollapsed && children.length > 0 && (
                    <div className="ml-3 border-l border-border/60 pl-1.5 my-0.5 space-y-0.5">
                      {children.map((child) => {
                        const childName = child.path.startsWith(dirName + '/')
                          ? child.path.slice(dirName.length + 1)
                          : child.path;
                        const isChildDir = child.path.endsWith('/');
                        const isSelected = selectedFile?.id === child.id;

                        return (
                          <button
                            key={child.id}
                            type="button"
                            onClick={() => !isChildDir && onSelectFile(child)}
                            className={cn(
                              'flex w-full items-center gap-1.5 py-1 px-1.5 rounded text-left transition-colors',
                              isSelected
                                ? 'bg-primary/15 text-primary font-medium border-l-2 border-primary'
                                : isChildDir
                                ? 'cursor-default text-muted-foreground'
                                : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
                            )}
                          >
                            {isChildDir ? (
                              <Folder className="h-3.5 w-3.5 text-amber-500" />
                            ) : (
                              getFileIcon(childName)
                            )}
                            <span className="truncate flex-1">{childName}</span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}

            {rootFiles.map((file) => {
              const isSelected = selectedFile?.id === file.id;
              return (
                <button
                  key={file.id}
                  type="button"
                  onClick={() => onSelectFile(file)}
                  className={cn(
                    'flex w-full items-center gap-1.5 py-1 px-1.5 rounded text-left transition-colors',
                    isSelected
                      ? 'bg-primary/15 text-primary font-medium border-l-2 border-primary'
                      : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
                  )}
                >
                  {getFileIcon(file.path)}
                  <span className="truncate flex-1">{file.path}</span>
                </button>
              );
            })}
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inline Code Viewer (Embedded Inside Workbench Split View)
// ---------------------------------------------------------------------------

function InlineCodeViewer({
  repositoryId,
  file,
}: {
  repositoryId: string;
  file: RepositoryFile;
}) {
  const { data: fileData, isLoading, isError } = useRepositoryFileContent(repositoryId, file.id);
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    if (!fileData?.content) return;
    try {
      await navigator.clipboard.writeText(fileData.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Ignore clipboard write failures
    }
  }

  const content = fileData?.content;
  const lines = useMemo(() => (content ? content.split('\n') : []), [content]);


  return (
    <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
      {/* Symbols Strip (if any extracted) */}
      {fileData?.symbols && fileData.symbols.length > 0 && (
        <div className="shrink-0 px-3 py-1.5 border-b border-border/60 bg-muted/20 flex items-center gap-1.5 overflow-x-auto text-xs">
          <span className="text-[10px] text-muted-foreground uppercase font-bold tracking-wider shrink-0 mr-1">
            Symbols ({fileData.symbols.length}):
          </span>
          {fileData.symbols.slice(0, 15).map((sym) => (
            <span
              key={sym.id}
              className="inline-flex items-center gap-1 rounded bg-background border border-border/60 px-1.5 py-0.5 text-[10px] text-foreground font-mono shrink-0"
              title={`${sym.kind} ${sym.name} (Lines ${sym.start_line}-${sym.end_line})`}
            >
              <span className="text-primary font-bold">{sym.kind}</span>
              <span>{sym.name}</span>
              <span className="text-muted-foreground text-[9px]">L{sym.start_line}</span>
            </span>
          ))}
          {fileData.symbols.length > 15 && (
            <span className="text-[10px] text-muted-foreground font-mono shrink-0">
              +{fileData.symbols.length - 15} more
            </span>
          )}
        </div>
      )}

      {/* Code Viewer Body */}
      <div className="flex-1 min-h-0 overflow-auto relative">
        {/* Floating copy button */}
        {fileData?.content && (
          <button
            onClick={handleCopy}
            className="absolute top-2 right-3 z-10 inline-flex items-center gap-1 px-2 py-1 rounded bg-card/80 backdrop-blur-sm border border-border text-[11px] font-mono text-muted-foreground hover:text-foreground hover:bg-accent transition-colors shadow-sm"
            title="Copy code to clipboard"
            aria-label="Copy code to clipboard"
          >
            {copied ? (
              <>
                <Check className="h-3 w-3 text-emerald-400" />
                <span className="text-emerald-400">Copied</span>
              </>
            ) : (
              <>
                <Copy className="h-3 w-3" />
                <span>Copy</span>
              </>
            )}
          </button>
        )}

        {isLoading ? (
          <div className="flex flex-col items-center justify-center py-20 gap-2">
            <LoadingSpinner size="md" label="Loading code…" />
            <span className="text-xs text-muted-foreground font-mono">Retrieving indexed chunks…</span>
          </div>
        ) : isError ? (
          <div className="p-6 text-center text-xs text-destructive">
            Could not retrieve file content. Chunks might still be indexing.
          </div>
        ) : !fileData?.content ? (
          <div className="p-6 text-center text-xs text-muted-foreground italic">
            Empty file or non-indexed binary content.
          </div>
        ) : (
          <div className="flex min-w-full font-mono text-xs leading-5">
            {/* Line numbers gutter */}
            <div className="shrink-0 py-3 px-3 text-right text-muted-foreground/40 select-none bg-muted/5 border-r border-border/40 font-mono text-[11px]">
              {lines.map((_, i) => (
                <div key={i}>{i + 1}</div>
              ))}
            </div>

            {/* Code content */}
            <div className="flex-1 py-3 px-4 text-foreground whitespace-pre overflow-x-auto">
              {lines.map((line, i) => (
                <div key={i} className="hover:bg-accent/20">
                  {line || '\n'}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
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
