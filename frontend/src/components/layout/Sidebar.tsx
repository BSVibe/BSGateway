'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useTranslation } from 'react-i18next';
import { LanguageSwitcher } from '../common/LanguageSwitcher';

interface NavItem {
  path: string;
  labelKey: string;
  icon: string;
}

const navItems: readonly NavItem[] = [
  { path: '/', labelKey: 'nav.dashboard', icon: 'dashboard' },
  { path: '/rules', labelKey: 'nav.rules', icon: 'alt_route' },
  { path: '/models', labelKey: 'nav.models', icon: 'model_training' },
  { path: '/test', labelKey: 'nav.routingTest', icon: 'route' },
  { path: '/usage', labelKey: 'nav.usage', icon: 'bar_chart' },
  { path: '/api-keys', labelKey: 'nav.apiKeys', icon: 'vpn_key' },
  { path: '/audit', labelKey: 'nav.audit', icon: 'receipt_long' },
];

interface SidebarProps {
  onLogout?: () => void;
  tenantSlug?: string | null;
  tenantName?: string | null;
  isOpen: boolean;
  onClose: () => void;
}

export function Sidebar({ onLogout, tenantSlug, tenantName, isOpen, onClose }: SidebarProps) {
  const pathname = usePathname() ?? '/';
  const { t } = useTranslation();

  return (
    <>
      {/* Backdrop - mobile only */}
      {isOpen && (
        <div
          data-testid="bsgateway-sidebar-backdrop"
          className="fixed inset-0 bg-black/50 z-40 md:hidden"
          onClick={onClose}
          role="presentation"
        />
      )}
    <aside className={`fixed left-0 top-0 h-screen w-64 bg-[#121317] flex flex-col z-50 transform transition-transform duration-200 ${isOpen ? 'translate-x-0' : '-translate-x-full'} md:translate-x-0`}>
      {/* Logo */}
      <div className="p-6 flex items-center gap-3">
        <div className="w-8 h-8 rounded bg-primary-container flex items-center justify-center">
          <span className="material-symbols-outlined text-on-primary text-xl">hub</span>
        </div>
        <div>
          <h1 className="text-xl font-bold tracking-tighter text-amber-500 leading-none">
            BS<span className="text-amber-500">Gateway</span>
          </h1>
          {tenantName ? (
            <p className="text-[10px] text-slate-500 truncate mt-1 max-w-[130px] uppercase tracking-widest" title={tenantSlug || ''}>
              {tenantName}
            </p>
          ) : (
            <p className="text-[10px] uppercase tracking-widest text-slate-500 mt-1">{t('nav.tagline')}</p>
          )}
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-4 py-4 space-y-1">
        {navItems.map((item) => {
          const isActive =
            item.path === '/'
              ? pathname === '/'
              : pathname.startsWith(item.path);
          return (
            <Link
              key={item.path}
              href={item.path}
              onClick={onClose}
              className={`flex items-center gap-3 px-4 py-3 rounded text-sm transition-all duration-200 ${
                isActive
                  ? 'text-amber-500 bg-amber-500/10 border-r-2 border-amber-500 font-semibold'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-[#1f1f24] active:scale-95'
              }`}
            >
              <span className="material-symbols-outlined">{item.icon}</span>
              <span>{t(item.labelKey)}</span>
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="p-4 border-t border-amber-900/10 space-y-3">
        <LanguageSwitcher />
        {onLogout && (
          <button
            onClick={onLogout}
            className="w-full flex items-center gap-3 px-4 py-3 rounded text-sm text-slate-400 hover:text-slate-200 hover:bg-[#1f1f24] transition-colors"
          >
            <span className="material-symbols-outlined">logout</span>
            <span>{t('nav.logout')}</span>
          </button>
        )}
      </div>
    </aside>
    </>
  );
}
