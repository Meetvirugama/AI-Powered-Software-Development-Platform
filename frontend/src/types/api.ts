/**
 * API-level TypeScript types.
 *
 * Fields are derived directly from backend Pydantic schemas:
 *   - backend/app/schemas/auth.py       (AuthenticatedUser)
 *   - backend/app/schemas/health.py     (HealthResponse)
 *   - backend/app/schemas/repository.py (RepositoryResponse, PaginatedResponse)
 *
 * Day 4 additions:
 *   - AvailableRepository                   (GitHub App–accessible repository)
 *   - PaginatedAvailableRepositoryResponse
 *   - ConnectRepositoryResponse             (Connect mutation result)
 *   - SyncProgressStep                      (UI-facing sync stage adapter)
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

  // -------------------------------------------------------------------------
  // Day 5 Mock Additions
  // The following fields are required by the Day 5 Repository Explorer UI
  // but are not yet exposed by the backend `RepositoryResponse`.
  // They are mocked on the frontend until the backend contract is updated.
  // -------------------------------------------------------------------------
  description?: string | null;
  framework?: string | null;
  file_count?: number;
  symbol_count?: number;
  chunk_count?: number;
}

// ---------------------------------------------------------------------------
// Files — matches backend/app/schemas/repository.py :: RepositoryFileResponse
// ---------------------------------------------------------------------------

/**
 * An indexed file within a repository.
 * Mirrors backend RepositoryFileResponse exactly.
 */
export interface RepositoryFile {
  id: string;
  path: string;
  language: string | null;
  size_bytes: number;
  line_count: number;
  content_hash: string;
  /** ISO-8601 datetime string or null. */
  last_indexed_at: string | null;
}

/**
 * Paginated wrapper for repository files.
 * Matches backend PaginatedResponse[RepositoryFileResponse].
 */
export interface PaginatedRepositoryFileResponse {
  items: RepositoryFile[];
  total: number;
  page: number;
  page_size: number;
}

// ---------------------------------------------------------------------------
// Dependencies — Day 5 Mock
// ---------------------------------------------------------------------------

/**
 * A top-level dependency for a repository.
 *
 * MOCKED: The backend does not yet expose dependencies via any endpoint.
 * This is a temporary frontend contract to support the Day 5 Explorer UI.
 */
