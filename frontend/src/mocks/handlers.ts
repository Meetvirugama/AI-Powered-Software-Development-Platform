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
 * Day 4 — Prompt 1 additions:
 *   GET /api/v1/github/repositories — repository discovery (GitHub App repos)
 *
 * Day 4 — Prompt 2 additions:
 *   POST /api/v1/github/repositories/:githubRepoId/connect — connect a repo
 *   GET  /api/v1/repositories/:id                          — single repo detail
 *
 * Neither the connect endpoint nor the per-repo detail endpoint is yet
 * implemented in the backend. Both are mocked here until Yug/Parth confirm
 * the final contract.
 *
 * To simulate a failed connect, append ?fail=1 to the connect URL.
 */
import { http, HttpResponse } from 'msw';

const BASE = '/api/v1';

// ---------------------------------------------------------------------------
// Mock data — connected repositories (Day 3)
// Returned by GET /api/v1/repositories and GET /api/v1/repositories/:id
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
    description: 'Core backend services for the AI Platform.',
    framework: 'FastAPI',
    file_count: 142,
    symbol_count: 850,
    chunk_count: 3100,
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
    description: 'React frontend for the AI Platform.',
    framework: 'React',
    file_count: 210,
    symbol_count: 1200,
    chunk_count: 4500,
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
    description: 'Data ingestion and processing pipelines.',
    framework: 'PySpark',
    file_count: 45,
    symbol_count: 320,
    chunk_count: 1100,
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
    description: 'Experimental machine learning models.',
    framework: 'PyTorch',
    file_count: 12,
    symbol_count: 50,
    chunk_count: 120,
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
    description: 'Infrastructure as code for the platform.',
    framework: 'Terraform',
    file_count: 30,
    symbol_count: 150,
    chunk_count: 500,
  },
  // repo-new: represents a freshly connected repository (begins SYNCING).
  // Returned by the connect mock so the UI can demonstrate sync progress.
  {
    id: 'repo-new',
    github_repo_id: '123456010',
    owner: 'dev-user',
    name: 'auth-service',
    full_name: 'dev-user/auth-service',
    default_branch: 'main',
    language: 'Go',
    sync_status: 'SYNCING',
    last_synced_at: null,
    description: 'Authentication and authorization service.',
    framework: 'Gin',
    file_count: 0, // Since it's syncing, we can pretend it hasn't indexed yet
    symbol_count: 0,
    chunk_count: 0,
  },
];

// ---------------------------------------------------------------------------
// Mock data — file tree (Day 5)
// ---------------------------------------------------------------------------

const MOCK_FILES = [
  {
    id: 'file-1',
    path: 'src/',
    language: null,
    size_bytes: 0,
    line_count: 0,
    content_hash: '',
    last_indexed_at: '2026-09-24T18:00:00Z',
  },
  {
    id: 'file-2',
    path: 'src/main.py',
    language: 'Python',
    size_bytes: 1530,
    line_count: 52,
    content_hash: 'hash-main-py',
    last_indexed_at: '2026-09-24T18:00:00Z',
  },
  {
    id: 'file-3',
    path: 'src/api/',
    language: null,
    size_bytes: 0,
    line_count: 0,
    content_hash: '',
    last_indexed_at: '2026-09-24T18:00:00Z',
  },
  {
    id: 'file-4',
    path: 'src/api/routes.py',
    language: 'Python',
    size_bytes: 4200,
    line_count: 120,
    content_hash: 'hash-routes-py',
    last_indexed_at: '2026-09-24T18:00:00Z',
  },
  {
    id: 'file-5',
    path: 'requirements.txt',
    language: 'Text',
    size_bytes: 320,
    line_count: 12,
    content_hash: 'hash-req',
    last_indexed_at: '2026-09-24T18:00:00Z',
  },
  {
    id: 'file-6',
    path: 'README.md',
    language: 'Markdown',
    size_bytes: 1800,
    line_count: 45,
    content_hash: 'hash-readme',
    last_indexed_at: '2026-09-24T18:00:00Z',
  },
];

// ---------------------------------------------------------------------------
// Mock data — dependencies (Day 5)
// ---------------------------------------------------------------------------

const MOCK_DEPENDENCIES = [
  { name: 'fastapi', version: '0.110.0', ecosystem: 'pip' },
  { name: 'pydantic', version: '2.6.4', ecosystem: 'pip' },
  { name: 'uvicorn', version: '0.29.0', ecosystem: 'pip' },
  { name: 'sqlalchemy', version: '2.0.29', ecosystem: 'pip' },
  { name: 'pytest', version: '8.1.1', ecosystem: 'pip' },
];

