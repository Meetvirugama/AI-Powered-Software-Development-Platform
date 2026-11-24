import React, { useState, useMemo, useEffect, useCallback } from 'react';
import { Loader2 } from 'lucide-react';
import { listMCPServers, pingMCPServer } from '../services/mcp';
import type {
  MCPServerRegistration,
  MCPToolSchemaItem,
  ToolRiskTier,
} from '../services/mcp';

export type { ToolRiskTier, MCPToolSchemaItem, MCPServerRegistration };

export const ToolsIntegrationsAdminPage: React.FC = () => {
  const [servers, setServers] = useState<MCPServerRegistration[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedToolKey, setExpandedToolKey] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [pingingId, setPingingId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pingError, setPingError] = useState<string | null>(null);

  const loadServers = useCallback((isMounted?: () => boolean) => {
    setLoadError(null);
    return listMCPServers()
      .then((data) => {
        if (isMounted && !isMounted()) return;
        setServers(Array.isArray(data) ? data : []);
      })
      .catch(() => {
        if (isMounted && !isMounted()) return;
        setLoadError('Unable to load the MCP tool catalog.');
      })
      .finally(() => {
        if (isMounted && !isMounted()) return;
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    let mounted = true;
    void loadServers(() => mounted);
    return () => {
      mounted = false;
    };
  }, [loadServers]);

  const handleRetryLoad = () => {
    setLoading(true);
    void loadServers();
  };

  const filteredServers = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return servers;
    return servers.filter(
      (srv) =>
        srv.name.toLowerCase().includes(q) ||
        srv.endpointOrCommand.toLowerCase().includes(q) ||
        srv.tools.some(
          (t) =>
            t.name.toLowerCase().includes(q) ||
            t.description.toLowerCase().includes(q),
        ),
    );
  }, [servers, searchQuery]);

  const pingServer = async (id: string) => {
    if (pingingId === id) return;
    setPingError(null);
    setPingingId(id);
    try {
      const result = await pingMCPServer(id);
      setServers((prev) =>
        prev.map((server) => (server.id === id ? result : server)),
      );
    } catch {
      setPingError('Unable to ping the MCP dispatcher.');
    } finally {
      setPingingId((cur) => (cur === id ? null : cur));
    }
  };

  return (
    <div className="h-full overflow-y-auto pr-1 space-y-6 text-foreground">
      <header className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-border pb-5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="text-xl font-semibold tracking-tight text-foreground">
              Tools &amp; MCP Integrations
            </h1>
            {loading && (
              <span
                role="status"
                aria-live="polite"
                className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-muted text-muted-foreground text-[11px] font-medium"
              >
                <Loader2 className="h-3 w-3 animate-spin" />
                <span>Loading MCP tools…</span>
              </span>
            )}
          </div>
          <p className="text-sm text-muted-foreground mt-0.5">
            Inspect built-in MCP tool schemas and approval requirements.
          </p>
        </div>
        <input
          type="search"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Filter servers or tools..."
          aria-label="Filter servers or tools"
          className="px-3 py-1.5 rounded-lg bg-card border border-border text-xs text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:w-64"
        />
      </header>

      {loadError && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-2.5 text-xs text-destructive"
        >
          <span>{loadError}</span>
          <button
            type="button"
            onClick={handleRetryLoad}
            className="font-medium underline shrink-0 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
          >
            Retry
          </button>
        </div>
      )}

      {pingError && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-2.5 text-xs text-destructive"
        >
          <span>{pingError}</span>
          <button
            type="button"
            onClick={() => setPingError(null)}
            className="font-medium underline shrink-0 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
          >
            Dismiss
          </button>
        </div>
      )}

      <div className="space-y-4 pb-6">
        {!loading && !loadError && filteredServers.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border bg-card/50 p-8 text-center space-y-3">
            <p className="text-sm font-medium text-foreground">
              {searchQuery.trim()
                ? `No MCP servers or tools match "${searchQuery.trim()}".`
                : 'No matching tools.'}
            </p>
            {searchQuery.trim() && (
              <>
                <p className="text-xs text-muted-foreground">
                  Try adjusting or clearing your filter query.
                </p>
                <button
                  type="button"
                  onClick={() => setSearchQuery('')}
                  className="px-3 py-1.5 rounded-lg border border-border bg-background hover:bg-accent text-xs font-medium text-foreground cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  Clear filter
                </button>
              </>
            )}
          </div>
        ) : (
          filteredServers.map((server) => (
            <section
              key={server.id}
              className="rounded-xl border border-border bg-card p-5 space-y-4"
            >
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h2 className="text-base font-semibold text-foreground break-words">
                      {server.name}
                    </h2>
                    <span className="text-[11px] font-mono px-2 py-0.5 rounded-md bg-muted text-muted-foreground border border-border">
                      Built-in · MCP {server.protocolVersion}
                    </span>
                    <span
                      className={`text-[11px] font-medium px-2 py-0.5 rounded-full border ${
                        server.status === 'connected'
                          ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/25'
                          : server.status === 'degraded'
                            ? 'bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/25'
                            : 'bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-500/25'
                      }`}
                    >
                      {server.status}
                      {server.lastLatencyMs != null ? ` (${server.lastLatencyMs}ms)` : ''}
                    </span>
                  </div>
                  <p
                    className="text-xs font-mono text-muted-foreground mt-1 truncate"
                    title={server.endpointOrCommand}
                  >
                    {server.endpointOrCommand}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2 shrink-0">
                  <button
                    type="button"
                    disabled={pingingId === server.id}
                    onClick={() => void pingServer(server.id)}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium border border-border bg-background text-foreground hover:bg-accent transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {pingingId === server.id ? 'Pinging…' : 'Ping dispatcher'}
                  </button>
                </div>
              </div>

              {server.tools.length === 0 ? (
                <p className="text-xs text-muted-foreground italic border-t border-border/60 pt-3">
                  No tools exposed by this server yet.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm border-collapse">
                    <thead>
                      <tr className="border-b border-border text-muted-foreground text-[11px] uppercase tracking-wider">
                        <th className="py-2 pr-4 font-medium whitespace-nowrap">Tool Name</th>
                        <th className="py-2 pr-4 font-medium whitespace-nowrap">Description</th>
                        <th className="py-2 pr-4 font-medium whitespace-nowrap">Risk Tier</th>
                        <th className="py-2 pr-4 font-medium whitespace-nowrap">Schema</th>
                        <th className="py-2 font-medium whitespace-nowrap">Approval Gate</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/70">
                      {server.tools.map((tool) => {
                        const rowKey = `${server.id}:${tool.name}`;
                        const isExpanded = expandedToolKey === rowKey;
                        return (
                          <React.Fragment key={tool.name}>
                            <tr className="hover:bg-accent/30 transition-colors">
                              <td className="py-2.5 pr-4 font-mono text-xs font-medium text-foreground whitespace-nowrap">
                                {tool.name}
                              </td>
                              <td className="py-2.5 pr-4 text-muted-foreground text-xs min-w-[200px]">
                                {tool.description}
                              </td>
                              <td className="py-2.5 pr-4 whitespace-nowrap">
                                <span
                                  className={`text-[11px] font-mono px-2 py-0.5 rounded-md border ${
                                    tool.riskTier === 'critical'
                                      ? 'bg-red-500/10 text-red-700 dark:text-red-400 border-red-500/30 font-semibold'
                                      : tool.riskTier === 'high'
                                        ? 'bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-500/25'
                                        : tool.riskTier === 'medium'
                                          ? 'bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/25'
                                          : 'bg-muted text-muted-foreground border-border'
                                  }`}
                                >
                                  {tool.riskTier}
                                </span>
                              </td>
                              <td className="py-2.5 pr-4 whitespace-nowrap">
                                <button
                                  type="button"
                                  aria-expanded={isExpanded}
                                  onClick={() => setExpandedToolKey(isExpanded ? null : rowKey)}
                                  className="text-xs font-medium text-foreground underline underline-offset-2 hover:text-muted-foreground cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
                                >
                                  {isExpanded ? 'Hide Schema' : 'Inspect Schema'}
                                </button>
                              </td>
                              <td className="py-2.5 whitespace-nowrap">
                                <span
                                  className={`inline-block text-xs px-2.5 py-1 rounded-md border ${
                                    tool.requiresApproval
                                      ? 'bg-amber-500/10 border-amber-500/30 text-amber-700 dark:text-amber-400'
                                      : 'bg-muted/60 border-border text-muted-foreground'
                                  }`}
                                >
                                  {tool.requiresApproval
                                    ? 'Approval Required'
                                    : 'No additional approval'}
                                </span>
                              </td>
                            </tr>
                            {isExpanded && (
                              <tr>
                                <td colSpan={5} className="py-2.5">
                                  <pre className="p-3 rounded-lg bg-muted/60 border border-border text-xs font-mono text-foreground overflow-x-auto">
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
          ))
        )}
      </div>
    </div>
  );
};
