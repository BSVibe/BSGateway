import { useCallback, useEffect, useState } from 'react';
import { isDemoMode } from '@bsvibe/demo';
import { api, setOnUnauthorized, resetLogoutFlag } from '../api/client';

const AUTH_URL =
  (typeof process !== 'undefined' && process.env?.NEXT_PUBLIC_AUTH_URL) ||
  'https://auth.bsvibe.dev';
const TENANT_NAME_KEY = 'bsvibe_tenant_name';
const STORED_TOKEN_KEY = 'bsgateway_access_token';
const STORED_REFRESH_KEY = 'bsgateway_refresh_token';
const LS_ACTIVE_TENANT = 'bsgateway_active_tenant';

interface SessionResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  active_tenant_id?: string | null;
}

let cachedToken: { value: string; expiresAt: number } | null = null;
let cachedActiveTenant: string | null = null;

interface AccessTokenOptions {
  probeRemoteSession?: boolean;
}

function decodeJwt(token: string): Record<string, unknown> {
  const parts = token.split('.');
  let base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
  const pad = base64.length % 4;
  if (pad) base64 += '='.repeat(4 - pad);
  return JSON.parse(atob(base64));
}

function isExpired(token: string): boolean {
  try {
    const payload = decodeJwt(token) as { exp?: number };
    if (!payload.exp) return false;
    return Date.now() / 1000 >= payload.exp - 30;
  } catch {
    return true;
  }
}

/**
 * Read tokens from URL hash fragment (#access_token=...&refresh_token=...) and
 * persist them. Used after redirect from auth.bsvibe.dev/login when running on
 * a cross-origin host (e.g. bsserver:13300) where session cookies aren't
 * accessible.
 */
function consumeHashTokens(): string | null {
  if (typeof window === 'undefined') return null;
  const hash = window.location.hash.startsWith('#') ? window.location.hash.slice(1) : '';
  if (!hash) return null;
  const params = new URLSearchParams(hash);
  const access = params.get('access_token');
  const refresh = params.get('refresh_token');
  if (!access) return null;
  localStorage.setItem(STORED_TOKEN_KEY, access);
  if (refresh) localStorage.setItem(STORED_REFRESH_KEY, refresh);
  history.replaceState(null, '', window.location.pathname + window.location.search);
  return access;
}

export async function getAccessToken({
  probeRemoteSession = true,
}: AccessTokenOptions = {}): Promise<string | null> {
  if (cachedToken && Date.now() < cachedToken.expiresAt - 30_000) {
    return cachedToken.value;
  }

  // 1. Hash fragment (just returned from SSO login on a cross-origin host)
  const hashToken = consumeHashTokens();
  if (hashToken && !isExpired(hashToken)) {
    return hashToken;
  }

  // 2. localStorage fallback (persisted from a previous hash exchange)
  const stored = typeof window !== 'undefined' ? localStorage.getItem(STORED_TOKEN_KEY) : null;
  if (stored && !isExpired(stored)) {
    return stored;
  }

  if (!probeRemoteSession) {
    return null;
  }

  // 3. Cookie-based session (works only on *.bsvibe.dev origins)
  try {
    const res = await fetch(`${AUTH_URL}/api/session`, { credentials: 'include' });
    if (!res.ok) return null;
    const data: SessionResponse = await res.json();
    cachedToken = {
      value: data.access_token,
      expiresAt: Date.now() + data.expires_in * 1000,
    };
    if (data.active_tenant_id) {
      cachedActiveTenant = data.active_tenant_id;
      if (typeof window !== 'undefined') {
        localStorage.setItem(LS_ACTIVE_TENANT, data.active_tenant_id);
      }
    }
    return data.access_token;
  } catch {
    return null;
  }
}

/**
 * Resolve the active tenant id for the `X-Active-Tenant` request header.
 *
 * Tier 3.2 collapsed the wrapped session JWT to the raw Supabase JWT, which
 * carries no tenant claim. Product backends now read the active tenant from
 * this header. Resolution order: module cache → localStorage → probe
 * `/api/session` on the auth server → null.
 */
