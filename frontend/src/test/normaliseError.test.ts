import { describe, it, expect } from 'vitest';
import { AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios';
import { normaliseError } from '../services/api';

function createMockAxiosError(
  status?: number,
  data?: unknown,
  code?: string,
  message?: string
): AxiosError {
  const config = { headers: {} } as InternalAxiosRequestConfig;
  const response = status
    ? ({
        data,
        status,
        statusText: String(status),
        headers: {},
        config,
      } as AxiosResponse)
    : undefined;

  const error = new AxiosError(message || 'Error occurred', code, config, {}, response);
  return error;
}

describe('normaliseError', () => {
  it('extracts structured backend error envelope', () => {
    const error = createMockAxiosError(400, {
      error: {
        code: 'VALIDATION_FAILED',
        message: 'Invalid target path provided.',
        retryable: false,
      },
    });

    const result = normaliseError(error);
    expect(result.code).toBe('VALIDATION_FAILED');
    expect(result.message).toBe('Invalid target path provided.');
    expect(result.retryable).toBe(false);
  });

  it('maps HTTP 401 to UNAUTHORIZED', () => {
    const error = createMockAxiosError(401);
    const result = normaliseError(error);
    expect(result.code).toBe('UNAUTHORIZED');
    expect(result.retryable).toBe(false);
  });

  it('maps HTTP 403 to FORBIDDEN', () => {
    const error = createMockAxiosError(403);
    const result = normaliseError(error);
    expect(result.code).toBe('FORBIDDEN');
    expect(result.retryable).toBe(false);
  });

  it('maps HTTP 404 to NOT_FOUND', () => {
    const error = createMockAxiosError(404);
    const result = normaliseError(error);
    expect(result.code).toBe('NOT_FOUND');
    expect(result.retryable).toBe(false);
  });

  it('maps HTTP 500+ to SERVER_ERROR with retryable=true', () => {
    const error = createMockAxiosError(502);
    const result = normaliseError(error);
    expect(result.code).toBe('SERVER_ERROR');
    expect(result.retryable).toBe(true);
  });

  it('maps ECONNABORTED timeout to REQUEST_TIMEOUT with retryable=true and history guidance (F-04)', () => {
    const error = createMockAxiosError(undefined, undefined, 'ECONNABORTED', 'timeout of 30000ms exceeded');
    const result = normaliseError(error);
    expect(result.code).toBe('REQUEST_TIMEOUT');
    expect(result.message).toContain('check Analysis History before retrying');
    expect(result.retryable).toBe(true);
  });

  it('maps ERR_NETWORK to NETWORK_ERROR with retryable=true', () => {
    const error = createMockAxiosError(undefined, undefined, 'ERR_NETWORK', 'Network Error');
    const result = normaliseError(error);
    expect(result.code).toBe('NETWORK_ERROR');
    expect(result.retryable).toBe(true);
  });

  it('handles unknown fallback cleanly', () => {
    const error = createMockAxiosError(undefined, undefined, undefined, 'Unexpected crash');
    const result = normaliseError(error);
    expect(result.code).toBe('UNKNOWN_ERROR');
    expect(result.message).toBe('Unexpected crash');
    expect(result.retryable).toBe(false);
  });
});
