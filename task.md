Frontend Deep Audit --- AI-Powered Software Development Platform
Audit scope: Week 1 + Week 2 only
Repository archive:
AI-Powered-Software-Development-Platform-main (1).zip
Frontend stack declared: React 19, TypeScript 6, Vite 8, React
Router 7, TanStack Query 5, Zustand 5, Axios, Tailwind CSS 4
Audit date: 2026-10-27
Audit type: Static source inspection + cross-check against backend
route/schema implementations and Docs/week1.md / Docs/week2.md
Execution status: Dependency installation timed out; a clean
TypeScript/Vite build and browser E2E run could not be completed in this
environment. Findings below distinguish directly evidenced defects from
risks that require runtime verification.
1. Executive summary
The frontend has a meaningful foundation: authenticated routes, a
central Axios client, repository discovery and management, an
indexed-code explorer, repository chat, a four-feature Week 2 analysis
panel, and a backend analysis service layer. The Week 2 screens are not
merely decorative: RepositoryDetail.tsx wires mutations for
explanation, bug detection, test generation and review to real API
service functions, and the backend router contains matching analysis
endpoints.

However, the frontend should not yet be treated as verified
production-ready. The biggest gaps are end-to-end verification,
incomplete analysis history UX, assumptions embedded in repository/file
loading, a fixed request timeout that is poorly suited to long AI
analysis, and a repository tree that only loads a bounded first page.
There are also UI-state and contract-maintenance issues that can create
confusing or misleading results.
Overall assessment
  Area                     Assessment              Evidence / qualification
  Frontend architecture    Good foundation, needs  Services, hooks, types and views
                           consolidation           are separated, but the large
                                                   repository detail and feature
                                                   view components carry too much
                                                   orchestration/UI state.

  Week 1 authentication    Partially verified by   Cookie-based auth and protected
                           source                  routes exist. Runtime OAuth,
                                                   cookie/CORS and error behavior
                                                   still need E2E verification.

  Repository               Contract mostly aligned Frontend endpoint paths and core
  discovery/connect                                response fields match
                                                   backend/app/api/v1/github.py
                                                   and repository schemas.

  Repository explorer      Functional foundation,  Explorer requests only page 1
                           incomplete for large    with 500 files and has no
                           repositories            visible pagination/loading-more
                                                   path in this flow.

  Repository chat          Real API integration,   services/chat.ts documents the
                           not streaming           real non-streaming endpoint; UI
                                                   must not imply token streaming.

  Week 2 explanation       Wired to real endpoint  UI mutation and service exist;
                                                   output grounding/line-reference
                                                   accuracy depend on backend and
                                                   need integration tests.

  Week 2 bug detection     Wired to real endpoint  UI sends static + AI flags and
                                                   consumes structured findings. No
                                                   dedicated frontend
                                                   history/reopen UX found.

  Week 2 test generation   Wired to real endpoint  Result schema and display exist.
                                                   Proposed-path collision check is
                                                   based only on the loaded file
                                                   list and can be wrong for larger
                                                   repositories.

  Week 2 code review       Most complete workflow  File/commit/PR/diff target UI
                                                   and a review history drawer
                                                   exist. Review history is the
                                                   only complete history workflow
                                                   found.

  Analysis history         Incomplete across four  History APIs exist for all
                           features                feature types, but only review
                                                   history is wired into a visible
                                                   history drawer.

  Automated frontend       Not established         package.json has no test
  validation                                       script and the archive contains
                                                   no frontend test/spec files.
                                                   Dependency installation timed
                                                   out, so build/lint results
                                                   remain unverified.

  Performance/resilience   Needs improvement       One global 30-second Axios
                                                   timeout, broad repository
                                                   invalidations, and large
                                                   monolithic views create
                                               latency/performance risks.
Bottom line: retain the existing frontend and fix the verified gaps.
Do not rewrite it from scratch. First establish a reproducible
build/test baseline, then fix repository completeness, analysis history,
request lifecycle and state correctness before polishing UI.
2. Scope and exclusions
This report audits only the frontend work needed for:
Week 1 --- Repository intelligence foundation
- GitHub OAuth/session handling
- Repository discovery, connect, sync and listing
- Repository files, symbols, dependencies and source preview
- Repository-aware chat and source citations
- Frontend API/error/realtime integration
Week 2 --- Developer intelligence
- Code explanation
- Bug detection
- Test generation
- Standalone AI code review for supported file/commit/PR/diff targets
- Findings, source references, loading/error states and analysis
  history
