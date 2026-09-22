/**
 * MSW request handlers.
 *
 * Day 1 — minimal infrastructure only.
 * These handlers mock backend endpoints that are not yet implemented,
 * allowing frontend development to proceed independently.
 *
 * DO NOT add application business logic here.
 * DO NOT invent response fields not specified by the backend contract.
 *
 * Add handlers here as the backend contract is specified (Day 2+).
 * Remove handlers as real endpoints become available.
 */
import { http, HttpResponse } from 'msw';

const BASE = '/api/v1';

export const handlers = [
  /**
   * GET /api/v1/auth/me
   * Returns a stub authenticated user so frontend pages can be built while
   * Yug implements the real endpoint on Day 2.
   *
   * Remove this handler once the real endpoint is available.
   */
  http.get(`${BASE}/auth/me`, () => {
    return HttpResponse.json({
      id: 'mock-user-1',
      login: 'dev-user',
      name: 'Dev User',
      avatar_url: null,
    });
  }),

  /**
   * GET /api/v1/health
   * Matches the finalized HealthResponse schema from backend/app/schemas/health.py.
   */
  http.get(`${BASE}/health`, () => {
    return HttpResponse.json({ status: 'ok', version: '1.0.0' });
  }),
];
