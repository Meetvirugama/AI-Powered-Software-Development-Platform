/**
 * Repository Discovery API service — Day 4.
 *
 * This is the ONLY module that knows:
 *   - the exact discovery HTTP endpoint
 *   - the exact query parameter names sent to the backend
 *   - the raw backend response shape (before adaptation)
 *
 * All other code (hooks, components) must consume the adapted types
 * from types/api.ts (AvailableRepository, PaginatedAvailableRepositoryResponse)
 * and never import this module directly.
 *
 * Dependency flow:
 *   useAvailableRepositories()
 *     → listAvailableRepositories()   ← this file
 *     → GET /api/v1/github/repositories
 *     → PaginatedAvailableRepositoryResponse (adapted)
 *
 * Backend status (Day 4):
 *   The endpoint GET /api/v1/github/repositories does NOT yet exist in the
 *   backend. It is backed by MSW mocks (src/mocks/handlers.ts) during
 *   development. When the backend implements it, only this file needs updating.
 *
 * Expected backend response contract (assumed — to be confirmed with Yug/Parth):
 *   {
 *     "items": [
 *       {
 *         "github_repo_id": "123456001",
 *         "owner": "dev-user",
 *         "name": "platform-backend",
 *         "full_name": "dev-user/platform-backend",
 *         "default_branch": "main",
 *         "language": "Python",
 *         "is_connected": true
 *       },
 *       ...
 *     ],
 *     "total": 42,
 *     "page": 1,
 *     "page_size": 20,
 *     "total_pages": 3
 *   }
 */
import { apiClient } from './api';
import type {
  AvailableRepository,
  ConnectRepositoryResponse,
  PaginatedAvailableRepositoryResponse,
} from '../types/api';

// ---------------------------------------------------------------------------
// Parameters
// ---------------------------------------------------------------------------

export interface ListAvailableRepositoriesParams {
  /** 1-based page number. */
  page: number;
  /** Items per page (default 20). */
  pageSize: number;
  /**
   * Optional search/filter term sent to the backend.
   * The backend performs server-side name filtering — we do NOT download all
   * repos and filter locally.
   * Empty string means no filter.
   */
  search: string;
}

// ---------------------------------------------------------------------------
// Raw backend response shape
//
// This internal type captures the exact JSON the backend (or MSW) returns.
// Isolating it here means the adapter below can be updated independently of
// the AvailableRepository type that the rest of the frontend consumes.
// ---------------------------------------------------------------------------

interface RawAvailableRepo {
  github_repo_id: string;
  owner: string;
  name: string;
  full_name: string;
  default_branch: string;
  language: string | null;
  is_connected: boolean;
}

interface RawDiscoveryResponse {
  items: RawAvailableRepo[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// ---------------------------------------------------------------------------
// Adapter
//
// Maps the raw backend response to the PaginatedAvailableRepositoryResponse
// type consumed by the hook and (later) the UI.
//
// If the backend changes field names, update ONLY this function.
// ---------------------------------------------------------------------------

function adaptResponse(raw: RawDiscoveryResponse): PaginatedAvailableRepositoryResponse {
  const items: AvailableRepository[] = raw.items.map((r) => ({
    github_repo_id: r.github_repo_id,
    owner: r.owner,
    name: r.name,
    full_name: r.full_name,
    default_branch: r.default_branch,
    language: r.language,
    is_connected: r.is_connected,
  }));

  return {
    items,
    total: raw.total,
    page: raw.page,
    page_size: raw.page_size,
    total_pages: raw.total_pages,
  };
}

// ---------------------------------------------------------------------------
// Service function
// ---------------------------------------------------------------------------

/**
 * Fetch a page of GitHub repositories accessible to the installed GitHub App.
 *
 * GET /api/v1/github/repositories
 *
 * Query parameters:
 *   page       — 1-based page number
 *   page_size  — items per page
 *   search     — optional name filter (server-side, not local)
 *
 * This function is the single point of change when the backend endpoint or
 * its parameter names are finalised. The hook (useAvailableRepositories) and
 * the UI never touch HTTP concerns directly.
 */
export async function listAvailableRepositories(
  params: ListAvailableRepositoriesParams,
): Promise<PaginatedAvailableRepositoryResponse> {
  const { page, pageSize, search } = params;

  const queryParams: Record<string, string | number> = {
    page,
    page_size: pageSize,
  };

  // Only include `search` when non-empty to avoid sending `search=` to the backend.
  if (search.trim()) {
    queryParams.search = search.trim();
  }

  const response = await apiClient.get<RawDiscoveryResponse>('/github/repositories', {
    params: queryParams,
  });

  return adaptResponse(response.data);
}

// ---------------------------------------------------------------------------
// Connect repository
//
// Assumed backend endpoint (not yet implemented — backed by MSW):
//   POST /api/v1/github/repositories/:githubRepoId/connect
//
// The backend is expected to:
//   1. Look up the repository in GitHub using the installation token
//   2. Create a repository record in our DB
//   3. Queue a sync job immediately
//   4. Return { repository_id, job_id }
//
// Raw response shape (assumed, to be confirmed with Yug/Parth):
//   { "repository_id": "<uuid>", "job_id": "<uuid>" }
//
// If the backend splits this into two requests (POST /github/repositories/connect
// + POST /repositories/:id/sync), only this function needs updating.
// ---------------------------------------------------------------------------

interface RawConnectResponse {
  repository_id: string;
  job_id: string;
}

/**
 * Connect a GitHub repository to the platform.
 *
 * POST /api/v1/github/repositories/:githubRepoId/connect
 *
 * Triggers:
 *   1. A new repository record is created in our database.
 *   2. A sync job is queued immediately (Cloning → Scanning → Indexing → Ready).
 *
 * Returns:
 *   ConnectRepositoryResponse with our internal repository_id and job_id.
 *   The caller (useConnectRepository hook) uses repository_id to navigate
 *   to the repository detail page and poll sync status.
 *
 * This function is the ONLY place that knows:
 *   - the exact HTTP endpoint
 *   - the exact request method and body
 *   - the raw response field names
 *
 * Navigation on success belongs to the UI layer, not here.
 */
export async function connectRepository(
  githubRepoId: string,
): Promise<ConnectRepositoryResponse> {
  const response = await apiClient.post<RawConnectResponse>(
    `/github/repositories/${githubRepoId}/connect`,
  );

  const raw = response.data;
  return {
    repository_id: raw.repository_id,
    job_id: raw.job_id,
  };
}
