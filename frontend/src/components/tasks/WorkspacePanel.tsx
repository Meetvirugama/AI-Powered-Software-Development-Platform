import {
  Box,
  GitBranch,
  GitCommit,
  Folder,
  Clock,
  Shield,
  AlertTriangle,
  HardDrive,
  Cpu,
  FileCheck2,
  RefreshCw,
} from 'lucide-react';
import { useTaskWorkspace } from '../../hooks/useTasks';
import {
  WorkspaceStatus,
  type WorkspaceMetadata,
} from '../../types/task';
import type { ApiError } from '../../types/api';
import { LoadingSpinner } from '../shared/LoadingSpinner';
import { ErrorMessage } from '../shared/ErrorMessage';
import { cn } from '../../lib/utils';

export interface WorkspacePanelProps {
  taskId?: string;
  workspace?: WorkspaceMetadata | null;
  isLoading?: boolean;
  error?: ApiError | null;
  onRefresh?: () => void;
  className?: string;
}

function formatDate(dateStr: string): string {
  try {
    return new Date(dateStr).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return dateStr;
  }
}

function getWorkspaceStatusBadge(status: WorkspaceStatus | string) {
  const norm = String(status || '').toUpperCase();
  switch (norm) {
    case WorkspaceStatus.CREATING:
      return {
        label: 'CREATING',
        className: 'bg-amber-500/10 text-amber-400 border-amber-500/30 animate-pulse',
      };
    case WorkspaceStatus.READY:
      return {
        label: 'READY',
        className: 'bg-sky-500/10 text-sky-400 border-sky-500/30',
      };
    case WorkspaceStatus.IN_USE:
      return {
        label: 'IN USE',
        className: 'bg-blue-500/10 text-blue-400 border-blue-500/30 animate-pulse',
      };
    case WorkspaceStatus.STOPPED:
      return {
        label: 'STOPPED',
        className: 'bg-zinc-500/10 text-zinc-400 border-zinc-500/30',
      };
    case WorkspaceStatus.FAILED:
      return {
        label: 'FAILED',
        className: 'bg-rose-500/10 text-rose-400 border-rose-500/30',
      };
    case WorkspaceStatus.CLEANUP_PENDING:
      return {
        label: 'CLEANUP PENDING',
        className: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
      };
    case WorkspaceStatus.CLEANED:
      return {
        label: 'CLEANED',
        className: 'bg-purple-500/10 text-purple-400 border-purple-500/30',
      };
    case WorkspaceStatus.NOT_CREATED:
    default:
      return {
        label: 'NOT CREATED',
        className: 'bg-zinc-500/10 text-zinc-400 border-zinc-500/30',
      };
  }
}

