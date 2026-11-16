import { describe, it, expect } from 'vitest';
import { apiClient } from '../services/api';
import type { InternalAxiosRequestConfig } from 'axios';

describe('TST-19: Frontend Timeout Policy (OPT-02)', () => {
  // Extract the registered request interceptor
  // Axios stores handlers in apiClient.interceptors.request.handlers
  const requestInterceptor = (apiClient.interceptors.request as any).handlers[0]?.fulfilled;

  it('allocates 180s timeout to AI mutation operations (POST/PUT/PATCH)', () => {
    const aiEndpoints = [
      { method: 'post', url: '/api/v1/repositories/repo-1/explain' },
      { method: 'post', url: '/api/v1/repositories/repo-1/detect-bugs' },
      { method: 'post', url: '/api/v1/repositories/repo-1/generate-tests' },
      { method: 'post', url: '/api/v1/repositories/repo-1/review' },
      { method: 'post', url: '/api/v1/tasks/task-1/plan' },
      { method: 'post', url: '/api/v1/tasks/task-1/execute' },
      { method: 'post', url: '/api/v1/tasks/task-1/repair' },
      { method: 'post', url: '/api/v1/tasks/task-1/verify' },
      { method: 'post', url: '/api/v1/chat' },
      { method: 'post', url: '/api/v1/run-workflow' },
    ];

    for (const endpoint of aiEndpoints) {
      const config: InternalAxiosRequestConfig = {
        method: endpoint.method,
        url: endpoint.url,
        headers: {} as any,
        timeout: 30000,
      };

      const result = requestInterceptor(config);
      expect(result.timeout, `Endpoint ${endpoint.url} should receive 180s timeout`).toBe(180000);
    }
  });

  it('retains default 30s timeout for GET endpoints even if path contains AI keywords', () => {
    const getEndpoints = [
      '/api/v1/tasks/task-1/tests',
      '/api/v1/tasks/task-1/plan',
      '/api/v1/analysis/review/settings',
      '/api/v1/repositories/repo-1/chat/history',
      '/api/v1/repositories',
      '/api/v1/health/live',
    ];

    for (const url of getEndpoints) {
      const config: InternalAxiosRequestConfig = {
        method: 'get',
        url,
        headers: {} as any,
        timeout: 30000,
      };

      const result = requestInterceptor(config);
      expect(result.timeout, `GET ${url} must retain standard 30s timeout`).toBe(30000);
    }
  });

  it('preserves explicitly specified custom timeouts on AI requests', () => {
    const customConfig: InternalAxiosRequestConfig = {
      method: 'post',
      url: '/api/v1/repositories/repo-1/explain',
      headers: {} as any,
      timeout: 45000, // custom explicit timeout
    };

    const result = requestInterceptor(customConfig);
    expect(result.timeout).toBe(45000);
  });
});
