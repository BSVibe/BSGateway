import type { BSVibeUser } from './types';

const USER_KEY = 'bsvibe_user';
const STATE_KEY = 'bsvibe_auth_state';

export function saveSession(user: BSVibeUser): void {
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function getSession(): BSVibeUser | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;

  try {
    return JSON.parse(raw) as BSVibeUser;
  } catch {
    return null;
  }
}

export function clearSession(): void {
  localStorage.removeItem(USER_KEY);
}

export function isTokenExpired(expiresAt: number): boolean {
  return Date.now() / 1000 >= expiresAt - 30;
}

export function saveState(state: string): void {
  sessionStorage.setItem(STATE_KEY, state);
}

export function getAndClearState(): string | null {
  const state = sessionStorage.getItem(STATE_KEY);
  sessionStorage.removeItem(STATE_KEY);
  return state;
}
