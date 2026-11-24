import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useParams } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';
import { Repositories } from '../pages/Repositories';
import { Dashboard } from '../pages/Dashboard';
import type { AvailableRepository, Repository } from '../types/api';

function RepoDetailSpy() {
  const { id } = useParams<{ id: string }>();
  return <div data-testid="opened-repo-id">{id}</div>;
}

function createTestClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

function makeConnectedRepo(overrides: Partial<Repository> = {}): Repository {
  return {
    id: 'uuid-repo-1',
    github_repo_id: '100001',
    owner: 'acme',
    name: 'code-intelligence',
    full_name: 'acme/code-intelligence',
    default_branch: 'main',
    language: 'TypeScript',
    sync_status: 'SYNCED',
    last_synced_at: '2026-11-20T10:00:00Z',
    file_count: 42,
    ...overrides,
  };
}

function makeAvailableRepo(overrides: Partial<AvailableRepository> = {}): AvailableRepository {
  return {
    github_repo_id: '100001',
    owner: 'acme',
    name: 'code-intelligence',
    full_name: 'acme/code-intelligence',
    default_branch: 'main',
    language: 'TypeScript',
    is_connected: true,
    ...overrides,
  };
}

describe('R1 Repository Opening & R3 Parity (Repositories & Dashboard)', () => {
  it('opens a connected repository in Repositories when clicking its name', async () => {
    const connected = makeConnectedRepo({ id: 'uuid-alpha-1', github_repo_id: '100001', name: 'alpha-service', full_name: 'acme/alpha-service' });
    const available = makeAvailableRepo({ github_repo_id: '100001', name: 'alpha-service', full_name: 'acme/alpha-service', is_connected: true });

    server.use(
      http.get('*/api/v1/repositories', () =>
        HttpResponse.json([connected], { headers: { 'x-total-count': '1' } })
      ),
      http.get('*/api/v1/github/repositories', () =>
        HttpResponse.json({
          items: [available],
          total: 1,
          page: 1,
          page_size: 9,
          total_pages: 1,
        })
      ),
    );

    render(
      <QueryClientProvider client={createTestClient()}>
        <MemoryRouter initialEntries={['/app/repositories']}>
          <Routes>
            <Route path="/app/repositories" element={<Repositories />} />
            <Route path="/app/repositories/:id" element={<RepoDetailSpy />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const nameLink = await screen.findByRole('link', { name: 'alpha-service' });
    expect(nameLink).toHaveAttribute('href', '/app/repositories/uuid-alpha-1');

    fireEvent.click(nameLink);
    expect(await screen.findByTestId('opened-repo-id')).toHaveTextContent('uuid-alpha-1');
  });

  it('shows Connected status badge and explicit Open link that navigates to /app/repositories/:id', async () => {
    const connected = makeConnectedRepo({ id: 'uuid-beta-2', github_repo_id: '200002', name: 'beta-worker', full_name: 'acme/beta-worker' });
    const available = makeAvailableRepo({ github_repo_id: '200002', name: 'beta-worker', full_name: 'acme/beta-worker', is_connected: true });

    server.use(
      http.get('*/api/v1/repositories', () =>
        HttpResponse.json([connected], { headers: { 'x-total-count': '1' } })
      ),
      http.get('*/api/v1/github/repositories', () =>
        HttpResponse.json({
          items: [available],
          total: 1,
          page: 1,
          page_size: 9,
          total_pages: 1,
        })
      ),
    );

    render(
      <QueryClientProvider client={createTestClient()}>
        <MemoryRouter initialEntries={['/app/repositories']}>
          <Routes>
            <Route path="/app/repositories" element={<Repositories />} />
            <Route path="/app/repositories/:id" element={<RepoDetailSpy />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const openLink = await screen.findByRole('link', { name: /Open beta-worker/i });
    expect(openLink).toHaveAttribute('href', '/app/repositories/uuid-beta-2');
    expect(screen.getByLabelText('beta-worker is connected')).toHaveTextContent('Connected');

    fireEvent.click(openLink);
    expect(await screen.findByTestId('opened-repo-id')).toHaveTextContent('uuid-beta-2');
  });

  it('falls back to case-insensitive full_name matching when github_repo_id differs', async () => {
    const connected = makeConnectedRepo({
      id: 'uuid-fallback-9',
      github_repo_id: 'different-id',
      name: 'design-system',
      full_name: 'Acme/Design-System',
    });
    const available = makeAvailableRepo({
      github_repo_id: '999999',
      name: 'design-system',
      full_name: 'acme/design-system',
      is_connected: true,
    });

    server.use(
      http.get('*/api/v1/repositories', () =>
        HttpResponse.json([connected], { headers: { 'x-total-count': '1' } })
      ),
      http.get('*/api/v1/github/repositories', () =>
        HttpResponse.json({
          items: [available],
          total: 1,
          page: 1,
          page_size: 9,
          total_pages: 1,
        })
      ),
    );

    render(
      <QueryClientProvider client={createTestClient()}>
        <MemoryRouter initialEntries={['/app/repositories']}>
          <Routes>
            <Route path="/app/repositories" element={<Repositories />} />
            <Route path="/app/repositories/:id" element={<RepoDetailSpy />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const openLink = await screen.findByRole('link', { name: /Open design-system/i });
    expect(openLink).toHaveAttribute('href', '/app/repositories/uuid-fallback-9');
  });

  it('preserves Connect flow for unconnected repositories and avoids broken /undefined links', async () => {
    const unconnected = makeAvailableRepo({
      github_repo_id: '300003',
      name: 'new-repo',
      full_name: 'acme/new-repo',
      is_connected: false,
    });
    const unresolvedConnected = makeAvailableRepo({
      github_repo_id: '400004',
      name: 'unindexed-connected',
      full_name: 'acme/unindexed-connected',
      is_connected: true,
    });

    server.use(
      http.get('*/api/v1/repositories', () =>
        HttpResponse.json([], { headers: { 'x-total-count': '0' } })
      ),
      http.get('*/api/v1/github/repositories', () =>
        HttpResponse.json({
          items: [unconnected, unresolvedConnected],
          total: 2,
          page: 1,
          page_size: 9,
          total_pages: 1,
        })
      ),
      http.post('*/api/v1/github/repositories/300003/connect', () =>
        HttpResponse.json({ repository_id: 'uuid-newly-connected', job_id: 'job-1' })
      ),
    );

    render(
      <QueryClientProvider client={createTestClient()}>
        <MemoryRouter initialEntries={['/app/repositories']}>
          <Routes>
            <Route path="/app/repositories" element={<Repositories />} />
            <Route path="/app/repositories/:id" element={<RepoDetailSpy />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const connectBtn = await screen.findByRole('button', { name: /Connect new-repo/i });
    expect(screen.queryByRole('link', { name: 'new-repo' })).toBeNull();
    expect(screen.queryByRole('link', { name: /unindexed-connected/i })).toBeNull();

    // Unresolved connected repo shows disabled button rather than /app/repositories/undefined
    const fallbackBtn = screen.getByRole('button', { name: /unindexed-connected is already connected/i });
    expect(fallbackBtn).toBeDisabled();

    fireEvent.click(connectBtn);
    expect(await screen.findByTestId('opened-repo-id')).toHaveTextContent('uuid-newly-connected');
  });

  it('renders Code Intelligence copy in empty installations state and pagination when total_pages > 1', async () => {
    server.use(
      http.get('*/api/v1/repositories', () =>
        HttpResponse.json([], { headers: { 'x-total-count': '0' } })
      ),
      http.get('*/api/v1/github/repositories', () =>
        HttpResponse.json({
          items: [],
          total: 0,
          page: 1,
          page_size: 9,
          total_pages: 1,
        })
      ),
    );

    const { unmount } = render(
      <QueryClientProvider client={createTestClient()}>
        <MemoryRouter initialEntries={['/app/repositories']}>
          <Routes>
            <Route path="/app/repositories" element={<Repositories />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('Code Intelligence')).toBeInTheDocument();
    expect(screen.queryByText(/AI Dev Platform/i)).toBeNull();
    unmount();

    const paginatedItem = makeAvailableRepo({ github_repo_id: '500005', name: 'paged-repo', full_name: 'acme/paged-repo', is_connected: false });
    server.use(
      http.get('*/api/v1/repositories', () =>
        HttpResponse.json([], { headers: { 'x-total-count': '0' } })
      ),
      http.get('*/api/v1/github/repositories', () =>
        HttpResponse.json({
          items: [paginatedItem],
          total: 12,
          page: 1,
          page_size: 9,
          total_pages: 2,
        })
      ),
    );

    render(
      <QueryClientProvider client={createTestClient()}>
        <MemoryRouter initialEntries={['/app/repositories']}>
          <Routes>
            <Route path="/app/repositories" element={<Repositories />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole('navigation', { name: 'Repository pagination' })).toBeInTheDocument();
    expect(screen.getByText('1 / 2')).toBeInTheDocument();
  });

  it('opens a repository from Dashboard via name or View button and clamps pagination cleanly', async () => {
    const page1Repos = Array.from({ length: 6 }, (_, i) =>
      makeConnectedRepo({
        id: `uuid-p1-${i + 1}`,
        github_repo_id: `${600000 + i}`,
        name: `repo-${i + 1}`,
        full_name: `acme/repo-${i + 1}`,
      }),
    );
    const page2Repo = makeConnectedRepo({
      id: 'uuid-p2-7',
      github_repo_id: '600007',
      name: 'repo-7',
      full_name: 'acme/repo-7',
    });

    let total = 7;

    server.use(
      http.get('*/api/v1/repositories', ({ request }) => {
        const url = new URL(request.url);
        const page = Number(url.searchParams.get('page') ?? '1');
        const items = page === 1 ? page1Repos : total > 6 ? [page2Repo] : [];
        return HttpResponse.json(items, {
          headers: { 'x-total-count': String(total) },
        });
      }),
      http.get('*/api/v1/tasks', () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 })
      ),
    );

    render(
      <QueryClientProvider client={createTestClient()}>
        <MemoryRouter initialEntries={['/app/dashboard']}>
          <Routes>
            <Route path="/app/dashboard" element={<Dashboard />} />
            <Route path="/app/repositories/:id" element={<RepoDetailSpy />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    // Wait for page 1 to load and navigate to page 2
    expect(await screen.findByText('repo-1')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Next page' }));
    expect(await screen.findByText('repo-7')).toBeInTheDocument();

    // Simulate total shrinking to 6 while on page 2, then trigger Refresh
    total = 6;
    fireEvent.click(screen.getByRole('button', { name: 'Refresh repositories' }));

    await waitFor(() => {
      expect(screen.getByText('repo-1')).toBeInTheDocument();
    });
    expect(screen.queryByText('No repositories connected')).toBeNull();

    // Open via View button
    fireEvent.click(screen.getByRole('button', { name: 'View repo-1' }));
    expect(await screen.findByTestId('opened-repo-id')).toHaveTextContent('uuid-p1-1');
  });
});
