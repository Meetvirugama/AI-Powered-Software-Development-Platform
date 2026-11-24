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
  transport: 'in_process';
  endpointOrCommand: string;
  enabled: boolean;
  status: 'connected' | 'degraded' | 'offline';
  protocolVersion: string;
  lastLatencyMs: number | null;
  tools: MCPToolSchemaItem[];
}

export async function listMCPServers(): Promise<MCPServerRegistration[]> {
  const resp = await apiClient.get<MCPServerRegistration[]>('/mcp/servers');
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
