import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AnalysisHistoryDrawer } from '../components/explorer/AnalysisHistoryDrawer';
import * as analysisService from '../services/analysis';

vi.mock('../services/analysis', () => ({
  getAnalysisRuns: vi.fn(),
  getAnalysisRun: vi.fn(),
  exportAnalysisRunsDataset: vi.fn(),
}));

describe('AnalysisHistoryDrawer - Dataset Export (Issue #195)', () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });

    vi.mocked(analysisService.getAnalysisRuns).mockResolvedValue({
      items: [
        {
          id: 'run-1',
          repository_id: 'repo-1',
          feature_type: 'detect_bugs',
          status: 'COMPLETED',
          findings_count: 2,
          created_at: new Date().toISOString(),
          target_path: 'src/main.py',
        },
      ],
      total: 1,
      page: 1,
      page_size: 8,
      total_pages: 1,
    } as any);

    // Mock window.URL methods
    window.URL.createObjectURL = vi.fn().mockReturnValue('blob:http://localhost/test-blob');
    window.URL.revokeObjectURL = vi.fn();
  });

  function renderDrawer() {
    return render(
      <QueryClientProvider client={queryClient}>
        <AnalysisHistoryDrawer
          isOpen={true}
          onClose={vi.fn()}
          repositoryId="repo-1"
        />
      </QueryClientProvider>
    );
  }

  it('renders Export button when runs are available in history', async () => {
    renderDrawer();

    await waitFor(() => {
      expect(screen.queryByText('Loading saved analysis runs…')).not.toBeInTheDocument();
    });

    const exportBtn = screen.getByRole('button', { name: /Export/i });
    expect(exportBtn).toBeInTheDocument();
    expect(exportBtn).not.toBeDisabled();
  });

  it('opens export menu with JSONL, Langfuse, and JSON options on click', async () => {
    renderDrawer();

    await waitFor(() => {
      expect(screen.queryByText('Loading saved analysis runs…')).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /Export/i }));

    expect(screen.getByText('Evaluation Dataset (Issue #195)')).toBeInTheDocument();
    expect(screen.getByText('JSONL (Plain)')).toBeInTheDocument();
    expect(screen.getByText('Langfuse Dataset')).toBeInTheDocument();
    expect(screen.getByText('JSON Array')).toBeInTheDocument();
    expect(screen.getByText('Feedback only')).toBeInTheDocument();
  });

  it('triggers exportAnalysisRunsDataset with selected format and downloads dataset', async () => {
    const mockBlob = new Blob(['{"input": {}, "expected_output": {}}'], { type: 'application/x-ndjson' });
    vi.mocked(analysisService.exportAnalysisRunsDataset).mockResolvedValue(mockBlob);

    renderDrawer();

    await waitFor(() => {
      expect(screen.queryByText('Loading saved analysis runs…')).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /Export/i }));
    fireEvent.click(screen.getByText('Langfuse Dataset'));

    await waitFor(() => {
      expect(analysisService.exportAnalysisRunsDataset).toHaveBeenCalledWith(
        'repo-1',
        expect.objectContaining({
          format: 'langfuse',
          include_feedback_only: false,
        })
      );
    });
  });
});
