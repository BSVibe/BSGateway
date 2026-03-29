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
        <h2 className="text-2xl font-bold text-gray-50">Dashboard</h2>
        <p className="text-gray-500 text-sm mt-1">Routing overview and metrics</p>
      </div>

      {error && <ErrorBanner message={error} onRetry={loadDashboard} />}

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((stat) => (
          <div
            key={stat.label}
            className="bg-gray-900 rounded-lg p-6 border border-gray-700 border-l-4 border-l-accent-500"
          >
            <p className="text-gray-400 text-sm font-medium">{stat.label}</p>
            <p className="text-3xl font-bold text-gray-50 mt-2">{stat.value}</p>
            {stat.subtext && <p className="text-xs text-gray-500 mt-1">{stat.subtext}</p>}
          </div>
        ))}
      </div>

      {/* Usage Trend */}
      {usageData.length > 0 && (
        <div className="bg-gray-900 rounded-lg border border-gray-700 p-6">
          <h3 className="text-lg font-semibold text-gray-50 mb-4">Request Trend (7 days)</h3>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={usageData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2a2d42" />
              <XAxis dataKey="date" stroke="#5a5f7d" tick={{ fill: '#8187a8' }} />
              <YAxis stroke="#5a5f7d" tick={{ fill: '#8187a8' }} />
              <Tooltip
                contentStyle={{ backgroundColor: '#181926', border: '1px solid #2a2d42', borderRadius: '8px', color: '#f2f3f7' }}
                labelStyle={{ color: '#a8adc6' }}
              />
              <Legend wrapperStyle={{ color: '#a8adc6' }} />
              <Line
                type="monotone"
                dataKey="requests"
                stroke="#f59e0b"
                dot={{ fill: '#f59e0b' }}
                name="Requests"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Quick Info */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-gray-900 rounded-lg p-6 border border-gray-700">
          <h3 className="font-semibold text-gray-50">Getting Started</h3>
          <ul className="text-sm text-gray-400 mt-2 space-y-1">
            <li className="flex items-center gap-2"><span className="text-accent-500">&#10003;</span> Register your LLM models in the Models tab</li>
            <li className="flex items-center gap-2"><span className="text-accent-500">&#10003;</span> Create routing rules to control traffic</li>
            <li className="flex items-center gap-2"><span className="text-accent-500">&#10003;</span> Test your rules before enabling</li>
            <li className="flex items-center gap-2"><span className="text-accent-500">&#10003;</span> Monitor usage metrics here</li>
          </ul>
        </div>

        <div className="bg-gray-900 rounded-lg p-6 border border-gray-700">
          <h3 className="font-semibold text-gray-50">API Integration</h3>
          <p className="text-sm text-gray-400 mt-2">
            Use the chat completions endpoint at <code className="bg-gray-800 px-2 py-1 rounded text-xs font-mono text-accent-500">/api/v1/chat/completions</code>
          </p>
          <p className="text-xs text-gray-500 mt-2">
            Authenticate with your Supabase JWT as a Bearer token in the Authorization header.
          </p>
        </div>
      </div>
    </div>
  );
}
