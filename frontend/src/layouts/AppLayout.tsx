import { Suspense, useEffect, type ReactNode } from 'react';
import { Outlet, NavLink, useNavigate, useLocation, matchPath } from 'react-router-dom';
import { useAppStore } from '../stores/useAppStore';
import { useAuth } from '../hooks/useAuth';
import { useRealtimeRepositories } from '../hooks/useRealtimeRepositories';
import { ErrorBoundary } from '../components/shared/ErrorBoundary';
import { LoadingSpinner } from '../components/shared/LoadingSpinner';
import { ThemeToggle } from '../components/shared/ThemeToggle';
import { CommandPalette } from '../components/studios/CommandPalette';
import {
  PanelLeft,
  LayoutDashboard,
  FolderGit2,
  LogOut,
  Cpu,
  ListTodo,
  Wrench,
  Search,
  Menu,
  X,
} from 'lucide-react';
import { cn } from '../lib/utils';

function getSectionTitle(pathname: string): string {
  if (pathname.startsWith('/app/dashboard')) return 'Dashboard';
  if (pathname.startsWith('/app/repositories/')) return 'Repository';
  if (pathname.startsWith('/app/repositories')) return 'Repositories';
  if (pathname.startsWith('/app/tasks/new')) return 'New Task';
  if (pathname.startsWith('/app/tasks')) return 'Tasks';
  if (pathname.startsWith('/app/tools')) return 'Tools & MCP';
  return 'Workspace';
}

