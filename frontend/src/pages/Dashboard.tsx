import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useRepositories } from '../hooks/useRepositories';
import { RepositoryCard } from '../components/shared/RepositoryCard';
import { LoadingSpinner } from '../components/shared/LoadingSpinner';
import { ErrorMessage } from '../components/shared/ErrorMessage';
import type { PaginatedRepositoryResponse, Repository } from '../types/api';
import { PlusCircle, ChevronLeft, ChevronRight, GitBranch, RefreshCw } from 'lucide-react';
import { cn } from '../lib/utils';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Repositories shown per page. Change here to adjust the grid layout. */
const PAGE_SIZE = 6;

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

export function Dashboard() {
  const [page, setPage] = useState(1);
  const navigate = useNavigate();

  const { data, isLoading, isFetching, isError, error, refetch } = useRepositories(
    page,
    PAGE_SIZE,
    {
      refetchInterval: (query: { state: { data?: PaginatedRepositoryResponse } }) => {
        const items = query.state.data?.items;
        const hasSyncing = items?.some((r: Repository) => r.sync_status === 'SYNCING');
        return hasSyncing ? 3000 : false;
      },
    },
  );

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  const hasPrev = page > 1;
  const hasNext = page < totalPages;

  return (
    <div className="h-full flex flex-col min-h-0 overflow-hidden">
      {/* ------------------------------------------------------------------ */}
      {/* Pinned Page Header                                                 */}
      {/* ------------------------------------------------------------------ */}
      <div className="shrink-0 pb-3 border-b border-border/60 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-foreground tracking-tight">Dashboard</h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            Your connected GitHub repositories.
          </p>
        </div>
        <div className="flex items-center gap-2 self-start sm:self-auto shrink-0">
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-accent disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            title="Refresh repository list"
            aria-label="Refresh repositories"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', isFetching && 'animate-spin')} />
            <span className="hidden sm:inline">Refresh</span>
          </button>
          <button
            onClick={() => navigate('/app/repositories')}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label="Connect a repository"
          >
            <PlusCircle className="h-3.5 w-3.5" />
            Add Repository
          </button>
        </div>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Scrollable Repository Cards Box                                     */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex-1 min-h-0 overflow-y-auto py-3 pr-1 space-y-4">
        {/* Loading */}
        {isLoading && (
          <div className="flex items-center justify-center py-16">
            <LoadingSpinner size="lg" label="Loading repositories…" />
          </div>
        )}

        {/* Error */}
        {isError && !isLoading && (
          <div className="flex flex-col items-center gap-4 py-12">
            <ErrorMessage
              message={error instanceof Error ? error.message : 'Could not load repositories.'}
              className="max-w-md"
            />
            <div className="flex items-center gap-3">
              <button
                onClick={() => refetch()}
                className="rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-accent"
              >
                Retry
              </button>
              <button
                onClick={() => navigate('/login')}
                className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
              >
                Log in again
              </button>
            </div>
          </div>
        )}

        {/* Empty */}
        {!isLoading && !isError && data && data.items.length === 0 && (
          <EmptyState onAddRepository={() => navigate('/app/repositories')} />
        )}

        {/* Cards Grid */}
        {!isLoading && !isError && data && data.items.length > 0 && (
          <>
            {isFetching && (
              <div className="flex items-center gap-1.5 font-mono text-[11px] text-muted-foreground" aria-live="polite">
                <LoadingSpinner size="sm" label="Refreshing…" />
                <span>Refreshing…</span>
              </div>
            )}

            <div
              className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-3"
              aria-label="Repository list"
            >
              {data.items.map((repo) => (
                <RepositoryCard key={repo.id} repo={repo} />
              ))}
            </div>
          </>
        )}
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Pinned Pagination Footer                                           */}
      {/* ------------------------------------------------------------------ */}
      {!isLoading && !isError && data && data.items.length > 0 && totalPages > 1 && (
        <div className="shrink-0 pt-2.5 border-t border-border/60">
          <Pagination
            page={page}
            totalPages={totalPages}
            total={data.total}
            pageSize={PAGE_SIZE}
            hasPrev={hasPrev}
            hasNext={hasNext}
            onPrev={() => setPage((p) => p - 1)}
            onNext={() => setPage((p) => p + 1)}
          />
        </div>
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// EmptyState
// ---------------------------------------------------------------------------

function EmptyState({ onAddRepository }: { onAddRepository: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 rounded-xl border border-dashed border-border py-16 text-center">
      <div className="rounded-full bg-muted p-4">
        <GitBranch className="h-8 w-8 text-muted-foreground" />
      </div>
      <div>
        <p className="font-medium text-foreground">No repositories connected</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Connect a GitHub repository to get started.
        </p>
      </div>
      <button
        onClick={onAddRepository}
        className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <PlusCircle className="h-4 w-4" />
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
    <nav
      className="flex items-center justify-between border-t border-border pt-4"
      aria-label="Pagination"
    >
      <p className="text-sm text-muted-foreground">
        Showing {from}–{to} of {total}
      </p>
      <div className="flex items-center gap-2">
        <button
          onClick={onPrev}
          disabled={!hasPrev}
          className="inline-flex items-center gap-1 rounded-lg border border-border bg-background px-3 py-1.5 text-sm text-foreground transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="Previous page"
        >
          <ChevronLeft className="h-4 w-4" />
          Previous
        </button>
        <span className="text-sm text-muted-foreground" aria-current="page">
          {page} / {totalPages}
        </span>
        <button
          onClick={onNext}
          disabled={!hasNext}
          className="inline-flex items-center gap-1 rounded-lg border border-border bg-background px-3 py-1.5 text-sm text-foreground transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="Next page"
        >
          Next
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </nav>
  );
}
