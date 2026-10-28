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
  Clock,
  Search,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import type { Repository } from '../../types/api';
import { useSyncRepository, syncProgressFromStatus } from '../../hooks/useRepositories';

interface StudioSubNavProps {
  repository?: Repository;
  isLoading?: boolean;
  onOpenCommandPalette?: () => void;
}

export function StudioSubNav({ repository, isLoading, onOpenCommandPalette }: StudioSubNavProps) {
  const { id } = useParams<{ id: string }>();
  const repoId = id ?? repository?.id ?? '';
  const syncMutation = useSyncRepository();

  const syncStatus = repository?.sync_status;
  const syncProgress = syncProgressFromStatus(syncStatus ?? 'NOT_SYNCED');
  const isSyncing = syncStatus === 'SYNCING' || syncMutation.isPending;

  const repoName = repository?.name ?? repository?.full_name?.split('/')[1] ?? (isLoading ? 'Loading...' : 'Repository');
  const repoOrg = repository?.full_name?.split('/')[0] ?? '';

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
      badge: 'RAG',
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
      badge: 'W3',
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
            <div className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-accent text-[11px] font-mono text-muted-foreground border border-border">
              <GitBranch className="h-3 w-3" />
              <span>{repository.default_branch}</span>
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

          {syncStatus && (
            <div className="hidden md:flex items-center gap-1.5 text-xs text-muted-foreground">
              {syncStatus === 'SYNCED' ? (
                <span className="inline-flex items-center gap-1 text-emerald-500 font-mono text-[11px]">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  Indexed
                </span>
              ) : isSyncing ? (
                <span className="inline-flex items-center gap-1.5 text-amber-500 font-mono text-[11px]">
                  <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                  {syncProgress.label}
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 text-muted-foreground font-mono text-[11px]">
                  <Clock className="h-3.5 w-3.5" />
                  {syncProgress.label}
                </span>
              )}
            </div>
          )}

          <button
            onClick={() => syncMutation.mutate(repoId)}
            disabled={isSyncing}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md border border-border bg-background hover:bg-accent text-foreground disabled:opacity-50 transition-colors shadow-xs"
            title="Trigger repository re-index"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', isSyncing && 'animate-spin text-primary')} />
            <span className="hidden sm:inline">{isSyncing ? 'Syncing...' : 'Sync'}</span>
          </button>
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
