/**
 * Developer Intelligence Analysis Services.
 *
 * Calls Week 2 API endpoints registered in backend/app/api/v1/analysis.py:
 *   - POST /api/v1/repositories/{repository_id}/explain
 *   - POST /api/v1/repositories/{repository_id}/detect-bugs
 *   - POST /api/v1/repositories/{repository_id}/generate-tests
 *   - POST /api/v1/repositories/{repository_id}/review
 *   - GET  /api/v1/repositories/{repository_id}/analysis-runs
 *   - GET  /api/v1/analysis-runs/{run_id}
 */

import { apiClient, API_BASE_URL, getStoredToken } from './api';
import type { ApiError } from '../types/api';
import type {
  ExplainCodeRequest,
  CodeExplanationResponse,
  RelatedFilesDiscoveryResponse,
  BugDetectionRequest,
  BugDetectionResponse,
  TestGenerationRequest,
  TestGenerationResponse,
  CodeReviewRequest,
  ReviewReportResponse,
  PaginatedAnalysisRunResponse,
  AnalysisRunDetailResponse,
  AnalysisRunFeatureType,
  AnalysisRunMetricsSummaryResponse,
} from '../types/analysis';

/**
 * Request an AI-powered explanation for a file, symbol, or line range.
 *
 * @param repositoryId The UUID of the authorized repository.
 * @param payload The validated target and execution options.
 * @returns The structured explanation response envelope.
 */
export interface AnalysisRequestOptions {
  signal?: AbortSignal;
  timeout?: number;
}

export interface AnalysisStageEvent {
  stage: string;
  message: string;
}

export interface AnalysisStreamHandlers {
  onStage?: (event: AnalysisStageEvent) => void;
}

export class AnalysisStreamUnavailableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'AnalysisStreamUnavailableError';
  }
}

