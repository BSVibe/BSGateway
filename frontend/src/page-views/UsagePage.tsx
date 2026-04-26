'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Area, AreaChart
} from 'recharts';
import { api } from '../api/client';
import { useAuth } from '../hooks/useAuth';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorBanner } from '../components/common/ErrorBanner';
import type { UsageResponse } from '../types/api';

const COLORS = ['#f59e0b', '#8fd5ff', '#d8c3ad', '#d97706', '#10b981', '#ec4899'];

const PERIOD_LABELS = {
  day: 'Today',
  week: 'Last 7 days',
  month: 'Last 30 days',
};

export function UsagePage() {
  const { tenantId } = useAuth();
  const tid = tenantId || '';
  const [period, setPeriod] = useState<'day' | 'week' | 'month'>('week');
  const [data, setData] = useState<UsageResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadUsage = useCallback(async () => {
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
  }, [tid, period]);

  useEffect(() => {
    loadUsage();
  }, [loadUsage]);

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

  const totalRequests = data?.total_requests ?? 0;
  const totalTokens = data?.total_tokens ?? 0;
  const modelCount = data ? Object.keys(data.by_model).length : 0;

  return (
    <div className="p-8 min-h-screen space-y-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 mb-12">
        <div>
          <h2 className="text-4xl font-extrabold tracking-tight text-on-surface mb-2">Analytics Dashboard</h2>
          <p className="text-on-surface-variant opacity-70">Monitor performance metrics and operational costs across all active gateways.</p>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex bg-surface-container-low p-1 rounded-xl border border-outline-variant/15">
            {(['day', 'week', 'month'] as const).map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={`px-4 py-1.5 text-xs font-bold rounded-lg transition-colors ${
                  period === p
                    ? 'bg-surface-container-highest text-primary'
                    : 'text-on-surface-variant hover:text-on-surface'
                }`}
              >
                {PERIOD_LABELS[p]}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && <ErrorBanner message={error} onRetry={loadUsage} />}

      {/* Main Charts Area (Bento Grid) */}
      {data && (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-12">
            {/* Large Area Chart */}
            <div className="lg:col-span-2 bg-surface-container-low rounded-[2rem] p-8 border border-outline-variant/15 relative overflow-hidden">
              <div className="flex justify-between items-start mb-12">
                <div>
                  <h3 className="text-lg font-bold text-on-surface mb-1">Daily Request Trend</h3>
                  <p className="text-sm text-on-surface-variant opacity-60">{PERIOD_LABELS[period]}</p>
                </div>
                <div className="text-right">
                  <div className="text-3xl font-black text-primary tracking-tighter">{totalRequests.toLocaleString()}</div>
                  <div className="text-xs text-on-surface-variant">total requests</div>
                </div>
              </div>
              {dailyData.length > 0 ? (
                <ResponsiveContainer width="100%" height={256}>
                  <AreaChart data={dailyData} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
                    <defs>
                      <linearGradient id="usageGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#343439" vertical={false} />
                    <XAxis dataKey="date" stroke="#343439" tick={{ fill: '#d8c3ad', fontSize: 10 }} tickLine={false} />
                    <YAxis stroke="#343439" tick={{ fill: '#d8c3ad', fontSize: 10 }} tickLine={false} axisLine={false} />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#1f1f24', border: '1px solid #534434', borderRadius: '12px', color: '#e3e2e8', fontSize: '12px' }}
                      labelStyle={{ color: '#d8c3ad' }}
                      cursor={{ stroke: '#534434' }}
                    />
                    <Area
                      type="monotone"
                      dataKey="requests"
                      stroke="#f59e0b"
                      strokeWidth={3}
                      fill="url(#usageGradient)"
                      dot={{ fill: '#f59e0b', r: 4, strokeWidth: 0 }}
                      activeDot={{ fill: '#f59e0b', r: 6, strokeWidth: 0 }}
                      name="Requests"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-[256px] flex flex-col items-center justify-center">
                  <span className="material-symbols-outlined text-4xl text-on-surface-variant/30 mb-3">show_chart</span>
                  <p className="text-sm text-on-surface-variant">No daily data available</p>
                </div>
              )}
            </div>

            {/* Donut Chart: Model Distribution */}
            <div className="bg-surface-container-low rounded-[2rem] p-8 border border-outline-variant/15 flex flex-col justify-between">
              <div>
                <h3 className="text-lg font-bold text-on-surface mb-1">Traffic by Model</h3>
                <p className="text-sm text-on-surface-variant opacity-60">Request distribution</p>
              </div>
              {modelData.length > 0 ? (
                <>
                  <div className="relative flex items-center justify-center py-8">
                    <ResponsiveContainer width="100%" height={180}>
                      <PieChart>
                        <Pie
                          data={modelData}
                          cx="50%"
                          cy="50%"
                          innerRadius={50}
                          outerRadius={75}
                          dataKey="value"
                          strokeWidth={0}
                        >
                          {modelData.map((_, index) => (
                            <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                          ))}
                        </Pie>
                        <Tooltip
                          contentStyle={{ backgroundColor: '#1f1f24', border: '1px solid #534434', borderRadius: '12px', color: '#e3e2e8', fontSize: '11px' }}
                        />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="space-y-3">
                    {modelData.slice(0, 5).map((item, index) => (
                      <div key={item.name} className="flex items-center justify-between text-sm">
                        <div className="flex items-center gap-2">
                          <div className="w-2 h-2 rounded-full" style={{ backgroundColor: COLORS[index % COLORS.length] }} />
                          <span className="text-on-surface-variant truncate">{item.name}</span>
                        </div>
                        <span className="font-mono text-on-surface">{item.value}</span>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <div className="flex-1 flex flex-col items-center justify-center">
                  <span className="material-symbols-outlined text-4xl text-on-surface-variant/30 mb-3">donut_large</span>
                  <p className="text-sm text-on-surface-variant">No model data</p>
                </div>
              )}
            </div>
          </div>

          {/* Summary Stats Row */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 mb-12">
            <div className="bg-surface-container-low p-6 rounded-xl border border-outline-variant/15 relative overflow-hidden group">
              <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
                <span className="material-symbols-outlined text-5xl">database</span>
              </div>
              <p className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-2">Total Requests</p>
              <h3 className="text-3xl font-extrabold tracking-tighter text-primary">{totalRequests.toLocaleString()}</h3>
            </div>
            <div className="bg-surface-container-low p-6 rounded-xl border border-outline-variant/15 relative overflow-hidden group">
              <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
                <span className="material-symbols-outlined text-5xl">token</span>
              </div>
              <p className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-2">Total Tokens</p>
              <h3 className="text-3xl font-extrabold tracking-tighter text-primary">
                {totalTokens > 1_000_000
                  ? `${(totalTokens / 1_000_000).toFixed(2)}M`
                  : totalTokens > 1_000
                  ? `${(totalTokens / 1_000).toFixed(1)}K`
                  : totalTokens.toLocaleString()}
              </h3>
            </div>
            <div className="bg-surface-container-low p-6 rounded-xl border border-outline-variant/15 relative overflow-hidden group">
              <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
                <span className="material-symbols-outlined text-5xl">model_training</span>
              </div>
              <p className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-2">Active Models</p>
              <h3 className="text-3xl font-extrabold tracking-tighter text-primary">{modelCount}</h3>
            </div>
          </div>

          {/* Traffic by Rule */}
          {ruleData.length > 0 && (
            <div className="bg-surface-container-low rounded-[2rem] p-8 border border-outline-variant/15">
              <div className="flex justify-between items-center mb-10">
                <div>
                  <h3 className="text-lg font-bold text-on-surface mb-1">Traffic by Rule</h3>
                  <p className="text-sm text-on-surface-variant opacity-60">Routing rule hits</p>
                </div>
              </div>
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={ruleData} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#343439" vertical={false} />
                  <XAxis dataKey="name" stroke="#343439" tick={{ fill: '#d8c3ad', fontSize: 10 }} tickLine={false} />
                  <YAxis stroke="#343439" tick={{ fill: '#d8c3ad', fontSize: 10 }} tickLine={false} axisLine={false} />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#1f1f24', border: '1px solid #534434', borderRadius: '12px', color: '#e3e2e8', fontSize: '12px' }}
                    cursor={{ fill: '#1f1f24' }}
                  />
                  <Bar dataKey="requests" fill="#f59e0b" radius={[4, 4, 0, 0]} name="Requests" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}

      {!data && !loading && (
        <div className="bg-surface-container-low rounded-[2rem] border border-outline-variant/15 flex flex-col items-center justify-center py-16">
          <span className="material-symbols-outlined text-5xl text-on-surface-variant/30 mb-4">analytics</span>
          <p className="text-sm text-on-surface-variant font-medium">No usage data available</p>
          <p className="text-xs text-on-surface-variant/60 mt-1">Start routing requests to see analytics</p>
        </div>
      )}
    </div>
  );
}
