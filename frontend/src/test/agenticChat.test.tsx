import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';
import { RepositoryChat } from '../pages/RepositoryChat';

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

function renderRepositoryChat(initialRoute = '/app/repositories/test-repo-123/chat') {
  const queryClient = createTestQueryClient();
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[initialRoute]}>
          <Routes>
            <Route path="/app/repositories/:id/chat" element={<RepositoryChat />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    ),
  };
}

describe('Bounded Agentic Repository Chat UI (Issue #188 / F08)', () => {
  beforeEach(() => {
    // Mock repository details
    server.use(
      http.get('*/api/v1/repositories/test-repo-123', () => {
        return HttpResponse.json({
          id: 'test-repo-123',
          name: 'test-repo',
          full_name: 'org/test-repo',
          default_branch: 'main',
          is_active: true,
        });
      }),
    );
  });

  it('renders mode selector defaulting to Normal Chat', async () => {
    renderRepositoryChat();

    const normalBtn = await screen.findByRole('button', { name: /Normal Chat/i });
    const agenticBtn = screen.getByRole('button', { name: /Agentic Chat/i });

    expect(normalBtn).toBeInTheDocument();
    expect(agenticBtn).toBeInTheDocument();
    expect(normalBtn).toHaveAttribute('aria-pressed', 'true');
    expect(agenticBtn).toHaveAttribute('aria-pressed', 'false');
  });

  it('allows switching to Agentic Chat mode', async () => {
    renderRepositoryChat();

    const normalBtn = await screen.findByRole('button', { name: /Normal Chat/i });
    const agenticBtn = screen.getByRole('button', { name: /Agentic Chat/i });

    fireEvent.click(agenticBtn);

    expect(normalBtn).toHaveAttribute('aria-pressed', 'false');
    expect(agenticBtn).toHaveAttribute('aria-pressed', 'true');
  });

  it('sends mode: "agentic" in request payload and displays agent metadata on response', async () => {
    let capturedPayload: any = null;

    server.use(
      http.post('*/api/v1/repositories/test-repo-123/chat', async ({ request }) => {
        capturedPayload = await request.json();
        return HttpResponse.json({
          answer: 'The authentication service uses JWT tokens verified via RS256.',
          sources: [
            {
              file: 'src/auth/jwt.py',
              start_line: 15,
              end_line: 45,
              symbol: 'verify_token',
            },
          ],
          confidence: 'high',
          status: 'completed',
          agent_metadata: {
            mode: 'agentic',
            rounds: 2,
            tools_called: 3,
            duration_ms: 1420,
            evidence_count: 2,
            tool_summary: [
              { tool: 'search_code', input: { query: 'verify_token' } },
              { tool: 'get_symbol', input: { name: 'verify_token' } },
              { tool: 'read_file_range', input: { path: 'src/auth/jwt.py', start_line: 1, end_line: 50 } },
            ],
          },
        });
      }),
    );

    renderRepositoryChat();

    // Switch to agentic mode
    const agenticBtn = await screen.findByRole('button', { name: /Agentic Chat/i });
    fireEvent.click(agenticBtn);

    // Type a question
    const textarea = screen.getByRole('textbox', { name: /Ask a question about/i });
    fireEvent.change(textarea, { target: { value: 'How does authentication token verification work?' } });

    // Send
    const sendBtn = screen.getByRole('button', { name: /Send/i });
    fireEvent.click(sendBtn);

    // Verify received response
    await waitFor(() => {
      expect(screen.getByText(/The authentication service uses JWT tokens verified via RS256/i)).toBeInTheDocument();
    });

    // Verify payload sent had mode: 'agentic'
    expect(capturedPayload).not.toBeNull();
    expect(capturedPayload.mode).toBe('agentic');
    expect(capturedPayload.question).toBe('How does authentication token verification work?');

    // Verify Agentic mode badge is displayed
    expect(screen.getByText('Agentic mode')).toBeInTheDocument();
    expect(screen.getByText('3 tool calls')).toBeInTheDocument();
    expect(screen.getByText('1.4s')).toBeInTheDocument();

    // Verify view tools toggle works
    const viewToolsBtn = screen.getByRole('button', { name: /View tools/i });
    expect(viewToolsBtn).toBeInTheDocument();
    fireEvent.click(viewToolsBtn);

    // Expanded tool list should show tools called
    expect(screen.getByText('search_code')).toBeInTheDocument();
    expect(screen.getByText('get_symbol')).toBeInTheDocument();
    expect(screen.getByText('read_file_range')).toBeInTheDocument();
  });
});
