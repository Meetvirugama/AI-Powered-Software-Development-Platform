# Professional frontend audit — SoftwearProject

Your target should be a professional AI coding workspace inspired by the workflow of Antigravity and Claude Code, but with its own identity, layout, visual language, and interactions.

I inspected the frontend source in `Archive.zip`, including `Docs/week1.md`, React routes, pages, API services, hooks, stores, styling, mocks, and the backend route definitions that the frontend depends on.

My conclusion: you have a useful React foundation, but the frontend is not yet a cohesive, production-quality AI developer workspace. The biggest problems are mismatched contracts, incomplete live integration, authentication error handling, missing features, and a design that still resembles a basic dashboard rather than a code-intelligence environment.

## 1. What Week 1 actually requires

According to `Docs/week1.md`, your frontend must support five screens and a complete user journey:

1\. Login

GitHub OAuth, callback handling, session verification, and clear error states.

2\. Dashboard

Connected repositories, language, last synchronization, status, and useful quick actions.

3\. Repository selector

Discover GitHub repositories, search, connect, and show synchronization progress.

4\. Repository explorer

Repository metadata, file tree, language/framework information, symbols, and dependencies.

5\. Repository chat

Repository-aware questions, response streaming, clickable source references, loading states, and retryable errors.

The fifth screen is especially important. This is not supposed to be a generic chatbot with a GitHub logo. It should feel like a developer working with an AI that understands the selected repository.

## 2. Confirmed frontend issues

Critical — repository discovery has stale integration assumptions

`frontend/src/services/repositoryDiscovery.ts` still says its endpoints do not exist and that they are backed by MSW mocks. However, the archived backend defines `GET /api/v1/github/repositories` and `POST /api/v1/github/repositories/{github_repo_id}/connect`.

Update the frontend contract based on the actual backend response schemas, not the old comments or assumed mock contract.

High — authentication treats network errors as logout

`frontend/src/hooks/useAuth.ts` catches every `/auth/me` failure and clears the authenticated user. A temporary network or server failure is therefore treated the same as an invalid session, potentially redirecting a legitimate user to login.

Distinguish `401` from network failures and server errors. Show a retryable session-check error when authentication cannot be verified.

High — the configured API URL is ignored

`frontend/.env.local` defines `VITE_API_BASE_URL`, but `frontend/src/services/api.ts` hard-codes `baseURL: '/api/v1'`.

Centralize the base URL and use a development proxy deliberately. Do not expose secrets through Vite environment variables.

High — the chat is not actually streaming

`useRepositoryChat.ts` creates a pending assistant message, but `services/chat.ts` waits for a complete JSON response. The typing state is a loading placeholder, not token-by-token streaming, despite the Week 1 chat UI requirement.

Either implement the streaming contract jointly with the backend or label the current behavior honestly until streaming is available. Never simulate real streaming by progressively displaying a completed response.

High — real-time connection handling is incomplete

`frontend/src/realtime/index.ts` closes the EventSource on error, and the hook has no reconnection backoff. The connection can remain down until the component remounts.

The backend route and event schema must also be verified before relying on SSE for sync status.

High — incomplete service modules

`pullRequests.ts`, `tasks.ts`, `execution.ts`, `reviews.ts`, and `blastRadius.ts` are empty files. They should either be explicitly deferred to later weeks or removed until required. Do not expose nonfunctional features in the Week 1 interface.

These are source-level findings from the archive, not assumptions about what the frontend looks like when rendered in your browser.

## 3. Page-by-page professional audit

### A. Login and authentication

Files: `pages/Login.tsx`, `pages/AuthCallback.tsx`, `hooks/useAuth.ts`, `services/auth.ts`, `layouts/ProtectedRoute.tsx`.

Problems to address:

- The login screen is a minimal centered card rather than a branded developer-tool entry point.
- OAuth callback behavior needs to be matched exactly to the backend redirect and cookie-setting behavior.
- A session-check failure is currently interpreted as unauthenticated regardless of cause.
- The logout handler in `AppLayout.tsx` awaits the logout request before navigating. If the request fails, the local session is cleared by the hook, but navigation can fail to execute because the rejected promise propagates.
- Authentication checks should not run unnecessarily in multiple mounted components.
- There is no polished recovery UI for callback failures, denied permissions, expired sessions, or a temporarily unavailable backend.

Target: a restrained, professional sign-in screen with a clear product identity, one primary GitHub action, permission explanation, and actionable errors. Keep the cookie-based authentication model; never store the JWT in `localStorage`.

