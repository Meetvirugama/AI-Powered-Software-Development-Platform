import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAvailableRepositories } from '../hooks/useAvailableRepositories';
import { useConnectRepository } from '../hooks/useConnectRepository';
import { LoadingSpinner } from '../components/shared/LoadingSpinner';
import { ErrorMessage } from '../components/shared/ErrorMessage';
import type { AvailableRepository, ApiError } from '../types/api';
import {
  Search,
  GitBranch,
  CheckCircle2,
  PlusCircle,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  X,
  AlertCircle,
} from 'lucide-react';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PAGE_SIZE = 9;
/** Debounce delay in ms before sending a search query to the server. */
const SEARCH_DEBOUNCE_MS = 350;

// ---------------------------------------------------------------------------
// Repository Selector (main page component)
//
// Flow:
//   user types in search input
//   → debounced after 350ms
//   → page resets to 1
//   → useAvailableRepositories({ page, pageSize, search }) re-fetches
//   → server filters + paginates
//   → AvailableRepositoryCard grid renders
//   → user clicks Connect
//   → useConnectRepository().mutate(github_repo_id)
//   → on success: navigate to /app/repositories/:repository_id
// ---------------------------------------------------------------------------

export function Repositories() {
  const navigate = useNavigate();

  // ------------------------------------------------------------------
  // Search state — raw input (immediately updated) + debounced value
  // The debounced value is the one sent to the server.
  // ------------------------------------------------------------------
  const [searchInput, setSearchInput] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ------------------------------------------------------------------
  // Pagination state
  // ------------------------------------------------------------------
  const [page, setPage] = useState(1);

  const handleSearchChange = useCallback((value: string) => {
    setSearchInput(value);
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    debounceTimerRef.current = setTimeout(() => {
      setDebouncedSearch(value);
      setPage(1); // Reset to page 1 when search changes
    }, SEARCH_DEBOUNCE_MS);
  }, []);

  // Clean up debounce timer on unmount.
  useEffect(() => {
    return () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    };
  }, []);

  // ------------------------------------------------------------------
  // Per-card connect error state
  // Key: github_repo_id → error message
  // Cleared when the user retries.
  // ------------------------------------------------------------------
  const [connectErrors, setConnectErrors] = useState<Record<string, string>>({});

  // ------------------------------------------------------------------
  // Discovery query
  // ------------------------------------------------------------------
  const { data, isLoading, isFetching, isError, error, refetch } =
    useAvailableRepositories({ page, pageSize: PAGE_SIZE, search: debouncedSearch });

  // ------------------------------------------------------------------
  // Connect mutation
  // ------------------------------------------------------------------
  const { mutate: connectRepo, isPending: isConnecting, variables: connectingId } =
    useConnectRepository();

  function handleConnect(repo: AvailableRepository) {
    // Clear any previous error for this card
    setConnectErrors((prev) => {
      const next = { ...prev };
      delete next[repo.github_repo_id];
      return next;
    });

    connectRepo(repo.github_repo_id, {
      onSuccess: ({ repository_id }) => {
        // Navigate to detail page — caller decides navigation, not the service
        navigate(`/app/repositories/${repository_id}`);
      },
      onError: (err: ApiError) => {
        // Expose error per-card so user can retry; do not redirect or corrupt list
        setConnectErrors((prev) => ({
          ...prev,
          [repo.github_repo_id]:
            err?.message ?? 'Failed to connect repository. Please try again.',
        }));
      },
    });
  }

  // ------------------------------------------------------------------
  // Derived pagination values
  // ------------------------------------------------------------------
  const totalPages = data ? Math.max(1, data.total_pages) : 1;
  const hasPrev = page > 1;
  const hasNext = page < totalPages;

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------
  return (
    <div className="space-y-6">
      {/* ---------------------------------------------------------------- */}
      {/* Page header                                                        */}
      {/* ---------------------------------------------------------------- */}
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold text-foreground">Connect a Repository</h1>
        <p className="text-sm text-muted-foreground">
          GitHub repositories available through your GitHub App installation.
        </p>
      </div>

      {/* ---------------------------------------------------------------- */}
      {/* Search input                                                       */}
      {/* ---------------------------------------------------------------- */}
      <div className="relative max-w-md">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground pointer-events-none" />
        <input
          id="repository-search"
          type="search"
          placeholder="Search repositories…"
          value={searchInput}
          onChange={(e) => handleSearchChange(e.target.value)}
          className="w-full rounded-lg border border-border bg-background py-2 pl-9 pr-9 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition-colors"
          aria-label="Search repositories"
        />
        {/* Clear button */}
        {searchInput && (
          <button
            onClick={() => handleSearchChange('')}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
            aria-label="Clear search"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* ---------------------------------------------------------------- */}
      {/* Background refetch indicator                                       */}
      {/* Shown when search/page changes while data already exists.         */}
      {/* ---------------------------------------------------------------- */}
      {isFetching && !isLoading && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground" aria-live="polite">
          <LoadingSpinner size="sm" label="Refreshing…" />
          <span>Refreshing…</span>
        </div>
      )}

      {/* ---------------------------------------------------------------- */}
      {/* Initial loading skeleton                                          */}
      {/* ---------------------------------------------------------------- */}
      {isLoading && (
        <div className="flex items-center justify-center py-16">
          <LoadingSpinner size="lg" label="Loading repositories…" />
        </div>
      )}

      {/* ---------------------------------------------------------------- */}
      {/* Discovery API error                                               */}
      {/* ---------------------------------------------------------------- */}
      {isError && !isLoading && (
        <div className="flex flex-col items-center gap-4 py-12">
          <ErrorMessage
            message={
              error instanceof Error
                ? error.message
                : 'Could not load repositories. Check your GitHub App installation.'
            }
            className="max-w-md"
          />
          <button
            onClick={() => refetch()}
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label="Retry loading repositories"
          >
            <RefreshCw className="h-4 w-4" />
            Retry
          </button>
        </div>
      )}

      {/* ---------------------------------------------------------------- */}
      {/* Empty — no repositories via GitHub App at all                     */}
      {/* ---------------------------------------------------------------- */}
      {!isLoading && !isError && data && data.items.length === 0 && !debouncedSearch && (
        <EmptyNoRepositories />
      )}

      {/* ---------------------------------------------------------------- */}
      {/* Empty — search returned no results                                */}
      {/* ---------------------------------------------------------------- */}
      {!isLoading && !isError && data && data.items.length === 0 && debouncedSearch && (
        <EmptySearchResults
          search={debouncedSearch}
          onClear={() => handleSearchChange('')}
        />
      )}

      {/* ---------------------------------------------------------------- */}
      {/* Repository grid                                                   */}
      {/* ---------------------------------------------------------------- */}
      {!isLoading && !isError && data && data.items.length > 0 && (
        <>
          {/* Result count */}
          <p className="text-sm text-muted-foreground" aria-live="polite">
            {debouncedSearch
              ? `${data.total} result${data.total !== 1 ? 's' : ''} for "${debouncedSearch}"`
              : `${data.total} repositor${data.total !== 1 ? 'ies' : 'y'} available`}
          </p>

          <div
            className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
            aria-label="Available repositories"
          >
            {data.items.map((repo) => (
              <AvailableRepositoryCard
                key={repo.github_repo_id}
                repo={repo}
                isConnecting={isConnecting && connectingId === repo.github_repo_id}
                connectError={connectErrors[repo.github_repo_id]}
                onConnect={handleConnect}
                onRetry={() => handleConnect(repo)}
              />
            ))}
          </div>

          {/* Pagination — only rendered when there are multiple pages */}
          {totalPages > 1 && (
            <DiscoveryPagination
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
// AvailableRepositoryCard
//
// Displays a single GitHub-App-accessible repository.
// Matches the visual style of RepositoryCard (connected repos on Dashboard)
// but uses AvailableRepository data and a Connect action instead of View/Ask.
// ---------------------------------------------------------------------------

interface AvailableRepositoryCardProps {
  repo: AvailableRepository;
  /** True when THIS card's Connect is in-flight. */
  isConnecting: boolean;
  /** Per-card connect error message, or undefined if none. */
  connectError?: string;
  onConnect: (repo: AvailableRepository) => void;
  onRetry: () => void;
}

function AvailableRepositoryCard({
  repo,
  isConnecting,
  connectError,
  onConnect,
  onRetry,
}: AvailableRepositoryCardProps) {
  return (
    <article
      className="flex flex-col gap-4 rounded-xl border border-border bg-card p-5 shadow-sm transition-shadow hover:shadow-md"
      aria-label={`Repository ${repo.full_name}`}
    >
      {/* Header: name + language badge */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3
            className="truncate text-sm font-semibold text-foreground"
            title={repo.full_name}
          >
            {repo.name}
          </h3>
          <p className="truncate text-xs text-muted-foreground">{repo.owner}</p>
        </div>
        {repo.language && (
          <span className="shrink-0 rounded-full border border-border bg-muted px-2 py-0.5 text-xs text-muted-foreground">
            {repo.language}
          </span>
        )}
      </div>

      {/* Branch info */}
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <GitBranch className="h-3.5 w-3.5 flex-shrink-0" />
        <span className="truncate">{repo.default_branch}</span>
      </div>

      {/* Per-card connect error */}
      {connectError && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive"
        >
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
          <span>{connectError}</span>
        </div>
      )}

      {/* Action area */}
      <div className="mt-auto">
        {repo.is_connected ? (
          // Already connected — show a clear non-interactive badge
          <div
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700"
            aria-label={`${repo.name} is already connected`}
          >
            <CheckCircle2 className="h-3.5 w-3.5" />
            Connected
          </div>
        ) : connectError ? (
          // Error state — allow retry
          <button
            onClick={onRetry}
            disabled={isConnecting}
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
            aria-label={`Retry connecting ${repo.name}`}
          >
            {isConnecting ? (
              <>
                <LoadingSpinner size="sm" label="Connecting…" />
                Connecting…
              </>
            ) : (
              <>
                <RefreshCw className="h-3.5 w-3.5" />
                Retry
              </>
            )}
          </button>
        ) : (
          // Normal unconnected state — Connect button
          <button
            onClick={() => onConnect(repo)}
            disabled={isConnecting}
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
            aria-label={`Connect ${repo.name}`}
          >
            {isConnecting ? (
              <>
                <LoadingSpinner size="sm" label="Connecting…" />
                Connecting…
              </>
            ) : (
              <>
                <PlusCircle className="h-3.5 w-3.5" />
                Connect
              </>
            )}
          </button>
        )}
      </div>
    </article>
  );
}

// ---------------------------------------------------------------------------
// Empty states
// ---------------------------------------------------------------------------

function EmptyNoRepositories() {
  return (
    <div className="flex flex-col items-center justify-center gap-4 rounded-xl border border-dashed border-border py-16 text-center">
      <div className="rounded-full bg-muted p-4">
        <GitBranch className="h-8 w-8 text-muted-foreground" />
      </div>
      <div>
        <p className="font-medium text-foreground">No repositories found</p>
        <p className="mt-1 text-sm text-muted-foreground">
          No GitHub repositories are accessible through your GitHub App installation.
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          Make sure the GitHub App is installed on the correct organization or user account.
        </p>
      </div>
    </div>
  );
}

function EmptySearchResults({ search, onClear }: { search: string; onClear: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 rounded-xl border border-dashed border-border py-16 text-center">
      <div className="rounded-full bg-muted p-4">
        <Search className="h-8 w-8 text-muted-foreground" />
      </div>
      <div>
        <p className="font-medium text-foreground">No results for &ldquo;{search}&rdquo;</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Try a different search term or clear the filter.
        </p>
      </div>
      <button
        onClick={onClear}
        className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <X className="h-4 w-4" />
        Clear search
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pagination — mirrors the Pagination component in Dashboard.tsx exactly
// so the UX is consistent across both paginated views.
// ---------------------------------------------------------------------------

interface DiscoveryPaginationProps {
  page: number;
  totalPages: number;
  total: number;
  pageSize: number;
  hasPrev: boolean;
  hasNext: boolean;
  onPrev: () => void;
  onNext: () => void;
}

function DiscoveryPagination({
  page,
  totalPages,
  total,
  pageSize,
  hasPrev,
  hasNext,
  onPrev,
  onNext,
}: DiscoveryPaginationProps) {
  const from = (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);

  return (
    <nav
      className="flex items-center justify-between border-t border-border pt-4"
      aria-label="Repository pagination"
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
