import { useCallback, useEffect, useState } from 'react';
import { XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area } from 'recharts';
import { rulesApi } from '../api/rules';
import { auditApi } from '../api/audit';
import { usageApi } from '../api/usage';
import { useAuth } from '../hooks/useAuth';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorBanner } from '../components/common/ErrorBanner';
import type { AuditLog } from '../types/api';

interface Stat {
  label: string;
  value: string | number;
  subtext?: string;
  icon: string;
  accent?: boolean;
  dim?: boolean;
  bgIcon: string;
}

interface ChartPoint {
  date: string;
  requests: number;
}

interface ModelBar {
  model: string;
  tokens: number;
  requests: number;
}

const StatCard = ({ stat }: { stat: Stat }) => (
  <div className="bg-surface-container-low p-6 rounded-xl relative overflow-hidden group">
    <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
      <span className="material-symbols-outlined text-6xl">{stat.bgIcon}</span>
    </div>
    <p className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-2">{stat.label}</p>
    <h3 className={`text-4xl font-extrabold tracking-tighter ${stat.dim ? 'text-on-surface-variant' : 'text-primary'}`}>
      {stat.value}
    </h3>
    {stat.subtext && (
      <div className="mt-4 flex items-center gap-2 text-xs text-amber-500/80">
        <span className="material-symbols-outlined text-sm">{stat.icon}</span>
        <span>{stat.subtext}</span>
      </div>
    )}
  </div>
);

