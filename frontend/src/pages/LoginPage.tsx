import { auth } from '../hooks/useAuth';

export function LoginPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950">
      <div className="bg-gray-900 rounded-lg border border-gray-700 p-8 w-full max-w-md text-center">
        <h1 className="text-2xl font-bold text-gray-50 mb-1">
          BS<span className="text-accent-500">Gateway</span>
        </h1>
        <p className="text-gray-500 mb-6">LLM Routing Dashboard</p>

        <p className="text-sm text-gray-400 mb-6">
          Complexity-based cost-optimized routing for LLM APIs.
          Manage models, rules, and usage from one place.
        </p>

        <button
          onClick={() => auth.redirectToLogin()}
          className="w-full bg-accent-500 text-gray-950 py-2 rounded-lg font-medium hover:bg-accent-400 transition-colors"
        >
          Sign in with BSVibe
        </button>
      </div>
    </div>
  );
}
