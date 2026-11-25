import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  useAvailableRepositories,
  useRefreshAvailableRepositories,
} from '../hooks/useAvailableRepositories';
import { useConnectRepository } from '../hooks/useConnectRepository';
import { useRepositories } from '../hooks/useRepositories';
import { LoadingSpinner } from '../components/shared/LoadingSpinner';
import { RepositoryGridSkeleton } from '../components/shared/Skeletons';
import { ErrorMessage } from '../components/shared/ErrorMessage';
import { GitHubInstallButton } from '../components/shared/GitHubInstallButton';
import { RepositoryCard } from '../components/shared/RepositoryCard';
import { linkGitHubInstallation } from '../services/repositoryDiscovery';
import type { AvailableRepository, ApiError, Repository } from '../types/api';
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
  FolderOpen,
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
  const [searchParams] = useSearchParams();
  const urlInstallationId = searchParams.get('installation_id') || undefined;

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
  // Discovery query + connected repositories index (for R1 opening)
  // ------------------------------------------------------------------
  const { data, isLoading, isFetching, isError, error, refetch } =
    useAvailableRepositories({
      page,
      pageSize: PAGE_SIZE,
      search: debouncedSearch,
      installationId: urlInstallationId,
    });
  const { mutate: refreshFromGitHub, isPending: isManualRefreshing } =
    useRefreshAvailableRepositories({
      page,
      pageSize: PAGE_SIZE,
      search: debouncedSearch,
      installationId: urlInstallationId,
    });

  const { data: connectedData, isLoading: isLoadingConnected } = useRepositories(1, 100);

  const connectedRepoIndex = useMemo(() => {
    const byGithubId = new Map<string, Repository>();
    const byFullName = new Map<string, Repository>();
    for (const item of connectedData?.items ?? []) {
      if (item.github_repo_id) {
        byGithubId.set(String(item.github_repo_id), item);
      }
      if (item.full_name) {
        byFullName.set(item.full_name.toLowerCase(), item);
      }
    }
    return { byGithubId, byFullName };
  }, [connectedData]);

  const resolveConnectedRepo = useCallback(
    (repo: AvailableRepository): Repository | undefined => {
      return (
        connectedRepoIndex.byGithubId.get(String(repo.github_repo_id)) ??
        connectedRepoIndex.byFullName.get(repo.full_name.toLowerCase())
      );
    },
    [connectedRepoIndex]
  );

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
  const connectedRepos = connectedData?.items ?? [];

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------
  return (
    <div className="h-full flex flex-col min-h-0 overflow-hidden">
      {/* Pinned Page Header & Controls */}
      <div className="shrink-0 space-y-4 pb-5 border-b border-border">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div className="flex flex-col gap-0.5">
            <h1 className="text-xl font-semibold text-foreground tracking-tight">Connect a Repository</h1>
            <p className="text-sm text-muted-foreground">
              Repositories accessible through your GitHub App installation.
            </p>
          </div>
          <div className="flex items-center gap-2 self-start sm:self-auto shrink-0">
            <button
              type="button"
              onClick={() => refreshFromGitHub()}
              disabled={isManualRefreshing || isFetching}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium text-foreground hover:bg-accent transition-colors disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
              title="Bypass GitHub discovery cache and fetch latest repositories"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${isManualRefreshing ? 'animate-spin' : ''}`} />
              <span>{isManualRefreshing ? 'Refreshing…' : 'Refresh from GitHub'}</span>
            </button>
            <GitHubInstallButton
              label="Install / Manage GitHub App"
              size="sm"
              className="shrink-0"
            />
          </div>
        </div>

        {/* Search input & repo count row */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="relative w-full max-w-md">
            <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground pointer-events-none" />
            <input
              id="repository-search"
              type="search"
              placeholder="Search repositories…"
              value={searchInput}
              onChange={(e) => handleSearchChange(e.target.value)}
              className="w-full rounded-lg border border-border bg-card py-2 pl-9 pr-8 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition-colors"
              aria-label="Search repositories"
            />
            {searchInput && (
              <button
                type="button"
                onClick={() => handleSearchChange('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded text-muted-foreground hover:text-foreground hover:bg-accent transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                aria-label="Clear search"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>

          <div className="flex items-center gap-2 text-xs text-muted-foreground shrink-0">
            {isFetching && !isLoading && (
              <div className="flex items-center gap-1.5 font-mono text-[11px]" aria-live="polite">
                <LoadingSpinner size="sm" label="Refreshing…" />
                <span>Refreshing…</span>
              </div>
            )}
            {data && (
              <span className="font-medium text-foreground tabular-nums">
                {debouncedSearch
                  ? `${data.total} result${data.total !== 1 ? 's' : ''}`
                  : `${data.total} repositories available`}
              </span>
            )}
          </div>
        </div>

        {/* Connected quick-open bar for instant 1-click navigation */}
        {connectedRepos.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 pt-1" aria-label="Connected quick open">
            <span className="text-[11px] font-medium text-muted-foreground mr-1">
              Connected:
            </span>
            {connectedRepos.slice(0, 8).map((connected) => (
              <Link
                key={connected.id}
                to={`/app/repositories/${connected.id}`}
                className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-1 text-[11px] font-medium text-foreground hover:bg-accent hover:text-accent-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
              >
                <FolderOpen className="h-3 w-3 text-muted-foreground" />
                <span className="truncate max-w-[180px]">{connected.full_name}</span>
              </Link>
            ))}
            {(connectedData?.total ?? 0) > 8 && (
              <Link
                to="/app/dashboard"
                className="text-[11px] font-medium text-muted-foreground hover:text-foreground underline-offset-2 hover:underline px-1.5 py-1 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
              >
                View all on Dashboard
              </Link>
            )}
          </div>
        )}
      </div>

      {/* ---------------------------------------------------------------- */}
      {/* Scrollable Repository Cards Box                                   */}
      {/* ---------------------------------------------------------------- */}
      <div className="flex-1 min-h-0 overflow-y-auto py-3 pr-1 space-y-4">
        {/* Loading skeleton */}
        {isLoading && <RepositoryGridSkeleton count={PAGE_SIZE} label="Loading repositories…" />}

        {/* Error state */}
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
              type="button"
              onClick={() => refetch()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
              aria-label="Retry loading repositories"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Retry
            </button>
          </div>
        )}

        {/* Empty — no repositories */}
        {!isLoading && !isError && data && data.items.length === 0 && !debouncedSearch && (
          <EmptyNoRepositories onRefresh={() => refetch()} />
        )}

        {/* Fallback connected repositories grid when discovery is empty or failed */}
        {!isLoading &&
          (isError || (data && data.items.length === 0 && !debouncedSearch)) &&
          connectedRepos.length > 0 && (
            <section aria-label="Connected repositories" className="space-y-3 pt-2">
              <h2 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Connected Repositories
              </h2>
              <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-3">
                {connectedRepos.map((connected) => (
                  <RepositoryCard key={connected.id} repo={connected} />
                ))}
              </div>
            </section>
          )}

        {/* Empty — search returned no results */}
        {!isLoading && !isError && data && data.items.length === 0 && debouncedSearch && (
          <EmptySearchResults
            search={debouncedSearch}
            onClear={() => handleSearchChange('')}
          />
        )}

        {/* 3-column repository cards grid */}
        {!isLoading && !isError && data && data.items.length > 0 && (
          <div
            className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-3"
            aria-label="Available repositories"
          >
            {data.items.map((repo) => (
              <AvailableRepositoryCard
                key={repo.github_repo_id}
                repo={repo}
                connectedRepo={resolveConnectedRepo(repo)}
                isResolvingConnected={isLoadingConnected}
                isConnecting={isConnecting && connectingId === repo.github_repo_id}
                connectError={connectErrors[repo.github_repo_id]}
                onConnect={handleConnect}
                onRetry={() => handleConnect(repo)}
              />
            ))}
          </div>
        )}
      </div>

      {/* ---------------------------------------------------------------- */}
      {/* Pinned Pagination Footer                                          */}
      {/* ---------------------------------------------------------------- */}
      {!isLoading && !isError && data && data.items.length > 0 && totalPages > 1 && (
        <div className="shrink-0 pt-3 border-t border-border">
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
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// AvailableRepositoryCard
//
// Displays a single GitHub-App-accessible repository.
// Matches the visual style of RepositoryCard (connected repos on Dashboard)
// and supports direct opening via name click or explicit Open link when connected.
// ---------------------------------------------------------------------------

interface AvailableRepositoryCardProps {
  repo: AvailableRepository;
  /** Resolved connected platform repository (provides UUID for /app/repositories/:id). */
  connectedRepo?: Repository;
  /** True while connected repositories list is still loading. */
  isResolvingConnected?: boolean;
  /** True when THIS card's Connect is in-flight. */
  isConnecting: boolean;
  /** Per-card connect error message, or undefined if none. */
  connectError?: string;
  onConnect: (repo: AvailableRepository) => void;
  onRetry: () => void;
}

function AvailableRepositoryCard({
  repo,
  connectedRepo,
  isResolvingConnected,
  isConnecting,
  connectError,
  onConnect,
  onRetry,
}: AvailableRepositoryCardProps) {
  const repoDetailPath =
    repo.is_connected && connectedRepo?.id ? `/app/repositories/${connectedRepo.id}` : null;

  return (
    <article
      className="flex flex-col gap-3.5 rounded-xl border border-border bg-card p-4 transition-colors hover:border-foreground/20"
      aria-label={`Repository ${repo.full_name}`}
    >
      {/* Header: name + language badge */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          {repoDetailPath ? (
            <Link
              to={repoDetailPath}
              className="block max-w-full text-left font-semibold text-foreground hover:underline transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded cursor-pointer"
              title={`Open ${repo.full_name}`}
            >
              <h3 className="truncate text-sm">{repo.name}</h3>
            </Link>
          ) : (
            <h3
              className="truncate text-sm font-semibold text-foreground"
              title={repo.full_name}
            >
              {repo.name}
            </h3>
          )}
          <p className="truncate text-xs text-muted-foreground mt-0.5">{repo.owner}</p>
        </div>
        {repo.language && (
          <span className="shrink-0 rounded-md bg-muted px-2 py-0.5 text-[11px] text-muted-foreground font-mono">
            {repo.language}
          </span>
        )}
      </div>

      {/* Branch info + Connected status badge */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground min-w-0">
          <GitBranch className="h-3.5 w-3.5 flex-shrink-0" />
          <span className="truncate">{repo.default_branch}</span>
        </div>
        {repo.is_connected && (
          <span
            className="inline-flex items-center gap-1 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:text-emerald-400"
            aria-label={`${repo.name} is connected`}
          >
            <CheckCircle2 className="h-3 w-3" />
            Connected
          </span>
        )}
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
          repoDetailPath ? (
            <Link
              to={repoDetailPath}
              className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-border bg-background px-3 py-2 text-xs font-medium text-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
              aria-label={`Open ${repo.name}`}
            >
              <FolderOpen className="h-3.5 w-3.5" />
              Open
            </Link>
          ) : (
            <button
              type="button"
              disabled
              className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-emerald-500/25 bg-emerald-500/10 px-3 py-2 text-xs font-medium text-emerald-700 dark:text-emerald-400 cursor-not-allowed opacity-80"
              aria-label={`${repo.name} is already connected`}
            >
              <CheckCircle2 className="h-3.5 w-3.5" />
              {isResolvingConnected ? 'Loading…' : 'Connected'}
            </button>
          )
        ) : connectError ? (
          // Error state — allow retry
          <button
            type="button"
            onClick={onRetry}
            disabled={isConnecting}
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60 cursor-pointer"
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
            type="button"
            onClick={() => onConnect(repo)}
            disabled={isConnecting}
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60 cursor-pointer"
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

function EmptyNoRepositories({ onRefresh }: { onRefresh?: () => void }) {
  const [manualId, setManualId] = useState('');
  const [isLinking, setIsLinking] = useState(false);
  const [linkError, setLinkError] = useState<string | null>(null);

  const handleManualLink = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!manualId.trim()) return;
    setIsLinking(true);
    setLinkError(null);
    try {
      await linkGitHubInstallation(manualId);
      setManualId('');
      onRefresh?.();
    } catch (err: unknown) {
      const msg = err && typeof err === 'object' && 'message' in err ? String((err as { message: unknown }).message) : 'Failed to link installation ID.';
      setLinkError(msg);
    } finally {
      setIsLinking(false);
    }
  };

  return (
    <div className="flex flex-col items-center justify-center gap-4 rounded-xl border border-dashed border-border py-16 px-4 text-center">
      <div className="rounded-full bg-muted p-4">
        <GitBranch className="h-8 w-8 text-muted-foreground" />
      </div>
      <div className="max-w-md">
        <p className="font-semibold text-lg text-foreground">No repositories found</p>
        <p className="mt-1 text-sm text-muted-foreground">
          No repositories are available because the <strong>Code Intelligence</strong> GitHub App is not yet installed on your GitHub account or organizations.
        </p>
      </div>
      <div className="flex flex-wrap items-center justify-center gap-3">
        <GitHubInstallButton
          label="Install GitHub App & Select Repositories"
          size="md"
        />
        {onRefresh && (
          <button
            onClick={onRefresh}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-4 py-2.5 text-sm font-semibold text-foreground transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
            type="button"
          >
            <RefreshCw className="h-4 w-4" />
            Check Installation
          </button>
        )}
      </div>

      <form onSubmit={handleManualLink} className="mt-4 flex flex-col items-center gap-2">
        <p className="text-xs text-muted-foreground">
          Already installed? Link your GitHub Installation ID:
        </p>
        <div className="flex flex-wrap items-center justify-center gap-2">
          <input
            type="text"
            aria-label="GitHub Installation ID"
            placeholder="e.g. 171308854"
            value={manualId}
            onChange={(e) => setManualId(e.target.value)}
            className="rounded-lg border border-border bg-background px-3 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring w-44"
          />
          <button
            type="submit"
            disabled={isLinking || !manualId.trim()}
            className="rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
          >
            {isLinking ? 'Linking...' : 'Link'}
          </button>
        </div>
        {linkError && <p role="alert" className="text-xs text-destructive">{linkError}</p>}
      </form>
    </div>
  );
}

function EmptySearchResults({ search, onClear }: { search: string; onClear: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 rounded-xl border border-dashed border-border py-16 px-4 text-center">
      <div className="rounded-full bg-muted p-4">
        <Search className="h-8 w-8 text-muted-foreground" />
      </div>
      <div>
        <p className="font-semibold text-lg text-foreground">No results for &ldquo;{search}&rdquo;</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Try a different search term or clear the filter.
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          If your repository isn't listed, ensure it was selected during the GitHub App installation.
        </p>
      </div>
      <div className="flex flex-wrap items-center justify-center gap-3">
        <button
          type="button"
          onClick={onClear}
          className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
        >
          <X className="h-4 w-4" />
          Clear search
        </button>
        <GitHubInstallButton
          label="Add More Repositories"
          variant="secondary"
          size="md"
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pagination — mirrors the Pagination component in Dashboard.tsx
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
      className="flex flex-wrap items-center justify-between gap-2"
      aria-label="Repository pagination"
    >
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
