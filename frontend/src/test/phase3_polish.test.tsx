import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, renderHook, act, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { SyncProgressIndicator } from '../components/explorer/SyncProgressIndicator';
import {
  PageShellSkeleton,
  RepositoryGridSkeleton,
  DashboardTasksSkeleton,
  StudioLayoutSkeleton,
} from '../components/shared/Skeletons';
import {
  streamAnalysisEndpoint,
  AnalysisStreamUnavailableError,
} from '../services/analysis';
import {
  repositoryKeys,
  useSyncRepository,
  useDeleteRepository,
} from '../hooks/useRepositories';
import * as repositoriesService from '../services/repositories';
import type { PaginatedRepositoryResponse, Repository } from '../types/api';

function makeWrapper(queryClient: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe('Phase 3 Polish & Responsiveness', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders live granular progress bar, file counters, chunks, and stage message', () => {
    const now = Date.now();
    render(
      <SyncProgressIndicator
        currentStage="INDEXING"
        isFailed={false}
        liveProgress={{
          repository_id: 'repo-1',
          job_id: 'job-1',
          stage: 'INDEXING',
          files_processed: 15,
          files_total: 30,
          chunks_embedded: 64,
          progress_pct: 50,
          message: 'Indexed 15 / 30 files (64 chunks)',
          startedAt: now - 5000,
          updatedAt: now,
        }}
      />,
    );

    const progressbar = screen.getByRole('progressbar', { name: /Repository indexing progress/i });
    expect(progressbar).toHaveAttribute('aria-valuenow', '50');
    expect(screen.getByText('50%')).toBeInTheDocument();
    expect(screen.getByText(/15 \/ 30 files · 64 chunks embedded/i)).toBeInTheDocument();
    expect(screen.getByText('Indexed 15 / 30 files (64 chunks)')).toBeInTheDocument();
  });

  it('parses chunked SSE analysis events and returns done payload', async () => {
    const encoder = new TextEncoder();
    const sseChunks = [
      'event: status\ndata: {"stage":"retrieving_context","message":"Gathering context..."}\n\n',
      'event: status\ndata: {"stage":"generating_output","message":"Running model..."}\n\n',
      'event: done\ndata: {"run_id":"r1","status":"COMPLETED"}\n\n',
    ];

    let chunkIndex = 0;
    const fakeResponse = new Response(
      new ReadableStream({
        pull(controller) {
          if (chunkIndex < sseChunks.length) {
            controller.enqueue(encoder.encode(sseChunks[chunkIndex++]));
          } else {
            controller.close();
          }
        },
      }),
      {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      },
    );

    vi.spyOn(globalThis, 'fetch').mockResolvedValue(fakeResponse);

    const seenStages: string[] = [];
    const result = await streamAnalysisEndpoint<{ run_id: string; status: string }>(
      '/repositories/repo-1/explain/stream',
      { target: { type: 'file', path: 'app.py' } },
      { onStage: (e) => seenStages.push(e.stage) },
    );

    expect(seenStages).toEqual(['retrieving_context', 'generating_output']);
    expect(result).toEqual({ run_id: 'r1', status: 'COMPLETED' });
  });

  it('throws AnalysisStreamUnavailableError on HTTP 404 for seamless POST fallback', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('Not found', { status: 404 }),
    );

    await expect(
      streamAnalysisEndpoint('/repositories/repo-1/explain/stream', {}),
    ).rejects.toBeInstanceOf(AnalysisStreamUnavailableError);
  });

  it('optimistically updates caches on sync and delete and rolls back on failure', async () => {
    const repo: Repository = {
      id: 'repo-1',
      github_repo_id: 'gh-1',
      owner: 'octo',
      name: 'demo',
      full_name: 'octo/demo',
      default_branch: 'main',
      language: 'TypeScript',
      sync_status: 'SYNCED',
      last_synced_at: '2026-01-01T00:00:00Z',
      last_sync_error: null,
      file_count: 10,
      symbol_count: 20,
      chunk_count: 30,
    };
    const listPage: PaginatedRepositoryResponse = {
      items: [repo],
      total: 1,
      page: 1,
      page_size: 6,
    };

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    queryClient.setQueryData(repositoryKeys.detail('repo-1'), repo);
    queryClient.setQueryData(repositoryKeys.list(1, 6), listPage);

    let rejectSync!: (err: Error) => void;
    vi.spyOn(repositoriesService, 'syncRepository').mockImplementationOnce(
      () => new Promise((_, rej) => { rejectSync = rej; }),
    );

    const { result: syncHook } = renderHook(() => useSyncRepository(), {
      wrapper: makeWrapper(queryClient),
    });

    let syncPromise: Promise<unknown>;
    act(() => {
      syncPromise = syncHook.current.mutateAsync('repo-1').catch(() => undefined);
    });

    await waitFor(() => {
      expect(queryClient.getQueryData<Repository>(repositoryKeys.detail('repo-1'))?.sync_status).toBe(
        'SYNCING',
      );
    });

    await act(async () => {
      rejectSync(new Error('Network down'));
      await syncPromise;
    });

    expect(queryClient.getQueryData<Repository>(repositoryKeys.detail('repo-1'))?.sync_status).toBe(
      'SYNCED',
    );

    let rejectDelete!: (err: Error) => void;
    vi.spyOn(repositoriesService, 'deleteRepository').mockImplementationOnce(
      () => new Promise((_, rej) => { rejectDelete = rej; }),
    );

    const { result: deleteHook } = renderHook(() => useDeleteRepository(), {
      wrapper: makeWrapper(queryClient),
    });

    let deletePromise: Promise<unknown>;
    act(() => {
      deletePromise = deleteHook.current.mutateAsync('repo-1').catch(() => undefined);
    });

    await waitFor(() => {
      expect(
        queryClient.getQueryData<PaginatedRepositoryResponse>(repositoryKeys.list(1, 6))?.items,
      ).toHaveLength(0);
    });

    await act(async () => {
      rejectDelete(new Error('Delete blocked'));
      await deletePromise;
    });

    expect(
      queryClient.getQueryData<PaginatedRepositoryResponse>(repositoryKeys.list(1, 6))?.items,
    ).toHaveLength(1);
  });

  it('renders accessible skeleton states across workspace layouts', () => {
    render(
      <div>
        <PageShellSkeleton />
        <RepositoryGridSkeleton />
        <DashboardTasksSkeleton />
        <StudioLayoutSkeleton />
      </div>,
    );

    expect(screen.getByRole('status', { name: /Loading workspace/i })).toBeInTheDocument();
    expect(screen.getByRole('status', { name: /Loading repositories/i })).toBeInTheDocument();
    expect(screen.getByRole('status', { name: /Loading tasks/i })).toBeInTheDocument();
    expect(screen.getByRole('status', { name: /Loading repository…/i })).toBeInTheDocument();
  });
});
