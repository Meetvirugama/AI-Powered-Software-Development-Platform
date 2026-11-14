import React, { useState, useMemo } from 'react';

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

const INITIAL_SERVERS: MCPServerRegistration[] = [
  {
    id: 'mcp-platform-core',
    name: 'Platform Repository Intelligence MCP',
    transport: 'stdio',
    endpointOrCommand: 'python -m backend.mcp.server',
    enabled: true,
    status: 'connected',
    protocolVersion: '2024-11-05',
    lastLatencyMs: 4,
    tools: [
      {
        name: 'repo_read_file',
        description: 'Read repository file with workspace boundary and secret-redaction guards.',
        riskTier: 'low',
        requiresApproval: false,
        inputSchemaJson: JSON.stringify(
          {
            type: 'object',
            properties: { path: { type: 'string' } },
            required: ['path'],
            additionalProperties: false,
          },
          null,
          2,
        ),
      },
      {
        name: 'repo_search_symbols',
        description: 'Query Tree-sitter + PageRank + Co-Change symbol intelligence graph.',
        riskTier: 'low',
        requiresApproval: false,
        inputSchemaJson: JSON.stringify(
          {
            type: 'object',
            properties: { query: { type: 'string' }, limit: { type: 'integer' } },
            required: ['query'],
            additionalProperties: false,
          },
          null,
          2,
        ),
      },
      {
        name: 'sandbox_execute_patch',
        description: 'Apply synthesized unified diff inside isolated sandbox worktree.',
        riskTier: 'high',
        requiresApproval: true,
        inputSchemaJson: JSON.stringify(
          {
            type: 'object',
            properties: { unified_diff: { type: 'string' } },
            required: ['unified_diff'],
            additionalProperties: false,
          },
          null,
          2,
        ),
      },
    ],
  },
];