export async function streamAnalysisEndpoint<T>(
  endpointPath: string,
  payload: unknown,
  handlers: AnalysisStreamHandlers = {},
  options?: AnalysisRequestOptions,
): Promise<T> {
  if (typeof fetch !== 'function' || typeof TextDecoder === 'undefined') {
    throw new AnalysisStreamUnavailableError('Streaming is not supported in this environment.');
  }

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  };
  const token = getStoredToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${endpointPath}`, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
      credentials: 'include',
      signal: options?.signal,
    });
  } catch (err) {
    if (options?.signal?.aborted) throw err;
    throw new AnalysisStreamUnavailableError(err instanceof Error ? err.message : 'Network error');
  }

  if ([401, 404, 405, 501].includes(response.status)) {
    throw new AnalysisStreamUnavailableError(`Streaming endpoint unavailable (HTTP ${response.status}).`);
  }

  if (!response.ok) {
    let message = `Request failed (HTTP ${response.status}).`;
    let code = 'ANALYSIS_FAILED';
    let retryable = response.status >= 500 || response.status === 429;
    try {
      const body = await response.json();
      message = body?.error?.message ?? body?.detail ?? message;
      code = body?.error?.code ?? code;
      retryable = body?.error?.retryable ?? retryable;
    } catch {
      // Keep defaults
    }
    throw { message, status: response.status, code, retryable } as ApiError;
  }

  const contentType = response.headers?.get?.('content-type') ?? '';
  if (!response.body || (contentType && !contentType.includes('text/event-stream'))) {
    throw new AnalysisStreamUnavailableError('Response did not return an SSE stream.');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let finalResult: T | null = null;

  const processFrame = (rawFrame: string) => {
    let eventName = 'message';
    const dataLines: string[] = [];
    for (const line of rawFrame.split('\n')) {
      if (line.startsWith('event:')) eventName = line.slice(6).trim();
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
    }
    if (!dataLines.length) return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(dataLines.join('\n'));
    } catch {
      return;
    }
    const obj = (parsed ?? {}) as Record<string, unknown>;
    if (eventName === 'status') {
      handlers.onStage?.({
        stage: String(obj.stage ?? ''),
        message: String(obj.message ?? ''),
      });
    } else if (eventName === 'done') {
      finalResult = parsed as T;
    } else if (eventName === 'error') {
      throw {
        message: String(obj.message ?? 'Analysis failed during execution.'),
        status: 500,
        code: String(obj.code ?? 'ANALYSIS_FAILED'),
        retryable: Boolean(obj.retryable ?? false),
      } as ApiError;
    }
  };

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');
      let sep: number;
      while ((sep = buffer.indexOf('\n\n')) !== -1) {
        const rawFrame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        processFrame(rawFrame);
      }
    }
    if (buffer.trim()) {
      processFrame(buffer.trim());
    }
  } finally {
    reader.releaseLock?.();
  }

  if (!finalResult) {
    throw {
      message: 'Analysis stream closed before completion.',
      status: 502,
      code: 'ANALYSIS_STREAM_INCOMPLETE',
      retryable: true,
    } as ApiError;
  }

  return finalResult;
}

export async function streamExplainCode(
  repositoryId: string,
  payload: ExplainCodeRequest,
  handlers?: AnalysisStreamHandlers,
  options?: AnalysisRequestOptions,
): Promise<CodeExplanationResponse> {
  return streamAnalysisEndpoint<CodeExplanationResponse>(
    `/repositories/${repositoryId}/explain/stream`,
    payload,
    handlers,
    options,
  );
}

export async function streamDetectBugs(
  repositoryId: string,
  payload: BugDetectionRequest,
  handlers?: AnalysisStreamHandlers,
  options?: AnalysisRequestOptions,
): Promise<BugDetectionResponse> {
  return streamAnalysisEndpoint<BugDetectionResponse>(
    `/repositories/${repositoryId}/detect-bugs/stream`,
    payload,
    handlers,
    options,
  );
}

export async function streamGenerateTests(
  repositoryId: string,
  payload: TestGenerationRequest,
  handlers?: AnalysisStreamHandlers,
  options?: AnalysisRequestOptions,
): Promise<TestGenerationResponse> {
  return streamAnalysisEndpoint<TestGenerationResponse>(
    `/repositories/${repositoryId}/generate-tests/stream`,
    payload,
    handlers,
    options,
  );
}

export async function streamReviewCode(
  repositoryId: string,
  payload: CodeReviewRequest,
  handlers?: AnalysisStreamHandlers,
  options?: AnalysisRequestOptions,
): Promise<ReviewReportResponse> {
  return streamAnalysisEndpoint<ReviewReportResponse>(
    `/repositories/${repositoryId}/review/stream`,
    payload,
    handlers,
    options,
  );
}

export async function explainCode(
  repositoryId: string,
  payload: ExplainCodeRequest,
  options?: AnalysisRequestOptions
): Promise<CodeExplanationResponse> {
  const response = await apiClient.post<CodeExplanationResponse>(
    `/repositories/${repositoryId}/explain`,
    payload,
    { signal: options?.signal, timeout: options?.timeout }
  );
  return response.data;
}

/**
 * Discover related files and graph neighbors for a code explanation target (RIE).
 */
export async function getRelatedFiles(
  repositoryId: string,
  path: string,
  symbol?: string
): Promise<RelatedFilesDiscoveryResponse> {
  const params = new URLSearchParams({ path });
  if (symbol) params.set('symbol', symbol);
  const response = await apiClient.get<RelatedFilesDiscoveryResponse>(
    `/repositories/${repositoryId}/explain/related-files?${params.toString()}`
  );
  return response.data;
}

/**
 * Scan for bugs using static analysis rules and AI reasoning (Week 2 — Day 3).
 *
 * Calls POST /api/v1/repositories/{repository_id}/detect-bugs
 *
 * @param repositoryId The UUID of the authorized repository.
 * @param payload Target, options, and engine flags.
 * @param options Request options including optional cancellation signal and timeout.
 * @returns The structured bug detection response envelope.
 */
export async function detectBugs(
  repositoryId: string,
  payload: BugDetectionRequest,
  options?: AnalysisRequestOptions
): Promise<BugDetectionResponse> {
  const response = await apiClient.post<BugDetectionResponse>(
    `/repositories/${repositoryId}/detect-bugs`,
    payload,
    { signal: options?.signal, timeout: options?.timeout }
  );
  return response.data;
}

/**
 * Generate a framework-aware test file following repository conventions (Week 2 — Day 4).
 *
 * Calls POST /api/v1/repositories/{repository_id}/generate-tests
 *
 * @param repositoryId The UUID of the authorized repository.
 * @param payload Target, options, and optional framework override.
 * @param options Request options including optional cancellation signal and timeout.
 * @returns The structured test generation response envelope.
 */
export async function generateTests(
  repositoryId: string,
  payload: TestGenerationRequest,
  options?: AnalysisRequestOptions
): Promise<TestGenerationResponse> {
  const response = await apiClient.post<TestGenerationResponse>(
    `/repositories/${repositoryId}/generate-tests`,
    payload,
    { signal: options?.signal, timeout: options?.timeout }
  );
  return response.data;
}

/**
 * Run a standalone AI and static code review on a file, commit, PR, or diff (Week 2 — Day 5).
 *
 * Calls POST /api/v1/repositories/{repository_id}/review
 *
 * @param repositoryId The UUID of the authorized repository.
 * @param payload Review target (file, commit, pr, or diff) and options.
 * @param options Request options including optional cancellation signal and timeout.
 * @returns The structured review report response envelope.
 */
export async function reviewCode(
  repositoryId: string,
  payload: CodeReviewRequest,
  options?: AnalysisRequestOptions
): Promise<ReviewReportResponse> {
  const response = await apiClient.post<ReviewReportResponse>(
    `/repositories/${repositoryId}/review`,
    payload,
    { signal: options?.signal, timeout: options?.timeout }
  );
  return response.data;
}

/**
 * List historical analysis runs (e.g. explanation runs, bug scans, test generation, code reviews)
 * for an authorized repository.
 *
 * @param repositoryId The UUID of the authorized repository.
 * @param params Query filtering and pagination options.
 * @returns Paginated list of analysis run summaries.
 */
export async function getAnalysisRuns(
  repositoryId: string,
  params?: {
    feature_type?: AnalysisRunFeatureType;
    status?: string;
    target_path?: string;
    source_revision?: string;
    user_id?: string;
    page?: number;
    page_size?: number;
  }
): Promise<PaginatedAnalysisRunResponse> {
  const response = await apiClient.get<PaginatedAnalysisRunResponse>(
    `/repositories/${repositoryId}/analysis-runs`,
    { params }
  );
  return response.data;
}

/**
 * Reopen a specific analysis run from persistent history.
 */
export async function getAnalysisRun(
  runId: string
): Promise<AnalysisRunDetailResponse> {
  const response = await apiClient.get<AnalysisRunDetailResponse>(
    `/analysis-runs/${runId}`
  );
  return response.data;
}

/**
 * List historical standalone code review runs for an authorized repository (Scenario D Step 7).
 *
 * @param repositoryId The UUID of the authorized repository.
 * @param params Query filtering and pagination options.
 * @returns Paginated list of analysis run summaries.
 */
export async function getCodeReviewHistory(
  repositoryId: string,
  params?: {
    status?: string;
    target_path?: string;
    source_revision?: string;
    user_id?: string;
    page?: number;
    page_size?: number;
  }
): Promise<PaginatedAnalysisRunResponse> {
  return getAnalysisRuns(repositoryId, {
    ...params,
    feature_type: 'review',
  });
}

/**
 * Reopen a specific standalone code review run from persistent history (Scenario D Step 7).
 *
 * @param runId The UUID of the code review analysis run.
 * @returns Detailed record with findings and structured result payload.
 */
export async function reopenCodeReview(
  runId: string
): Promise<AnalysisRunDetailResponse> {
  return getAnalysisRun(runId);
}


/**
 * Retrieve aggregate run and finding metrics across all 4 Developer Intelligence features
 * for an authorized repository (Week 2 — Day 6/7).
 *
 * Calls GET /api/v1/repositories/{repository_id}/analysis-runs/summary
 */
export async function getAnalysisRunsSummary(
  repositoryId: string
): Promise<AnalysisRunMetricsSummaryResponse> {
  const response = await apiClient.get<AnalysisRunMetricsSummaryResponse>(
    `/repositories/${repositoryId}/analysis-runs/summary`
  );
  return response.data;
}

/**
 * Export historical analysis runs and user feedback as an evaluation dataset (Issue #195).
 *
 * Calls GET /api/v1/repositories/{repository_id}/analysis-runs/export
 *
 * @param repositoryId The UUID of the authorized repository.
 * @param params Query filtering options (format, feature_type, status, include_feedback_only, limit).
 * @returns Blob representing the dataset file (JSONL, JSON, or Langfuse).
 */
export async function exportAnalysisRunsDataset(
  repositoryId: string,
  params?: {
    format?: 'jsonl' | 'json' | 'langfuse';
    feature_type?: AnalysisRunFeatureType;
    status?: string;
    include_feedback_only?: boolean;
    limit?: number;
  }
): Promise<Blob> {
  const response = await apiClient.get<Blob>(
    `/repositories/${repositoryId}/analysis-runs/export`,
    {
      params,
      responseType: 'blob',
    }
  );
  return response.data;
}

/**
 * Submit developer feedback for a review finding (useful, not_useful, false_positive, etc.).
 *
 * Calls POST /api/v1/analysis-runs/{run_id}/findings/{finding_id}/feedback
 */
export async function submitFindingFeedback(
  runId: string,
  findingId: string,
  payload: { feedback_type: string; comment?: string }
): Promise<{
  finding_id: string;
  feedback_type: string;
  comment?: string | null;
  lifecycle_status?: string | null;
  repository_stats: {
    useful_count: number;
    not_useful_count: number;
    false_positive_count: number;
    acceptance_rate: number;
    false_positive_rate: number;
  };
}> {
  const response = await apiClient.post(
    `/analysis-runs/${runId}/findings/${findingId}/feedback`,
    payload
  );
  return response.data;
}

/**
 * Trigger manual publication of qualified code review findings to GitHub PR.
 *
 * Calls POST /api/v1/repositories/{repository_id}/review/publish
 */
export async function publishCodeReview(
  repositoryId: string,
  payload: {
    run_id: string;
    pr_number: number;
    commit_sha?: string;
    force_publish?: boolean;
    max_comments?: number;
  }
): Promise<{
  status: string;
  review_id?: number | null;
  pr_number?: number | null;
  commit_sha?: string | null;
  published_comments_count: number;
  skipped_reason?: string | null;
  error_message?: string | null;
  published_at?: string | null;
}> {
  const response = await apiClient.post(
    `/repositories/${repositoryId}/review/publish`,
    payload
  );
  return response.data;
}

/**
 * Retrieve repository review automation settings.
 *
 * Calls GET /api/v1/repositories/{repository_id}/review/settings
 */
export async function getReviewSettings(
  repositoryId: string
): Promise<{
  repository_id: string;
  pr_review_enabled: boolean;
  pr_review_drafts: boolean;
  max_comments: number;
  min_confidence: string;
  changed_lines_only: boolean;
}> {
  const response = await apiClient.get(
    `/repositories/${repositoryId}/review/settings`
  );
  return response.data;
}

/**
 * Update repository review automation settings.
 *
 * Calls PATCH /api/v1/repositories/{repository_id}/review/settings
 */
export async function updateReviewSettings(
  repositoryId: string,
  payload: {
    pr_review_enabled?: boolean;
    pr_review_drafts?: boolean;
    max_comments?: number;
    min_confidence?: string;
    changed_lines_only?: boolean;
  }
): Promise<{
  repository_id: string;
  pr_review_enabled: boolean;
  pr_review_drafts: boolean;
  max_comments: number;
  min_confidence: string;
  changed_lines_only: boolean;
}> {
  const response = await apiClient.patch(
    `/repositories/${repositoryId}/review/settings`,
    payload
  );
  return response.data;
}
