/**
 * Repository API service.
 *
 * All repository API calls go through this module.
 * Components and hooks must not use apiClient directly for repository data.
 *
 * Pagination note:
 *   The current backend endpoint GET /api/v1/repositories returns a plain
 *   list[RepositoryResponse] with no pagination metadata. We wrap the response
 *   here into PaginatedRepositoryResponse so that:
 *   a) The hook and UI already work with a paginated shape.
 *   b) When the backend adds server-side pagination, only this file changes.
 */
import { apiClient } from './api';
import type {
  PaginatedRepositoryResponse,
  Repository,
  RepositoryFile,
  PaginatedRepositoryFileResponse,
  RepositoryDependency,
  RepositoryFileContent,
  RemoteIssueInfo,
  SyncJob,
  RepositoryMetrics,
  RepositoryBranch,
  RepositoryCommit,
  RepositoryPullRequest,
} from '../types/api';

export interface ListRepositoriesParams {
  page: number;
  pageSize: number;
}

/**
 * Fetch a page of repositories for the authenticated user.
 *
 * GET /api/v1/repositories?page=&page_size=
 *
 * The backend returns one page as a plain list and the overall count in the
 * `X-Total-Count` header. Previously `total` was taken from the page length, so
 * with more than one page of repositories the dashboard always showed "1 / 1"
 * and the remaining repositories were unreachable.
 */
export async function listRepositories(
  params: ListRepositoriesParams,
): Promise<PaginatedRepositoryResponse> {
  const { page, pageSize } = params;
  const response = await apiClient.get<Repository[]>('/repositories', {
    params: { page, page_size: pageSize },
  });
  const pageItems = Array.isArray(response.data) ? response.data : [];

  const headerTotal = Number.parseInt(String(response.headers?.['x-total-count'] ?? ''), 10);
  if (Number.isFinite(headerTotal) && headerTotal >= 0) {
    return { items: pageItems, total: headerTotal, page, page_size: pageSize };
  }

  // Fallback for older backends that ignore pagination and return everything.
  const items =
    pageItems.length > pageSize ? pageItems.slice((page - 1) * pageSize, page * pageSize) : pageItems;
  const total = pageItems.length > pageSize ? pageItems.length : (page - 1) * pageSize + pageItems.length;
  return { items, total, page, page_size: pageSize };
}

/**
 * Fetch a single repository by ID.
 *
 * GET /api/v1/repositories/:id
 */
export async function getRepository(id: string): Promise<Repository> {
  const response = await apiClient.get<Repository>(`/repositories/${id}`);
  return response.data;
}

export interface GetRepositoryFilesParams {
  page: number;
  pageSize: number;
  path?: string;
}

/**
 * Fetch indexed files for a repository.
 *
 * GET /api/v1/repositories/:id/files
 */
export async function getRepositoryFiles(
  id: string,
  params: GetRepositoryFilesParams,
): Promise<PaginatedRepositoryFileResponse> {
  const response = await apiClient.get<PaginatedRepositoryFileResponse>(
    `/repositories/${id}/files`,
    {
      params: {
        page: params.page,
        page_size: params.pageSize,
        ...(params.path ? { path: params.path } : {}),
      },
    },
  );
  return response.data;
}

/**
 * Look up an indexed repository file by exact path.
 *
 * GET /api/v1/repositories/:id/files/by-path?path=...
 */
export async function lookupRepositoryFileByPath(
  id: string,
  path: string,
): Promise<RepositoryFile | null> {
  try {
    const response = await apiClient.get<RepositoryFile>(
      `/repositories/${id}/files/by-path`,
      { params: { path } },
    );
    return response.data;
  } catch (err: unknown) {
    const errorObj = err as { status?: number; response?: { status?: number } } | null;
    if (errorObj?.status === 404 || errorObj?.response?.status === 404) {
      return null;
    }
    throw err;
  }
}

/**
 * Fetch top-level dependencies for a repository.
 *
 * GET /api/v1/repositories/:id/dependencies
 * Live backend parses package.json, requirements.txt, go.mod, Cargo.toml from indexed files.
 */
export async function getRepositoryDependencies(
  id: string,
): Promise<RepositoryDependency[]> {
  const response = await apiClient.get<RepositoryDependency[]>(
    `/repositories/${id}/dependencies`,
  );
  return response.data;
}

/**
 * Trigger background synchronization for a repository.
 *
 * POST /api/v1/repositories/:id/sync
 */
export async function syncRepository(
  id: string,
  force: boolean = false,
): Promise<{ job_id: string }> {
  const url = force ? `/repositories/${id}/sync?force=true` : `/repositories/${id}/sync`;
  const response = await apiClient.post<{ job_id: string }>(url);
  return response.data;
}

/**
 * Disconnect and remove a repository and its indexed data.
 *
 * DELETE /api/v1/repositories/:id
 */
export async function deleteRepository(id: string): Promise<void> {
  await apiClient.delete(`/repositories/${id}`);
}

