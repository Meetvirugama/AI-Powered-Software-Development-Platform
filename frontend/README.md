# Frontend — AI-Powered Software Development Platform

The frontend provides a real-time developer workbench for repository intelligence, AST symbol navigation, and repository-aware AI chat.

**Lead Owner:** Dhramraj (Frontend Lead)

---

## 1. Technology Stack

- **Framework:** React 19 + TypeScript + Vite 8
- **Routing:** React Router v7 (`react-router-dom`)
- **State Management:** Zustand (`useAuthStore`, `useRepositoryStore`, `useAppStore`)
- **Data Fetching:** TanStack React Query v5 + Axios client (`src/services/api.ts`)
- **Icons:** Lucide React
- **Mocking:** Mock Service Worker (MSW v2)
- **Code Quality:** Oxlint + TypeScript strict compiler (`tsc -b`)

---

## 2. Directory Structure

```text
frontend/src/
├── components/
│   ├── shared/          # Reusable UI primitives (ErrorBoundary, RepositoryCard, etc.)
│   ├── tasks/           # Workflow automation UI (ExecutionTimeline, PublicationPanel, etc.)
│   └── chat/            # Agentic metadata badges and citation inspectors
├── hooks/               # Custom hooks for auth, chat, repository queries, and realtime
├── layouts/
│   ├── AppLayout.tsx    # Global dashboard layout with navigation header and user profile
│   ├── RepositoryStudioLayout.tsx # Studio layout with sub-navigation tabs
│   └── ProtectedRoute.tsx # Route guard enforcing authentication
├── pages/
│   ├── Login.tsx        # GitHub OAuth login screen
│   ├── AuthCallback.tsx # OAuth code exchange and session establishment
│   ├── Dashboard.tsx    # Connected repositories overview and quick stats
│   ├── Repositories.tsx # Repository discovery and connection manager
│   ├── RepositoryDetail.tsx # File tree, symbols, and sync status
│   ├── RepositoryChat.tsx   # Dual-mode chat (Normal RAG + Agentic Investigation)
│   ├── RepositoryExplainStudio.tsx # Code Explanation Studio
│   ├── RepositoryBugStudio.tsx     # Bug Detection & Static Analysis Studio
│   ├── RepositoryTestStudio.tsx    # Framework-Aware Test Generation Studio
│   ├── RepositoryReviewStudio.tsx  # AI Code Review Studio
│   ├── RepositoryTaskStudio.tsx    # Workflow Automation & Plan Studio
│   ├── Tasks.tsx        # Global task list across repositories
│   └── TaskDetail.tsx   # Task execution, approval gate, and draft PR status
├── realtime/            # Real-time WebSocket/SSE event listeners and handlers
├── services/            # Axios API clients mapped to backend REST endpoints
├── stores/              # Zustand state stores
└── types/               # TypeScript interfaces mirroring backend Pydantic schemas
```

---

## 3. Pages & User Flows

| Route | Page Component | Description |
|---|---|---|
| `/login` | `Login.tsx` | Landing screen with "Connect with GitHub" OAuth action |
| `/auth/github/callback` | `AuthCallback.tsx` | Captures OAuth exchange and redirects to dashboard |
| `/dashboard` | `Dashboard.tsx` | Synced repositories grid, quick metrics, and sync health |
| `/repositories` | `Repositories.tsx` | Discover and connect GitHub App accessible repositories |
| `/repositories/:id` | `RepositoryDetail.tsx` | Deep view of repository files, symbols, and status |
| `/repositories/:id/chat` | `RepositoryChat.tsx` | Dual-mode chat: Normal RAG vs Agentic Investigation with tool activity inspector |
| `/repositories/:id/explain` | `RepositoryExplainStudio.tsx` | Deep structured code explanation with syntax highlighting |
| `/repositories/:id/bugs` | `RepositoryBugStudio.tsx` | Static scanner + AI bug findings with confidence scores |
| `/repositories/:id/tests` | `RepositoryTestStudio.tsx` | Framework-aware test generation (`pytest`, `jest`, `unittest`) |
| `/repositories/:id/review` | `RepositoryReviewStudio.tsx` | Multi-category code review with file and PR diff inspection |
| `/repositories/:id/tasks` | `RepositoryTaskStudio.tsx` | Plan generation, human approval gate, and execution monitoring |
| `/tasks/:taskId` | `TaskDetail.tsx` | Execution timeline, bounded repair tracker, and Draft PR link |

---

## 4. Development & Build

### Install Dependencies
```bash
npm install
```

### Run Local Development Server
```bash
npm run dev
# Starts Vite dev server at http://localhost:5173
```

### Run Unit Tests
```bash
npm test -- --run
# Runs Vitest unit test suite (329 tests across 27 suites)
```

### Type Check & Production Build
```bash
npm run build
# Runs `tsc -b && vite build`
```

### Linting
```bash
npm run lint
# Runs Oxlint across all TypeScript and React files
```
