import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { HelpButton } from '../help/HelpButton';

interface LayoutProps {
  onLogout?: () => void;
  tenantSlug?: string | null;
  tenantName?: string | null;
}

export function Layout({ onLogout, tenantSlug, tenantName }: LayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

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
          className="md:hidden fixed top-4 left-4 z-30 p-2 rounded-lg bg-[#121317] text-slate-300"
          onClick={() => setSidebarOpen(true)}
        >
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
        <Outlet />
      </main>
      <HelpButton />
    </div>
  );
}
