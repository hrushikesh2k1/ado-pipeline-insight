import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import { AuthGate } from './components/LoginPage'
import { PluginProvider } from './context/PluginContext'
import './styles.css'

const client = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } })

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={client}>
      <PluginProvider>
        <AuthGate>
          <App />
        </AuthGate>
      </PluginProvider>
    </QueryClientProvider>
  </React.StrictMode>
)
