import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios';
import type { ApiError } from '../types/api';

/**
 * Centralised Axios client.
 *
 * Authentication strategy: HTTP-only cookies.
 * The backend sets the JWT in an httpOnly cookie after OAuth callback.
 * The frontend never stores or reads the token value directly — `withCredentials: true`
 * ensures the browser sends the cookie on every request automatically.
 */
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

export const DEFAULT_TIMEOUT_MS = 30000;
export const AI_ANALYSIS_TIMEOUT_MS = 120000;

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
  timeout: DEFAULT_TIMEOUT_MS,
  headers: {
    'Content-Type': 'application/json',
  },
});

type RequestConfigWithMetadata = InternalAxiosRequestConfig & {
  metadata?: {
    startTime: number;
  };
};

// ---------------------------------------------------------------------------
// Request interceptor — configure timeouts & instrument request start
// ---------------------------------------------------------------------------
apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const reqConfig = config as RequestConfigWithMetadata;
  reqConfig.metadata = { startTime: Date.now() };

  // F-04: Apply dedicated long-running timeout for AI analysis endpoints if not explicitly overridden
  const url = reqConfig.url || '';
  const isAiEndpoint =
    url.includes('/explain') ||
    url.includes('/detect-bugs') ||
    url.includes('/generate-tests') ||
    url.includes('/review') ||
    url.includes('/chat');

  if (isAiEndpoint && (reqConfig.timeout === undefined || reqConfig.timeout === DEFAULT_TIMEOUT_MS)) {
    reqConfig.timeout = AI_ANALYSIS_TIMEOUT_MS;
  }

  return reqConfig;
});

// ---------------------------------------------------------------------------
// Response interceptor — latency logging & error normalisation
// ---------------------------------------------------------------------------
apiClient.interceptors.response.use(
  (response) => {
    const reqConfig = response.config as RequestConfigWithMetadata;
    if (reqConfig?.metadata?.startTime && import.meta.env.DEV) {
      const elapsed = Date.now() - reqConfig.metadata.startTime;
      console.debug(`[API] ${reqConfig.method?.toUpperCase()} ${reqConfig.url} completed in ${elapsed}ms`);
    }
    return response;
  },
  (error: AxiosError) => {
    const reqConfig = error.config as RequestConfigWithMetadata | undefined;
    if (reqConfig?.metadata?.startTime && import.meta.env.DEV) {
      const elapsed = Date.now() - reqConfig.metadata.startTime;
      console.warn(`[API] ${reqConfig.method?.toUpperCase()} ${reqConfig.url} failed after ${elapsed}ms`);
    }

    const normalised = normaliseError(error);

    // F-10: Preserve intended return route on 401 redirect
    if (
      error.response?.status === 401 &&
      typeof window !== 'undefined' &&
      !window.location.pathname.startsWith('/login') &&
      !window.location.pathname.startsWith('/auth')
    ) {
      const currentPath = window.location.pathname + window.location.search;
      const redirectQuery = currentPath && currentPath !== '/' ? `?redirect=${encodeURIComponent(currentPath)}` : '';
      window.location.href = `/login${redirectQuery}`;
    }

    return Promise.reject(normalised);
  }
);

/**
 * Normalise any Axios/HTTP error into the standard ApiError shape (F-10).
 *
 * Preserves status, request_id, validation details, cancellation and timeout specifics.
 */
export function normaliseError(error: AxiosError | any): ApiError {
  // Handle cancellation separately from genuine network errors (F-10)
  if (axios.isCancel(error) || error?.code === 'ERR_CANCELED') {
    return {
      code: 'REQUEST_CANCELLED',
      message: 'Request was cancelled.',
      retryable: false,
      status: 0,
    };
  }

  // Handle request timeouts (F-04)
  if (error?.code === 'ECONNABORTED' || (typeof error?.message === 'string' && error.message.toLowerCase().includes('timeout'))) {
    return {
      code: 'REQUEST_TIMEOUT',
      message: 'Analysis request timed out — please check Analysis History before retrying.',
      retryable: true,
      status: 408,
    };
  }

  const status = error?.response?.status as number | undefined;
  const data = error?.response?.data as Record<string, unknown> | undefined;
  const envelope = data?.error as (Partial<ApiError> & { details?: Record<string, unknown> | unknown[] }) | undefined;

  const requestId =
    (error?.response?.headers?.['x-request-id'] as string) ||
    (typeof data?.request_id === 'string' ? data.request_id : undefined) ||
    (typeof envelope?.requestId === 'string' ? envelope.requestId : undefined);

  // If backend returned a structured error envelope
  if (envelope?.code && envelope?.message) {
    return {
      code: envelope.code,
      message: envelope.message,
      retryable: envelope.retryable ?? (status ? status >= 500 : false),
      status,
      requestId,
      details: envelope.details ?? (data?.details as any),
    };
  }

  // Fallback by HTTP status code
  if (status === 400) {
    const msg = typeof data?.detail === 'string' ? data.detail : 'Bad request.';
    return { code: 'BAD_REQUEST', message: msg, retryable: false, status, requestId };
  }
  if (status === 401) {
    return { code: 'UNAUTHORIZED', message: 'Not authenticated.', retryable: false, status, requestId };
  }
  if (status === 403) {
    return { code: 'FORBIDDEN', message: 'Access denied.', retryable: false, status, requestId };
  }
  if (status === 404) {
    return { code: 'NOT_FOUND', message: 'Resource not found.', retryable: false, status, requestId };
  }
  if (status === 409) {
    return { code: 'CONFLICT', message: 'Resource conflict occurred.', retryable: false, status, requestId };
  }
  if (status === 422) {
    return {
      code: 'INVALID_REQUEST',
      message: 'Request validation failed.',
      retryable: false,
      status,
      requestId,
      details: data?.detail as any,
    };
  }
  if (status === 429) {
    return {
      code: 'RATE_LIMITED',
      message: 'Rate limit exceeded. Please wait a moment before trying again.',
      retryable: true,
      status,
      requestId,
    };
  }
  if (status === 503) {
    return {
      code: 'SERVICE_UNAVAILABLE',
      message: 'Service is temporarily unavailable. Please try again later.',
      retryable: true,
      status,
      requestId,
    };
  }
  if (status && status >= 500) {
    return {
      code: 'SERVER_ERROR',
      message: 'An unexpected server error occurred.',
      retryable: true,
      status,
      requestId,
    };
  }
  if (error?.code === 'ERR_NETWORK') {
    return {
      code: 'NETWORK_ERROR',
      message: 'Network error. Please check your connection.',
      retryable: true,
      status: 0,
    };
  }

  return {
    code: 'UNKNOWN_ERROR',
    message: error?.message || 'An unknown error occurred.',
    retryable: false,
    status,
    requestId,
  };
}
