import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useRepositories } from '../hooks/useRepositories';
import { RepositoryCard } from '../components/shared/RepositoryCard';
import { LoadingSpinner } from '../components/shared/LoadingSpinner';
import { ErrorMessage } from '../components/shared/ErrorMessage';
import { PlusCircle, ChevronLeft, ChevronRight, GitBranch } from 'lucide-react';

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

  const { data, isLoading, isFetching, isError, error, refetch } =
    useRepositories(page, PAGE_SIZE);

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  const hasPrev = page > 1;
  const hasNext = page < totalPages;

  return (
    <div className="space-y-8">
      {/* ------------------------------------------------------------------ */}
      {/* Page header                                                          */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Dashboard</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Your connected GitHub repositories.
          </p>
        </div>
        <button
          onClick={() => navigate('/app/repositories')}
          className="inline-flex items-center gap-2 self-start rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:self-auto"
          aria-label="Connect a repository"
        >
          <PlusCircle className="h-4 w-4" />
          Add Repository
        </button>
      </div>


      {/* ------------------------------------------------------------------ */}
      {/* Repository grid — loading                                            */}
      {/* ------------------------------------------------------------------ */}
      {isLoading && (
        <div className="flex items-center justify-center py-16">
          <LoadingSpinner size="lg" label="Loading repositories…" />
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Repository grid — error                                              */}
      {/* ------------------------------------------------------------------ */}
      {isError && !isLoading && (
        <div className="flex flex-col items-center gap-4 py-12">
          <ErrorMessage
            message={error instanceof Error ? error.message : 'Could not load repositories.'}
            className="max-w-md"
          />
          <button
            onClick={() => refetch()}
            className="rounded-lg border border-border bg-background px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Retry
          </button>
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Repository grid — empty                                             */}
      {/* ------------------------------------------------------------------ */}
      {!isLoading && !isError && data && data.items.length === 0 && (
        <EmptyState onAddRepository={() => navigate('/app/repositories')} />
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Repository grid — data                                              */}
      {/* ------------------------------------------------------------------ */}
      {!isLoading && !isError && data && data.items.length > 0 && (
        <>
          {/* Subtle refetch indicator — shown when background refetch runs */}
          {isFetching && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground" aria-live="polite">
              <LoadingSpinner size="sm" label="Refreshing…" />
              <span>Refreshing…</span>
            </div>
          )}

          <div
            className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
            aria-label="Repository list"
          >
            {data.items.map((repo) => (
              <RepositoryCard key={repo.id} repo={repo} />
            ))}
          </div>

          {/* Pagination controls */}
          {totalPages > 1 && (
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
          )}
        </>
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
