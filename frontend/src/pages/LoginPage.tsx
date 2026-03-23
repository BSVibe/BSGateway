import { auth } from '../hooks/useAuth';

export function LoginPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100">
      <div className="bg-white rounded-lg shadow-lg p-8 w-full max-w-md text-center">
        <h1 className="text-2xl font-bold mb-1">BSGateway</h1>
        <p className="text-gray-500 mb-6">LLM Routing Dashboard</p>

        <p className="text-sm text-gray-600 mb-6">
          Complexity-based cost-optimized routing for LLM APIs.
          Manage models, rules, and usage from one place.
        </p>

        <button
          onClick={() => auth.redirectToLogin()}
          className="w-full bg-blue-600 text-white py-2 rounded-lg hover:bg-blue-700"
        >
          Sign in with BSVibe
        </button>
      </div>
    </div>
  );
}
