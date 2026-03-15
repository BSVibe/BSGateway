import { useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { usageApi } from '../api/usage';
import { useApi } from '../hooks/useApi';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorBanner } from '../components/common/ErrorBanner';

const TENANT_ID = localStorage.getItem('bsg_tenant_id') || '';

export function UsagePage() {
  const [period, setPeriod] = useState<'day' | 'week' | 'month'>('week');
  const { data: usage, loading, error, refetch } = useApi(
    () => usageApi.get(TENANT_ID, period),
    [TENANT_ID, period],
  );

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onRetry={refetch} />;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-gray-900">Usage</h2>
        <div className="flex gap-1 bg-gray-200 rounded-lg p-1">
          {(['day', 'week', 'month'] as const).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`px-3 py-1 rounded text-sm ${
                period === p ? 'bg-white shadow font-medium' : 'text-gray-600'
              }`}
            >
              {p.charAt(0).toUpperCase() + p.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-white rounded-lg shadow p-6">
          <p className="text-sm text-gray-500">Total Requests</p>
          <p className="text-3xl font-bold">{usage?.total_requests.toLocaleString() ?? 0}</p>
        </div>
        <div className="bg-white rounded-lg shadow p-6">
          <p className="text-sm text-gray-500">Total Tokens</p>
          <p className="text-3xl font-bold">{usage?.total_tokens.toLocaleString() ?? 0}</p>
        </div>
      </div>

      {/* Daily Chart */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold mb-4">Daily Requests</h3>
        {usage && usage.daily_breakdown.length > 0 ? (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={usage.daily_breakdown}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="requests" fill="#3b82f6" />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-gray-500 text-center py-8">No data for this period</p>
        )}
      </div>

      {/* By Model */}
      {usage && Object.keys(usage.by_model).length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold mb-4">By Model</h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left">
                <th className="px-4 py-2 font-medium text-gray-600">Model</th>
                <th className="px-4 py-2 font-medium text-gray-600">Requests</th>
                <th className="px-4 py-2 font-medium text-gray-600">Tokens</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(usage.by_model).map(([model, stats]) => (
                <tr key={model} className="border-b border-gray-100">
                  <td className="px-4 py-2 font-mono">{model}</td>
                  <td className="px-4 py-2">{stats.requests.toLocaleString()}</td>
                  <td className="px-4 py-2">{stats.tokens.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* By Rule */}
      {usage && Object.keys(usage.by_rule).length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold mb-4">By Rule</h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left">
                <th className="px-4 py-2 font-medium text-gray-600">Rule</th>
                <th className="px-4 py-2 font-medium text-gray-600">Matches</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(usage.by_rule).map(([rule, count]) => (
                <tr key={rule} className="border-b border-gray-100">
                  <td className="px-4 py-2">{rule}</td>
                  <td className="px-4 py-2">{count.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
