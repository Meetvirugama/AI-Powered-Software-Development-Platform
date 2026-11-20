import { Suspense, useEffect, type ReactNode } from 'react';
import { Outlet, NavLink, useNavigate, useLocation, matchPath } from 'react-router-dom';
import { useAppStore } from '../stores/useAppStore';
import { useAuth } from '../hooks/useAuth';
import { useRealtimeRepositories } from '../hooks/useRealtimeRepositories';
import { ErrorBoundary } from '../components/shared/ErrorBoundary';
import { LoadingSpinner } from '../components/shared/LoadingSpinner';
import { CommandPalette } from '../components/studios/CommandPalette';
import { Menu, LayoutDashboard, FolderGit2, LogOut, Terminal, Cpu, ListTodo, Wrench, Search } from 'lucide-react';
import { cn } from '../lib/utils';

export function AppLayout() {
  const sidebarOpen = useAppStore((state) => state.sidebarOpen);
  const toggleSidebar = useAppStore((state) => state.toggleSidebar);
  const commandPaletteOpen = useAppStore((state) => state.commandPaletteOpen);
  const setCommandPaletteOpen = useAppStore((state) => state.setCommandPaletteOpen);
  const toggleCommandPalette = useAppStore((state) => state.toggleCommandPalette);
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  // Maintain the SSE connection for the duration of the authenticated session.
  useRealtimeRepositories();

  // Repository workspace (and its id) — used for the full-bleed layout and repo-aware palette.
  const repoMatch = matchPath({ path: '/app/repositories/:id/*' }, location.pathname);
  const activeRepoId = repoMatch?.params.id;
  const isRepositoryWorkspace = Boolean(activeRepoId);

  // Global Ctrl/Cmd+K: command-based navigation from every page, not only inside a repository.
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && !e.altKey && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        toggleCommandPalette();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [toggleCommandPalette]);

  // Close the palette whenever the route changes (e.g. browser back button).
  useEffect(() => {
    setCommandPaletteOpen(false);
  }, [location.pathname, setCommandPaletteOpen]);


  async function handleLogout() {
    try {
      await logout();
    } finally {
      navigate('/login', { replace: true });
    }
  }

  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      {/* ------------------------------------------------------------------ */}
      {/* Sidebar                                                              */}
      {/* ------------------------------------------------------------------ */}
      <aside
        className={cn(
          'flex flex-col flex-shrink-0 bg-card border-r border-border transition-all duration-300 z-20',
          sidebarOpen ? 'w-64' : 'w-16'
        )}
      >
        {/* Sidebar brand */}
        <div className="h-14 flex items-center px-4 border-b border-border gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 border border-primary/20 text-primary shrink-0">
            <Cpu className="h-4 w-4" />
          </div>
          {sidebarOpen && (
            <div className="min-w-0">
              <span className="font-semibold text-sm text-foreground tracking-tight block truncate">Code Intelligence</span>
              <span className="text-[10px] text-muted-foreground uppercase font-mono block">Workbench</span>
            </div>
          )}
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto py-4 px-2 space-y-1">
          <SidebarLink
            to="/app/dashboard"
            icon={<LayoutDashboard className="h-4 w-4 flex-shrink-0" />}
            label="Dashboard"
            collapsed={!sidebarOpen}
          />
          <SidebarLink
            to="/app/repositories"
            icon={<FolderGit2 className="h-4 w-4 flex-shrink-0" />}
            label="Repositories"
            collapsed={!sidebarOpen}
          />
          <SidebarLink
            to="/app/tasks"
            icon={<ListTodo className="h-4 w-4 flex-shrink-0" />}
            label="Tasks"
            collapsed={!sidebarOpen}
          />
          <SidebarLink
            to="/app/tools"
            icon={<Wrench className="h-4 w-4 flex-shrink-0" />}
            label="Tools & MCP"
            collapsed={!sidebarOpen}
          />
        </nav>

        {/* User footer */}
        {sidebarOpen && (
          <div className="p-3 border-t border-border flex items-center gap-2">
            <div className="h-7 w-7 rounded-full bg-primary/20 text-primary flex items-center justify-center text-xs font-mono font-medium">
              {user?.login ? user.login[0].toUpperCase() : 'U'}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium text-foreground truncate">{user?.login ?? 'Developer'}</p>
              <p className="text-[10px] text-muted-foreground truncate">GitHub Connected</p>
            </div>
          </div>
        )}
      </aside>

      {/* ------------------------------------------------------------------ */}
      {/* Main column                                                          */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex flex-1 flex-col overflow-hidden min-w-0">
        {/* Top header */}
        <header className="h-14 flex-shrink-0 bg-card border-b border-border flex items-center gap-4 px-4">
          <button
            onClick={toggleSidebar}
            aria-label={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
            className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Menu className="w-4 h-4" />
          </button>

          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Terminal className="h-3.5 w-3.5 text-primary" />
            <span className="font-mono hidden sm:inline">ai-platform / workspace</span>
          </div>

          <div className="ml-auto flex items-center gap-3">
            <button
              onClick={() => setCommandPaletteOpen(true)}
              title="Open Command Palette (Ctrl/Cmd + K)"
              aria-label="Open command palette"
              className="hidden sm:inline-flex items-center gap-2 px-2.5 py-1 text-xs rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-accent transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Search className="w-3.5 h-3.5" />
              <span>Search</span>
              <kbd className="font-mono text-[10px] px-1 rounded border border-border bg-background">⌘K</kbd>
            </button>
            <span className="text-xs text-muted-foreground font-mono hidden md:inline">{user?.login}</span>
            <button
              onClick={handleLogout}
              aria-label="Sign out"
              title="Sign out"
              className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-accent transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <LogOut className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Sign out</span>
            </button>
          </div>
        </header>

        {/* Content area */}
        <main className="flex-1 bg-background min-w-0 overflow-hidden flex flex-col h-full">
          {/* resetKeys: a crash on one page must not keep the error screen up after navigating away. */}
          <ErrorBoundary resetKeys={[location.pathname]}>
            {/* Suspense inside the shell: lazy pages load in the content area while the sidebar
                and header stay mounted (the top-level fallback replaced the whole screen). */}
            <Suspense
              fallback={
                <div className="flex h-full w-full items-center justify-center">
                  <LoadingSpinner size="lg" label="Loading page..." />
                </div>
              }
            >
              {isRepositoryWorkspace ? (
                <div className="h-full flex flex-col min-h-0 overflow-hidden">
                  <Outlet />
                </div>
              ) : (
                <div className="h-full flex flex-col min-h-0 max-w-7xl w-full mx-auto p-4 sm:p-6 overflow-hidden">
                  <Outlet />
                </div>
              )}
            </Suspense>
          </ErrorBoundary>
        </main>
      </div>

      <CommandPalette
        repoId={activeRepoId}
        isOpen={commandPaletteOpen}
        onClose={() => setCommandPaletteOpen(false)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

interface SidebarLinkProps {
  to: string;
  icon: ReactNode;
  label: string;
  collapsed: boolean;
}

function SidebarLink({ to, icon, label, collapsed }: SidebarLinkProps) {
  return (
    <NavLink
      to={to}
      title={collapsed ? label : undefined}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
          isActive
            ? 'bg-accent text-accent-foreground'
            : 'text-muted-foreground hover:text-foreground hover:bg-accent'
        )
      }
    >
      {icon}
      {!collapsed && <span className="truncate">{label}</span>}
    </NavLink>
  );
}
