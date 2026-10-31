import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RepositoryBugStudio } from '../pages/RepositoryBugStudio';
import type { RepositoryFile } from '../types/api';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false },
  },
});

const mockFiles: RepositoryFile[] = [
  {
    id: 'file-1',
    path: 'src/main.py',
    size_bytes: 1200,
    line_count: 50,
    language: 'Python',
    content_hash: 'hash1',
    last_indexed_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 'file-2',
    path: 'src/utils.py',
    size_bytes: 800,
    line_count: 30,
    language: 'Python',
    content_hash: 'hash2',
    last_indexed_at: '2026-01-01T00:00:00Z',
  },
];

vi.mock('../hooks/useRepositories', () => ({
  useRepositoryFiles: () => ({
    data: { items: mockFiles, total: 2 },
    isLoading: false,
    isError: false,
  }),
  useRepositoryFileContent: () => ({
    data: { content: 'print("hello")', symbols: [] },
    isLoading: false,
    isError: false,
  }),
}));

function renderBugStudio() {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/app/repositories/repo-1/bugs']}>
        <Routes>
          <Route path="/app/repositories/:id/bugs" element={<RepositoryBugStudio />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('Repository Studio Responsive Layout (F-09)', () => {
  it('renders target file picker button with accessible popover attributes', () => {
    renderBugStudio();

    const pickerBtn = screen.getByTitle('Switch target file');
    expect(pickerBtn).toBeInTheDocument();
    expect(pickerBtn).toHaveAttribute('aria-haspopup', 'dialog');
    expect(pickerBtn).toHaveAttribute('aria-expanded', 'false');

    // Click to open anchored popover
    fireEvent.click(pickerBtn);
    expect(pickerBtn).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByPlaceholderText(/Search repository files/i)).toBeInTheDocument();
  });

  it('renders responsive mobile tabs and allows switching between Source and Results', () => {
    renderBugStudio();

    const sourceTab = screen.getByRole('button', { name: 'Source' });
    const resultsTab = screen.getByRole('button', { name: 'Results' });

    expect(sourceTab).toBeInTheDocument();
    expect(resultsTab).toBeInTheDocument();

    // Default tab is Source
    expect(sourceTab).toHaveClass('font-semibold');

    // Switch to Results tab
    fireEvent.click(resultsTab);
    expect(resultsTab).toHaveClass('font-semibold');

    // Switch back to Source
    fireEvent.click(sourceTab);
    expect(sourceTab).toHaveClass('font-semibold');
  });
});
