import { useParams, Link } from 'react-router-dom';
import {
  useRepository,
  useRepositoryFiles,
  useRepositoryDependencies,
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
    isError: filesError 
  } = useRepositoryFiles(id, 1, 100, { enabled: isReady }); // use larger page size to ensure we get root files

  const { 
    data: dependencies, 
    isLoading: depsLoading, 
    isError: depsError 
  } = useRepositoryDependencies(id, { enabled: isReady });

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

  // ------------------------------------------------------------------
  // Main Render
  // ------------------------------------------------------------------

  return (
    <div className="space-y-8 max-w-5xl">
      {/* Back link */}
      <Link
        to="/app/dashboard"
        className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Dashboard
      </Link>

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
              <RefreshCw className="h-4 w-4" />
              <span>{progress.label}</span>
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
            (!progress.isComplete) || progress.isFailed
              ? 'pointer-events-none opacity-50'
              : 'hover:bg-primary/90'
          )}
          aria-disabled={(!progress.isComplete) || progress.isFailed}
          tabIndex={(!progress.isComplete) || progress.isFailed ? -1 : undefined}
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
        <div className="rounded-xl border border-border bg-card p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-foreground mb-2">Repository Syncing</h2>
          <p className="text-sm text-muted-foreground mb-6">
            The repository is currently being processed. Explorer features will be available once syncing is complete.
          </p>
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
                  <div className="flex justify-center py-4"><LoadingSpinner size="sm" /></div>
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

          {/* Right Column: File Tree */}
          <div className="md:col-span-2">
            <div className="rounded-xl border border-border bg-card shadow-sm overflow-hidden h-full flex flex-col">
              <div className="bg-muted/30 px-4 py-3 border-b border-border flex items-center justify-between shrink-0">
                <h3 className="font-semibold text-sm text-foreground">File Explorer (Preview)</h3>
              </div>
              <div className="p-4 flex-1 overflow-y-auto max-h-[600px] min-h-[300px]">
                {filesLoading ? (
                  <div className="flex justify-center py-8"><LoadingSpinner size="md" label="Loading files…" /></div>
                ) : filesError ? (
                  <p className="text-sm text-destructive py-4">Failed to load repository files.</p>
                ) : !filesData || filesData.items.length === 0 ? (
                  <p className="text-sm text-muted-foreground italic py-4">No files indexed yet.</p>
                ) : (
                  <FileTree files={filesData.items} />
                )}
              </div>
            </div>
          </div>

        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// File Tree Component (2-level limit)
// ---------------------------------------------------------------------------

function FileTree({ files }: { files: RepositoryFile[] }) {
  // Build a simple 2-level tree from the flat list
  // The backend paginated response doesn't guarantee all files, so we construct
  // what we can from the current page of data.
  
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
    } else if (parts.length === 2) {
      // It's a child of a root directory
      const rootDir = parts[0];
      if (!directories.has(rootDir)) directories.set(rootDir, []);
      directories.get(rootDir)!.push(file);
    }
    // Ignore parts.length > 2 for this 2-level requirement
  }

  // Sort: directories first, then files alphabetically
  const sortedDirs = Array.from(directories.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  rootFiles.sort((a, b) => a.path.localeCompare(b.path));

  const getFileIcon = (filename: string) => {
    if (filename.endsWith('.md')) return <FileText className="h-4 w-4 text-muted-foreground" />;
    if (filename.match(/\.(js|ts|py|go|rs|jsx|tsx|java|cpp|c)$/)) return <FileCode className="h-4 w-4 text-muted-foreground" />;
    return <File className="h-4 w-4 text-muted-foreground" />;
  };

  return (
    <div className="text-sm font-mono">
      {sortedDirs.map(([dirName, children]) => (
        <div key={dirName} className="mb-1">
          <div className="flex items-center gap-2 py-1.5 px-2 hover:bg-accent rounded-md cursor-default text-foreground">
            <Folder className="h-4 w-4 text-blue-500 fill-blue-500/20" />
            <span>{dirName}/</span>
          </div>
          {children.length > 0 && (
            <div className="ml-6 border-l border-border pl-2 my-1">
              {children.sort((a,b) => a.path.localeCompare(b.path)).map(child => {
                const childName = child.path.split('/').filter(Boolean)[1];
                const isChildDir = child.path.endsWith('/');
                return (
                  <div key={child.id} className="flex items-center gap-2 py-1 px-2 hover:bg-accent rounded-md cursor-default text-muted-foreground hover:text-foreground transition-colors">
                    {isChildDir ? <Folder className="h-4 w-4 text-blue-500 fill-blue-500/20" /> : getFileIcon(childName)}
                    <span className="truncate">{childName}{isChildDir ? '/' : ''}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      ))}
      
      {rootFiles.map(file => (
        <div key={file.id} className="flex items-center gap-2 py-1.5 px-2 hover:bg-accent rounded-md cursor-default text-foreground transition-colors">
          {getFileIcon(file.path)}
          <span className="truncate">{file.path}</span>
        </div>
      ))}
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
                    : 'border-muted-foreground/30 text-muted-foreground'
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
                    : 'text-muted-foreground'
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
