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
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/+$/, '');

export const DEFAULT_TIMEOUT_MS = 30000;
export const AI_ANALYSIS_TIMEOUT_MS = 180000;

const TOKEN_STORAGE_KEY = 'app_tok';

export function getStoredToken(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return (
      localStorage.getItem(TOKEN_STORAGE_KEY) ||
      sessionStorage.getItem(TOKEN_STORAGE_KEY) ||
      localStorage.getItem('auth_token') ||
      sessionStorage.getItem('auth_token')
    );
  } catch {
    return null;
  }
}

export function setStoredToken(token: string): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } catch {
    try {
      sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
    } catch {
      // Storage unavailable
    }
  }
}

export function clearStoredToken(): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    sessionStorage.removeItem(TOKEN_STORAGE_KEY);
    localStorage.removeItem('auth_token');
    sessionStorage.removeItem('auth_token');
  } catch {
    // Storage unavailable
  }
}

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

  // Attach Bearer token for cross-origin or cookie-independent authentication
  const token = getStoredToken();
  if (token && reqConfig.headers && !reqConfig.headers.Authorization) {
    reqConfig.headers.Authorization = `Bearer ${token}`;
  }

  // F-04 / OPT-02: Apply dedicated long-running timeout for AI mutation endpoints (POST/PUT/PATCH)
  // GET endpoints (e.g. status, plans, tests, settings) retain the default 30s timeout
  const method = (reqConfig.method || 'GET').toUpperCase();
  const url = reqConfig.url || '';
  const isAiMutation =
    method !== 'GET' &&
    (url.includes('/explain') ||
      url.includes('/detect-bugs') ||
      url.includes('/generate-tests') ||
      url.includes('/review') ||
      url.includes('/plan') ||
      url.includes('/chat') ||
      url.includes('/execute') ||
      url.includes('/repair') ||
      url.includes('/verify') ||
      url.includes('/run-workflow'));

  if (isAiMutation && (reqConfig.timeout === undefined || reqConfig.timeout === DEFAULT_TIMEOUT_MS)) {
    reqConfig.timeout = AI_ANALYSIS_TIMEOUT_MS;
  }

  return reqConfig;
});

let refreshPromise: Promise<string | null> | null = null;

