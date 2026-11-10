/**
 * MSW Mock Handlers for Project Memory & MCP Resources (Issue #217).
 */

import { http, HttpResponse } from 'msw';
import type {
  CreateMemoryPayload,
  MCPMemoryResource,
  MemoryEntry,
  PinRulePayload,
  UpdateMemoryPayload,
} from '../../types/memory';

let mockMemories: MemoryEntry[] = [
  {
    id: 'mem-1',
    repository_id: 'repo-1',
    type: 'rule',
    content: 'Always use parameterized SQL queries in repositories.',
    source: 'user_pinned',
    status: 'active',
    created_at: new Date(Date.now() - 3600000 * 24).toISOString(),
    updated_at: new Date(Date.now() - 3600000 * 24).toISOString(),
  },
  {
    id: 'mem-2',
    repository_id: 'repo-1',
    type: 'decision',
    content: 'Use PostgreSQL with pgvector for relational code intelligence and embeddings.',
    source: 'architectural_decision',
    status: 'active',
    created_at: new Date(Date.now() - 3600000 * 12).toISOString(),
    updated_at: new Date(Date.now() - 3600000 * 12).toISOString(),
  },
  {
    id: 'mem-3',
    repository_id: 'repo-1',
    type: 'task_summary',
    content: "Task 'Add JWT blocklist' completed successfully. Verification: All tests passed. Repair attempts used: 0.",
    source: 'task:task-jwt-1',
    status: 'active',
    created_at: new Date(Date.now() - 3600000 * 6).toISOString(),
    updated_at: new Date(Date.now() - 3600000 * 6).toISOString(),
  },
  {
    id: 'mem-4',
    repository_id: 'repo-1',
    type: 'failure',
    content: "Task 'Redis lock refactor' failed. Failure diagnosis: Deadlock under stress testing. Repair attempts exhausted: 3.",
    source: 'task:task-redis-1',
    status: 'active',
    created_at: new Date(Date.now() - 3600000 * 2).toISOString(),
    updated_at: new Date(Date.now() - 3600000 * 2).toISOString(),
  },
];

export function resetMockMemoryStore() {
  mockMemories = [
    {
      id: 'mem-1',
      repository_id: 'repo-1',
      type: 'rule',
      content: 'Always use parameterized SQL queries in repositories.',
      source: 'user_pinned',
      status: 'active',
      created_at: new Date(Date.now() - 3600000 * 24).toISOString(),
      updated_at: new Date(Date.now() - 3600000 * 24).toISOString(),
    },
    {
      id: 'mem-2',
      repository_id: 'repo-1',
      type: 'decision',
      content: 'Use PostgreSQL with pgvector for relational code intelligence and embeddings.',
      source: 'architectural_decision',
      status: 'active',
      created_at: new Date(Date.now() - 3600000 * 12).toISOString(),
      updated_at: new Date(Date.now() - 3600000 * 12).toISOString(),
    },
    {
      id: 'mem-3',
      repository_id: 'repo-1',
      type: 'task_summary',
      content: "Task 'Add JWT blocklist' completed successfully. Verification: All tests passed. Repair attempts used: 0.",
      source: 'task:task-jwt-1',
      status: 'active',
      created_at: new Date(Date.now() - 3600000 * 6).toISOString(),
      updated_at: new Date(Date.now() - 3600000 * 6).toISOString(),
    },
    {
      id: 'mem-4',
      repository_id: 'repo-1',
      type: 'failure',
      content: "Task 'Redis lock refactor' failed. Failure diagnosis: Deadlock under stress testing. Repair attempts exhausted: 3.",
      source: 'task:task-redis-1',
      status: 'active',
      created_at: new Date(Date.now() - 3600000 * 2).toISOString(),
      updated_at: new Date(Date.now() - 3600000 * 2).toISOString(),
    },
  ];
}

