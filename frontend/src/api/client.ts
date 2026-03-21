const BASE_URL = '/api/v1';

// Session storage keys — single source of truth
export const SESSION_KEYS = {
  token: 'bsg_token',
  tenantId: 'bsg_tenant_id',
  tenantSlug: 'bsg_tenant_slug',
  tenantName: 'bsg_tenant_name',
} as const;

/** Clear all session data (shared by logout + 401 handler). */
export function clearSession() {
  Object.values(SESSION_KEYS).forEach((k) => sessionStorage.removeItem(k));
}

let authToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setAuthToken(token: string | null) {
  authToken = token;
}

export function getAuthToken(): string | null {
  return authToken;
}

/** Register a callback for 401 responses (called once, then ignored for concurrent requests). */
export function setOnUnauthorized(cb: () => void) {
  onUnauthorized = cb;
}

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };

  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`;
  }

  const response = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const message = body?.error?.message || body?.detail || response.statusText;

    // Auto-logout on 401 — token expired or revoked
    if (response.status === 401 && authToken) {
      authToken = null;
      clearSession();
      onUnauthorized?.();
      onUnauthorized = null; // prevent duplicate calls from concurrent requests
    }

    throw new ApiError(response.status, message);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json();
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: body ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
};

export { ApiError };
