import { Outlet, Link } from 'react-router-dom';
import { useAppStore } from '../stores/useAppStore';
import { Menu } from 'lucide-react';

export function AppLayout() {
  const sidebarOpen = useAppStore((state) => state.sidebarOpen);
  const toggleSidebar = useAppStore((state) => state.toggleSidebar);

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Sidebar */}
      <aside
        className={`${
          sidebarOpen ? 'w-64' : 'w-16'
        } transition-all duration-300 bg-card border-r border-border flex flex-col`}
      >
        <div className="h-16 flex items-center justify-center border-b border-border">
          <span className="font-bold text-foreground">
            {sidebarOpen ? 'AI Platform' : 'AI'}
          </span>
        </div>
        <nav className="flex-1 p-4 space-y-2 text-muted-foreground">
          <Link to="/app/dashboard" className="block hover:text-foreground">
            {sidebarOpen ? 'Dashboard' : 'D'}
          </Link>
          <Link to="/app/repositories" className="block hover:text-foreground">
            {sidebarOpen ? 'Repositories' : 'R'}
          </Link>
        </nav>
      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top Header */}
        <header className="h-16 bg-card border-b border-border flex items-center px-4">
          <button
            onClick={toggleSidebar}
            className="p-2 text-muted-foreground hover:text-foreground focus:outline-none"
          >
            <Menu className="w-6 h-6" />
          </button>
          <div className="ml-auto text-foreground">User Profile</div>
        </header>

        {/* Content Area */}
        <main className="flex-1 overflow-auto p-6 text-foreground bg-background">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
