import { useState } from 'react';
import { api, ApiError } from '../api/client';

interface TokenResponse {
  token: string;
  tenant_id: string;
  tenant_slug: string;
  tenant_name: string;
  scopes: string[];
}

interface LoginPageProps {
  onLogin: (token: string, tenantId: string, tenantSlug: string, tenantName: string) => void;
}

export function LoginPage({ onLogin }: LoginPageProps) {
  const [apiKey, setApiKey] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!apiKey) {
      setError('API key is required');
      return;
    }

    setLoading(true);
    setError('');

    try {
      const data = await api.post<TokenResponse>('/auth/token', { api_key: apiKey });
      onLogin(data.token, data.tenant_id, data.tenant_slug, data.tenant_name);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError('Invalid API key');
      } else {
        setError(err instanceof Error ? err.message : 'Authentication failed');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100">
      <div className="bg-white rounded-lg shadow-lg p-8 w-full max-w-md">
        <h1 className="text-2xl font-bold text-center mb-2">BSGateway</h1>
        <p className="text-gray-500 text-center mb-6">LLM Routing Dashboard</p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">API Key</label>
            <div className="relative">
              <input
                type={showKey ? 'text' : 'password'}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="bsg_..."
                className="w-full border rounded-lg px-3 py-2 pr-16 text-sm font-mono"
                autoComplete="off"
                autoFocus
              />
              <button
                type="button"
                onClick={() => setShowKey(!showKey)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-400 hover:text-gray-600"
              >
                {showKey ? 'Hide' : 'Show'}
              </button>
            </div>
            <p className="text-xs text-gray-400 mt-1">
              Your API key identifies the tenant automatically.
            </p>
          </div>
          {error && <p className="text-red-600 text-sm">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 text-white py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? 'Signing in...' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  );
}
