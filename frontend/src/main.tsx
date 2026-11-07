import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './App.tsx';
import './index.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

function renderApp() {
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </React.StrictMode>,
  );
}

if (import.meta.env.DEV && import.meta.env.VITE_ENABLE_MSW === 'true') {
  import('./lib/mswBootstrap.ts')
    .then(({ enableMocking }) => enableMocking())
    .catch((err) => {
      console.error('Error during MSW bootstrap:', err);
    })
    .finally(() => {
      renderApp();
    });
} else {
  renderApp();
}
