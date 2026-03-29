import { useEffect, useState } from 'react';
import {
  LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from 'recharts';
import { api } from '../api/client';
import { useAuth } from '../hooks/useAuth';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorBanner } from '../components/common/ErrorBanner';
import type { UsageResponse } from '../types/api';

const COLORS = ['#f59e0b', '#ef4444', '#10b981', '#3b82f6', '#8b5cf6', '#ec4899'];

export function UsagePage() {
  const { tenantId } = useAuth();
  const tid = tenantId || '';
  const [period, setPeriod] = useState<'day' | 'week' | 'month'>('week');
  const [data, setData] = useState<UsageResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadUsage();
  }, [period]);

  const loadUsage = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<UsageResponse>(
        `/tenants/${tid}/usage?period=${period}`
      );
      setData(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load usage data');
    } finally {
      setLoading(false);
    }
  };

  if (loading) return <LoadingSpinner />;

  const dailyData = data?.daily_breakdown
    ? data.daily_breakdown.map((d) => ({
      date: new Date(d.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
      requests: d.requests,
    }))
    : [];

  const modelData = data?.by_model
    ? Object.entries(data.by_model).map(([model, usage]) => ({
      name: model,
      value: usage.requests,
    }))
    : [];

  const ruleData = data?.by_rule
    ? Object.entries(data.by_rule).map(([rule, requests]) => ({
      name: rule,
      requests,
    }))
    : [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-50">Usage Analytics</h2>
          <p className="text-gray-500 text-sm mt-1">Routing traffic and token consumption</p>
        </div>
        <select
          value={period}
          onChange={(e) => setPeriod(e.target.value as 'day' | 'week' | 'month')}
          className="border border-gray-700 rounded-lg px-3 py-2 text-sm bg-gray-900"
        >
          <option value="day">Today</option>
          <option value="week">Last 7 days</option>
          <option value="month">Last 30 days</option>
        </select>
      </div>

      {error && <ErrorBanner message={error} onRetry={loadUsage} />}

      {/* Summary Stats */}
      {data && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="bg-gray-900 rounded-lg border border-gray-700 p-6">
            <p className="text-gray-400 text-sm">Total Requests</p>
            <p className="text-3xl font-bold text-gray-50 mt-2">{data.total_requests}</p>
          </div>
          <div className="bg-gray-900 rounded-lg border border-gray-700 p-6">
            <p className="text-gray-400 text-sm">Total Tokens</p>
            <p className="text-3xl font-bold text-gray-50 mt-2">{data.total_tokens.toLocaleString()}</p>
          </div>
          <div className="bg-gray-900 rounded-lg border border-gray-700 p-6">
            <p className="text-gray-400 text-sm">Models Used</p>
            <p className="text-3xl font-bold text-gray-50 mt-2">
              {Object.keys(data.by_model).length}
            </p>
          </div>
        </div>
      )}

      {/* Daily Trend */}
      {dailyData.length > 0 && (
        <div className="bg-gray-900 rounded-lg border border-gray-700 p-6">
          <h3 className="text-lg font-semibold text-gray-50 mb-4">Daily Requests</h3>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={dailyData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2a2d42" />
              <XAxis dataKey="date" stroke="#5a5f7d" tick={{ fill: '#8187a8' }} />
              <YAxis stroke="#5a5f7d" tick={{ fill: '#8187a8' }} />
              <Tooltip
                contentStyle={{ backgroundColor: '#181926', border: '1px solid #2a2d42', borderRadius: '8px', color: '#f2f3f7' }}
                labelStyle={{ color: '#a8adc6' }}
              />
              <Line
                type="monotone"
                dataKey="requests"
                stroke="#f59e0b"
                dot={{ fill: '#f59e0b' }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* By Model & By Rule */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {modelData.length > 0 && (
          <div className="bg-gray-900 rounded-lg border border-gray-700 p-6">
            <h3 className="text-lg font-semibold text-gray-50 mb-4">Traffic by Model</h3>
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={modelData}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={({ name, value }) => `${name}: ${value}`}
                  outerRadius={80}
                  fill="#8884d8"
                  dataKey="value"
                >
                  {modelData.map((_, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ backgroundColor: '#181926', border: '1px solid #2a2d42', borderRadius: '8px', color: '#f2f3f7' }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        )}

        {ruleData.length > 0 && (
          <div className="bg-gray-900 rounded-lg border border-gray-700 p-6">
            <h3 className="text-lg font-semibold text-gray-50 mb-4">Traffic by Rule</h3>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={ruleData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2a2d42" />
                <XAxis dataKey="name" stroke="#5a5f7d" tick={{ fill: '#8187a8' }} />
                <YAxis stroke="#5a5f7d" tick={{ fill: '#8187a8' }} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#181926', border: '1px solid #2a2d42', borderRadius: '8px', color: '#f2f3f7' }}
                />
                <Bar dataKey="requests" fill="#f59e0b" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  );
}
