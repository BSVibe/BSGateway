import type { BSVibeAuthConfig, BSVibeUser } from './types';
import { parseToken } from './token';
import {
  saveSession,
  getSession,
  clearSession,
  isTokenExpired,
  saveState,
  getAndClearState,
} from './session';

function generateState(): string {
  const array = new Uint8Array(32);
  crypto.getRandomValues(array);
  return Array.from(array, (b) => b.toString(16).padStart(2, '0')).join('');
}

export class BSVibeAuth {
  private authUrl: string;
  private callbackPath: string;

  constructor(config: BSVibeAuthConfig) {
    this.authUrl = config.authUrl.replace(/\/+$/, '');
    this.callbackPath = config.callbackPath ?? '/auth/callback';
  }

  /** Redirect the user to the BSVibe login page */
  redirectToLogin(): void {
    const state = generateState();
    saveState(state);

    const redirectUri = `${window.location.origin}${this.callbackPath}`;
    const loginUrl = new URL('/login', this.authUrl);
    loginUrl.searchParams.set('redirect_uri', redirectUri);
    loginUrl.searchParams.set('state', state);

    window.location.href = loginUrl.toString();
  }

  /** Redirect the user to the BSVibe signup page */
  redirectToSignup(): void {
    const state = generateState();
    saveState(state);

    const redirectUri = `${window.location.origin}${this.callbackPath}`;
    const signupUrl = new URL('/signup', this.authUrl);
    signupUrl.searchParams.set('redirect_uri', redirectUri);
    signupUrl.searchParams.set('state', state);

    window.location.href = signupUrl.toString();
  }

  /**
   * SSO check via redirect. If no local session exists, redirects to auth server.
   * Returns user if already authenticated or if tokens are in the URL hash.
   * Returns null if SSO check already failed (sso_error in URL).
   * Returns 'redirect' if redirecting to auth server (page will navigate away).
   */
  checkSession(): BSVibeUser | null | 'redirect' {
    // 1. Check local storage
    const existing = this.getUser();
    if (existing) return existing;

    // 2. Check if we just returned from SSO with tokens in hash
    const hash = window.location.hash.substring(1);
    if (hash) {
      const params = new URLSearchParams(hash);
      const accessToken = params.get('access_token');
      const refreshToken = params.get('refresh_token');
      if (accessToken && refreshToken) {
        try {
          const user = parseToken(accessToken, refreshToken);
          saveSession(user);
          history.replaceState(null, '', window.location.pathname + window.location.search);
          return user;
        } catch { /* fall through */ }
      }
    }

    // 3. Check if SSO already failed
    const searchParams = new URLSearchParams(window.location.search);
    if (searchParams.get('sso_error')) {
      // Clean up the error param from URL
      searchParams.delete('sso_error');
      const cleanSearch = searchParams.toString();
      const cleanUrl = window.location.pathname + (cleanSearch ? `?${cleanSearch}` : '');
      history.replaceState(null, '', cleanUrl);
      return null;
    }

    // 4. Redirect to auth server for SSO check
    const currentUrl = window.location.href.split('#')[0];
    window.location.href = `${this.authUrl}/api/silent-check?redirect_uri=${encodeURIComponent(currentUrl)}`;
    return 'redirect';
  }

  /** Extract tokens from the callback URL fragment. Returns user on success, null on failure. */
  handleCallback(): BSVibeUser | null {
    const hash = window.location.hash.substring(1);
    if (!hash) return null;

    const params = new URLSearchParams(hash);
    const accessToken = params.get('access_token');
    const refreshToken = params.get('refresh_token');
    const returnedState = params.get('state');

    if (!accessToken || !refreshToken) return null;

    const savedState = getAndClearState();
    if (savedState && returnedState !== savedState) {
      console.error('BSVibeAuth: state mismatch — possible CSRF attack');
      return null;
    }

    try {
      const user = parseToken(accessToken, refreshToken);
      saveSession(user);
      history.replaceState(null, '', window.location.pathname + window.location.search);
      return user;
    } catch {
      return null;
    }
  }

  /** Check if the user is currently authenticated (token exists and not expired) */
  isAuthenticated(): boolean {
    return this.getUser() !== null;
  }

  /** Get the current user, or null if not authenticated */
  getUser(): BSVibeUser | null {
    const user = getSession();
    if (!user) return null;
    if (isTokenExpired(user.expiresAt)) {
      clearSession();
      return null;
    }
    return user;
  }

  /** Get the current access token for API calls */
  getToken(): string | null {
    return this.getUser()?.accessToken ?? null;
  }

  /** Clear the session and redirect to auth-app's logout page */
  logout(): void {
    clearSession();
    const redirectUri = window.location.origin;
    window.location.href = `${this.authUrl}/logout?redirect_uri=${encodeURIComponent(redirectUri)}`;
  }
}