export async function getActiveTenantId(): Promise<string | null> {
  if (cachedActiveTenant) return cachedActiveTenant;

  const stored =
    typeof window !== 'undefined' ? localStorage.getItem(LS_ACTIVE_TENANT) : null;
  if (stored) {
    cachedActiveTenant = stored;
    return stored;
  }

  // Probe the auth server's /api/session — this also refreshes the token
  // cache and, on success, populates cachedActiveTenant as a side effect.
  try {
    const res = await fetch(`${AUTH_URL}/api/session`, { credentials: 'include' });
    if (!res.ok) return null;
    const data: SessionResponse = await res.json();
    if (data.active_tenant_id) {
      cachedActiveTenant = data.active_tenant_id;
      if (typeof window !== 'undefined') {
        localStorage.setItem(LS_ACTIVE_TENANT, data.active_tenant_id);
      }
      return data.active_tenant_id;
    }
    return null;
  } catch {
    return null;
  }
}

export function clearTokenCache() {
  cachedToken = null;
  cachedActiveTenant = null;
  if (typeof window !== 'undefined') {
    localStorage.removeItem(STORED_TOKEN_KEY);
    localStorage.removeItem(STORED_REFRESH_KEY);
    localStorage.removeItem(LS_ACTIVE_TENANT);
  }
}

/**
 * Inject a demo session JWT into the auth token cache so the API client
 * (`getAccessToken()`) returns the demo Bearer for every fetch. Without
 * this, the demo dashboard renders an empty shell — every API call goes
 * out without Authorization and the backend returns 401.
 *
 * Wire this up from the demo shell's ``useAutoDemoSession({onSessionReady})``
 * callback (`@bsvibe/demo` >= 0.3).
 */
export function injectDemoToken(
  token: string,
  expiresIn: number,
): void {
  cachedToken = { value: token, expiresAt: Date.now() + expiresIn * 1000 };
  if (typeof window !== 'undefined') {
    localStorage.setItem(STORED_TOKEN_KEY, token);
    sessionStorage.setItem(TENANT_NAME_KEY, 'Demo sandbox');
  }
}

interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
  tenantId: string | null;
  tenantName: string | null;
  role: string | null;
  email: string | null;
}

function readInitialState(): AuthState {
  // Synchronously read persisted token so consumers (like ModelsPage) get a
  // non-null tenantId on first render instead of firing API calls with "".
  const tenantName = typeof window !== 'undefined'
    ? sessionStorage.getItem(TENANT_NAME_KEY)
    : null;
  const stored = typeof window !== 'undefined'
    ? localStorage.getItem(STORED_TOKEN_KEY)
    : null;
  if (stored && !isExpired(stored)) {
    try {
      const payload = decodeJwt(stored);
      const meta = payload.app_metadata as Record<string, string> | undefined;
      // Demo JWT carries `tenant_id` directly (no app_metadata envelope).
      const directTenantId = (payload.tenant_id as string | undefined) ?? null;
      const isDemoSession = payload.is_demo === true;
      return {
        isAuthenticated: true,
        isLoading: false,
        tenantId: meta?.tenant_id ?? directTenantId,
        tenantName: tenantName ?? (isDemoSession ? 'Demo sandbox' : null),
        role: meta?.role ?? (isDemoSession ? 'demo' : 'member'),
        email: (payload.email as string) ?? (isDemoSession ? 'demo@bsvibe.dev' : null),
      };
    } catch {
      // Fall through to unauthenticated default
    }
  }
  return {
    isAuthenticated: false,
    isLoading: true,
    tenantId: null,
    tenantName,
    role: null,
    email: null,
  };
}

interface SessionTenant {
  id: string;
  name: string;
  role?: string;
}

