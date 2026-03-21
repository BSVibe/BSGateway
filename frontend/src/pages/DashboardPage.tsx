import { useEffect, useState } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { rulesApi } from '../api/rules';
import { tenantsApi } from '../api/tenants';
import { usageApi } from '../api/usage';
import { useAuth } from '../hooks/useAuth';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorBanner } from '../components/common/ErrorBanner';

interface Stat {
  label: string;
  value: string | number;
  subtext?: string;
}

interface UsageData {
  date: string;
  requests: number;
}

export function DashboardPage() {
  const { tenantId } = useAuth();
  const tid = tenantId || '';
  const [stats, setStats] = useState<Stat[]>([]);
  const [usageData, setUsageData] = useState<UsageData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadDashboard();
  }, []);

  const loadDashboard = async () => {
    setLoading(true);
    setError(null);
    try {
      const [rules, models, usage] = await Promise.all([
        rulesApi.list(tid).catch(() => []),
        tenantsApi.listModels(tid).catch(() => []),
        usageApi.get(tid, 'week').catch(() => null),
      ]);

      const ruleCount = Array.isArray(rules) ? rules.length : 0;
      const modelCount = Array.isArray(models) ? models.length : 0;
      const totalRequests = usage?.total_requests || 0;
      const totalTokens = usage?.total_tokens || 0;

      setStats([
        { label: 'Active Rules', value: ruleCount, subtext: 'routing policies' },
        { label: 'Registered Models', value: modelCount, subtext: 'LLM endpoints' },
        { label: 'Daily Requests', value: totalRequests, subtext: 'this week' },
        { label: 'Total Tokens', value: totalTokens.toLocaleString() },
      ]);

      // Format usage data for chart
      if (usage?.daily_breakdown) {
        const chartData = usage.daily_breakdown.map((d) => ({
          date: new Date(d.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
          requests: d.requests,
        }));
        setUsageData(chartData);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load dashboard');
    } finally {
      setLoading(false);
    }
  };

  if (loading) return <LoadingSpinner />;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Dashboard</h2>
        <p className="text-gray-500 text-sm mt-1">Routing overview and metrics</p>
      </div>

      {error && <ErrorBanner message={error} onRetry={loadDashboard} />}

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((stat) => (
          <div
            key={stat.label}
            className="bg-white rounded-lg shadow p-6 border-l-4 border-blue-500"
          >
            <p className="text-gray-500 text-sm font-medium">{stat.label}</p>
            <p className="text-3xl font-bold text-gray-900 mt-2">{stat.value}</p>
            {stat.subtext && <p className="text-xs text-gray-400 mt-1">{stat.subtext}</p>}
          </div>
        ))}
      </div>

      {/* Usage Trend */}
      {usageData.length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Request Trend (7 days)</h3>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={usageData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" />
              <YAxis />
              <Tooltip />
              <Legend />
              <Line
                type="monotone"
                dataKey="requests"
                stroke="#2563eb"
                dot={{ fill: '#2563eb' }}
                name="Requests"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Quick Info */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-blue-50 rounded-lg p-6 border border-blue-100">
          <h3 className="font-semibold text-blue-900">Getting Started</h3>
          <ul className="text-sm text-blue-800 mt-2 space-y-1">
            <li>✓ Register your LLM models in the Models tab</li>
            <li>✓ Create routing rules to control traffic</li>
            <li>✓ Test your rules before enabling</li>
            <li>✓ Monitor usage metrics here</li>
          </ul>
        </div>

        <div className="bg-green-50 rounded-lg p-6 border border-green-100">
          <h3 className="font-semibold text-green-900">API Integration</h3>
          <p className="text-sm text-green-800 mt-2">
            Use the chat completions endpoint at <code className="bg-white px-2 py-1 rounded text-xs font-mono">/api/v1/chat/completions</code>
          </p>
          <p className="text-xs text-green-700 mt-2">
            Authenticate with your API key as a Bearer token in the Authorization header.
          </p>
        </div>
      </div>
    </div>
  );
}
