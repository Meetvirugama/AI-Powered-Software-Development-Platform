import { useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Brain,
  X,
  Plus,
  Search,
  CheckCircle,
  AlertTriangle,
  Lightbulb,
  Pin,
  Trash2,
  Edit2,
  Copy,
  Check,
  RefreshCw,
  Layers,
  Sparkles,
} from 'lucide-react';
import {
  listMemories,
  updateMemory,
  deleteMemory,
  pinArchitecturalRule,
  listMCPResources,
} from '../../services/memory';
import { LoadingSpinner } from '../shared/LoadingSpinner';
import { cn } from '../../lib/utils';
import type {
  MemoryType,
  MemoryStatus,
} from '../../types/memory';

export interface ProjectMemoryPanelProps {
  isOpen: boolean;
  onClose: () => void;
  repositoryId: string;
}

type TabType = 'all' | 'rule' | 'decision' | 'task_summary' | 'failure' | 'mcp';

export function ProjectMemoryPanel({
  isOpen,
  onClose,
  repositoryId,
}: ProjectMemoryPanelProps) {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<TabType>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [showPinForm, setShowPinForm] = useState(false);
  const [newRuleText, setNewRuleText] = useState('');
  const [editingEntryId, setEditingEntryId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState('');
  const [editStatus, setEditStatus] = useState<MemoryStatus>('active');
  const [copiedUri, setCopiedUri] = useState<string | null>(null);

  // Queries
  const {
    data: memoryData,
    isLoading: memoriesLoading,
    refetch: refetchMemories,
  } = useQuery({
    queryKey: ['project-memories', repositoryId, activeTab, searchQuery],
    queryFn: () =>
      listMemories(repositoryId, {
        query: searchQuery || undefined,
        type: activeTab !== 'all' && activeTab !== 'mcp' ? activeTab : undefined,
        page_size: 100,
      }),
    enabled: isOpen && activeTab !== 'mcp',
  });

  const {
    data: mcpData,
    isLoading: mcpLoading,
  } = useQuery({
    queryKey: ['mcp-resources', repositoryId],
    queryFn: () => listMCPResources(repositoryId),
    enabled: isOpen && activeTab === 'mcp',
  });

  // Mutations
  const pinRuleMutation = useMutation({
    mutationFn: (rule: string) =>
      pinArchitecturalRule(repositoryId, { rule, source: 'user_pinned' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project-memories', repositoryId] });
      queryClient.invalidateQueries({ queryKey: ['mcp-resources', repositoryId] });
      setNewRuleText('');
      setShowPinForm(false);
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, content, status }: { id: string; content: string; status: MemoryStatus }) =>
      updateMemory(repositoryId, id, { content, status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project-memories', repositoryId] });
      queryClient.invalidateQueries({ queryKey: ['mcp-resources', repositoryId] });
      setEditingEntryId(null);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteMemory(repositoryId, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project-memories', repositoryId] });
      queryClient.invalidateQueries({ queryKey: ['mcp-resources', repositoryId] });
    },
  });

  const entries = useMemo(() => memoryData?.items ?? [], [memoryData]);

  if (!isOpen) return null;

  const handleCopyUri = (uri: string) => {
    navigator.clipboard.writeText(uri);
    setCopiedUri(uri);
    setTimeout(() => setCopiedUri(null), 2000);
  };

  const getTypeBadge = (type: MemoryType) => {
    switch (type) {
      case 'rule':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-purple-500/10 text-purple-400 border border-purple-500/20">
            <Pin className="h-2.5 w-2.5" /> Rule
          </span>
        );
      case 'decision':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-blue-500/10 text-blue-400 border border-blue-500/20">
            <Lightbulb className="h-2.5 w-2.5" /> Decision
          </span>
        );
      case 'task_summary':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <CheckCircle className="h-2.5 w-2.5" /> Task Summary
          </span>
        );
      case 'failure':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-rose-500/10 text-rose-400 border border-rose-500/20">
            <AlertTriangle className="h-2.5 w-2.5" /> Failure
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-muted text-muted-foreground border border-border">
            {type}
          </span>
        );
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Project Memory & Knowledge"
      className="fixed inset-0 z-50 flex justify-end bg-background/80 backdrop-blur-xs animate-in fade-in duration-200"
    >
      <div className="w-full max-w-2xl bg-card border-l border-border h-full flex flex-col shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="p-4 border-b border-border flex items-center justify-between shrink-0 bg-muted/20">
          <div className="flex items-center gap-2.5">
            <div className="h-8 w-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
              <Brain className="h-4 w-4" />
            </div>
            <div>
              <h2 className="font-semibold text-sm text-foreground flex items-center gap-1.5">
                Project Memory & Knowledge
                <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-primary/10 text-primary border border-primary/20">
                  F36
                </span>
              </h2>
              <p className="text-xs text-muted-foreground">
                Episodic summaries, failure diagnoses, pinned rules & MCP resources
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => refetchMemories()}
              className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
              title="Refresh memories"
              aria-label="Refresh memories"
            >
              <RefreshCw className="h-4 w-4" />
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
              title="Close panel"
              aria-label="Close panel"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Toolbar: Navigation Tabs & Search */}
        <div className="p-3 border-b border-border/80 flex flex-col gap-2.5 shrink-0 bg-background/50">
          <div className="flex items-center justify-between gap-2 overflow-x-auto pb-1">
            <div className="flex items-center gap-1 text-xs">
              {(
                [
                  { id: 'all', label: 'All' },
                  { id: 'rule', label: 'Rules' },
                  { id: 'decision', label: 'Decisions' },
                  { id: 'task_summary', label: 'Summaries' },
                  { id: 'failure', label: 'Failures' },
                  { id: 'mcp', label: 'MCP Resources' },
                ] as const
              ).map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={cn(
                    'px-2.5 py-1 rounded-md font-medium transition-colors text-xs whitespace-nowrap',
                    activeTab === tab.id
                      ? 'bg-primary text-primary-foreground shadow-2xs'
                      : 'text-muted-foreground hover:text-foreground hover:bg-muted'
                  )}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            <button
              onClick={() => setShowPinForm((prev) => !prev)}
              className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md bg-purple-500/10 text-purple-400 hover:bg-purple-500/20 border border-purple-500/30 transition-colors shrink-0"
              title="Pin a new architectural rule"
            >
              <Plus className="h-3 w-3" />
              <span>Pin Rule</span>
            </button>
          </div>

          {activeTab !== 'mcp' && (
            <div className="relative">
              <Search className="h-3.5 w-3.5 absolute left-2.5 top-2.5 text-muted-foreground pointer-events-none" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search memories by keyword, failure diagnosis, or source..."
                className="w-full pl-8 pr-3 py-1.5 text-xs rounded-md bg-muted/30 border border-border text-foreground placeholder:text-muted-foreground focus:outline-hidden focus:border-primary transition-colors"
              />
            </div>
          )}
        </div>

        {/* Pin Rule Input Form Drawer */}
        {showPinForm && (
          <div className="p-3 border-b border-border bg-purple-500/5 space-y-2 animate-in slide-in-from-top-2 duration-150 shrink-0">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-purple-300 flex items-center gap-1">
                <Pin className="h-3 w-3" /> Pin Architectural Convention or Rule
              </span>
              <button
                onClick={() => setShowPinForm(false)}
                className="text-muted-foreground hover:text-foreground"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
            <textarea
              rows={2}
              value={newRuleText}
              onChange={(e) => setNewRuleText(e.target.value)}
              placeholder="e.g. All Redis locks must specify an explicit TTL; never write raw secrets to stdout."
              className="w-full p-2 text-xs rounded-md bg-background border border-border text-foreground placeholder:text-muted-foreground focus:outline-hidden focus:border-primary"
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowPinForm(false)}
                className="px-2.5 py-1 text-xs rounded border border-border text-muted-foreground hover:text-foreground"
              >
                Cancel
              </button>
              <button
                aria-label="Confirm Pin Rule"
                onClick={() => {
                  if (newRuleText.trim()) {
                    pinRuleMutation.mutate(newRuleText.trim());
                  }
                }}
                disabled={!newRuleText.trim() || pinRuleMutation.isPending}
                className="px-3 py-1 text-xs rounded font-medium bg-purple-600 text-white hover:bg-purple-500 disabled:opacity-50"
              >
                {pinRuleMutation.isPending ? 'Pinning...' : 'Pin Rule'}
              </button>
            </div>
          </div>
        )}

        {/* Content Area */}
        <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-3">
          {activeTab === 'mcp' ? (
            mcpLoading ? (
              <div className="flex h-40 items-center justify-center">
                <LoadingSpinner size="md" label="Loading MCP resources..." />
              </div>
            ) : !mcpData?.resources.length ? (
              <div className="text-center py-12 text-muted-foreground text-xs">
                No MCP resources found.
              </div>
            ) : (
              <div className="space-y-4">
                <div className="rounded-lg border border-border bg-muted/20 p-3 text-xs text-muted-foreground space-y-1">
                  <div className="font-semibold text-foreground flex items-center gap-1.5">
                    <Sparkles className="h-3.5 w-3.5 text-primary" />
                    Model Context Protocol (MCP 2025-11-25) Integration
                  </div>
                  <p>
                    External MCP clients and subagents can read repository episodic memory natively using these resource URIs.
                  </p>
                </div>

                {mcpData.resources.map((res) => (
                  <div
                    key={res.uri}
                    className="rounded-lg border border-border bg-card p-3 space-y-2 hover:border-primary/40 transition-colors shadow-2xs"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <h4 className="font-semibold text-xs text-foreground flex items-center gap-1.5">
                          {res.name}
                          <span className="px-1.5 py-0.2 rounded text-[10px] font-mono bg-muted text-muted-foreground">
                            {res.entries_count} entries
                          </span>
                        </h4>
                        <p className="text-[11px] text-muted-foreground mt-0.5">
                          {res.description}
                        </p>
                      </div>
                      <button
                        onClick={() => handleCopyUri(res.uri)}
                        className="inline-flex items-center gap-1 px-2 py-1 text-[11px] rounded border border-border bg-muted/40 hover:bg-accent text-foreground transition-colors shrink-0"
                        title="Copy MCP Resource URI"
                      >
                        {copiedUri === res.uri ? (
                          <>
                            <Check className="h-3 w-3 text-emerald-400" />
                            <span>Copied</span>
                          </>
                        ) : (
                          <>
                            <Copy className="h-3 w-3 text-muted-foreground" />
                            <span>Copy URI</span>
                          </>
                        )}
                      </button>
                    </div>

                    <div className="bg-muted/40 rounded p-2 text-[11px] font-mono text-muted-foreground select-all break-all border border-border/60">
                      {res.uri}
                    </div>

                    <details className="text-xs">
                      <summary className="cursor-pointer text-[11px] text-primary hover:underline">
                        Preview Markdown Content
                      </summary>
                      <pre className="mt-2 p-2.5 rounded bg-muted/60 text-[11px] font-mono text-foreground whitespace-pre-wrap max-h-48 overflow-y-auto border border-border">
                        {res.text}
                      </pre>
                    </details>
                  </div>
                ))}
              </div>
            )
          ) : memoriesLoading ? (
            <div className="flex h-40 items-center justify-center">
              <LoadingSpinner size="md" label="Loading project memories..." />
            </div>
          ) : entries.length === 0 ? (
            <div className="text-center py-16 space-y-2 text-muted-foreground text-xs">
              <Layers className="h-8 w-8 mx-auto text-muted-foreground/40" />
              <div className="font-medium text-foreground">No memory entries found</div>
              <p className="max-w-xs mx-auto">
                {searchQuery
                  ? 'No memories match your search filter.'
                  : 'Automated task summaries, failure diagnoses, and pinned rules will appear here.'}
              </p>
            </div>
          ) : (
            entries.map((entry) => (
              <div
                key={entry.id}
                className="rounded-lg border border-border bg-card p-3 space-y-2 hover:border-border/80 transition-colors shadow-2xs"
              >
                {/* Entry Header */}
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    {getTypeBadge(entry.type)}
                    <span
                      className={cn(
                        'text-[10px] font-mono px-1.5 py-0.2 rounded border',
                        entry.status === 'active'
                          ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                          : entry.status === 'stale'
                          ? 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                          : 'bg-muted text-muted-foreground border-border'
                      )}
                    >
                      {entry.status}
                    </span>
                  </div>

                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => {
                        setEditingEntryId(entry.id);
                        setEditContent(entry.content);
                        setEditStatus(entry.status);
                      }}
                      className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                      title="Edit memory"
                      aria-label="Edit memory"
                    >
                      <Edit2 className="h-3 w-3" />
                    </button>
                    <button
                      onClick={() => {
                        if (confirm('Delete this project memory entry?')) {
                          deleteMutation.mutate(entry.id);
                        }
                      }}
                      className="p-1 rounded text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
                      title="Delete memory"
                      aria-label="Delete memory"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                </div>

                {/* Inline Editing */}
                {editingEntryId === entry.id ? (
                  <div className="space-y-2 pt-1">
                    <textarea
                      rows={3}
                      value={editContent}
                      onChange={(e) => setEditContent(e.target.value)}
                      className="w-full p-2 text-xs rounded bg-background border border-border text-foreground"
                    />
                    <div className="flex items-center justify-between">
                      <select
                        value={editStatus}
                        onChange={(e) => setEditStatus(e.target.value as MemoryStatus)}
                        className="text-xs bg-background border border-border rounded px-2 py-1 text-foreground"
                      >
                        <option value="active">Active</option>
                        <option value="stale">Stale</option>
                        <option value="archived">Archived</option>
                      </select>
                      <div className="flex gap-1.5">
                        <button
                          onClick={() => setEditingEntryId(null)}
                          className="px-2 py-1 text-xs rounded border border-border text-muted-foreground hover:text-foreground"
                        >
                          Cancel
                        </button>
                        <button
                          onClick={() => {
                            updateMutation.mutate({
                              id: entry.id,
                              content: editContent,
                              status: editStatus,
                            });
                          }}
                          className="px-2.5 py-1 text-xs rounded bg-primary text-primary-foreground hover:bg-primary/90"
                        >
                          Save
                        </button>
                      </div>
                    </div>
                  </div>
                ) : (
                  <p className="text-xs text-foreground leading-relaxed whitespace-pre-wrap">
                    {entry.content}
                  </p>
                )}

                {/* Footer metadata */}
                <div className="flex items-center justify-between text-[10px] text-muted-foreground pt-1 border-t border-border/40 font-mono">
                  <span className="truncate max-w-[200px]" title={entry.source}>
                    Source: {entry.source}
                  </span>
                  <span>{new Date(entry.created_at).toLocaleDateString()}</span>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
