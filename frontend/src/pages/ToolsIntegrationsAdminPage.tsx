import React, { useState, useMemo, useEffect } from 'react';
import { listMCPServers, pingMCPServer } from '../services/mcp';
import type { MCPServerRegistration } from '../services/mcp';

export const ToolsIntegrationsAdminPage: React.FC = () => {
  const [servers, setServers] = useState<MCPServerRegistration[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedToolKey, setExpandedToolKey] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [pinging, setPinging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    listMCPServers()
      .then((data) => { if (mounted) setServers(data); })
      .catch(() => { if (mounted) setError('Unable to load the MCP tool catalog.'); })
      .finally(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, []);

  const filteredServers = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return servers;
    return servers.filter(
      (srv) =>
        srv.name.toLowerCase().includes(q) ||
        srv.tools.some((t) => t.name.toLowerCase().includes(q) || t.description.toLowerCase().includes(q)),
    );
  }, [servers, searchQuery]);

  const pingServer = async (id: string) => {
    setError(null);
    setPinging(true);
    try {
      const result = await pingMCPServer(id);
      setServers((servers) => servers.map((server) => server.id === id ? result : server));
    } catch {
      setError('Unable to ping the MCP dispatcher.');
    } finally {
      setPinging(false);
    }
  };

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6 text-slate-100">
      <header className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-slate-800 pb-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Tools &amp; MCP Integrations</h1>
          <p className="text-sm text-slate-400">
            Inspect built-in MCP tool schemas and approval requirements.
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

      {loading && <p role="status">Loading MCP tools…</p>}
      {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
      {!loading && !error && filteredServers.length === 0 && <p className="text-sm text-slate-400">No matching tools.</p>}

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
                    Built-in · MCP {server.protocolVersion}
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
                  onClick={() => void pingServer(server.id)}
                  disabled={pinging}
                  className="px-3 py-1.5 rounded text-xs font-medium border border-slate-700 hover:bg-slate-800"
                >
                  {pinging ? 'Pinging…' : 'Ping dispatcher'}
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
                              <span
                                className={`text-xs px-2.5 py-1 rounded border ${
                                  tool.requiresApproval
                                    ? 'bg-amber-950/60 border-amber-700 text-amber-200'
                                    : 'bg-slate-800 border-slate-700 text-slate-300'
                                }`}
                              >
                                {tool.requiresApproval ? 'Approval Required' : 'No additional approval'}
                              </span>
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
