import React, { useState, useMemo, useEffect, useCallback, useRef } from 'react';
import { Loader2 } from 'lucide-react';
import { normaliseError } from '../services/api';
import type { ApiError } from '../types/api';
import {
  listMCPServers,
  registerMCPServer,
  pingMCPServer,
  toggleMCPServer,
  updateMCPToolPolicy,
} from '../services/mcp';
import type {
  MCPServerRegistration,
  MCPToolSchemaItem,
  ToolRiskTier,
} from '../services/mcp';

export type { ToolRiskTier, MCPToolSchemaItem, MCPServerRegistration };

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

function toApiError(err: unknown): ApiError {
  if (
    typeof err === 'object' &&
    err !== null &&
    'code' in err &&
    'message' in err &&
    'retryable' in err &&
    typeof (err as ApiError).code === 'string' &&
    typeof (err as ApiError).message === 'string' &&
    typeof (err as ApiError).retryable === 'boolean'
  ) {
    return err as ApiError;
  }
  return normaliseError(err);
}

async function pingMCPServerWithTiming(id: string): Promise<MCPServerRegistration> {
  const startedAt = Date.now();
  const updated = await pingMCPServer(id);
  const elapsedMs = Math.max(1, Date.now() - startedAt);
  return {
    ...updated,
    lastLatencyMs: updated.lastLatencyMs ?? elapsedMs,
  };
}

