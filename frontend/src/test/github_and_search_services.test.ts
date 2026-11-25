import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { apiClient } from '../services/api';
import {
  listWebhookEvents,
  getWebhookEvent,
  replayWebhookEvent,
  getRepositoryAutomation,
  updateRepositoryAutomation,
} from '../services/github';
import { searchRepository, listRepositorySymbols } from '../services/repositories';

describe('GitHub & Code Search Services (FEAT-15 / FEAT-16)', () => {
  let getSpy: any;
  let postSpy: any;
  let patchSpy: any;

  beforeEach(() => {
    getSpy = vi.spyOn(apiClient, 'get');
    postSpy = vi.spyOn(apiClient, 'post');
    patchSpy = vi.spyOn(apiClient, 'patch');
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('listWebhookEvents calls /github/events with query params', async () => {
    const mockData = { items: [], total: 0, page: 1, page_size: 20, total_pages: 0 };
    getSpy.mockResolvedValueOnce({ data: mockData });

    const result = await listWebhookEvents({ status: 'PROCESSED', page: 1, page_size: 20 });
    expect(getSpy).toHaveBeenCalledWith('/github/events', {
      params: { status: 'PROCESSED', page: 1, page_size: 20 },
    });
    expect(result).toEqual(mockData);
  });

  it('getWebhookEvent calls /github/events/:id', async () => {
    const mockData = { id: 'evt-1', delivery_id: 'del-1', event_type: 'push', status: 'PROCESSED' };
    getSpy.mockResolvedValueOnce({ data: mockData });

    const result = await getWebhookEvent('evt-1');
    expect(getSpy).toHaveBeenCalledWith('/github/events/evt-1');
    expect(result).toEqual(mockData);
  });

  it('replayWebhookEvent posts to /github/events/:id/replay', async () => {
    const mockData = { status: 'replayed', event_id: 'evt-1', replay_count: 1 };
    postSpy.mockResolvedValueOnce({ data: mockData });

    const result = await replayWebhookEvent('evt-1');
    expect(postSpy).toHaveBeenCalledWith('/github/events/evt-1/replay');
    expect(result).toEqual(mockData);
  });

  it('getRepositoryAutomation calls /github/repositories/:id/automation', async () => {
    const mockData = {
      github_repo_id: 'gh-123',
      auto_sync_enabled: true,
      pr_review_enabled: true,
      pr_review_drafts: false,
    };
    getSpy.mockResolvedValueOnce({ data: mockData });

    const result = await getRepositoryAutomation('gh-123');
    expect(getSpy).toHaveBeenCalledWith('/github/repositories/gh-123/automation');
    expect(result).toEqual(mockData);
  });

  it('updateRepositoryAutomation patches /github/repositories/:id/automation', async () => {
    const mockData = {
      github_repo_id: 'gh-123',
      auto_sync_enabled: false,
      pr_review_enabled: true,
      pr_review_drafts: false,
    };
    patchSpy.mockResolvedValueOnce({ data: mockData });

    const result = await updateRepositoryAutomation('gh-123', { auto_sync_enabled: false });
    expect(patchSpy).toHaveBeenCalledWith('/github/repositories/gh-123/automation', {
      auto_sync_enabled: false,
    });
    expect(result).toEqual(mockData);
  });

  it('searchRepository posts to /repositories/:id/search', async () => {
    const mockData = { query: 'authenticate', total: 1, results: [] };
    postSpy.mockResolvedValueOnce({ data: mockData });

    const result = await searchRepository('repo-uuid', 'authenticate', 5);
    expect(postSpy).toHaveBeenCalledWith('/repositories/repo-uuid/search', {
      query: 'authenticate',
      top_k: 5,
    });
    expect(result).toEqual(mockData);
  });

  it('listRepositorySymbols calls /repositories/:id/symbols', async () => {
    const mockData = [{ id: 'sym-1', name: 'login', kind: 'function', file_path: 'auth.py', start_line: 1, end_line: 10 }];
    getSpy.mockResolvedValueOnce({ data: mockData });

    const result = await listRepositorySymbols('repo-uuid', { kind: 'function' });
    expect(getSpy).toHaveBeenCalledWith('/repositories/repo-uuid/symbols', {
      params: { kind: 'function' },
    });
    expect(result).toEqual(mockData);
  });

  it('listRepositorySymbols maps query to q and unwraps PaginatedResponse items', async () => {
    const items = [{ id: 'sym-2', name: 'verifyToken', kind: 'function', file_path: 'auth.py', start_line: 12, end_line: 25 }];
    getSpy.mockResolvedValueOnce({
      data: { page: 1, page_size: 50, total: 1, items },
    });

    const result = await listRepositorySymbols('repo-uuid', { query: 'verify', kind: 'function' });
    expect(getSpy).toHaveBeenCalledWith('/repositories/repo-uuid/symbols', {
      params: { kind: 'function', q: 'verify' },
    });
    expect(result).toEqual(items);
  });
});
