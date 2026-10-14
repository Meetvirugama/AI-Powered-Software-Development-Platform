import { useState } from 'react';
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
  FileText,
  FileCode,
  Box,
  Database,
  Code,
  File,
  Trash2,
  RotateCw,
  X,
} from 'lucide-react';
import type { SyncStage, RepositoryFile } from '../types/api';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SYNC_POLL_INTERVAL_MS = 3000;

// ---------------------------------------------------------------------------
// Repository Detail Page
// ---------------------------------------------------------------------------

export function RepositoryDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [selectedFile, setSelectedFile] = useState<RepositoryFile | null>(null);
  const [showConfirmDelete, setShowConfirmDelete] = useState(false);

  // ------------------------------------------------------------------
  // Mutations
  // ------------------------------------------------------------------
  const { mutate: triggerSync, isPending: isSyncPending } = useSyncRepository();
  const { mutate: deleteRepo, isPending: isDeletePending } = useDeleteRepository();

  // ------------------------------------------------------------------
  // Data Fetching
  // ------------------------------------------------------------------
  const { data: repo, isLoading: repoLoading, isError: repoError, error: repoErrorData } = useRepository(id);
  const progress = repo ? syncProgressFromStatus(repo.sync_status) : null;
  const isPolling = progress?.isActive ?? false;
  const isReady = progress?.isComplete ?? false;

  useRepository(id, {
    refetchInterval: isPolling ? SYNC_POLL_INTERVAL_MS : false,
  });

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
      <div className="flex flex-col items-start gap-4">
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
  // Main Render
  // ------------------------------------------------------------------

  return (
    <div className="space-y-8 max-w-5xl">
      {/* Top Bar: Navigation & Action Header */}
      <div className="flex items-center justify-between">
        <Link
          to="/app/dashboard"
          className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Dashboard
        </Link>

        {/* Header Action Buttons */}
        <div className="flex items-center gap-2">
          {/* Re-sync Button */}
          <button
            onClick={handleSync}
            disabled={isSyncActive}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-medium text-foreground hover:bg-accent transition-colors disabled:opacity-50"
            title="Re-synchronize repository"
          >
            <RotateCw className={cn('h-3.5 w-3.5', isSyncActive && 'animate-spin text-primary')} />
            <span>{isSyncActive ? 'Syncing…' : 'Re-sync'}</span>
          </button>

          {/* Disconnect Button */}
          <button
            onClick={() => setShowConfirmDelete(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-1.5 text-xs font-medium text-destructive hover:bg-destructive/10 transition-colors"
            title="Disconnect repository"
          >
            <Trash2 className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Disconnect</span>
          </button>
        </div>
      </div>

      {/* Disconnect Confirmation Alert */}
      {showConfirmDelete && (
        <div
          role="alert"
          className="rounded-xl border border-destructive/30 bg-destructive/10 p-4 space-y-3"
        >
          <div className="flex items-start justify-between">
            <div>
              <h3 className="font-semibold text-foreground text-sm">Disconnect {repo.name}?</h3>
              <p className="text-xs text-muted-foreground mt-0.5">
                This will delete the repository indexing data, symbols, and vector chunks from this platform.
              </p>
            </div>
            <button
              onClick={() => setShowConfirmDelete(false)}
              className="text-muted-foreground hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="flex items-center gap-3 justify-end">
            <button
              onClick={() => setShowConfirmDelete(false)}
              className="px-3 py-1.5 rounded-lg border border-border bg-background text-xs font-medium text-foreground hover:bg-accent"
            >
              Cancel
            </button>
            <button
              onClick={handleDelete}
              disabled={isDeletePending}
              className="px-3 py-1.5 rounded-lg bg-destructive text-destructive-foreground text-xs font-medium hover:bg-destructive/90 disabled:opacity-50"
            >
              {isDeletePending ? 'Deleting…' : 'Confirm Disconnect'}
            </button>
          </div>
        </div>
      )}

      {/* Header Section */}
      <div className="flex flex-col gap-6 border-b border-border pb-6 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-3">
          <div>
            <h1 className="text-3xl font-bold text-foreground">{repo.name}</h1>
            <p className="mt-1 text-base text-muted-foreground">{repo.full_name}</p>
          </div>

          <p className="text-sm text-foreground max-w-2xl">
            {repo.description || <span className="italic text-muted-foreground">No description provided.</span>}
          </p>

          <div className="flex flex-wrap items-center gap-4 text-sm text-muted-foreground">
            {repo.language && (
              <div className="flex items-center gap-1.5">
                <Code className="h-4 w-4" />
                <span>{repo.language}</span>
              </div>
            )}
            {repo.framework && (
              <div className="flex items-center gap-1.5">
                <Box className="h-4 w-4" />
                <span>{repo.framework}</span>
              </div>
            )}
            <div className="flex items-center gap-1.5">
              <RefreshCw className={cn('h-4 w-4', isSyncActive && 'animate-spin text-primary')} />
              <span>{isSyncActive ? 'Syncing…' : progress.label}</span>
            </div>
            {repo.last_synced_at && (
              <div className="flex items-center gap-1.5">
                <Clock className="h-4 w-4" />
                <span>Last synced {new Date(repo.last_synced_at).toLocaleDateString()}</span>
              </div>
            )}
          </div>
        </div>

        <Link
          to={`/app/repositories/${repo.id}/chat`}
          className={cn(
            'inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring shrink-0',
            !progress.isComplete || progress.isFailed
              ? 'pointer-events-none opacity-50'
              : 'hover:bg-primary/90',
          )}
          aria-disabled={!progress.isComplete || progress.isFailed}
          tabIndex={!progress.isComplete || progress.isFailed ? -1 : undefined}
          onClick={(e) => {
            if (!progress.isComplete || progress.isFailed) {
              e.preventDefault();
            }
          }}
        >
          <MessageSquare className="h-4 w-4" />
          Chat with this repository
        </Link>
      </div>

      {/* Sync Status / Content Area */}
      {!isReady ? (
        <div className="rounded-xl border border-border bg-card p-6 shadow-sm space-y-6">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold text-foreground">
                {progress.isFailed
                  ? 'Synchronization Failed'
                  : isSyncActive
                  ? 'Repository Synchronization in Progress'
                  : 'Repository Not Synced'}
              </h2>
              <p className="text-sm text-muted-foreground mt-1">
                {progress.isFailed
                  ? 'An issue occurred during repository indexing. Click Retry to re-run the sync process.'
                  : isSyncActive
                  ? 'Files are being cloned, scanned, and indexed into the AI vector database.'
                  : 'This repository has not been indexed yet. Start synchronization to enable file explorer and AI chat.'}
              </p>
            </div>

            {/* Prominent Retry Sync Button */}
            {(progress.isFailed || repo.sync_status === 'NOT_SYNCED') && (
              <button
                onClick={handleSync}
                disabled={isSyncActive}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50 shrink-0 self-start sm:self-auto"
              >
                <RefreshCw className={cn('h-4 w-4', isSyncActive && 'animate-spin')} />
                <span>{isSyncActive ? 'Starting Sync…' : 'Retry Synchronization'}</span>
              </button>
            )}
          </div>

          <SyncProgressIndicator
            currentStage={progress.stage}
            isFailed={progress.isFailed}
          />
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          {/* Left Column: Stats & Dependencies */}
          <div className="space-y-8 md:col-span-1">
            {/* Statistics */}
            <div className="rounded-xl border border-border bg-card shadow-sm overflow-hidden">
              <div className="bg-muted/30 px-4 py-3 border-b border-border">
                <h3 className="font-semibold text-sm text-foreground">Statistics</h3>
              </div>
              <div className="p-4 space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <FileText className="h-4 w-4" />
                    <span>Files</span>
                  </div>
                  <span className="font-medium text-foreground">{repo.file_count ?? '-'}</span>
                </div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Code className="h-4 w-4" />
                    <span>Symbols</span>
                  </div>
                  <span className="font-medium text-foreground">{repo.symbol_count ?? '-'}</span>
                </div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Database className="h-4 w-4" />
                    <span>Chunks</span>
                  </div>
                  <span className="font-medium text-foreground">{repo.chunk_count ?? '-'}</span>
                </div>
              </div>
            </div>

            {/* Dependencies */}
            <div className="rounded-xl border border-border bg-card shadow-sm overflow-hidden">
              <div className="bg-muted/30 px-4 py-3 border-b border-border">
                <h3 className="font-semibold text-sm text-foreground">Dependencies</h3>
              </div>
              <div className="p-4">
                {depsLoading ? (
                  <div className="flex justify-center py-4">
                    <LoadingSpinner size="sm" />
                  </div>
                ) : depsError ? (
                  <p className="text-sm text-destructive">Failed to load dependencies.</p>
                ) : !dependencies || dependencies.length === 0 ? (
                  <p className="text-sm text-muted-foreground italic">No dependencies found.</p>
                ) : (
                  <ul className="space-y-3">
                    {dependencies.map((dep, idx) => (
                      <li key={idx} className="flex flex-col gap-0.5">
                        <div className="flex justify-between items-baseline gap-2">
                          <span className="text-sm font-medium text-foreground truncate">{dep.name}</span>
                          <span className="text-xs font-mono text-muted-foreground shrink-0">{dep.version}</span>
                        </div>
                        <span className="text-xs text-muted-foreground">{dep.ecosystem}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </div>

          {/* Right Column: Interactive File Tree */}
          <div className="md:col-span-2">
            <div className="rounded-xl border border-border bg-card shadow-sm overflow-hidden h-full flex flex-col">
              <div className="bg-muted/30 px-4 py-3 border-b border-border flex items-center justify-between shrink-0">
                <h3 className="font-semibold text-sm text-foreground">File Explorer (Click to View Code)</h3>
                <span className="text-xs text-muted-foreground">{filesData?.total ?? 0} files indexed</span>
              </div>
              <div className="p-4 flex-1 overflow-y-auto max-h-[600px] min-h-[300px]">
                {filesLoading ? (
                  <div className="flex justify-center py-8">
                    <LoadingSpinner size="md" label="Loading files…" />
                  </div>
                ) : filesError ? (
                  <p className="text-sm text-destructive py-4">Failed to load repository files.</p>
                ) : !filesData || filesData.items.length === 0 ? (
                  <p className="text-sm text-muted-foreground italic py-4">No files indexed yet.</p>
                ) : (
                  <FileTree
                    files={filesData.items}
                    onSelectFile={(file) => setSelectedFile(file)}
                  />
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* File Preview Modal */}
      {selectedFile && id && (
        <FilePreviewModal
          repositoryId={id}
          file={selectedFile}
          onClose={() => setSelectedFile(null)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// File Tree Component (Interactive)
// ---------------------------------------------------------------------------

function FileTree({
  files,
  onSelectFile,
}: {
  files: RepositoryFile[];
  onSelectFile: (file: RepositoryFile) => void;
}) {
  const rootFiles: RepositoryFile[] = [];
  const directories = new Map<string, RepositoryFile[]>();

  for (const file of files) {
    const parts = file.path.split('/').filter(Boolean);
    const isDir = file.path.endsWith('/');

    if (parts.length === 1) {
      if (isDir) {
        if (!directories.has(parts[0])) directories.set(parts[0], []);
      } else {
        rootFiles.push(file);
      }
    } else if (parts.length >= 2) {
      const rootDir = parts[0];
      if (!directories.has(rootDir)) directories.set(rootDir, []);
      directories.get(rootDir)!.push(file);
    }
  }

  const sortedDirs = Array.from(directories.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  rootFiles.sort((a, b) => a.path.localeCompare(b.path));

  const getFileIcon = (filename: string) => {
    if (filename.endsWith('.md')) return <FileText className="h-4 w-4 text-muted-foreground" />;
    if (filename.match(/\.(js|ts|py|go|rs|jsx|tsx|java|cpp|c|html|css|json)$/)) {
      return <FileCode className="h-4 w-4 text-blue-500" />;
    }
    return <File className="h-4 w-4 text-muted-foreground" />;
  };

  return (
    <div className="text-sm font-mono select-none">
      {sortedDirs.map(([dirName, children]) => (
        <div key={dirName} className="mb-1">
          <div className="flex items-center gap-2 py-1.5 px-2 hover:bg-accent/60 rounded-md cursor-default text-foreground font-medium">
            <Folder className="h-4 w-4 text-amber-500 fill-amber-500/20" />
            <span>{dirName}/</span>
          </div>
          {children.length > 0 && (
            <div className="ml-5 border-l border-border pl-2 my-1 space-y-0.5">
              {children
                .sort((a, b) => a.path.localeCompare(b.path))
                .map((child) => {
                  const childName = child.path.startsWith(dirName + '/')
                    ? child.path.slice(dirName.length + 1)
                    : child.path;
                  const isChildDir = child.path.endsWith('/');
                  return (
                    <button
                      key={child.id}
                      onClick={() => !isChildDir && onSelectFile(child)}
                      className={cn(
                        'flex w-full items-center gap-2 py-1 px-2 rounded-md text-left transition-colors',
                        isChildDir
                          ? 'cursor-default text-muted-foreground'
                          : 'cursor-pointer text-foreground hover:bg-accent hover:text-accent-foreground',
                      )}
                    >
                      {isChildDir ? (
                        <Folder className="h-4 w-4 text-amber-500 fill-amber-500/20" />
                      ) : (
                        getFileIcon(childName)
                      )}
                      <span className="truncate">{childName}{isChildDir ? '/' : ''}</span>
                    </button>
                  );
                })}
            </div>
          )}
        </div>
      ))}

      {rootFiles.map((file) => (
        <button
          key={file.id}
          onClick={() => onSelectFile(file)}
          className="flex w-full items-center gap-2 py-1.5 px-2 hover:bg-accent rounded-md text-left text-foreground transition-colors cursor-pointer"
        >
          {getFileIcon(file.path)}
          <span className="truncate">{file.path}</span>
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// File Preview Modal (Inspect Code & Extracted Symbols)
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

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in duration-200"
    >
      <div className="relative flex flex-col w-full max-w-4xl max-h-[85vh] rounded-xl border border-border bg-card shadow-2xl overflow-hidden">
        {/* Modal Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3.5 bg-muted/20">
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
            <button
              onClick={() => {
                onClose();
                navigate(`/app/repositories/${repositoryId}/chat`);
              }}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary/10 text-primary px-3 py-1.5 text-xs font-medium hover:bg-primary hover:text-primary-foreground transition-colors"
            >
              <MessageSquare className="h-3.5 w-3.5" />
              <span>Ask AI About File</span>
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
              aria-label="Close code preview"
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
              <span className="text-muted-foreground text-sm font-sans">Loading file content…</span>
            </div>
          ) : isError ? (
            <p className="text-destructive py-8 font-sans">
              Could not load file content. Chunks might still be indexing.
            </p>
          ) : (
            <div className="space-y-6">
              {/* Symbols Section (if any) */}
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

              {/* Code Viewer with Lines */}
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
    if (isFailed) {
      currentIndex = 0;
    } else {
      currentIndex = -1;
    }
  }

  return (
    <div className="relative">
      <div className="flex items-center justify-between">
        {STAGES.map((step, index) => {
          const isCompleted = index < currentIndex || currentStage === 'READY';
          const isCurrent = index === currentIndex && !isFailed;
          const isCurrentFailed = index === currentIndex && isFailed;

          return (
            <div key={step.id} className="relative z-10 flex flex-col items-center gap-3">
              <div
                className={cn(
                  'flex h-10 w-10 items-center justify-center rounded-full border-2 bg-background transition-colors',
                  isCompleted
                    ? 'border-emerald-600 text-emerald-600'
                    : isCurrent
                    ? 'border-blue-600 text-blue-600 shadow-sm'
                    : isCurrentFailed
                    ? 'border-destructive text-destructive'
                    : 'border-muted-foreground/30 text-muted-foreground',
                )}
              >
                {isCompleted ? (
                  <CheckCircle2 className="h-5 w-5" />
                ) : isCurrent ? (
                  <RefreshCw className="h-5 w-5 animate-spin" />
                ) : isCurrentFailed ? (
                  <XCircle className="h-5 w-5" />
                ) : (
                  <Clock className="h-5 w-5 opacity-50" />
                )}
              </div>

              <span
                className={cn(
                  'text-sm font-medium transition-colors',
                  isCompleted
                    ? 'text-foreground'
                    : isCurrent
                    ? 'text-blue-600'
                    : isCurrentFailed
                    ? 'text-destructive'
                    : 'text-muted-foreground',
                )}
              >
                {step.label}
              </span>
            </div>
          );
        })}
      </div>

      <div className="absolute left-0 top-5 -z-10 h-[2px] w-full -translate-y-1/2 bg-muted-foreground/20" />

      <div
        className="absolute left-0 top-5 -z-10 h-[2px] -translate-y-1/2 bg-emerald-600 transition-all duration-500 ease-in-out"
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

