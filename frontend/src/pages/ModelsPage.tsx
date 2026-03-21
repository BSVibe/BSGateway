import { useState } from 'react';
import { tenantsApi } from '../api/tenants';
import { SESSION_KEYS } from '../api/client';
import { useApi } from '../hooks/useApi';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorBanner } from '../components/common/ErrorBanner';
import type { TenantModel, TenantModelCreate } from '../types/api';

export function ModelsPage() {
  const tenantId = sessionStorage.getItem(SESSION_KEYS.tenantId) || '';
  const { data: models, loading, error, refetch } = useApi(
    () => tenantsApi.listModels(tenantId),
    [tenantId],
  );
  const [showForm, setShowForm] = useState(false);
  const [formData, setFormData] = useState<TenantModelCreate>({
    model_name: '',
    litellm_model: '',
  });
  const [submitting, setSubmitting] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const handleCreate = async () => {
    setSubmitting(true);
    setCreateError(null);
    try {
      await tenantsApi.createModel(tenantId, formData);
      setShowForm(false);
      setFormData({ model_name: '', litellm_model: '' });
      refetch();
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : 'Failed to create model');
    } finally {
      setSubmitting(false);
    }
  };

  const [deleting, setDeleting] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const handleDelete = async (model: TenantModel) => {
    if (deleting === model.id) {
      setDeleteError(null);
      try {
        await tenantsApi.deleteModel(tenantId, model.id);
        setDeleting(null);
        refetch();
      } catch (err) {
        setDeleteError(err instanceof Error ? err.message : 'Delete failed');
      }
    } else {
      setDeleting(model.id);
      setDeleteError(null);
    }
  };

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onRetry={refetch} />;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-gray-900">Models</h2>
        <button
          onClick={() => setShowForm(!showForm)}
          className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-blue-700"
        >
          {showForm ? 'Cancel' : 'Register Model'}
        </button>
      </div>

      {createError && <ErrorBanner message={createError} onRetry={() => setCreateError(null)} />}

      {showForm && (
        <div className="bg-white rounded-lg shadow p-6 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Alias</label>
              <input
                type="text"
                value={formData.model_name}
                onChange={(e) => setFormData({ ...formData, model_name: e.target.value })}
                placeholder="gpt-4o"
                className="w-full border rounded-lg px-3 py-2 text-sm"
              />
              <p className="text-xs text-gray-400 mt-1">Tenant 내부에서 사용할 이름</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Model Name</label>
              <input
                type="text"
                value={formData.litellm_model}
                onChange={(e) => setFormData({ ...formData, litellm_model: e.target.value })}
                placeholder="openai/gpt-4o"
                className="w-full border rounded-lg px-3 py-2 text-sm font-mono"
              />
              <p className="text-xs text-gray-400 mt-1">LiteLLM 모델 ID (provider/model)</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                API Base <span className="text-gray-400 font-normal">(optional)</span>
              </label>
              <input
                type="text"
                value={formData.api_base || ''}
                onChange={(e) => setFormData({ ...formData, api_base: e.target.value || undefined })}
                placeholder="http://localhost:11434"
                className="w-full border rounded-lg px-3 py-2 text-sm font-mono"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                API Key <span className="text-gray-400 font-normal">(optional)</span>
              </label>
              <input
                type="password"
                value={formData.api_key || ''}
                onChange={(e) => setFormData({ ...formData, api_key: e.target.value || undefined })}
                placeholder="sk-..."
                className="w-full border rounded-lg px-3 py-2 text-sm"
              />
            </div>
          </div>
          <button
            onClick={handleCreate}
            disabled={submitting || !formData.model_name || !formData.litellm_model}
            className="bg-green-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-green-700 disabled:opacity-50"
          >
            {submitting ? 'Registering...' : 'Register Model'}
          </button>
        </div>
      )}

      {deleteError && <ErrorBanner message={deleteError} onRetry={() => setDeleteError(null)} />}

      <div className="bg-white rounded-lg shadow">
        {models && models.length > 0 ? (
          <div className="divide-y">
            {models.map((model) => (
              <div key={model.id} className="p-4 flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{model.model_name}</span>
                    <span className="text-xs bg-blue-100 text-blue-800 px-2 py-0.5 rounded">
                      {model.litellm_model.split('/')[0]}
                    </span>
                    {!model.is_active && (
                      <span className="text-xs bg-red-100 text-red-800 px-2 py-0.5 rounded">
                        inactive
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-gray-500 mt-1 font-mono">{model.litellm_model}</p>
                  {model.api_base && (
                    <p className="text-xs text-gray-400 mt-0.5 font-mono">{model.api_base}</p>
                  )}
                </div>
                <button
                  onClick={() => handleDelete(model)}
                  onBlur={() => setDeleting(null)}
                  className={`text-sm ${
                    deleting === model.id
                      ? 'text-white bg-red-600 px-3 py-1 rounded'
                      : 'text-red-500 hover:text-red-700'
                  }`}
                >
                  {deleting === model.id ? 'Confirm?' : 'Delete'}
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-gray-500 text-center py-8">No models registered</p>
        )}
      </div>
    </div>
  );
}
