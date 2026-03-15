import { useState } from 'react';
import { rulesApi } from '../api/rules';
import type { RuleTestResponse } from '../types/api';

const TENANT_ID = localStorage.getItem('bsg_tenant_id') || '';

export function RoutingTestPage() {
  const [prompt, setPrompt] = useState('');
  const [model, setModel] = useState('auto');
  const [result, setResult] = useState<RuleTestResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleTest = async () => {
    if (!prompt.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const resp = await rulesApi.test(TENANT_ID, {
        messages: [{ role: 'user', content: prompt }],
        model,
      });
      setResult(resp);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Test failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-gray-900">Routing Test</h2>

      <div className="bg-white rounded-lg shadow p-6 space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Model</label>
          <input
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="w-full border rounded-lg px-3 py-2 text-sm"
            placeholder="auto"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Prompt</label>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={4}
            className="w-full border rounded-lg px-3 py-2 text-sm"
            placeholder="Enter a test prompt..."
          />
        </div>
        <button
          onClick={handleTest}
          disabled={loading || !prompt.trim()}
          className="bg-blue-600 text-white px-6 py-2 rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? 'Testing...' : 'Test'}
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700 text-sm">
          {error}
        </div>
      )}

      {result && (
        <div className="bg-white rounded-lg shadow p-6 space-y-4">
          <h3 className="text-lg font-semibold">Result</h3>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-sm text-gray-500">Matched Rule</p>
              <p className="font-medium">
                {result.matched_rule
                  ? `${result.matched_rule.name} (P${result.matched_rule.priority})`
                  : 'No match'}
              </p>
            </div>
            <div>
              <p className="text-sm text-gray-500">Target Model</p>
              <p className="font-mono">{result.target_model ?? 'None'}</p>
            </div>
          </div>

          {result.context && (
            <div>
              <p className="text-sm text-gray-500 mb-2">Context</p>
              <div className="bg-gray-50 rounded-lg p-3 text-sm font-mono">
                <pre className="whitespace-pre-wrap">{JSON.stringify(result.context, null, 2)}</pre>
              </div>
            </div>
          )}

          {result.evaluation_trace.length > 0 && (
            <div>
              <p className="text-sm text-gray-500 mb-2">Evaluation Trace</p>
              <div className="bg-gray-50 rounded-lg p-3 text-sm font-mono">
                <pre className="whitespace-pre-wrap">{JSON.stringify(result.evaluation_trace, null, 2)}</pre>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
