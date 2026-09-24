/**
 * API-level TypeScript types.
 *
 * Fields are derived directly from backend Pydantic schemas:
 *   - backend/app/schemas/auth.py       (AuthenticatedUser)
 *   - backend/app/schemas/health.py     (HealthResponse)
 *   - backend/app/schemas/repository.py (RepositoryResponse, PaginatedResponse)
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