### B. Dashboard

File: `pages/Dashboard.tsx`.

What is good:

- Repository cards are reusable.
- Loading, error, empty, and pagination states already exist.
- The page uses TanStack Query for server data.

What needs improvement:

- The page is primarily a repository grid; it does not yet establish a clear overview of the developer's workspace.
- Sync failures and stale repositories need clearer status treatment and recovery actions.
- Quick actions should be based on real functionality, not decorative cards.
- Repository counts and activity summaries must be derived from backend data, not invented statistics.
- Pagination and background refetching need to preserve the user's current context.
- The page should adapt to small laptop viewports without creating excessive scrolling.

Target: a workspace overview with connected repositories, actual indexing states, recent repository activity when available, and an obvious route to ask a question or connect another repository.

### C. Repository selector

Files: `pages/Repositories.tsx`, `services/repositoryDiscovery.ts`, `hooks/useAvailableRepositories.ts`, `hooks/useConnectRepository.ts`.

What is good:

- Debounced search is implemented.
- The UI distinguishes connected from available repositories.
- Connection errors are tracked per repository.
- The code uses query-cache invalidation after successful connection.

What needs improvement:

- The response contract is still documented as assumed in places even though the backend contains relevant routes.
- The page must distinguish GitHub installation problems from an empty repository list.
- A single `isConnecting` flag can make mutation feedback ambiguous when multiple cards are rendered; ensure the UI disables and indicates only the relevant operation or intentionally serializes connects.
- After connecting a repository, the UI must not imply indexing is complete merely because the connect endpoint returned successfully.
- Search, pagination, and connect actions must remain consistent as background queries refresh.

Target: a repository discovery workbench with a strong search field, connected/unconnected state, per-repository connect actions, and a real synchronization state.

### D. Repository explorer

File: `pages/RepositoryDetail.tsx`.

This page is one of the largest integration risks because it consumes multiple endpoints and displays repository data that is not all present in the current backend response schema.

The frontend defines optional fields for description, framework, file count, symbol count, and chunk count, while explicitly documenting some of them as mocked additions. The dependency service also states that the backend does not expose the expected endpoint.

Required fixes:

- Remove fabricated metadata and placeholder dependencies from the production path.
- Show a genuine loading or unavailable state when metadata is not available.
- Avoid issuing file/dependency queries before the repository reaches an appropriate indexing state.
- Poll sync status only while the job is active, with bounded frequency and cleanup on unmount.
- Show the last successful sync separately from the current attempt.
- Provide a usable file tree with clear empty/error states and a route into repository chat.
- Display file, symbol, and chunk counts only when backed by real data.

Target: a compact codebase overview with a repository header, sync status, real file tree, meaningful metadata, and a clear “Ask this codebase” action.

### E. Repository chat

Files: `pages/RepositoryChat.tsx`, `hooks/useRepositoryChat.ts`, `services/chat.ts`.

This is the core product screen and deserves the largest design and engineering investment.

Current strengths:

- The chat is repository-scoped.
- Conversation state is kept locally.
- The request sends a validated question/history structure.
- Source metadata is represented by a TypeScript type.
- The composer supports Enter to send and Shift+Enter for a newline.
- There is an initial loading/pending state and a retry affordance.

Problems:

- The backend returns a complete answer rather than a real stream.
- The UI's `isStreaming` name overstates the behavior.
- Conversation state is lost when the component is unmounted or refreshed.
- The source type defines file and line references, but each source needs to be a genuine interactive control that opens the correct repository file and location.
- Error handling should preserve the failed question and let the user retry without duplicating messages.
- The current layout relies on negative margins and a fixed viewport calculation. Nested scroll containers and small laptop windows need explicit testing.
- There is no clear evidence of markdown/code rendering quality, syntax highlighting, copy controls, or accessible source navigation.
- Long responses, empty retrieval, model/provider errors, and indexing-in-progress states need deliberate handling.

Target: a coding assistant conversation panel, not a generic messaging screen. Answers should support readable markdown, code blocks, copy actions, source chips, and clear retrieval/grounding states when the backend provides that information.

## 4. Design direction: inspired by Antigravity and Claude Code, not copied

Use these products as workflow references, not visual templates. Your product should have its own name, component design, icons, spacing, colors, and interaction patterns.

