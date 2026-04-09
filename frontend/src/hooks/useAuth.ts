import { useCallback, useEffect, useState } from 'react';
import { BSVibeAuth } from '../lib/bsvibe-auth';
import { api, setAuthToken, setOnUnauthorized } from '../api/client';

const AUTH_URL = import.meta.env.VITE_AUTH_URL || 'https://auth.bsvibe.dev';
const TENANT_NAME_KEY = 'bsvibe_tenant_name';

const auth = new BSVibeAuth({
  authUrl: AUTH_URL,
  callbackPath: '/auth/callback',
});

interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
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
      isLoading: !user, // loading if no local session (will try silent SSO)
      tenantId: user?.tenantId ?? null,
      tenantName: sessionStorage.getItem(TENANT_NAME_KEY),
      role: user?.role ?? null,
      email: user?.email ?? null,
    };
  });

  // Silent SSO check on init when no local session.
  // This must run in an effect (not in the lazy state initializer) because
  // `auth.checkSession()` may set `window.location.href` to redirect to the
  // auth server — a side effect that would double-fire under StrictMode if
  // placed in render. The setState calls below reflect the result of
  // integrating with that external (browser-history) state, which is the
  // canonical use case for the eslint escape hatch on `set-state-in-effect`.
  useEffect(() => {
    if (state.isAuthenticated) return;

    const result = auth.checkSession();
    if (result === 'redirect') return; // page is navigating away
    if (result) {
      setAuthToken(result.accessToken);
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setState({
        isAuthenticated: true,
        isLoading: false,
        tenantId: result.tenantId,
        tenantName: sessionStorage.getItem(TENANT_NAME_KEY),
        role: result.role,
        email: result.email,
      });
    } else {
      setState((prev) => ({ ...prev, isLoading: false }));
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

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

  const signup = useCallback(() => {
    auth.redirectToSignup();
  }, []);

  return { ...state, login, signup, logout };
}

export { auth };
