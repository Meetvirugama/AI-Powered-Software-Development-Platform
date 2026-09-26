/**
 * API-level TypeScript types.
 *
 * Fields are derived directly from backend Pydantic schemas:
 *   - backend/app/schemas/auth.py       (AuthenticatedUser)
 *   - backend/app/schemas/health.py     (HealthResponse)
 *   - backend/app/schemas/repository.py (RepositoryResponse, PaginatedResponse)
 *
 * Day 4 additions:
 *   - AvailableRepository               (GitHub App–accessible repository)
 *   - PaginatedAvailableRepositoryResponse
 */

// ---------------------------------------------------------------------------
// Standard error envelope
// ---------------------------------------------------------------------------

/**
 * Normalised error returned by every failed API call.
 * Matches the backend's standard error handler contract:
 *   { "error": { "code": "...", "message": "...", "retryable": false } }
 */
export interface ApiError {
  /** Machine-readable error code, e.g. "UNAUTHORIZED", "NOT_FOUND". */
  code: string;
  /** Human-readable error message. */
  message: string;
  /** Whether retrying the same request might succeed. */
  retryable: boolean;
}

// ---------------------------------------------------------------------------
// Health (finalized — schema/health.py)
// ---------------------------------------------------------------------------

export interface HealthResponse {
  status: string;
  version: string;
}

// ---------------------------------------------------------------------------
// Auth — matches backend/app/schemas/auth.py :: AuthenticatedUser
// ---------------------------------------------------------------------------

/**
 * Authenticated user returned by GET /api/v1/auth/me.
 * Mirrors backend AuthenticatedUser exactly.
 */
export interface User {
  id: string;
  login: string;
  name: string | null;
  email: string | null;
  avatar_url: string | null;
}

// ---------------------------------------------------------------------------
// Repositories — matches backend/app/schemas/repository.py :: RepositoryResponse
// ---------------------------------------------------------------------------

/**
 * Sync status values from the backend SyncStatus enum.
 * Maps directly to repository.sync_status.value in the backend response.
 */
export type SyncStatus = 'NOT_SYNCED' | 'SYNCING' | 'SYNCED' | 'FAILED';

/**
 * A connected GitHub repository.
 * Mirrors backend RepositoryResponse exactly.
 */
export interface Repository {
  id: string;
  github_repo_id: string;
  owner: string;
  name: string;
  full_name: string;
  default_branch: string;
  language: string | null;
  sync_status: SyncStatus;
  /** ISO-8601 datetime string or null. */
  last_synced_at: string | null;
}

/**
 * Paginated wrapper for repository lists.
 *
 * The current backend returns list[RepositoryResponse] without pagination
 * metadata. This wrapper isolates the pagination contract so that when the
 * backend adds pagination, only src/services/repositories.ts needs updating.
 */
export interface PaginatedRepositoryResponse {
  items: Repository[];
  total: number;
  page: number;
  page_size: number;
}

// ---------------------------------------------------------------------------
// Repository Discovery — Day 4
//
// These types represent GitHub repositories accessible to the installed
// GitHub App but NOT necessarily connected to the platform yet.
//
// Conceptually SEPARATE from `Repository` (connected repository):
//   - `Repository`          → stored in DB, has sync_status, id is our UUID
//   - `AvailableRepository` → sourced from GitHub API, id is GitHub's integer
//
// Assumed backend endpoint (not yet implemented — backed by MSW):
//   GET /api/v1/github/repositories?page=1&page_size=20&search=<term>
//
// IMPORTANT: The exact backend response contract may still change.
// The service layer (services/repositoryDiscovery.ts) is the ONLY place
// that knows the exact HTTP endpoint and field names. Hook and UI must
// always consume AvailableRepository, never raw API response shapes.
// ---------------------------------------------------------------------------

/**
 * A GitHub repository accessible via the installed GitHub App.
 *
 * Contains only fields needed by the Day 4 Repository Selector:
 * - Enough to identify and display the repository
 * - Whether it is already connected to the platform
 *
 * Derived from GitHubRepository in
 * backend/app/integrations/github/base.py with `is_connected` added
 * by the backend endpoint.
 */
export interface AvailableRepository {
  /** GitHub's numeric repository ID (string for JSON safety). */
  github_repo_id: string;
  /** Repository owner login (user or org). */
  owner: string;
  /** Short repository name, e.g. "platform-backend". */
  name: string;
  /** Full name in owner/repo format, e.g. "dev-user/platform-backend". */
  full_name: string;
  /** Default branch name (e.g. "main"). */
  default_branch: string;
  /** Detected primary language, or null if unknown. */
  language: string | null;
  /**
   * True when this GitHub repository is already connected to the platform
   * (i.e. it exists in our `repositories` table).
   * Used by the selector to show "Connected" vs. "Connect" states.
   */
  is_connected: boolean;
}

/**
 * Paginated response for repository discovery.
 *
 * The backend is assumed to return server-side pagination metadata.
 * If the backend contract changes, only services/repositoryDiscovery.ts
 * needs to update the adapter — the hook and UI always consume this shape.
 */
export interface PaginatedAvailableRepositoryResponse {
  items: AvailableRepository[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}