/**
 * Fetch indexed content and symbols for a specific file.
 *
 * GET /api/v1/repositories/:repositoryId/files/:fileId/content
 */
export async function getRepositoryFileContent(
  repositoryId: string,
  fileId: string,
): Promise<RepositoryFileContent> {
  const response = await apiClient.get<RepositoryFileContent>(
    `/repositories/${repositoryId}/files/${fileId}/content`,
  );
  return response.data;
}

/**
 * List remote issues for an authorized repository from GitHub (F16 - Issue #196).
 *
 * GET /api/v1/repositories/:repositoryId/source/issues
 */
export async function listRemoteSourceIssues(
  repositoryId: string,
  params?: {
    state?: 'open' | 'closed' | 'all';
    per_page?: number;
    page?: number;
  },
): Promise<RemoteIssueInfo[]> {
  const response = await apiClient.get<RemoteIssueInfo[]>(
    `/repositories/${repositoryId}/source/issues`,
    { params },
  );
  return response.data;
}

/**
 * Get detail for a specific remote GitHub issue (F16 - Issue #196).
 *
 * GET /api/v1/repositories/:repositoryId/source/issues/:issueNumber
 */
export async function getRemoteSourceIssue(
  repositoryId: string,
  issueNumber: number,
): Promise<RemoteIssueInfo> {
  const response = await apiClient.get<RemoteIssueInfo>(
    `/repositories/${repositoryId}/source/issues/${issueNumber}`,
  );
  return response.data;
}

/**
 * Hybrid code search within indexed repository files (FEAT-16).
 *
 * POST /api/v1/repositories/:repositoryId/search
 */
export async function searchRepository(
  repositoryId: string,
  query: string,
  topK = 10,
): Promise<{ query: string; total: number; results: Array<{ file_path: string; start_line: number; end_line: number; content: string; score: number }> }> {
  const response = await apiClient.post(
    `/repositories/${repositoryId}/search`,
    { query, top_k: topK },
  );
  return response.data;
}

/**
 * List code symbols indexed for a repository (FEAT-16).
 *
 * GET /api/v1/repositories/:repositoryId/symbols
 */
export async function listRepositorySymbols(
  repositoryId: string,
  params?: { query?: string; kind?: string },
): Promise<Array<{ id: string; name: string; kind: string; file_path: string; start_line: number; end_line: number }>> {
  const response = await apiClient.get(
    `/repositories/${repositoryId}/symbols`,
    { params },
  );
  return response.data;
}





// ---------------------------------------------------------------------------
// Sync status, metrics and live GitHub data
// ---------------------------------------------------------------------------

/** GET /api/v1/repositories/:id/sync-jobs — newest first, with stage, timing and failure reason. */
export async function getRepositorySyncJobs(id: string, limit = 10): Promise<SyncJob[]> {
  const response = await apiClient.get<SyncJob[]>(`/repositories/${id}/sync-jobs`, { params: { limit } });
  return response.data;
}

/** GET /api/v1/repositories/:id/sync-jobs/:jobId */
export async function getRepositorySyncJob(id: string, jobId: string): Promise<SyncJob> {
  const response = await apiClient.get<SyncJob>(`/repositories/${id}/sync-jobs/${jobId}`);
  return response.data;
}

/** GET /api/v1/repositories/:id/metrics */
export async function getRepositoryMetrics(id: string, top = 10): Promise<RepositoryMetrics> {
  const response = await apiClient.get<RepositoryMetrics>(`/repositories/${id}/metrics`, { params: { top } });
  return response.data;
}

/** GET /api/v1/repositories/:id/branches */
export async function getRepositoryBranches(id: string): Promise<RepositoryBranch[]> {
  const response = await apiClient.get<RepositoryBranch[]>(`/repositories/${id}/branches`);
  return response.data;
}

/** GET /api/v1/repositories/:id/commits */
export async function getRepositoryCommits(
  id: string,
  params: { branch?: string; path?: string; page?: number; pageSize?: number } = {},
): Promise<RepositoryCommit[]> {
  const response = await apiClient.get<RepositoryCommit[]>(`/repositories/${id}/commits`, {
    params: {
      ...(params.branch ? { branch: params.branch } : {}),
      ...(params.path ? { path: params.path } : {}),
      page: params.page ?? 1,
      page_size: params.pageSize ?? 30,
    },
  });
  return response.data;
}

/** GET /api/v1/repositories/:id/pulls */
export async function getRepositoryPullRequests(
  id: string,
  params: { state?: 'open' | 'closed' | 'all'; page?: number; pageSize?: number } = {},
): Promise<RepositoryPullRequest[]> {
  const response = await apiClient.get<RepositoryPullRequest[]>(`/repositories/${id}/pulls`, {
    params: { state: params.state ?? 'open', page: params.page ?? 1, page_size: params.pageSize ?? 30 },
  });
  return response.data;
}