[Primeros pasos con Google Antigravity  |  Google Codelabs](https://images.openai.com/static-rsc-4/sDQtOKubIE_FsI2SMZl44trC3Yl1Lk5KbhM_hgvSNGtzcDdyQC2Pfqh4ZszEu9L6k7WWUtsvWM0eoo0VRevib6OXeWzBUNaEcVQ6zSjM2SShL4zc-KH6MYznDRG4ExKxnRs9pMOODJWbKzWopji4mibIUgIqW5p3Biiw0t5yo04?purpose=inline)

Reference: Antigravity

Borrow the concept of an integrated developer workspace: clear project context, tools close to the work, status visibility, and an environment that feels built for engineering.

[Claude Code can just do things - Dane Grant](https://images.openai.com/static-rsc-4/5PblcZLjY6etXFkgYxN3w2dZrbxiAKhtUpny21HKneJWrHpcWAhalWKZ0X18DYtKWsz5cbzsByz0FA2iaAPW1t7cciWHjILeiv81MF-Wv69I9nETIfGgXcnTK0exV99gBUGvvzqu-szAjHqdyet2XF7YjLTeLqamRmPDJi023Bw?purpose=inline)

Reference: Claude Code

Borrow the workflow principle of a focused coding conversation grounded in project context. Keep the question, answer, code evidence, and follow-up actions connected.

### Recommended product identity

Use a dark, low-glare Code Intelligence Workbench design:

- Deep charcoal background rather than pure black.
- Slightly lighter panels with subtle borders.
- One restrained accent color for primary actions and selected navigation.
- Monospace typography for paths, symbols, line numbers, and code.
- A clean sans-serif font for explanations, headings, and controls.
- Compact but readable spacing.
- Minimal shadows and restrained gradients.
- Clear hierarchy instead of excessive glass effects, glowing borders, or animated decoration.

Do not clone either product's exact layout, logos, terminology, screenshots, or distinctive visual assets.

### Proposed application shell

### Code Intelligence

Workspace

WORKSPACE

Overview

Repositories

CURRENT PROJECT

my-codebase

src/auth.ts

src/api.ts

REPOSITORY INTELLIGENCE

## Understand your codebase

Explore architecture, search symbols, and ask questions grounded in indexed source files.

Ask your repository

Where is authentication implemented?

Conceptual layout only — not a screenshot of your current application.

This is the overall direction, not a final visual specification. The real chat screen should use more horizontal room for conversation and evidence than the overview page.

## 5. Professional design specification

The design should be consistent across all five screens, with the chat and repository explorer sharing the same application shell.

### Global layout

Desktop application shell

Target

Navigation

200–240 px

Workspace, repositories, settings

Main workspace

Flexible width

Dashboard, file explorer, or chat

Evidence panel

Optional

Sources, symbols, file details

Suggested proportions, not fixed pixel requirements. The evidence panel should collapse on narrower screens.

Use a viewport-filling shell with independently scrollable content panels. On a normal laptop, the main workspace should fit within the available viewport; long file trees, conversations, and source lists should scroll inside their own panels instead of creating multiple competing page scrollbars.

### Design tokens

| Token            | Recommendation                                                 |
| ---------------- | -------------------------------------------------------------- |
| Main background  | Deep charcoal                                                  |
| Panel background | Slightly lighter charcoal                                      |
| Borders          | Subtle neutral gray                                            |
| Primary accent   | Restrained blue or blue-violet                                 |
| Success          | Muted green                                                    |
| Warning          | Amber                                                          |
| Error            | Muted red                                                      |
| Typography       | Clean sans-serif; monospace for code                           |
| Radius           | Consistent 6–10 px                                             |
| Motion           | Short, purposeful transitions; respect reduced-motion settings |

Do not hard-code colors throughout individual components. Centralize tokens and use shared primitives for buttons, inputs, cards, status indicators, tooltips, dialogs, and loading states.

### Page layout rules

- Login: minimal, branded, focused on GitHub authentication.
- Dashboard: compact workspace overview and connected repository cards.
- Repositories: search, filter, connect, and sync status.
- Explorer: repository header, compact file tree, real metadata, and chat action.
- Chat: conversation center, repository context in the left panel, and collapsible evidence/source details.

Avoid filling every screen with cards. Use typography, whitespace, subtle dividers, and clear interaction hierarchy.

## 6. API integration and state management audit

The existing architecture is worth retaining: React, React Router, TanStack Query, Zustand, Axios, and TypeScript. A professional redesign should not require replacing these tools.

| Component                         | Required change                                                                                                                             |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `services/api.ts`                 | Use configurable base URL, consistent error normalization, request timeout, and safe handling of session expiry.                            |
| `services/auth.ts`                | Match the real backend session and logout contract.                                                                                         |
| `services/repositories.ts`        | Match actual response schemas; do not assume server pagination when the endpoint returns a plain list.                                      |
| `services/repositoryDiscovery.ts` | Remove stale mock assumptions and align field names and status codes with the implemented backend.                                          |
| `services/chat.ts`                | Keep the response contract accurate; add streaming only when a real streaming API exists.                                                   |
| `hooks/useAuth.ts`                | Distinguish unauthenticated, loading, and service-unavailable states.                                                                       |
| `hooks/useRepositories.ts`        | Handle polling, cache invalidation, pagination, and synchronization states correctly.                                                       |
| `hooks/useRepositoryChat.ts`      | Prevent duplicate submissions, preserve retryable questions, clean up requests, and handle completed versus streaming responses accurately. |
| `realtime/index.ts`               | Implement bounded reconnection and verify event contracts.                                                                                  |
| `types/api.ts`                    | Make backend-derived types accurate and remove assumptions disguised as confirmed schemas.                                                  |
| `mocks/handlers.ts`               | Keep mock data for isolated development/testing only; never mix mock and live data silently.                                                |

### Important synchronization issue

The frontend currently maps the entire `SYNCING` state to `CLONING`, because the backend does not provide distinct stages in the repository status enum. This is an acceptable temporary display only if clearly communicated.

To show `Cloning → Scanning → Indexing → Ready` truthfully, the backend must expose actual job progress. Do not animate through stages merely to make the interface look active.

### Important streaming issue

`Docs/week1.md` requires a streaming chat experience, but the current chat service uses an ordinary POST request that returns a complete answer.

Antigravity should:

1. Inspect the actual backend chat response and any existing SSE routes.
2. Decide on one supported streaming contract with the backend.
3. If implemented, handle partial content, cancellation, connection failure, final citations, and completion events.
4. If the backend cannot stream yet, keep a high-quality pending state and explicitly report streaming as incomplete.

The UI must never display fake token-by-token streaming.

## 7. Accessibility, responsiveness, and reliability

A professional frontend must work beyond a single desktop screenshot.

- Support keyboard navigation and visible focus states.
- Use semantic buttons and links, with accessible labels for icon-only controls.
- Ensure dialogs, popovers, and menus are keyboard accessible.
- Use appropriate live announcements for completed chat responses and errors without repeatedly announcing every render.
- Respect reduced-motion preferences.
- Ensure code blocks and long paths do not force the entire page wider than the viewport.
- Test at laptop, tablet, and mobile widths.
- Keep the chat composer visible while the conversation panel scrolls.
- Ensure the sidebar collapses appropriately on smaller screens.
- Handle browser refresh on nested routes.
- Preserve intended redirects after authentication.
- Add request cancellation and prevent stale responses from overwriting newer state.
- Avoid unnecessary polling, repeated `/auth/me` calls, and duplicate requests.
- Display useful empty, loading, error, and success states for every asynchronous screen.

## 8. Build and testing status

I attempted `npm run build` in the extracted archive.

- The TypeScript build step completed far enough to reach Vite.
- Vite then failed because the archived `node_modules` lacked the platform-specific Rolldown native binding required by the Linux audit environment.

This is an environment/dependency installation problem; it does not establish that the frontend source fails to compile on your MacBook.

The final audit should run a clean dependency installation on the target development environment, then execute:

```
cd frontend
npm ci
npm run build
npm run lint
```

Antigravity should also add tests for authentication state, repository connection, query-cache invalidation, sync progress, chat retry behavior, citation links, and error states. Add browser-level end-to-end tests for the primary user journey if the project's existing tooling supports them.

## 9. Ready-to-paste Antigravity prompt

This is the implementation prompt. It directs Antigravity to audit the existing frontend, align it with `Docs/week1.md`, fix functional issues, and redesign the UI around a distinct AI coding workspace inspired by the workflows of Antigravity and Claude Code.

# Task: Professional Frontend Audit, Functional Repair, and Code Intelligence Workspace Redesign

## Project context

Project: existing SoftwearProject codebase.

Primary requirements: `Docs/week1.md`.

Frontend: `frontend/`.

Backend contract: inspect the actual FastAPI routes, Pydantic schemas, response models, authentication behavior, synchronization jobs, and chat API before changing frontend integration.

Reference products: Google Antigravity and Claude Code, for workflow inspiration only.

## Main objective

Perform a complete, professional frontend audit and implement the required changes.

The target is a polished AI Code Intelligence Workspace that feels like a serious developer tool, not a generic admin dashboard or ordinary chatbot.

Take inspiration from the integrated developer workflows of Antigravity and Claude Code, but create an original visual identity, layout, components, navigation, and interactions. Do not copy their screenshots, logos, exact layouts, distinctive assets, or branding.

**Do not stop after providing an audit report. Inspect the actual code, implement necessary changes, run checks, fix failures, and verify the complete Week 1 user journey.**

Preserve the existing React, TypeScript, Vite, React Router, TanStack Query, Zustand, Axios, and Tailwind architecture unless a specific technical problem justifies a change.

Do not rewrite the application unnecessarily.

## Phase 1 — Complete frontend inventory

Inspect the entire `frontend/src/` directory, configuration, dependencies, and relevant backend files.

Audit at least:

- `App.tsx` and `main.tsx`
- All pages in `pages/`
- All components in `components/`
- `layouts/`
- `services/`
- `hooks/`
- `stores/`
- `types/api.ts`
- `realtime/`
- `mocks/`
- `index.css`
- Tailwind configuration
- Vite configuration
- TypeScript configuration
- `package.json` and lockfile
- Frontend environment files
- `Docs/week1.md`
- Corresponding backend routes and schemas

For every module, identify:

1. Actual responsibility.
2. Whether it is used.
3. Broken imports and incorrect assumptions.
4. Missing functionality.
5. Incorrect backend contracts.
6. Duplicate logic and unnecessary abstractions.
7. Mocked data and unfinished implementations.
8. Authentication and state-management problems.
9. Responsive layout and accessibility problems.
10. Relevant Week 1 requirements and acceptance tests.

Classify each finding as CRITICAL, HIGH, MEDIUM, LOW, or DEFERRED.

Produce a file-by-file audit report and a Week 1 requirements traceability matrix.

## Phase 2 — Align with Docs/week1.md

Week 1 requires five functional screens:

1. Login and GitHub OAuth callback.
2. Dashboard with connected repositories and sync status.
3. Repository selector with GitHub discovery, search, and connection.
4. Repository explorer with metadata, files, symbols, and dependencies where available.
5. Repository chat with loading states, streaming where supported, and clickable source references.

Preserve this scope.

Do not add nonfunctional pull-request management, autonomous agents, code execution, reviews, tasks, or other Week 2/3 functionality to the Week 1 navigation.

Inspect the existing empty service files:

- `services/pullRequests.ts`
- `services/tasks.ts`
- `services/execution.ts`
- `services/reviews.ts`
- `services/blastRadius.ts`

Remove or defer them explicitly if they have no Week 1 responsibility. Do not delete any module without checking imports and planned dependencies.

## Phase 3 — Redesign the application shell

Create a coherent Code Intelligence Workspace.

### Visual identity

Use a restrained dark developer-workspace aesthetic:

- Deep charcoal backgrounds.
- Slightly lighter panel surfaces.
- Subtle neutral borders.
- One consistent accent color.
- Clean sans-serif typography for the interface.
- Monospace typography for file paths, symbols, line numbers, and code.
- Consistent spacing, radii, and icon sizes.
- Clear typography hierarchy.
- Minimal shadows and decorative effects.
- Purposeful transitions that respect reduced-motion preferences.

Avoid excessive gradients, glowing borders, glass effects, oversized cards, decorative statistics, and generic AI-generated dashboard styling.

Do not copy Antigravity or Claude Code's exact interface. Create an original design system.

### Application shell

Implement a consistent shell with:

- Collapsible left navigation.
- Product identity and workspace context.
- Repository navigation.
- Current repository context when applicable.
- Main workspace.
- Optional contextual evidence panel.
- Clear account/session controls.
- Accessible tooltips and menus.

The navigation should distinguish workspace overview, repositories, and the currently selected repository.

Use the full available viewport on desktop and laptop screens. Keep panels independently scrollable, with the chat composer pinned where appropriate. Avoid unnecessary nested page scrolling.

On narrower screens, collapse the navigation and contextual panels cleanly.

Use the existing routing and component structure where possible.

## Phase 4 — Establish design tokens and reusable primitives

Centralize design tokens in the existing styling system.

Define consistent values for:

- Background and panel surfaces.
- Foreground and muted text.
- Borders and dividers.
- Primary and secondary actions.
- Success, warning, and error states.
- Focus rings.
- Typography scale.
- Spacing.
- Radius.
- Transitions.
- Z-index and overlay behavior.

Create or refactor reusable primitives as needed:

- Button
- IconButton
- Input
- Textarea
- Tooltip
- StatusBadge
- RepositoryCard
- LoadingSkeleton
- EmptyState
- ErrorState
- RetryAction
- Dialog
- Dropdown
- Tabs
- FileTreeItem
- SourceReference
- CodeBlock
- Toast or notification

Avoid duplicate UI implementations across pages. Do not introduce a second component library without a demonstrated need.

Use semantic HTML and accessible controls.

## Phase 5 — Repair authentication

Inspect:

- `pages/Login.tsx`
- `pages/AuthCallback.tsx`
- `hooks/useAuth.ts`
- `stores/useAuthStore.ts`
- `services/auth.ts`
- `layouts/ProtectedRoute.tsx`
- `layouts/AppLayout.tsx`
- Backend authentication routes and cookie configuration

Fix the real integration rather than merely restyling the screens.

Requirements:

- Match the actual backend OAuth start and callback URLs.
- Verify how the backend redirects after setting the HTTP-only session cookie.
- Keep JWTs out of localStorage and sessionStorage.
- Keep credentials out of frontend code.
- Handle successful login, denied permissions, invalid state, expired session, and callback failure.
- Distinguish HTTP 401 from network errors, 5xx responses, and temporary session-check failures.
- Do not clear valid local user state on every transient server error.
- Provide a retryable error screen when session verification cannot complete.
- Avoid duplicate `/auth/me` requests caused by component mounting.
- Ensure logout clears local session state and navigates correctly even if the logout request fails.
- Preserve safe redirects after authentication.
- Ensure protected routes do not render protected data before session verification completes.

Test login, refresh, logout, invalid session, and temporary backend outage.

## Phase 6 — Repair API integration and TypeScript contracts

Inspect the actual backend endpoints and Pydantic response schemas.

Known issues to investigate:

1. `services/api.ts` hard-codes `/api/v1` even though `VITE_API_BASE_URL` is configured.
2. `services/repositoryDiscovery.ts` contains stale comments claiming relevant endpoints are not implemented, despite the archived backend defining repository discovery and connection routes.
3. Repository discovery response fields and pagination assumptions may not match the real backend.
4. `services/repositories.ts` uses client-side pagination because the connected repository endpoint returns a plain list.
5. Repository description, framework, counts, and dependencies include mocked or optional frontend assumptions.
6. The chat response currently returns a complete answer, not a token stream.
7. The frontend SSE client expects an events endpoint whose backend availability and schema must be verified.

Required actions:

- Centralize API base URL configuration.
- Keep `withCredentials` for cookie authentication.
- Do not expose secrets through `VITE_` environment variables.
- Normalize backend errors consistently.
- Configure request timeouts.
- Preserve request cancellation where supported.
- Use typed service functions.
- Match real field names, response envelopes, pagination, and status codes.
- Remove stale comments and speculative contracts after verification.
- Keep UI-facing adapters only where they serve a real compatibility purpose.
- Avoid `any` and unsafe type assertions in production code.
- Avoid showing mocked metadata in the real backend workflow.

Update API types from the actual backend schemas rather than maintaining multiple competing contracts.

Do not silently switch between mocked and live responses.

## Phase 7 — Dashboard

Redesign `pages/Dashboard.tsx` as a workspace overview.

Include:

- A clear page heading and repository context.
- Connected repository list.
- Repository name, language, last successful sync, and actual sync status.
- Useful quick actions to connect a repository, explore a repository, or ask a question.
- Loading, empty, error, retry, and background-refetch states.
- Pagination when needed.
- Responsive repository cards or rows.
- Clear failed-sync recovery actions.

Only display counts and recent activity when supported by real backend data. Do not invent repository statistics, activity, model usage, or success rates.

Keep the layout compact and useful rather than filling the screen with decorative metric cards.

## Phase 8 — Repository selector

Redesign `pages/Repositories.tsx` and its related hooks/services.

Requirements:

- Search and filtering.
- Debounced requests.
- Stable pagination.
- Clear connected and unconnected states.
- Per-repository connection loading state.
- Prevent duplicate submissions.
- Display actionable connection errors.
- Correct cache invalidation after successful connection.
- Navigate using the internal repository UUID returned by the backend.
- Distinguish an empty result from a GitHub App installation or permission error.
- Avoid marking a repository ready merely because the connect endpoint succeeded.

Verify the actual GitHub discovery and connect endpoints.

The interface should communicate that connecting and indexing are different operations.

## Phase 9 — Repository explorer

Redesign `pages/RepositoryDetail.tsx`.

Create a compact codebase overview with:

- Repository name and owner.
- Default branch.
- Language and supported metadata.
- Current sync/indexing status.
- Last successful synchronization time.
- File tree with readable paths.
- Symbol information where available.
- Dependency information only when supported by real API data.
- A prominent action to ask questions about the repository.
- Appropriate empty, loading, failed-sync, and unavailable-data states.

Requirements:

- Do not fabricate descriptions, frameworks, file counts, symbol counts, chunk counts, or dependencies.
- Do not request unavailable endpoints.
- Do not issue expensive queries before the repository is ready.
- Poll sync status only while a job is active.
- Stop polling on unmount or terminal status.
- Use bounded polling intervals.
- Preserve the last known successful sync information when a new sync fails.
- Make the file tree keyboard accessible.
- Show long paths without breaking the layout.
- Provide a coherent navigation path from a selected file or symbol to repository chat.

If file-content retrieval is not implemented by the backend, do not pretend that a file can be opened in a real code editor.

## Phase 10 — Repository chat: highest priority

Inspect:

- `pages/RepositoryChat.tsx`
- `hooks/useRepositoryChat.ts`
- `services/chat.ts`
- Chat-related TypeScript types.
- Backend chat endpoint and response schema.
- Any existing backend SSE or streaming implementation.

Build a high-quality repository-aware conversation interface.

### Layout

- Compact repository header.
- Conversation history in the main panel.
- Composer anchored at the bottom.
- Clear repository context.
- Optional collapsible sources/evidence panel.
- Appropriate independent scrolling.
- Responsive behavior for laptop, tablet, and mobile.

### Conversation behavior

- Support Enter to send and Shift+Enter for a newline.
- Prevent duplicate submissions.
- Disable submission while the request is active.
- Preserve the failed question for retry.
- Provide a cancel/stop action only when the request can genuinely be cancelled.
- Handle long answers and code blocks.
- Support accessible keyboard navigation.
- Show loading skeletons and useful error states.
- Avoid duplicate user or assistant messages after failures.
- Preserve conversation state while navigating within the intended scope.
- Do not claim conversation persistence if it is only in local component state.

### Response rendering

- Render Markdown safely.
- Support readable code blocks and copy controls.
- Preserve whitespace and code formatting.
- Display sources with file path, line range, and symbol when available.
- Make verified source references clickable.
- Use real routes or file-detail actions; do not add dead buttons.
- Clearly communicate insufficient evidence or unavailable grounding when provided by the backend.
- Do not display invented confidence values or fabricated citations.

### Streaming

Week 1 requests streaming, but the current chat service uses a regular POST returning a complete JSON response.

Inspect the actual backend capability before implementation.

If a real SSE or streaming endpoint exists, implement it correctly, including:

- Partial response updates.
- Cancellation.
- Network errors.
- Completion events.
- Final citation metadata.
- Cleanup when the component unmounts.

If the backend does not support streaming, keep a truthful pending/loading state and report streaming as an outstanding integration task. Do not fake token-by-token streaming by progressively rendering a completed answer.

## Phase 11 — Synchronization and realtime updates

Inspect:

- `realtime/events.ts`
- `realtime/index.ts`
- `hooks/useRealtimeRepositories.ts`
- Backend event routes and event payload schemas.
- Repository sync job/status schemas.

Fix the lifecycle of the SSE connection.

- Connect only when the authenticated session and backend endpoint are valid.
- Close the connection on logout or unmount.
- Add bounded reconnection with backoff and cleanup.
- Avoid reconnect loops.
- Validate event payloads before using them.
- Invalidate the correct TanStack Query keys.
- Do not rely on guessed event names or payload shapes.
- Fall back to bounded polling if realtime events are unavailable.

The backend currently exposes coarse synchronization states. Show Cloning, Scanning, Indexing, and Ready only when those stages are backed by actual backend job progress.

Never animate fake progress.

## Phase 12 — State management and performance

Preserve the existing separation:

- TanStack Query for server data.
- Zustand for small shared UI/session state.
- Local React state for transient component concerns.

Audit all query keys, cache invalidation, retries, polling, and cancellation.

Requirements:

- Avoid duplicate requests.
- Avoid storing the same server data in both Zustand and TanStack Query.
- Reset user-specific caches when logging out.
- Prevent stale requests from overwriting current route data.
- Use stable list keys.
- Avoid unnecessary component re-renders.
- Debounce search correctly.
- Avoid excessive refetching.
- Lazy-load routes only where it improves real performance.
- Ensure the application remains responsive with large repository lists and long conversations.

Do not optimize based on guesses. Verify the actual source of unnecessary work.

## Phase 13 — Responsive behavior and accessibility

Test at desktop, laptop, tablet, and mobile widths.

Requirements:

- The main workspace fits the available desktop viewport.
- Side panels collapse or become overlays on narrow screens.
- Chat composer remains accessible.
- File paths and code blocks do not cause page-wide horizontal overflow.
- Long conversations scroll within the conversation panel.
- Every icon-only action has an accessible name.
- Buttons and links work by keyboard.
- Focus states remain visible.
- Dialogs and menus are keyboard accessible.
- Status changes and completed responses are announced appropriately.
- Color is not the only way to communicate state.
- Contrast is sufficient.
- Reduced-motion preferences are respected.

Avoid competing nested scrollbars and fixed heights that clip content on short laptop screens.

## Phase 14 — Remove dead code and production mocks

Search the complete frontend for:

- Empty service files.
- Unused components and hooks.
- Duplicate services.
- Stale API comments.
- Placeholder values.
- Fake response data.
- Mock endpoints in production paths.
- Dead navigation links.
- Inert buttons.
- Unused imports and dependencies.
- Hard-coded URLs.
- Incorrect assumptions hidden behind TypeScript types.

Retain MSW only for explicit development and testing scenarios. Enable it intentionally through a documented development setting, not silently in production.

Never display mock repository data alongside live data.

Do not delete a file until all references, tests, and intended future responsibilities have been checked.

## Phase 15 — Tests and verification

Run:

```
cd frontend
npm ci
npm run build
npm run lint
```

Resolve dependency installation problems appropriately for the target environment. Do not assume archived native modules are portable between operating systems.

Add tests using the existing tooling where practical.

Test:

1. Login and callback states.
2. Authentication check success, 401, network error, and server error.
3. Logout behavior.
4. Protected routes.
5. Repository discovery, search, pagination, and connection.
6. Cache invalidation.
7. Sync status and polling cleanup.
8. Repository explorer loading, empty, and error states.
9. Chat success, retry, duplicate-submit prevention, and cancellation where supported.
10. Source-reference navigation.
11. SSE reconnect and cleanup where applicable.
12. Responsive navigation and accessible controls.
13. API contract consistency with the backend.
14. Full user flow from login to repository chat.

Use mocked API responses for repeatable tests. Add browser-level end-to-end tests if the existing environment supports them.

Report tests as PASSED, FAILED, BLOCKED, or NOT RUN. Do not claim a test passed if it was not executed.

## Phase 16 — Required deliverables

Produce:

1. File-by-file frontend audit report.
2. Week 1 requirements traceability matrix.
3. Implemented frontend redesign.
4. List of added, modified, removed, and deferred files.
5. Updated design tokens and reusable components.
6. Corrected API contracts and state handling.
7. Updated environment/setup instructions.
8. Actual test and build results.
9. Screenshots of the implemented application at desktop and mobile widths, if browser tooling is available.
10. A list of remaining backend blockers and incomplete Week 1 features.

## Execution order

1. Inspect all source files and trace API contracts.
2. Produce the audit and establish the baseline.
3. Fix authentication and API integration.
4. Establish design tokens and the application shell.
5. Redesign the dashboard and repository selector.
6. Redesign the repository explorer.
7. Prioritize and complete the repository chat.
8. Fix synchronization/realtime lifecycle.
9. Remove dead code and misleading mocks.
10. Run tests, fix defects, and verify the full journey.
11. Update the traceability matrix and report remaining blockers.

**Final acceptance criterion:** the frontend must be visually cohesive, responsive, accessible, and genuinely connected to the real Week 1 backend workflow. It must look and behave like an original professional AI code-intelligence workspace, with Antigravity and Claude Code serving only as workflow references.

Start with the real code and `Docs/week1.md`, then implement and verify the changes. Do not stop after writing recommendations.

## 10. Recommended priority

I would have Antigravity finish these three outcomes first:

1. Functional correctness: OAuth, repository discovery, connection, synchronization status, and API contracts.
2. Core developer experience: a distinctive application shell, compact repository explorer, and high-quality grounded chat.
3. Reliability and polish: streaming when supported, real source navigation, retry behavior, responsive layouts, and tests.

The strongest result will come from building a cohesive workspace around real repository data—not from adding more visual effects or more pages.&#x20;
