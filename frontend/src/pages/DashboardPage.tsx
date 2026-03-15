import { useMemo } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { usageApi } from '../api/usage';
import { rulesApi } from '../api/rules';
import { useApi } from '../hooks/useApi';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorBanner } from '../components/common/ErrorBanner';

const TENANT_ID = localStorage.getItem('bsg_tenant_id') || '';

export function DashboardPage() {
  const { data: usage, loading, error, refetch } = useApi(
    () => usageApi.get(TENANT_ID, 'week'),
    [TENANT_ID],
  );
  const { data: rules } = useApi(
    () => rulesApi.list(TENANT_ID),
    [TENANT_ID],
  );

  const activeRules = useMemo(
    () => rules?.filter((r) => r.is_active).length ?? 0,
    [rules],
  );

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onRetry={refetch} />;

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-gray-900">Dashboard</h2>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-white rounded-lg shadow p-6">
          <p className="text-sm text-gray-500">Total Requests (7d)</p>
          <p className="text-3xl font-bold text-gray-900">
            {usage?.total_requests.toLocaleString() ?? 0}
          </p>
        </div>
        <div className="bg-white rounded-lg shadow p-6">
          <p className="text-sm text-gray-500">Total Tokens (7d)</p>
          <p className="text-3xl font-bold text-gray-900">
            {usage?.total_tokens.toLocaleString() ?? 0}
          </p>
        </div>
        <div className="bg-white rounded-lg shadow p-6">
          <p className="text-sm text-gray-500">Active Rules</p>
          <p className="text-3xl font-bold text-gray-900">{activeRules}</p>
        </div>
      </div>

      {/* Usage Chart */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold mb-4">Requests (7 days)</h3>
        {usage && usage.daily_breakdown.length > 0 ? (
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={usage.daily_breakdown}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" />
              <YAxis />
              <Tooltip />
              <Line
                type="monotone"
                dataKey="requests"
                stroke="#3b82f6"
                strokeWidth={2}
              />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-gray-500 text-center py-8">No usage data yet</p>
        )}
      </div>

      {/* Model breakdown */}
      {usage && Object.keys(usage.by_model).length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold mb-4">By Model</h3>
          <div className="space-y-2">
            {Object.entries(usage.by_model).map(([model, stats]) => (
              <div key={model} className="flex items-center justify-between py-2 border-b border-gray-100">
                <span className="font-mono text-sm">{model}</span>
                <div className="text-sm text-gray-600">
                  {stats.requests.toLocaleString()} requests / {stats.tokens.toLocaleString()} tokens
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
