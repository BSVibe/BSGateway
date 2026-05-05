'use client';

import { Component, useSyncExternalStore, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { DemoBanner, isDemoMode, useAutoDemoSession } from '@bsvibe/demo';
import { Layout } from './Layout';
import { useAuth, injectDemoToken } from '../../hooks/useAuth';
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
        <ErrorBoundaryFallback
          isPage={isPage}
          message={this.state.message}
          onReset={() => this.setState({ hasError: false, message: '' })}
        />
      );
    }
    return this.props.children;
  }
}

function ErrorBoundaryFallback({
  isPage,
  message,
  onReset,
}: {
  isPage: boolean;
  message: string;
  onReset: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className={`flex items-center justify-center ${isPage ? 'min-h-[50vh]' : 'min-h-screen'} bg-surface`}>
      <div className="text-center p-8">
        <h1 className="text-2xl font-bold text-on-surface mb-2">{t('common.somethingWrong')}</h1>
        <p className="text-on-surface-variant mb-4">{message}</p>
        <button
          onClick={() => {
            if (isPage) {
              onReset();
            } else if (typeof window !== 'undefined') {
              window.location.reload();
            }
          }}
          className="bg-primary-container text-on-primary px-4 py-2 rounded-xl hover:brightness-110 font-bold"
        >
          {isPage ? t('common.tryAgain') : t('common.reloadPage')}
        </button>
      </div>
    </div>
  );
}

function DemoShell({ children }: { children: ReactNode }) {
  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? 'https://api-demo-gateway.bsvibe.dev';
  const { loading, error } = useAutoDemoSession(apiBase, {
    onSessionReady: ({ token, expiresIn }) => {
      // Stash the demo JWT in the auth token cache so child pages'
      // useAuth() / api client picks it up. Without this, the demo
      // shell renders but every data fetch goes out without
      // Authorization → 401 → empty dashboard.
      injectDemoToken(token, expiresIn);
    },
  });

  if (loading) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-surface gap-4">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-amber-500" />
        <p className="text-on-surface-variant text-sm">Setting up your demo sandbox…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface">
        <div className="text-center p-8">
          <h1 className="text-xl font-bold text-on-surface mb-2">Demo unavailable</h1>
          <p className="text-on-surface-variant text-sm">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <>
      <DemoBanner productName="BSGateway" locale="en" />
      <Layout
        onLogout={() => {
          /* demo: no logout */
        }}
        tenantSlug="demo"
        tenantName="Demo sandbox"
        email="demo@bsvibe.dev"
        role="demo"
        tenants={[]}
        onSwitchTenant={() => Promise.resolve()}
      >
        {children}
      </Layout>
    </>
  );
}

function ProdShellInner({ children }: { children: ReactNode }) {
  const hasMounted = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );
  const { isAuthenticated, isLoading, tenantId, tenantName, email, role, logout, tenants, switchTenant } = useAuth({
    probeRemoteSession: false,
  });

  if (!hasMounted || isLoading) {
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
    <Layout
      onLogout={logout}
      tenantSlug={tenantId}
      tenantName={tenantName}
      email={email}
      role={role}
      tenants={tenants}
      onSwitchTenant={switchTenant}
    >
      {children}
    </Layout>
  );
}

function ShellInner({ children }: { children: ReactNode }) {
  // Build-time switch — demo branch is tree-shaken out of prod bundles
  // because isDemoMode() resolves to a static boolean at build time.
  return isDemoMode() ? <DemoShell>{children}</DemoShell> : <ProdShellInner>{children}</ProdShellInner>;
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <ErrorBoundary>
      <ShellInner>{children}</ShellInner>
    </ErrorBoundary>
  );
}
