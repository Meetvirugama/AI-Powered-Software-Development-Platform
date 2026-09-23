/**
 * MSW request handlers — Day 2.
 *
 * These mocks allow the full authentication flow to be exercised without
 * the real backend running. The GitHub login button still redirects to the
 * real backend URL (MSW cannot intercept browser navigations).
 *
 * Default state: authenticated (GET /auth/me returns a valid user).
 *
 * To test the unauthenticated state during development, temporarily swap
 * the /auth/me handler to return HttpResponse.json({}, { status: 401 }).
 * Example (browser console):
 *
 *   worker.use(
 *     http.get('/api/v1/auth/me', () =>
 *       HttpResponse.json({}, { status: 401 })
 *     )
 *   );
 *
 * The worker is exposed on window.__mswWorker in development builds via
 * src/mocks/browser.ts if you need to inspect it.
 */
import { http, HttpResponse } from 'msw';

const BASE = '/api/v1';

export const handlers = [
  /**
   * GET /api/v1/auth/me
   * Returns the authenticated user. Matches backend AuthenticatedUser schema.
   */
  http.get(`${BASE}/auth/me`, () => {
    return HttpResponse.json({
      id: 'mock-user-1',
      login: 'dev-user',
      name: 'Dev User',
      email: 'dev@example.com',
      avatar_url: null,
    });
  }),

  /**
   * POST /api/v1/auth/logout
   * Backend returns 204 No Content and deletes the auth cookie.
   */
  http.post(`${BASE}/auth/logout`, () => {
    return new HttpResponse(null, { status: 204 });
  }),

  /**
   * GET /api/v1/health
   * Matches backend HealthResponse schema.
   */
  http.get(`${BASE}/health`, () => {
    return HttpResponse.json({ status: 'ok', version: '1.0.0' });
  }),
];
