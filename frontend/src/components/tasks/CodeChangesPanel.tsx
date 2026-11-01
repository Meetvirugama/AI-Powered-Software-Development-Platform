import { useState } from 'react';
import {
  FileCode,
  FileDiff,
  Plus,
  Minus,
  ChevronDown,
  ChevronRight,
  Target,
  ListTodo,
  Layers,
  RefreshCw,
} from 'lucide-react';
import { useTaskDiff } from '../../hooks/useTasks';
import type { TaskDiffRanges } from '../../types/task';
import type { ApiError } from '../../types/api';
import { LoadingSpinner } from '../shared/LoadingSpinner';
import { cn } from '../../lib/utils';

export interface CodeChangesPanelProps {
  taskId?: string;
  repositoryId?: string;
  plannedTargetFiles?: string[];
  plannedExpectedFiles?: string[];
  diffData?: TaskDiffRanges | null;
  isLoading?: boolean;
  error?: ApiError | null;
  className?: string;
}

function getFileStatusBadge(status: string) {
  switch (status.toLowerCase()) {
    case 'added':
      return {
        label: 'ADDED',
        className: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
      };
    case 'removed':
    case 'deleted':
      return {
        label: 'REMOVED',
        className: 'bg-rose-500/10 text-rose-400 border-rose-500/30',
      };
    case 'renamed':
      return {
        label: 'RENAMED',
        className: 'bg-purple-500/10 text-purple-400 border-purple-500/30',
      };
    case 'modified':
    default:
      return {
        label: 'MODIFIED',
        className: 'bg-sky-500/10 text-sky-400 border-sky-500/30',
      };
  }
}

