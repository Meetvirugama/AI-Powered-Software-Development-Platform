import { useParams, Link } from 'react-router-dom';
import { useRepository, syncProgressFromStatus } from '../hooks/useRepositories';
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
} from 'lucide-react';
import type { SyncStage } from '../types/api';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/**
 * How often to poll the repository detail endpoint while a sync is active.
 *
 * Polling is isolated to this page and only active when the sync is running.
 */
const SYNC_POLL_INTERVAL_MS = 3000;

// ---------------------------------------------------------------------------
// Repository Detail Page
// ---------------------------------------------------------------------------

export function RepositoryDetail() {
  const { id } = useParams<{ id: string }>();

  // ------------------------------------------------------------------
  // Repository query
  // ------------------------------------------------------------------
  // We determine if we need to poll by checking if the data indicates an active sync.
  // We can't use the hook's returned data before calling the hook, so we provide
  // a dynamic refetchInterval function. TanStack Query v5 allows refetchInterval
  // to be a function receiving the query.
  //
  // However, useQuery in v5 accepts refetchInterval as `number | false | ((query: Query) => number | false | undefined)`.
  // To keep it simple and safe for standard React Query v5 usage, we just use a small
  // wrapper or derive it. Actually, `useQuery` accepts a function `(query) => number | false`.
  // We can also just read the `data` in the component and pass the interval dynamically,
  // since `useQuery` reacts to option changes.
  // ------------------------------------------------------------------

  const { data: repo, isLoading, isError, error } = useRepository(id);

  // If we have data and the sync is not complete/failed, we poll.
  const progress = repo ? syncProgressFromStatus(repo.sync_status) : null;
  const isPolling = progress?.isActive ?? false;

  // Re-run the hook to apply the refetchInterval. React Query merges options.
  useRepository(id, {
    refetchInterval: isPolling ? SYNC_POLL_INTERVAL_MS : false,
  });

  // ------------------------------------------------------------------
  // Loading & Error States
  // ------------------------------------------------------------------

  if (isLoading) {
    return (
      <div className="flex h-[50vh] flex-col items-center justify-center gap-4">
        <LoadingSpinner size="lg" label="Loading repository details…" />
      </div>
    );
  }

  if (isError || !repo || !progress) {
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
          message={error instanceof Error ? error.message : 'Repository not found.'}
        />
      </div>
    );
  }

  // ------------------------------------------------------------------
  // Main Render
  // ------------------------------------------------------------------

  return (
    <div className="space-y-8 max-w-4xl">
      {/* Back link */}
      <Link
        to="/app/dashboard"
        className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Dashboard
      </Link>

      {/* Header */}
      <div className="flex flex-col gap-4 border-b border-border pb-6 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold text-foreground">{repo.name}</h1>
          <p className="mt-1 text-base text-muted-foreground">{repo.full_name}</p>
        </div>
        <Link
          to={`/app/repositories/${repo.id}/chat`}
          // Disable chat if sync failed or not started
          className={cn(
            'inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
            (!progress.isComplete && !progress.isActive) || progress.isFailed
              ? 'pointer-events-none opacity-50'
              : 'hover:bg-primary/90'
          )}
          aria-disabled={(!progress.isComplete && !progress.isActive) || progress.isFailed}
        >
          <MessageSquare className="h-4 w-4" />
          Open Chat
        </Link>
      </div>

      {/* Sync Progress Indicator */}
      <div className="rounded-xl border border-border bg-card p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-foreground mb-6">Sync Status</h2>
        <SyncProgressIndicator
          currentStage={progress.stage}
          isFailed={progress.isFailed}
        />
      </div>

      {/* Future sections (Day 5/6) */}
      <div className="rounded-xl border border-dashed border-border p-8 text-center text-muted-foreground">
        <p>Repository metrics, PRs, and execution tasks will appear here.</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sync Progress Indicator Component
//
// Renders the Cloning → Scanning → Indexing → Ready flow required by week1.md.
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
  // If not started or failed without reaching a stage, default to 0
  let currentIndex = STAGES.findIndex((s) => s.id === currentStage);
  if (currentIndex === -1) {
    if (isFailed) {
      // If it failed and we don't know the stage, maybe it failed at cloning.
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
              {/* Icon Circle */}
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

              {/* Label */}
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

      {/* Connecting Line (background) */}
      <div className="absolute left-0 top-5 -z-10 h-[2px] w-full -translate-y-1/2 bg-muted-foreground/20" />

      {/* Connecting Line (progress fill) */}
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