export function useAuth({
  probeRemoteSession = true,
}: AccessTokenOptions = {}) {
  const [state, setState] = useState<AuthState>(readInitialState);
  const [tenants, setTenants] = useState<SessionTenant[]>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const token = await getAccessToken({ probeRemoteSession });
      if (cancelled) return;
      if (!token) {
        setState((prev) => ({ ...prev, isLoading: false }));
        return;
      }
      const payload = decodeJwt(token);
      const meta = payload.app_metadata as Record<string, string> | undefined;
      const directTenantId = (payload.tenant_id as string | undefined) ?? null;
      const isDemoSession = payload.is_demo === true;
      setState({
        isAuthenticated: true,
        isLoading: false,
        tenantId: meta?.tenant_id ?? directTenantId,
        tenantName:
          sessionStorage.getItem(TENANT_NAME_KEY) ??
          (isDemoSession ? 'Demo sandbox' : null),
        role: meta?.role ?? (isDemoSession ? 'demo' : 'member'),
        email:
          (payload.email as string) ??
          (isDemoSession ? 'demo@bsvibe.dev' : null),
      });
    })();
    return () => { cancelled = true; };
  }, [probeRemoteSession]);

  // Fetch tenant name on first auth (Gateway backend)
  useEffect(() => {
    if (!state.isAuthenticated || !state.tenantId || state.tenantName) return;

    api.get<{ name: string }>(`/tenants/${state.tenantId}`)
      .then((tenant) => {
        sessionStorage.setItem(TENANT_NAME_KEY, tenant.name);
        setState((prev) => ({ ...prev, tenantName: tenant.name }));
      })
      .catch(() => {});
  }, [state.isAuthenticated, state.tenantId, state.tenantName]);

  // Fetch tenants list (auth-app /api/session) so the workspace switcher
  // has all options for the current user. Cookie or bearer accepted.
  // The tenants state defaults to []; when auth is gone, we just skip
  // the fetch (logout() also resets) — avoids a React 19 compiler-lint
  // synchronous-setState-in-effect warning.
  useEffect(() => {
    if (!state.isAuthenticated) return;
    // Demo deployments authenticate against the demo backend, not BSVibe
    // Auth — skip the prod tenants fetch (would CORS-fail anyway).
    if (isDemoMode()) return;
    let cancelled = false;
    (async () => {
      const token = await getAccessToken({ probeRemoteSession });
      if (!token || cancelled) return;
      try {
        const res = await fetch(`${AUTH_URL}/api/session`, {
          credentials: 'include',
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok || cancelled) return;
        const data = (await res.json()) as { tenants?: SessionTenant[] };
        if (!cancelled) setTenants(data.tenants ?? []);
      } catch {
        // ignore
      }
    })();
    return () => { cancelled = true; };
  }, [state.isAuthenticated, probeRemoteSession]);

  const logout = useCallback(async () => {
    clearTokenCache();
    resetLogoutFlag();
    sessionStorage.removeItem(TENANT_NAME_KEY);
    await fetch(`${AUTH_URL}/api/session`, { method: 'DELETE', credentials: 'include' }).catch(() => {});
    setTenants([]);
    setState({
      isAuthenticated: false,
      isLoading: false,
      tenantId: null,
      tenantName: null,
      role: null,
      email: null,
    });
    window.location.href = 'https://bsvibe.dev/';
  }, []);

  useEffect(() => {
    setOnUnauthorized(logout);
  }, [logout]);

  const login = useCallback(() => {
    const redirectUri = `${window.location.origin}/dashboard`;
    window.location.href = `${AUTH_URL}/login?redirect_uri=${encodeURIComponent(redirectUri)}`;
  }, []);

  const signup = useCallback(() => {
    const redirectUri = `${window.location.origin}/dashboard`;
    window.location.href = `${AUTH_URL}/signup?redirect_uri=${encodeURIComponent(redirectUri)}`;
  }, []);

  // Switch active workspace via /api/session/switch_tenant + reload.
  const switchTenant = useCallback(async (nextTenantId: string) => {
    if (nextTenantId === state.tenantId) return;
    const token = await getAccessToken({ probeRemoteSession });
    if (!token) return;
    try {
      const res = await fetch(`${AUTH_URL}/api/session/switch_tenant`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ tenant_id: nextTenantId }),
      });
      if (res.ok) {
        clearTokenCache();
        sessionStorage.removeItem(TENANT_NAME_KEY);
        window.location.reload();
      }
    } catch {
      // ignore
    }
  }, [state.tenantId, probeRemoteSession]);

  return { ...state, login, signup, logout, tenants, switchTenant };
}
