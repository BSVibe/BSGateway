'use client';

import { Component, type ReactNode } from 'react';
import { Layout } from './Layout';
import { useAuth } from '../../hooks/useAuth';
import { LoginPage } from '../../page-views/LoginPage';
// Initialize i18next on the client (avoids running in server-render path).
import '../../i18n';

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
                } else if (typeof window !== 'undefined') {
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

function ShellInner({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading, tenantId, tenantName, logout } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-amber-500" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <LoginPage />;
  }

  return (
    <Layout onLogout={logout} tenantSlug={tenantId} tenantName={tenantName}>
      {children}
    </Layout>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <ErrorBoundary>
      <ShellInner>{children}</ShellInner>
    </ErrorBoundary>
  );
}
