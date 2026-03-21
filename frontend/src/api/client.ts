const BASE_URL = import.meta.env.VITE_API_URL || '/api/v1';

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
let isLoggingOut = false;

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

const REQUEST_TIMEOUT_MS = 30_000;

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

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...options,
      headers,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeoutId);
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const message = body?.error?.message || body?.detail || response.statusText;

    // Auto-logout on 401 — token expired or revoked
    if (response.status === 401 && authToken && !isLoggingOut) {
      isLoggingOut = true;
      authToken = null;
      clearSession();
      onUnauthorized?.();
      // Reset after a tick to allow any remaining concurrent requests to see the flag
      setTimeout(() => { isLoggingOut = false; }, 0);
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
