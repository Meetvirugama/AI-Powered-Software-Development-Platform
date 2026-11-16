import { apiClient } from './api';

export type ToolRiskTier = 'low' | 'medium' | 'high' | 'critical';

export interface MCPToolSchemaItem {
  name: string;
  description: string;
  riskTier: ToolRiskTier;
  requiresApproval: boolean;
  inputSchemaJson: string;
}

export interface MCPServerRegistration {
  id: string;
  name: string;
  transport: 'stdio' | 'sse' | 'streamable_http';
  endpointOrCommand: string;
  enabled: boolean;
  status: 'connected' | 'degraded' | 'offline';
  protocolVersion: string;
  lastLatencyMs: number | null;
  tools: MCPToolSchemaItem[];
}

export interface RegisterMCPServerPayload {
  name: string;
  transport?: 'stdio' | 'sse' | 'streamable_http';
  endpointOrCommand: string;
}

/**
 * List registered MCP servers from the backend registry.
 * GET /api/v1/mcp/servers
 */
export async function listMCPServers(): Promise<MCPServerRegistration[]> {
  const resp = await apiClient.get<MCPServerRegistration[]>('/mcp/servers');
  return resp.data;
}

/**
 * Register a new external or local MCP server.
 * POST /api/v1/mcp/servers
 */
export async function registerMCPServer(payload: RegisterMCPServerPayload): Promise<MCPServerRegistration> {
  const resp = await apiClient.post<MCPServerRegistration>('/mcp/servers', payload);
  return resp.data;
}

/**
 * Probe server health and round-trip latency.
 * POST /api/v1/mcp/servers/:serverId/ping
 */
export async function pingMCPServer(serverId: string): Promise<MCPServerRegistration> {
  const resp = await apiClient.post<MCPServerRegistration>(`/mcp/servers/${serverId}/ping`);
  return resp.data;
}

/**
 * Toggle an MCP server between enabled and disabled states.
 * PATCH /api/v1/mcp/servers/:serverId/toggle
 */
export async function toggleMCPServer(serverId: string): Promise<MCPServerRegistration> {
  const resp = await apiClient.patch<MCPServerRegistration>(`/mcp/servers/${serverId}/toggle`);
  return resp.data;
}

/**
 * Update the approval gate requirement for an individual tool.
 * PATCH /api/v1/mcp/servers/:serverId/tools/:toolName/policy
 */
export async function updateMCPToolPolicy(
  serverId: string,
  toolName: string,
  requiresApproval: boolean
): Promise<MCPServerRegistration> {
  const resp = await apiClient.patch<MCPServerRegistration>(
    `/mcp/servers/${serverId}/tools/${toolName}/policy`,
    { requiresApproval }
  );
  return resp.data;
}
