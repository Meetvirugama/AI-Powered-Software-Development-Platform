/**
 * Project Memory Management & MCP Resources API Client (Issue #217).
 *
 * Connects frontend views to backend/app/api/v1/memories.py endpoints:
 *   - GET    /repositories/{repo_id}/memories
 *   - POST   /repositories/{repo_id}/memories
 *   - GET    /repositories/{repo_id}/memories/{entry_id}
 *   - PATCH  /repositories/{repo_id}/memories/{entry_id}
 *   - DELETE /repositories/{repo_id}/memories/{entry_id}
 *   - POST   /repositories/{repo_id}/memories/rules
 *   - GET    /repositories/{repo_id}/memories/mcp-resources
 *   - GET    /repositories/{repo_id}/memories/mcp-resources/{slug}
 */

import { apiClient } from './api';
import type {
  CreateMemoryPayload,
  MCPMemoryResource,
  MCPMemoryResourcesListResponse,
  MemoryEntry,
  MemoryFilterParams,
  PaginatedMemoryEntriesResponse,
  PinRulePayload,
  UpdateMemoryPayload,
} from '../types/memory';

/**
 * List and search memory entries for a repository.
 */
export async function listMemories(
  repositoryId: string,
  params: MemoryFilterParams = {}
): Promise<PaginatedMemoryEntriesResponse> {
  const queryParams = new URLSearchParams();
  if (params.query?.trim()) queryParams.set('query', params.query.trim());
  if (params.type) queryParams.set('type', params.type);
  if (params.status) queryParams.set('status', params.status);
  if (params.page) queryParams.set('page', String(params.page));
  if (params.page_size) queryParams.set('page_size', String(params.page_size));

  const qs = queryParams.toString();
  const url = `/repositories/${repositoryId}/memories${qs ? `?${qs}` : ''}`;
  const response = await apiClient.get<PaginatedMemoryEntriesResponse>(url);
  return response.data;
}

/**
 * Retrieve a specific memory entry.
 */
export async function getMemory(
  repositoryId: string,
  entryId: string
): Promise<MemoryEntry> {
  const response = await apiClient.get<MemoryEntry>(
    `/repositories/${repositoryId}/memories/${entryId}`
  );
  return response.data;
}

/**
 * Create a new memory entry.
 */
export async function createMemory(
  repositoryId: string,
  payload: CreateMemoryPayload
): Promise<MemoryEntry> {
  const response = await apiClient.post<MemoryEntry>(
    `/repositories/${repositoryId}/memories`,
    payload
  );
  return response.data;
}

/**
 * Update an existing memory entry.
 */
export async function updateMemory(
  repositoryId: string,
  entryId: string,
  payload: UpdateMemoryPayload
): Promise<MemoryEntry> {
  const response = await apiClient.patch<MemoryEntry>(
    `/repositories/${repositoryId}/memories/${entryId}`,
    payload
  );
  return response.data;
}

/**
 * Delete a memory entry.
 */
export async function deleteMemory(
  repositoryId: string,
  entryId: string
): Promise<void> {
  await apiClient.delete(`/repositories/${repositoryId}/memories/${entryId}`);
}

/**
 * Pin an architectural rule into project memory.
 */
export async function pinArchitecturalRule(
  repositoryId: string,
  payload: PinRulePayload
): Promise<MemoryEntry> {
  const response = await apiClient.post<MemoryEntry>(
    `/repositories/${repositoryId}/memories/rules`,
    payload
  );
  return response.data;
}

/**
 * List exposed MCP memory resources for a repository.
 */
export async function listMCPResources(
  repositoryId: string
): Promise<MCPMemoryResourcesListResponse> {
  const response = await apiClient.get<MCPMemoryResourcesListResponse>(
    `/repositories/${repositoryId}/memories/mcp-resources`
  );
  return response.data;
}

/**
 * Resolve a specific MCP memory resource.
 */
export async function getMCPResource(
  repositoryId: string,
  resourceSlug: string
): Promise<MCPMemoryResource> {
  const response = await apiClient.get<MCPMemoryResource>(
    `/repositories/${repositoryId}/memories/mcp-resources/${resourceSlug}`
  );
  return response.data;
}
