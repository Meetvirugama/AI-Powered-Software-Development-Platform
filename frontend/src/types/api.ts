/**
 * API-level TypeScript types.
 *
 * Fields are derived directly from backend Pydantic schemas:
 *   - backend/app/schemas/auth.py       (AuthenticatedUser, TokenResponse)
 *   - backend/app/schemas/health.py     (HealthResponse)
 *   - backend/app/schemas/repository.py (Repository — placeholder)
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
// Repositories — Placeholder until backend implements GET /api/v1/repositories
// ---------------------------------------------------------------------------

export type SyncStatus = 'idle' | 'pending' | 'syncing' | 'synced' | 'error';

/**
 * A connected GitHub repository.
 * Fields are placeholders; update when the OpenAPI spec is available.
 */
export interface Repository {
  /** @placeholder */
  id: string;
  name: string;
  full_name: string;
  sync_status: SyncStatus;
  last_synced_at: string | null;
}
