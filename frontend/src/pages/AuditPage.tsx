import { useEffect, useState } from 'react';
import { api, SESSION_KEYS } from '../api/client';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorBanner } from '../components/common/ErrorBanner';

interface AuditLog {
  id: string;
  created_at: string;
  actor: string;
  action: string;
  resource_type: string;
  resource_id: string;
  details: Record<string, any> | null;
}

export function AuditPage() {
  const tenantId = sessionStorage.getItem(SESSION_KEYS.tenantId) || '';
  const [logs, setLogs] = useState<AuditLog[]>([]);
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
      const res = await api.get<AuditLog[]>(
        `/tenants/${tenantId}/audit?limit=${limit}&offset=${offset}`
      );
      setLogs(res);
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
    if (action.includes('created')) return 'bg-green-100 text-green-800';
    if (action.includes('deleted')) return 'bg-red-100 text-red-800';
    if (action.includes('deactivated')) return 'bg-red-100 text-red-800';
    return 'bg-blue-100 text-blue-800';
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Audit Log</h2>
        <p className="text-gray-500 text-sm mt-1">All admin operations and changes</p>
      </div>

      {error && <ErrorBanner message={error} onRetry={loadAuditLogs} />}

      <div className="bg-white rounded-lg shadow overflow-hidden">
        {logs.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="px-6 py-3 text-left font-semibold text-gray-700">Timestamp</th>
                  <th className="px-6 py-3 text-left font-semibold text-gray-700">Actor</th>
                  <th className="px-6 py-3 text-left font-semibold text-gray-700">Action</th>
                  <th className="px-6 py-3 text-left font-semibold text-gray-700">Resource</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {logs.map((log) => (
                  <tr key={log.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 text-gray-600 whitespace-nowrap">
                      {formatDate(log.created_at)}
                    </td>
                    <td className="px-6 py-4">
                      <code className="text-xs bg-gray-100 px-2 py-1 rounded font-mono">
                        {log.actor.substring(0, 8)}...
                      </code>
                    </td>
                    <td className="px-6 py-4">
                      <span className={`text-xs px-2 py-1 rounded font-medium ${getActionColor(log.action)}`}>
                        {log.action}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-gray-600 font-mono text-xs">
                      {log.resource_type}:{' '}
                      <span className="text-gray-900 font-semibold">{log.resource_id.substring(0, 12)}</span>
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
      {logs.length >= limit && (
        <div className="flex justify-center gap-2">
          <button
            onClick={() => setOffset(Math.max(0, offset - limit))}
            disabled={offset === 0}
            className="px-4 py-2 border rounded-lg text-sm hover:bg-gray-50 disabled:opacity-50"
          >
            ← Previous
          </button>
          <button
            onClick={() => setOffset(offset + limit)}
            className="px-4 py-2 border rounded-lg text-sm hover:bg-gray-50"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}