export const ToolsIntegrationsAdminPage: React.FC = () => {
  const [servers, setServers] = useState<MCPServerRegistration[]>(INITIAL_SERVERS);
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedToolKey, setExpandedToolKey] = useState<string | null>(null);
  const [newServerName, setNewServerName] = useState('');
  const [newServerEndpoint, setNewServerEndpoint] = useState('');
  const [newServerTransport, setNewServerTransport] = useState<'stdio' | 'sse' | 'streamable_http'>('stdio');

  const filteredServers = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return servers;
    return servers.filter(
      (srv) =>
        srv.name.toLowerCase().includes(q) ||
        srv.tools.some((t) => t.name.toLowerCase().includes(q) || t.description.toLowerCase().includes(q)),
    );
  }, [servers, searchQuery]);

  const toggleServer = (id: string) => {
    setServers((prev) =>
      prev.map((srv) =>
        srv.id === id
          ? {
              ...srv,
              enabled: !srv.enabled,
              status: !srv.enabled ? 'connected' : 'offline',
              lastLatencyMs: !srv.enabled ? 5 : null,
            }
          : srv,
      ),
    );
  };

  const pingServer = (id: string) => {
    setServers((prev) =>
      prev.map((srv) =>
        srv.id === id && srv.enabled
          ? { ...srv, status: 'connected', lastLatencyMs: Math.max(1, Math.floor(Math.random() * 8) + 2) }
          : srv,
      ),
    );
  };

  const toggleToolApprovalPolicy = (serverId: string, toolName: string) => {
    setServers((prev) =>
      prev.map((srv) =>
        srv.id !== serverId
          ? srv
          : {
              ...srv,
              tools: srv.tools.map((tool) =>
                tool.name === toolName ? { ...tool, requiresApproval: !tool.requiresApproval } : tool,
              ),
            },
      ),
    );
  };

  const handleRegisterServer = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newServerName.trim() || !newServerEndpoint.trim()) return;
    const created: MCPServerRegistration = {
      id: `mcp-${Date.now()}`,
      name: newServerName.trim(),
      transport: newServerTransport,
      endpointOrCommand: newServerEndpoint.trim(),
      enabled: true,
      status: 'connected',
      protocolVersion: '2024-11-05',
      lastLatencyMs: 3,
      tools: [],
    };
    setServers((prev) => [...prev, created]);
    setNewServerName('');
    setNewServerEndpoint('');
  };

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6 text-slate-100">
      <header className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-slate-800 pb-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Tools &amp; MCP Integrations</h1>
          <p className="text-sm text-slate-400">
            Manage Model Context Protocol (MCP) servers, inspect JSON Schema tool contracts, and configure approval gates.
          </p>
        </div>
        <input
          type="search"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Filter servers or tools..."
          aria-label="Filter servers or tools"
          className="px-3 py-2 rounded-md bg-slate-900 border border-slate-700 text-sm"
        />
      </header>

      <form
        onSubmit={handleRegisterServer}
        className="grid grid-cols-1 md:grid-cols-4 gap-3 bg-slate-900/70 border border-slate-800 rounded-lg p-4"
      >
        <input
          type="text"
          value={newServerName}
          onChange={(e) => setNewServerName(e.target.value)}
          placeholder="Server display name"
          className="px-3 py-2 rounded bg-slate-950 border border-slate-700 text-sm"
        />
        <select
          value={newServerTransport}
          onChange={(e) => setNewServerTransport(e.target.value as 'stdio' | 'sse' | 'streamable_http')}
          className="px-3 py-2 rounded bg-slate-950 border border-slate-700 text-sm"
        >
          <option value="stdio">stdio</option>
          <option value="sse">SSE</option>
          <option value="streamable_http">Streamable HTTP</option>
        </select>
        <input
          type="text"
          value={newServerEndpoint}
          onChange={(e) => setNewServerEndpoint(e.target.value)}
          placeholder="Command or endpoint URL"
          className="px-3 py-2 rounded bg-slate-950 border border-slate-700 text-sm"
        />
        <button
          type="submit"
          className="px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-500 text-sm font-medium"
        >
          Register MCP Server
        </button>
      </form>

      <div className="space-y-4">
        {filteredServers.map((server) => (
          <section
            key={server.id}
            className="rounded-lg border border-slate-800 bg-slate-900/50 p-4 space-y-4"
          >
            <div className="flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-lg font-medium">{server.name}</h2>
                  <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-300">
                    {server.transport} · MCP {server.protocolVersion}
                  </span>
                  <span
                    className={`text-xs px-2 py-0.5 rounded ${
                      server.status === 'connected'
                        ? 'bg-emerald-950 text-emerald-300 border border-emerald-800'
                        : 'bg-rose-950 text-rose-300 border border-rose-800'
                    }`}
                  >
                    {server.status}
                    {server.lastLatencyMs != null ? ` (${server.lastLatencyMs}ms)` : ''}
                  </span>
                </div>
                <p className="text-xs font-mono text-slate-400 mt-1">{server.endpointOrCommand}</p>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => pingServer(server.id)}
                  className="px-3 py-1.5 rounded text-xs font-medium border border-slate-700 hover:bg-slate-800"
                >
                  Ping Handshake
                </button>
                <button
                  type="button"
                  onClick={() => toggleServer(server.id)}
                  className="px-3 py-1.5 rounded text-xs font-medium border border-slate-700 hover:bg-slate-800"
                >
                  {server.enabled ? 'Disable Server' : 'Enable Server'}
                </button>
              </div>
            </div>

            {server.tools.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm border-collapse">
                  <thead>
                    <tr className="border-b border-slate-800 text-slate-400 text-xs uppercase">
                      <th className="py-2 pr-4">Tool Name</th>
                      <th className="py-2 pr-4">Description</th>
                      <th className="py-2 pr-4">Risk Tier</th>
                      <th className="py-2 pr-4">Schema</th>
                      <th className="py-2">Approval Gate</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    {server.tools.map((tool) => {
                      const rowKey = `${server.id}:${tool.name}`;
                      return (
                        <React.Fragment key={tool.name}>
                          <tr>
                            <td className="py-2 pr-4 font-mono text-xs text-indigo-300">{tool.name}</td>
                            <td className="py-2 pr-4 text-slate-300 text-xs">{tool.description}</td>
                            <td className="py-2 pr-4">
                              <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-200">
                                {tool.riskTier}
                              </span>
                            </td>
                            <td className="py-2 pr-4">
                              <button
                                type="button"
                                onClick={() => setExpandedToolKey(expandedToolKey === rowKey ? null : rowKey)}
                                className="text-xs text-indigo-400 underline"
                              >
                                {expandedToolKey === rowKey ? 'Hide Schema' : 'Inspect Schema'}
                              </button>
                            </td>
                            <td className="py-2">
                              <button
                                type="button"
                                onClick={() => toggleToolApprovalPolicy(server.id, tool.name)}
                                className={`text-xs px-2.5 py-1 rounded border ${
                                  tool.requiresApproval
                                    ? 'bg-amber-950/60 border-amber-700 text-amber-200'
                                    : 'bg-slate-800 border-slate-700 text-slate-300'
                                }`}
                              >
                                {tool.requiresApproval ? 'Approval Required' : 'Auto-Approve'}
                              </button>
                            </td>
                          </tr>
                          {expandedToolKey === rowKey && (
                            <tr>
                              <td colSpan={5} className="py-2">
                                <pre className="p-3 rounded bg-slate-950 border border-slate-800 text-xs font-mono text-slate-300 overflow-x-auto">
                                  {tool.inputSchemaJson}
                                </pre>
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        ))}
      </div>
    </div>
  );
};
