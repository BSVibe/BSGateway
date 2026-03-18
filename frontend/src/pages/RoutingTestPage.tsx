import { useEffect, useState } from 'react';
import { tenantsApi } from '../api/tenants';
import { rulesApi } from '../api/rules';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorBanner } from '../components/common/ErrorBanner';

const TENANT_ID = localStorage.getItem('bsg_tenant_id') || '';

interface TestMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

interface TestResult {
  selected_model: string;
  matched_rule: string | null;
  latency_ms: number;
  conditions_matched: Record<string, boolean>;
}

export function RoutingTestPage() {
  const [models, setModels] = useState<any[]>([]);
  const [loadingModels, setLoadingModels] = useState(true);
  const [selectedModel, setSelectedModel] = useState('');
  const [messages, setMessages] = useState<TestMessage[]>([{ role: 'user', content: '' }]);
  const [result, setResult] = useState<TestResult | null>(null);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadModelsAndRules();
  }, []);

  const loadModelsAndRules = async () => {
    try {
      const [m] = await Promise.all([
        tenantsApi.listModels(TENANT_ID),
        rulesApi.list(TENANT_ID),
      ]);
      setModels(m || []);
      if (m && m.length > 0) {
        setSelectedModel(m[0].model_name);
      }
    } catch {
      setError('Failed to load models and rules');
    } finally {
      setLoadingModels(false);
    }
  };

  const handleTest = async () => {
    if (!selectedModel || !messages[0]?.content) {
      setError('Model and at least one message required');
      return;
    }

    setTesting(true);
    setError(null);
    try {
      const res = await fetch(`/api/v1/tenants/${TENANT_ID}/rules/test`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('bsg_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          model: selectedModel,
          messages: messages.filter(m => m.content.trim()),
        }),
      });
      if (!res.ok) throw new Error('Test failed');
      const data = await res.json();
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Test failed');
    } finally {
      setTesting(false);
    }
  };

  if (loadingModels) return <LoadingSpinner />;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Route Testing</h2>
        <p className="text-gray-500 text-sm mt-1">Test routing logic before deployment</p>
      </div>

      {error && <ErrorBanner message={error} onRetry={() => setError(null)} />}

      {/* Test Form */}
      <div className="bg-white rounded-lg shadow p-6 space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">Model</label>
          <select
            value={selectedModel}
            onChange={(e) => setSelectedModel(e.target.value)}
            className="w-full border rounded-lg px-3 py-2 text-sm"
          >
            <option value="">Select model</option>
            {models.map((m) => (
              <option key={m.id} value={m.model_name}>
                {m.model_name} ({m.provider})
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">Messages</label>
          {messages.map((msg, i) => (
            <div key={i} className="mb-3 space-y-2">
              <div className="flex gap-2">
                <select
                  value={msg.role}
                  onChange={(e) => {
                    const newMsgs = [...messages];
                    newMsgs[i].role = e.target.value as any;
                    setMessages(newMsgs);
                  }}
                  className="w-24 border rounded-lg px-2 py-1 text-sm"
                >
                  <option value="user">user</option>
                  <option value="assistant">assistant</option>
                  <option value="system">system</option>
                </select>
                {messages.length > 1 && (
                  <button
                    onClick={() => setMessages(messages.filter((_, j) => j !== i))}
                    className="text-red-500 text-sm hover:text-red-700"
                  >
                    Remove
                  </button>
                )}
              </div>
              <textarea
                value={msg.content}
                onChange={(e) => {
                  const newMsgs = [...messages];
                  newMsgs[i].content = e.target.value;
                  setMessages(newMsgs);
                }}
                placeholder="Message content"
                className="w-full border rounded-lg px-3 py-2 text-sm"
                rows={2}
              />
            </div>
          ))}
          <button
            type="button"
            onClick={() => setMessages([...messages, { role: 'user', content: '' }])}
            className="text-blue-600 text-sm hover:text-blue-700"
          >
            + Add Message
          </button>
        </div>

        <button
          onClick={handleTest}
          disabled={testing || !selectedModel}
          className="bg-blue-600 text-white px-6 py-2 rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50"
        >
          {testing ? 'Testing...' : 'Test Routing'}
        </button>
      </div>

      {/* Results */}
      {result && (
        <div className="bg-white rounded-lg shadow p-6 space-y-4">
          <h3 className="text-lg font-semibold text-gray-900">Test Result</h3>
          
          <div className="grid grid-cols-2 gap-4">
            <div className="border rounded-lg p-4">
              <p className="text-xs text-gray-500 mb-1">Selected Model</p>
              <p className="font-mono text-sm font-semibold">{result.selected_model}</p>
            </div>
            <div className="border rounded-lg p-4">
              <p className="text-xs text-gray-500 mb-1">Matched Rule</p>
              <p className="font-mono text-sm font-semibold">{result.matched_rule || '(none)'}</p>
            </div>
            <div className="col-span-2 border rounded-lg p-4">
              <p className="text-xs text-gray-500 mb-1">Latency</p>
              <p className="text-sm font-mono">{result.latency_ms}ms</p>
            </div>
          </div>

          {Object.keys(result.conditions_matched).length > 0 && (
            <div className="border-t pt-4">
              <p className="text-sm font-semibold text-gray-700 mb-2">Matched Conditions</p>
              <div className="space-y-1">
                {Object.entries(result.conditions_matched).map(([condition, matched]) => (
                  <div key={condition} className="flex items-center gap-2 text-sm">
                    <span className={matched ? 'text-green-600' : 'text-gray-400'}>
                      {matched ? '✓' : '✗'}
                    </span>
                    <span className="font-mono text-xs">{condition}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