export function AppLayout() {
  const sidebarOpen = useAppStore((state) => state.sidebarOpen);
  const toggleSidebar = useAppStore((state) => state.toggleSidebar);
  const mobileNavOpen = useAppStore((state) => state.mobileNavOpen);
  const setMobileNavOpen = useAppStore((state) => state.setMobileNavOpen);
  const toggleMobileNav = useAppStore((state) => state.toggleMobileNav);
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
  const sectionTitle = getSectionTitle(location.pathname);

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

  // Close the palette and mobile drawer whenever the route changes (e.g. browser back button).
  useEffect(() => {
    setCommandPaletteOpen(false);
    setMobileNavOpen(false);
  }, [location.pathname, setCommandPaletteOpen, setMobileNavOpen]);

  // Close the mobile drawer on Escape (CommandPalette takes precedence if open).
  useEffect(() => {
    if (!mobileNavOpen || commandPaletteOpen) return;
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        setMobileNavOpen(false);
      }
    };
    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [mobileNavOpen, commandPaletteOpen, setMobileNavOpen]);

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
      {/* Mobile backdrop                                                      */}
      {/* ------------------------------------------------------------------ */}
      {mobileNavOpen && (
        <div
          data-testid="mobile-nav-backdrop"
          aria-hidden="true"
          onClick={() => setMobileNavOpen(false)}
          className="fixed inset-0 z-30 bg-black/40 dark:bg-black/60 backdrop-blur-[1px] md:hidden"
        />
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Sidebar                                                              */}
      {/* ------------------------------------------------------------------ */}
      <aside
        id="app-sidebar"
        aria-label="Sidebar navigation"
        className={cn(
          'fixed inset-y-0 left-0 z-40 flex flex-col flex-shrink-0 w-60 bg-card border-r border-border transition-all duration-200',
          'md:relative md:inset-auto md:z-20 md:translate-x-0',
          mobileNavOpen ? 'translate-x-0 shadow-xl md:shadow-none' : '-translate-x-full',
          sidebarOpen ? 'md:w-60' : 'md:w-16'
        )}
      >
        {/* Sidebar brand */}
        <div
          className={cn(
            'h-13 flex items-center justify-between px-3.5 border-b border-border gap-2.5',
            !sidebarOpen && 'md:justify-center md:px-2'
          )}
        >
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground shrink-0">
              <Cpu className="h-3.5 w-3.5" />
            </div>
            <span
              className={cn(
                'font-semibold text-sm text-foreground tracking-tight truncate',
                !sidebarOpen && 'md:hidden'
              )}
            >
              Code Intelligence
            </span>
          </div>
          <button
            type="button"
            onClick={() => setMobileNavOpen(false)}
            aria-label="Close navigation menu"
            className="md:hidden p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-0.5" aria-label="Primary">
          <SidebarLink
            to="/app/dashboard"
            icon={<LayoutDashboard className="h-4 w-4 flex-shrink-0" />}
            label="Dashboard"
            collapsed={!sidebarOpen}
            onNavigate={() => setMobileNavOpen(false)}
          />
          <SidebarLink
            to="/app/repositories"
            icon={<FolderGit2 className="h-4 w-4 flex-shrink-0" />}
            label="Repositories"
            collapsed={!sidebarOpen}
            onNavigate={() => setMobileNavOpen(false)}
          />
          <SidebarLink
            to="/app/tasks"
            icon={<ListTodo className="h-4 w-4 flex-shrink-0" />}
            label="Tasks"
            collapsed={!sidebarOpen}
            onNavigate={() => setMobileNavOpen(false)}
          />
          <SidebarLink
            to="/app/tools"
            icon={<Wrench className="h-4 w-4 flex-shrink-0" />}
            label="Tools & MCP"
            collapsed={!sidebarOpen}
            onNavigate={() => setMobileNavOpen(false)}
          />
        </nav>

        {/* User footer */}
        <div
          className={cn(
            'p-3 border-t border-border flex items-center gap-2.5',
            !sidebarOpen && 'md:justify-center md:px-2'
          )}
        >
          <div
            title={!sidebarOpen ? (user?.login ?? 'Developer') : undefined}
            className="h-7 w-7 rounded-full bg-muted border border-border text-foreground flex items-center justify-center text-xs font-medium shrink-0"
          >
            {user?.login ? user.login[0].toUpperCase() : 'U'}
          </div>
          <div className={cn('min-w-0 flex-1', !sidebarOpen && 'md:hidden')}>
            <p className="text-xs font-medium text-foreground truncate">{user?.login ?? 'Developer'}</p>
            <p className="text-[11px] text-muted-foreground truncate">GitHub</p>
          </div>
        </div>
      </aside>

      {/* ------------------------------------------------------------------ */}
      {/* Main column                                                          */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex flex-1 flex-col overflow-hidden min-w-0">
        {/* Top header */}
        <header className="h-13 flex-shrink-0 bg-card/80 backdrop-blur-sm border-b border-border flex items-center gap-2 sm:gap-3 px-3 sm:px-4">
          <button
            type="button"
            onClick={toggleMobileNav}
            aria-label="Toggle navigation menu"
            aria-expanded={mobileNavOpen}
            aria-controls="app-sidebar"
            className="md:hidden p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
          >
            <Menu className="w-4 h-4" />
          </button>

          <button
            type="button"
            onClick={toggleSidebar}
            aria-label={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
            aria-expanded={sidebarOpen}
            aria-controls="app-sidebar"
            className="hidden md:inline-flex p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
          >
            <PanelLeft className="w-4 h-4" />
          </button>

          <span className="text-xs font-medium text-muted-foreground truncate">
            {sectionTitle}
          </span>

          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                setMobileNavOpen(false);
                setCommandPaletteOpen(true);
              }}
              title="Open Command Palette (Ctrl/Cmd + K)"
              aria-label="Open command palette"
              className="inline-flex items-center justify-center gap-2 h-8 w-8 sm:w-auto sm:px-2.5 text-xs rounded-md border border-border bg-background text-muted-foreground hover:text-foreground hover:bg-accent transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
            >
              <Search className="w-3.5 h-3.5" />
              <span className="hidden md:inline">Search…</span>
              <kbd className="hidden sm:inline font-mono text-[10px] px-1 py-0.5 rounded bg-muted text-muted-foreground leading-none">
                ⌘K
              </kbd>
            </button>

            <ThemeToggle />

            {!sidebarOpen && user?.login && (
              <span className="text-xs text-muted-foreground font-mono hidden md:inline px-1">
                {user.login}
              </span>
            )}

            <button
              type="button"
              onClick={handleLogout}
              aria-label="Sign out"
              title="Sign out"
              className="inline-flex items-center justify-center gap-1.5 h-8 w-8 sm:w-auto sm:px-2.5 text-xs rounded-md border border-border bg-background text-muted-foreground hover:text-foreground hover:bg-accent transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
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
                <div className="h-full flex flex-col min-h-0 max-w-6xl w-full mx-auto px-4 py-5 sm:px-8 sm:py-6 overflow-hidden">
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
  onNavigate?: () => void;
}

function SidebarLink({ to, icon, label, collapsed, onNavigate }: SidebarLinkProps) {
  return (
    <NavLink
      to={to}
      title={collapsed ? label : undefined}
      aria-label={label}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-2.5 rounded-md px-2.5 py-2 text-[13px] font-medium transition-colors cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-ring',
          collapsed && 'md:justify-center md:px-0',
          isActive
            ? 'bg-accent text-foreground'
            : 'text-muted-foreground hover:text-foreground hover:bg-accent/60'
        )
      }
    >
      {icon}
      <span className={cn('truncate', collapsed && 'md:hidden')}>{label}</span>
    </NavLink>
  );
}
