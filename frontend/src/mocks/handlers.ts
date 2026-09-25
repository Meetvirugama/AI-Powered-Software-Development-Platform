/**
 * MSW request handlers — Day 2 / Day 3.
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

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const MOCK_REPOSITORIES = [
  {
    id: 'repo-1',
    github_repo_id: '123456001',
    owner: 'dev-user',
    name: 'platform-backend',
    full_name: 'dev-user/platform-backend',
    default_branch: 'main',
    language: 'Python',
    sync_status: 'SYNCED',
    last_synced_at: '2026-09-24T18:00:00Z',
  },
  {
    id: 'repo-2',
    github_repo_id: '123456002',
    owner: 'dev-user',
    name: 'platform-frontend',
    full_name: 'dev-user/platform-frontend',
    default_branch: 'main',
    language: 'TypeScript',
    sync_status: 'SYNCING',
    last_synced_at: null,
  },
  {
    id: 'repo-3',
    github_repo_id: '123456003',
    owner: 'dev-user',
    name: 'data-pipeline',
    full_name: 'dev-user/data-pipeline',
    default_branch: 'develop',
    language: 'Python',
    sync_status: 'FAILED',
    last_synced_at: '2026-09-23T09:30:00Z',
  },
  {
    id: 'repo-4',
    github_repo_id: '123456004',
    owner: 'dev-user',
    name: 'ml-experiments',
    full_name: 'dev-user/ml-experiments',
    default_branch: 'main',
    language: 'Python',
    sync_status: 'NOT_SYNCED',
    last_synced_at: null,
  },
  {
    id: 'repo-5',
    github_repo_id: '123456005',
    owner: 'dev-user',
    name: 'infrastructure',
    full_name: 'dev-user/infrastructure',
    default_branch: 'main',
    language: null,
    sync_status: 'SYNCED',
    last_synced_at: '2026-09-24T12:15:00Z',
  },
];

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

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

  // GET /api/v1/repositories — returns a plain list (no server pagination yet).
  // The service layer (services/repositories.ts) wraps this into a paginated shape.
  // Mock includes all four sync statuses so every UI state can be visually tested.
  http.get(`${BASE}/repositories`, () => {
    return HttpResponse.json(MOCK_REPOSITORIES);
  }),

  // GET /api/v1/health — matches backend HealthResponse schema.
  http.get(`${BASE}/health`, () => {
    return HttpResponse.json({ status: 'ok', version: '1.0.0' });
  }),
];
