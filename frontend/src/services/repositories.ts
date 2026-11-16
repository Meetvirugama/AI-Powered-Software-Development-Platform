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
} from '../types/api';

export interface ListRepositoriesParams {
  page: number;
  pageSize: number;
}

/**
 * Fetch a page of repositories for the authenticated user.
 *
 * GET /api/v1/repositories
 *
 * Until the backend supports pagination query parameters, client-side slicing
 * is used so the hook contract is stable. This function is the single place
 * to update once server-side pagination is confirmed.
 */
export async function listRepositories(
  params: ListRepositoriesParams,
): Promise<PaginatedRepositoryResponse> {
  const { page, pageSize } = params;
  const response = await apiClient.get<Repository[]>('/repositories', {
    params: { page, page_size: pageSize },
  });
  const all = response.data;

  // Server-side pagination support with graceful fallback (ISS-024)
  const items = all.length > pageSize ? all.slice((page - 1) * pageSize, page * pageSize) : all;

  return {
    items,
    total: all.length,
    page,
    page_size: pageSize,
  };
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



