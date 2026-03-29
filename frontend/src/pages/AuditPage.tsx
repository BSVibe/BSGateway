import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { useAuth } from '../hooks/useAuth';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorBanner } from '../components/common/ErrorBanner';
import type { AuditLog } from '../types/api';

interface AuditLogListResponse {
  items: AuditLog[];
  total: number;
}

export function AuditPage() {
  const { tenantId } = useAuth();
  const tid = tenantId || '';
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const limit = 50;
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    loadAuditLogs();
  }, [offset]);

  const loadAuditLogs = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<AuditLogListResponse>(
        `/tenants/${tid}/audit?limit=${limit}&offset=${offset}`
      );
      setLogs(res.items);
      setTotal(res.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load audit logs');
    } finally {
      setLoading(false);
    }
  };

  if (loading) return <LoadingSpinner />;

  const formatDate = (isoString: string) => {
    const date = new Date(isoString);
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const getActionColor = (action: string) => {
    if (action.includes('created')) return 'bg-green-500/15 text-green-400';
    if (action.includes('deleted')) return 'bg-red-500/15 text-red-400';
    if (action.includes('deactivated')) return 'bg-red-500/15 text-red-400';
    return 'bg-accent-500/15 text-accent-500';
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-gray-50">Audit Log</h2>
        <p className="text-gray-500 text-sm mt-1">All admin operations and changes</p>
      </div>

      {error && <ErrorBanner message={error} onRetry={loadAuditLogs} />}

      <div className="bg-gray-900 rounded-lg border border-gray-700 overflow-hidden">
        {logs.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-850 border-b border-gray-700">
                <tr>
                  <th className="px-6 py-3 text-left font-semibold text-gray-400">Timestamp</th>
                  <th className="px-6 py-3 text-left font-semibold text-gray-400">Actor</th>
                  <th className="px-6 py-3 text-left font-semibold text-gray-400">Action</th>
                  <th className="px-6 py-3 text-left font-semibold text-gray-400">Resource</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {logs.map((log) => (
                  <tr key={log.id} className="hover:bg-gray-800/50 transition-colors">
                    <td className="px-6 py-4 text-gray-400 whitespace-nowrap">
                      {formatDate(log.created_at)}
                    </td>
                    <td className="px-6 py-4">
                      <code className="text-xs bg-gray-800 px-2 py-1 rounded font-mono text-gray-300 border border-gray-700">
                        {log.actor.substring(0, 8)}...
                      </code>
                    </td>
                    <td className="px-6 py-4">
                      <span className={`text-xs px-2 py-1 rounded font-medium ${getActionColor(log.action)}`}>
                        {log.action}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-gray-400 font-mono text-xs">
                      {log.resource_type}:{' '}
                      <span className="text-gray-50 font-semibold">{log.resource_id.substring(0, 12)}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-gray-500 text-center py-8">No audit logs</p>
        )}
      </div>

      {/* Pagination */}
      {total > limit && (
        <div className="flex justify-center items-center gap-2">
          <button
            onClick={() => setOffset(Math.max(0, offset - limit))}
            disabled={offset === 0}
            className="px-4 py-2 border border-gray-700 rounded-lg text-sm text-gray-300 hover:bg-gray-800 disabled:opacity-50"
          >
            Previous
          </button>
          <span className="text-sm text-gray-500">
            {offset + 1}--{Math.min(offset + limit, total)} of {total}
          </span>
          <button
            onClick={() => setOffset(offset + limit)}
            disabled={offset + limit >= total}
            className="px-4 py-2 border border-gray-700 rounded-lg text-sm text-gray-300 hover:bg-gray-800 disabled:opacity-50"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
