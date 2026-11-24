import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  FolderGit2,
  MessageSquare,
  Sparkles,
  ShieldAlert,
  FlaskConical,
  FileCheck,
  ListTodo,
  Wrench,
  Search,
  FileCode,
  X,
  CornerDownLeft,
  LayoutDashboard,
  PlusCircle,
  GitBranch,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import { useRepositories, useRepositoryFiles } from '../../hooks/useRepositories';
import { useTasks } from '../../hooks/useTasks';

interface CommandPaletteProps {
  /** When set, repository studios and files of this repository are offered too. */
  repoId?: string;
  isOpen: boolean;
  onClose: () => void;
}

type PaletteGroup = 'navigation' | 'studio' | 'repository' | 'task' | 'file';

interface PaletteItem {
  id: string;
  type: PaletteGroup;
  title: string;
  subtitle?: string;
  icon: typeof FolderGit2;
  /** Route to open. Every command is navigation, so items carry data instead of closures. */
  to: string;
}

const GROUP_LABELS: Record<PaletteGroup, string> = {
  navigation: 'Navigation',
  studio: 'Repository studios',
  repository: 'Repositories',
  task: 'Recent tasks',
  file: 'Files',
};

/** Studio route for "open this file here": stay in the current studio when it can show a file. */
function studioBaseFor(pathname: string, repoId: string): string {
  const base = `/app/repositories/${repoId}`;
  const match = pathname.match(/^\/app\/repositories\/[^/]+(?:\/([^/]+))?/);
  const segment = match?.[1];
  if (!segment) return base; // Explorer reads ?file= too
  // These studios read ?file=; the task planner does not, so fall back to Explain there.
  return ['chat', 'explain', 'bugs', 'tests', 'review'].includes(segment) ? `${base}/${segment}` : `${base}/explain`;
}

