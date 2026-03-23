export interface BSVibeAuthConfig {
  /** URL of the BSVibe auth app, e.g. 'https://auth.bsvibe.dev' */
  authUrl: string;
  /** Callback path on the client app. Default: '/auth/callback' */
  callbackPath?: string;
}

export interface BSVibeUser {
  id: string;
  email: string;
  tenantId: string;
  role: string;
  accessToken: string;
  refreshToken: string;
  expiresAt: number;
}
