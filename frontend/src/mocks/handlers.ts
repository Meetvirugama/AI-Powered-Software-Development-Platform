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

  // POST /api/v1/repositories/:id/chat — repository-scoped chat (Day 6 + Day 7).
  // Matches backend schema:
  //   Request:  { question: string (1-4000 chars, non-whitespace), history: ChatHistoryMessage[] (max 50) }
  //   Response: RepositoryAnswer { answer: string, sources: SourceReference[], confidence: 'high' | 'medium' | 'low' }
  http.post(`${BASE}/repositories/:id/chat`, /**
   * Return canned answers, citations, and confidence for known mock repositories
   * or the demo UUID 11111111-1111-1111-1111-111111111111; otherwise return 404.
   * Invalid JSON, a missing/non-string/blank question, more than 4000 UTF-16 code
   * units before trimming, or an array history longer than 50 produce 422.
   * History entries and non-array history are not validated or used in answers.
   * After validation, questions containing `503` or case-insensitive `unavailable`
   * produce retryable 503 responses; otherwise `500` or case-insensitive
   * `server error` produce non-retryable 500 responses.
   */ async ({ params, request }) => {
    const { id } = params;

    // Route validation: repository existence
    const repo = MOCK_REPOSITORIES.find((r) => r.id === id);
    if (!repo && id !== '11111111-1111-1111-1111-111111111111') {
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

    let body: any;
    try {
      body = await request.json();
    } catch {
      return HttpResponse.json(
        {
          error: {
            code: 'INVALID_REQUEST',
            message: 'Invalid JSON request body.',
            retryable: false,
          },
        },
        { status: 422 },
      );
    }

    const question = typeof body?.question === 'string' ? body.question : '';
    const trimmedQuestion = question.trim();

    // Empty or whitespace-only question rejection (matches backend Pydantic validator)
    if (!trimmedQuestion) {
      return HttpResponse.json(
        {
          error: {
            code: 'INVALID_REQUEST',
            message: 'question must contain non-whitespace characters',
            retryable: false,
          },
        },
        { status: 422 },
      );
    }

    // Question length validation (1 - 4000 chars)
    if (question.length > 4000) {
      return HttpResponse.json(
        {
          error: {
            code: 'INVALID_REQUEST',
            message: 'question exceeds maximum length of 4000 characters',
            retryable: false,
          },
        },
        { status: 422 },
      );
    }

    // History validation (max 50 messages)
    if (Array.isArray(body?.history) && body.history.length > 50) {
      return HttpResponse.json(
        {
          error: {
            code: 'INVALID_REQUEST',
            message: 'history exceeds maximum length of 50 messages',
            retryable: false,
          },
        },
        { status: 422 },
      );
    }

    // Simulated 503 Service Unavailable scenario
    if (trimmedQuestion.includes('503') || trimmedQuestion.toLowerCase().includes('unavailable')) {
      return HttpResponse.json(
        {
          error: {
            code: 'SERVICE_UNAVAILABLE',
            message: 'Repository chat is not available because the RAG pipeline is temporarily unavailable.',
            retryable: true,
          },
        },
        { status: 503 },
      );
    }

    // Simulated 500 Server Error scenario
    if (trimmedQuestion.includes('500') || trimmedQuestion.toLowerCase().includes('server error')) {
      return HttpResponse.json(
        {
          error: {
            code: 'INTERNAL_ERROR',
            message: 'An internal server error occurred while generating the answer.',
            retryable: false,
          },
        },
        { status: 500 },
      );
    }

    // Grounded mock responses matching RepositoryAnswer shape
    const q = trimmedQuestion.toLowerCase();
    let answer = `Based on the repository source files, the project uses FastAPI for backend services and React with TypeScript for the frontend client interface.`;
    let sources = [
      {
        file: 'backend/app/main.py',
        start_line: 1,
        end_line: 20,
        symbol: 'app',
      },
      {
        file: 'frontend/src/App.tsx',
        start_line: 15,
        end_line: 45,
        symbol: 'App',
      },
    ];
    let confidence: 'high' | 'medium' | 'low' = 'high';

    if (q.includes('auth') || q.includes('login') || q.includes('token') || q.includes('cookie')) {
      answer = `Authentication is managed via HTTP-only session cookies and GitHub OAuth. In \`backend/app/api/v1/auth.py\`, the \`/auth/callback\` endpoint issues secure session cookies, while client requests authenticate automatically using \`withCredentials: true\`.`;
      sources = [
        {
          file: 'backend/app/api/v1/auth.py',
          start_line: 25,
          end_line: 60,
          symbol: 'auth_callback',
        },
        {
          file: 'frontend/src/services/api.ts',
          start_line: 10,
          end_line: 25,
          symbol: 'apiClient',
        },
      ];
      confidence = 'high';
    } else if (q.includes('bug') || q.includes('scan') || q.includes('detect')) {
      answer = `The bug detection pipeline combines static AST heuristics with AI analysis in \`backend/app/services/bug_detector.py\`. Scans are initiated per-file or symbol and return categorized findings with code snippets.`;
      sources = [
        {
          file: 'backend/app/services/bug_detector.py',
          start_line: 40,
          end_line: 85,
          symbol: 'detect_bugs_in_file',
        },
      ];
      confidence = 'high';
    } else if (q.includes('test') || q.includes('pytest') || q.includes('generate')) {
      answer = `Test generation automatically identifies target framework conventions (e.g. pytest or Vitest) and drafts isolated test suites covering normal, edge, and failure scenarios.`;
      sources = [
        {
          file: 'tests/test_services.py',
          start_line: 10,
          end_line: 55,
          symbol: 'test_pipeline',
        },
      ];
      confidence = 'medium';
    }

    return HttpResponse.json({
      answer,
      sources,
      confidence,
    });
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

  // GET /api/v1/repositories/:repositoryId/files/:fileId/content — file content and symbols.
  http.get(`${BASE}/repositories/:repositoryId/files/:fileId/content`, ({ params }) => {
    const { fileId } = params as { repositoryId: string; fileId: string };
    const file = MOCK_FILES.find((f) => f.id === fileId);

    if (!file || file.path.endsWith('/')) {
      return HttpResponse.json(
        {
          error: {
            code: 'FILE_NOT_FOUND',
            message: 'File does not exist or has not been indexed.',
            retryable: false,
          },
        },
        { status: 404 },
      );
    }

    const mockContentMap: Record<string, { content: string; symbols: any[] }> = {
      'file-2': {
        content: `"""Application entry point and service bootstrap."""\nfrom fastapi import FastAPI\nfrom app.api.routes import router\n\napp = FastAPI(title="Platform API", version="1.0.0")\napp.include_router(router)\n\n@app.get("/health")\ndef health_check():\n    """Return service health status."""\n    return {"status": "healthy", "service": "platform-backend"}\n\nif __name__ == "__main__":\n    import uvicorn\n    uvicorn.run(app, host="0.0.0.0", port=8000)\n`,
        symbols: [
          {
            id: 'sym-1',
            file_id: 'file-2',
            name: 'health_check',
            kind: 'function',
            start_line: 9,
            end_line: 12,
            signature: '() -> dict',
            parent_id: null,
          },
        ],
      },
      'file-4': {
        content: `from fastapi import APIRouter, HTTPException, Depends\nfrom typing import List\n\nrouter = APIRouter(prefix="/v1")\n\n@router.get("/items")\ndef list_items():\n    return [{"id": 1, "name": "Item A"}, {"id": 2, "name": "Item B"}]\n\n@router.post("/items")\ndef create_item(payload: dict):\n    if not payload.get("name"):\n        raise HTTPException(status_code=400, detail="Name required")\n    return {"id": 3, **payload}\n`,
        symbols: [
          {
            id: 'sym-2',
            file_id: 'file-4',
            name: 'list_items',
            kind: 'function',
            start_line: 6,
            end_line: 8,
            signature: '() -> list',
            parent_id: null,
          },
          {
            id: 'sym-3',
            file_id: 'file-4',
            name: 'create_item',
            kind: 'function',
            start_line: 10,
            end_line: 14,
            signature: '(payload: dict) -> dict',
            parent_id: null,
          },
        ],
      },
      'file-5': {
        content: `fastapi==0.110.0\npydantic==2.6.4\nuvicorn==0.29.0\nsqlalchemy==2.0.29\npytest==8.1.1\n`,
        symbols: [],
      },
      'file-6': {
        content: `# Platform Backend\n\nCore microservice powering code intelligence, repository indexing, and AST analysis.\n\n## Getting Started\n\n1. Install dependencies: \`pip install -r requirements.txt\`\n2. Run server: \`python src/main.py\`\n`,
        symbols: [],
      },
    };

    const details = mockContentMap[file.id] || {
      content: `// Source content for ${file.path}\nconsole.log("File loaded");\n`,
      symbols: [],
    };

    return HttpResponse.json({
      id: file.id,
      path: file.path,
      language: file.language,
      size_bytes: file.size_bytes,
      line_count: details.content.split('\n').length,
      content: details.content,
      symbols: details.symbols,
    });
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

  // -------------------------------------------------------------------------
  // Feature 1: Code Explanation (Week 2 Day 2)
  //
  // POST /api/v1/repositories/:id/explain
  //
  // Matches real backend contract in backend/app/schemas/analysis.py
  // -------------------------------------------------------------------------
  http.post(`${BASE}/repositories/:id/explain`, async ({ params, request }) => {
    const { id } = params as { id: string };
    let body: any = null;
    try {
      body = (await request.json()) as any;
    } catch {
      // Malformed body
    }

    const target = body?.target || {
      type: 'file',
      path: body?.path || 'src/main.py',
    };

    // Error simulation paths for testing
    if (target.path?.includes('500') || target.path?.includes('fail')) {
      return HttpResponse.json(
        {
          error: {
            code: 'ANALYSIS_FAILED',
            message: 'AI analysis output failed validation and could not be repaired.',
            retryable: false,
          },
        },
        { status: 500 }
      );
    }

    if (target.path?.includes('503') || target.path?.includes('timeout')) {
      return HttpResponse.json(
        {
          error: {
            code: 'SERVICE_UNAVAILABLE',
            message: 'AI analysis provider is temporarily unavailable. Please try again.',
            retryable: true,
          },
        },
        { status: 503 }
      );
    }

    const filePath = target.path || 'src/main.py';
    const isSymbol = target.type === 'symbol' && Boolean(target.symbol);
    const isRange = target.type === 'range' && Boolean(target.start_line);

    const startLine = target.start_line ?? 1;
    const endLine = target.end_line ?? 25;

    const explanation = {
      purpose: isSymbol
        ? `Implements the "${target.symbol}" function to handle core execution logic in ${filePath}.`
        : isRange
        ? `Executes procedural logic and input validation between lines ${startLine} and ${endLine} of ${filePath}.`
        : `Serves as the main module entry point and operational coordinator for ${filePath}.`,
      logic_flow: [
        'Inspect incoming arguments and verify preconditions.',
        'Dispatch operational calls to internal helper routines and dependencies.',
        'Normalize and validate resulting data structures.',
        'Return validated execution result or raise typed exception.',
      ],
      key_symbols: isSymbol
        ? [
            {
              name: target.symbol,
              kind: 'function',
              role: 'Primary target routine under analysis.',
              start_line: startLine,
              end_line: endLine,
            },
            {
              name: 'validate_payload',
              kind: 'function',
              role: 'Precondition sanitization helper.',
              start_line: startLine,
              end_line: Math.min(startLine + 5, endLine),
            },
          ]
        : [
            {
              name: 'health_check',
              kind: 'function',
              role: 'Returns service health status and diagnostics.',
              start_line: 9,
              end_line: 12,
            },
            {
              name: 'app',
              kind: 'variable',
              role: 'FastAPI application instance bootstrapping routes.',
              start_line: 5,
              end_line: 7,
            },
          ],
      inputs_and_outputs: isSymbol
        ? `Accepts arguments appropriate for "${target.symbol}"; yields transformed data models or raises APIError.`
        : `Accepts HTTP requests and CLI bootstrap triggers; emits JSON responses or system status dictionaries.`,
      dependencies: [
        'fastapi (HTTP routing and middleware)',
        'pydantic (schema models and input parsing)',
        'uvicorn (ASGI server runner)',
      ],
      assumptions_and_limitations: [
        'Assumes standard ASGI environment configuration and accessible port bindings.',
        'Dynamic caller sites outside the indexed symbol graph cannot be inferred.',
      ],
      sources: [
        {
          repository_id: id,
          file_path: filePath,
          start_line: startLine,
          end_line: endLine,
          revision: target.revision ?? 'main',
          symbol_name: target.symbol ?? null,
        },
      ],
      confidence: 'high' as const,
      missing_context: isSymbol
        ? [`No direct test callers found in symbol graph for "${target.symbol}".`]
        : [],
    };

    return HttpResponse.json({
      run_id: 'mock-run-' + Date.now(),
      repository_id: id,
      status: 'COMPLETED',
      target,
      revision: target.revision ?? 'main',
      explanation,
      created_at: new Date().toISOString(),
    });
  }),

  // -------------------------------------------------------------------------
  // Feature 2: Dedicated Bug Detection (Week 2 Day 3)
  //
  // POST /api/v1/repositories/:id/detect-bugs
  //
  // Matches real backend contract in backend/app/schemas/analysis.py
  // -------------------------------------------------------------------------
  http.post(`${BASE}/repositories/:id/detect-bugs`, async ({ params, request }) => {
    const { id } = params as { id: string };
    let body: any = null;
    try {
      body = (await request.json()) as any;
    } catch {
      // Malformed body
    }

    const target = body?.target || {
      type: 'file',
      path: body?.path || 'src/main.py',
    };

    // Error simulation paths for testing
    if (target.path?.includes('500') || target.path?.includes('fail')) {
      return HttpResponse.json(
        {
          error: {
            code: 'ANALYSIS_FAILED',
            message: 'Bug detection scan failed due to an unrecoverable internal error.',
            retryable: false,
          },
        },
        { status: 500 }
      );
    }

    if (target.path?.includes('503') || target.path?.includes('timeout')) {
      return HttpResponse.json(
        {
          error: {
            code: 'SERVICE_UNAVAILABLE',
            message: 'Bug detection service is temporarily unavailable. Please retry.',
            retryable: true,
          },
        },
        { status: 503 }
      );
    }

    const filePath = target.path || 'src/main.py';

    // Zero findings / clean scan simulation for README.md or clean files
    if (filePath.toLowerCase().endsWith('readme.md') || filePath.includes('clean')) {
      return HttpResponse.json({
        run_id: 'mock-bug-run-' + Date.now(),
        repository_id: id,
        status: 'COMPLETED',
        target,
        revision: target.revision ?? 'main',
        findings: [],
        total_findings: 0,
        static_findings_count: 0,
        ai_findings_count: 0,
        missing_context: [],
        created_at: new Date().toISOString(),
      });
    }

    const allFindings = [
      {
        id: 'mock-bug-1',
        category: 'off_by_one',
        severity: 'CRITICAL',
        title: 'Off-by-one loop bound in collection pagination',
        description: 'Loop termination condition uses len(items) + 1 with 0-indexed offset, causing potential IndexError.',
        source_reference: {
          repository_id: id,
          file_path: filePath,
          start_line: 12,
          end_line: 15,
          revision: target.revision ?? 'main',
          symbol_name: target.symbol ?? null,
        },
        evidence: 'for i in range(0, len(items) + 1):',
        suggested_fix: 'for i in range(0, len(items)):  # Correct boundary',
        confidence: 'high',
        is_uncertain: false,
        source_type: 'COMBINED',
        rule_id: 'AST001',
      },
      {
        id: 'mock-bug-2',
        category: 'security',
        severity: 'HIGH',
        title: 'Potential SQL query string interpolation',
        description: 'Raw string formatting detected inside database execute call; risk of SQL injection vulnerability.',
        source_reference: {
          repository_id: id,
          file_path: filePath,
          start_line: 28,
          end_line: 30,
          revision: target.revision ?? 'main',
          symbol_name: null,
        },
        evidence: 'db.execute(f"SELECT * FROM items WHERE id = {item_id}")',
        suggested_fix: 'db.execute("SELECT * FROM items WHERE id = :id", {"id": item_id})',
        confidence: 'high',
        is_uncertain: false,
        source_type: 'STATIC',
        rule_id: 'B608',
      },
      {
        id: 'mock-bug-3',
        category: 'null_safety',
        severity: 'MEDIUM',
        title: 'Unchecked nullable property access on optional configuration',
        description: 'Variable config is accessed without ensuring None check after initialization.',
        source_reference: {
          repository_id: id,
          file_path: filePath,
          start_line: 42,
          end_line: 45,
          revision: target.revision ?? 'main',
          symbol_name: null,
        },
        evidence: 'return config.timeout_seconds',
        suggested_fix: 'return config.timeout_seconds if config else DEFAULT_TIMEOUT',
        confidence: 'medium',
        is_uncertain: true,
        source_type: 'AI',
        rule_id: null,
      },
      {
        id: 'mock-bug-4',
        category: 'resource_leak',
        severity: 'LOW',
        title: 'Unclosed file descriptor across asynchronous task boundary',
        description: 'File handle opened without a context manager inside background task.',
        source_reference: {
          repository_id: id,
          file_path: filePath,
          start_line: null,
          end_line: null,
          revision: target.revision ?? 'main',
          symbol_name: null,
        },
        evidence: 'f = open(log_path, "w")',
        suggested_fix: null,
        confidence: 'low',
        is_uncertain: false,
        source_type: 'AI',
        rule_id: null,
      },
      {
        id: 'mock-bug-5',
        category: 'other',
        severity: 'INFO',
        title: 'Mutable default argument in function signature',
        description: 'Default argument cache: list = [] is shared across function invocations.',
        source_reference: {
          repository_id: id,
          file_path: filePath,
          start_line: 8,
          end_line: 9,
          revision: target.revision ?? 'main',
          symbol_name: null,
        },
        evidence: 'def slice_page(items: list, cache: list = []):',
        suggested_fix: 'def slice_page(items: list, cache: list | None = None):',
        confidence: 'high',
        is_uncertain: false,
        source_type: 'STATIC',
        rule_id: 'AST004',
      },
    ];

    const severityRank: Record<string, number> = {
      CRITICAL: 5,
      HIGH: 4,
      MEDIUM: 3,
      LOW: 2,
      INFO: 1,
    };
    const minThreshold = severityRank[body?.min_severity ?? 'LOW'] ?? 2;
    const filteredFindings = allFindings.filter(
      (f) => (severityRank[f.severity] ?? 0) >= minThreshold
    );

    const staticCount = filteredFindings.filter((f) => f.source_type === 'STATIC').length;
    const aiCount = filteredFindings.filter(
      (f) => f.source_type === 'AI' || f.source_type === 'COMBINED'
    ).length;

    return HttpResponse.json({
      run_id: 'mock-bug-run-' + Date.now(),
      repository_id: id,
      status: 'COMPLETED',
      target,
      revision: target.revision ?? 'main',
      findings: filteredFindings,
      total_findings: filteredFindings.length,
      static_findings_count: staticCount,
      ai_findings_count: aiCount,
      missing_context: [
        'Runtime test suite coverage metrics outside the active file were not evaluated.',
      ],
      created_at: new Date().toISOString(),
    });
  }),

  // -------------------------------------------------------------------------
  // Feature 3: Framework-Aware Test Generation (Week 2 Day 4)
  //
  // POST /api/v1/repositories/:id/generate-tests
  //
  // Matches real backend contract in backend/app/schemas/analysis.py
  // -------------------------------------------------------------------------
  http.post(`${BASE}/repositories/:id/generate-tests`, async ({ params, request }) => {
    const { id } = params as { id: string };
    let body: any = null;
    try {
      body = (await request.json()) as any;
    } catch {
      // Malformed body
    }

    const target = body?.target || {
      type: 'file',
      path: body?.path || 'backend/app/services/auth.py',
    };

    const filePath = target.path || 'backend/app/services/auth.py';
    const symbol = target.symbol || null;

    // Error simulation 1: Service unavailable (503)
    if (filePath.includes('503') || filePath.includes('unavailable') || filePath.includes('timeout')) {
      return HttpResponse.json(
        {
          error: {
            code: 'SERVICE_UNAVAILABLE',
            message: 'Test generation is not available because `test_generation_service` is not configured.',
            retryable: true,
          },
        },
        { status: 503 }
      );
    }

    // Error simulation 2: Analysis failed (500)
    if (filePath.includes('500') || filePath.includes('fail')) {
      return HttpResponse.json(
        {
          error: {
            code: 'ANALYSIS_FAILED',
            message: 'Test generation failed due to an unrecoverable internal error.',
            retryable: true,
          },
        },
        { status: 500 }
      );
    }

    // Determine target framework
    const isTsOrJs =
      filePath.endsWith('.ts') ||
      filePath.endsWith('.tsx') ||
      filePath.endsWith('.js') ||
      filePath.endsWith('.jsx');

    let detectedFramework: 'pytest' | 'unittest' | 'jest' = isTsOrJs ? 'jest' : 'pytest';
    if (body?.framework && ['pytest', 'unittest', 'jest'].includes(body.framework)) {
      detectedFramework = body.framework;
    }

    // Determine proposed test path
    const fileStem = filePath.split('/').pop()?.replace(/\.[^/.]+$/, '') || 'component';
    let proposedTestPath = '';
    if (filePath.includes('exists') || filePath.includes('collision')) {
      // Return a path that intentionally exists in standard repo file lists
      proposedTestPath = 'backend/tests/test_analysis_api.py';
    } else if (detectedFramework === 'jest') {
      proposedTestPath = `frontend/src/components/__tests__/${fileStem}.test.tsx`;
    } else if (detectedFramework === 'unittest') {
      proposedTestPath = `backend/tests/test_${fileStem}_unit.py`;
    } else {
      proposedTestPath = `backend/tests/services/test_${fileStem}.py`;
    }

    // Syntax validation status simulation
    const isSyntaxInvalid = filePath.includes('syntax-error') || filePath.includes('invalid');
    const syntaxValid = !isSyntaxInvalid;
    const validationErrors = isSyntaxInvalid
      ? [
          'SyntaxError: unexpected EOF while parsing (line 28)',
          'StructuralError: Missing fixture dependency in test module scope',
        ]
      : [];

    // Empty content edge case simulation
    const isEmptyContent = filePath.includes('empty-test');

    // Generate complete code content according to framework
    let testContent = '';
    if (isEmptyContent) {
      testContent = '';
    } else if (detectedFramework === 'jest') {
      testContent = `import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ${symbol || fileStem} } from '../${fileStem}';

describe('${symbol || fileStem}', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Normal Behavior', () => {
    it('renders default state without crashing', () => {
      render(<${symbol || fileStem} />);
      expect(document.body).toBeInTheDocument();
    });

    it('handles standard user interaction correctly', async () => {
      const handleAction = vi.fn();
      render(<${symbol || fileStem} onAction={handleAction} />);
      const button = screen.queryByRole('button');
      if (button) {
        fireEvent.click(button);
        expect(handleAction).toHaveBeenCalledTimes(1);
      }
    });
  });

  describe('Edge Cases', () => {
    it('handles empty or null props gracefully', () => {
      const { container } = render(<${symbol || fileStem} items={[]} data={null} />);
      expect(container).toBeDefined();
    });

    it('renders correctly with long boundary text strings', () => {
      const longText = 'A'.repeat(500);
      render(<${symbol || fileStem} title={longText} />);
      expect(screen.getByText(longText)).toBeInTheDocument();
    });
  });

  describe('Failure Paths', () => {
    it('displays error fallback UI when asynchronous operation rejects', async () => {
      const mockFailingApi = vi.fn().mockRejectedValue(new Error('Network connection timeout'));
      render(<${symbol || fileStem} fetcher={mockFailingApi} />);
      const errorIndicator = await screen.findByText(/error|failed|timeout/i);
      expect(errorIndicator).toBeInTheDocument();
    });
  });
});
`;
    } else if (detectedFramework === 'unittest') {
      testContent = `"""Unit tests for ${filePath} using Python standard unittest."""

import unittest
from unittest.mock import MagicMock, patch

try:
    from app.services.${fileStem} import ${symbol || fileStem}
except ImportError:
    # Fallback import structure for test discovery
    ${symbol || fileStem} = MagicMock()


class Test${symbol || fileStem.charAt(0).toUpperCase() + fileStem.slice(1)}(unittest.TestCase):
    """Test suite covering normal, edge-case, and failure behavior."""

    def setUp(self):
        """Set up test environment before each test method."""
        self.mock_db = MagicMock()
        self.sample_payload = {
            "id": "test-item-001",
            "name": "Standard Test Item",
            "status": "ACTIVE",
        }

    def test_normal_execution_success(self):
        """Verify successful operation with valid inputs."""
        result = ${symbol || fileStem}(self.sample_payload, db=self.mock_db)
        self.assertIsNotNone(result)

    def test_edge_case_empty_collection(self):
        """Verify handling when collection or list parameter is empty."""
        empty_payload = {"id": "", "name": "", "items": []}
        result = ${symbol || fileStem}(empty_payload, db=self.mock_db)
        self.assertTrue(result is not None or result == {})

    def test_edge_case_boundary_values(self):
        """Verify handling of extreme numeric boundary values."""
        boundary_payload = {"count": 0, "limit": 100000}
        result = ${symbol || fileStem}(boundary_payload, db=self.mock_db)
        self.assertIsNotNone(result)

    def test_failure_path_invalid_type_raises_value_error(self):
        """Verify passing an invalid type raises ValueError."""
        with self.assertRaises((ValueError, TypeError)):
            ${symbol || fileStem}(None, db=self.mock_db)

    def test_failure_path_database_connection_error(self):
        """Verify database exception is caught or propagated appropriately."""
        self.mock_db.query.side_effect = ConnectionError("Database unreachable")
        with self.assertRaises(ConnectionError):
            ${symbol || fileStem}(self.sample_payload, db=self.mock_db)


if __name__ == '__main__':
    unittest.main()
`;
    } else {
      // Default: pytest
      testContent = `"""Framework-aware test suite for ${filePath} using pytest."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

try:
    from app.services.${fileStem} import ${symbol || fileStem}
except ImportError:
    # Fallback stub for test runners outside the active virtual environment
    ${symbol || fileStem} = MagicMock()


@pytest.fixture
def mock_db_session():
    """Provides a mocked database session with query capabilities."""
    session = MagicMock()
    session.add = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    return session


@pytest.fixture
def valid_context_payload():
    """Provides standard valid test payload."""
    return {
        "repository_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
        "file_path": "${filePath}",
        "max_tokens": 4096,
    }


# ---------------------------------------------------------------------------
# 1. Normal Scenarios
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_${fileStem}_successful_execution(mock_db_session, valid_context_payload):
    """Verify normal operation with valid parameters returns expected outcome."""
    result = ${symbol || fileStem}(valid_context_payload, db=mock_db_session)
    assert result is not None
    assert getattr(result, "status", "SUCCESS") != "FAILED"


def test_${fileStem}_preserves_deterministic_invariants(valid_context_payload):
    """Verify invariant structure is maintained across multiple invocations."""
    res1 = ${symbol || fileStem}(valid_context_payload)
    res2 = ${symbol || fileStem}(valid_context_payload)
    assert type(res1) == type(res2)


# ---------------------------------------------------------------------------
# 2. Edge Case Scenarios
# ---------------------------------------------------------------------------

def test_${fileStem}_handles_empty_sequences():
    """Verify behavior when empty collections or whitespace strings are passed."""
    empty_payload = {"file_path": "", "tokens": []}
    result = ${symbol || fileStem}(empty_payload)
    assert result is not None


def test_${fileStem}_unicode_and_special_characters():
    """Verify handling of special characters, quotes, and international characters."""
    special_payload = {"query": "test_search\\n\\t\\u2705 'quoted' \\"double\\""}
    result = ${symbol || fileStem}(special_payload)
    assert result is not None


# ---------------------------------------------------------------------------
# 3. Failure Path Scenarios
# ---------------------------------------------------------------------------

def test_${fileStem}_raises_on_unhandled_type():
    """Verify passing None or malformed target raises expected exception."""
    with pytest.raises((ValueError, TypeError, KeyError)):
        ${symbol || fileStem}(None)


@pytest.mark.asyncio
async def test_${fileStem}_upstream_service_timeout(mock_db_session):
    """Verify that network or DB timeout fails gracefully with clear error."""
    mock_db_session.execute.side_effect = TimeoutError("Connection to backend database timed out.")
    with pytest.raises((TimeoutError, RuntimeError, Exception)):
        ${symbol || fileStem}({"target": "invalid"}, db=mock_db_session)
`;
    }

    const coveredScenarios = [
      {
        name: `test_${fileStem}_successful_execution`,
        category: 'normal' as const,
        description: `Verifies that ${symbol || fileStem} executes as expected with valid parameters.`,
      },
      {
        name: `test_${fileStem}_preserves_deterministic_invariants`,
        category: 'normal' as const,
        description: 'Verifies consistent output types and schema invariants across invocations.',
      },
      {
        name: `test_${fileStem}_handles_empty_sequences`,
        category: 'edge_case' as const,
        description: 'Verifies graceful fallback when given empty inputs, zero lengths, or missing keys.',
      },
      {
        name: `test_${fileStem}_unicode_and_special_characters`,
        category: 'edge_case' as const,
        description: 'Verifies correct handling of multiline strings, escape sequences, and unicode.',
      },
      {
        name: `test_${fileStem}_raises_on_unhandled_type`,
        category: 'failure_path' as const,
        description: 'Verifies that invalid or null inputs raise appropriate validation exceptions.',
      },
      {
        name: `test_${fileStem}_upstream_service_timeout`,
        category: 'failure_path' as const,
        description: 'Verifies timeout and connection failures trigger controlled error responses.',
      },
    ];

    const assumptionsAndWarnings = [
      `Detected runner '${detectedFramework}' matching repository conventions.`,
      `Proposed test file '${proposedTestPath}' derived from convention detector.`,
      'Assumes shared test fixtures and environment configuration are accessible in root test directory.',
    ];

    if (filePath.includes('exists') || filePath.includes('collision')) {
      assumptionsAndWarnings.push(
        `Warning: Target file '${proposedTestPath}' already exists in this repository.`
      );
    }

    return HttpResponse.json({
      run_id: 'mock-gen-test-' + Date.now(),
      repository_id: id,
      status: 'COMPLETED',
      target,
      revision: target.revision ?? 'main',
      result: {
        detected_framework: detectedFramework,
        proposed_test_path: proposedTestPath,
        test_content: testContent,
        covered_scenarios: coveredScenarios,
        assumptions_and_warnings: assumptionsAndWarnings,
        syntax_valid: syntaxValid,
        validation_errors: validationErrors,
        sources: [
          {
            repository_id: id,
            file_path: filePath,
            start_line: target.start_line ?? 1,
            end_line: target.end_line ?? 50,
            revision: target.revision ?? 'main',
            symbol_name: symbol,
          },
        ],
      },
      created_at: new Date().toISOString(),
    });
  }),

  // -------------------------------------------------------------------------
  // Feature 4: Standalone AI Code Review (Week 2 Day 5)
  //
  // POST /api/v1/repositories/:id/review
  //
  // Matches real backend contract in backend/app/schemas/analysis.py
  // -------------------------------------------------------------------------
  http.post(`${BASE}/repositories/:id/review`, async ({ params, request }) => {
    const { id } = params as { id: string };
    let body: any = null;
    try {
      body = (await request.json()) as any;
    } catch {
      // Malformed body
    }

    const target = body?.target || {
      type: 'file',
      path: body?.path || 'backend/app/services/auth.py',
    };

    const targetType = target.type || 'file';
    const filePath = target.path || 'backend/app/services/auth.py';
    const commitSha = target.commit_sha || '';
    const prNumber = target.pr_number;
    const diffText = target.diff || '';

    // Validation checks matching backend _validate_review_target
    if (targetType === 'file' && (!target.path || !target.path.trim())) {
      return HttpResponse.json(
        {
          error: {
            code: 'VALIDATION_ERROR',
            message: "target.path is required when review target.type is 'file'.",
            retryable: false,
          },
        },
        { status: 400 }
      );
    }
    if (targetType === 'commit' && (!commitSha || !/^[0-9a-fA-F]{7,64}$/.test(commitSha.trim()))) {
      return HttpResponse.json(
        {
          error: {
            code: 'VALIDATION_ERROR',
            message: "target.commit_sha must be a valid 7-to-64 character hexadecimal SHA when type='commit'.",
            retryable: false,
          },
        },
        { status: 400 }
      );
    }
    if (targetType === 'pr' && (prNumber === undefined || prNumber === null || typeof prNumber !== 'number' || prNumber < 1)) {
      return HttpResponse.json(
        {
          error: {
            code: 'VALIDATION_ERROR',
            message: "target.pr_number must be a valid positive integer when review target.type is 'pr'.",
            retryable: false,
          },
        },
        { status: 400 }
      );
    }
    if (targetType === 'diff' && (!diffText || !diffText.trim())) {
      return HttpResponse.json(
        {
          error: {
            code: 'VALIDATION_ERROR',
            message: "target.diff must be a non-empty unified diff when type='diff'.",
            retryable: false,
          },
        },
        { status: 400 }
      );
    }

    // Error simulation 1: Service unavailable (503)
    const combinedInput = `${filePath} ${commitSha} ${diffText}`;
    if (combinedInput.includes('503') || combinedInput.includes('unavailable') || combinedInput.includes('timeout')) {
      return HttpResponse.json(
        {
          error: {
            code: 'SERVICE_UNAVAILABLE',
            message: 'AI code review is not available because `code_review_service` is not configured or timed out.',
            retryable: true,
          },
        },
        { status: 503 }
      );
    }

    // Error simulation 2: Analysis failed (500)
    if (combinedInput.includes('500') || combinedInput.includes('fail') || prNumber === 999) {
      return HttpResponse.json(
        {
          error: {
            code: 'ANALYSIS_FAILED',
            message: 'Code review execution failed: Upstream model reasoning returned an unrecoverable failure.',
            retryable: true,
          },
        },
        { status: 500 }
      );
    }

    // Scenario 2: Clean review with 0 findings and risk_level NONE
    const isCleanReview =
      combinedInput.includes('clean') ||
      commitSha === '0000000' ||
      prNumber === 100 ||
      filePath.includes('clean');

    if (isCleanReview) {
      const runId = 'mock-review-run-' + Date.now();
      const responsePayload = {
        run_id: runId,
        repository_id: id,
        status: 'COMPLETED' as const,
        target,
        report: {
          summary: 'Clean code review. All evaluated changes satisfy platform reliability, security, and correctness guidelines with zero defects detected.',
          risk_level: 'NONE' as const,
          findings: [],
          total_findings: 0,
          category_counts: {
            correctness: 0,
            security: 0,
            performance: 0,
            reliability: 0,
            maintainability: 0,
          },
          missing_context: [],
        },
        created_at: new Date().toISOString(),
      };

      // Record in mock history
      mockAnalysisRuns.unshift({
        id: runId,
        repository_id: id,
        user_id: 'mock-user-id',
        feature_type: 'review',
        status: 'COMPLETED',
        target_path: target.path || target.commit_sha || (target.pr_number ? `PR #${target.pr_number}` : 'Custom Diff'),
        target_symbol: null,
        start_line: null,
        end_line: null,
        source_revision: target.head_revision || target.commit_sha || 'main',
        findings_count: 0,
        result_payload: responsePayload,
        test_output: null,
        findings: [],
        error_message: null,
        created_at: responsePayload.created_at,
        completed_at: responsePayload.created_at,
      });

      return HttpResponse.json(responsePayload);
    }

    // Scenario 1, 3, 4, 5: Comprehensive review with findings across all 5 categories
    const primaryFile = targetType === 'file' ? filePath : 'backend/app/services/auth.py';

    const findings = [
      {
        id: 'rev-find-1',
        category: 'security',
        severity: 'CRITICAL',
        title: 'Hardcoded JWT signing secret fallback vulnerability',
        description: 'The secret key defaults to a predictable static string in production when environment variables are omitted.',
        source_reference: {
          repository_id: id,
          file_path: primaryFile,
          start_line: 14,
          end_line: 18,
          revision: target.head_revision ?? 'main',
          symbol_name: 'get_jwt_secret',
        },
        evidence: 'SECRET_KEY = os.getenv("JWT_SECRET", "super-secret-default-key-12345")',
        suggested_fix: 'SECRET_KEY = os.environ["JWT_SECRET"]  # Fail-closed in production if unconfigured',
        confidence: 'high',
        is_uncertain: false,
        is_new_in_change: true,
        source_type: 'COMBINED',
        rule_id: 'SEC-JWT-001',
      },
      {
        id: 'rev-find-2',
        category: 'correctness',
        severity: 'HIGH',
        title: 'Potential off-by-one boundary truncation in token expiration check',
        description: 'Using strict inequality (<) instead of (<=) allows tokens precisely matching expiration second to pass validation.',
        source_reference: {
          repository_id: id,
          file_path: primaryFile,
          start_line: 32,
          end_line: 36,
          revision: target.head_revision ?? 'main',
          symbol_name: 'is_token_expired',
        },
        evidence: 'if current_timestamp < exp_timestamp:\n    return True',
        suggested_fix: 'if current_timestamp <= exp_timestamp:\n    return True',
        confidence: 'high',
        is_uncertain: false,
        is_new_in_change: true,
        source_type: 'AI',
        rule_id: null,
      },
      {
        id: 'rev-find-3',
        category: 'reliability',
        severity: 'HIGH',
        title: 'Uncaught connection error during redis token revocation check',
        description: 'Redis client call is unhandled and can raise redis.ConnectionError, terminating caller request cycle with 500.',
        source_reference: {
          repository_id: id,
          file_path: primaryFile,
          start_line: 52,
          end_line: 58,
          revision: target.head_revision ?? 'main',
          symbol_name: 'check_revocation_list',
        },
        evidence: 'is_blacklisted = await redis_client.get(f"revoked:{token_jti}")',
        suggested_fix: 'try:\n    is_blacklisted = await redis_client.get(f"revoked:{token_jti}")\nexcept RedisError as exc:\n    logger.error("revocation_check_failed", extra={"err": str(exc)})\n    raise ServiceUnavailableError("Revocation backend offline")',
        confidence: 'medium',
        is_uncertain: false,
        is_new_in_change: true,
        source_type: 'STATIC',
        rule_id: 'REL-REDIS-002',
      },
      {
        id: 'rev-find-4',
        category: 'performance',
        severity: 'MEDIUM',
        title: 'N+1 synchronous database query loop inside user permission resolution',
        description: 'Iterating over repository roles and querying permissions individually introduces unnecessary latency.',
        source_reference: {
          repository_id: id,
          file_path: primaryFile,
          start_line: 78,
          end_line: 85,
          revision: target.head_revision ?? 'main',
          symbol_name: 'resolve_user_permissions',
        },
        evidence: 'for role in user.roles:\n    perms = db.query(Permission).filter(Permission.role_id == role.id).all()',
        suggested_fix: 'role_ids = [r.id for r in user.roles]\nperms = db.query(Permission).filter(Permission.role_id.in_(role_ids)).all()',
        confidence: 'high',
        is_uncertain: false,
        is_new_in_change: true,
        source_type: 'AI',
        rule_id: null,
      },
      {
        id: 'rev-find-5',
        category: 'maintainability',
        severity: 'LOW',
        title: 'Global scope configuration drift without explicit module documentation',
        description: 'Module imports dynamic environment settings without schema type annotations or documentation on supported key overrides.',
        source_reference: {
          repository_id: id,
          file_path: primaryFile,
          start_line: null,
          end_line: null,
          revision: target.head_revision ?? 'main',
          symbol_name: null,
        },
        evidence: 'config = load_dynamic_settings()',
        suggested_fix: 'from app.core.config import Settings\nconfig: Settings = get_settings()',
        confidence: 'low',
        is_uncertain: true,
        is_new_in_change: false,
        source_type: 'AI',
        rule_id: null,
      },
    ];

    const runId = 'mock-review-run-' + Date.now();
    const responsePayload = {
      run_id: runId,
      repository_id: id,
      status: 'COMPLETED' as const,
      target,
      report: {
        summary: 'Review identified 5 findings across Security, Correctness, Reliability, Performance, and Maintainability dimensions. 1 critical vulnerability requires immediate remediation prior to merging.',
        risk_level: 'CRITICAL' as const,
        findings,
        total_findings: findings.length,
        category_counts: {
          security: 1,
          correctness: 1,
          reliability: 1,
          performance: 1,
          maintainability: 1,
        },
        missing_context: [
          'Downstream caller graph outside the target package was truncated due to context budget limits.',
        ],
      },
      created_at: new Date().toISOString(),
    };

    // Record in mock history
    mockAnalysisRuns.unshift({
      id: runId,
      repository_id: id,
      user_id: 'mock-user-id',
      feature_type: 'review',
      status: 'COMPLETED',
      target_path: target.path || target.commit_sha || (target.pr_number ? `PR #${target.pr_number}` : 'Custom Diff'),
      target_symbol: null,
      start_line: 14,
      end_line: 85,
      source_revision: target.head_revision || target.commit_sha || 'main',
      findings_count: findings.length,
      result_payload: responsePayload,
      test_output: null,
      findings,
      error_message: null,
      created_at: responsePayload.created_at,
      completed_at: responsePayload.created_at,
    });

    return HttpResponse.json(responsePayload);
  }),

  // -------------------------------------------------------------------------
  // Feature 5: Analysis Run History & Retrieval (Week 2 Day 3–5 Contract)
  //
  // GET /api/v1/repositories/:id/analysis-runs
  // GET /api/v1/analysis-runs/:runId
  // -------------------------------------------------------------------------
  http.get(`${BASE}/repositories/:id/analysis-runs`, ({ params, request }) => {
    const { id } = params as { id: string };
    const url = new URL(request.url);
    const featureType = url.searchParams.get('feature_type');
    const status = url.searchParams.get('status');
    const page = parseInt(url.searchParams.get('page') || '1', 10);
    const pageSize = parseInt(url.searchParams.get('page_size') || '10', 10);

    const matching = mockAnalysisRuns.filter((r) => {
      if (r.repository_id !== id && id !== '11111111-1111-1111-1111-111111111111') return true;
      if (featureType && r.feature_type !== featureType) return false;
      if (status && r.status !== status) return false;
      return true;
    });

    const total = matching.length;
    const offset = (page - 1) * pageSize;
    const items = matching.slice(offset, offset + pageSize).map((r) => ({
      id: r.id,
      repository_id: r.repository_id,
      feature_type: r.feature_type,
      status: r.status,
      target_path: r.target_path,
      target_symbol: r.target_symbol,
      start_line: r.start_line,
      end_line: r.end_line,
      source_revision: r.source_revision,
      findings_count: r.findings_count,
      error_message: r.error_message,
      created_at: r.created_at,
      completed_at: r.completed_at,
    }));

    return HttpResponse.json({
      page,
      page_size: pageSize,
      total,
      items,
    });
  }),

  http.get(`${BASE}/analysis-runs/:runId`, ({ params }) => {
    const { runId } = params as { runId: string };
    const run = mockAnalysisRuns.find((r) => r.id === runId);
    if (!run) {
      return HttpResponse.json(
        {
          error: {
            code: 'NOT_FOUND',
            message: `Analysis run ${runId} not found.`,
            retryable: false,
          },
        },
        { status: 404 }
      );
    }

    return HttpResponse.json(run);
  }),
];

const mockAnalysisRuns: Array<{
  id: string;
  repository_id: string;
  user_id: string | null;
  feature_type: string;
  status: string;
  target_path: string | null;
  target_symbol: string | null;
  start_line: number | null;
  end_line: number | null;
  source_revision: string | null;
  findings_count: number;
  result_payload: any;
  test_output: string | null;
  findings: any[];
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}> = [
  {
    id: 'mock-hist-review-01',
    repository_id: '11111111-1111-1111-1111-111111111111',
    user_id: 'mock-user-id',
    feature_type: 'review',
    status: 'COMPLETED',
    target_path: 'backend/app/services/auth.py',
    target_symbol: null,
    start_line: 14,
    end_line: 18,
    source_revision: 'aadeed7',
    findings_count: 2,
    result_payload: {
      target: {
        type: 'file',
        path: 'backend/app/services/auth.py',
        head_revision: 'aadeed7',
      },
      report: {
        summary: 'Historical code review for auth module. 2 findings identified (1 Security, 1 Correctness).',
        risk_level: 'HIGH',
        findings: [
          {
            id: 'hist-find-1',
            category: 'security',
            severity: 'HIGH',
            title: 'Hardcoded secret token in auth config',
            description: 'Fallback secret key defaults to static string in development configuration.',
            source_reference: {
              repository_id: '11111111-1111-1111-1111-111111111111',
              file_path: 'backend/app/services/auth.py',
              start_line: 14,
              end_line: 18,
              revision: 'aadeed7',
              symbol_name: 'get_jwt_secret',
            },
            evidence: 'SECRET_KEY = os.getenv("JWT_SECRET", "super-secret-default-key-12345")',
            suggested_fix: 'SECRET_KEY = os.environ["JWT_SECRET"]',
            confidence: 'high',
            is_uncertain: false,
            is_new_in_change: true,
            source_type: 'STATIC',
            rule_id: 'SEC-JWT-001',
          },
          {
            id: 'hist-find-2',
            category: 'correctness',
            severity: 'MEDIUM',
            title: 'Strict inequality allows token expiration boundary bypass',
            description: 'Comparison operator allows token on boundary second to remain valid.',
            source_reference: {
              repository_id: '11111111-1111-1111-1111-111111111111',
              file_path: 'backend/app/services/auth.py',
              start_line: 32,
              end_line: 36,
              revision: 'aadeed7',
              symbol_name: 'is_token_expired',
            },
            evidence: 'if current_timestamp < exp_timestamp:\n    return True',
            suggested_fix: 'if current_timestamp <= exp_timestamp:\n    return True',
            confidence: 'high',
            is_uncertain: false,
            is_new_in_change: true,
            source_type: 'AI',
            rule_id: null,
          },
        ],
        total_findings: 2,
        category_counts: {
          security: 1,
          correctness: 1,
        },
        missing_context: [],
      },
    },
    test_output: null,
    findings: [
      {
        id: 'hist-find-1',
        category: 'security',
        severity: 'HIGH',
        title: 'Hardcoded secret token in auth config',
        description: 'Fallback secret key defaults to static string in development configuration.',
        source_reference: {
          repository_id: '11111111-1111-1111-1111-111111111111',
          file_path: 'backend/app/services/auth.py',
          start_line: 14,
          end_line: 18,
          revision: 'aadeed7',
          symbol_name: 'get_jwt_secret',
        },
        evidence: 'SECRET_KEY = os.getenv("JWT_SECRET", "super-secret-default-key-12345")',
        suggested_fix: 'SECRET_KEY = os.environ["JWT_SECRET"]',
        confidence: 'high',
        is_uncertain: false,
        is_new_in_change: true,
        source_type: 'STATIC',
        rule_id: 'SEC-JWT-001',
      },
      {
        id: 'hist-find-2',
        category: 'correctness',
        severity: 'MEDIUM',
        title: 'Strict inequality allows token expiration boundary bypass',
        description: 'Comparison operator allows token on boundary second to remain valid.',
        source_reference: {
          repository_id: '11111111-1111-1111-1111-111111111111',
          file_path: 'backend/app/services/auth.py',
          start_line: 32,
          end_line: 36,
          revision: 'aadeed7',
          symbol_name: 'is_token_expired',
        },
        evidence: 'if current_timestamp < exp_timestamp:\n    return True',
        suggested_fix: 'if current_timestamp <= exp_timestamp:\n    return True',
        confidence: 'high',
        is_uncertain: false,
        is_new_in_change: true,
        source_type: 'AI',
        rule_id: null,
      },
    ],
    error_message: null,
    created_at: new Date(Date.now() - 3600000 * 2).toISOString(),
    completed_at: new Date(Date.now() - 3600000 * 2 + 5000).toISOString(),
  },
];
