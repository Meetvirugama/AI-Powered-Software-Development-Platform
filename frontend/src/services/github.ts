/**
 * GitHub Integration & Webhook Console Service (FEAT-15).
 *
 * Exposes durable webhook event inspection, dead-letter replay,
 * and repository-level opt-in automation settings.
 */

import { apiClient } from './api';

export interface WebhookEventRecord {
  id: string;
  delivery_id: string;
  event_type: string;
  action: string | null;
  installation_id: string | null;
  repository_id: string | null;
  status: string;
  attempts: number;
  max_attempts: number;
  available_at: string | null;
  processed_at: string | null;
  last_error: string | null;
  replay_count: number;
  created_at: string | null;
}

export interface PaginatedWebhookEvents {
  items: WebhookEventRecord[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface RepositoryAutomationSettings {
  github_repo_id: string;
  auto_sync_enabled: boolean;
  pr_review_enabled: boolean;
  pr_review_drafts: boolean;
  last_indexed_commit_sha?: string | null;
}

/**
 * List durably persisted GitHub webhook events (FEAT-15).
 *
 * GET /api/v1/github/events
 */
export async function listWebhookEvents(params?: {
  status?: string;
  event_type?: string;
  repository_id?: string;
  page?: number;
  page_size?: number;
}): Promise<PaginatedWebhookEvents> {
  const response = await apiClient.get<PaginatedWebhookEvents>('/github/events', {
    params,
  });
  return response.data;
}

/**
 * Get detailed status and metadata for a specific webhook event.
 *
 * GET /api/v1/github/events/:id
 */
export async function getWebhookEvent(eventId: string): Promise<WebhookEventRecord> {
  const response = await apiClient.get<WebhookEventRecord>(`/github/events/${eventId}`);
  return response.data;
}

/**
 * Safely replay a failed or dead-letter webhook event.
 *
 * POST /api/v1/github/events/:id/replay
 */
export async function replayWebhookEvent(eventId: string): Promise<{ status: string; event_id: string; replay_count: number }> {
  const response = await apiClient.post(`/github/events/${eventId}/replay`);
  return response.data;
}

/**
 * Retrieve automation settings for a connected repository.
 *
 * GET /api/v1/github/repositories/:githubRepoId/automation
 */
export async function getRepositoryAutomation(githubRepoId: string): Promise<RepositoryAutomationSettings> {
  const response = await apiClient.get<RepositoryAutomationSettings>(
    `/github/repositories/${githubRepoId}/automation`,
  );
  return response.data;
}

/**
 * Update opt-in automation settings for a repository.
 *
 * PATCH /api/v1/github/repositories/:githubRepoId/automation
 */
export async function updateRepositoryAutomation(
  githubRepoId: string,
  payload: Partial<Omit<RepositoryAutomationSettings, 'github_repo_id'>>,
): Promise<RepositoryAutomationSettings> {
  const response = await apiClient.patch<RepositoryAutomationSettings>(
    `/github/repositories/${githubRepoId}/automation`,
    payload,
  );
  return response.data;
}
