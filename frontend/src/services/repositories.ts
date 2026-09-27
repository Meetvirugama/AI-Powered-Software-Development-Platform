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
  PaginatedRepositoryFileResponse,
  RepositoryDependency,
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
  const response = await apiClient.get<Repository[]>('/repositories');
  const all = response.data;

  // Client-side pagination shim — replace with server-side params once the
  // backend supports ?page=&page_size= on this endpoint.
  const { page, pageSize } = params;
  const start = (page - 1) * pageSize;
  const items = all.slice(start, start + pageSize);

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
      },
    },
  );
  return response.data;
}

/**
 * Fetch top-level dependencies for a repository.
 *
 * GET /api/v1/repositories/:id/dependencies
 * MOCKED: The backend does not yet expose dependencies.
 */
export async function getRepositoryDependencies(
  id: string,
): Promise<RepositoryDependency[]> {
  const response = await apiClient.get<RepositoryDependency[]>(
    `/repositories/${id}/dependencies`,
  );
  return response.data;
}
