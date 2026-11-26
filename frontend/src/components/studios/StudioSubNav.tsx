import { useEffect, useMemo, useRef, useState } from 'react';
import { NavLink, useParams, Link } from 'react-router-dom';
import {
  FolderGit2,
  MessageSquare,
  Sparkles,
  ShieldAlert,
  FlaskConical,
  FileCheck,
  ListChecks,
  ArrowLeft,
  RefreshCw,
  GitBranch,
  CheckCircle2,
  Search,
  ChevronDown,
  Check,
  Lock,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import type { Repository } from '../../types/api';
import {
  useRepositoryBranches,
  useSwitchRepositoryBranch,
  useSyncRepository,
} from '../../hooks/useRepositories';

interface StudioSubNavProps {
  repository?: Repository;
  isLoading?: boolean;
  onOpenCommandPalette?: () => void;
}

export function StudioSubNav({ repository, isLoading, onOpenCommandPalette }: StudioSubNavProps) {
  const { id } = useParams<{ id: string }>();
  const repoId = id ?? repository?.id ?? '';
  const syncMutation = useSyncRepository();
  const switchBranchMutation = useSwitchRepositoryBranch();

  const [isBranchMenuOpen, setIsBranchMenuOpen] = useState(false);
  const [branchSearch, setBranchSearch] = useState('');
  const branchMenuRef = useRef<HTMLDivElement>(null);

  const {
    data: branches = [],
    isLoading: branchesLoading,
    isError: branchesError,
    refetch: refetchBranches,
  } = useRepositoryBranches(repoId || undefined, { enabled: isBranchMenuOpen && Boolean(repoId) });

  const filteredBranches = useMemo(() => {
    const q = branchSearch.trim().toLowerCase();
    if (!q) return branches;
    return branches.filter((b) => b.name.toLowerCase().includes(q));
  }, [branches, branchSearch]);

  useEffect(() => {
    if (!isBranchMenuOpen) return;
    function handleOutsideClick(event: MouseEvent) {
      if (branchMenuRef.current && !branchMenuRef.current.contains(event.target as Node)) {
        setIsBranchMenuOpen(false);
      }
    }
    function handleEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setIsBranchMenuOpen(false);
      }
    }
    document.addEventListener('mousedown', handleOutsideClick);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('mousedown', handleOutsideClick);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [isBranchMenuOpen]);

  const syncStatus = repository?.sync_status;
  const isSyncing = syncStatus === 'SYNCING' || syncMutation.isPending || switchBranchMutation.isPending;

  const repoName = repository?.name ?? repository?.full_name?.split('/')[1] ?? (isLoading ? 'Loading...' : 'Repository');
  const repoOrg = repository?.full_name?.split('/')[0] ?? '';

  function handleSelectBranch(branchName: string) {
    setIsBranchMenuOpen(false);
    setBranchSearch('');
    if (!repoId || branchName === repository?.default_branch) return;
    switchBranchMutation.mutate({ id: repoId, branch: branchName });
  }

  const navItems = [
    {
      to: `/app/repositories/${repoId}`,
      end: true,
      label: 'Explorer',
      icon: FolderGit2,
      badge: repository?.file_count ? `${repository.file_count}` : undefined,
    },
    {
      to: `/app/repositories/${repoId}/chat`,
      label: 'Chat',
      icon: MessageSquare,
      badge: undefined,
    },
    {
      to: `/app/repositories/${repoId}/explain`,
      label: 'Explain',
      icon: Sparkles,
      badge: undefined,
    },
    {
      to: `/app/repositories/${repoId}/bugs`,
      label: 'Bug Hunter',
      icon: ShieldAlert,
      badge: undefined,
    },
    {
      to: `/app/repositories/${repoId}/tests`,
      label: 'Test Studio',
      icon: FlaskConical,
      badge: undefined,
    },
    {
      to: `/app/repositories/${repoId}/review`,
      label: 'Code Review',
      icon: FileCheck,
      badge: undefined,
    },
    {
      to: `/app/repositories/${repoId}/tasks`,
      label: 'Task Planner',
      icon: ListChecks,
      badge: undefined,
    },
  ];

  return (
    <header className="flex-shrink-0 bg-card/80 backdrop-blur-md border-b border-border z-10 select-none">
      {/* Top row: Repo breadcrumbs, Sync Status, Actions */}
      <div className="h-12 px-4 flex items-center justify-between gap-3 border-b border-border/50">
        <div className="flex items-center gap-2.5 min-w-0">
          <Link
            to="/app/repositories"
            className="inline-flex items-center justify-center p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
            title="Back to all repositories"
            aria-label="Back to repositories"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>

          <div className="flex items-center gap-1.5 min-w-0 text-sm font-medium">
            {repoOrg && (
              <>
                <span className="text-muted-foreground truncate">{repoOrg}</span>
                <span className="text-muted-foreground/60">/</span>
              </>
            )}
            <span className="text-foreground font-semibold truncate">{repoName}</span>
          </div>

          {repository?.default_branch && (
            <div ref={branchMenuRef} className="relative">
              <button
                type="button"
                onClick={() => setIsBranchMenuOpen((prev) => !prev)}
                disabled={switchBranchMutation.isPending}
                aria-haspopup="listbox"
                aria-expanded={isBranchMenuOpen}
                aria-label={`Switch branch (current: ${repository.default_branch})`}
                title="Switch active repository branch"
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-accent hover:bg-accent/80 text-[11px] font-mono text-muted-foreground hover:text-foreground border border-border transition-colors cursor-pointer disabled:opacity-60"
              >
                {switchBranchMutation.isPending ? (
                  <RefreshCw className="h-3 w-3 animate-spin" />
                ) : (
                  <GitBranch className="h-3 w-3" />
                )}
                <span className="max-w-[140px] truncate">{repository.default_branch}</span>
                <ChevronDown className="h-3 w-3 opacity-70" />
              </button>

              {isBranchMenuOpen && (
                <div
                  role="listbox"
                  aria-label="Repository branches"
                  className="absolute left-0 mt-1.5 w-64 rounded-xl border border-border bg-card shadow-lg z-50 overflow-hidden"
                >
                  <div className="px-3 py-2 border-b border-border/60 flex items-center justify-between">
                    <span className="text-[11px] font-semibold text-foreground">Switch branch</span>
                    <span className="text-[10px] text-muted-foreground">Re-indexes workspace</span>
                  </div>

                  {branches.length > 6 && (
                    <div className="p-2 border-b border-border/60">
                      <input
                        type="search"
                        value={branchSearch}
                        onChange={(e) => setBranchSearch(e.target.value)}
                        placeholder="Filter branches…"
                        aria-label="Filter branches"
                        autoFocus
                        className="w-full rounded-md border border-border bg-background px-2.5 py-1 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                      />
                    </div>
                  )}

                  {switchBranchMutation.isError && (
                    <div className="px-3 py-2 text-[11px] text-destructive bg-destructive/5 border-b border-destructive/20">
                      {switchBranchMutation.error?.message || 'Failed to switch branch.'}
                    </div>
                  )}

                  <div className="max-h-60 overflow-y-auto py-1">
                    {branchesLoading ? (
                      <div className="flex items-center gap-2 px-3 py-3 text-xs text-muted-foreground">
                        <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                        <span>Loading branches…</span>
                      </div>
                    ) : branchesError ? (
                      <div className="px-3 py-2.5 space-y-2 text-xs text-muted-foreground">
                        <p>Could not fetch branches from GitHub.</p>
                        <button
                          type="button"
                          onClick={() => refetchBranches()}
                          className="inline-flex items-center gap-1 text-primary hover:underline font-medium cursor-pointer"
                        >
                          <RefreshCw className="h-3 w-3" />
                          Retry
                        </button>
                      </div>
                    ) : filteredBranches.length === 0 ? (
                      <div className="px-3 py-3 text-xs text-muted-foreground">
                        No matching branches found.
                      </div>
                    ) : (
                      filteredBranches.map((branch) => {
                        const isCurrent = branch.name === repository.default_branch;
                        return (
                          <button
                            key={branch.name}
                            type="button"
                            role="option"
                            aria-selected={isCurrent}
                            onClick={() => handleSelectBranch(branch.name)}
                            className={cn(
                              'w-full flex items-center justify-between gap-2 px-3 py-1.5 text-left text-xs transition-colors cursor-pointer',
                              isCurrent
                                ? 'bg-primary/10 text-primary font-medium'
                                : 'text-foreground hover:bg-accent',
                            )}
                          >
                            <span className="flex items-center gap-1.5 min-w-0 font-mono">
                              <Check
                                className={cn(
                                  'h-3.5 w-3.5 shrink-0',
                                  isCurrent ? 'opacity-100' : 'opacity-0',
                                )}
                              />
                              <span className="truncate">{branch.name}</span>
                            </span>
                            {branch.protected && (
                              <Lock
                                className="h-3 w-3 shrink-0 text-muted-foreground"
                                aria-label="Protected branch"
                              />
                            )}
                          </button>
                        );
                      })
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right action bar: Index Status & Sync Button */}
        <div className="flex items-center gap-2.5 shrink-0">
          {onOpenCommandPalette && (
            <button
              onClick={onOpenCommandPalette}
              className="hidden sm:inline-flex items-center gap-2 px-2.5 py-1 text-xs text-muted-foreground bg-accent/60 hover:bg-accent hover:text-foreground border border-border rounded-md transition-colors shadow-2xs"
              title="Open Command Palette (Cmd/Ctrl + K)"
            >
              <Search className="h-3.5 w-3.5" />
              <span className="text-[11px]">Jump to...</span>
              <kbd className="inline-flex items-center gap-0.5 px-1 py-0.2 rounded bg-background text-[10px] font-mono border border-border text-muted-foreground">
                ⌘K
              </kbd>
            </button>
          )}

          {/* Canonical Index / Sync Status & Action */}
          {isSyncing ? (
            <div
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-500/10 border border-amber-500/25 text-amber-700 dark:text-amber-400 text-xs font-medium"
              title="Repository synchronization in progress"
            >
              <RefreshCw className="h-3.5 w-3.5 animate-spin" />
              <span>Syncing…</span>
            </div>
          ) : syncStatus === 'SYNCED' ? (
            <div className="flex items-center gap-1.5">
              <span className="hidden md:inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/25 text-emerald-700 dark:text-emerald-400 text-[11px] font-medium">
                <CheckCircle2 className="h-3 w-3" />
                Indexed
              </span>
              <button
                onClick={() => syncMutation.mutate(repoId)}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md border border-border bg-background hover:bg-accent text-foreground transition-colors cursor-pointer"
                title="Trigger repository re-index"
                aria-label="Re-index repository"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                <span>Sync</span>
              </button>
            </div>
          ) : syncStatus === 'FAILED' ? (
            <div className="flex items-center gap-1.5">
              <span
                className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-destructive/10 border border-destructive/20 text-destructive text-[11px] font-medium max-w-[260px]"
                title={repository?.last_sync_error ?? 'The last synchronization failed.'}
              >
                <span className="truncate">
                  {repository?.last_sync_error ? `Failed: ${repository.last_sync_error}` : 'Failed'}
                </span>
              </span>
              <button
                onClick={() => syncMutation.mutate({ id: repoId, force: true })}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md bg-destructive text-destructive-foreground hover:bg-destructive/90 transition-colors shadow-2xs"
                title="Retry repository sync"
                aria-label="Retry sync"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                <span>Retry</span>
              </button>
            </div>
          ) : (
            <button
              onClick={() => syncMutation.mutate(repoId)}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors shadow-2xs"
              title="Start repository indexing"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              <span>Sync</span>
            </button>
          )}
        </div>
      </div>

      {/* Bottom row: Antigravity-style Studio Tabs */}
      <nav className="flex items-center px-4 overflow-x-auto no-scrollbar gap-1">
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  'relative flex items-center gap-2 px-3 py-2 text-xs font-medium transition-colors border-b-2 whitespace-nowrap',
                  isActive
                    ? 'border-primary text-primary font-semibold'
                    : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'
                )
              }
            >
              <Icon className="h-3.5 w-3.5 shrink-0" />
              <span>{item.label}</span>
              {item.badge && (
                <span
                  className={cn(
                    'px-1.5 py-0.2 rounded text-[10px] font-mono leading-none',
                    item.badge === 'RAG' || item.badge === 'W3'
                      ? 'bg-primary/10 text-primary border border-primary/20'
                      : 'bg-muted text-muted-foreground'
                  )}
                >
                  {item.badge}
                </span>
              )}
            </NavLink>
          );
        })}
      </nav>
    </header>
  );
}
