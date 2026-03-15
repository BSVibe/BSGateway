import { useCallback, useState } from 'react';
import { setAuthToken, getAuthToken } from '../api/client';

interface AuthState {
  isAuthenticated: boolean;
  tenantId: string | null;
}

export function useAuth() {
  const [auth, setAuth] = useState<AuthState>({
    isAuthenticated: !!getAuthToken(),
    tenantId: localStorage.getItem('bsg_tenant_id'),
  });

  const login = useCallback((apiKey: string, tenantId: string) => {
    setAuthToken(apiKey);
    localStorage.setItem('bsg_tenant_id', tenantId);
    setAuth({ isAuthenticated: true, tenantId });
  }, []);

  const logout = useCallback(() => {
    setAuthToken(null);
    localStorage.removeItem('bsg_tenant_id');
    setAuth({ isAuthenticated: false, tenantId: null });
  }, []);

  return { ...auth, login, logout };
}
