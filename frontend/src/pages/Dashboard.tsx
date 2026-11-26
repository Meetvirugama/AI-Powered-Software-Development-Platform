import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useRepositories } from '../hooks/useRepositories';
import { useTasks } from '../hooks/useTasks';
import { TaskStatusBadge } from '../components/tasks/TaskStatusBadge';
import { TaskStatus } from '../types/task';
import { RepositoryCard } from '../components/shared/RepositoryCard';
import { LoadingSpinner } from '../components/shared/LoadingSpinner';
import { DashboardTasksSkeleton, RepositoryGridSkeleton } from '../components/shared/Skeletons';
import { useSseConnectionStatus } from '../hooks/useSseConnectionStatus';
import { ErrorMessage } from '../components/shared/ErrorMessage';
import type { PaginatedRepositoryResponse, Repository } from '../types/api';
import { PlusCircle, ChevronLeft, ChevronRight, GitBranch, RefreshCw, ListTodo, ArrowRight } from 'lucide-react';
import { cn } from '../lib/utils';

const PAGE_SIZE = 6;
const RECENT_TASKS = 5;

const ATTENTION_STATUSES = new Set<string>([
  TaskStatus.PENDING_APPROVAL,
  TaskStatus.FAILED,
  TaskStatus.RECOVERY_REQUIRED,
  TaskStatus.BLOCKED,
]);
const DONE_STATUSES = new Set<string>([TaskStatus.DRAFT_PR_CREATED, TaskStatus.CANCELLED, TaskStatus.REJECTED]);

