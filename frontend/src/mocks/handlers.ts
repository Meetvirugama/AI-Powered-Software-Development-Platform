/**
 * MSW request handlers — Day 2 / Day 3 / Day 4.
 *
 * Default state: authenticated (GET /auth/me returns a valid user).
 *
 * To test the unauthenticated state, edit the /auth/me handler below to
 * return a 401 response, then restart the dev server:
 *
 *   return new HttpResponse(null, { status: 401 });
 *
 * Day 4 addition:
 *   GET /api/v1/github/repositories — repository discovery (GitHub App repos)
 *   This endpoint does not yet exist in the backend. It is mocked here until
 *   Parth/Yug implement GET /api/v1/github/repositories.
 */
import { http, HttpResponse } from 'msw';

const BASE = '/api/v1';

// ---------------------------------------------------------------------------
// Mock data — connected repositories (Day 3)
// Returned by GET /api/v1/repositories
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
// Mock data — available GitHub App repositories (Day 4)
//
// Returned by GET /api/v1/github/repositories (backend not yet implemented).
//
// Design:
//   - 22 entries so pagination can be tested across multiple pages
//     (e.g. page_size=10 → 3 pages; page_size=20 → 2 pages)
//   - Mix of connected (is_connected: true) and unconnected repositories
//   - Diverse languages and branch names for realistic display testing
//   - github_repo_id values match MOCK_REPOSITORIES where applicable so the
//     selector can detect already-connected repos
// ---------------------------------------------------------------------------

