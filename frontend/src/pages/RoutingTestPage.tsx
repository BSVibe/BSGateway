import { useEffect, useState } from 'react';
import { tenantsApi } from '../api/tenants';
import { SESSION_KEYS } from '../api/client';
import { rulesApi } from '../api/rules';
import type { TenantModel } from '../types/api';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorBanner } from '../components/common/ErrorBanner';

interface TestMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

interface MatchedRule {
  id: string;
  name: string;
  priority: number;
}

interface TestResult {
  matched_rule: MatchedRule | null;
  target_model: string | null;
  evaluation_trace: Record<string, unknown>[];
  context: Record<string, unknown>;
}

export function RoutingTestPage() {
  const tenantId = sessionStorage.getItem(SESSION_KEYS.tenantId) || '';
  const [models, setModels] = useState<TenantModel[]>([]);
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
      const m = await tenantsApi.listModels(tenantId);
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
      const data = await rulesApi.test(tenantId, {
        model: selectedModel,
        messages: messages.filter(m => m.content.trim()),
      });
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
                    newMsgs[i].role = e.target.value as 'user' | 'assistant' | 'system';
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
              <p className="text-xs text-gray-500 mb-1">Target Model</p>
              <p className="font-mono text-sm font-semibold">{result.target_model || '(none)'}</p>
            </div>
            <div className="border rounded-lg p-4">
              <p className="text-xs text-gray-500 mb-1">Matched Rule</p>
              <p className="font-mono text-sm font-semibold">
                {result.matched_rule ? `${result.matched_rule.name} (priority: ${result.matched_rule.priority})` : '(none)'}
              </p>
            </div>
          </div>

          {result.context && Object.keys(result.context).length > 0 && (
            <div className="border-t pt-4">
              <p className="text-sm font-semibold text-gray-700 mb-2">Request Context</p>
              <div className="grid grid-cols-2 gap-2">
                {Object.entries(result.context).map(([key, value]) => (
                  value !== null && value !== undefined && (
                    <div key={key} className="flex items-center gap-2 text-sm">
                      <span className="text-gray-500 text-xs">{key}:</span>
                      <span className="font-mono text-xs">{String(value)}</span>
                    </div>
                  )
                ))}
              </div>
            </div>
          )}

          {result.evaluation_trace && result.evaluation_trace.length > 0 && (
            <div className="border-t pt-4">
              <p className="text-sm font-semibold text-gray-700 mb-2">Evaluation Trace</p>
              <div className="space-y-1">
                {result.evaluation_trace.map((entry, i) => {
                  const safeEntry: Record<string, unknown> = {};
                  for (const [k, v] of Object.entries(entry)) {
                    safeEntry[k] = typeof v === 'string' ? v : JSON.stringify(v);
                  }
                  return (
                    <div key={i} className="text-xs font-mono bg-gray-50 rounded px-2 py-1 whitespace-pre-wrap break-all">
                      {JSON.stringify(safeEntry)}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
