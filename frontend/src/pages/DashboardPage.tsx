import { useEffect, useState } from 'react';
import { XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area, BarChart, Bar, Cell } from 'recharts';
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
  icon: React.ReactNode;
  accent?: boolean;
  dim?: boolean;
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
  <div className="bg-gray-900 rounded-xl p-5 border border-gray-700 hover:border-gray-600 transition-colors">
    <div className="flex items-start justify-between mb-3">
      <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${
        stat.accent ? 'bg-accent-500/15 text-accent-500' : 'bg-gray-800 text-gray-400'
      }`}>
        {stat.icon}
      </div>
    </div>
    <p className={`text-2xl font-bold tabular-nums ${stat.dim ? 'text-gray-500' : 'text-gray-50'}`}>
      {stat.value}
    </p>
    <p className="text-xs font-medium text-gray-400 mt-1">{stat.label}</p>
    {stat.subtext && <p className="text-[11px] text-gray-600 mt-0.5">{stat.subtext}</p>}
  </div>
);

function formatModel(name: string): string {
  return name.length > 18 ? name.slice(0, 16) + '…' : name;
}

function formatRelativeTime(isoStr: string): string {
  const diff = Date.now() - new Date(isoStr).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

const MODEL_COLORS = ['#f59e0b', '#d97706', '#b45309', '#92400e', '#78350f'];

export function DashboardPage() {
  const { tenantId, tenantName } = useAuth();
  const tid = tenantId || '';
  const [stats, setStats] = useState<Stat[]>([]);
  const [chartData, setChartData] = useState<ChartPoint[]>([]);
  const [modelBars, setModelBars] = useState<ModelBar[]>([]);
  const [recentLogs, setRecentLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadDashboard();
  }, []);

  const loadDashboard = async () => {
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
          label: 'Requests',
          value: totalRequests.toLocaleString(),
          subtext: 'last 7 days',
          accent: true,
          icon: (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M2 12L5 8L7.5 10L10.5 5L14 9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          ),
        },
        {
          label: 'Total Tokens',
          value: totalTokens > 1_000_000
            ? `${(totalTokens / 1_000_000).toFixed(1)}M`
            : totalTokens > 1_000
            ? `${(totalTokens / 1_000).toFixed(1)}K`
            : totalTokens.toString(),
          subtext: 'processed this week',
          icon: (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <circle cx="8" cy="8" r="5.5" stroke="currentColor" strokeWidth="1.5"/>
              <path d="M8 5.5V8L9.5 9.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
            </svg>
          ),
        },
        {
          label: 'Active Rules',
          value: ruleCount,
          subtext: 'routing policies',
          icon: (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M2 4h12M2 8h8M2 12h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
              <circle cx="13" cy="8" r="2" fill="currentColor" opacity="0.8"/>
            </svg>
          ),
        },
        {
          label: 'Avg Latency',
          value: '—',
          subtext: 'not yet tracked',
          dim: true,
          icon: (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <circle cx="8" cy="8" r="5.5" stroke="currentColor" strokeWidth="1.5"/>
              <path d="M8 5v3.5l2 2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          ),
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
  };

  if (loading) return <LoadingSpinner />;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-50">
            {tenantName ? `${tenantName} Overview` : 'Dashboard'}
          </h2>
          <p className="text-gray-500 text-sm mt-0.5">Routing overview and metrics</p>
        </div>
        <button
          onClick={loadDashboard}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-gray-700 text-xs text-gray-400 hover:text-gray-200 hover:border-gray-600 transition-colors"
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
            <path d="M10 6A4 4 0 112 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
            <path d="M10 2v4H6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
          Refresh
        </button>
      </div>

      {error && <ErrorBanner message={error} onRetry={loadDashboard} />}

      {/* Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((stat) => (
          <StatCard key={stat.label} stat={stat} />
        ))}
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Request Volume Area Chart */}
        <div className="bg-gray-900 rounded-xl border border-gray-700 p-6">
          <div className="mb-5">
            <h3 className="text-sm font-semibold text-gray-50">Request Volume</h3>
            <p className="text-xs text-gray-500 mt-0.5">Last 7 days</p>
          </div>
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
                <defs>
                  <linearGradient id="requestGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.2} />
                    <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e2033" vertical={false} />
                <XAxis dataKey="date" stroke="#2a2d42" tick={{ fill: '#5a5f7d', fontSize: 11 }} tickLine={false} />
                <YAxis stroke="#2a2d42" tick={{ fill: '#5a5f7d', fontSize: 11 }} tickLine={false} axisLine={false} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#111218', border: '1px solid #2a2d42', borderRadius: '8px', color: '#f2f3f7', fontSize: '12px' }}
                  labelStyle={{ color: '#8187a8' }}
                  cursor={{ stroke: '#2a2d42' }}
                />
                <Area
                  type="monotone"
                  dataKey="requests"
                  stroke="#f59e0b"
                  strokeWidth={2}
                  fill="url(#requestGradient)"
                  dot={{ fill: '#f59e0b', r: 3, strokeWidth: 0 }}
                  activeDot={{ fill: '#f59e0b', r: 5, strokeWidth: 0 }}
                  name="Requests"
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[200px] flex flex-col items-center justify-center">
              <div className="w-10 h-10 rounded-xl bg-gray-800 flex items-center justify-center mb-3">
                <svg width="18" height="18" viewBox="0 0 18 18" fill="none" className="text-gray-500" aria-hidden="true">
                  <path d="M2 14L6 9L9 11L12 6L16 10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </div>
              <p className="text-sm text-gray-500">No usage data yet</p>
            </div>
          )}
        </div>

        {/* Cost Breakdown by Model Bar Chart */}
        <div className="bg-gray-900 rounded-xl border border-gray-700 p-6">
          <div className="mb-5">
            <h3 className="text-sm font-semibold text-gray-50">Token Usage by Model</h3>
            <p className="text-xs text-gray-500 mt-0.5">This week</p>
          </div>
          {modelBars.length > 0 ? (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={modelBars} margin={{ top: 4, right: 4, bottom: 0, left: -10 }} barSize={20}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e2033" vertical={false} />
                <XAxis
                  dataKey="model"
                  stroke="#2a2d42"
                  tick={{ fill: '#5a5f7d', fontSize: 10 }}
                  tickLine={false}
                  tickFormatter={formatModel}
                />
                <YAxis stroke="#2a2d42" tick={{ fill: '#5a5f7d', fontSize: 11 }} tickLine={false} axisLine={false} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#111218', border: '1px solid #2a2d42', borderRadius: '8px', color: '#f2f3f7', fontSize: '12px' }}
                  labelStyle={{ color: '#8187a8' }}
                  cursor={{ fill: '#1e2033' }}
                  formatter={(value) => [typeof value === 'number' ? value.toLocaleString() : value, 'Tokens']}
                />
                <Bar dataKey="tokens" radius={[4, 4, 0, 0]}>
                  {modelBars.map((entry, i) => (
                    <Cell key={entry.model} fill={MODEL_COLORS[i % MODEL_COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[200px] flex flex-col items-center justify-center">
              <div className="w-10 h-10 rounded-xl bg-gray-800 flex items-center justify-center mb-3">
                <svg width="18" height="18" viewBox="0 0 18 18" fill="none" className="text-gray-500" aria-hidden="true">
                  <rect x="2" y="8" width="4" height="8" rx="1" stroke="currentColor" strokeWidth="1.5"/>
                  <rect x="7" y="5" width="4" height="11" rx="1" stroke="currentColor" strokeWidth="1.5"/>
                  <rect x="12" y="2" width="4" height="14" rx="1" stroke="currentColor" strokeWidth="1.5"/>
                </svg>
              </div>
              <p className="text-sm text-gray-500">No model data yet</p>
            </div>
          )}
        </div>
      </div>

      {/* Recent Routing Decisions */}
      <div className="bg-gray-900 rounded-xl border border-gray-700 overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800">
          <div>
            <h3 className="text-sm font-semibold text-gray-50">Recent Activity</h3>
            <p className="text-xs text-gray-500 mt-0.5">Latest audit events</p>
          </div>
        </div>
        {recentLogs.length > 0 ? (
          <div>
            <div className="hidden sm:grid grid-cols-[140px_1fr_120px_100px] gap-4 px-5 py-2.5 border-b border-gray-800">
              <span className="text-[10px] font-semibold text-gray-600 uppercase tracking-wider">Actor</span>
              <span className="text-[10px] font-semibold text-gray-600 uppercase tracking-wider">Action</span>
              <span className="text-[10px] font-semibold text-gray-600 uppercase tracking-wider">Resource</span>
              <span className="text-[10px] font-semibold text-gray-600 uppercase tracking-wider">When</span>
            </div>
            {recentLogs.map((log, idx) => (
              <div
                key={log.id}
                className={`sm:grid sm:grid-cols-[140px_1fr_120px_100px] flex flex-wrap gap-2 px-5 py-3 items-center hover:bg-gray-800/40 transition-colors ${
                  idx < recentLogs.length - 1 ? 'border-b border-gray-800' : ''
                }`}
              >
                <span className="text-xs text-gray-400 truncate font-mono">{log.actor?.slice(0, 16) ?? '—'}</span>
                <div className="flex items-center gap-2">
                  <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium ${
                    log.action.startsWith('create') ? 'bg-emerald-500/15 text-emerald-400' :
                    log.action.startsWith('delete') ? 'bg-red-500/15 text-red-400' :
                    'bg-gray-700 text-gray-400'
                  }`}>
                    {log.action}
                  </span>
                </div>
                <span className="text-xs text-gray-500">{log.resource_type}</span>
                <span className="text-xs text-gray-600">{formatRelativeTime(log.created_at)}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-12">
            <div className="w-10 h-10 rounded-xl bg-gray-800 flex items-center justify-center mb-3">
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none" className="text-gray-500">
                <path d="M3 5h12M3 9h8M3 13h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
              </svg>
            </div>
            <p className="text-sm text-gray-500">No recent activity</p>
            <p className="text-xs text-gray-600 mt-1">Events will appear here as you use BSGateway</p>
          </div>
        )}
      </div>
    </div>
  );
}
