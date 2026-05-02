'use client';

import { type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import {
  LanguageToggle,
  ResponsiveSidebar,
  SidebarBrand,
  SidebarTenantSwitcher,
  SidebarUserCard,
} from '@bsvibe/layout';
import type { SidebarTenant } from '@bsvibe/layout';
import { SUPPORTED_LOCALES, setLocale, type Locale } from '../../i18n';
import { HelpButton } from '../help/HelpButton';

interface LayoutProps {
  onLogout?: () => void;
  tenantSlug?: string | null;
  tenantName?: string | null;
  email?: string | null;
  role?: string | null;
  tenants?: ReadonlyArray<SidebarTenant>;
  onSwitchTenant?: (next: string) => void;
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

export function Layout({
  onLogout,
  tenantSlug,
  tenantName,
  email,
  role,
  tenants = [],
  onSwitchTenant,
  children,
}: LayoutProps) {
  const { t, i18n } = useTranslation();

  const items = navItems.map((item) => ({
    href: item.path,
    label: t(item.labelKey),
    icon: <span className="material-symbols-outlined" aria-hidden="true">{item.icon}</span>,
  }));

  // Show only the tenant name in the tagline slot; collapse to no
  // tagline when the tenant context isn't known yet (matches the other
  // 3 products which also surface only the active workspace name).
  const tagline = tenantName ?? undefined;

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
            <SidebarTenantSwitcher
              tenants={tenants}
              activeTenantId={tenantSlug ?? null}
              onSwitchTenant={(id) => onSwitchTenant?.(id)}
              dataTestId="sidebar-tenant-switcher"
            />
            <LanguageToggle
              value={(i18n.language as Locale) ?? 'en'}
              options={SUPPORTED_LOCALES.map((l) => ({ value: l, label: l.toUpperCase() }))}
              onChange={(next) => setLocale(next as Locale)}
              ariaLabel={t('language.label')}
              dataTestId="lang-switcher"
            />
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
      {/* Mobile top padding (`pt-14`) makes room for the floating hamburger
          shipped by @bsvibe/layout's ResponsiveSidebar (`fixed top-3 left-3`).
          Disabled on md+ where the sidebar becomes an inline rail. */}
      <main className="flex-1 min-h-screen min-w-0 pt-14 md:pt-0">
        {children}
      </main>
      <HelpButton />
    </div>
  );
}
