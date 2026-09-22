/**
 * API-level TypeScript types.
 *
 * Fields are derived from:
 *   - backend/app/schemas/health.py  (only finalized schema on Day 1)
 *   - Docs/daily_tasks.md            (contract placeholders for upcoming endpoints)
 *
 * Placeholder types are clearly marked. Do NOT add fields not supported by
 * the backend contract. Fields will be filled in as Yug finalises the OpenAPI
 * spec on Day 2.
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
// Auth  — Placeholder until Yug finalises auth endpoints on Day 2
// ---------------------------------------------------------------------------

/**
 * The authenticated user object returned by GET /api/v1/auth/me.
 * Fields are placeholders; update when the OpenAPI spec is available.
 */
export interface User {
  /** @placeholder — actual field names TBD by backend contract */
  id: string;
  login: string;
  name: string | null;
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