export interface RepositoryDependency {
  name: string;
  version: string;
  ecosystem: string; // e.g. "npm", "pip", "cargo", "gomod"
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

// ---------------------------------------------------------------------------
// Connect Repository — Day 4 (Prompt 2)
//
// Assumed backend endpoint (not yet implemented — backed by MSW):
//   POST /api/v1/github/repositories/:githubRepoId/connect
//
// Expected request body: none required (github_repo_id is in the URL path)
//
// Expected response contract (to be confirmed with Yug/Parth):
//   {
//     "repository_id": "<our internal UUID>",
//     "job_id":        "<sync job UUID>"
//   }
//
// The backend must:
//   1. Create a repository record in our DB using GitHubService metadata
//   2. Immediately queue a sync job (equivalent to POST /repositories/:id/sync)
//   3. Return our internal repository_id + the sync job_id
//
// NOTE: The existing POST /api/v1/repositories/:id/sync endpoint takes our
// internal UUID, not a GitHub repo ID. A dedicated Connect endpoint that
// combines insert + sync is cleaner than calling two endpoints from the UI.
//
// IMPORTANT: Only services/repositoryDiscovery.ts knows the exact endpoint.
// ---------------------------------------------------------------------------

/**
 * Response from a successful Connect mutation.
 *
 * repository_id  — our internal UUID, used to query sync status via
 *                  GET /api/v1/repositories/:id
 * job_id         — the queued sync job ID (for future job-status polling if needed)
 *
 * NOTE: job_id mirrors the SyncJobResponse schema from
 * backend/app/schemas/repository.py :: SyncJobResponse { job_id, status }
 */
export interface ConnectRepositoryResponse {
  /** Our internal UUID for the newly created repository record. */
  repository_id: string;
  /** The background sync job ID, returned after the job is queued. */
  job_id: string;
}

// ---------------------------------------------------------------------------
// Sync Progress — Day 4 (Prompt 2)
//
// week1.md requires the UI to show: Cloning → Scanning → Indexing → Ready
//
// The current backend SyncStatus enum has only four values:
//   NOT_SYNCED | SYNCING | SYNCED | FAILED
//
// The intermediate Cloning/Scanning/Indexing stages are NOT yet confirmed
// in the backend contract. The backend may expose them in the future as:
//   - a separate `sync_stage` field on the repository record
//   - additional SyncStatus enum values
//   - a job-status endpoint
//
// This adapter is the ONLY place in the frontend that maps backend state
// to UI stages. When the backend contract is confirmed, only this adapter
// needs updating — no hook or UI changes are required.
// ---------------------------------------------------------------------------

/**
 * The four sync stages shown to the user in the Day 4 UI.
 * Maps to the Cloning → Scanning → Indexing → Ready sequence from week1.md.
 */
export type SyncStage = 'CLONING' | 'SCANNING' | 'INDEXING' | 'READY' | 'FAILED' | 'NOT_STARTED';

/**
 * UI-facing representation of a repository's current sync progress.
 *
 * Produced by `syncProgressFromStatus()` in hooks/useRepositories.ts.
 * The UI reads this — never SyncStatus directly — for progress display.
 */
export interface SyncProgress {
  /**
   * The current stage.
   *
   * ASSUMPTION (unconfirmed): Until the backend exposes intermediate
   * stage information, the entire SYNCING state maps to CLONING.
   * This will be updated when Yug/Parth confirm the backend contract.
   */
  stage: SyncStage;
  /** Human-readable label for display in the step indicator. */
  label: string;
  /** True while a sync job is actively running (stage is not terminal). */
  isActive: boolean;
  /** True when sync completed successfully. */
  isComplete: boolean;
  /** True when sync failed. */
  isFailed: boolean;
}

// ---------------------------------------------------------------------------
// Chat — Day 6
//
// Frontend contract for the repository chat feature.
//
// Assumed backend endpoint (not yet confirmed — mocked via MSW):
//   POST /api/v1/repositories/:id/chat
//   Body:    { "question": string }
//   Returns: ChatResponse
//
// IMPORTANT: The backend contract is not yet confirmed with Yug/Parth.
// Only src/services/chat.ts knows the exact endpoint. Hooks and UI
// always consume ChatMessage / ChatResponse — never raw HTTP shapes.
//
// Streaming note:
//   The current contract uses a simple request-response shape to keep the
//   data layer replaceable. The types and service are structured so that
//   when the backend confirms a streaming/SSE contract, only
//   src/services/chat.ts needs to change — the hook and UI remain stable.
//
//   If SSE streaming is added later, each streamed chunk will extend the
//   assistant ChatMessage in place (by appending to `content`).
//   The `isStreaming` field on ChatMessage is reserved for that.
// ---------------------------------------------------------------------------

/**
 * A single source reference cited by the assistant.
 *
 * Represents evidence from an indexed repository file.
 * All fields except `file_path` are optional because the backend may
 * not always be able to determine precise line numbers or symbols.
 *
 * MOCKED: Field names are assumed. Align with backend schema when confirmed.
 */
export interface ChatSource {
  /** Repository-relative file path, e.g. "src/api/auth.py". */
  file_path: string;
  /** First line of the relevant excerpt (1-indexed). null if not available. */
  line_start: number | null;
  /** Last line of the relevant excerpt (1-indexed). null if not available. */
  line_end: number | null;
  /** Optional symbol name referenced (e.g. function, class). */
  symbol?: string | null;
  /** Optional brief excerpt snippet for preview. */
  snippet?: string | null;
}

/**
 * Role of the message author in the chat conversation.
 * Mirrors the convention used by most LLM APIs.
 */
export type ChatRole = 'user' | 'assistant';

/**
 * A single message in the chat conversation.
 *
 * Kept in local React component state only — not persisted to the server.
 * The `id` is a client-generated identifier used as a React key.
 */
export interface ChatMessage {
  /** Client-generated unique identifier (e.g. crypto.randomUUID()). */
  id: string;
  /** Who produced this message. */
  role: ChatRole;
  /** The text content of the message. */
  content: string;
  /** ISO-8601 timestamp of when the message was created on the client. */
  timestamp: string;
  /**
   * Source references cited for this message.
   * Only populated for assistant messages.
   */
  sources?: ChatSource[];
  /**
   * Reserved for streaming support.
   * When true, this message is still being streamed and `content` is partial.
   * Currently always false — set to true when SSE streaming is implemented.
   */
  isStreaming?: boolean;
}

/**
 * Request body sent to the chat endpoint.
 *
 * POST /api/v1/repositories/:id/chat
 * MOCKED: The exact field name ("question" vs "query" vs "message") is
 * assumed and must be confirmed with the backend team.
 */
export interface ChatRequest {
  /** The user's question about the repository. */
  question: string;
}

/**
 * Response from the chat endpoint.
 *
 * Contains the assistant's answer and an optional list of source references.
 * MOCKED: Field names are assumed. Align with backend schema when confirmed.
 */
export interface ChatResponse {
  /** The assistant's answer text. */
  answer: string;
  /** Source file references that support the answer. May be empty. */
  sources: ChatSource[];
}
