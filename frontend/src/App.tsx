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
const RepositoryDetail = lazy(() => import('./pages/RepositoryDetail').then((m) => ({ default: m.RepositoryDetail })));
const RepositoryChat = lazy(() => import('./pages/RepositoryChat').then((m) => ({ default: m.RepositoryChat })));

function RouteFallback() {
  return (
    <div className="flex h-64 w-full items-center justify-center">
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
                <Route path="repositories/:id" element={<RepositoryDetail />} />
                <Route path="repositories/:id/chat" element={<RepositoryChat />} />
              </Route>
            </Route>

            {/* Root redirect */}
            <Route path="/" element={<Navigate to="/app/dashboard" replace />} />

            {/* Catch-all */}
            <Route path="*" element={<Navigate to="/app/dashboard" replace />} />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </ErrorBoundary>
  );
}

export default App;
