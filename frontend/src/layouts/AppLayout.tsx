import type { ReactNode } from 'react';
import { Outlet, NavLink } from 'react-router-dom';
import { useAppStore } from '../stores/useAppStore';
import { ErrorBoundary } from '../components/shared/ErrorBoundary';
import { Menu, LayoutDashboard, FolderGit2 } from 'lucide-react';
import { cn } from '../lib/utils';

/**
 * AppLayout — application shell.
 *
 * Responsibilities:
 *  - Top header with sidebar toggle
 *  - Collapsible sidebar with navigation links
 *  - Main content area where child routes render via <Outlet />
 *  - Wraps content in ErrorBoundary so page errors don't crash the shell
 *
 * Sidebar state (open/collapsed) lives in useAppStore (Zustand UI state).
 */
export function AppLayout() {
  const sidebarOpen = useAppStore((state) => state.sidebarOpen);
  const toggleSidebar = useAppStore((state) => state.toggleSidebar);

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* ------------------------------------------------------------------ */}
      {/* Sidebar                                                              */}
      {/* ------------------------------------------------------------------ */}
      <aside
        className={cn(
          'flex flex-col flex-shrink-0 bg-card border-r border-border transition-all duration-300',
          sidebarOpen ? 'w-60' : 'w-16'
        )}
      >
        {/* Sidebar brand */}
        <div className="h-16 flex items-center px-4 border-b border-border">
          {sidebarOpen ? (
            <span className="font-bold text-foreground truncate">AI Platform</span>
          ) : (
            <span className="font-bold text-foreground">AI</span>
          )}
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto py-4 px-2 space-y-1">
          <SidebarLink
            to="/app/dashboard"
            icon={<LayoutDashboard className="h-5 w-5 flex-shrink-0" />}
            label="Dashboard"
            collapsed={!sidebarOpen}
          />
          <SidebarLink
            to="/app/repositories"
            icon={<FolderGit2 className="h-5 w-5 flex-shrink-0" />}
            label="Repositories"
            collapsed={!sidebarOpen}
          />
        </nav>
      </aside>

      {/* ------------------------------------------------------------------ */}
      {/* Main column                                                          */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex flex-1 flex-col overflow-hidden min-w-0">
        {/* Top header */}
        <header className="h-16 flex-shrink-0 bg-card border-b border-border flex items-center gap-4 px-4">
          <button
            onClick={toggleSidebar}
            aria-label={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
            className="p-2 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Menu className="w-5 h-5" />
          </button>
          <div className="ml-auto text-sm text-muted-foreground">
            {/* User profile placeholder — populated on Day 2 */}
            User
          </div>
        </header>

        {/* Content area */}
        <main className="flex-1 overflow-auto">
          <ErrorBoundary>
            <div className="max-w-7xl mx-auto p-6">
              <Outlet />
            </div>
          </ErrorBoundary>
        </main>
      </div>
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