export function CodeChangesPanel({
  taskId,
  repositoryId,
  plannedTargetFiles = [],
  plannedExpectedFiles = [],
  diffData: initialDiff,
  isLoading: initialLoading,
  error: initialError,
  className,
}: CodeChangesPanelProps) {
  const {
    data: fetchedDiff,
    isLoading: queryLoading,
    isError: queryIsError,
    error: queryError,
    refetch,
    isFetching,
  } = useTaskDiff(taskId, repositoryId, {
    enabled: initialDiff === undefined,
  });

  const diffData = initialDiff !== undefined ? initialDiff : fetchedDiff;
  const isLoading = initialLoading !== undefined ? initialLoading : queryLoading;
  const error = initialError !== undefined ? initialError : (queryIsError ? queryError : null);

  // Expanded file patches state
  const [expandedFiles, setExpandedFiles] = useState<Record<string, boolean>>({});

  function toggleFile(filePath: string) {
    setExpandedFiles((prev) => ({
      ...prev,
      [filePath]: !prev[filePath],
    }));
  }

  // Deduplicate planned files
  const uniqueTargetFiles = Array.from(new Set(plannedTargetFiles));
  const uniqueExpectedFiles = Array.from(new Set(plannedExpectedFiles));

  return (
    <div
      data-testid="code-changes-panel"
      className={cn(
        'rounded-lg border border-border bg-card p-5 shadow-xs space-y-6',
        className
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border pb-3">
        <div className="flex items-center gap-2">
          <FileDiff className="h-4 w-4 text-primary" />
          <h3 className="text-base font-semibold text-foreground">Code Changes & Diff Telemetry</h3>
        </div>

        <button
          type="button"
          onClick={() => refetch()}
          disabled={isFetching || isLoading}
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground p-1 rounded hover:bg-accent transition-colors disabled:opacity-50"
          title="Refresh diff telemetry"
        >
          <RefreshCw className={cn('h-3.5 w-3.5', (isFetching || isLoading) && 'animate-spin')} />
        </button>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Section 1: Planned Changes (Pre-Execution Forecast)                */}
      {/* ------------------------------------------------------------------ */}
      <div className="rounded-md border border-border/80 bg-background/40 p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h4 className="text-xs font-semibold uppercase text-muted-foreground tracking-wider flex items-center gap-1.5">
            <Layers className="h-3.5 w-3.5 text-primary" />
            Planned Changes (Pre-Execution Forecast)
          </h4>
          <span className="text-[11px] text-muted-foreground/80 italic">
            Not actual modifications
          </span>
        </div>

        <p className="text-xs text-muted-foreground">
          Files forecasted by task requirements and implementation plan steps. These reflect planned scope, not verified workspace modifications.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1">
          {/* Requirement Target Files */}
          <div className="space-y-1.5">
            <span className="text-[11px] font-medium text-foreground flex items-center gap-1">
              <Target className="h-3 w-3 text-primary" />
              Requirement Target Files ({uniqueTargetFiles.length})
            </span>
            {uniqueTargetFiles.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {uniqueTargetFiles.map((file) => (
                  <span
                    key={file}
                    className="font-mono text-[11px] bg-background px-2 py-0.5 rounded border border-border/80 text-foreground/90"
                  >
                    {file}
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground italic">No requirement targets specified.</p>
            )}
          </div>

          {/* Plan Expected Files */}
          <div className="space-y-1.5">
            <span className="text-[11px] font-medium text-foreground flex items-center gap-1">
              <ListTodo className="h-3 w-3 text-sky-400" />
              Plan Expected Files ({uniqueExpectedFiles.length})
            </span>
            {uniqueExpectedFiles.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {uniqueExpectedFiles.map((file) => (
                  <span
                    key={file}
                    className="font-mono text-[11px] bg-background px-2 py-0.5 rounded border border-border/80 text-foreground/90"
                  >
                    {file}
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground italic">No plan files specified.</p>
            )}
          </div>
        </div>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Section 2: Actual Workspace Modifications (Git Diff Telemetry)     */}
      {/* ------------------------------------------------------------------ */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h4 className="text-xs font-semibold uppercase text-muted-foreground tracking-wider flex items-center gap-1.5">
            <FileCode className="h-3.5 w-3.5 text-emerald-400" />
            Actual Workspace Modifications
          </h4>

          {diffData && (
            <div className="flex items-center gap-3 font-mono text-xs">
              <span className="text-muted-foreground">
                {diffData.total_files_changed} file{diffData.total_files_changed === 1 ? '' : 's'} changed
              </span>
              <span className="text-emerald-400 font-semibold flex items-center">
                <Plus className="h-3 w-3 inline" />
                {diffData.total_additions}
              </span>
              <span className="text-rose-400 font-semibold flex items-center">
                <Minus className="h-3 w-3 inline" />
                {diffData.total_deletions}
              </span>
            </div>
          )}
        </div>

        {isLoading ? (
          <div className="py-8 text-center space-y-2">
            <LoadingSpinner size="sm" label="Loading git diff..." />
            <p className="text-xs text-muted-foreground">Inspecting workspace branch diff...</p>
          </div>
        ) : error || !diffData || !diffData.files ? (
          <div className="p-4 border border-dashed border-border rounded-md bg-background/50 text-center space-y-1.5">
            <p className="text-xs font-medium text-foreground">Diff Telemetry Unavailable</p>
            <p className="text-xs text-muted-foreground">
              Workspace git diff has not been generated or execution has not modified files yet.
            </p>
          </div>
        ) : diffData.files.length === 0 ? (
          <div className="p-6 text-center border border-dashed border-border rounded-md bg-background/50 space-y-1.5">
            <FileDiff className="h-6 w-6 mx-auto text-muted-foreground/60" />
            <p className="text-xs font-medium text-foreground">No Actual Changes Detected</p>
            <p className="text-xs text-muted-foreground">
              The isolated workspace currently has zero modified files relative to the base revision.
            </p>
          </div>
        ) : (
          <div className="space-y-2.5">
            {diffData.files.map((file) => {
              const badge = getFileStatusBadge(file.status);
              const isExpanded = expandedFiles[file.file_path] ?? true;

              return (
                <div
                  key={file.file_path}
                  data-testid={`diff-file-${file.file_path}`}
                  className="rounded-md border border-border/80 bg-background/50 overflow-hidden"
                >
                  {/* File Header */}
                  <button
                    type="button"
                    onClick={() => toggleFile(file.file_path)}
                    className="w-full flex items-center justify-between p-3 hover:bg-accent/40 transition-colors text-left"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      {isExpanded ? (
                        <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />
                      ) : (
                        <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
                      )}
                      <span className="font-mono text-xs font-semibold text-foreground truncate">
                        {file.file_path}
                      </span>
                      <span
                        className={cn(
                          'font-mono text-[10px] font-semibold px-1.5 py-0.2 rounded border',
                          badge.className
                        )}
                      >
                        {badge.label}
                      </span>
                    </div>

                    <div className="flex items-center gap-3 font-mono text-xs shrink-0">
                      <span className="text-emerald-400 font-medium">+{file.additions}</span>
                      <span className="text-rose-400 font-medium">-{file.deletions}</span>
                    </div>
                  </button>

                  {/* Diff Hunk Content */}
                  {isExpanded && (
                    <div className="border-t border-border/60 bg-muted/20 p-3 font-mono text-xs overflow-x-auto max-h-72 overflow-y-auto">
                      {file.patch ? (
                        <pre className="space-y-0.5 leading-relaxed">
                          {file.patch.split('\n').map((line, idx) => {
                            let lineStyle = 'text-foreground/80';
                            if (line.startsWith('+') && !line.startsWith('+++')) {
                              lineStyle = 'text-emerald-400 bg-emerald-950/20 block px-1 rounded-xs';
                            } else if (line.startsWith('-') && !line.startsWith('---')) {
                              lineStyle = 'text-rose-400 bg-rose-950/20 block px-1 rounded-xs';
                            } else if (line.startsWith('@@')) {
                              lineStyle = 'text-cyan-400 bg-cyan-950/30 block px-1 font-semibold rounded-xs';
                            }

                            return (
                              <span key={idx} className={lineStyle}>
                                {line || ' '}
                              </span>
                            );
                          })}
                        </pre>
                      ) : file.diff_ranges && file.diff_ranges.length > 0 ? (
                        <div className="space-y-1">
                          <p className="text-muted-foreground text-[11px] mb-1">Modified Line Ranges:</p>
                          {file.diff_ranges.map((rng, rIdx) => (
                            <div key={rIdx} className="text-foreground/90 pl-2">
                              • Lines {rng.start_line} – {rng.end_line} ({rng.change_type || 'modified'})
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-muted-foreground italic text-xs">
                          Diff hunks not captured for this file.
                        </p>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
