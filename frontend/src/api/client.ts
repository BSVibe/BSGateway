import { getAccessToken, clearTokenCache } from '../hooks/useAuth';

const API_PATH_PREFIX = '/api/v1';

/**
 * Build BASE_URL for API requests.
 *
 * - Dev (no env var): falls back to '/api/v1' (Next.js rewrites in
 *   `next.config.mjs` forward /api/* to the backend)
 * - Prod: NEXT_PUBLIC_API_URL should be the backend origin, e.g.
 *   'https://api-gateway.bsvibe.dev'. The path prefix '/api/v1' is
 *   appended automatically if not already present.
 */
function buildBaseUrl(): string {
  const raw =
    (typeof process !== 'undefined' && process.env?.NEXT_PUBLIC_API_URL) ||
    '';
  if (!raw) return API_PATH_PREFIX;

  const url = raw.endsWith('/') ? raw.slice(0, -1) : raw;
  return url.endsWith(API_PATH_PREFIX) ? url : `${url}${API_PATH_PREFIX}`;
}

const BASE_URL = buildBaseUrl();

let onUnauthorized: (() => void) | null = null;
let isLoggingOut = false;

/** Register a callback for 401 responses (called once, then ignored for concurrent requests). */
export function setOnUnauthorized(cb: () => void) {
  onUnauthorized = cb;
}

export function resetLogoutFlag() {
  isLoggingOut = false;
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

  const token = await getAccessToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
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

    if (response.status === 401 && !isLoggingOut) {
      isLoggingOut = true;
      clearTokenCache();
      onUnauthorized?.();
    }

    throw new ApiError(response.status, message);
  }

  if (response.status === 204) {
    return undefined as unknown as T;
  }

  return response.json();
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: body ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
};

export { ApiError };
