import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  History,
  X,
  Clock,
  BookOpen,
  Bug,
  FlaskConical,
  FileCheck,
  AlertCircle,
  ExternalLink,
  ChevronLeft,
  ChevronRight,
  Filter,
} from 'lucide-react';
import { LoadingSpinner } from '../shared/LoadingSpinner';
import { getAnalysisRuns, getAnalysisRun } from '../../services/analysis';
import {
  reconstructAnalysisResult,
  type ReopenedAnalysisResult,
} from '../../lib/reconstructAnalysisResult';
import { cn } from '../../lib/utils';
import type {
  AnalysisFeatureType,
  AnalysisRunSummary,
  AnalysisTarget,
  CodeExplanation,
  BugDetectionResponse,
  TestGenerationResponse,
  ReviewReportResponse,
} from '../../types/analysis';

export interface AnalysisHistoryDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  repositoryId?: string;
  initialFeature?: AnalysisFeatureType | 'all';
  currentFilePath?: string;
  onReopenExplain?: (explanation: CodeExplanation, target: AnalysisTarget, runId: string) => void;
  onReopenBugs?: (bugResult: BugDetectionResponse, target: AnalysisTarget, runId: string) => void;
  onReopenTests?: (testResult: TestGenerationResponse, target: AnalysisTarget, runId: string) => void;
  onReopenReview?: (reviewResult: ReviewReportResponse) => void;
}

const FEATURE_CONFIG: Record<
  string,
  { label: string; icon: typeof BookOpen; color: string; badge: string }
> = {
  explain: {
    label: 'Explain',
    icon: BookOpen,
    color: 'text-blue-400',
    badge: 'bg-blue-500/10 text-blue-400 border-blue-500/30',
  },
  detect_bugs: {
    label: 'Bugs',
    icon: Bug,
    color: 'text-amber-400',
    badge: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
  },
  bugs: {
    label: 'Bugs',
    icon: Bug,
    color: 'text-amber-400',
    badge: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
  },
  generate_tests: {
    label: 'Tests',
    icon: FlaskConical,
    color: 'text-emerald-400',
    badge: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
  },
  tests: {
    label: 'Tests',
    icon: FlaskConical,
    color: 'text-emerald-400',
    badge: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
  },
  review: {
    label: 'Review',
    icon: FileCheck,
    color: 'text-purple-400',
    badge: 'bg-purple-500/10 text-purple-400 border-purple-500/30',
  },
};

