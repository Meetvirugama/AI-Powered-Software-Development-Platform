import { describe, it, expect } from 'vitest';
import { normaliseError } from '../services/api';

describe('normaliseError (F-04 & F-10)', () => {
  it('normalises structured backend error envelope preserving requestId and details', () => {
    const error: any = {
      response: {
        status: 400,
        headers: { 'x-request-id': 'req-987' },
        data: {
          error: {
            code: 'UNSUPPORTED_TARGET',
            message: 'Target is not a supported file type.',
            retryable: false,
            details: { target: 'style.css' },
          },
        },
      },
    };

    const normalised = normaliseError(error);
    expect(normalised.code).toBe('UNSUPPORTED_TARGET');
    expect(normalised.message).toBe('Target is not a supported file type.');
    expect(normalised.retryable).toBe(false);
    expect(normalised.status).toBe(400);
    expect(normalised.requestId).toBe('req-987');
    expect(normalised.details).toEqual({ target: 'style.css' });
  });

  it('normalises client timeouts with history check guidance (F-04)', () => {
    const timeoutError: any = {
      code: 'ECONNABORTED',
      message: 'timeout of 120000ms exceeded',
    };

    const normalised = normaliseError(timeoutError);
    expect(normalised.code).toBe('REQUEST_TIMEOUT');
    expect(normalised.message).toContain('check Analysis History before retrying');
    expect(normalised.status).toBe(408);
    expect(normalised.retryable).toBe(true);
  });

  it('normalises client cancellation into REQUEST_CANCELLED without treating as network failure', () => {
    const cancelError: any = {
      code: 'ERR_CANCELED',
      message: 'canceled',
    };

    const normalised = normaliseError(cancelError);
    expect(normalised.code).toBe('REQUEST_CANCELLED');
    expect(normalised.message).toBe('Request was cancelled.');
    expect(normalised.retryable).toBe(false);
  });

  it('normalises standard HTTP status codes', () => {
    expect(normaliseError({ response: { status: 401 } }).code).toBe('UNAUTHORIZED');
    expect(normaliseError({ response: { status: 403 } }).code).toBe('FORBIDDEN');
    expect(normaliseError({ response: { status: 404 } }).code).toBe('NOT_FOUND');
    expect(normaliseError({ response: { status: 429 } }).code).toBe('RATE_LIMITED');
    expect(normaliseError({ response: { status: 503 } }).code).toBe('SERVICE_UNAVAILABLE');
    expect(normaliseError({ response: { status: 500 } }).code).toBe('SERVER_ERROR');
    expect(normaliseError({ code: 'ERR_NETWORK' }).code).toBe('NETWORK_ERROR');
  });
});