export const ToolsIntegrationsAdminPage: React.FC = () => {
  const [servers, setServers] = useState<MCPServerRegistration[]>(INITIAL_SERVERS);
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedToolKey, setExpandedToolKey] = useState<string | null>(null);
  const [newServerName, setNewServerName] = useState('');
  const [newServerEndpoint, setNewServerEndpoint] = useState('');
  const [newServerTransport, setNewServerTransport] = useState<'stdio' | 'sse' | 'streamable_http'>('stdio');

  const [isLoadingServers, setIsLoadingServers] = useState(true);
  const [registryWarning, setRegistryWarning] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pingingId, setPingingId] = useState<string | null>(null);
  const [togglingServerId, setTogglingServerId] = useState<string | null>(null);
  const [updatingToolKey, setUpdatingToolKey] = useState<string | null>(null);
  const [isRegistering, setIsRegistering] = useState(false);
  const [formErrors, setFormErrors] = useState<{ name?: string; endpoint?: string }>({});
  const hasLocalMutationRef = useRef(false);

  const loadServersAsync = useCallback((isMounted?: () => boolean) => {
    return listMCPServers()
      .then((data) => {
        if (isMounted && !isMounted()) return;
        if (Array.isArray(data) && !hasLocalMutationRef.current) {
          setServers(data);
        }
        setRegistryWarning(null);
      })
      .catch((err) => {
        if (isMounted && !isMounted()) return;
        const apiErr = toApiError(err);
        setRegistryWarning(
          `Live MCP registry is unreachable (${apiErr.message}) — showing built-in platform server defaults.`
        );
      })
      .finally(() => {
        if (isMounted && !isMounted()) return;
        setIsLoadingServers(false);
      });
  }, []);

  const handleRetryRegistry = () => {
    setIsLoadingServers(true);
    void loadServersAsync();
  };

  useEffect(() => {
    let mounted = true;
    void loadServersAsync(() => mounted);
    return () => {
      mounted = false;
    };
  }, [loadServersAsync]);

  const filteredServers = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return servers;
    return servers.filter(
      (srv) =>
        srv.name.toLowerCase().includes(q) ||
        srv.endpointOrCommand.toLowerCase().includes(q) ||
        srv.tools.some((t) => t.name.toLowerCase().includes(q) || t.description.toLowerCase().includes(q)),
    );
  }, [servers, searchQuery]);

  const toggleServer = (id: string) => {
    const prevServer = servers.find((s) => s.id === id);
    if (!prevServer) return;
    hasLocalMutationRef.current = true;
    setActionError(null);
    setTogglingServerId(id);

    setServers((prev) =>
      prev.map((srv) =>
        srv.id === id
          ? {
              ...srv,
              enabled: !srv.enabled,
              status: !srv.enabled ? 'connected' : 'offline',
              lastLatencyMs: !srv.enabled ? srv.lastLatencyMs : null,
            }
          : srv,
      ),
    );

    toggleMCPServer(id)
      .then((updated) => {
        if (updated && updated.id) {
          setServers((prev) => prev.map((srv) => (srv.id === id ? updated : srv)));
        }
      })
      .catch((err) => {
        const apiErr = toApiError(err);
        setServers((prev) => prev.map((srv) => (srv.id === id ? prevServer : srv)));
        setActionError(`Failed to update ${prevServer.name}: ${apiErr.message}`);
      })
      .finally(() => {
        setTogglingServerId((cur) => (cur === id ? null : cur));
      });
  };

  const pingServer = (id: string) => {
    const target = servers.find((s) => s.id === id);
    if (!target || !target.enabled || pingingId === id) return;

    setActionError(null);
    setPingingId(id);

    pingMCPServerWithTiming(id)
      .then((updated) => {
        setServers((prev) =>
          prev.map((srv) => (srv.id === id ? updated : srv)),
        );
      })
      .catch((err) => {
        const apiErr = toApiError(err);
        setActionError(`Ping handshake failed for ${target.name}: ${apiErr.message}`);
      })
      .finally(() => {
        setPingingId((cur) => (cur === id ? null : cur));
      });
  };

  const toggleToolApprovalPolicy = (serverId: string, toolName: string) => {
    const target = servers.find((s) => s.id === serverId);
    const tool = target?.tools.find((t) => t.name === toolName);
    if (!target || !tool) return;
    const prevRequiresApproval = tool.requiresApproval;
    const nextVal = !prevRequiresApproval;
    const rowKey = `${serverId}:${toolName}`;

    hasLocalMutationRef.current = true;
    setActionError(null);
    setUpdatingToolKey(rowKey);

    setServers((prev) =>
      prev.map((srv) =>
        srv.id !== serverId
          ? srv
          : {
              ...srv,
              tools: srv.tools.map((t) =>
                t.name === toolName ? { ...t, requiresApproval: nextVal } : t,
              ),
            },
      ),
    );

    updateMCPToolPolicy(serverId, toolName, nextVal)
      .then((updated) => {
        if (updated && updated.id) {
          setServers((prev) => prev.map((srv) => (srv.id === serverId ? updated : srv)));
        }
      })
      .catch((err) => {
        const apiErr = toApiError(err);
        setServers((prev) =>
          prev.map((srv) =>
            srv.id !== serverId
              ? srv
              : {
                  ...srv,
                  tools: srv.tools.map((t) =>
                    t.name === toolName ? { ...t, requiresApproval: prevRequiresApproval } : t,
                  ),
                },
          ),
        );
        setActionError(`Failed to update approval policy for ${toolName}: ${apiErr.message}`);
      })
      .finally(() => {
        setUpdatingToolKey((cur) => (cur === rowKey ? null : cur));
      });
  };

  const handleRegisterServer = (e: React.FormEvent) => {
    e.preventDefault();
    const name = newServerName.trim();
    const endpoint = newServerEndpoint.trim();
    const nextErrors: { name?: string; endpoint?: string } = {};
    if (!name) nextErrors.name = 'Server display name is required.';
    if (!endpoint) nextErrors.endpoint = 'Command or endpoint URL is required.';
    if (nextErrors.name || nextErrors.endpoint) {
      setFormErrors(nextErrors);
      return;
    }

    hasLocalMutationRef.current = true;
    setFormErrors({});
    setActionError(null);
    setIsRegistering(true);

    const transport = newServerTransport;
    const tempId = `mcp-${Date.now()}`;
    const created: MCPServerRegistration = {
      id: tempId,
      name,
      transport,
      endpointOrCommand: endpoint,
      enabled: true,
      status: 'connected',
      protocolVersion: '2024-11-05',
      lastLatencyMs: null,
      tools: [],
    };
    setServers((prev) => [...prev, created]);
    setNewServerName('');
    setNewServerEndpoint('');

    registerMCPServer({
      name,
      transport,
      endpointOrCommand: endpoint,
    })
      .then((saved) => {
        if (saved && saved.id) {
          setServers((prev) => prev.map((srv) => (srv.id === tempId ? saved : srv)));
        }
      })
      .catch((err) => {
        const apiErr = toApiError(err);
        if (
          apiErr.status === 404 ||
          apiErr.status === 0 ||
          apiErr.code === 'NETWORK_ERROR' ||
          apiErr.code === 'REQUEST_TIMEOUT'
        ) {
          setActionError(
            `Registered "${name}" in local session only (live registry endpoint unavailable: ${apiErr.message})`
          );
        } else {
          setServers((prev) => prev.filter((srv) => srv.id !== tempId));
          setActionError(`Failed to register "${name}": ${apiErr.message}`);
        }
      })
      .finally(() => {
        setIsRegistering(false);
      });
  };

  return (
    <div className="h-full overflow-y-auto pr-1 space-y-6 text-foreground">
      <header className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-border pb-5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="text-xl font-semibold tracking-tight text-foreground">Tools &amp; MCP Integrations</h1>
            {isLoadingServers && (
              <span
                role="status"
                aria-live="polite"
                className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-muted text-muted-foreground text-[11px] font-medium"
              >
                <Loader2 className="h-3 w-3 animate-spin" />
                <span>Syncing registry…</span>
              </span>
            )}
          </div>
          <p className="text-sm text-muted-foreground mt-0.5">
            Manage Model Context Protocol (MCP) servers, inspect tool schemas, and configure approval gates.
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

      {registryWarning && (
        <div
          role="status"
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-xs text-amber-800 dark:text-amber-300"
        >
          <span>{registryWarning}</span>
          <div className="flex items-center gap-3 shrink-0">
            <button
              type="button"
              onClick={handleRetryRegistry}
              className="font-medium underline cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
            >
              Retry
            </button>
            <button
              type="button"
              onClick={() => setRegistryWarning(null)}
              className="font-medium underline cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {actionError && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-2.5 text-xs text-destructive"
        >
          <span>{actionError}</span>
          <button
            type="button"
            onClick={() => setActionError(null)}
            className="font-medium underline shrink-0 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
          >
            Dismiss
          </button>
        </div>
      )}

      <form
        onSubmit={handleRegisterServer}
        noValidate
        className="grid grid-cols-1 md:grid-cols-4 md:items-start gap-3 bg-card border border-border rounded-xl p-4"
      >
        <div className="space-y-1">
          <label htmlFor="mcp-server-name" className="block text-[11px] font-medium text-muted-foreground">
            Server Name
          </label>
          <input
            id="mcp-server-name"
            type="text"
            value={newServerName}
            onChange={(e) => {
              setNewServerName(e.target.value);
              if (formErrors.name) setFormErrors((prev) => ({ ...prev, name: undefined }));
            }}
            placeholder="Server display name"
            aria-invalid={Boolean(formErrors.name)}
            aria-describedby={formErrors.name ? 'mcp-name-error' : undefined}
            className="w-full px-3 py-2 rounded-lg bg-background border border-border text-xs text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          {formErrors.name && (
            <p id="mcp-name-error" role="alert" className="text-[11px] text-destructive">
              {formErrors.name}
            </p>
          )}
        </div>

        <div className="space-y-1">
          <label htmlFor="mcp-server-transport" className="block text-[11px] font-medium text-muted-foreground">
            Transport
          </label>
          <select
            id="mcp-server-transport"
            value={newServerTransport}
            onChange={(e) => setNewServerTransport(e.target.value as 'stdio' | 'sse' | 'streamable_http')}
            className="w-full px-3 py-2 rounded-lg bg-background border border-border text-xs text-foreground cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <option value="stdio">stdio</option>
            <option value="sse">SSE</option>
            <option value="streamable_http">Streamable HTTP</option>
          </select>
        </div>

        <div className="space-y-1">
          <label htmlFor="mcp-server-endpoint" className="block text-[11px] font-medium text-muted-foreground">
            Command or Endpoint URL
          </label>
          <input
            id="mcp-server-endpoint"
            type="text"
            value={newServerEndpoint}
            onChange={(e) => {
              setNewServerEndpoint(e.target.value);
              if (formErrors.endpoint) setFormErrors((prev) => ({ ...prev, endpoint: undefined }));
            }}
            placeholder="Command or endpoint URL"
            aria-invalid={Boolean(formErrors.endpoint)}
            aria-describedby={formErrors.endpoint ? 'mcp-endpoint-error' : undefined}
            className="w-full px-3 py-2 rounded-lg bg-background border border-border text-xs text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          {formErrors.endpoint && (
            <p id="mcp-endpoint-error" role="alert" className="text-[11px] text-destructive">
              {formErrors.endpoint}
            </p>
          )}
        </div>

        <div className="md:pt-5">
          <button
            type="submit"
            disabled={isRegistering}
            className="w-full px-4 py-2 rounded-lg bg-primary hover:bg-primary/90 text-primary-foreground text-xs font-medium transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {isRegistering ? 'Registering…' : 'Register MCP Server'}
          </button>
        </div>
      </form>

      <div className="space-y-4 pb-6">
        {filteredServers.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border bg-card/50 p-8 text-center space-y-3">
            <p className="text-sm font-medium text-foreground">
              {searchQuery.trim()
                ? `No MCP servers match "${searchQuery.trim()}".`
                : 'No MCP servers registered yet.'}
            </p>
            <p className="text-xs text-muted-foreground">
              {searchQuery.trim()
                ? 'Try adjusting or clearing your filter query.'
                : 'Use the registration form above to connect a local or remote MCP server.'}
            </p>
            {searchQuery.trim() && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                className="px-3 py-1.5 rounded-lg border border-border bg-background hover:bg-accent text-xs font-medium text-foreground cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                Clear filter
              </button>
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
                    <h2 className="text-base font-semibold text-foreground break-words">{server.name}</h2>
                    <span className="text-[11px] font-mono px-2 py-0.5 rounded-md bg-muted text-muted-foreground border border-border">
                      {server.transport} · MCP {server.protocolVersion}
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
                  <p className="text-xs font-mono text-muted-foreground mt-1 truncate" title={server.endpointOrCommand}>
                    {server.endpointOrCommand}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2 shrink-0">
                  <button
                    type="button"
                    disabled={!server.enabled || pingingId === server.id}
                    onClick={() => pingServer(server.id)}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium border border-border bg-background text-foreground hover:bg-accent transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {pingingId === server.id ? 'Pinging…' : 'Ping Handshake'}
                  </button>
                  <button
                    type="button"
                    aria-pressed={server.enabled}
                    disabled={togglingServerId === server.id}
                    onClick={() => toggleServer(server.id)}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium border border-border bg-background text-foreground hover:bg-accent transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {server.enabled ? 'Disable Server' : 'Enable Server'}
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
                        const isUpdatingTool = updatingToolKey === rowKey;
                        return (
                          <React.Fragment key={tool.name}>
                            <tr className="hover:bg-accent/30 transition-colors">
                              <td className="py-2.5 pr-4 font-mono text-xs font-medium text-foreground whitespace-nowrap">{tool.name}</td>
                              <td className="py-2.5 pr-4 text-muted-foreground text-xs min-w-[200px]">{tool.description}</td>
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
                                <button
                                  type="button"
                                  aria-pressed={tool.requiresApproval}
                                  disabled={isUpdatingTool}
                                  onClick={() => toggleToolApprovalPolicy(server.id, tool.name)}
                                  className={`text-xs px-2.5 py-1 rounded-md border transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                                    tool.requiresApproval
                                      ? 'bg-amber-500/10 border-amber-500/30 text-amber-700 dark:text-amber-400'
                                      : 'bg-background border-border text-muted-foreground hover:text-foreground hover:bg-accent'
                                  }`}
                                >
                                  {tool.requiresApproval ? 'Approval Required' : 'Auto-Approve'}
                                </button>
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
