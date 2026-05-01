'use client';

import { type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { ResponsiveSidebar, SidebarBrand, SidebarUserCard } from '@bsvibe/layout';
import { LanguageSwitcher } from '../common/LanguageSwitcher';
import { HelpButton } from '../help/HelpButton';

interface LayoutProps {
  onLogout?: () => void;
  tenantSlug?: string | null;
  tenantName?: string | null;
  email?: string | null;
  role?: string | null;
  children: ReactNode;
}

interface NavItemDef {
  path: string;
  labelKey: string;
  icon: string;
}

const navItems: readonly NavItemDef[] = [
  { path: '/', labelKey: 'nav.dashboard', icon: 'dashboard' },
  { path: '/rules', labelKey: 'nav.rules', icon: 'alt_route' },
  { path: '/models', labelKey: 'nav.models', icon: 'model_training' },
  { path: '/test', labelKey: 'nav.routingTest', icon: 'route' },
  { path: '/usage', labelKey: 'nav.usage', icon: 'bar_chart' },
  { path: '/api-keys', labelKey: 'nav.apiKeys', icon: 'vpn_key' },
  { path: '/audit', labelKey: 'nav.audit', icon: 'receipt_long' },
];

function GatewayLogo() {
  return (
    <span className="material-symbols-outlined text-on-primary text-xl" aria-hidden="true">
      hub
    </span>
  );
}

export function Layout({ onLogout, tenantSlug, tenantName, email, role, children }: LayoutProps) {
  const { t } = useTranslation();

  const items = navItems.map((item) => ({
    href: item.path,
    label: t(item.labelKey),
    icon: <span className="material-symbols-outlined" aria-hidden="true">{item.icon}</span>,
  }));

  const tagline = tenantName ?? t('nav.tagline');

  return (
    <div className="min-h-screen bg-surface text-on-surface antialiased flex">
      <ResponsiveSidebar
        ariaLabel={t('nav.openNav')}
        items={items}
        logo={
          <SidebarBrand
            icon={<GatewayLogo />}
            name="BSGateway"
            tagline={tagline}
            href="/"
          />
        }
        footer={
          <div className="flex flex-col gap-3" title={tenantSlug || ''}>
            <LanguageSwitcher />
            {onLogout && email ? (
              <SidebarUserCard
                email={email}
                role={role ?? undefined}
                onSignOut={onLogout}
                signOutLabel={t('nav.logout')}
              />
            ) : null}
          </div>
        }
      />
      <main className="flex-1 min-h-screen min-w-0">
        {children}
      </main>
      <HelpButton />
    </div>
  );
}