const MOCK_AVAILABLE_REPOSITORIES = [
  // Connected repos — these also appear in MOCK_REPOSITORIES above
  {
    github_repo_id: '123456001',
    owner: 'dev-user',
    name: 'platform-backend',
    full_name: 'dev-user/platform-backend',
    default_branch: 'main',
    language: 'Python',
    is_connected: true,
  },
  {
    github_repo_id: '123456002',
    owner: 'dev-user',
    name: 'platform-frontend',
    full_name: 'dev-user/platform-frontend',
    default_branch: 'main',
    language: 'TypeScript',
    is_connected: true,
  },
  {
    github_repo_id: '123456003',
    owner: 'dev-user',
    name: 'data-pipeline',
    full_name: 'dev-user/data-pipeline',
    default_branch: 'develop',
    language: 'Python',
    is_connected: true,
  },
  // Unconnected repos — available via GitHub App but not yet on the platform
  {
    github_repo_id: '123456010',
    owner: 'dev-user',
    name: 'auth-service',
    full_name: 'dev-user/auth-service',
    default_branch: 'main',
    language: 'Go',
    is_connected: false,
  },
  {
    github_repo_id: '123456011',
    owner: 'dev-user',
    name: 'api-gateway',
    full_name: 'dev-user/api-gateway',
    default_branch: 'main',
    language: 'TypeScript',
    is_connected: false,
  },
  {
    github_repo_id: '123456012',
    owner: 'dev-user',
    name: 'vector-search',
    full_name: 'dev-user/vector-search',
    default_branch: 'main',
    language: 'Python',
    is_connected: false,
  },
  {
    github_repo_id: '123456013',
    owner: 'dev-user',
    name: 'rag-pipeline',
    full_name: 'dev-user/rag-pipeline',
    default_branch: 'main',
    language: 'Python',
    is_connected: false,
  },
  {
    github_repo_id: '123456014',
    owner: 'dev-user',
    name: 'code-scanner',
    full_name: 'dev-user/code-scanner',
    default_branch: 'main',
    language: 'Rust',
    is_connected: false,
  },
  {
    github_repo_id: '123456015',
    owner: 'dev-user',
    name: 'embedding-service',
    full_name: 'dev-user/embedding-service',
    default_branch: 'main',
    language: 'Python',
    is_connected: false,
  },
  {
    github_repo_id: '123456016',
    owner: 'dev-user',
    name: 'llm-gateway',
    full_name: 'dev-user/llm-gateway',
    default_branch: 'main',
    language: 'Python',
    is_connected: false,
  },
  {
    github_repo_id: '123456017',
    owner: 'dev-user',
    name: 'indexer-worker',
    full_name: 'dev-user/indexer-worker',
    default_branch: 'develop',
    language: 'Go',
    is_connected: false,
  },
  {
    github_repo_id: '123456018',
    owner: 'dev-user',
    name: 'shared-ui',
    full_name: 'dev-user/shared-ui',
    default_branch: 'main',
    language: 'TypeScript',
    is_connected: false,
  },
  {
    github_repo_id: '123456019',
    owner: 'dev-user',
    name: 'deploy-scripts',
    full_name: 'dev-user/deploy-scripts',
    default_branch: 'main',
    language: 'Shell',
    is_connected: false,
  },
  {
    github_repo_id: '123456020',
    owner: 'dev-user',
    name: 'config-server',
    full_name: 'dev-user/config-server',
    default_branch: 'main',
    language: 'Java',
    is_connected: false,
  },
  {
    github_repo_id: '123456021',
    owner: 'dev-user',
    name: 'feature-flags',
    full_name: 'dev-user/feature-flags',
    default_branch: 'main',
    language: 'TypeScript',
    is_connected: false,
  },
  {
    github_repo_id: '123456022',
    owner: 'dev-user',
    name: 'monitoring-stack',
    full_name: 'dev-user/monitoring-stack',
    default_branch: 'main',
    language: null,
    is_connected: false,
  },
  {
    github_repo_id: '123456023',
    owner: 'dev-user',
    name: 'db-migrations',
    full_name: 'dev-user/db-migrations',
    default_branch: 'main',
    language: 'SQL',
    is_connected: false,
  },
  {
    github_repo_id: '123456024',
    owner: 'dev-user',
    name: 'event-bus',
    full_name: 'dev-user/event-bus',
    default_branch: 'main',
    language: 'Go',
    is_connected: false,
  },
  {
    github_repo_id: '123456025',
    owner: 'dev-user',
    name: 'notification-service',
    full_name: 'dev-user/notification-service',
    default_branch: 'main',
    language: 'TypeScript',
    is_connected: false,
  },
  {
    github_repo_id: '123456026',
    owner: 'dev-user',
    name: 'test-harness',
    full_name: 'dev-user/test-harness',
    default_branch: 'main',
    language: 'Python',
    is_connected: false,
  },
  {
    github_repo_id: '123456027',
    owner: 'dev-user',
    name: 'docs-site',
    full_name: 'dev-user/docs-site',
    default_branch: 'gh-pages',
    language: 'MDX',
    is_connected: false,
  },
  {
    github_repo_id: '123456028',
    owner: 'dev-user',
    name: 'cli-tools',
    full_name: 'dev-user/cli-tools',
    default_branch: 'main',
    language: 'Rust',
    is_connected: false,
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

  // ---------------------------------------------------------------------------
  // Day 4 — GET /api/v1/github/repositories
  //
  // Repository discovery endpoint (backend not yet implemented).
  //
  // Supports:
  //   ?page=<n>         — 1-based page number (default: 1)
  //   ?page_size=<n>    — items per page (default: 20)
  //   ?search=<term>    — case-insensitive name filter (server-side)
  //
  // Returns PaginatedAvailableRepositoryResponse shape.
  // ---------------------------------------------------------------------------
  http.get(`${BASE}/github/repositories`, ({ request }) => {
    const url = new URL(request.url);
    const page = Math.max(1, parseInt(url.searchParams.get('page') ?? '1', 10));
    const pageSize = Math.max(1, parseInt(url.searchParams.get('page_size') ?? '20', 10));
    const search = (url.searchParams.get('search') ?? '').toLowerCase().trim();

    // Server-side search: filter by name (case-insensitive substring match).
    const filtered = search
      ? MOCK_AVAILABLE_REPOSITORIES.filter((r) =>
          r.name.toLowerCase().includes(search) ||
          r.full_name.toLowerCase().includes(search),
        )
      : MOCK_AVAILABLE_REPOSITORIES;

    // Server-side pagination.
    const total = filtered.length;
    const total_pages = Math.max(1, Math.ceil(total / pageSize));
    const start = (page - 1) * pageSize;
    const items = filtered.slice(start, start + pageSize);

    return HttpResponse.json({
      items,
      total,
      page,
      page_size: pageSize,
      total_pages,
    });
  }),
];
