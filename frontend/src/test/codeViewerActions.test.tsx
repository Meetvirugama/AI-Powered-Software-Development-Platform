import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CodeViewer } from '../components/explorer/CodeViewer';
import RepositoryExplainStudio from '../pages/RepositoryExplainStudio';
import RepositoryBugStudio from '../pages/RepositoryBugStudio';
import RepositoryTestStudio from '../pages/RepositoryTestStudio';
import RepositoryReviewStudio from '../pages/RepositoryReviewStudio';
import RepositoryDetail from '../pages/RepositoryDetail';
import type { RepositoryFile } from '../types/api';
import type { AnalysisTarget } from '../types/analysis';

const mockFile: RepositoryFile = {
  id: 'file-1',
  path: 'src/index.ts',
  size_bytes: 120,
  language: 'typescript',
  line_count: 10,
  content_hash: 'abc123hash',
  last_indexed_at: null,
};

const mockFileTarget: AnalysisTarget = {
  type: 'file',
  path: 'src/index.ts',
};

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      {ui}
    </QueryClientProvider>
  );
}

describe('CodeViewer Action Contract (P0.1)', () => {
  it('renders action button with custom label when provided and fires onClick', () => {
    const handleClick = vi.fn();
    renderWithClient(
      <CodeViewer
        repositoryId="repo-1"
        file={mockFile}
        activeTarget={mockFileTarget}
        onTargetChange={vi.fn()}
        action={{
          label: 'Scan for bugs',
          onClick: handleClick,
        }}
      />
    );

    const actionButton = screen.getByRole('button', { name: /Scan for bugs/i });
    expect(actionButton).toBeInTheDocument();
    fireEvent.click(actionButton);
    expect(handleClick).toHaveBeenCalledOnce();
  });

  it('does not render action button when action is not provided', () => {
    renderWithClient(
      <CodeViewer
        repositoryId="repo-1"
        file={mockFile}
        activeTarget={mockFileTarget}
        onTargetChange={vi.fn()}
      />
    );

    expect(screen.queryByRole('button', { name: /Explain target|Scan for bugs|Generate tests|Review target/i })).not.toBeInTheDocument();
  });

  it('renders pending label and disables button when isPending is true', () => {
    const handleClick = vi.fn();
    renderWithClient(
      <CodeViewer
        repositoryId="repo-1"
        file={mockFile}
        activeTarget={mockFileTarget}
        onTargetChange={vi.fn()}
        action={{
          label: 'Generate tests',
          onClick: handleClick,
          isPending: true,
        }}
      />
    );

    const actionButton = screen.getByRole('button', { name: /Generate tests…/i });
    expect(actionButton).toBeInTheDocument();
    expect(actionButton).toBeDisabled();
    fireEvent.click(actionButton);
    expect(handleClick).not.toHaveBeenCalled();
  });

  it('disables button with disabledReason tooltip when disabled is true', () => {
    const handleClick = vi.fn();
    renderWithClient(
      <CodeViewer
        repositoryId="repo-1"
        file={mockFile}
        activeTarget={mockFileTarget}
        onTargetChange={vi.fn()}
        action={{
          label: 'Review target',
          onClick: handleClick,
          disabled: true,
          disabledReason: 'No files modified in selection',
        }}
      />
    );

    const actionButton = screen.getByRole('button', { name: /Review target/i });
    expect(actionButton).toBeDisabled();
    expect(actionButton).toHaveAttribute('title', 'No files modified in selection');
    fireEvent.click(actionButton);
    expect(handleClick).not.toHaveBeenCalled();
  });

  it('renders custom icon when supplied in action', () => {
    renderWithClient(
      <CodeViewer
        repositoryId="repo-1"
        file={mockFile}
        activeTarget={mockFileTarget}
        onTargetChange={vi.fn()}
        action={{
          label: 'Custom action',
          onClick: vi.fn(),
          icon: <span data-testid="custom-action-icon">icon</span>,
        }}
      />
    );

    expect(screen.getByTestId('custom-action-icon')).toBeInTheDocument();
    expect(screen.getByText('Custom action')).toBeInTheDocument();
  });

  it('supports each studio-specific action configuration accurately', () => {
    const explainClick = vi.fn();
    const bugClick = vi.fn();
    const testClick = vi.fn();
    const reviewClick = vi.fn();
    const detailClick = vi.fn();

    // 1. Explain Studio
    const { unmount: unmount1 } = renderWithClient(
      <CodeViewer
        repositoryId="repo-1"
        file={mockFile}
        activeTarget={mockFileTarget}
        onTargetChange={vi.fn()}
        action={{ label: 'Explain target', onClick: explainClick }}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /Explain target/i }));
    expect(explainClick).toHaveBeenCalledOnce();
    unmount1();

    // 2. Bug Studio
    const { unmount: unmount2 } = renderWithClient(
      <CodeViewer
        repositoryId="repo-1"
        file={mockFile}
        activeTarget={mockFileTarget}
        onTargetChange={vi.fn()}
        action={{ label: 'Scan for bugs', onClick: bugClick }}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /Scan for bugs/i }));
    expect(bugClick).toHaveBeenCalledOnce();
    unmount2();

    // 3. Test Studio
    const { unmount: unmount3 } = renderWithClient(
      <CodeViewer
        repositoryId="repo-1"
        file={mockFile}
        activeTarget={mockFileTarget}
        onTargetChange={vi.fn()}
        action={{ label: 'Generate tests', onClick: testClick }}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /Generate tests/i }));
    expect(testClick).toHaveBeenCalledOnce();
    unmount3();

    // 4. Review Studio
    const { unmount: unmount4 } = renderWithClient(
      <CodeViewer
        repositoryId="repo-1"
        file={mockFile}
        activeTarget={mockFileTarget}
        onTargetChange={vi.fn()}
        action={{ label: 'Review target', onClick: reviewClick }}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /Review target/i }));
    expect(reviewClick).toHaveBeenCalledOnce();
    unmount4();

    // 5. Repository Detail
    const { unmount: unmount5 } = renderWithClient(
      <CodeViewer
        repositoryId="repo-1"
        file={mockFile}
        activeTarget={mockFileTarget}
        onTargetChange={vi.fn()}
        action={{ label: 'Explain in Studio', onClick: detailClick }}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /Explain in Studio/i }));
    expect(detailClick).toHaveBeenCalledOnce();
    unmount5();
  });
});

