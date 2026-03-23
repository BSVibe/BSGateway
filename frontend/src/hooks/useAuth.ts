import { useCallback, useEffect, useState } from 'react';
import { BSVibeAuth } from '../lib/bsvibe-auth';
import { api, setAuthToken, setOnUnauthorized } from '../api/client';

const AUTH_URL = import.meta.env.VITE_AUTH_URL || 'https://auth.bsvibe.dev';
const TENANT_NAME_KEY = 'bsvibe_tenant_name';

const auth = new BSVibeAuth({
  authUrl: AUTH_URL,
  callbackPath: '/dashboard/auth/callback',
});

interface AuthState {
  isAuthenticated: boolean;
  tenantId: string | null;
  tenantName: string | null;
  role: string | null;
  email: string | null;
}

export function useAuth() {
  const [state, setState] = useState<AuthState>(() => {
    const user = auth.getUser();
    if (user) setAuthToken(user.accessToken);
    return {
      isAuthenticated: !!user,
      tenantId: user?.tenantId ?? null,
      tenantName: sessionStorage.getItem(TENANT_NAME_KEY),
      role: user?.role ?? null,
      email: user?.email ?? null,
    };
  });

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

  const logout = useCallback(() => {
    setAuthToken(null);
    sessionStorage.removeItem(TENANT_NAME_KEY);
    auth.logout();
  }, []);

  useEffect(() => {
    setOnUnauthorized(logout);
  }, [logout]);

  const login = useCallback(() => {
    auth.redirectToLogin();
  }, []);

  return { ...state, login, logout };
}

export { auth };