export function AnalysisHistoryDrawer({
  isOpen,
  onClose,
  repositoryId,
  initialFeature = 'all',
  currentFilePath,
  onReopenExplain,
  onReopenBugs,
  onReopenTests,
  onReopenReview,
}: AnalysisHistoryDrawerProps) {
  const [featureFilter, setFeatureFilter] = useState<string>(
    initialFeature === 'bugs'
      ? 'detect_bugs'
      : initialFeature === 'tests'
      ? 'generate_tests'
      : initialFeature
  );
  const [filterCurrentFile, setFilterCurrentFile] = useState(false);
  const [statusFilter, setStatusFilter] = useState<'all' | 'COMPLETED' | 'FAILED'>('all');
  const [page, setPage] = useState(1);
  const pageSize = 8;

  const [reopeningId, setReopeningId] = useState<string | null>(null);
  const [unavailableMessage, setUnavailableMessage] = useState<string | null>(null);

  // Sync initialFeature when drawer opens via render-phase state adjustment
  const [prevIsOpen, setPrevIsOpen] = useState(isOpen);
  if (!prevIsOpen && isOpen) {
    setPrevIsOpen(true);
    setFeatureFilter(
      initialFeature === 'bugs'
        ? 'detect_bugs'
        : initialFeature === 'tests'
        ? 'generate_tests'
        : initialFeature
    );
    setPage(1);
    setUnavailableMessage(null);
  } else if (prevIsOpen && !isOpen) {
    setPrevIsOpen(false);
  }

  const queryParams = useMemo(() => {
    const params: Record<string, string | number> = {
      page,
      page_size: pageSize,
    };
    if (featureFilter !== 'all') {
      params.feature_type = featureFilter;
    }
    if (statusFilter !== 'all') {
      params.status = statusFilter;
    }
    if (filterCurrentFile && currentFilePath) {
      params.target_path = currentFilePath;
    }
    return params;
  }, [page, pageSize, featureFilter, statusFilter, filterCurrentFile, currentFilePath]);

  const {
    data: historyData,
    isLoading,
    error: queryError,
  } = useQuery({
    queryKey: ['analysis-runs', repositoryId, queryParams],
    queryFn: () => getAnalysisRuns(repositoryId!, queryParams),
    enabled: Boolean(isOpen && repositoryId),
  });

  const runs: AnalysisRunSummary[] = historyData?.items || [];
  const totalRuns = historyData?.total || 0;
  const error = queryError instanceof Error ? queryError.message : queryError ? 'Failed to fetch analysis history runs.' : null;

  if (!isOpen) return null;

  const totalPages = Math.max(1, Math.ceil(totalRuns / pageSize));

  async function handleReopenRun(runId: string) {
    setReopeningId(runId);
    setUnavailableMessage(null);

    try {
      const detail = await getAnalysisRun(runId);
      const parsed: ReopenedAnalysisResult = reconstructAnalysisResult(detail);

      if (parsed.kind === 'unavailable') {
        setUnavailableMessage(parsed.message);
        return;
      }

      if (parsed.kind === 'explain' && onReopenExplain) {
        onReopenExplain(parsed.explanation, parsed.target, parsed.runId);
        onClose();
      } else if (parsed.kind === 'bugs' && onReopenBugs) {
        onReopenBugs(parsed.bugResult, parsed.target, parsed.runId);
        onClose();
      } else if (parsed.kind === 'tests' && onReopenTests) {
        onReopenTests(parsed.testResult, parsed.target, parsed.runId);
        onClose();
      } else if (parsed.kind === 'review' && onReopenReview) {
        onReopenReview(parsed.reviewResult);
        onClose();
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load details for this analysis run.';
      setUnavailableMessage(msg);
    } finally {
      setReopeningId(null);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-background/80 backdrop-blur-xs animate-in fade-in">
      <div className="w-full max-w-2xl max-h-[85vh] rounded-xl border border-border bg-card shadow-2xl flex flex-col overflow-hidden">
        {/* Drawer Header */}
        <div className="px-4 py-3 border-b border-border bg-muted/20 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2">
            <History className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-semibold text-foreground">
              Analysis History & Reopen
            </h3>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-muted text-muted-foreground border border-border">
              {totalRuns} {totalRuns === 1 ? 'run' : 'runs'}
            </span>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
            aria-label="Close analysis history drawer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Filter Toolbar */}
        <div className="p-3 border-b border-border/60 bg-muted/10 flex flex-wrap items-center justify-between gap-2 shrink-0">
          {/* Feature selector tabs */}
          <div className="flex items-center gap-1 overflow-x-auto py-0.5">
            {[
              { id: 'all', label: 'All' },
              { id: 'explain', label: 'Explain' },
              { id: 'detect_bugs', label: 'Bugs' },
              { id: 'generate_tests', label: 'Tests' },
              { id: 'review', label: 'Review' },
            ].map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => {
                  setFeatureFilter(tab.id);
                  setPage(1);
                }}
                className={cn(
                  'px-2.5 py-1 text-xs rounded-md font-medium transition-colors border',
                  featureFilter === tab.id
                    ? 'bg-primary text-primary-foreground border-primary'
                    : 'bg-background/60 text-muted-foreground border-border/60 hover:text-foreground hover:bg-accent'
                )}
              >
                {tab.label}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            {/* Status dropdown */}
            <select
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value as 'all' | 'COMPLETED' | 'FAILED');
                setPage(1);
              }}
              className="text-xs rounded-md bg-background/80 border border-border/80 px-2 py-1 text-foreground focus:outline-none focus:border-primary"
            >
              <option value="all">All Statuses</option>
              <option value="COMPLETED">Completed</option>
              <option value="FAILED">Failed</option>
            </select>

            {/* Current file filter toggle */}
            {currentFilePath && (
              <button
                type="button"
                onClick={() => {
                  setFilterCurrentFile((prev) => !prev);
                  setPage(1);
                }}
                className={cn(
                  'inline-flex items-center gap-1 px-2.5 py-1 text-xs rounded-md border transition-colors',
                  filterCurrentFile
                    ? 'bg-primary/15 text-primary border-primary/30 font-medium'
                    : 'bg-background/60 text-muted-foreground border-border/60 hover:text-foreground'
                )}
                title={`Filter by current file: ${currentFilePath}`}
              >
                <Filter className="h-3 w-3" />
                <span className="truncate max-w-[120px]">
                  {filterCurrentFile ? 'This File' : 'Filter by File'}
                </span>
              </button>
            )}
          </div>
        </div>

        {/* Unavailable or error notification banner */}
        {unavailableMessage && (
          <div className="m-3 p-3 rounded-lg border border-amber-500/30 bg-amber-500/10 text-xs text-amber-400 flex items-start gap-2">
            <AlertCircle className="h-4 w-4 shrink-0 mt-0.5 text-amber-500" />
            <div className="flex-1">
              <span className="font-semibold">Unable to Reopen Run:</span>{' '}
              {unavailableMessage}
            </div>
            <button
              onClick={() => setUnavailableMessage(null)}
              className="text-amber-400/80 hover:text-amber-400"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}

        {error && (
          <div className="m-3 p-3 rounded-lg border border-destructive/30 bg-destructive/10 text-xs text-destructive flex items-center gap-2">
            <AlertCircle className="h-4 w-4 shrink-0 text-destructive" />
            <span>{error}</span>
          </div>
        )}

        {/* Runs List */}
        <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-2">
          {isLoading ? (
            <div className="py-12 flex flex-col items-center justify-center gap-2 text-muted-foreground text-xs">
              <LoadingSpinner size="md" />
              <span>Loading saved analysis runs…</span>
            </div>
          ) : runs.length === 0 ? (
            <div className="py-12 text-center text-xs text-muted-foreground space-y-2">
              <Clock className="h-8 w-8 mx-auto opacity-40 text-primary" />
              <p className="font-medium text-foreground">No historical runs found</p>
              <p className="text-[11px] max-w-sm mx-auto">
                {filterCurrentFile
                  ? `No runs recorded for "${currentFilePath}". Try switching off the file filter.`
                  : 'Run an explanation, bug scan, test generation, or code review to see past results here.'}
              </p>
            </div>
          ) : (
            runs.map((run) => {
              const cfg =
                FEATURE_CONFIG[run.feature_type] || {
                  label: run.feature_type,
                  icon: BookOpen,
                  color: 'text-primary',
                  badge: 'bg-muted text-muted-foreground',
                };
              const Icon = cfg.icon;

              return (
                <div
                  key={run.id}
                  className="p-3 rounded-lg border border-border/60 bg-muted/20 hover:border-border transition-colors flex items-center justify-between gap-3 text-xs"
                >
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span
                        className={cn(
                          'inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium border',
                          cfg.badge
                        )}
                      >
                        <Icon className="h-3 w-3" />
                        <span>{cfg.label}</span>
                      </span>

                      <span
                        className={cn(
                          'px-1.5 py-0.5 rounded text-[9px] font-mono uppercase font-bold',
                          run.status === 'COMPLETED'
                            ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                            : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                        )}
                      >
                        {run.status}
                      </span>

                      <span className="text-[10px] text-muted-foreground font-mono">
                        {new Date(run.created_at).toLocaleString()}
                      </span>
                    </div>

                    <div className="font-mono text-[11px] text-foreground truncate">
                      Target: {run.target_path || 'Repository Changes'}
                      {run.target_symbol && (
                        <span className="text-primary ml-1">#{run.target_symbol}</span>
                      )}
                      {run.start_line && (
                        <span className="text-muted-foreground ml-1">
                          (L{run.start_line}–{run.end_line || run.start_line})
                        </span>
                      )}
                    </div>

                    <div className="text-[10px] text-muted-foreground flex items-center gap-2">
                      {run.findings_count > 0 && (
                        <span>
                          {run.findings_count} finding{run.findings_count === 1 ? '' : 's'}
                        </span>
                      )}
                      {run.source_revision && (
                        <span className="font-mono">
                          rev: {run.source_revision.slice(0, 7)}
                        </span>
                      )}
                    </div>
                  </div>

                  <button
                    type="button"
                    disabled={reopeningId === run.id || run.status === 'FAILED'}
                    onClick={() => handleReopenRun(run.id)}
                    className="shrink-0 inline-flex items-center gap-1 px-3 py-1.5 rounded-md text-xs font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-40 disabled:cursor-not-allowed shadow-xs"
                    title={
                      run.status === 'FAILED'
                        ? 'Failed run cannot be reopened'
                        : 'Reopen this historical result'
                    }
                  >
                    {reopeningId === run.id ? (
                      <>
                        <LoadingSpinner size="sm" />
                        <span>Loading…</span>
                      </>
                    ) : (
                      <>
                        <ExternalLink className="h-3 w-3" />
                        <span>Reopen</span>
                      </>
                    )}
                  </button>
                </div>
              );
            })
          )}
        </div>

        {/* Pagination Footer */}
        {totalRuns > pageSize && (
          <div className="px-4 py-2 border-t border-border bg-muted/20 flex items-center justify-between text-xs text-muted-foreground shrink-0">
            <span>
              Page {page} of {totalPages} ({totalRuns} total)
            </span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="p-1 rounded border border-border/80 bg-background hover:bg-accent disabled:opacity-40 transition-colors"
                aria-label="Previous page"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
                className="p-1 rounded border border-border/80 bg-background hover:bg-accent disabled:opacity-40 transition-colors"
                aria-label="Next page"
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