// ---------------------------------------------------------------------------
// Mock data — available GitHub App repositories (Day 4 — Prompt 1)
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
  // -------------------------------------------------------------------------
  // Auth
  // -------------------------------------------------------------------------

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

  // -------------------------------------------------------------------------
  // Health
  // -------------------------------------------------------------------------

  // GET /api/v1/health — matches backend HealthResponse schema.
  http.get(`${BASE}/health`, () => {
    return HttpResponse.json({ status: 'ok', version: '1.0.0' });
  }),

  // -------------------------------------------------------------------------
  // Connected repositories (Day 3)
  // -------------------------------------------------------------------------

  // GET /api/v1/repositories — returns a plain list (no server pagination yet).
  // The service layer (services/repositories.ts) wraps this into a paginated shape.
  // Mock includes all four sync statuses so every UI state can be visually tested.
  http.get(`${BASE}/repositories`, () => {
    return HttpResponse.json(MOCK_REPOSITORIES);
  }),

  // GET /api/v1/repositories/:id — single repository detail (Day 4 — Prompt 2).
  //
  // Returns the full RepositoryResponse for a connected repository.
  // Supports all four sync_status values so the progress adapter can be tested:
  //   repo-1   → SYNCED
  //   repo-2   → SYNCING   (maps to CLONING in the UI progress adapter)
  //   repo-3   → FAILED
  //   repo-4   → NOT_SYNCED
  //   repo-new → SYNCING   (freshly connected, returned by connect mock)
  //
  // Returns 404 for unknown IDs.
  //
  // NOTE: This handler is MORE SPECIFIC than GET /repositories and must be
  // registered BEFORE the list handler in MSW so :id is matched correctly.
  http.get(`${BASE}/repositories/:id`, ({ params }) => {
    const { id } = params;
    const repo = MOCK_REPOSITORIES.find((r) => r.id === id);
    if (!repo) {
      return HttpResponse.json(
        {
          error: {
            code: 'REPOSITORY_NOT_FOUND',
            message: 'Repository does not exist or you do not have access.',
            retryable: false,
          },
        },
        { status: 404 },
      );
    }
    return HttpResponse.json(repo);
  }),

  // GET /api/v1/repositories/:id/files — repository file tree (Day 5).
  // Mock returns MOCK_FILES paginated.
  http.get(`${BASE}/repositories/:id/files`, ({ request }) => {
    const url = new URL(request.url);
    const page = Math.max(1, parseInt(url.searchParams.get('page') ?? '1', 10));
    const pageSize = Math.max(1, parseInt(url.searchParams.get('page_size') ?? '50', 10));

    const total = MOCK_FILES.length;
    const start = (page - 1) * pageSize;
    const items = MOCK_FILES.slice(start, start + pageSize);

    return HttpResponse.json({
      items,
      total,
      page,
      page_size: pageSize,
    });
  }),

  // GET /api/v1/repositories/:id/dependencies — top level dependencies (Day 5 Mock).
  http.get(`${BASE}/repositories/:id/dependencies`, () => {
    return HttpResponse.json(MOCK_DEPENDENCIES);
  }),

  // -------------------------------------------------------------------------
  // Repository discovery (Day 4 — Prompt 1)
  // -------------------------------------------------------------------------

  // GET /api/v1/github/repositories — repository discovery endpoint.
  // Backend not yet implemented. Mocked here until Yug/Parth confirm contract.
  //
  // Supports:
  //   ?page=<n>         — 1-based page number (default: 1)
  //   ?page_size=<n>    — items per page (default: 20)
  //   ?search=<term>    — case-insensitive name filter (server-side)
  //
  // Returns PaginatedAvailableRepositoryResponse shape.
  http.get(`${BASE}/github/repositories`, ({ request }) => {
    const url = new URL(request.url);
    const page = Math.max(1, parseInt(url.searchParams.get('page') ?? '1', 10));
    const pageSize = Math.max(1, parseInt(url.searchParams.get('page_size') ?? '20', 10));
    const search = (url.searchParams.get('search') ?? '').toLowerCase().trim();

    // Server-side search: filter by name (case-insensitive substring match).
    const filtered = search
      ? MOCK_AVAILABLE_REPOSITORIES.filter(
          (r) =>
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

  // -------------------------------------------------------------------------
  // Connect repository (Day 4 — Prompt 2)
  // -------------------------------------------------------------------------

  // POST /api/v1/github/repositories/:githubRepoId/connect
  // Backend not yet implemented. Mocked here until Yug/Parth confirm contract.
  //
  // Simulates the backend:
  //   1. Looking up the repository via GitHub API (installation token)
  //   2. Creating a repository record in our DB
  //   3. Queuing a sync job immediately
  //   4. Returning { repository_id, job_id }
  //
  // Success path (201):
  //   Returns ConnectRepositoryResponse.
  //   repository_id matches repo-new in MOCK_REPOSITORIES so that
  //   GET /api/v1/repositories/repo-new returns a realistic SYNCING response.
  //
  // Failure paths:
  //   ?fail=1           → 500 CONNECT_FAILED   (generic failure, retryable)
  //   Already-connected → 409 ALREADY_CONNECTED (not retryable)
  //
  // Error format matches the standard backend error envelope:
  //   { "error": { "code": "...", "message": "...", "retryable": bool } }
  http.post(`${BASE}/github/repositories/:githubRepoId/connect`, ({ params, request }) => {
    const { githubRepoId } = params;
    const url = new URL(request.url);

    // ?fail=1 forces a generic failure for UI error-state testing.
    const forceFail = url.searchParams.get('fail') === '1';

    // These IDs are already connected — simulate duplicate-connect error.
    const alreadyConnectedIds = ['123456001', '123456002', '123456003'];
    const isAlreadyConnected = alreadyConnectedIds.includes(githubRepoId as string);

    if (forceFail) {
      return HttpResponse.json(
        {
          error: {
            code: 'CONNECT_FAILED',
            message: 'Failed to connect the repository. Please try again.',
            retryable: true,
          },
        },
        { status: 500 },
      );
    }

    if (isAlreadyConnected) {
      return HttpResponse.json(
        {
          error: {
            code: 'ALREADY_CONNECTED',
            message: 'This repository is already connected to the platform.',
            retryable: false,
          },
        },
        { status: 409 },
      );
    }

    // Success: return repository_id + queued job_id.
    // repository_id = repo-new so the caller can poll
    // GET /api/v1/repositories/repo-new and see SYNCING status.
    return HttpResponse.json(
      {
        repository_id: 'repo-new',
        job_id: 'job-mock-001',
      },
      { status: 201 },
    );
  }),

  // -------------------------------------------------------------------------
  // Chat — Day 7
  //
  // POST /api/v1/repositories/:id/chat
  //
  // Matches the real backend contract:
  //   Request:  { question: string, history: { role, content }[] }
  //   Response: { answer: string, sources: SourceReference[], confidence: "high"|"medium"|"low" }
  //
  // Source fields match backend SourceReference (backend/ai/schemas/output.py):
  //   { file: string, start_line: number, end_line: number, symbol?: string | null }
  //
  // Error simulation: include "fail" in the question body.
  // -------------------------------------------------------------------------

  http.post(`${BASE}/repositories/:id/chat`, async ({ params, request }) => {
    const { id } = params as { id: string };

    // Parse request body — real contract: { question, history }
    let question = '';
    try {
      const body = await request.json() as { question?: string; history?: unknown[] };
      question = body?.question ?? '';
    } catch {
      // Malformed body — treat as empty question.
    }

    // Force-error simulation: include "fail" in the question.
    if (question.toLowerCase().includes('fail')) {
      return HttpResponse.json(
        {
          error: {
            code: 'CHAT_ERROR',
            message: 'The assistant encountered an error processing your question.',
            retryable: true,
          },
        },
        { status: 500 },
      );
    }

    // Deterministic mock response based on repository ID.
    const repoName =
      MOCK_REPOSITORIES.find((r) => r.id === id)?.name ?? 'this repository';

    const mockAnswer =
      `In ${repoName}, authentication is handled through the backend authentication module. ` +
      `The \`/api/v1/auth\` route group manages OAuth login via GitHub, ` +
      `token validation, and session management using HTTP-only cookies. ` +
      `The \`AuthService\` class in \`backend/app/services/auth_service.py\` ` +
      `encapsulates the JWT creation and verification logic. ` +
      `Route-level protection is enforced through a FastAPI dependency ` +
      `injected into each protected endpoint.`;

    // Sources use the REAL backend field names: file, start_line, end_line, symbol.
    const mockSources = [
      {
        file: 'backend/app/api/v1/auth.py',
        start_line: 1,
        end_line: 45,
        symbol: 'router',
      },
      {
        file: 'backend/app/services/auth_service.py',
        start_line: 22,
        end_line: 68,
        symbol: 'AuthService',
      },
      {
        file: 'backend/app/core/dependencies.py',
        start_line: 10,
        end_line: 30,
        symbol: 'get_current_user',
      },
    ];

    return HttpResponse.json({
      answer: mockAnswer,
      sources: mockSources,
      confidence: 'high',
    });
  }),
];

