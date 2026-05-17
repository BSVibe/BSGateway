'use client';

import { useCallback, useEffect, useState } from 'react';
import { useT } from '@bsvibe/i18n';
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
  const t = useT('gateway');
  const { tenantId } = useAuth();
  const tid = tenantId || '';
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const limit = 50;
  const [offset, setOffset] = useState(0);

  const loadAuditLogs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<AuditLogListResponse>(
        `/tenants/${tid}/audit?limit=${limit}&offset=${offset}`
      );
      setLogs(res.items);
      setTotal(res.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('audit.loadFailed'));
    } finally {
      setLoading(false);
    }
    // `t` intentionally omitted — see DashboardPage.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tid, offset]);

  useEffect(() => {
    const id = window.setTimeout(() => {
      loadAuditLogs();
    }, 0);
    return () => window.clearTimeout(id);
  }, [loadAuditLogs]);

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
    if (action.includes('deleted')) return 'bg-error/15 text-error';
    if (action.includes('deactivated')) return 'bg-error/15 text-error';
    return 'bg-secondary-container/20 text-secondary';
  };

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      <div>
        <h2 className="text-4xl font-extrabold tracking-tight text-on-surface mb-2">{t('audit.title')}</h2>
        <p className="text-on-surface-variant">{t('audit.subtitle')}</p>
      </div>

      {error && <ErrorBanner message={error} onRetry={loadAuditLogs} />}

      <div className="bg-surface-container-low rounded-2xl overflow-hidden border border-outline-variant/5">
        {logs.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="bg-surface-container/50">
                  <th className="px-6 py-4 text-left text-[10px] uppercase tracking-widest text-on-surface-variant font-bold">{t('audit.table.timestamp')}</th>
                  <th className="px-6 py-4 text-left text-[10px] uppercase tracking-widest text-on-surface-variant font-bold">{t('audit.table.actor')}</th>
                  <th className="px-6 py-4 text-left text-[10px] uppercase tracking-widest text-on-surface-variant font-bold">{t('audit.table.action')}</th>
                  <th className="px-6 py-4 text-left text-[10px] uppercase tracking-widest text-on-surface-variant font-bold">{t('audit.table.resource')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-outline-variant/5">
                {logs.map((log) => (
                  <tr key={log.id} className="hover:bg-surface-container/30 transition-colors">
                    <td className="px-6 py-4 font-mono text-[11px] text-on-surface-variant whitespace-nowrap">
                      {formatDate(log.created_at)}
                    </td>
                    <td className="px-6 py-4">
                      <code className="text-xs bg-surface-container-highest px-2 py-1 rounded font-mono text-on-surface border border-outline-variant/10">
                        {log.actor.substring(0, 8)}...
                      </code>
                    </td>
                    <td className="px-6 py-4">
                      <span className={`px-2 py-1 text-[10px] rounded-full font-bold ${getActionColor(log.action)}`}>
                        {log.action}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-on-surface-variant font-mono text-xs">
                      {log.resource_type}:{' '}
                      <span className="text-on-surface font-semibold">{log.resource_id.substring(0, 12)}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-16">
            <span className="material-symbols-outlined text-5xl text-on-surface-variant/30 mb-4">receipt_long</span>
            <p className="text-sm text-on-surface-variant">{t('audit.empty.noLogs')}</p>
          </div>
        )}
      </div>

      {/* Pagination */}
      {total > limit && (
        <div className="flex justify-center items-center gap-3">
          <button
            onClick={() => setOffset(Math.max(0, offset - limit))}
            disabled={offset === 0}
            className="p-1.5 rounded bg-surface-container text-on-surface-variant hover:text-on-surface disabled:opacity-30 transition-colors"
          >
            <span className="material-symbols-outlined text-sm">chevron_left</span>
          </button>
          <span className="text-on-surface-variant text-xs font-medium">
            {t('audit.pagination.range', { from: offset + 1, to: Math.min(offset + limit, total), total })}
          </span>
          <button
            onClick={() => setOffset(offset + limit)}
            disabled={offset + limit >= total}
            className="p-1.5 rounded bg-surface-container text-on-surface-variant hover:text-on-surface disabled:opacity-30 transition-colors"
          >
            <span className="material-symbols-outlined text-sm">chevron_right</span>
          </button>
        </div>
      )}
    </div>
  );
}
