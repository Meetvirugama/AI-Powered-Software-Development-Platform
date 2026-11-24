import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';
import { resetMockStore } from '../mocks/handlers';
import RepositoryTaskStudio from '../pages/RepositoryTaskStudio';
import { ToolsIntegrationsAdminPage } from '../pages/ToolsIntegrationsAdminPage';
import { Tasks } from '../pages/Tasks';
import { CreateTask } from '../pages/CreateTask';
import { CodeChangesPanel } from '../components/tasks/CodeChangesPanel';
import { RepairBudgetTracker } from '../components/tasks/RepairBudgetTracker';
import { PublicationPanel } from '../components/tasks/PublicationPanel';
import { TaskVerificationPhasePanel } from '../components/taskStudio/TaskPhasePanels';
import { TaskStatus } from '../types/task';

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
      mutations: {
        retry: false,
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

function mockRepoLanguage(language: string | null) {
  server.use(
    http.get('*/api/v1/repositories/:repositoryId', ({ params }) => {
      return HttpResponse.json({
        id: String(params.repositoryId),
        name: 'demo-repo',
        full_name: `org/${params.repositoryId}`,
        owner: 'org',
        description: 'Test repository',
        default_branch: 'main',
        language,
        sync_status: 'ready',
        last_synced_at: '2026-01-01T00:00:00Z',
      });
    })
  );
}

describe('M2 UI/UX Polish & Accessibility Verification', () => {
  beforeEach(() => {
    resetMockStore();
  });

  describe('RepositoryTaskStudio responsive drawers, modals & language-aware test runner (F5)', () => {
    it('toggles mobile task drawer via button, closes on Escape and backdrop, and auto-closes on task selection', async () => {
      renderTaskStudio('/app/repositories/repo-1/studios/tasks');

      await waitFor(() => {
        expect(
          screen.getByRole('heading', { level: 2, name: /Optimize Vector Similarity Query Index/i })
        ).toBeInTheDocument();
      });

      const toggleBtn = screen.getByRole('button', { name: /Toggle task list/i });
      const sidebar = document.getElementById('task-studio-sidebar');
      expect(sidebar).not.toBeNull();
      expect(toggleBtn).toHaveAttribute('aria-expanded', 'false');
      expect(sidebar?.className).toContain('-translate-x-full');

      // Open drawer
      fireEvent.click(toggleBtn);
      expect(toggleBtn).toHaveAttribute('aria-expanded', 'true');
      expect(sidebar?.className).toContain('translate-x-0');

      // Close via Escape
      fireEvent.keyDown(window, { key: 'Escape' });
      expect(toggleBtn).toHaveAttribute('aria-expanded', 'false');
      expect(sidebar?.className).toContain('-translate-x-full');

      // Open again and close via backdrop click
      fireEvent.click(toggleBtn);
      expect(toggleBtn).toHaveAttribute('aria-expanded', 'true');
      const backdrop = sidebar?.previousElementSibling;
      expect(backdrop).not.toBeNull();
      expect(backdrop).toHaveAttribute('aria-hidden', 'true');
      if (backdrop) {
        fireEvent.click(backdrop);
      }
      expect(toggleBtn).toHaveAttribute('aria-expanded', 'false');
      expect(sidebar?.className).toContain('-translate-x-full');

      // Open again and close via close button
      fireEvent.click(toggleBtn);
      expect(toggleBtn).toHaveAttribute('aria-expanded', 'true');
      fireEvent.click(screen.getByRole('button', { name: /Close task list/i }));
      expect(toggleBtn).toHaveAttribute('aria-expanded', 'false');

      // Open again and select a task -> auto-closes drawer
      fireEvent.click(toggleBtn);
      expect(toggleBtn).toHaveAttribute('aria-expanded', 'true');
      fireEvent.click(screen.getByRole('button', { name: /Fix Token Budget Overflow in AST Analyzer/i }));
      expect(toggleBtn).toHaveAttribute('aria-expanded', 'false');
    });

    it('mutually excludes mobile task drawer and Activity feed and wires phase tabpanel ARIA', async () => {
      renderTaskStudio('/app/repositories/repo-1/studios/tasks');

      await waitFor(() => {
        expect(screen.getByRole('tablist', { name: /Task workflow phases/i })).toBeInTheDocument();
      });

      const tasksToggleBtn = screen.getByRole('button', { name: /Toggle task list/i });
      const activityBtn = screen.getByRole('button', { name: /Activity/i });

      // Open mobile task drawer, then open Activity -> task drawer closes
      fireEvent.click(tasksToggleBtn);
      expect(tasksToggleBtn).toHaveAttribute('aria-expanded', 'true');
      fireEvent.click(activityBtn);
      expect(activityBtn).toHaveAttribute('aria-pressed', 'true');
      expect(tasksToggleBtn).toHaveAttribute('aria-expanded', 'false');

      // Open mobile task drawer while Activity is open -> Activity closes
      fireEvent.click(tasksToggleBtn);
      expect(tasksToggleBtn).toHaveAttribute('aria-expanded', 'true');
      expect(activityBtn).toHaveAttribute('aria-pressed', 'false');

      // Verify phase tabpanel ARIA wiring
      const testsTab = screen.getByRole('tab', { name: /3\. Tests/i });
      expect(testsTab).toHaveAttribute('id', 'studio-tab-tests');
      expect(testsTab).toHaveAttribute('aria-controls', 'studio-tabpanel-tests');
      fireEvent.click(testsTab);

      const activeTabPanel = screen.getByRole('tabpanel');
      expect(activeTabPanel).toHaveAttribute('id', 'studio-tabpanel-tests');
      expect(activeTabPanel).toHaveAttribute('aria-labelledby', 'studio-tab-tests');
    });

    it('renders accessible Activity & Import buttons and closes Activity feed via Escape', async () => {
      renderTaskStudio('/app/repositories/repo-1/studios/tasks');

      await waitFor(() => {
        expect(screen.getByRole('tablist', { name: /Task workflow phases/i })).toBeInTheDocument();
      });

      const activityBtn = screen.getByRole('button', { name: /Activity/i });
      expect(activityBtn.className).not.toContain('hidden');
      expect(activityBtn).toHaveAttribute('aria-pressed', 'false');

      fireEvent.click(activityBtn);
      expect(activityBtn).toHaveAttribute('aria-pressed', 'true');
      expect(screen.getByRole('complementary', { name: /Activity Feed/i })).toBeInTheDocument();

      fireEvent.keyDown(window, { key: 'Escape' });
      expect(activityBtn).toHaveAttribute('aria-pressed', 'false');
      expect(screen.queryByRole('complementary', { name: /Activity Feed/i })).not.toBeInTheDocument();

      const importBtn = screen.getByRole('button', { name: /Import GitHub Issue/i });
      expect(importBtn.className).not.toContain('hidden');
    });

    it('exposes dialog ARIA, labels, backdrop click-to-close, and Escape close on New Task and Import Issue modals', async () => {
      renderTaskStudio('/app/repositories/repo-1/studios/tasks');

      await waitFor(() => {
        expect(screen.getByRole('tablist')).toBeInTheDocument();
      });

      // Open New Task modal
      fireEvent.click(screen.getByRole('button', { name: /New Task/i }));
      const newTaskDialog = screen.getByRole('dialog');
      expect(newTaskDialog).toHaveAttribute('aria-modal', 'true');
      expect(newTaskDialog).toHaveAttribute('aria-labelledby', 'new-task-modal-title');
      expect(screen.getByLabelText(/What do you want the AI to build or fix\?/i)).toBeInTheDocument();

      // Backdrop click closes modal
      fireEvent.click(newTaskDialog);
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

      // Open Import Issue modal
      fireEvent.click(screen.getByRole('button', { name: /Import GitHub Issue/i }));
      const importDialog = screen.getByRole('dialog');
      expect(importDialog).toHaveAttribute('aria-modal', 'true');
      expect(importDialog).toHaveAttribute('aria-labelledby', 'import-issue-modal-title');
      expect(screen.getByLabelText(/GitHub Issue Number/i)).toBeInTheDocument();

      // Escape closes modal
      fireEvent.keyDown(window, { key: 'Escape' });
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it.each([
      ['Python', 'Run Pytest'],
      ['TypeScript', 'Run Vitest'],
      ['Rust', 'Run Cargo Test'],
      ['Go', 'Run Go Test'],
      [null, 'Run Tests'],
    ])('resolves language %s to test runner button "%s"', async (language, expectedLabel) => {
      mockRepoLanguage(language);
      renderTaskStudio('/app/repositories/repo-1/studios/tasks');

      await waitFor(() => {
        expect(screen.getByRole('tab', { name: /3\. Tests/i })).toBeInTheDocument();
      });

      const testsTab = screen.getByRole('tab', { name: /3\. Tests/i });
      fireEvent.click(testsTab);
      expect(testsTab).toHaveAttribute('aria-selected', 'true');

      await waitFor(() => {
        expect(screen.getByRole('button', { name: expectedLabel })).toBeInTheDocument();
      });
    });

    it('resets publication authorization checkbox when switching between tasks', async () => {
      renderTaskStudio('/app/repositories/repo-1/studios/tasks');

      await waitFor(() => {
        expect(screen.getByRole('tab', { name: /6\. Pull Request/i })).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole('tab', { name: /6\. Pull Request/i }));

      const checkbox = await screen.findByRole('checkbox');
      fireEvent.click(checkbox);
      expect(checkbox).toBeChecked();

      // Switch to second task and check PR tab again
      fireEvent.click(screen.getByRole('button', { name: /Fix Token Budget Overflow in AST Analyzer/i }));
      await waitFor(() => {
        expect(
          screen.getByRole('heading', { level: 2, name: /Fix Token Budget Overflow in AST Analyzer/i })
        ).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole('tab', { name: /6\. Pull Request/i }));
      const nextCheckbox = await screen.findByRole('checkbox');
      expect(nextCheckbox).toBeInTheDocument();
      expect(nextCheckbox).not.toBeChecked();
    });

    it('renders horizontal scroll and shrink-0 line gutters on TaskVerificationPhasePanel diff', () => {
      const { container } = render(
        <TaskVerificationPhasePanel
          unifiedDiff={'@@ -1,1 +1,1 @@\n-const a = 1;\n+const a = "very_long_line_that_must_scroll_horizontally_without_clipping";'}
          repairAttempt={0}
          maxRepairAttempts={3}
          testsPassed={1}
          testsFailed={0}
        />
      );
      const scrollBox = container.querySelector('.overflow-auto');
      expect(scrollBox).not.toBeNull();
      const innerMinWMax = scrollBox?.querySelector('.min-w-max');
      expect(innerMinWMax).not.toBeNull();
    });
  });

  describe('ToolsIntegrationsAdminPage accessibility, validation & non-silent errors (F7)', () => {
    it('associates explicit labels, validates empty submissions inline, and clears errors on typing', () => {
      render(<ToolsIntegrationsAdminPage />);

      const nameInput = screen.getByLabelText(/Server Name/i);
      const transportSelect = screen.getByLabelText(/Transport/i);
      const endpointInput = screen.getByLabelText(/Command or Endpoint URL/i);

      expect(nameInput).toHaveAttribute('placeholder', 'Server display name');
      expect(transportSelect).toHaveValue('stdio');
      expect(endpointInput).toHaveAttribute('placeholder', 'Command or endpoint URL');

      // Submit empty form -> displays inline validation errors
      fireEvent.click(screen.getByRole('button', { name: /Register MCP Server/i }));
      expect(screen.getByText(/Server display name is required\./i)).toBeInTheDocument();
      expect(screen.getByText(/Command or endpoint URL is required\./i)).toBeInTheDocument();

      // Typing clears validation errors
      fireEvent.change(nameInput, { target: { value: 'My MCP' } });
      expect(screen.queryByText(/Server display name is required\./i)).not.toBeInTheDocument();
    });

    it('renders search empty state with Clear filter button and exposes aria-expanded/aria-pressed', () => {
      render(<ToolsIntegrationsAdminPage />);

      const inspectBtn = screen.getAllByRole('button', { name: /Inspect Schema/i })[0];
      expect(inspectBtn).toHaveAttribute('aria-expanded', 'false');
      fireEvent.click(inspectBtn);
      expect(screen.getByRole('button', { name: /Hide Schema/i })).toHaveAttribute('aria-expanded', 'true');

      const toggleServerBtn = screen.getByRole('button', { name: /Disable Server/i });
      expect(toggleServerBtn).toHaveAttribute('aria-pressed', 'true');
      fireEvent.click(toggleServerBtn);
      expect(screen.getByRole('button', { name: /Enable Server/i })).toHaveAttribute('aria-pressed', 'false');

      // Search unmatched query -> empty state + Clear filter
      const searchBox = screen.getByRole('searchbox', { name: /Filter servers or tools/i });
      fireEvent.change(searchBox, { target: { value: 'nonexistent-mcp-xyz' } });
      expect(screen.getByText(/No MCP servers match "nonexistent-mcp-xyz"\./i)).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /Clear filter/i }));
      expect(screen.getByText('Platform Repository Intelligence MCP')).toBeInTheDocument();
    });

    it('surfaces non-silent warning/error banners when MCP API calls fail while keeping fallback servers', async () => {
      server.use(
        http.get('*/api/v1/mcp/servers', () => HttpResponse.json({ message: 'Offline' }, { status: 503 })),
        http.post('*/api/v1/mcp/servers/:id/ping', () =>
          HttpResponse.json({ message: 'Handshake timeout' }, { status: 503 })
        )
      );

      render(<ToolsIntegrationsAdminPage />);

      // Initial fallback stays visible
      expect(screen.getByText('Platform Repository Intelligence MCP')).toBeInTheDocument();

      // Offline warning surfaces after listMCPServers rejects
      await waitFor(() => {
        expect(screen.getByText(/Live MCP registry is unreachable/i)).toBeInTheDocument();
      });

      // Trigger ping -> non-silent error banner appears
      fireEvent.click(screen.getByRole('button', { name: /Ping Handshake/i }));
      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent(/Ping handshake failed/i);
      });
    });

    it.each([
      ['HTTP 404', () => HttpResponse.json({ message: 'Not found' }, { status: 404 })],
      ['NETWORK_ERROR', () => HttpResponse.error()],
    ])('retains registered server in local session on POST /mcp/servers %s', async (_label, handler) => {
      server.use(
        http.get('*/api/v1/mcp/servers', () => HttpResponse.json([], { status: 200 })),
        http.post('*/api/v1/mcp/servers', handler)
      );

      render(<ToolsIntegrationsAdminPage />);

      const nameInput = screen.getByLabelText(/Server Name/i);
      const endpointInput = screen.getByLabelText(/Command or Endpoint URL/i);
      fireEvent.change(nameInput, { target: { value: 'Local Session MCP' } });
      fireEvent.change(endpointInput, { target: { value: 'npx local-mcp' } });
      fireEvent.click(screen.getByRole('button', { name: /Register MCP Server/i }));

      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent(
          /Registered "Local Session MCP" in local session only/i
        );
      });
      expect(screen.getByRole('heading', { level: 2, name: 'Local Session MCP' })).toBeInTheDocument();
    });

    it('does not let a late-resolving initial listMCPServers overwrite local mutations', async () => {
      let resolveList!: (value: Response) => void;
      const listPromise = new Promise<Response>((resolve) => {
        resolveList = resolve;
      });
      server.use(
        http.get('*/api/v1/mcp/servers', () => listPromise),
        http.post('*/api/v1/mcp/servers', () => HttpResponse.json({ message: 'Not found' }, { status: 404 }))
      );

      render(<ToolsIntegrationsAdminPage />);

      fireEvent.change(screen.getByLabelText(/Server Name/i), { target: { value: 'Early Local MCP' } });
      fireEvent.change(screen.getByLabelText(/Command or Endpoint URL/i), { target: { value: 'npx early-mcp' } });
      fireEvent.click(screen.getByRole('button', { name: /Register MCP Server/i }));

      await waitFor(() => {
        expect(screen.getByRole('heading', { level: 2, name: 'Early Local MCP' })).toBeInTheDocument();
      });

      // Now resolve the initial GET with an empty list
      resolveList(HttpResponse.json([], { status: 200 }));

      await waitFor(() => {
        expect(screen.queryByRole('status', { name: /Syncing registry/i })).not.toBeInTheDocument();
      });
      expect(screen.getByRole('heading', { level: 2, name: 'Early Local MCP' })).toBeInTheDocument();
    });
  });

  describe('Tasks, CreateTask, CodeChangesPanel & RepairBudgetTracker polish (F6)', () => {
    it('resets pagination to page 1 when clicking Clear search in Tasks', async () => {
      server.use(
        http.get('*/api/v1/tasks', ({ request }) => {
          const url = new URL(request.url);
          const page = Number(url.searchParams.get('page') || '1');
          const search = url.searchParams.get('search') || '';
          const items = Array.from({ length: 12 }, (_, idx) => ({
            task_id: `task-p${page}-${idx}`,
            repository_id: 'repo-1',
            title: search ? `Matched ${search} #${idx}` : `Task Page ${page} #${idx}`,
            description: 'Test task',
            status: 'CREATED',
            source: { type: 'USER_PROMPT', repository_id: 'repo-1' },
            requirements: [],
            assumptions: [],
            constraints: [],
            base_revision: 'abc',
            plan_version: 1,
            approved_plan_version: null,
            repair_attempts_used: 0,
            repair_attempts_max: 3,
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
          }));
          return HttpResponse.json({ items, total: 24, page, page_size: 12 });
        })
      );

      const queryClient = createTestQueryClient();
      render(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={['/app/tasks']}>
            <Tasks />
          </MemoryRouter>
        </QueryClientProvider>
      );

      await waitFor(() => {
        expect(screen.getByText(/Page 1 of 2/i)).toBeInTheDocument();
      });

      // Navigate to page 2
      fireEvent.click(screen.getByRole('button', { name: /Next Page/i }));
      await waitFor(() => {
        expect(screen.getByText(/Page 2 of 2/i)).toBeInTheDocument();
      });

      // Type search -> resets to page 1, navigate to page 2 again, then click Clear search
      const searchBox = screen.getByRole('searchbox');
      fireEvent.change(searchBox, { target: { value: 'alpha' } });
      await waitFor(() => {
        expect(screen.getByText(/Page 1 of 2/i)).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole('button', { name: /Next Page/i }));
      await waitFor(() => {
        expect(screen.getByText(/Page 2 of 2/i)).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole('button', { name: /Clear search/i }));
      await waitFor(() => {
        expect(screen.getByText(/Page 1 of 2/i)).toBeInTheDocument();
      });
    });

    it('uses accessible group and toggle buttons on CreateTask mode switcher without nested tab/button', () => {
      const queryClient = createTestQueryClient();
      render(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={['/app/tasks/new']}>
            <CreateTask />
          </MemoryRouter>
        </QueryClientProvider>
      );

      expect(screen.getByRole('group', { name: /Task creation mode/i })).toBeInTheDocument();
      expect(screen.queryByRole('tablist')).not.toBeInTheDocument();
      expect(screen.queryByRole('tab')).not.toBeInTheDocument();

      const manualBtn = screen.getByRole('button', { name: /Manual Task Creation/i });
      const githubBtn = screen.getByRole('button', { name: /Import from GitHub Issue/i });

      expect(manualBtn).toHaveAttribute('aria-pressed', 'true');
      expect(githubBtn).toHaveAttribute('aria-pressed', 'false');

      fireEvent.click(githubBtn);
      expect(manualBtn).toHaveAttribute('aria-pressed', 'false');
      expect(githubBtn).toHaveAttribute('aria-pressed', 'true');
    });

    it('renders PublicationPanel target-repo-display loading state without React DOM nesting errors', async () => {
      server.use(
        http.get('*/api/v1/repositories/repo-loading-test', () => new Promise(() => {})),
        http.get('*/api/v1/tasks/task-pub-loading/verification', () =>
          HttpResponse.json({
            task_id: 'task-pub-loading',
            status: 'PASSED',
            passed: true,
            verified_revision: 'abc1234567890',
            blocking_findings: [],
            checks: [],
            verified_at: '2026-01-01T00:00:00Z',
          })
        ),
        http.get('*/api/v1/tasks/task-pub-loading/stale-check', () =>
          HttpResponse.json({ is_stale: false, current_head: 'abc1234567890' })
        )
      );

      const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      try {
        const queryClient = createTestQueryClient();
        render(
          <QueryClientProvider client={queryClient}>
            <PublicationPanel
              task={{
                task_id: 'task-pub-loading',
                repository_id: 'repo-loading-test',
                title: 'Publication loading test',
                description: 'Verify valid HTML nesting while repo metadata loads',
                status: TaskStatus.READY_FOR_PUBLICATION,
                source: { type: 'USER_PROMPT', repository_id: 'repo-loading-test' },
                requirements: [],
                assumptions: [],
                constraints: [],
                base_revision: 'abc1234567890',
                plan_version: 1,
                approved_plan_version: 1,
                repair_attempts_used: 0,
                repair_attempts_max: 3,
                created_at: '2026-01-01T00:00:00Z',
                updated_at: '2026-01-01T00:00:00Z',
              }}
            />
          </QueryClientProvider>
        );

        const targetRepoDisplay = await screen.findByTestId('target-repo-display');
        expect(targetRepoDisplay.tagName).toBe('DIV');
        expect(targetRepoDisplay).toHaveTextContent(/Loading/i);

        const nestingWarnings = errorSpy.mock.calls
          .flat()
          .map(String)
          .filter((msg) => msg.includes('cannot be a descendant of') || msg.includes('hydration error'));
        expect(nestingWarnings).toHaveLength(0);
      } finally {
        errorSpy.mockRestore();
      }
    });

    it('applies full-width diff pre sizing in CodeChangesPanel and responsive grid in RepairBudgetTracker', () => {
      const queryClient = createTestQueryClient();
      const { container: diffContainer } = render(
        <QueryClientProvider client={queryClient}>
          <CodeChangesPanel
            diffData={{
              task_id: 't-1',
              total_files_changed: 1,
              total_additions: 1,
              total_deletions: 0,
              files: [
                {
                  file_path: 'src/very_long_module_path.ts',
                  status: 'modified',
                  additions: 1,
                  deletions: 0,
                  patch: '@@ -1,1 +1,2 @@\n+export const x = "very_long_line_that_overflows_mobile_viewport";',
                },
              ],
            }}
          />
        </QueryClientProvider>
      );
      const preEl = diffContainer.querySelector('pre');
      expect(preEl?.className).toContain('min-w-full');
      expect(preEl?.className).toContain('w-max');

      const { container: budgetContainer } = render(
        <QueryClientProvider client={queryClient}>
          <RepairBudgetTracker
            repairAttemptsUsed={2}
            repairAttemptsMax={5}
            history={[]}
          />
        </QueryClientProvider>
      );
      const slot1 = budgetContainer.querySelector('[data-testid="repair-slot-1"]');
      expect(slot1?.parentElement?.getAttribute('style')).toBeNull();
      expect(slot1?.parentElement?.className).toContain('grid-cols-2');
    });
  });
});
