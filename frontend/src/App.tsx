import { Component, type ReactNode } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Layout } from './components/layout/Layout';
import { DashboardPage } from './pages/DashboardPage';
import { RulesPage } from './pages/RulesPage';
import { ModelsPage } from './pages/ModelsPage';
import { IntentsPage } from './pages/IntentsPage';
import { RoutingTestPage } from './pages/RoutingTestPage';
import { UsagePage } from './pages/UsagePage';
import { AuditPage } from './pages/AuditPage';
import { ApiKeysPage } from './pages/ApiKeysPage';
import { LoginPage } from './pages/LoginPage';
import { AuthCallbackPage } from './pages/AuthCallbackPage';
import { useAuth } from './hooks/useAuth';
import './index.css';

class ErrorBoundary extends Component<
  { children: ReactNode; fallback?: 'page' | 'app' },
  { hasError: boolean; message: string }
> {
  state = { hasError: false, message: '' };

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, message: error.message };
  }

  render() {
    if (this.state.hasError) {
      const isPage = this.props.fallback === 'page';
      return (
        <div className={`flex items-center justify-center ${isPage ? 'min-h-[50vh]' : 'min-h-screen'} bg-surface`}>
          <div className="text-center p-8">
            <h1 className="text-2xl font-bold text-on-surface mb-2">Something went wrong</h1>
            <p className="text-on-surface-variant mb-4">{this.state.message}</p>
            <button
              onClick={() => {
                if (isPage) {
                  this.setState({ hasError: false, message: '' });
                } else {
                  window.location.reload();
                }
              }}
              className="bg-primary-container text-on-primary px-4 py-2 rounded-xl hover:brightness-110 font-bold"
            >
              {isPage ? 'Try Again' : 'Reload Page'}
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

function PageBoundary({ children }: { children: ReactNode }) {
  return <ErrorBoundary fallback="page">{children}</ErrorBoundary>;
}

function App() {
  const { isAuthenticated, isLoading, tenantId, tenantName, logout } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-amber-500" />
      </div>
    );
  }

  return (
    <BrowserRouter>
      <Routes>
        {/* Auth callback must be accessible regardless of auth state */}
        <Route path="auth/callback" element={<AuthCallbackPage />} />

        {!isAuthenticated ? (
          <Route path="*" element={<LoginPage />} />
        ) : (
          <Route element={<Layout onLogout={logout} tenantSlug={tenantId} tenantName={tenantName} />}>
            <Route index element={<PageBoundary><DashboardPage /></PageBoundary>} />
            <Route path="rules" element={<PageBoundary><RulesPage /></PageBoundary>} />
            <Route path="models" element={<PageBoundary><ModelsPage /></PageBoundary>} />
            <Route path="intents" element={<PageBoundary><IntentsPage /></PageBoundary>} />
            <Route path="test" element={<PageBoundary><RoutingTestPage /></PageBoundary>} />
            <Route path="api-keys" element={<PageBoundary><ApiKeysPage /></PageBoundary>} />
            <Route path="usage" element={<PageBoundary><UsagePage /></PageBoundary>} />
            <Route path="audit" element={<PageBoundary><AuditPage /></PageBoundary>} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        )}
      </Routes>
    </BrowserRouter>
  );
}

function AppWithErrorBoundary() {
  return (
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  );
}

export default AppWithErrorBoundary;
