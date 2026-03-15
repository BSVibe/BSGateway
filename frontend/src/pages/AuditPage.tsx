import { useState } from 'react';
import { auditApi } from '../api/audit';
import { useApi } from '../hooks/useApi';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorBanner } from '../components/common/ErrorBanner';

const TENANT_ID = localStorage.getItem('bsg_tenant_id') || '';
const PAGE_SIZE = 50;

export function AuditPage() {
  const [offset, setOffset] = useState(0);
  const { data: logs, loading, error, refetch } = useApi(
    () => auditApi.list(TENANT_ID, PAGE_SIZE, offset),
    [TENANT_ID, offset],
  );

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onRetry={refetch} />;

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-gray-900">Audit Log</h2>

      <div className="bg-white rounded-lg shadow overflow-hidden">
        {logs && logs.length > 0 ? (
          <>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-gray-50 text-left">
                  <th className="px-4 py-3 font-medium text-gray-600">Time</th>
                  <th className="px-4 py-3 font-medium text-gray-600">Actor</th>
                  <th className="px-4 py-3 font-medium text-gray-600">Action</th>
                  <th className="px-4 py-3 font-medium text-gray-600">Resource</th>
                  <th className="px-4 py-3 font-medium text-gray-600">Details</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => (
                  <tr key={log.id} className="border-b border-gray-100">
                    <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                      {new Date(log.created_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-3 font-mono text-sm">{log.actor}</td>
                    <td className="px-4 py-3">
                      <span className="bg-gray-100 text-gray-800 px-2 py-0.5 rounded text-xs font-mono">
                        {log.action}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm">
                      {log.resource_type}/{log.resource_id.slice(0, 8)}...
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500 max-w-xs truncate">
                      {Object.keys(log.details).length > 0
                        ? JSON.stringify(log.details)
                        : '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div className="flex items-center justify-between px-4 py-3 border-t bg-gray-50">
              <button
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                disabled={offset === 0}
                className="text-sm text-blue-600 hover:text-blue-800 disabled:text-gray-400"
              >
                Previous
              </button>
              <span className="text-sm text-gray-500">
                Showing {offset + 1}–{offset + logs.length}
              </span>
              <button
                onClick={() => setOffset(offset + PAGE_SIZE)}
                disabled={logs.length < PAGE_SIZE}
                className="text-sm text-blue-600 hover:text-blue-800 disabled:text-gray-400"
              >
                Next
              </button>
            </div>
          </>
        ) : (
          <p className="text-gray-500 text-center py-8">No audit logs</p>
        )}
      </div>
    </div>
  );
}