export function Dashboard() {
  const [page, setPage] = useState(1);
  const navigate = useNavigate();
  const { isConnected: isSseConnected } = useSseConnectionStatus();

  const { data, isLoading, isFetching, isError, error, refetch } = useRepositories(
    page,
    PAGE_SIZE,
    {
      refetchInterval: (query: { state: { data?: PaginatedRepositoryResponse } }) => {
        if (isSseConnected) return false;
        const items = query.state.data?.items;
        const hasSyncing = items?.some((r: Repository) => r.sync_status === 'SYNCING');
        return hasSyncing ? 20_000 : false;
      },
    },
  );

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  const effectivePage = data ? Math.min(page, totalPages) : page;
  const hasPrev = effectivePage > 1;
  const hasNext = effectivePage < totalPages;

  useEffect(() => {
    if (!data || page <= totalPages) return;
    const timer = window.setTimeout(() => {
      setPage(totalPages);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [data, page, totalPages]);

  return (
    <div className="h-full flex flex-col min-h-0 overflow-hidden">
      {/* Pinned Page Header */}
      <div className="shrink-0 pb-5 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-foreground tracking-tight">Dashboard</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Connected repositories and active engineering tasks.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 self-start sm:self-auto">
          <button
            type="button"
            onClick={() => refetch()}
            disabled={isFetching}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-accent transition-colors disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
            title="Refresh repository list"
            aria-label="Refresh repositories"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', isFetching && 'animate-spin')} />
            <span className="hidden sm:inline">Refresh</span>
          </button>
          <button
            type="button"
            onClick={() => navigate('/app/tasks/new')}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
            aria-label="Create a new task"
          >
            <ListTodo className="h-3.5 w-3.5 text-muted-foreground" />
            New Task
          </button>
          <button
            type="button"
            onClick={() => navigate('/app/repositories')}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
            aria-label="Connect a repository"
          >
            <PlusCircle className="h-3.5 w-3.5" />
            Add Repository
          </button>
        </div>
      </div>

      {/* Scrollable Content */}
      <div className="flex-1 min-h-0 overflow-y-auto pr-1 space-y-6 pb-4">
        {/* Repositories Section */}
        <section aria-label="Repositories" className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Repositories
              {data && data.total > 0 && (
                <span className="ml-2 font-mono text-muted-foreground">{data.total}</span>
              )}
            </h2>
            {isFetching && !isLoading && (
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground" aria-live="polite">
                <LoadingSpinner size="sm" label="Refreshing…" />
                <span>Refreshing…</span>
              </div>
            )}
          </div>

          {isLoading && <RepositoryGridSkeleton count={PAGE_SIZE} label="Loading repositories…" />}

          {isError && !isLoading && (
            <div className="flex flex-col items-center gap-4 py-12">
              <ErrorMessage
                message={error instanceof Error ? error.message : 'Could not load repositories.'}
                className="max-w-md"
              />
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => refetch()}
                  className="rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
                >
                  Retry
                </button>
                <button
                  type="button"
                  onClick={() => navigate('/login')}
                  className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
                >
                  Log in again
                </button>
              </div>
            </div>
          )}

          {!isLoading && !isError && data && data.total === 0 && (
            <EmptyState onAddRepository={() => navigate('/app/repositories')} />
          )}

          {!isLoading && !isError && data && data.items.length > 0 && (
            <div
              className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
              aria-label="Repository list"
            >
              {data.items.map((repo) => (
                <RepositoryCard key={repo.id} repo={repo} />
              ))}
            </div>
          )}
        </section>

        {/* Recent Tasks Section */}
        <TaskOverview
          hasRepositories={Boolean(data && data.total > 0)}
          onCreateTask={() => navigate('/app/tasks/new')}
        />
      </div>

      {/* Pinned Pagination Footer */}
      {!isLoading && !isError && data && data.items.length > 0 && totalPages > 1 && (
        <div className="shrink-0 pt-3 border-t border-border">
          <Pagination
            page={effectivePage}
            totalPages={totalPages}
            total={data.total}
            pageSize={PAGE_SIZE}
            hasPrev={hasPrev}
            hasNext={hasNext}
            onPrev={() => setPage(Math.max(1, effectivePage - 1))}
            onNext={() => setPage(Math.min(totalPages, effectivePage + 1))}
          />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// TaskOverview
// ---------------------------------------------------------------------------

function TaskOverview({
  hasRepositories,
  onCreateTask,
}: {
  hasRepositories: boolean;
  onCreateTask: () => void;
}) {
  const { data, isLoading, isError, refetch } = useTasks({ page: 1, page_size: 20 });
  const tasks = useMemo(() => data?.items ?? [], [data]);

  const counts = useMemo(() => {
    let attention = 0;
    let done = 0;
    for (const t of tasks) {
      const status = String(t.status);
      if (ATTENTION_STATUSES.has(status)) attention += 1;
      else if (DONE_STATUSES.has(status)) done += 1;
    }
    return { attention, done, active: tasks.length - attention - done };
  }, [tasks]);

  return (
    <section aria-labelledby="dashboard-tasks-heading" className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <h2
            id="dashboard-tasks-heading"
            className="text-xs font-medium uppercase tracking-wider text-muted-foreground"
          >
            Development tasks
          </h2>
          {data && tasks.length > 0 && (
            <div className="hidden sm:flex items-center gap-2 text-xs text-muted-foreground tabular-nums">
              <span>{counts.active} active</span>
              <span className="text-border">·</span>
              <span className={cn(counts.attention > 0 && 'text-amber-700 dark:text-amber-400 font-medium')}>
                {counts.attention} need attention
              </span>
              <span className="text-border">·</span>
              <span>{counts.done} finished</span>
            </div>
          )}
        </div>
        <Link
          to="/app/tasks"
          className="inline-flex items-center gap-1 rounded text-xs text-muted-foreground hover:text-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          View all <ArrowRight className="h-3 w-3" />
        </Link>
      </div>

      <div className="rounded-xl border border-border bg-card overflow-hidden">
        {isLoading && <DashboardTasksSkeleton />}

        {isError && !isLoading && (
          <div className="flex items-center gap-3 p-4 text-xs text-muted-foreground">
            <span>Could not load tasks.</span>
            <button
              type="button"
              onClick={() => refetch()}
              className="rounded underline hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
            >
              Retry
            </button>
          </div>
        )}

        {!isLoading && !isError && tasks.length === 0 && (
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4">
            <p className="text-sm text-muted-foreground">
              {hasRepositories
                ? 'No tasks yet. Describe a change and review the generated plan before execution.'
                : 'Connect a repository first to create your first task.'}
            </p>
            {hasRepositories && (
              <button
                type="button"
                onClick={onCreateTask}
                className="inline-flex items-center gap-1.5 self-start shrink-0 rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-medium text-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring transition-colors cursor-pointer"
              >
                <PlusCircle className="h-3.5 w-3.5" />
                Create first task
              </button>
            )}
          </div>
        )}

        {!isLoading && !isError && tasks.length > 0 && (
          <ul className="divide-y divide-border" aria-label="Recent tasks">
            {tasks.slice(0, RECENT_TASKS).map((task) => (
              <li key={task.task_id}>
                <Link
                  to={`/app/tasks/${task.task_id}`}
                  className="flex items-center justify-between gap-4 px-4 py-3 text-sm hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring transition-colors"
                >
                  <span className="truncate font-medium text-foreground">{task.title || task.task_id}</span>
                  <TaskStatusBadge status={task.status} size="sm" />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// EmptyState
// ---------------------------------------------------------------------------

function EmptyState({ onAddRepository }: { onAddRepository: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3.5 rounded-xl border border-dashed border-border bg-card/50 py-14 text-center px-4">
      <div className="rounded-xl bg-muted p-3">
        <GitBranch className="h-6 w-6 text-muted-foreground" />
      </div>
      <div className="space-y-1">
        <p className="text-sm font-semibold text-foreground">No repositories connected</p>
        <p className="text-xs text-muted-foreground">
          Connect a GitHub repository to start indexing and exploring code.
        </p>
      </div>
      <button
        type="button"
        onClick={onAddRepository}
        className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3.5 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
      >
        <PlusCircle className="h-3.5 w-3.5" />
        Add Repository
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pagination
// ---------------------------------------------------------------------------

interface PaginationProps {
  page: number;
  totalPages: number;
  total: number;
  pageSize: number;
  hasPrev: boolean;
  hasNext: boolean;
  onPrev: () => void;
  onNext: () => void;
}

function Pagination({
  page,
  totalPages,
  total,
  pageSize,
  hasPrev,
  hasNext,
  onPrev,
  onNext,
}: PaginationProps) {
  const from = (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);

  return (
    <nav className="flex flex-wrap items-center justify-between gap-2" aria-label="Pagination">
      <p className="text-xs text-muted-foreground tabular-nums">
        Showing {from}–{to} of {total}
      </p>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onPrev}
          disabled={!hasPrev}
          className="inline-flex items-center gap-1 rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
          aria-label="Previous page"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
          Previous
        </button>
        <span className="text-xs text-muted-foreground tabular-nums px-1" aria-current="page">
          {page} / {totalPages}
        </span>
        <button
          type="button"
          onClick={onNext}
          disabled={!hasNext}
          className="inline-flex items-center gap-1 rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
          aria-label="Next page"
        >
          Next
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>
    </nav>
  );
}