Explicitly out of scope
- Week 3 autonomous code editing and repair loops
- Automatic branch creation/pushing and draft PR creation
- Agent approval/task orchestration UI
- Deployment automation
The existence of a frontend control or a backend route is not, by
itself, proof of a working feature. This audit checks source wiring and
cross-file contracts; live behavior still needs a running stack and test
repositories.
3. Evidence reviewed
Frontend source areas
- frontend/package.json, vite.config.ts, tsconfig*.json
- frontend/src/App.tsx, main.tsx, index.css
- frontend/src/layouts/ProtectedRoute.tsx, AppLayout.tsx
- frontend/src/pages/Login.tsx, AuthCallback.tsx, Dashboard.tsx,
  Repositories.tsx, RepositoryDetail.tsx, RepositoryChat.tsx
- frontend/src/services/api.ts, auth.ts, repositories.ts,
  repositoryDiscovery.ts, chat.ts, analysis.ts
- frontend/src/hooks/*, frontend/src/stores/*,
  frontend/src/types/*
- frontend/src/components/explorer/*,
  frontend/src/components/shared/*
- frontend/src/realtime/*
Cross-checks against backend/docs
- backend/app/api/v1/router.py
- backend/app/api/v1/auth.py, github.py, repositories.py,
  chat.py, analysis.py, events.py
- backend/app/schemas/repository.py,
  backend/app/schemas/analysis.py
- Docs/week1.md, Docs/week2.md
Validation attempted
- Archive extracted and source inventory inspected.
- Frontend dependency install attempted with
  npm ci --ignore-scripts --no-audit --no-fund; it timed out.
- Therefore no successful npm run build, npm run lint, or
  browser-based workflow is claimed.
4. Route and API contract cross-check
The frontend apiClient defaults to /api/v1 and backend main.py
registers the versioned router under settings.api_v1_prefix. Relative
service paths are therefore expected.
  Frontend workflow Frontend service path                                  Backend implementation                 Static result
  Current user      GET /auth/me                                         backend/app/api/v1/auth.py           Path aligns; OAuth/cookie runtime not
                                                                                                                  tested.

  Logout            POST /auth/logout                                    backend/app/api/v1/auth.py           Path aligns.

  List connected    GET /repositories                                    backend/app/api/v1/repositories.py   Aligns; frontend slices client-side for
  repositories                                                                                                    pagination.

  Repository detail GET /repositories/{id}                               backend/app/api/v1/repositories.py   Aligns.

  Sync repository   POST /repositories/{id}/sync                         backend/app/api/v1/repositories.py   Aligns.

  List repository   GET /repositories/{id}/files?page=&page_size=        backend/app/api/v1/repositories.py   Aligns; backend permits up to 1000 items
  files                                                                                                           per page.

  File content      GET /repositories/{id}/files/{file_id}/content       backend/app/api/v1/repositories.py   Aligns.

  Repository        GET /repositories/{id}/dependencies                  backend/app/api/v1/repositories.py   Route exists; response/runtime not tested.
  dependencies                                                                                                    

  Discover GitHub   GET /github/repositories                             backend/app/api/v1/github.py         Aligns; response schema has
  repos                                                                                                           items,total,page,page_size,total_pages.

  Connect GitHub    POST /github/repositories/{github_repo_id}/connect   backend/app/api/v1/github.py         Aligns; backend returns repository_id and
  repo                                                                                                            job_id.

  Repository chat   POST /repositories/{id}/chat                         backend/app/api/v1/chat.py           Aligns; backend response is complete, not
                                                                                                                  token-streamed.

  Explain code      POST /repositories/{id}/explain                      backend/app/api/v1/analysis.py       Aligns.

  Detect bugs       POST /repositories/{id}/detect-bugs                  backend/app/api/v1/analysis.py       Aligns.

  Generate tests    POST /repositories/{id}/generate-tests               backend/app/api/v1/analysis.py       Aligns.

  Code review       POST /repositories/{id}/review                       backend/app/api/v1/analysis.py       Aligns.

  List analysis     GET /repositories/{id}/analysis-runs                 backend/app/api/v1/analysis.py       Service/type exist; only review history is
  history                                                                                                         visibly consumed.

  Analysis detail   GET /analysis-runs/{run_id}                          backend/app/api/v1/analysis.py       Service exists; visible reopen flow only
                                                                                                                  found for review.

  Analysis summary  GET /repositories/{id}/analysis-runs/summary         backend/app/api/v1/analysis.py       Service/type exist; no frontend use found.

  Repository SSE    GET /events through realtime client                  backend/app/api/v1/events.py         Wiring exists; reconnection and real
                                                                                                              payload behavior need runtime test.
Contract conclusion
The four primary Week 2 request routes and the GitHub repository
discovery/connect routes are present on both sides. The largest contract
concern is not an obvious path typo; it is lack of automated contract
tests to prevent future drift between TypeScript interfaces and
Pydantic response models.

Recommended: generate OpenAPI from the running backend and add a
contract-check step (or generated TS types) to CI. At minimum,
integration tests must assert each service request and response shape
against the real API.
5. Findings --- prioritized
Severity definitions: - P0: blocks safe release / core application
use. - P1: important feature correctness/completeness defect. -
P2: reliability, UX or maintainability issue that should be fixed
before calling the scope complete. - P3: lower-priority improvement.
F-01 --- No frontend automated test suite or test script
Severity: P1 --- verification gap
Evidence: frontend/package.json defines dev, build, lint,
and preview, but no test script. The archive contains no frontend
*.test.*, *.spec.*, or frontend __tests__ files.

Why it matters: The most important workflows involve route state,
asynchronous mutations, source highlighting, authentication redirects,
and API response parsing. Static types alone cannot verify these
behaviors. This makes regressions easy to introduce and prevents the
project from objectively proving "all features working accurately."

Required action: 1. Add Vitest + React Testing Library (or the
repository's chosen test framework) and a test/test:ci script. 2.
Unit-test normaliseError, repository status mapping, source-reference
matching and test-path status. 3. Mock API boundaries for component
tests, but also add real-backend integration/E2E tests so mocks are not
mistaken for end-to-end proof. 4. Add Playwright smoke flows for login
state, repository open, all four analysis features, failure states, and
review history. 5. Run build, lint, unit tests and E2E in CI.

Acceptance: CI fails on a broken build, failing unit test or
critical E2E regression. No feature is marked complete based only on a
rendered screen.
F-02 --- Repository Explorer only fetches the first 500 files
Severity: P1 --- incomplete repository coverage
Evidence: frontend/src/pages/RepositoryDetail.tsx:247-253 calls
useRepositoryFiles(id, 1, 500, ...).
backend/app/api/v1/repositories.py allows page_size up to 1000 and
returns pagination metadata. FileTree receives only filesData?.items
(RepositoryDetail.tsx:1023-1027).

Impact: For repositories with more than 500 indexed files, the UI
silently exposes only the first page. Users cannot browse the complete
repository through this tree. Citation navigation, file selection and
analysis-target selection can fail for files that are indexed but
outside the loaded page. The page itself acknowledges incomplete
deep-linked previews around RepositoryDetail.tsx:1075-1085, but does
not provide a load-more action there.

Related defect: RepositoryDetail.tsx:347-355 determines whether a
generated test path already exists by checking filesData.items.
Because that collection is only the first 500 files, a proposed path can
be incorrectly marked NEW when the file exists on a later page.

Required action: 1. Implement server-side file pagination or an
explicit "Load more" strategy in the explorer. 2. Prefer a dedicated
file-path lookup endpoint for citation navigation and proposed-test-path
collision checks; do not fetch every file just to validate one path. 3.
Treat an unsearched/unloaded path as UNKNOWN, not NEW or "not
found." 4. Keep the visible total count and loaded count explicit.

Acceptance: A test repository with more than 1000 files can navigate
to a file on a later page and correctly determine whether a proposed
test path exists.
F-03 --- Analysis history is only surfaced for Code Review
Severity: P1 --- Week 2 completeness gap
Evidence: frontend/src/services/analysis.ts provides
getAnalysisRuns, getBugScanHistory, getTestGenerationHistory,
getCodeReviewHistory, getAnalysisRun, and reopen helpers. Search
across frontend/src shows visible history drawer integration only in
frontend/src/components/explorer/CodeReviewView.tsx (including
ReviewHistoryDrawer around lines 1175 onward). No equivalent history
UI is wired for explanation, bug detection or test generation.
getAnalysisRunsSummary also has no consumer.

Cross-check: Docs/week2.md says analysis runs should be saved and
revisited and describes all four independent features. Backend routes
support listing and reopening runs.

Impact: Users can revisit review results but cannot discover/reopen
saved explanation, bug scan or test generation runs through the
frontend. A user can lose access to a result after changing file/feature
or refreshing the page, despite the backend persistence API being
available.

Required action: 1. Build a shared AnalysisHistory component for
all feature types. 2. Filter by feature, target path, status and
revision using the existing API. 3. Reopen each run and reconstruct the
correct result shape based on feature_type and result_payload. 4.
Handle old/missing payload fields safely and show a clear "result
unavailable" state instead of rendering partial/misleading output. 5.
Decide whether the summary endpoint powers a small history/quality
panel; if not needed for Week 2, remove unused client code or document
it as deferred.

Acceptance: Each of the four feature types can be listed and
reopened after a page refresh, with correct target, result and source
references.
F-04 --- Global 30-second timeout is unsuitable for all analysis requests
Severity: P1/P2 --- reliability risk
Evidence: frontend/src/services/api.ts:17-25 sets a single Axios
timeout: 30000 for every request. The same client is used for ordinary
metadata reads and potentially expensive AI workflows (explanation, bug
detection, test generation, code review, repository chat).

Impact: A valid but slow analysis may be aborted by the browser
client after 30 seconds. The backend may continue processing and persist
a run, leaving the user with a failure while history contains a
completed result. This is a risk inferred from the request lifecycle; it
must be confirmed with latency measurements.

Required action: 1. Keep short timeouts for metadata calls but use a
separate configurable timeout for long analysis calls, or change the API
to return a run ID and poll status. 2. If an analysis request is
cancelled/times out, show "request timed out; check history before
retrying" when appropriate to avoid duplicate expensive runs. 3. Use an
AbortController on navigation/unmount where cancellation is supported
and define whether cancellation cancels backend work or only the client
wait. 4. Instrument latency by endpoint and choose timeout values from
p95/p99 measurements.

Acceptance: A deliberately slow analysis is handled predictably and
does not produce confusing duplicate runs when the user retries.
F-05 --- Analysis result state is shared across four different features
Severity: P2 --- UI state correctness
Evidence: frontend/src/pages/RepositoryDetail.tsx:147-161 holds
one analysisStatus and one analysisError alongside four separate
result states. The action bar's feature switch
(RepositoryDetail.tsx:998-1015) updates this shared status based on
whether a prior result exists.

Impact: Feature switching and overlapping lifecycle transitions are
harder to reason about. A shared status can temporarily describe a
different feature than the currently visible result if mutations
complete late or feature state changes while a request is running.
Result objects are separate, but status/error are not. The current
pending guard reduces some overlap but does not make state ownership
explicit.

Required action: 1. Store a per-feature state object (status,
error, result, target, runId) or model the analysis workflow
with a reducer. 2. Associate each response with the target/revision that
initiated it. Ignore stale responses if the selected target changes
before completion, or explicitly keep the completed result tied to its
original target. 3. Reset only the appropriate feature state when the
user changes files. 4. Add race-condition tests for switching
files/features during a pending request.

Acceptance: A delayed response for file A cannot appear as the
result for file B, and the status shown always belongs to the active
feature/run.
F-06 --- Revision field is populated with the branch name, not a commit revision
Severity: P2 --- provenance accuracy risk
Evidence: frontend/src/pages/RepositoryDetail.tsx sends
revision: repo?.default_branch || 'main' in explanation, bug detection
and test generation requests (inside handleRunAnalysis).
AnalysisTarget.revision is documented in backend
backend/app/schemas/analysis.py as an optional source revision /
commit SHA, and history filtering calls the field source_revision.

Impact: A branch name is mutable and does not identify the exact
code analyzed. Historical results may be displayed as if they came from
a specific revision when they actually came from the default branch
label. Whether backend resolves the branch to a commit is not
established by this frontend code.

Required action: 1. Fetch and pass the resolved commit SHA from
repository sync metadata where available. 2. If the backend only accepts
branch refs, rename/document the field as a ref and separately return
the resolved commit SHA used for analysis. 3. Display the analyzed
revision in results/history.

Acceptance: Every saved run records a stable revision identifier or
explicitly states that the revision is unknown.
F-07 --- Code review history reconstruction uses permissive any casts and fallback payloads
Severity: P2 --- data integrity/maintainability
Evidence: frontend/src/components/explorer/CodeReviewView.tsx in
ReviewHistoryDrawer.handleReopen reads
(detail.result_payload as any)?.report and .target, then
reconstructs a response with defaults when fields are missing.

Impact: Schema drift can be hidden by fallback data. A historical
run with a malformed/missing payload may appear like a valid review,
potentially showing an invented summary or risk level rather than
telling the user the result is incomplete. Broad any also bypasses
compile-time protection at a high-risk API boundary.

Required action: 1. Define a typed discriminated result payload by
feature_type. 2. Validate history payloads at runtime (Zod or
equivalent) before reconstructing view models. 3. Preserve an explicit
"legacy/incomplete result" state instead of synthesizing fields that
look authoritative. 4. Add tests for null payload, unknown feature type,
malformed report, and empty findings.

Acceptance: Malformed historical data is safely reported and never
presented as a fully verified result.
F-08 --- Repository synchronization progress is intentionally approximate
Severity: P2 --- progress UX mismatch
Evidence: frontend/src/hooks/useRepositories.ts documents
syncProgressFromStatus: backend exposes
NOT_SYNCED | SYNCING | SYNCED | FAILED, and SYNCING is mapped to
CLONING because fine-grained stages are not exposed. Docs/week1.md
describes a Cloning → Scanning → Indexing → Ready flow.

Impact: The UI cannot accurately tell users whether a repository is
cloning, scanning or indexing. If the interface displays distinct
stages, they should not be implied to be observed backend states when
they are not.

Required action: 1. Either display a truthful indeterminate "Syncing
/ indexing" status or implement a real backend sync_stage/job-status
contract. 2. Use the same contract in dashboard, repository list and
detail views. 3. Do not animate stages forward based only on elapsed
time.

Acceptance: Every stage shown to the user is backed by real backend
state or is clearly labeled as an estimate.
F-09 --- SSE reconnection strategy is incomplete
Severity: P2 --- real-time freshness risk
Evidence: frontend/src/hooks/useRealtimeRepositories.ts contains a
TODO for exponential-backoff reconnection;
frontend/src/realtime/events.ts documents future event types.
Repository updates invalidate the broad repositoryKeys.all query
prefix.

Impact: If the SSE connection drops, the UI can stop receiving
updates until the connection is re-established by browser behavior or a
remount. Broad invalidation can refetch every repository list/detail
query, even when a single repository changed.

Required action: 1. Verify the EventSource reconnection behavior
and server heartbeat/retry settings. 2. Surface connection state and add
a bounded backoff strategy if the custom client bypasses native
reconnection. 3. Include repository IDs in event payloads and invalidate
the specific repository's detail/list query where possible. 4. Keep
periodic status polling as a deliberate fallback for long-running syncs.

Acceptance: Dropping the connection and restoring it does not leave
stale repository status indefinitely, and one update does not trigger
unnecessary refetch storms.
F-10 --- Error normalization loses HTTP status and request context
Severity: P2 --- supportability
Evidence: frontend/src/services/api.ts:62-97 maps errors to
{code,message,retryable} and discards status, endpoint, request ID and
structured validation details. The interceptor redirects any 401 to
/login except /login and /auth paths.

Impact: UI components cannot reliably distinguish validation errors,
rate limiting, service unavailability, timeouts and conflicts except
through message text. Redirecting on any 401 can also interrupt a
page-level action without preserving the user's return destination. This
is not necessarily a security flaw, but it reduces recovery quality.

Required action: 1. Extend the normalized error type with status,
optional details, and request_id if supplied by the backend. 2. Keep
messages safe for users and log diagnostic fields without secrets. 3.
Preserve the intended return route on authentication redirects. 4. Treat
cancellation separately from genuine network errors. 5. Use structured
error codes in UI rather than substring matching.

Acceptance: A 400 validation error, 429 rate limit, 503 provider
outage, 401 auth expiry and client timeout each produce an appropriate
recovery action.
F-11 --- Feature support/error classification depends on error-message text
Severity: P2 --- fragile UX
Evidence: frontend/src/components/explorer/AnalysisResultPanel.tsx
sets isUnsupportedTargetError by searching error.toLowerCase() for
phrases such as "static", "not a testable", "unsupported target" and
"unsupported test framework".

Impact: A backend wording change can alter UI behavior without
changing the error code. Generic errors may be misclassified as
unsupported targets, and localized/rewritten messages will break the
check.

Required action: Use normalized API error codes and feature-specific
validation details; retain text only as the display string.

Acceptance: Unit tests prove unsupported-language/framework,
invalid-path, provider-unavailable and generic-server errors route to
distinct UI states.
F-12 --- Large feature components make regressions and review expensive
Severity: P2 --- maintainability/performance risk
Evidence: RepositoryDetail.tsx is 1380 lines; CodeReviewView.tsx
1356 lines; TestGenerationView.tsx 751 lines; BugScannerView.tsx 700
lines; AnalysisResultPanel.tsx 563 lines. The repository detail page
owns file selection, analysis orchestration, review targets, result
states, source navigation, dependencies and modals.

Impact: It is difficult to isolate behavior, add unit tests, reason
about async races, and keep all four feature flows consistent. Large
views also make it more likely that shared status/target logic diverges
over time.

Required action: Refactor incrementally, not as a redesign: -
useRepositoryExplorerState for selected file/target/source
navigation. - useAnalysisRun(feature) or a typed analysis reducer for
request/result lifecycle. - Shared AnalysisHistory and
SourceReferenceLink components. - Separate review-target form, review
history drawer, findings list, filters and finding detail. - Keep API
calls in services/hooks rather than view components.

Acceptance: Refactor does not change API contracts and has
regression tests for the existing workflows.
F-13 --- Syntax highlighting is a lightweight regex tokenizer, not a parser
Severity: P3 --- display correctness
Evidence:
frontend/src/components/explorer/CodeViewer.tsx:21 onward explicitly
describes a lightweight tokenizer using regular expressions. It handles
some line comments and simple strings but does not implement full
language grammars (e.g. multiline comments, nested/template constructs,
language-specific syntax).

Impact: Some valid code may be colored incorrectly. This is a visual
issue, not a code-analysis engine defect, but the interface should not
imply compiler-grade syntax understanding.

Required action: Either label this as lightweight highlighting or
adopt a maintained syntax-highlighting library with language bundles and
size limits. Do not introduce raw HTML rendering for highlighting.

Acceptance: Representative Python, TS/JS, JSON and Markdown fixtures
render consistently without modifying source text.
F-14 --- Chat is request/response, not streaming
Severity: P2 if UI implies streaming; otherwise informational
Evidence: frontend/src/services/chat.ts explicitly says the
backend returns one complete RepositoryAnswer and that no
token-by-token streaming occurs. useRepositoryChat.ts uses a pending
assistant placeholder while the request is in flight.

Impact: This is a legitimate implementation choice for Week 1, but
the UI should communicate "Thinking..."/loading rather than animate
partial tokens or imply that output is streaming. Long response latency
compounds the global 30-second timeout issue.

Required action: Keep the current request/response contract
truthful. If streaming is later required, add a separate backend
streaming contract and test disconnect/cancel semantics rather than
simulating streaming on the client.

Acceptance: The loading state resolves exactly once on success,
failure and cancellation; no stale placeholder remains.
6. Week 1 feature-by-feature audit
6.1 Authentication and routing
Present: - App.tsx registers login, callback, dashboard,
repositories, repository detail and repository chat routes. - /app/*
routes are wrapped by ProtectedRoute. - useAuth calls
GET /auth/me; the auth store contains only user/session UI state. -
Axios uses withCredentials: true and does not expose/store the token
in JavaScript.

Risks / tests required: - Verify the backend cookie SameSite,
Secure, domain and CORS settings in the actual deployment topology. -
Test OAuth callback success, callback error, expired cookie, revoked
session, network outage and logout. - The root/catch-all route redirects
to /app/dashboard; verify the intended post-login return path is
preserved where required. - In React StrictMode, effects may be invoked
more than once in development; ensure session checks and SSE connection
setup tolerate this.

Status: Implemented by source; runtime/security configuration not
independently verified.
6.2 Repository discovery and connect
Present: - services/repositoryDiscovery.ts uses
GET /github/repositories and
POST /github/repositories/{githubRepoId}/connect. - These routes exist
in backend/app/api/v1/github.py. - The raw discovery adapter maps the
same key fields as the backend schema: github_repo_id, owner/name/full
name, branch, language and is_connected. - Connect response shape
{repository_id, job_id} matches backend ConnectRepositoryResponse.

Risks / tests required: - Verify empty GitHub installation state,
GitHub API failure, duplicate connect (409), and missing GitHub App
configuration (503). - Search debounce and pagination need UI tests to
confirm changing search resets page to 1 and does not show stale
results. - Verify connect mutation invalidates repository queries and
the UI polls the new repository until sync completes.

Status: API contract aligns by source; full GitHub lifecycle
unverified.
6.3 Repository listing and pagination
services/repositories.ts retrieves the full connected repository list
then slices locally. This matches the current backend
GET /repositories returning a plain list, so it is not a mismatch
today. It does not scale well for accounts with many repositories;
server-side pagination should be introduced only alongside a backend
contract change.

Status: Correct against current contract; scalability improvement
later.
6.4 File tree and code preview
Present: - File tree builds a nested path structure, supports
filtering and selection. - File content is loaded through a separate
endpoint using repository ID + file ID. - Code viewer renders code as
React text nodes; no dangerouslySetInnerHTML usage was found in the
inspected frontend source. - Query-string deep links can select
files/lines/symbols when the file exists in loaded results.

Issues: - First-500-files limitation (F-02). - Citation navigation
is limited to the loaded file list. - Regex tokenizer is not
grammar-accurate (F-13). - Test path collision check is based on
incomplete client data (F-02). - Verify behavior for empty files, very
large files, Unicode paths, deleted files, secret-redacted content, and
line ranges outside file bounds.

Status: Core implementation exists; large-repository completeness is
not acceptable yet.
6.5 Repository chat and RAG UX
Present: - services/chat.ts calls the backend chat endpoint. -
useRepositoryChat.ts builds history from completed turns and uses an
abort controller. - The UI includes a pending assistant placeholder and
error handling.

Risks / tests required: - Chat history is explicitly ephemeral in
the hook; refresh loses the conversation. This is acceptable only if the
Week 1 product contract says history is not persisted. - Ensure retrying
a failed question does not duplicate user messages or retain an
unanswered assistant bubble. - Verify source references navigate to the
correct repository/file/line and that missing source files do not
highlight unrelated code. - No token streaming is currently implemented;
UI copy must be truthful. - Verify the request size/history limit and
that only completed turns are sent.

Status: Real request/response integration is present; RAG answer
quality and runtime behavior need E2E tests.
7. Week 2 feature-by-feature audit
7.1 Code explanation
Frontend wiring: useExplainCode → explainCode →
POST /repositories/{id}/explain; RepositoryDetail.tsx sets the
target and displays ExplanationResultView through
AnalysisResultPanel.

Contract cross-check: Frontend request uses { target, options };
backend ExplainCodeRequest expects the same. Target includes
type/path/range/symbol/revision. Response type expects explanation,
status, run ID, repository ID and timestamps, consistent with backend
schema naming.

Tests required: - File, symbol and line-range targets. - Unknown
symbol, invalid line range, unsupported file, empty source and oversized
file. - Sources include valid repository-relative path and 1-indexed
line ranges. - Missing context is disclosed instead of hallucinated
dependencies. - A response arriving after the user changes selection
remains tied to the original target.

Status: API and view wiring present; grounding and source accuracy
unverified at runtime.
7.2 Bug detection
Frontend wiring: useDetectBugs → detectBugs →
POST /repositories/{id}/detect-bugs; request includes
include_static: true, include_ai: true, min_severity: 'LOW'.

Contract cross-check: Backend route and request schema exist;
frontend consumes findings, counts, missing context, status and run ID.

Tests required: - No findings is a successful completed scan, not an
error. - Static-only, AI-only and combined findings have correct source
type. - Duplicate findings are not shown twice; severity filtering is
consistent. - Each finding path/line points to the correct file and does
not exceed source bounds. - Provider unavailable and static scanner
failure produce clear, distinct states.

Gap: No visible bug-scan history/reopen view found even though
service helpers exist (F-03).

Status: Wired; accuracy/history completeness unverified.
7.3 Test generation
Frontend wiring: useGenerateTests → generateTests →
POST /repositories/{id}/generate-tests; framework override is sent
when selected. UI displays proposed path, test content, covered
scenarios, warnings and syntax-validation status.

Contract cross-check: TestGenerationRequest includes
target/options/framework. Frontend response schema mirrors backend
result fields including proposed_test_path, test_content,
syntax_valid, validation errors/warnings and sources.

Issues: - Proposed-path collision check can be wrong when existing
file is beyond the loaded first 500 files (F-02). - The feature should
clearly distinguish "generated and syntax-validated" from "executed
successfully." The frontend type has syntax_valid and optional
test_output; do not show a passing-test badge unless actual execution
was performed and reported. - Re-selecting a framework after a result
exists triggers a new generation run (handleFrameworkChange), which
may be surprising and can consume additional model quota; label this
action clearly or require an explicit regenerate click.

Tests required: Python pytest/unittest and JS Jest support,
unsupported language, framework detection fallback, syntax-invalid
output, validation warnings, collision path and copy/download behavior.

Gap: No visible test-generation history/reopen view found (F-03).

Status: Wired; output execution semantics and history UX need work.
7.4 AI code review
Frontend wiring: useReviewCode → reviewCode →
POST /repositories/{id}/review. ReviewTarget supports file,
commit, diff, pr. UI includes a target selector and a history
drawer.

Contract cross-check: Backend ReviewTarget supports the same
target kinds and validates required target fields. Backend review
orchestrator contains separate branches for file, diff, commit and PR
retrieval. The UI and backend therefore appear aligned at the contract
level.

Tests required: - File review with source path. - Commit SHA
validation and unavailable commit. - PR number, inaccessible PR, no
changed files and truncated/unavailable patch. - Unified diff parse
errors, unsafe paths in diff and oversized diff. - New-in-change
findings only reference changed lines where required. - History with
missing/legacy payload and findings without source location. - A failed
history request should not leave a stale list from a previous
repository.

Issues: - History reconstruction uses any and synthetic fallbacks
(F-07). - Ensure the history drawer clears runs when the repository
changes or the request fails, so old repository data is never shown as
belonging to the current repository. - Review result/history should
expose source revision and missing context prominently.

Status: Most complete Week 2 workflow by source; still needs E2E and
history hardening.
8. Cross-cutting architecture and optimization
8.1 API client
Good: Central Axios client, credentials enabled for cookie auth,
normalized errors, no bearer-token storage.

Change: Separate default timeout policy for short metadata calls and
long AI analysis calls; add request IDs and structured error metadata;
explicitly handle cancellation. Avoid automatically retrying
non-idempotent analysis POSTs unless backend idempotency keys are
supported.
8.2 Server state vs UI state
Good: TanStack Query handles repositories and available GitHub
repositories; Zustand holds app shell/auth UI state.

Change: Keep analysis history and result state in query/cache or a
dedicated feature state layer where appropriate. Do not duplicate
server-owned analysis history in ad hoc local component state. Use query
keys that include repository ID, feature and filters.
8.3 Re-rendering and bundle size
- Measure bundle size after a successful build; no bundle report was
  available because install/build could not run.
- Consider lazy-loading the large analysis views/routes with
  React.lazy after confirming loading boundaries.
- Keep expensive syntax tokenization and file-tree construction
  memoized; they are already partly memoized, but benchmark on
  500--1000-file repositories and large source files.
- Avoid setting up duplicate SSE connections under nested layouts or
  StrictMode; verify cleanup and connection count.
- Invalidate targeted queries when possible rather than every
  repository query.
8.4 Accessibility and interaction quality
Add checks for: - Keyboard navigation through file tree, feature tabs,
findings, modals and history drawer. - Visible focus states and
appropriate aria-expanded, aria-selected, dialog roles and live
regions. - Loading announcements and non-color-only status indicators. -
Mobile/narrow viewport usability. The shell uses fixed viewport height
and internal overflow; test that each pane scrolls independently and
controls are not clipped. - Copy buttons report success/failure;
clipboard errors are not silently ignored.
8.5 Data provenance and trust
- Display exact source revision where available.
- Never infer a source line or test execution result from missing
  data.
- Treat AI findings as recommendations with evidence/confidence, not
  definitive proof.
- Validate API response payloads at runtime for persisted history,
  because old rows may outlive frontend schema changes.
- Continue rendering repository code and diffs as text; do not use raw
  HTML insertion for syntax highlighting or markdown without
  sanitization.
9. Recommended implementation order
Phase A --- Baseline (must happen first)
1. Run npm ci in a network-enabled environment.
2. Run npm run build and npm run lint; record all failures and do
   not mix baseline failures with new changes.
3. Add a frontend test runner and a minimal CI job.
4. Capture current UI screenshots and a manual smoke-test checklist for
   regressions.
Phase B --- Correctness blockers
1. Fix file-list completeness and path-existence checks (F-02).
2. Implement history/reopen for explanation, bugs and test generation
   (F-03).
3. Introduce per-feature analysis lifecycle state and stale-response
   protection (F-05).
4. Replace the global analysis timeout with a documented long-running
   request strategy (F-04).
5. Make source revision semantics precise (F-06).
Phase C --- Reliability and supportability
1. Type and validate persisted review payloads (F-07).
2. Improve SSE reconnect and targeted invalidation (F-09).
3. Normalize structured errors and stop relying on message substring
   matching (F-10/F-11).
4. Add cancellation, duplicate-submit and retry tests.
Phase D --- Refactor and optimize
1. Extract analysis state/orchestration from RepositoryDetail.tsx.
2. Split CodeReviewView.tsx into target selector, history drawer,
   finding filters/list and detail view.
3. Profile tree rendering and code viewer on large fixtures.
4. Add accessibility/responsive checks and only then polish visuals.
10. Frontend acceptance checklist for Week 1 + Week 2
Build and quality gates
- [ ] npm ci succeeds from lockfile.
- [ ] npm run build succeeds with TypeScript checks.
- [ ] npm run lint succeeds or has explicitly documented baseline
  exceptions.
- [ ] Automated frontend tests run in CI.
- [ ] No unreviewed API contract drift between TS types and backend
  schemas.
Week 1
- [ ] OAuth callback and cookie session work in target deployment.
- [ ] 401, 403, 404, 409, 429, 500 and 503 errors have correct UX.
- [ ] Repository discovery search/pagination/connect works with empty
  and failed GitHub states.
- [ ] Sync state updates via SSE and/or polling and does not become
  stale indefinitely.
- [ ] File tree supports repositories larger than 500 files.
- [ ] Deep-linked file/source navigation does not select or highlight
  an unrelated file.
- [ ] Chat success/error/retry/cancel paths do not leave stale
  placeholders.
- [ ] Source citations match actual repository paths, lines and
  revision.
Week 2
- [ ] Explain file/symbol/range works and displays grounded sources.
- [ ] Bug scan returns structured findings or a valid empty result.
- [ ] Test generation shows framework, proposed path, validation
  status and warnings accurately.
- [ ] Test generation does not claim tests passed unless execution was
  performed.
- [ ] Review works for file, commit, PR and unified diff targets.
- [ ] Findings use correct severity, category, source references and
  uncertainty state.
- [ ] All four feature histories can be listed and reopened after
  refresh.
- [ ] Changing target during an in-flight request cannot misattribute
  results.
- [ ] Long-running analysis has clear timeout/poll/retry behavior.
Safety and UX
- [ ] No raw HTML injection for source code or diff content.
- [ ] Keyboard-only operation works for core flows.
- [ ] Loading, empty, failed, partial and completed states are
  visually distinct.
- [ ] Large repositories and narrow viewports are tested.
11. Final verdict
The frontend already contains the main screens and service wiring for
Week 1 repository intelligence and Week 2's four developer-intelligence
features. API path and schema checks show that the core analysis
endpoints and GitHub discovery/connect endpoints are present on both
sides.

It is not yet justified to call the frontend "all features working"
because the project has no frontend test suite, a clean build could not
be verified in this audit environment, the explorer is bounded to the
first 500 files, and history/reopen is not implemented consistently
across all four Week 2 features. Long-running AI request behavior and
async state correctness also need targeted testing.

Recommended decision: keep the current implementation; do not
rewrite. Complete Phase A first, then fix F-02 through F-07 in
priority order. Only after the build, API integration tests and Week
1/Week 2 acceptance checklist pass should the frontend be marked
complete.