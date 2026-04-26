'use client';

import { useState } from 'react';
import { apiKeysApi } from '../api/apikeys';
import { useAuth } from '../hooks/useAuth';
import { useApi } from '../hooks/useApi';
import { useForm } from '../hooks/useForm';
import { useDeleteConfirm } from '../hooks/useDeleteConfirm';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorBanner } from '../components/common/ErrorBanner';
import type { ApiKeyCreate } from '../types/api';

const INITIAL_KEY: ApiKeyCreate = { name: '' };

export function ApiKeysPage() {
  const { tenantId } = useAuth();
  const tid = tenantId || '';
  const { data: keys, loading, error, refetch } = useApi(
    () => apiKeysApi.list(tid),
    [tid],
  );

  const [newKey, setNewKey] = useState<string | null>(null);

  const {
    formData, setFormData, showForm, setShowForm,
    submitting, createError, setCreateError, handleCreate,
  } = useForm<ApiKeyCreate>({
    initialValues: INITIAL_KEY,
    validate: (v) => !v.name.trim() ? 'Name is required' : null,
    onSubmit: async (v) => {
      const result = await apiKeysApi.create(tid, v);
      setNewKey(result.raw_key);
      refetch();
    },
  });

  const { deleting, deleteError, handleDelete: onDelete, setDeleteError } = useDeleteConfirm();

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onRetry={refetch} />;

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
        <div>
          <h1 className="text-4xl font-extrabold tracking-tight text-on-surface mb-2">API Keys</h1>
          <p className="text-on-surface-variant text-lg">Manage access keys for your applications.</p>
        </div>
        <button
          onClick={() => { setShowForm(!showForm); setNewKey(null); }}
          className="flex items-center gap-2 bg-gradient-to-br from-primary to-primary-container text-on-primary px-5 py-2.5 rounded-lg font-semibold shadow-lg shadow-primary/10 hover:brightness-110 active:scale-95 transition-all duration-200"
        >
          <span className="material-symbols-outlined text-[20px]">add</span>
          {showForm ? 'Cancel' : 'Generate New Key'}
        </button>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-surface-container-low p-6 rounded-xl border-l-4 border-amber-500 shadow-xl">
          <span className="text-on-surface-variant text-xs font-bold tracking-widest uppercase mb-1 block">Active Keys</span>
          <div className="text-3xl font-bold text-amber-500">
            {keys?.filter(k => k.is_active).length ?? 0}
          </div>
        </div>
        <div className="bg-surface-container-low p-6 rounded-xl border-l-4 border-outline-variant shadow-xl">
          <span className="text-on-surface-variant text-xs font-bold tracking-widest uppercase mb-1 block">Total Keys</span>
          <div className="text-3xl font-bold text-on-surface">{keys?.length ?? 0}</div>
        </div>
        <div className="bg-surface-container-low p-6 rounded-xl border-l-4 border-outline-variant shadow-xl">
          <span className="text-on-surface-variant text-xs font-bold tracking-widest uppercase mb-1 block">Revoked</span>
          <div className="text-3xl font-bold text-on-surface">
            {keys?.filter(k => !k.is_active).length ?? 0}
          </div>
        </div>
      </div>

      {createError && <ErrorBanner message={createError} onRetry={() => setCreateError(null)} />}

      {/* New Key Banner */}
      {newKey && (
        <div className="bg-green-500/10 border border-green-500/30 rounded-xl p-6">
          <p className="text-sm font-medium text-green-400 mb-3 flex items-center gap-2">
            <span className="material-symbols-outlined text-sm">check_circle</span>
            API Key created. Copy it now -- it won't be shown again.
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 bg-surface-container-lowest border border-outline-variant/20 rounded-lg px-4 py-3 text-sm font-mono text-on-surface select-all break-all">
              {newKey}
            </code>
            <button
              onClick={() => { navigator.clipboard.writeText(newKey); }}
              className="bg-primary-container text-on-primary px-4 py-3 rounded-lg text-sm font-bold hover:brightness-110 shrink-0 flex items-center gap-2"
            >
              <span className="material-symbols-outlined text-sm">content_copy</span>
              Copy
            </button>
          </div>
          <p className="text-xs text-on-surface-variant mt-3">
            Usage: <code className="bg-surface-container px-1.5 rounded text-on-surface-variant font-mono">Authorization: Bearer {newKey.slice(0, 12)}...</code>
          </p>
        </div>
      )}

      {/* Create Form */}
      {showForm && !newKey && (
        <div className="bg-surface-container-low rounded-xl border border-outline-variant/10 p-6 space-y-4">
          <div className="space-y-2">
            <label className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">Key Name</label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="e.g. production, staging, ci-pipeline"
              className="w-full bg-surface-container-highest border-none rounded-xl py-3 px-4 text-sm focus:ring-1 focus:ring-primary/40 placeholder:text-on-surface-variant/20"
            />
            <p className="text-[10px] text-on-surface-variant/60">A label to identify this key</p>
          </div>
          <button
            onClick={handleCreate}
            disabled={submitting || !formData.name.trim()}
            className="bg-primary-container text-on-primary px-6 py-3 rounded-xl font-bold hover:brightness-110 active:scale-95 transition-all disabled:opacity-50"
          >
            {submitting ? 'Creating...' : 'Create Key'}
          </button>
        </div>
      )}

      {deleteError && <ErrorBanner message={deleteError} onRetry={() => setDeleteError(null)} />}

      {/* Keys Table */}
      <div className="bg-surface-container rounded-xl overflow-hidden shadow-2xl border border-outline-variant/5">
        {keys && keys.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-surface-container-high">
                  <th className="px-6 py-4 text-xs font-bold tracking-widest text-on-surface-variant uppercase">Name</th>
                  <th className="px-6 py-4 text-xs font-bold tracking-widest text-on-surface-variant uppercase">Key</th>
                  <th className="px-6 py-4 text-xs font-bold tracking-widest text-on-surface-variant uppercase">Created</th>
                  <th className="px-6 py-4 text-xs font-bold tracking-widest text-on-surface-variant uppercase">Last Used</th>
                  <th className="px-6 py-4 text-xs font-bold tracking-widest text-on-surface-variant uppercase">Status</th>
                  <th className="px-6 py-4 text-xs font-bold tracking-widest text-on-surface-variant uppercase text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {keys.map((key) => {
                  const isExpired = key.expires_at && new Date(key.expires_at) < new Date() && key.is_active;
                  return (
                    <tr key={key.id} className="group hover:bg-surface-bright/10 transition-colors duration-200">
                      <td className="px-6 py-5 font-medium text-on-surface">{key.name}</td>
                      <td className="px-6 py-5">
                        <div className="flex items-center gap-2 font-mono text-sm text-on-surface-variant bg-surface-container-lowest px-2 py-1 rounded">
                          {key.key_prefix}...
                          <button
                            onClick={() => navigator.clipboard.writeText(key.key_prefix)}
                            className="material-symbols-outlined text-xs hover:text-amber-500 transition-colors"
                          >
                            content_copy
                          </button>
                        </div>
                      </td>
                      <td className="px-6 py-5 text-sm text-on-surface-variant">
                        {new Date(key.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                      </td>
                      <td className="px-6 py-5 text-sm text-on-surface-variant">
                        {key.last_used_at
                          ? new Date(key.last_used_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
                          : 'Never'}
                      </td>
                      <td className="px-6 py-5">
                        {!key.is_active ? (
                          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold tracking-wider uppercase bg-surface-container-highest text-on-surface-variant border border-outline-variant/20">
                            Revoked
                          </span>
                        ) : isExpired ? (
                          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold tracking-wider uppercase bg-amber-500/10 text-amber-500 border border-amber-500/20">
                            Expired
                          </span>
                        ) : (
                          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold tracking-wider uppercase bg-green-500/10 text-green-500 border border-green-500/20">
                            Active
                          </span>
                        )}
                      </td>
                      <td className="px-6 py-5 text-right">
                        {key.is_active && (
                          <button
                            onClick={() => onDelete(key.id, () => apiKeysApi.revoke(tid, key.id), refetch)}
                            className={`transition-colors ${
                              deleting === key.id
                                ? 'text-error'
                                : 'text-on-surface-variant hover:text-error'
                            }`}
                          >
                            <span className="material-symbols-outlined text-[20px]">
                              {deleting === key.id ? 'check_circle' : 'delete_forever'}
                            </span>
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-16">
            <span className="material-symbols-outlined text-5xl text-on-surface-variant/30 mb-4">vpn_key</span>
            <p className="text-sm text-on-surface-variant">No API keys created</p>
          </div>
        )}
      </div>

    </div>
  );
}
