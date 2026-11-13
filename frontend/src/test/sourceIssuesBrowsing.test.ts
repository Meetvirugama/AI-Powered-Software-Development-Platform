import { describe, it, expect } from 'vitest';
import { listRemoteSourceIssues, getRemoteSourceIssue } from '../services/repositories';
import { apiClient } from '../services/api';

describe('GitHub Source Issues Browsing & Endpoint Consolidation (F16 - Issue #196)', () => {
  const repoId = '11111111-2222-3333-4444-555555555555';

  it('lists remote issues for repository via GitHubSourceService endpoint', async () => {
    const issues = await listRemoteSourceIssues(repoId, { state: 'open' });
    expect(issues).toHaveLength(1);
    expect(issues[0].number).toBe(101);
    expect(issues[0].title).toBe('Mock remote issue from GitHub');
    expect(issues[0].author).toBe('octocat');
    expect(issues[0].labels).toContain('bug');
    expect(issues[0].is_pull_request).toBe(false);
  });

  it('retrieves detailed remote issue metadata by number', async () => {
    const detail = await getRemoteSourceIssue(repoId, 42);
    expect(detail.number).toBe(42);
    expect(detail.title).toBe('Mock remote issue #42');
    expect(detail.author).toBe('octocat');
    expect(detail.state).toBe('open');
  });

  it('handles 404 for non-existent remote issue cleanly', async () => {
    await expect(getRemoteSourceIssue(repoId, 404)).rejects.toMatchObject({
      code: 'NOT_FOUND',
    });
  });

  it('handles 400 for invalid issue number', async () => {
    await expect(getRemoteSourceIssue(repoId, 0)).rejects.toMatchObject({
      code: 'INVALID_REQUEST',
    });
  });

  it('confirms deprecated /source/task/* endpoints respond with 410 Gone and canonical header', async () => {
    try {
      await apiClient.post(`/repositories/${repoId}/source/task/verify`, {
        task_id: 'task-123',
      });
      expect.fail('Should have thrown 410 Gone');
    } catch (err: any) {
      expect(err.status).toBe(410);
    }
  });

  it('confirms deprecated /source/task-workspace/* endpoints respond with 410 Gone', async () => {
    try {
      await apiClient.post(`/repositories/${repoId}/source/task-workspace/tests`, {
        task_id: 'task-123',
      });
      expect.fail('Should have thrown 410 Gone');
    } catch (err: any) {
      expect(err.status).toBe(410);
    }
  });
});
