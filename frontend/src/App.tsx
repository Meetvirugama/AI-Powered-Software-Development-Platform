import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ErrorBoundary } from './components/shared/ErrorBoundary';
import { ProtectedRoute } from './layouts/ProtectedRoute';
import { AppLayout } from './layouts/AppLayout';
import { LoadingSpinner } from './components/shared/LoadingSpinner';

const Login = lazy(() => import('./pages/Login').then((m) => ({ default: m.Login })));
const AuthCallback = lazy(() => import('./pages/AuthCallback').then((m) => ({ default: m.AuthCallback })));
const Dashboard = lazy(() => import('./pages/Dashboard').then((m) => ({ default: m.Dashboard })));
const Repositories = lazy(() => import('./pages/Repositories').then((m) => ({ default: m.Repositories })));
const RepositoryStudioLayout = lazy(() =>
  import('./layouts/RepositoryStudioLayout').then((m) => ({ default: m.RepositoryStudioLayout }))
);
const RepositoryDetail = lazy(() => import('./pages/RepositoryDetail').then((m) => ({ default: m.RepositoryDetail })));
const RepositoryChat = lazy(() => import('./pages/RepositoryChat').then((m) => ({ default: m.RepositoryChat })));
const RepositoryExplainStudio = lazy(() =>
  import('./pages/RepositoryExplainStudio').then((m) => ({ default: m.RepositoryExplainStudio }))
);
const RepositoryBugStudio = lazy(() =>
  import('./pages/RepositoryBugStudio').then((m) => ({ default: m.RepositoryBugStudio }))
);
const RepositoryTestStudio = lazy(() =>
  import('./pages/RepositoryTestStudio').then((m) => ({ default: m.RepositoryTestStudio }))
);
const RepositoryReviewStudio = lazy(() =>
  import('./pages/RepositoryReviewStudio').then((m) => ({ default: m.RepositoryReviewStudio }))
);
const RepositoryTaskStudio = lazy(() =>
  import('./pages/RepositoryTaskStudio').then((m) => ({ default: m.RepositoryTaskStudio }))
);
const NotFound = lazy(() => import('./pages/NotFound').then((m) => ({ default: m.NotFound })));

function RouteFallback() {
  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-background">
      <LoadingSpinner size="lg" label="Loading page..." />
    </div>
  );
}

export function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/auth/callback" element={<AuthCallback />} />

            {/* Protected Application Routes */}
            <Route path="/app" element={<ProtectedRoute />}>
              <Route element={<AppLayout />}>
                <Route index element={<Navigate to="/app/dashboard" replace />} />
                <Route path="dashboard" element={<Dashboard />} />
                <Route path="repositories" element={<Repositories />} />

                {/* Dedicated Antigravity-Style Repository Workspace Studios */}
                <Route path="repositories/:id" element={<RepositoryStudioLayout />}>
                  <Route index element={<RepositoryDetail />} />
                  <Route path="chat" element={<RepositoryChat />} />
                  <Route path="explain" element={<RepositoryExplainStudio />} />
                  <Route path="bugs" element={<RepositoryBugStudio />} />
                  <Route path="tests" element={<RepositoryTestStudio />} />
                  <Route path="review" element={<RepositoryReviewStudio />} />
                  <Route path="tasks" element={<RepositoryTaskStudio />} />
                </Route>
              </Route>
            </Route>

            {/* Root redirect */}
            <Route path="/" element={<Navigate to="/app/dashboard" replace />} />

            {/* Catch-all 404 */}
            <Route path="*" element={<NotFound />} />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </ErrorBoundary>
  );
}

export default App;
