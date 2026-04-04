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

  /** Silent SSO check via hidden iframe. Returns user if session exists, null otherwise. */
  async checkSession(): Promise<BSVibeUser | null> {
    // Check local storage first
    const existing = this.getUser();
    if (existing) return existing;

    return new Promise((resolve) => {
      const timeout = 5000;
      let settled = false;

      const iframe = document.createElement('iframe');
      iframe.style.display = 'none';
      iframe.src = `${this.authUrl}/api/silent-check`;

      const cleanup = () => {
        if (settled) return;
        settled = true;
        window.removeEventListener('message', onMessage);
        clearTimeout(timer);
        if (iframe.parentNode) {
          iframe.parentNode.removeChild(iframe);
        }
      };

      const onMessage = (event: MessageEvent) => {
        if (!event.data || event.data.type !== 'bsvibe-auth') return;

        cleanup();

        if (event.data.error) {
          resolve(null);
          return;
        }

        const { access_token, refresh_token } = event.data;
        if (!access_token || !refresh_token) {
          resolve(null);
          return;
        }

        try {
          const user = parseToken(access_token, refresh_token);
          saveSession(user);
          resolve(user);
        } catch {
          resolve(null);
        }
      };

      const timer = setTimeout(() => {
        cleanup();
        resolve(null);
      }, timeout);

      window.addEventListener('message', onMessage);
      document.body.appendChild(iframe);
    });
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
