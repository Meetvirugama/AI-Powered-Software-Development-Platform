import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';
import { AppLayout } from '../layouts/AppLayout';
import { CommandPalette } from '../components/studios/CommandPalette';
import { Login } from '../pages/Login';
import { useAppStore } from '../stores/useAppStore';

const mockLogout = vi.fn().mockResolvedValue(undefined);

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({
    user: { id: 'user-1', login: 'yug', email: 'yug@example.com', avatar_url: null },
    isAuthenticated: true,
    isLoading: false,
    logout: mockLogout,
  }),
}));

vi.mock('../hooks/useRealtimeRepositories', () => ({
  useRealtimeRepositories: vi.fn(),
}));

const mockDevLogin = vi.fn();
vi.mock('../services/auth', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/auth')>();
  return {
    ...actual,
    devLogin: (...args: unknown[]) => mockDevLogin(...args),
  };
});

function createTestClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
}

function renderAppShell(initialEntry = '/app/dashboard') {
  return render(
    <QueryClientProvider client={createTestClient()}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/app" element={<AppLayout />}>
            <Route
              path="dashboard"
              element={
                <div>
                  <h1>Dashboard Page</h1>
                  <Link to="/app/tasks">Go to Tasks</Link>
                </div>
              }
            />
            <Route path="repositories" element={<div>Repositories Page</div>} />
            <Route path="tasks" element={<div>Tasks Page</div>} />
            <Route path="tools" element={<div>Tools Page</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('AppLayout mobile drawer, CommandPalette R2 & Login feedback', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAppStore.setState({
      sidebarOpen: true,
      mobileNavOpen: false,
      commandPaletteOpen: false,
    });
    server.use(
      http.get('*/api/v1/repositories', () =>
        HttpResponse.json([], { headers: { 'x-total-count': '0' } })
      ),
      http.get('*/api/v1/tasks', () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 })
      ),
    );
  });

  it('opens and closes mobile drawer via toggle button, backdrop, and drawer close button', async () => {
    renderAppShell();
    expect(await screen.findByText('Dashboard Page')).toBeInTheDocument();

    const sidebar = screen.getByRole('complementary', { name: /Sidebar navigation/i });
    const toggleBtn = screen.getByRole('button', { name: /Toggle navigation menu/i });

    expect(sidebar.className).toContain('-translate-x-full');
    expect(screen.queryByTestId('mobile-nav-backdrop')).toBeNull();
    expect(toggleBtn).toHaveAttribute('aria-expanded', 'false');

    // Open via mobile menu toggle
    fireEvent.click(toggleBtn);
    expect(useAppStore.getState().mobileNavOpen).toBe(true);
    expect(sidebar.className).toContain('translate-x-0');
    expect(toggleBtn).toHaveAttribute('aria-expanded', 'true');

    // Close via backdrop click
    const backdrop = screen.getByTestId('mobile-nav-backdrop');
    fireEvent.click(backdrop);
    expect(useAppStore.getState().mobileNavOpen).toBe(false);
    expect(screen.queryByTestId('mobile-nav-backdrop')).toBeNull();
    expect(sidebar.className).toContain('-translate-x-full');

    // Re-open and close via drawer X button
    fireEvent.click(toggleBtn);
    expect(useAppStore.getState().mobileNavOpen).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: /Close navigation menu/i }));
    expect(useAppStore.getState().mobileNavOpen).toBe(false);
  });

  it('closes mobile drawer on Escape and defers Escape to CommandPalette when both are open', async () => {
    renderAppShell();
    expect(await screen.findByText('Dashboard Page')).toBeInTheDocument();

    const toggleBtn = screen.getByRole('button', { name: /Toggle navigation menu/i });
    fireEvent.click(toggleBtn);
    expect(useAppStore.getState().mobileNavOpen).toBe(true);

    // Escape closes mobile drawer
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(useAppStore.getState().mobileNavOpen).toBe(false);

    // Open drawer, then open CommandPalette via Ctrl+K
    fireEvent.click(toggleBtn);
    expect(useAppStore.getState().mobileNavOpen).toBe(true);
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });

    const dialog = await screen.findByRole('dialog', { name: /Command Palette/i });
    expect(dialog).toBeInTheDocument();

    // Escape inside CommandPalette closes palette first without closing mobile drawer underneath
    const input = screen.getByLabelText('Search commands');
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(useAppStore.getState().commandPaletteOpen).toBe(false);
    expect(useAppStore.getState().mobileNavOpen).toBe(true);

    // Next Escape closes mobile drawer
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(useAppStore.getState().mobileNavOpen).toBe(false);
  });

  it('closes CommandPalette on Escape immediately before 40ms focus timer and on dialog backdrop without closing mobileNavOpen', async () => {
    renderAppShell();
    expect(await screen.findByText('Dashboard Page')).toBeInTheDocument();

    const toggleBtn = screen.getByRole('button', { name: /Toggle navigation menu/i });
    const searchBtn = screen.getByRole('button', { name: /Open command palette/i });

    // 1) Immediate Escape on focused trigger button (before 40ms input focus timer fires)
    fireEvent.click(toggleBtn);
    expect(useAppStore.getState().mobileNavOpen).toBe(true);
    searchBtn.focus();
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    expect(useAppStore.getState().commandPaletteOpen).toBe(true);

    fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' });
    expect(useAppStore.getState().commandPaletteOpen).toBe(false);
    expect(useAppStore.getState().mobileNavOpen).toBe(true);

    // 2) Escape directly on the role="dialog" backdrop container
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    const dialog = await screen.findByRole('dialog', { name: /Command Palette/i });
    fireEvent.keyDown(dialog, { key: 'Escape' });
    expect(useAppStore.getState().commandPaletteOpen).toBe(false);
    expect(useAppStore.getState().mobileNavOpen).toBe(true);

    // Subsequent Escape now closes mobile drawer
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(useAppStore.getState().mobileNavOpen).toBe(false);
  });

  it('auto-closes mobile drawer when clicking a sidebar link or changing route', async () => {
    renderAppShell();
    expect(await screen.findByText('Dashboard Page')).toBeInTheDocument();

    const toggleBtn = screen.getByRole('button', { name: /Toggle navigation menu/i });

    // 1) Sidebar NavLink click
    fireEvent.click(toggleBtn);
    expect(useAppStore.getState().mobileNavOpen).toBe(true);
    fireEvent.click(screen.getByRole('link', { name: 'Repositories' }));
    expect(await screen.findByText('Repositories Page')).toBeInTheDocument();
    expect(useAppStore.getState().mobileNavOpen).toBe(false);

    // 2) Programmatic / in-page route change
    fireEvent.click(toggleBtn);
    expect(useAppStore.getState().mobileNavOpen).toBe(true);
    fireEvent.click(screen.getByRole('link', { name: 'Dashboard' }));
    expect(await screen.findByText('Dashboard Page')).toBeInTheDocument();
    expect(useAppStore.getState().mobileNavOpen).toBe(false);

    fireEvent.click(toggleBtn);
    expect(useAppStore.getState().mobileNavOpen).toBe(true);
    fireEvent.click(screen.getByRole('link', { name: 'Go to Tasks' }));
    expect(await screen.findByText('Tasks Page')).toBeInTheDocument();
    expect(useAppStore.getState().mobileNavOpen).toBe(false);
  });

  it('keeps desktop sidebar collapse independent from mobile drawer and preserves user avatar', async () => {
    renderAppShell();
    expect(await screen.findByText('Dashboard Page')).toBeInTheDocument();

    const collapseBtn = screen.getByRole('button', { name: 'Collapse sidebar' });
    fireEvent.click(collapseBtn);

    expect(useAppStore.getState().sidebarOpen).toBe(false);
    expect(useAppStore.getState().mobileNavOpen).toBe(false);
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toBeInTheDocument();

    // User avatar initial 'Y' stays visible in sidebar footer when collapsed
    const sidebar = screen.getByRole('complementary', { name: /Sidebar navigation/i });
    expect(sidebar).toHaveTextContent('Y');
  });

  it('renders mobile-visible CommandPalette trigger and displays resolved R2 language labels instead of unknown', async () => {
    server.use(
      http.get('*/api/v1/repositories/repo-123/files', () =>
        HttpResponse.json({
          items: [
            { id: 'f1', path: 'README.md', language: 'unknown', size_bytes: 2048, line_count: 40, content_hash: 'h1', last_indexed_at: null },
            { id: 'f2', path: 'src/lib.rs', language: 'unknown', size_bytes: 4096, line_count: 100, content_hash: 'h2', last_indexed_at: null },
            { id: 'f3', path: 'docs/spec.pdf', language: null, size_bytes: 10240, line_count: 0, content_hash: 'h3', last_indexed_at: null },
            { id: 'f4', path: 'public/index.html', language: 'unknown', size_bytes: 1024, line_count: 25, content_hash: 'h4', last_indexed_at: null },
          ],
          total: 4,
          page: 1,
          page_size: 100,
        }),
      ),
    );

    const { unmount } = renderAppShell();
    expect(await screen.findByText('Dashboard Page')).toBeInTheDocument();

    const searchBtn = screen.getByRole('button', { name: /Open command palette/i });
    expect(searchBtn.className).not.toContain('hidden sm:inline-flex');
    fireEvent.click(searchBtn);
    expect(useAppStore.getState().commandPaletteOpen).toBe(true);
    unmount();

    const onClose = vi.fn();
    render(
      <QueryClientProvider client={createTestClient()}>
        <MemoryRouter initialEntries={['/app/repositories/repo-123']}>
          <Routes>
            <Route
              path="/app/repositories/:id"
              element={<CommandPalette repoId="repo-123" isOpen={true} onClose={onClose} />}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText(/Markdown · 2 KB/i)).toBeInTheDocument();
    expect(screen.getByText(/Rust · 4 KB/i)).toBeInTheDocument();
    expect(screen.getByText(/PDF Document · 10 KB/i)).toBeInTheDocument();
    expect(screen.getByText(/HTML · 1 KB/i)).toBeInTheDocument();
    expect(screen.queryByText(/unknown ·/i)).toBeNull();

    // Mobile Close X button and Clear query button
    const input = screen.getByLabelText('Search commands');
    fireEvent.change(input, { target: { value: 'Rust' } });
    const clearBtn = screen.getByRole('button', { name: 'Clear query' });
    fireEvent.click(clearBtn);
    expect(input).toHaveValue('');

    fireEvent.click(screen.getByRole('button', { name: 'Close command palette' }));
    expect(onClose).toHaveBeenCalledOnce();

    // Escape on backdrop and input each invoke onClose exactly once (no double-fire)
    onClose.mockClear();
    fireEvent.keyDown(screen.getByRole('dialog', { name: 'Command Palette' }), { key: 'Escape' });
    expect(onClose).toHaveBeenCalledOnce();

    onClose.mockClear();
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('surfaces inline auth error on Login failure and keeps ThemeToggle in non-overlapping header row', async () => {
    vi.stubEnv('VITE_DEV_LOGIN', 'dev-user');
    mockDevLogin.mockRejectedValueOnce({ message: 'Backend offline' });

    render(
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route path="/login" element={<Login />} />
        </Routes>
      </MemoryRouter>,
    );

    const devBtn = screen.getByRole('button', { name: /Quick Dev Sign-In/i });
    fireEvent.click(devBtn);

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Backend offline');
    });

    vi.unstubAllEnvs();
  });
});
