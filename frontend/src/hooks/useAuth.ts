import { useCallback, useState } from 'react';
import { setAuthToken } from '../api/client';

interface AuthState {
  isAuthenticated: boolean;
  tenantId: string | null;
  tenantSlug: string | null;
  tenantName: string | null;
}

export function useAuth() {
  const [auth, setAuth] = useState<AuthState>(() => {
    // Token + tenant metadata stored in sessionStorage (tab-scoped, cleared on tab close)
    const savedToken = sessionStorage.getItem('bsg_token');
    if (savedToken) setAuthToken(savedToken);
    return {
      isAuthenticated: !!savedToken,
      tenantId: sessionStorage.getItem('bsg_tenant_id'),
      tenantSlug: sessionStorage.getItem('bsg_tenant_slug'),
      tenantName: sessionStorage.getItem('bsg_tenant_name'),
    };
  });

  const login = useCallback(
    (token: string, tenantId: string, tenantSlug: string, tenantName: string) => {
      setAuthToken(token);
      sessionStorage.setItem('bsg_token', token);
      sessionStorage.setItem('bsg_tenant_id', tenantId);
      sessionStorage.setItem('bsg_tenant_slug', tenantSlug);
      sessionStorage.setItem('bsg_tenant_name', tenantName);
      setAuth({ isAuthenticated: true, tenantId, tenantSlug, tenantName });
    },
    [],
  );

  const logout = useCallback(() => {
    setAuthToken(null);
    sessionStorage.removeItem('bsg_token');
    sessionStorage.removeItem('bsg_tenant_id');
    sessionStorage.removeItem('bsg_tenant_slug');
    sessionStorage.removeItem('bsg_tenant_name');
    setAuth({ isAuthenticated: false, tenantId: null, tenantSlug: null, tenantName: null });
  }, []);

  return { ...auth, login, logout };
}
