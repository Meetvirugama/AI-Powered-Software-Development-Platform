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
│   └── shared/          # Reusable UI primitives (ErrorBoundary, RepositoryCard, etc.)
├── hooks/               # Custom hooks for auth, chat, repository queries, and realtime
├── layouts/
│   ├── AppLayout.tsx    # Global dashboard layout with navigation header and user profile
│   └── ProtectedRoute.tsx # Route guard enforcing authentication
├── pages/
│   ├── Login.tsx        # GitHub OAuth login screen
│   ├── AuthCallback.tsx # OAuth code exchange and session establishment
│   ├── Dashboard.tsx    # Connected repositories overview and quick stats
│   ├── Repositories.tsx # Repository discovery and connection manager
│   ├── RepositoryDetail.tsx # File tree, symbols, and sync status
│   └── RepositoryChat.tsx   # Grounded AI conversation with clickable citations
├── realtime/            # Real-time WebSocket/SSE event listeners and handlers
├── services/            # Axios API clients mapped to backend REST endpoints
├── stores/              # Zustand state stores
└── types/               # TypeScript interfaces mirroring backend Pydantic schemas
```

---

## 3. Pages & User Flows

| Route | Page Component | Description |
|-------|----------------|-------------|
| `/login` | `Login.tsx` | Landing screen with "Connect with GitHub" OAuth action |
| `/auth/github/callback` | `AuthCallback.tsx` | Captures OAuth exchange and redirects to dashboard |
| `/dashboard` | `Dashboard.tsx` | Synced repositories grid, quick metrics, and sync health |
| `/repositories` | `Repositories.tsx` | Discover and connect GitHub App accessible repositories |
| `/repositories/:id` | `RepositoryDetail.tsx` | Deep view of repository files, symbols, and status |
| `/repositories/:id/chat` | `RepositoryChat.tsx` | Grounded chat with streaming citations and source inspect |

---

## 4. Development & Build

### Install Dependencies
```bash
npm install
```

### Run Local Development Server
```bash
npm run dev
# Starts Vite dev server at http://localhost:5173 (or http://localhost:3000)
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

---

## 5. Mock Service Worker (MSW)

MSW is configured in `src/mocks/` for local UI development and testing independent of backend availability. To enable browser mocking:
```typescript
import { worker } from './mocks/browser';
if (import.meta.env.DEV && import.meta.env.VITE_USE_MSW === 'true') {
  worker.start();
}
```
