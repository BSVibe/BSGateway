import { useCallback, useEffect, useState } from 'react';
import { api, setOnUnauthorized, resetLogoutFlag } from '../api/client';

const AUTH_URL = import.meta.env.VITE_AUTH_URL || 'https://auth.bsvibe.dev';
const TENANT_NAME_KEY = 'bsvibe_tenant_name';

interface SessionResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

let cachedToken: { value: string; expiresAt: number } | null = null;

export async function getAccessToken(): Promise<string | null> {
  if (cachedToken && Date.now() < cachedToken.expiresAt - 30_000) {
    return cachedToken.value;
  }
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
}

function decodeJwt(token: string): Record<string, unknown> {
  const parts = token.split('.');
  let base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
  const pad = base64.length % 4;
  if (pad) base64 += '='.repeat(4 - pad);
  return JSON.parse(atob(base64));
}

interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
  tenantId: string | null;
  tenantName: string | null;
  role: string | null;
  email: string | null;
}

export function useAuth() {
  const [state, setState] = useState<AuthState>({
    isAuthenticated: false,
    isLoading: true,
    tenantId: null,
    tenantName: sessionStorage.getItem(TENANT_NAME_KEY),
    role: null,
    email: null,
  });

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
    window.location.href = `${AUTH_URL}/login`;
  }, []);

  const signup = useCallback(() => {
    window.location.href = `${AUTH_URL}/signup`;
  }, []);

  return { ...state, login, signup, logout };
}
