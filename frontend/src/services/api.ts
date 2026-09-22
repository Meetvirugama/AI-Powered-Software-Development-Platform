import axios, { AxiosError } from 'axios';
import type { ApiError } from '../types/api';

/**
 * Centralised Axios client.
 *
 * Authentication strategy: HTTP-only cookies.
 * The backend sets the JWT in an httpOnly cookie after OAuth callback
 * (Day 2 implementation). The frontend never stores or reads the token
 * value directly — `withCredentials: true` ensures the browser sends the
 * cookie on every request automatically.
 *
 * The request interceptor is a future hook for any headers that are safe to
 * inject from JS (e.g. X-Request-ID). Bearer token injection is intentionally
 * NOT implemented here because the project contract uses httpOnly cookies.
 */
export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  withCredentials: true, // sends httpOnly auth cookie automatically
  headers: {
    'Content-Type': 'application/json',
  },
});

// ---------------------------------------------------------------------------
// Request interceptor — inject safe request-level headers
// ---------------------------------------------------------------------------
apiClient.interceptors.request.use((config) => {
  // Placeholder for future safe request-level headers (e.g. X-Request-ID).
  // Do NOT inject bearer tokens here — auth uses httpOnly cookies.
  return config;
});

// ---------------------------------------------------------------------------
// Response interceptor — normalise errors into ApiError
// ---------------------------------------------------------------------------
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    const normalised = normaliseError(error);
    return Promise.reject(normalised);
  }
);

/**
 * Normalise any Axios/HTTP error into the standard ApiError shape.
 *
 * Backend error envelope (from daily_tasks.md):
 *   { "error": { "code": "...", "message": "...", "retryable": false } }
 */
export function normaliseError(error: AxiosError): ApiError {
  // If the backend returned a structured error envelope, use it.
  const data = error.response?.data as Record<string, unknown> | undefined;
  const envelope = data?.error as Partial<ApiError> | undefined;
  if (envelope?.code && envelope?.message) {
    return {
      code: envelope.code,
      message: envelope.message,
      retryable: envelope.retryable ?? false,
    };
  }

  // Fallback: derive from HTTP status
  const status = error.response?.status;
  if (status === 401) {
    return { code: 'UNAUTHORIZED', message: 'Not authenticated.', retryable: false };
  }
  if (status === 403) {
    return { code: 'FORBIDDEN', message: 'Access denied.', retryable: false };
  }
  if (status === 404) {
    return { code: 'NOT_FOUND', message: 'Resource not found.', retryable: false };
  }
  if (status && status >= 500) {
    return { code: 'SERVER_ERROR', message: 'An unexpected server error occurred.', retryable: true };
  }
  if (error.code === 'ECONNABORTED' || error.code === 'ERR_NETWORK') {
    return { code: 'NETWORK_ERROR', message: 'Network error. Please check your connection.', retryable: true };
  }

  return {
    code: 'UNKNOWN_ERROR',
    message: error.message || 'An unknown error occurred.',
    retryable: false,
  };
}
