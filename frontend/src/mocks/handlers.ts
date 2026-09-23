/**
 * MSW request handlers — Day 2.
 *
 * Default state: authenticated (GET /auth/me returns a valid user).
 *
 * To test the unauthenticated state, edit the /auth/me handler below to
 * return a 401 response, then restart the dev server:
 *
 *   return new HttpResponse(null, { status: 401 });
 */
import { http, HttpResponse } from 'msw';

const BASE = '/api/v1';

export const handlers = [
  // GET /api/v1/auth/me — returns the authenticated user.
  // Matches backend AuthenticatedUser schema (backend/app/schemas/auth.py).
  http.get(`${BASE}/auth/me`, () => {
    return HttpResponse.json({
      id: 'mock-user-1',
      login: 'dev-user',
      name: 'Dev User',
      email: 'dev@example.com',
      avatar_url: null,
    });
  }),

  // POST /api/v1/auth/logout — backend returns 204 and deletes the auth cookie.
  http.post(`${BASE}/auth/logout`, () => {
    return new HttpResponse(null, { status: 204 });
  }),

  // GET /api/v1/health — matches backend HealthResponse schema.
  http.get(`${BASE}/health`, () => {
    return HttpResponse.json({ status: 'ok', version: '1.0.0' });
  }),
];