export function WorkspacePanel({
  taskId,
  workspace: initialWorkspace,
  isLoading: initialLoading,
  error: initialError,
  onRefresh,
  className,
}: WorkspacePanelProps) {
  // If workspace is not explicitly passed, query it
  const {
    data: fetchedWorkspace,
    isLoading: queryLoading,
    isError: queryIsError,
    error: queryError,
    refetch,
    isFetching,
  } = useTaskWorkspace(taskId, {
    enabled: initialWorkspace === undefined,
  });

  const workspace = initialWorkspace !== undefined ? initialWorkspace : fetchedWorkspace;
  const isLoading = initialLoading !== undefined ? initialLoading : queryLoading;
  const error = initialError !== undefined ? initialError : (queryIsError ? queryError : null);

  function handleRefresh() {
    if (onRefresh) {
      onRefresh();
    } else {
      refetch();
    }
  }

  return (
    <div
      data-testid="workspace-panel"
      className={cn(
        'rounded-lg border border-border bg-card p-5 shadow-xs space-y-4',
        className
      )}
    >
      <div className="flex items-center justify-between border-b border-border pb-3">
        <div className="flex items-center gap-2">
          <Box className="h-4 w-4 text-primary" />
          <h3 className="text-base font-semibold text-foreground">Isolated Workspace Sandbox</h3>
        </div>

        <div className="flex items-center gap-2.5">
          {workspace?.status && (
            <span
              data-testid="workspace-status-badge"
              className={cn(
                'font-mono text-[11px] font-semibold px-2 py-0.5 rounded border uppercase',
                getWorkspaceStatusBadge(workspace.status).className
              )}
            >
              {getWorkspaceStatusBadge(workspace.status).label}
            </span>
          )}

          <button
            type="button"
            onClick={handleRefresh}
            disabled={isFetching || isLoading}
            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground p-1 rounded hover:bg-accent transition-colors disabled:opacity-50"
            title="Refresh workspace status"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', (isFetching || isLoading) && 'animate-spin')} />
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="py-8 text-center space-y-2">
          <LoadingSpinner size="sm" label="Loading workspace..." />
          <p className="text-xs text-muted-foreground">Checking sandbox allocation status...</p>
        </div>
      ) : error ? (
        <div className="space-y-3 py-2">
          <ErrorMessage error={error} message="Failed to load workspace metadata." />
        </div>
      ) : !workspace || workspace.status === WorkspaceStatus.NOT_CREATED ? (
        <div className="p-6 text-center border border-dashed border-border rounded-md bg-background/50 space-y-2">
          <Box className="h-7 w-7 mx-auto text-muted-foreground/60" />
          <p className="text-xs font-medium text-foreground">Workspace Not Created</p>
          <p className="text-xs text-muted-foreground max-w-md mx-auto">
            An isolated Git worktree workspace will be automatically allocated when execution is started.
          </p>
        </div>
      ) : (
        <div className="space-y-4 text-xs">
          {/* Workspace Creation Failure Banner */}
          {(workspace.status === WorkspaceStatus.FAILED || workspace.error_message) && (
            <div
              data-testid="workspace-error-banner"
              className="rounded-md border border-rose-500/30 bg-rose-500/10 p-3.5 text-xs text-rose-300 space-y-1"
            >
              <div className="flex items-center gap-1.5 font-semibold text-rose-400">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                <span>Workspace Allocation or Execution Failed</span>
              </div>
              <p className="text-rose-200/90 pl-5.5">
                {workspace.error_message || 'Sandbox creation or execution encountered an unrecoverable failure.'}
              </p>
            </div>
          )}

          {/* Primary Metadata Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {/* Workspace ID */}
            <div className="rounded-md border border-border/80 bg-background/50 p-3 space-y-1">
              <span className="text-[11px] text-muted-foreground font-medium flex items-center gap-1">
                <Box className="h-3 w-3 text-primary" /> Workspace ID
              </span>
              <p className="font-mono text-xs text-foreground font-semibold truncate" title={workspace.workspace_id}>
                {workspace.workspace_id || 'Not assigned'}
              </p>
            </div>

            {/* Task Branch */}
            <div className="rounded-md border border-border/80 bg-background/50 p-3 space-y-1">
              <span className="text-[11px] text-muted-foreground font-medium flex items-center gap-1">
                <GitBranch className="h-3 w-3 text-sky-400" /> Task Branch
              </span>
              <p className="font-mono text-xs text-foreground font-semibold truncate" title={workspace.branch_name}>
                {workspace.branch_name || 'Not assigned'}
              </p>
            </div>

            {/* Base Revision */}
            <div className="rounded-md border border-border/80 bg-background/50 p-3 space-y-1">
              <span className="text-[11px] text-muted-foreground font-medium flex items-center gap-1">
                <GitCommit className="h-3 w-3 text-purple-400" /> Base Revision
              </span>
              <p className="font-mono text-xs text-foreground font-semibold truncate" title={workspace.base_revision}>
                {workspace.base_revision ? workspace.base_revision.substring(0, 12) : 'Not available'}
              </p>
            </div>

            {/* Isolation Type */}
            {workspace.isolation_type && (
              <div className="rounded-md border border-border/80 bg-background/50 p-3 space-y-1">
                <span className="text-[11px] text-muted-foreground font-medium flex items-center gap-1">
                  <Shield className="h-3 w-3 text-emerald-400" /> Isolation Mode
                </span>
                <p className="font-mono text-xs text-foreground font-semibold">
                  {workspace.isolation_type}
                </p>
              </div>
            )}

            {/* Execution Started / Created Timestamp */}
            {(workspace.started_at || workspace.created_at) && (
              <div className="rounded-md border border-border/80 bg-background/50 p-3 space-y-1">
                <span className="text-[11px] text-muted-foreground font-medium flex items-center gap-1">
                  <Clock className="h-3 w-3 text-muted-foreground" />
                  {workspace.started_at ? 'Started At' : 'Created At'}
                </span>
                <p className="font-mono text-[11px] text-foreground">
                  {formatDate(workspace.started_at || workspace.created_at!)}
                </p>
              </div>
            )}

            {/* Execution Stopped / Cleaned Timestamp */}
            {(workspace.stopped_at || workspace.cleaned_at) && (
              <div className="rounded-md border border-border/80 bg-background/50 p-3 space-y-1">
                <span className="text-[11px] text-muted-foreground font-medium flex items-center gap-1">
                  <Clock className="h-3 w-3 text-amber-400" />
                  {workspace.stopped_at ? 'Stopped At' : 'Cleaned At'}
                </span>
                <p className="font-mono text-[11px] text-foreground">
                  {formatDate(workspace.stopped_at || workspace.cleaned_at!)}
                </p>
              </div>
            )}
          </div>

          {/* Workspace Path (if supplied) */}
          {workspace.workspace_path && (
            <div className="rounded-md border border-border/80 bg-background/50 p-3 space-y-1">
              <span className="text-[11px] text-muted-foreground font-medium flex items-center gap-1">
                <Folder className="h-3 w-3 text-amber-400" /> Workspace Filesystem Path
              </span>
              <p className="font-mono text-xs text-foreground/90 break-all select-all">
                {workspace.workspace_path}
              </p>
            </div>
          )}

          {/* Resource Limits (if supplied) */}
          {workspace.resource_limits && (
            <div className="rounded-md border border-border/80 bg-background/40 p-3.5 space-y-2">
              <span className="text-[11px] font-semibold uppercase text-muted-foreground tracking-wider flex items-center gap-1.5">
                <Shield className="h-3.5 w-3.5 text-primary" /> Resource Limits & Quotas
              </span>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1 font-mono text-[11px]">
                {workspace.resource_limits.timeout_seconds !== undefined && (
                  <div className="flex items-center gap-1 text-muted-foreground">
                    <Cpu className="h-3 w-3 text-muted-foreground" />
                    <span>Timeout: {workspace.resource_limits.timeout_seconds}s</span>
                  </div>
                )}

                {workspace.resource_limits.max_disk_bytes !== undefined && (
                  <div className="flex items-center gap-1 text-muted-foreground">
                    <HardDrive className="h-3 w-3 text-muted-foreground" />
                    <span>
                      Disk: {Math.round(workspace.resource_limits.max_disk_bytes / (1024 * 1024))} MB
                    </span>
                  </div>
                )}

                {workspace.resource_limits.max_file_size_bytes !== undefined && (
                  <div className="flex items-center gap-1 text-muted-foreground">
                    <HardDrive className="h-3 w-3 text-muted-foreground" />
                    <span>
                      Max File: {Math.round(workspace.resource_limits.max_file_size_bytes / (1024 * 1024))} MB
                    </span>
                  </div>
                )}

                {workspace.resource_limits.max_files_modified !== undefined && (
                  <div className="flex items-center gap-1 text-muted-foreground">
                    <FileCheck2 className="h-3 w-3 text-muted-foreground" />
                    <span>Max Files: {workspace.resource_limits.max_files_modified}</span>
                  </div>
                )}

                {workspace.resource_limits.network_egress_allowed !== undefined && (
                  <div className="col-span-2 sm:col-span-4 flex items-center gap-1 text-[11px] pt-1">
                    <span className="text-muted-foreground">Network Egress:</span>
                    <span
                      className={cn(
                        'px-1.5 py-0.2 rounded text-[10px] font-semibold',
                        workspace.resource_limits.network_egress_allowed
                          ? 'bg-amber-500/10 text-amber-400'
                          : 'bg-emerald-500/10 text-emerald-400'
                      )}
                    >
                      {workspace.resource_limits.network_egress_allowed ? 'Allowed' : 'Strictly Blocked'}
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
