/**
 * Types for Project Memory management, semantic retrieval & MCP resources (Issue #217).
 */

export type MemoryType = 'project' | 'decision' | 'rule' | 'task_summary' | 'failure';
export type MemoryStatus = 'active' | 'stale' | 'archived';

export interface MemoryEntry {
  id: string;
  repository_id: string;
  type: MemoryType;
  content: string;
  source: string;
  status: MemoryStatus;
  created_at: string;
  updated_at: string;
  embedding?: number[] | null;
}

export interface PaginatedMemoryEntriesResponse {
  page: number;
  page_size: number;
  total: number;
  items: MemoryEntry[];
}

export interface MemoryFilterParams {
  query?: string;
  type?: MemoryType;
  status?: MemoryStatus;
  page?: number;
  page_size?: number;
}

export interface CreateMemoryPayload {
  type: MemoryType;
  content: string;
  source?: string;
  status?: MemoryStatus;
  embedding?: number[];
}

export interface UpdateMemoryPayload {
  content?: string;
  status?: MemoryStatus;
  type?: MemoryType;
  source?: string;
}

export interface PinRulePayload {
  rule: string;
  source?: string;
}

export interface MCPMemoryResource {
  uri: string;
  name: string;
  mimeType: string;
  description?: string;
  text: string;
  entries_count: number;
  metadata?: Record<string, unknown>;
}

export interface MCPMemoryResourcesListResponse {
  resources: MCPMemoryResource[];
}