function refreshSessionToken(): Promise<string | null> {
  if (!refreshPromise) {
    const currentToken = getStoredToken();
    refreshPromise = axios
      .post<{ access_token?: string }>(
        `${API_BASE_URL}/auth/refresh`,
        {},
        {
          withCredentials: true,
          headers: currentToken ? { Authorization: `Bearer ${currentToken}` } : undefined,
        }
      )
      .then((res) => {
        const nextToken = res.data?.access_token ?? null;
        if (nextToken) {
          setStoredToken(nextToken);
        }
        return nextToken;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

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

    // ISS-012 / T4.9: Attempt deduplicated token renewal on 401 before redirecting
    const originalRequest = error.config as (InternalAxiosRequestConfig & { _retry?: boolean }) | undefined;
    const isAuthEndpoint =
      originalRequest?.url?.includes('/auth/refresh') ||
      originalRequest?.url?.includes('/auth/login') ||
      originalRequest?.url?.includes('/auth/github') ||
      originalRequest?.url?.includes('/auth/dev-login');

    if (error.response?.status === 401 && originalRequest && !originalRequest._retry && !isAuthEndpoint) {
      originalRequest._retry = true;
      return refreshSessionToken()
        .then((nextToken) => {
          if (nextToken && originalRequest.headers) {
            originalRequest.headers.Authorization = `Bearer ${nextToken}`;
          }
          return apiClient(originalRequest);
        })
        .catch(() => {
          clearStoredToken();
          if (
            typeof window !== 'undefined' &&
            !window.location.pathname.startsWith('/login') &&
            !window.location.pathname.startsWith('/auth')
          ) {
            const currentPath = window.location.pathname + window.location.search;
            const redirectQuery = currentPath && currentPath !== '/' ? `?redirect=${encodeURIComponent(currentPath)}` : '';
            window.location.href = `/login${redirectQuery}`;
          }
          return Promise.reject(normalised);
        });
    }

    // F-10: Preserve intended return route on 401 redirect (skip auth endpoints)
    if (
      error.response?.status === 401 &&
      !isAuthEndpoint &&
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
export function normaliseError(error: unknown): ApiError {
  const err = error as (AxiosError & { code?: string; message?: string; response?: { status?: number; data?: Record<string, unknown>; headers?: Record<string, string> } }) | undefined;

  // Handle cancellation separately from genuine network errors (F-10)
  if (axios.isCancel(err) || err?.code === 'ERR_CANCELED') {
    return {
      code: 'REQUEST_CANCELLED',
      message: 'Request was cancelled.',
      retryable: false,
      status: 0,
    };
  }

  // Handle request timeouts (F-04)
  if (err?.code === 'ECONNABORTED' || (typeof err?.message === 'string' && err.message.toLowerCase().includes('timeout'))) {
    return {
      code: 'REQUEST_TIMEOUT',
      message: 'Analysis request timed out — please check Analysis History before retrying.',
      retryable: true,
      status: 408,
    };
  }

  const status = err?.response?.status as number | undefined;
  const data = err?.response?.data as Record<string, unknown> | undefined;
  const envelope = data?.error as (Partial<ApiError> & { details?: Record<string, unknown> | unknown[] }) | undefined;

  const requestId =
    (err?.response?.headers?.['x-request-id'] as string) ||
    (typeof data?.request_id === 'string' ? data.request_id : undefined) ||
    (typeof envelope?.requestId === 'string' ? envelope.requestId : undefined);

  // Week 3 domain error code defaults
  const WEEK3_ERROR_DEFAULTS: Record<string, { message: string; retryable: boolean; status?: number }> = {
    APPROVAL_REQUIRED: {
      message: 'Human approval of the plan is required before this action can proceed.',
      retryable: false,
      status: 409,
    },
    PLAN_VERSION_MISMATCH: {
      message: 'The plan has been revised. Please refresh the page and review the updated plan version.',
      retryable: false,
      status: 409,
    },
    INVALID_STATE_TRANSITION: {
      message: 'This action cannot be performed from the current task state.',
      retryable: false,
      status: 409,
    },
    TASK_NOT_FOUND: {
      message: 'Task not found. It may have been deleted or moved.',
      retryable: false,
      status: 404,
    },
    POLICY_VIOLATION: {
      message: 'Action blocked by security or governance policy.',
      retryable: false,
      status: 403,
    },
    COMMAND_NOT_ALLOWED: {
      message: 'The requested command is not permitted by policy.',
      retryable: false,
      status: 403,
    },
    RETRY_BUDGET_EXHAUSTED: {
      message: 'Maximum repair attempts (3) exhausted for this task.',
      retryable: false,
      status: 400,
    },
    EXECUTION_TIMEOUT: {
      message: 'Request or execution timed out. Please check history before retrying.',
      retryable: true,
      status: 408,
    },
    WORKSPACE_CREATION_FAILED: {
      message: 'Failed to create an isolated workspace for this task.',
      retryable: true,
      status: 500,
    },
    RECOVERY_REQUIRED: {
      message: 'Task state is inconsistent. State reconciliation required.',
      retryable: false,
      status: 500,
    },
    GITHUB_API_ERROR: {
      message: 'GitHub API error occurred. Please verify your GitHub connection.',
      retryable: true,
      status: 502,
    },
  };

  const rawCode =
    envelope?.code ||
    (typeof data?.code === 'string' ? data.code : undefined) ||
    (typeof data?.detail === 'string' && data.detail in WEEK3_ERROR_DEFAULTS ? data.detail : undefined);

  if (rawCode && rawCode in WEEK3_ERROR_DEFAULTS) {
    const config = WEEK3_ERROR_DEFAULTS[rawCode];
    return {
      code: rawCode,
      message: envelope?.message || (typeof data?.message === 'string' ? data.message : undefined) || config.message,
      retryable: envelope?.retryable ?? config.retryable,
      status: status ?? config.status,
      requestId,
      details: envelope?.details ?? (data?.details as Record<string, unknown> | unknown[] | undefined),
    };
  }

  // If backend returned a structured error envelope
  if (envelope?.code && envelope?.message) {
    return {
      code: envelope.code,
      message: envelope.message,
      retryable: envelope.retryable ?? (status ? status >= 500 : false),
      status,
      requestId,
      details: envelope.details ?? (data?.details as Record<string, unknown> | unknown[] | undefined),
    };
  }

  // Fallback by HTTP status code
  const detailMessage = typeof data?.detail === 'string' && data.detail.trim() ? data.detail : undefined;
  if (status === 400) {
    return { code: 'BAD_REQUEST', message: detailMessage ?? 'Bad request.', retryable: false, status, requestId };
  }
  if (status === 401) {
    return { code: 'UNAUTHORIZED', message: detailMessage ?? 'Not authenticated.', retryable: false, status, requestId };
  }
  if (status === 403) {
    return { code: 'FORBIDDEN', message: detailMessage ?? 'Access denied.', retryable: false, status, requestId };
  }
  if (status === 404) {
    return { code: 'NOT_FOUND', message: detailMessage ?? 'Resource not found.', retryable: false, status, requestId };
  }
  if (status === 409) {
    return { code: 'CONFLICT', message: detailMessage ?? 'Resource conflict occurred.', retryable: false, status, requestId };
  }
  if (status === 422) {
    return {
      code: 'INVALID_REQUEST',
      message: 'Request validation failed.',
      retryable: false,
      status,
      requestId,
      details: data?.detail as Record<string, unknown> | unknown[] | undefined,
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
  if (err?.code === 'ERR_NETWORK') {
    return {
      code: 'NETWORK_ERROR',
      message: 'Network error. Please check your connection.',
      retryable: true,
      status: 0,
    };
  }

  return {
    code: 'UNKNOWN_ERROR',
    message: err?.message || 'An unknown error occurred.',
    retryable: false,
    status,
    requestId,
  };
}