describe('Studio Routes (P0.1)', () => {
  it('Explain Studio mounts without error', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/app/repositories/repo-test-1/studios/explain']}>
          <Routes>
            <Route path="/app/repositories/:id/studios/explain" element={<RepositoryExplainStudio />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );
    expect(screen.getByRole('heading', { name: /Code Explainer Studio/i })).toBeInTheDocument();
  });

  it('Bug Studio mounts without error', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/app/repositories/repo-test-1/studios/bugs']}>
          <Routes>
            <Route path="/app/repositories/:id/studios/bugs" element={<RepositoryBugStudio />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );
    expect(screen.getByRole('heading', { name: /Ready to scan/i })).toBeInTheDocument();
  });

  it('Test Studio mounts without error', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/app/repositories/repo-test-1/studios/tests']}>
          <Routes>
            <Route path="/app/repositories/:id/studios/tests" element={<RepositoryTestStudio />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );
    expect(screen.getByRole('heading', { name: /Test Generation Studio/i })).toBeInTheDocument();
  });

  it('Review Studio mounts without error', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/app/repositories/repo-test-1/studios/review']}>
          <Routes>
            <Route path="/app/repositories/:id/studios/review" element={<RepositoryReviewStudio />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );
    expect(screen.getByRole('heading', { name: /Ready for Review/i })).toBeInTheDocument();
  });

  it('RepositoryDetail mounts without error', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/app/repositories/repo-test-1']}>
          <Routes>
            <Route path="/app/repositories/:id" element={<RepositoryDetail />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );
    expect(screen.getByText(/Repository/i)).toBeInTheDocument();
  });
});
