import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ProjectMemoryPanel } from '../components/explorer/ProjectMemoryPanel';
import {
  listMemories,
  pinArchitecturalRule,
  updateMemory,
  deleteMemory,
  listMCPResources,
} from '../services/memory';
import { resetMockMemoryStore } from '../mocks/handlers';

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe('Project Memory & Knowledge Management (F36 / Issue #217)', () => {
  beforeEach(() => {
    resetMockMemoryStore();
    vi.clearAllMocks();
  });

  describe('Memory Service API', () => {
    it('fetches paginated memory entries for a repository', async () => {
      const res = await listMemories('repo-1');
      expect(res.total).toBeGreaterThanOrEqual(4);
      expect(res.items.some((i) => i.type === 'rule')).toBe(true);
      expect(res.items.some((i) => i.type === 'decision')).toBe(true);
    });

    it('filters memories by type and query', async () => {
      const res = await listMemories('repo-1', { type: 'rule', query: 'SQL' });
      expect(res.items.length).toBeGreaterThanOrEqual(1);
      expect(res.items[0].content).toContain('SQL');
    });

    it('pins an architectural rule successfully', async () => {
      const newRule = await pinArchitecturalRule('repo-1', {
        rule: 'Always sanitize external input before executing shell commands.',
        source: 'user_pinned',
      });
      expect(newRule.id).toBeDefined();
      expect(newRule.type).toBe('rule');
      expect(newRule.content).toContain('Always sanitize external input');

      const listed = await listMemories('repo-1', { type: 'rule' });
      expect(listed.items.some((i) => i.id === newRule.id)).toBe(true);
    });

    it('updates an existing memory entry', async () => {
      const updated = await updateMemory('repo-1', 'mem-1', {
        status: 'archived',
        content: 'Updated parameterized SQL guideline.',
      });
      expect(updated.status).toBe('archived');
      expect(updated.content).toBe('Updated parameterized SQL guideline.');
    });

    it('deletes a memory entry', async () => {
      await deleteMemory('repo-1', 'mem-1');
      const listed = await listMemories('repo-1');
      expect(listed.items.some((i) => i.id === 'mem-1')).toBe(false);
    });

    it('fetches exposed MCP memory resources with valid URIs', async () => {
      const mcp = await listMCPResources('repo-1');
      expect(mcp.resources.length).toBeGreaterThanOrEqual(4);
      const ruleRes = mcp.resources.find((r) => r.uri.endsWith('/rules'));
      expect(ruleRes).toBeDefined();
      expect(ruleRes?.uri).toBe('memory://repo/repo-1/rules');
      expect(ruleRes?.mimeType).toBe('text/markdown');
    });
  });

  describe('ProjectMemoryPanel Component', () => {
    it('renders memory list and badges when open', async () => {
      render(
        <ProjectMemoryPanel isOpen={true} onClose={vi.fn()} repositoryId="repo-1" />,
        { wrapper: createWrapper() }
      );

      expect(screen.getByText('Project Memory & Knowledge')).toBeInTheDocument();
      await waitFor(() => {
        expect(
          screen.getByText('Always use parameterized SQL queries in repositories.')
        ).toBeInTheDocument();
      });
      expect(screen.getByText(/Task 'Add JWT blocklist' completed successfully/)).toBeInTheDocument();
    });

    it('filters entries when clicking Rules tab', async () => {
      render(
        <ProjectMemoryPanel isOpen={true} onClose={vi.fn()} repositoryId="repo-1" />,
        { wrapper: createWrapper() }
      );

      await waitFor(() => {
        expect(screen.getByText('Always use parameterized SQL queries in repositories.')).toBeInTheDocument();
      });

      const rulesTab = screen.getByRole('button', { name: 'Rules' });
      fireEvent.click(rulesTab);

      await waitFor(() => {
        expect(screen.getByText('Always use parameterized SQL queries in repositories.')).toBeInTheDocument();
        expect(screen.queryByText(/Task 'Add JWT blocklist'/)).not.toBeInTheDocument();
      });
    });

    it('switches to MCP Resources tab and renders resource URIs', async () => {
      render(
        <ProjectMemoryPanel isOpen={true} onClose={vi.fn()} repositoryId="repo-1" />,
        { wrapper: createWrapper() }
      );

      const mcpTab = screen.getByRole('button', { name: 'MCP Resources' });
      fireEvent.click(mcpTab);

      await waitFor(() => {
        expect(screen.getByText('memory://repo/repo-1/rules')).toBeInTheDocument();
      });
      expect(screen.getByText('Model Context Protocol (MCP 2025-11-25) Integration')).toBeInTheDocument();
    });

    it('opens Pin Rule form and pins new convention', async () => {
      render(
        <ProjectMemoryPanel isOpen={true} onClose={vi.fn()} repositoryId="repo-1" />,
        { wrapper: createWrapper() }
      );

      const pinButton = screen.getByRole('button', { name: /Pin Rule/i });
      fireEvent.click(pinButton);

      expect(screen.getByPlaceholderText(/All Redis locks must specify an explicit TTL/)).toBeInTheDocument();
      const textarea = screen.getByPlaceholderText(/All Redis locks must specify an explicit TTL/);
      fireEvent.change(textarea, { target: { value: 'Always enforce rate limits on public endpoints.' } });

      const submitButton = screen.getByRole('button', { name: 'Confirm Pin Rule' });
      fireEvent.click(submitButton);

      await waitFor(() => {
        expect(screen.getByText('Always enforce rate limits on public endpoints.')).toBeInTheDocument();
      });
    });
  });
});
