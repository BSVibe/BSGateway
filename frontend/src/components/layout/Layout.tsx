'use client';

import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Sidebar } from './Sidebar';
import { HelpButton } from '../help/HelpButton';

interface LayoutProps {
  onLogout?: () => void;
  tenantSlug?: string | null;
  tenantName?: string | null;
  children: ReactNode;
}

export function Layout({ onLogout, tenantSlug, tenantName, children }: LayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { t } = useTranslation();

  return (
    <div className="min-h-screen bg-surface text-on-surface antialiased">
      <Sidebar
        onLogout={onLogout}
        tenantSlug={tenantSlug}
        tenantName={tenantName}
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />
      <main className="md:ml-64 min-h-screen">
        {/* Hamburger - mobile only */}
        <button
          type="button"
          aria-label={t('nav.openNav')}
          aria-expanded={sidebarOpen}
          className="md:hidden fixed top-3 left-4 z-30 p-2 rounded-lg bg-[#121317] text-slate-300 inline-flex items-center justify-center min-w-11 min-h-11"
          onClick={() => setSidebarOpen(true)}
        >
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
        {children}
      </main>
      <HelpButton />
    </div>
  );
}
