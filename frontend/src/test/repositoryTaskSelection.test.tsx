import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse, passthrough } from 'msw';
import { server } from '../mocks/server';
import { resetMockStore } from '../mocks/handlers';
import RepositoryTaskStudio from '../pages/RepositoryTaskStudio';
import { taskKeys } from '../hooks/useTasks';

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
    },
  });
}

function renderTaskStudio(initialRoute = '/app/repositories/repo-1/studios/tasks') {
  const queryClient = createTestQueryClient();
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[initialRoute]}>
          <Routes>
            <Route path="/app/repositories/:id/studios/tasks" element={<RepositoryTaskStudio />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    ),
  };
}

describe('RepositoryTaskStudio Selection & Query Invalidation (P0.3 & P0.4)', () => {
  beforeEach(() => {
    resetMockStore();
  });

  it('auto-selects first task when no taskId is in URL', async () => {
    renderTaskStudio('/app/repositories/repo-1/studios/tasks');

    // Wait for task list to load and verify first task heading renders in canvas
    await waitFor(() => {
      expect(
        screen.getByRole('heading', { level: 2, name: /Optimize Vector Similarity Query Index/i })
      ).toBeInTheDocument();
    });
  });

  it('selects taskId specified in URL query parameter over default selection', async () => {
    renderTaskStudio('/app/repositories/repo-1/studios/tasks?taskId=task-seed-1');

    await waitFor(() => {
      expect(
        screen.getByRole('heading', { level: 2, name: /Fix Token Budget Overflow in AST Analyzer/i })
      ).toBeInTheDocument();
    });
  });

  it('switching selected task updates active task view', async () => {
    renderTaskStudio('/app/repositories/repo-1/studios/tasks');

    await waitFor(() => {
      expect(
        screen.getByRole('heading', { level: 2, name: /Optimize Vector Similarity Query Index/i })
      ).toBeInTheDocument();
    });

    // Click on task-seed-1 in the sidebar
    const taskButton = screen.getByRole('button', { name: /Fix Token Budget Overflow in AST Analyzer/i });
    fireEvent.click(taskButton);

    // The active task details in the main pane should update to task-seed-1
    await waitFor(() => {
      expect(
        screen.getByRole('heading', { level: 2, name: /Fix Token Budget Overflow in AST Analyzer/i })
      ).toBeInTheDocument();
    });
  });

  it('handles optional resource (PR / workspace) failure gracefully without blanking task details', async () => {
    // Override pull-request endpoint to return 500 error
    server.use(
      http.get('*/api/v1/tasks/:taskId/pull-request', () => {
        return HttpResponse.json({ error: 'PR service unavailable' }, { status: 500 });
      })
    );

    renderTaskStudio('/app/repositories/repo-1/studios/tasks?taskId=task-seed-1');

    // Main task details must still render successfully
    await waitFor(() => {
      expect(
        screen.getByRole('heading', { level: 2, name: /Fix Token Budget Overflow in AST Analyzer/i })
      ).toBeInTheDocument();
      expect(screen.getByText(/Requirements/i)).toBeInTheDocument();
    });
  });

  it('query keys include task ID and repository filters to prevent stale data cross-contamination', () => {
    const listKeyRepo1 = taskKeys.list({ repository_id: 'repo-1' });
    const listKeyRepo2 = taskKeys.list({ repository_id: 'repo-2' });
    const detailKeyA = taskKeys.detail('task-A');
    const detailKeyB = taskKeys.detail('task-B');

    expect(listKeyRepo1).not.toEqual(listKeyRepo2);
    expect(detailKeyA).not.toEqual(detailKeyB);
    expect(detailKeyA).toContain('task-A');
    expect(detailKeyB).toContain('task-B');
  });

  it('task list fetch is independent of task selection (no loop)', async () => {
    let listFetchCount = 0;
    server.use(
      http.get('*/api/v1/tasks', ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get('repository_id') === 'repo-1') {
          listFetchCount++;
        }
        return passthrough();
      })
    );

    renderTaskStudio('/app/repositories/repo-1/studios/tasks');

    await waitFor(() => {
      expect(
        screen.getByRole('heading', { level: 2, name: /Optimize Vector Similarity Query Index/i })
      ).toBeInTheDocument();
    });

    // Selecting another task should NOT refetch the task list
    const taskButton = screen.getByRole('button', { name: /Fix Token Budget Overflow in AST Analyzer/i });
    fireEvent.click(taskButton);

    await waitFor(() => {
      expect(
        screen.getByRole('heading', { level: 2, name: /Fix Token Budget Overflow in AST Analyzer/i })
      ).toBeInTheDocument();
    });

    // List fetch should only have happened once
    expect(listFetchCount).toBe(1);
  });
});
