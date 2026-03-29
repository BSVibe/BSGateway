import { tenantsApi } from '../api/tenants';
import { useAuth } from '../hooks/useAuth';
import { useApi } from '../hooks/useApi';
import { useForm } from '../hooks/useForm';
import { useDeleteConfirm } from '../hooks/useDeleteConfirm';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorBanner } from '../components/common/ErrorBanner';
import type { TenantModelCreate } from '../types/api';

const INITIAL_MODEL: TenantModelCreate = { model_name: '', litellm_model: '' };

export function ModelsPage() {
  const { tenantId } = useAuth();
  const tid = tenantId || '';
  const { data: models, loading, error, refetch } = useApi(
    () => tenantsApi.listModels(tid),
    [tid],
  );

  const {
    formData, setFormData, showForm, setShowForm,
    submitting, createError, setCreateError, handleCreate,
  } = useForm<TenantModelCreate>({
    initialValues: INITIAL_MODEL,
    validate: (v) => (!v.model_name.trim() || !v.litellm_model.trim()) ? 'Alias and model name are required' : null,
    onSubmit: async (v) => { await tenantsApi.createModel(tid, v); refetch(); },
  });

  const { deleting, deleteError, handleDelete: onDelete, setDeleteError } = useDeleteConfirm();

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onRetry={refetch} />;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-gray-50">Models</h2>
        <button
          onClick={() => setShowForm(!showForm)}
          className="bg-accent-500 text-gray-950 px-4 py-2 rounded-lg text-sm font-medium hover:bg-accent-400"
        >
          {showForm ? 'Cancel' : 'Register Model'}
        </button>
      </div>

      {createError && <ErrorBanner message={createError} onRetry={() => setCreateError(null)} />}

      {showForm && (
        <div className="bg-gray-900 rounded-lg border border-gray-700 p-6 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Alias</label>
              <input
                type="text"
                value={formData.model_name}
                onChange={(e) => setFormData({ ...formData, model_name: e.target.value })}
                placeholder="gpt-4o"
                className="w-full border border-gray-700 rounded-lg px-3 py-2 text-sm bg-gray-900"
              />
              <p className="text-xs text-gray-500 mt-1">Internal alias for this model</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Model Name</label>
              <input
                type="text"
                value={formData.litellm_model}
                onChange={(e) => setFormData({ ...formData, litellm_model: e.target.value })}
                placeholder="openai/gpt-4o"
                className="w-full border border-gray-700 rounded-lg px-3 py-2 text-sm font-mono bg-gray-900"
              />
              <p className="text-xs text-gray-500 mt-1">LiteLLM model ID (provider/model)</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">
                API Base <span className="text-gray-500 font-normal">(optional)</span>
              </label>
              <input
                type="text"
                value={formData.api_base || ''}
                onChange={(e) => setFormData({ ...formData, api_base: e.target.value || undefined })}
                placeholder="http://localhost:11434"
                className="w-full border border-gray-700 rounded-lg px-3 py-2 text-sm font-mono bg-gray-900"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">
                API Key <span className="text-gray-500 font-normal">(optional)</span>
              </label>
              <input
                type="password"
                value={formData.api_key || ''}
                onChange={(e) => setFormData({ ...formData, api_key: e.target.value || undefined })}
                placeholder="sk-..."
                className="w-full border border-gray-700 rounded-lg px-3 py-2 text-sm bg-gray-900"
              />
            </div>
          </div>
          <button
            onClick={handleCreate}
            disabled={submitting || !formData.model_name.trim() || !formData.litellm_model.trim()}
            className="bg-accent-500 text-gray-950 px-4 py-2 rounded-lg text-sm font-medium hover:bg-accent-400 disabled:opacity-50"
          >
            {submitting ? 'Registering...' : 'Register Model'}
          </button>
        </div>
      )}

      {deleteError && <ErrorBanner message={deleteError} onRetry={() => setDeleteError(null)} />}

      <div className="bg-gray-900 rounded-lg border border-gray-700">
        {models && models.length > 0 ? (
          <div className="divide-y divide-gray-800">
            {models.map((model) => (
              <div key={model.id} className="p-4 flex items-center justify-between hover:bg-gray-800/50 transition-colors">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-gray-50">{model.model_name}</span>
                    <span className="text-xs bg-accent-500/15 text-accent-500 px-2 py-0.5 rounded">
                      {model.litellm_model.split('/')[0]}
                    </span>
                    {!model.is_active && (
                      <span className="text-xs bg-red-500/15 text-red-400 px-2 py-0.5 rounded">
                        inactive
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-gray-500 mt-1 font-mono">{model.litellm_model}</p>
                  {model.api_base && (
                    <p className="text-xs text-gray-500 mt-0.5 font-mono">{model.api_base}</p>
                  )}
                </div>
                <button
                  onClick={() => onDelete(model.id, () => tenantsApi.deleteModel(tid, model.id), refetch)}
                  className={`text-sm ${
                    deleting === model.id
                      ? 'text-white bg-red-600 px-3 py-1 rounded'
                      : 'text-red-400 hover:text-red-300'
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
