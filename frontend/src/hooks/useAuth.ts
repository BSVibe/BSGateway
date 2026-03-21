import { useCallback, useEffect, useState } from 'react';
import { SESSION_KEYS, clearSession, setAuthToken, setOnUnauthorized } from '../api/client';

interface AuthState {
  isAuthenticated: boolean;
  tenantId: string | null;
  tenantSlug: string | null;
  tenantName: string | null;
}

export function useAuth() {
  const [auth, setAuth] = useState<AuthState>(() => {
    // Token + tenant metadata stored in sessionStorage (tab-scoped, cleared on tab close)
    const savedToken = sessionStorage.getItem(SESSION_KEYS.token);
    if (savedToken) setAuthToken(savedToken);
    return {
      isAuthenticated: !!savedToken,
      tenantId: sessionStorage.getItem(SESSION_KEYS.tenantId),
      tenantSlug: sessionStorage.getItem(SESSION_KEYS.tenantSlug),
      tenantName: sessionStorage.getItem(SESSION_KEYS.tenantName),
    };
  });

  const logout = useCallback(() => {
    setAuthToken(null);
    clearSession();
    setAuth({ isAuthenticated: false, tenantId: null, tenantSlug: null, tenantName: null });
  }, []);

  // Register 401 handler so the API client delegates to auth state
  useEffect(() => {
    setOnUnauthorized(logout);
  }, [logout]);

  const login = useCallback(
    (token: string, tenantId: string, tenantSlug: string, tenantName: string) => {
      setAuthToken(token);
      sessionStorage.setItem(SESSION_KEYS.token, token);
      sessionStorage.setItem(SESSION_KEYS.tenantId, tenantId);
      sessionStorage.setItem(SESSION_KEYS.tenantSlug, tenantSlug);
      sessionStorage.setItem(SESSION_KEYS.tenantName, tenantName);
      setAuth({ isAuthenticated: true, tenantId, tenantSlug, tenantName });
    },
    [],
  );

  return { ...auth, login, logout };
}