function formatRelativeTime(isoStr: string): string {
  const diff = Date.now() - new Date(isoStr).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function formatModel(name: string): string {
  return name.length > 18 ? name.slice(0, 16) + '...' : name;
}

const MODEL_COLORS = ['#f59e0b', '#d97706', '#b45309', '#8fd5ff', '#534434'];

export function DashboardPage() {
  const { tenantId, tenantName } = useAuth();
  const tid = tenantId || '';
  const [stats, setStats] = useState<Stat[]>([]);
  const [chartData, setChartData] = useState<ChartPoint[]>([]);
  const [modelBars, setModelBars] = useState<ModelBar[]>([]);
  const [recentLogs, setRecentLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadDashboard = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [rules, usage, logs] = await Promise.all([
        rulesApi.list(tid).catch(() => []),
        usageApi.get(tid, 'week').catch(() => null),
        auditApi.list(tid, 10).catch(() => []),
      ]);

      const ruleCount = Array.isArray(rules) ? rules.length : 0;
      const totalRequests = usage?.total_requests ?? 0;
      const totalTokens = usage?.total_tokens ?? 0;

      setStats([
        {
          label: 'Total Requests',
          value: totalRequests.toLocaleString(),
          subtext: totalRequests > 0 ? 'last 7 days' : undefined,
          accent: true,
          icon: 'trending_up',
          bgIcon: 'database',
        },
        {
          label: 'Total Tokens',
          value: totalTokens > 1_000_000
            ? `${(totalTokens / 1_000_000).toFixed(1)}M`
            : totalTokens > 1_000
            ? `${(totalTokens / 1_000).toFixed(1)}K`
            : totalTokens.toString(),
          subtext: 'processed this week',
          icon: 'trending_up',
          bgIcon: 'payments',
        },
        {
          label: 'Active Rules',
          value: ruleCount,
          subtext: 'routing policies',
          icon: 'check_circle',
          bgIcon: 'speed',
        },
        {
          label: 'Avg Latency',
          value: '\u2014',
          subtext: 'not yet tracked',
          dim: true,
          icon: 'bolt',
          bgIcon: 'memory',
        },
      ]);

      if (usage?.daily_breakdown) {
        setChartData(usage.daily_breakdown.map((d) => ({
          date: new Date(d.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
          requests: d.requests,
        })));
      }

      if (usage?.by_model) {
        const bars: ModelBar[] = Object.entries(usage.by_model)
          .map(([model, data]) => ({ model, tokens: data.tokens, requests: data.requests }))
          .sort((a, b) => b.tokens - a.tokens)
          .slice(0, 6);
        setModelBars(bars);
      }

      setRecentLogs(Array.isArray(logs) ? logs : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load dashboard');
    } finally {
      setLoading(false);
    }
  }, [tid]);

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

  if (loading) return <LoadingSpinner />;

  return (
    <div className="p-8 space-y-8">
      {/* Top Bar */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-on-surface">
            {tenantName ? `${tenantName} Overview` : 'System Overview'}
          </h2>
          <p className="text-on-surface-variant text-sm mt-1">Routing overview and metrics</p>
        </div>
        <button
          onClick={loadDashboard}
          className="flex items-center gap-2 px-4 py-2 rounded-lg border border-outline-variant/20 text-xs font-bold text-on-surface-variant hover:bg-surface-container transition-all"
        >
          <span className="material-symbols-outlined text-sm">refresh</span>
          Refresh
        </button>
      </div>

      {error && <ErrorBanner message={error} onRetry={loadDashboard} />}

      {/* Stat Cards */}
      <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((stat) => (
          <StatCard key={stat.label} stat={stat} />
        ))}
      </section>

      {/* Charts Row */}
      <section className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* Request Volume */}
        <div className="lg:col-span-8 bg-surface-container-low p-8 rounded-xl relative overflow-hidden">
          <div className="flex justify-between items-center mb-8">
            <div>
              <h4 className="text-lg font-bold text-on-surface">Request Volume</h4>
              <p className="text-xs text-on-surface-variant">Live gateway traffic - last 7 days</p>
            </div>
          </div>
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={256}>
              <AreaChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
                <defs>
                  <linearGradient id="requestGradient" x1="0" y1="0" x2="0" y2="1">
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
                  fill="url(#requestGradient)"
                  dot={{ fill: '#f59e0b', r: 3, strokeWidth: 0 }}
                  activeDot={{ fill: '#f59e0b', r: 5, strokeWidth: 0 }}
                  name="Requests"
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[256px] flex flex-col items-center justify-center">
              <span className="material-symbols-outlined text-4xl text-on-surface-variant/30 mb-3">show_chart</span>
              <p className="text-sm text-on-surface-variant">No usage data yet</p>
            </div>
          )}
        </div>

        {/* Model Distribution */}
        <div className="lg:col-span-4 bg-surface-container-low p-8 rounded-xl flex flex-col">
          <div className="mb-8">
            <h4 className="text-lg font-bold text-on-surface">Model Distribution</h4>
            <p className="text-xs text-on-surface-variant">Token usage by model</p>
          </div>
          {modelBars.length > 0 ? (
            <div className="space-y-6 flex-1">
              {modelBars.slice(0, 4).map((bar, i) => {
                const maxTokens = modelBars[0].tokens;
                const pct = maxTokens > 0 ? Math.round((bar.tokens / maxTokens) * 100) : 0;
                return (
                  <div key={bar.model}>
                    <div className="flex justify-between mb-2">
                      <span className="text-xs font-bold text-on-surface">{formatModel(bar.model)}</span>
                      <span className="text-xs text-primary">{bar.tokens.toLocaleString()}</span>
                    </div>
                    <div className="h-2 w-full bg-surface-container rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{ width: `${pct}%`, backgroundColor: MODEL_COLORS[i % MODEL_COLORS.length] }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center">
              <span className="material-symbols-outlined text-4xl text-on-surface-variant/30 mb-3">bar_chart</span>
              <p className="text-sm text-on-surface-variant">No model data yet</p>
            </div>
          )}
        </div>
      </section>

      {/* Recent Activity Table */}
      <section className="bg-surface-container-low rounded-xl overflow-hidden">
        <div className="p-8 flex justify-between items-center">
          <div>
            <h4 className="text-lg font-bold text-on-surface">Recent Activity</h4>
            <p className="text-xs text-on-surface-variant">Latest audit events</p>
          </div>
        </div>
        {recentLogs.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-surface-container text-[10px] uppercase tracking-widest text-on-surface-variant font-bold">
                  <th className="px-8 py-4">Actor</th>
                  <th className="px-8 py-4">Action</th>
                  <th className="px-8 py-4">Resource</th>
                  <th className="px-8 py-4 text-right">When</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-outline-variant/10">
                {recentLogs.map((log) => (
                  <tr key={log.id} className="hover:bg-surface-container transition-colors">
                    <td className="px-8 py-4 font-mono text-[11px] text-on-surface-variant">
                      {log.actor?.slice(0, 16) ?? '\u2014'}
                    </td>
                    <td className="px-8 py-4">
                      <span className={`px-2 py-1 text-[10px] rounded-full font-bold ${
                        log.action.startsWith('create') ? 'bg-green-500/15 text-green-400' :
                        log.action.startsWith('delete') ? 'bg-error/15 text-error' :
                        'bg-secondary-container/20 text-secondary'
                      }`}>
                        {log.action}
                      </span>
                    </td>
                    <td className="px-8 py-4 text-xs text-on-surface-variant">{log.resource_type}</td>
                    <td className="px-8 py-4 text-right font-mono text-xs text-on-surface-variant">
                      {formatRelativeTime(log.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-12">
            <span className="material-symbols-outlined text-4xl text-on-surface-variant/30 mb-3">list_alt</span>
            <p className="text-sm text-on-surface-variant">No recent activity</p>
            <p className="text-xs text-on-surface-variant/60 mt-1">Events will appear here as you use BSGateway</p>
          </div>
        )}
      </section>
    </div>
  );
}
