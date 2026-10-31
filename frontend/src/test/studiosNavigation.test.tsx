import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StudioSubNav } from '../components/studios/StudioSubNav';
import { CommandPalette } from '../components/studios/CommandPalette';
import type { Repository } from '../types/api';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false },
  },
});

const mockRepo: Repository = {
  id: 'repo-abc-123',
  github_repo_id: 'gh-123',
  owner: 'acme',
  name: 'my-demo-app',
  full_name: 'acme/my-demo-app',
  default_branch: 'main',
  language: 'TypeScript',
  sync_status: 'SYNCED',
  last_synced_at: '2026-01-01T00:00:00Z',
  file_count: 42,
};

function renderWithProviders(ui: React.ReactElement, initialRoute = '/app/repositories/repo-abc-123') {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialRoute]}>
        <Routes>
          <Route path="/app/repositories/:id/*" element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('StudioSubNav', () => {
  it('renders repository name, org, and all 6 studio workspace tabs', () => {
    renderWithProviders(<StudioSubNav repository={mockRepo} />);

    // Org and repo name
    expect(screen.getByText('acme')).toBeInTheDocument();
    expect(screen.getByText('my-demo-app')).toBeInTheDocument();

    // 6 studio tabs
    expect(screen.getByRole('link', { name: /Explorer/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Chat/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Explain/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Bug Hunter/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Test Studio/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Code Review/i })).toBeInTheDocument();

    // Indexed status badge
    expect(screen.getByText('Indexed')).toBeInTheDocument();
  });

  it('triggers onOpenCommandPalette when Quick Jump button is clicked', () => {
    const onOpen = vi.fn();
    renderWithProviders(<StudioSubNav repository={mockRepo} onOpenCommandPalette={onOpen} />);

    const jumpBtn = screen.getByTitle(/Open Command Palette/i);
    expect(jumpBtn).toBeInTheDocument();
    fireEvent.click(jumpBtn);
    expect(onOpen).toHaveBeenCalledOnce();
  });
});

describe('CommandPalette', () => {
  it('renders nothing when closed', () => {
    const { container } = renderWithProviders(
      <CommandPalette repoId="repo-abc-123" isOpen={false} onClose={vi.fn()} />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders studios and filters by query when open', () => {
    const onClose = vi.fn();
    renderWithProviders(
      <CommandPalette repoId="repo-abc-123" isOpen={true} onClose={onClose} />
    );

    // Dialog is visible
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('Bug Hunter')).toBeInTheDocument();
    expect(screen.getByText('Test Studio')).toBeInTheDocument();

    // Typing in filter
    const input = screen.getByPlaceholderText(/Type a studio name/i);
    fireEvent.change(input, { target: { value: 'Explain' } });

    expect(screen.getByText('Explain Studio')).toBeInTheDocument();
    expect(screen.queryByText('Bug Hunter')).toBeNull();

    // Escape closes modal
    fireEvent.keyDown(input, { key: 'Escape', code: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });
});
