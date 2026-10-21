import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App.tsx'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
})

// MSW mocking is DISABLED — all requests go to the real backend at localhost:8000.
// To re-enable mocking for offline development, uncomment the block below.
//
// async function enableMocking() {
//   if (import.meta.env.DEV) {
//     const { worker } = await import('./mocks/browser')
//     return worker.start({ onUnhandledRequest: 'bypass' })
//   }
// }
// enableMocking().then(() => { ... })

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
)
