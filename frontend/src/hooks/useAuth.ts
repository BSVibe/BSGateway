import { useCallback, useEffect, useState } from 'react';
import { api, setOnUnauthorized, resetLogoutFlag } from '../api/client';

const AUTH_URL =
  (typeof process !== 'undefined' && process.env?.NEXT_PUBLIC_AUTH_URL) ||
  'https://auth.bsvibe.dev';
const TENANT_NAME_KEY = 'bsvibe_tenant_name';
const STORED_TOKEN_KEY = 'bsgateway_access_token';
const STORED_REFRESH_KEY = 'bsgateway_refresh_token';

interface SessionResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

let cachedToken: { value: string; expiresAt: number } | null = null;

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

export async function getAccessToken(): Promise<string | null> {
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

  // 3. Cookie-based session (works only on *.bsvibe.dev origins)
  try {
    const res = await fetch(`${AUTH_URL}/api/session`, { credentials: 'include' });
    if (!res.ok) return null;
    const data: SessionResponse = await res.json();
    cachedToken = {
      value: data.access_token,
      expiresAt: Date.now() + data.expires_in * 1000,
    };
    return data.access_token;
  } catch {
    return null;
  }
}

export function clearTokenCache() {
  cachedToken = null;
  if (typeof window !== 'undefined') {
    localStorage.removeItem(STORED_TOKEN_KEY);
    localStorage.removeItem(STORED_REFRESH_KEY);
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
      return {
        isAuthenticated: true,
        isLoading: false,
        tenantId: meta?.tenant_id ?? null,
        tenantName,
        role: meta?.role ?? 'member',
        email: (payload.email as string) ?? null,
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

export function useAuth() {
  const [state, setState] = useState<AuthState>(readInitialState);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const token = await getAccessToken();
      if (cancelled) return;
      if (!token) {
        setState((prev) => ({ ...prev, isLoading: false }));
        return;
      }
      const payload = decodeJwt(token);
      const meta = payload.app_metadata as Record<string, string> | undefined;
      setState({
        isAuthenticated: true,
        isLoading: false,
        tenantId: meta?.tenant_id ?? null,
        tenantName: sessionStorage.getItem(TENANT_NAME_KEY),
        role: meta?.role ?? 'member',
        email: (payload.email as string) ?? null,
      });
    })();
    return () => { cancelled = true; };
  }, []);

  // Fetch tenant name on first auth
  useEffect(() => {
    if (!state.isAuthenticated || !state.tenantId || state.tenantName) return;

    api.get<{ name: string }>(`/tenants/${state.tenantId}`)
      .then((tenant) => {
        sessionStorage.setItem(TENANT_NAME_KEY, tenant.name);
        setState((prev) => ({ ...prev, tenantName: tenant.name }));
      })
      .catch(() => {});
  }, [state.isAuthenticated, state.tenantId, state.tenantName]);

  const logout = useCallback(async () => {
    clearTokenCache();
    resetLogoutFlag();
    sessionStorage.removeItem(TENANT_NAME_KEY);
    await fetch(`${AUTH_URL}/api/session`, { method: 'DELETE', credentials: 'include' }).catch(() => {});
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

  return { ...state, login, signup, logout };
}