export const memoryHandlers = [
  // List MCP resources
  http.get('*/api/v1/repositories/:repoId/memories/mcp-resources', ({ params }) => {
    const { repoId } = params;
    const resources: MCPMemoryResource[] = [
      {
        uri: `memory://repo/${repoId}/rules`,
        name: 'Project Architectural Rules',
        mimeType: 'text/markdown',
        description: 'Active conventions and rules',
        text: '# Project Architectural Rules\n> Always use parameterized SQL queries in repositories.',
        entries_count: mockMemories.filter((m) => m.repository_id === repoId && m.type === 'rule').length,
      },
      {
        uri: `memory://repo/${repoId}/decisions`,
        name: 'Project Decisions',
        mimeType: 'text/markdown',
        description: 'Architectural and technical decisions',
        text: '# Project Decisions\n> Use PostgreSQL with pgvector',
        entries_count: mockMemories.filter((m) => m.repository_id === repoId && m.type === 'decision').length,
      },
      {
        uri: `memory://repo/${repoId}/task-summaries`,
        name: 'Task Summaries',
        mimeType: 'text/markdown',
        description: 'Completed task summaries',
        text: '# Task Summaries\n> Completed tasks',
        entries_count: mockMemories.filter((m) => m.repository_id === repoId && m.type === 'task_summary').length,
      },
      {
        uri: `memory://repo/${repoId}/failures`,
        name: 'Task Failures',
        mimeType: 'text/markdown',
        description: 'Recorded failures and negative feedback',
        text: '# Task Failures\n> Failed tasks',
        entries_count: mockMemories.filter((m) => m.repository_id === repoId && m.type === 'failure').length,
      },
      {
        uri: `memory://repo/${repoId}/all`,
        name: 'All Project Memories',
        mimeType: 'text/markdown',
        description: 'Complete active repository memory ledger',
        text: '# All Project Memories\n> All entries',
        entries_count: mockMemories.filter((m) => m.repository_id === repoId).length,
      },
    ];
    return HttpResponse.json({ resources });
  }),

  // Resolve specific MCP resource
  http.get('*/api/v1/repositories/:repoId/memories/mcp-resources/:slug', ({ params }) => {
    const { repoId, slug } = params;
    const res: MCPMemoryResource = {
      uri: `memory://repo/${repoId}/${slug}`,
      name: `MCP Resource for ${slug}`,
      mimeType: 'text/markdown',
      description: `Resource ${slug}`,
      text: `# Resource ${slug}\n> Repository ${repoId}`,
      entries_count: mockMemories.filter((m) => m.repository_id === repoId).length,
    };
    return HttpResponse.json(res);
  }),

  // Pin architectural rule
  http.post('*/api/v1/repositories/:repoId/memories/rules', async ({ params, request }) => {
    const { repoId } = params;
    const body = (await request.json()) as PinRulePayload;
    const entry: MemoryEntry = {
      id: `mem-${Date.now()}`,
      repository_id: String(repoId),
      type: 'rule',
      content: body.rule,
      source: body.source || 'user_pinned',
      status: 'active',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    mockMemories.unshift(entry);
    return HttpResponse.json(entry, { status: 201 });
  }),

  // List and search memories
  http.get('*/api/v1/repositories/:repoId/memories', ({ params, request }) => {
    const { repoId } = params;
    const url = new URL(request.url);
    const query = url.searchParams.get('query')?.toLowerCase();
    const type = url.searchParams.get('type');
    const status = url.searchParams.get('status');
    const page = parseInt(url.searchParams.get('page') || '1', 10);
    const pageSize = parseInt(url.searchParams.get('page_size') || '20', 10);

    let filtered = mockMemories.filter((m) => m.repository_id === repoId);
    if (type) {
      filtered = filtered.filter((m) => m.type === type);
    }
    if (status) {
      filtered = filtered.filter((m) => m.status === status);
    }
    if (query) {
      filtered = filtered.filter(
        (m) => m.content.toLowerCase().includes(query) || m.source.toLowerCase().includes(query)
      );
    }

    const start = (page - 1) * pageSize;
    const items = filtered.slice(start, start + pageSize);

    return HttpResponse.json({
      page,
      page_size: pageSize,
      total: filtered.length,
      items,
    });
  }),

  // Get specific memory
  http.get('*/api/v1/repositories/:repoId/memories/:id', ({ params }) => {
    const { repoId, id } = params;
    const entry = mockMemories.find((m) => m.repository_id === repoId && m.id === id);
    if (!entry) {
      return HttpResponse.json({ message: 'Memory not found' }, { status: 404 });
    }
    return HttpResponse.json(entry);
  }),

  // Create memory
  http.post('*/api/v1/repositories/:repoId/memories', async ({ params, request }) => {
    const { repoId } = params;
    const body = (await request.json()) as CreateMemoryPayload;
    const entry: MemoryEntry = {
      id: `mem-${Date.now()}`,
      repository_id: String(repoId),
      type: body.type,
      content: body.content,
      source: body.source || 'manual',
      status: body.status || 'active',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    mockMemories.unshift(entry);
    return HttpResponse.json(entry, { status: 201 });
  }),

  // Patch memory
  http.patch('*/api/v1/repositories/:repoId/memories/:id', async ({ params, request }) => {
    const { repoId, id } = params;
    const entry = mockMemories.find((m) => m.repository_id === repoId && m.id === id);
    if (!entry) {
      return HttpResponse.json({ message: 'Memory not found' }, { status: 404 });
    }
    const body = (await request.json()) as UpdateMemoryPayload;
    if (body.content !== undefined) entry.content = body.content;
    if (body.status !== undefined) entry.status = body.status;
    if (body.type !== undefined) entry.type = body.type;
    if (body.source !== undefined) entry.source = body.source;
    entry.updated_at = new Date().toISOString();
    return HttpResponse.json(entry);
  }),

  // Delete memory
  http.delete('*/api/v1/repositories/:repoId/memories/:id', ({ params }) => {
    const { repoId, id } = params;
    const index = mockMemories.findIndex((m) => m.repository_id === repoId && m.id === id);
    if (index === -1) {
      return HttpResponse.json({ message: 'Memory not found' }, { status: 404 });
    }
    mockMemories.splice(index, 1);
    return new HttpResponse(null, { status: 204 });
  }),
];