function CommandPaletteModal({ repoId, onClose }: { repoId?: string; onClose: () => void }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const { data: filesData } = useRepositoryFiles(repoId ?? '', 1, 100);
  const { data: reposData } = useRepositories(1, 50);
  const { data: tasksData } = useTasks({ page: 1, page_size: 20 });

  // Focus search input on mount; give focus back to whatever had it when the palette closes.
  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const timer = setTimeout(() => inputRef.current?.focus(), 40);
    return () => {
      clearTimeout(timer);
      previouslyFocused?.focus?.();
    };
  }, []);

  const navigationItems = useMemo<PaletteItem[]>(
    () => [
      { id: 'nav-dashboard', type: 'navigation', title: 'Dashboard', subtitle: 'Overview of repositories and tasks', icon: LayoutDashboard, to: '/app/dashboard' },
      { id: 'nav-repositories', type: 'navigation', title: 'Repositories', subtitle: 'Connect and manage GitHub repositories', icon: FolderGit2, to: '/app/repositories' },
      { id: 'nav-tasks', type: 'navigation', title: 'Tasks', subtitle: 'All development tasks', icon: ListTodo, to: '/app/tasks' },
      {
        id: 'nav-new-task',
        type: 'navigation',
        title: 'New Task',
        subtitle: repoId ? 'Start a development task for this repository' : 'Start a new development task',
        icon: PlusCircle,
        to: repoId ? `/app/tasks/new?repository_id=${encodeURIComponent(repoId)}` : '/app/tasks/new',
      },
      { id: 'nav-tools', type: 'navigation', title: 'Tools & MCP Integrations', subtitle: 'Inspect built-in MCP tool schemas and approval requirements', icon: Wrench, to: '/app/tools' },
    ],
    [repoId]
  );

  const studioItems = useMemo<PaletteItem[]>(() => {
    if (!repoId) return [];
    const base = `/app/repositories/${repoId}`;
    return [
      { id: 'studio-explorer', type: 'studio', title: 'Explorer', subtitle: 'Browse repository file tree and symbols', icon: FolderGit2, to: base },
      { id: 'studio-chat', type: 'studio', title: 'Chat Studio', subtitle: 'Ask questions grounded in codebase RAG context', icon: MessageSquare, to: `${base}/chat` },
      { id: 'studio-explain', type: 'studio', title: 'Explain Studio', subtitle: 'Deep code walkthrough and grounded citations', icon: Sparkles, to: `${base}/explain` },
      { id: 'studio-bugs', type: 'studio', title: 'Bug Hunter', subtitle: 'Triage vulnerabilities and inspect patch proposals', icon: ShieldAlert, to: `${base}/bugs` },
      { id: 'studio-tests', type: 'studio', title: 'Test Studio', subtitle: 'Generate scenario unit tests with path safety checks', icon: FlaskConical, to: `${base}/tests` },
      { id: 'studio-review', type: 'studio', title: 'Code Review Studio', subtitle: 'Inspect PR diffs, risk scorecards, and findings', icon: FileCheck, to: `${base}/review` },
      { id: 'studio-tasks', type: 'studio', title: 'Agent Tasks Studio', subtitle: 'Import GitHub issues, generate execution plans, and approve runs', icon: ListTodo, to: `${base}/tasks` },
    ];
  }, [repoId]);

  const repositoryItems = useMemo<PaletteItem[]>(
    () =>
      (reposData?.items ?? [])
        .filter((repo) => repo.id !== repoId)
        .map((repo) => ({
          id: `repo-${repo.id}`,
          type: 'repository' as const,
          title: repo.full_name || repo.name,
          subtitle: `${repo.language ?? 'repository'} · ${repo.sync_status.toLowerCase().replace('_', ' ')}`,
          icon: GitBranch,
          to: `/app/repositories/${repo.id}`,
        })),
    [reposData, repoId]
  );

  const taskItems = useMemo<PaletteItem[]>(
    () =>
      (tasksData?.items ?? []).map((task) => ({
        id: `task-${task.task_id}`,
        type: 'task' as const,
        title: task.title || task.task_id,
        subtitle: String(task.status).toLowerCase().replace(/_/g, ' '),
        icon: ListTodo,
        to: `/app/tasks/${task.task_id}`,
      })),
    [tasksData]
  );

  const fileItems = useMemo<PaletteItem[]>(() => {
    if (!repoId) return [];
    const base = studioBaseFor(location.pathname, repoId);
    return (filesData?.items ?? []).map((file) => ({
      id: `file-${file.id}`,
      type: 'file' as const,
      title: file.path,
      subtitle: `${file.language ?? 'file'} · ${file.size_bytes ? `${Math.max(1, Math.round(file.size_bytes / 1024))} KB` : 'file'}`,
      icon: FileCode,
      to: `${base}?file=${encodeURIComponent(file.path)}`,
    }));
  }, [filesData, location.pathname, repoId]);

  const filteredItems = useMemo(() => {
    const q = query.trim().toLowerCase();
    const matches = (item: PaletteItem) =>
      item.title.toLowerCase().includes(q) || Boolean(item.subtitle?.toLowerCase().includes(q));
    if (!q) {
      // Inside a repository the studios come first; elsewhere the global navigation does.
      const lead = repoId ? [...studioItems, ...navigationItems] : navigationItems;
      return [...lead, ...repositoryItems.slice(0, 5), ...taskItems.slice(0, 5), ...fileItems.slice(0, 15)];
    }
    const lead = repoId ? [...studioItems, ...navigationItems] : navigationItems;
    return [
      ...lead.filter(matches),
      ...repositoryItems.filter(matches).slice(0, 10),
      ...taskItems.filter(matches).slice(0, 10),
      ...fileItems.filter((f) => f.title.toLowerCase().includes(q)).slice(0, 20),
    ];
  }, [query, repoId, studioItems, navigationItems, repositoryItems, taskItems, fileItems]);

  // Data arrives asynchronously, so the list can shrink under the cursor — keep it in range.
  const activeIndex = filteredItems.length === 0 ? 0 : Math.min(selectedIndex, filteredItems.length - 1);

  // Keep the keyboard selection visible while arrowing through a long list.
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(`[data-palette-index="${activeIndex}"]`);
    el?.scrollIntoView?.({ block: 'nearest' });
  }, [activeIndex]);

  const runItem = useCallback(
    (item: PaletteItem | undefined) => {
      if (!item) return;
      navigate(item.to);
      onClose();
    },
    [navigate, onClose]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      const count = filteredItems.length;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (count) setSelectedIndex((activeIndex + 1) % count);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (count) setSelectedIndex((activeIndex - 1 + count) % count);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        runItem(filteredItems[activeIndex]);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    },
    [filteredItems, activeIndex, runItem, onClose]
  );

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Command Palette"
      className="fixed inset-0 z-50 flex items-start justify-center pt-16 sm:pt-24 px-4 bg-background/80 backdrop-blur-sm animate-in fade-in duration-150"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl rounded-xl border border-border/80 bg-card shadow-2xl overflow-hidden flex flex-col max-h-[75vh]"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        {/* Search header */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border/60 bg-muted/20">
          <Search className="h-4 w-4 text-muted-foreground shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            placeholder={
              repoId
                ? 'Type a studio name, page, repository, task, or file path to jump...'
                : 'Type a studio name, page, repository, or task to jump...'
            }
            aria-label="Search commands"
            aria-controls="command-palette-results"
            aria-activedescendant={filteredItems[activeIndex] ? `palette-item-${activeIndex}` : undefined}
            className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground/70 focus:outline-hidden"
          />
          {query && (
            <button
              onClick={() => setQuery('')}
              className="p-1 rounded text-muted-foreground hover:text-foreground"
              aria-label="Clear query"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
          <kbd className="hidden sm:inline-flex items-center px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground bg-accent rounded border border-border">
            ESC
          </kbd>
        </div>

        {/* Results list */}
        <div
          ref={listRef}
          id="command-palette-results"
          role="listbox"
          className="overflow-y-auto p-2 max-h-[420px]"
        >
          {filteredItems.length === 0 ? (
            <div className="py-10 text-center text-xs text-muted-foreground">
              No pages, studios or files matching &ldquo;{query}&rdquo;
            </div>
          ) : (
            filteredItems.map((item, idx) => {
              const Icon = item.icon;
              const isSelected = idx === activeIndex;
              const showHeader = idx === 0 || filteredItems[idx - 1].type !== item.type;
              return (
                <div key={item.id}>
                  {showHeader && (
                    <div className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                      {GROUP_LABELS[item.type]}
                    </div>
                  )}
                  <button
                    id={`palette-item-${idx}`}
                    role="option"
                    aria-selected={isSelected}
                    data-palette-index={idx}
                    onClick={() => runItem(item)}
                    onMouseEnter={() => setSelectedIndex(idx)}
                    className={cn(
                      'w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left text-xs transition-colors',
                      isSelected
                        ? 'bg-primary/10 text-primary border border-primary/30'
                        : 'hover:bg-accent/50 text-foreground border border-transparent'
                    )}
                  >
                    <div
                      className={cn(
                        'p-1.5 rounded-md shrink-0',
                        item.type === 'file' ? 'bg-muted text-muted-foreground' : 'bg-primary/10 text-primary'
                      )}
                    >
                      <Icon className="h-4 w-4" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="font-medium truncate">{item.title}</div>
                      {item.subtitle && (
                        <div className="text-[11px] text-muted-foreground truncate">{item.subtitle}</div>
                      )}
                    </div>
                    {isSelected && (
                      <div className="flex items-center gap-1 text-[11px] text-primary shrink-0">
                        <span>Jump</span>
                        <CornerDownLeft className="h-3 w-3" />
                      </div>
                    )}
                  </button>
                </div>
              );
            })
          )}
        </div>

        {/* Footer shortcuts */}
        <div className="px-4 py-2 bg-muted/30 border-t border-border/40 flex items-center justify-between text-[11px] text-muted-foreground">
          <div className="flex items-center gap-3">
            <span>
              <kbd className="font-mono bg-accent px-1 py-0.5 rounded border border-border">↑</kbd>{' '}
              <kbd className="font-mono bg-accent px-1 py-0.5 rounded border border-border">↓</kbd> navigate
            </span>
            <span>
              <kbd className="font-mono bg-accent px-1 py-0.5 rounded border border-border">↵</kbd> select
            </span>
          </div>
          <span className="font-mono text-[10px]">Ctrl/⌘ + K</span>
        </div>
      </div>
    </div>
  );
}

export function CommandPalette({ repoId, isOpen, onClose }: CommandPaletteProps) {
  if (!isOpen) return null;
  return <CommandPaletteModal repoId={repoId} onClose={onClose} />;
}
