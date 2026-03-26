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
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-gray-900">API Keys</h2>
        <button
          onClick={() => { setShowForm(!showForm); setNewKey(null); }}
          className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-blue-700"
        >
          {showForm ? 'Cancel' : 'Create API Key'}
        </button>
      </div>

      {createError && <ErrorBanner message={createError} onRetry={() => setCreateError(null)} />}

      {newKey && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4">
          <p className="text-sm font-medium text-green-800 mb-2">
            API Key created. Copy it now — it won't be shown again.
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 bg-white border rounded px-3 py-2 text-sm font-mono text-gray-800 select-all break-all">
              {newKey}
            </code>
            <button
              onClick={() => { navigator.clipboard.writeText(newKey); }}
              className="bg-green-600 text-white px-3 py-2 rounded text-sm hover:bg-green-700 shrink-0"
            >
              Copy
            </button>
          </div>
          <p className="text-xs text-gray-500 mt-2">
            Usage: <code className="bg-gray-100 px-1 rounded">Authorization: Bearer {newKey.slice(0, 12)}...</code>
          </p>
        </div>
      )}

      {showForm && !newKey && (
        <div className="bg-white rounded-lg shadow p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Key Name</label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="e.g. production, staging, ci-pipeline"
              className="w-full border rounded-lg px-3 py-2 text-sm"
            />
            <p className="text-xs text-gray-400 mt-1">A label to identify this key</p>
          </div>
          <button
            onClick={handleCreate}
            disabled={submitting || !formData.name.trim()}
            className="bg-green-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-green-700 disabled:opacity-50"
          >
            {submitting ? 'Creating...' : 'Create Key'}
          </button>
        </div>
      )}

      {deleteError && <ErrorBanner message={deleteError} onRetry={() => setDeleteError(null)} />}

      <div className="bg-white rounded-lg shadow">
        {keys && keys.length > 0 ? (
          <div className="divide-y">
            {keys.map((key) => (
              <div key={key.id} className="p-4 flex items-center justify-between">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{key.name}</span>
                    {!key.is_active && (
                      <span className="text-xs bg-red-100 text-red-800 px-2 py-0.5 rounded">
                        revoked
                      </span>
                    )}
                    {key.expires_at && new Date(key.expires_at) < new Date() && key.is_active && (
                      <span className="text-xs bg-yellow-100 text-yellow-800 px-2 py-0.5 rounded">
                        expired
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-gray-500 mt-1 font-mono">{key.key_prefix}...</p>
                  <div className="flex gap-4 text-xs text-gray-400 mt-1">
                    <span>Created {new Date(key.created_at).toLocaleDateString()}</span>
                    {key.last_used_at && (
                      <span>Last used {new Date(key.last_used_at).toLocaleDateString()}</span>
                    )}
                    {key.expires_at && (
                      <span>Expires {new Date(key.expires_at).toLocaleDateString()}</span>
                    )}
                  </div>
                </div>
                {key.is_active && (
                  <button
                    onClick={() => onDelete(key.id, () => apiKeysApi.revoke(tid, key.id), refetch)}
                    className={`text-sm shrink-0 ${
                      deleting === key.id
                        ? 'text-white bg-red-600 px-3 py-1 rounded'
                        : 'text-red-500 hover:text-red-700'
                    }`}
                  >
                    {deleting === key.id ? 'Confirm?' : 'Revoke'}
                  </button>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="text-gray-500 text-center py-8">No API keys created</p>
        )}
      </div>
    </div>
  );
}
