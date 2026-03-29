import { useApi } from '../hooks/useApi';
import { useForm } from '../hooks/useForm';
import { useDeleteConfirm } from '../hooks/useDeleteConfirm';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorBanner } from '../components/common/ErrorBanner';
import { intentsApi } from '../api/intents';
import { useAuth } from '../hooks/useAuth';


interface IntentFormData {
  name: string;
  description: string;
  examples: string[];
  target_model: string;
}

const INITIAL_INTENT: IntentFormData = { name: '', description: '', examples: [''], target_model: '' };

export function IntentsPage() {
  const { tenantId } = useAuth();
  const tid = tenantId || '';
  const { data: intents, loading, error, refetch } = useApi(
    () => intentsApi.list(tid).catch(() => []),
    [tid],
  );

  const {
    formData, setFormData, showForm, setShowForm,
    submitting, createError, setCreateError, handleCreate,
  } = useForm<IntentFormData>({
    initialValues: INITIAL_INTENT,
    validate: (v) => !v.name.trim() ? 'Name is required' : null,
    onSubmit: async (v) => {
      await intentsApi.create(tid, { ...v, examples: v.examples.filter(e => e.trim()) });
      refetch();
    },
  });
  const { deleting, deleteError, handleDelete: onDelete, setDeleteError } = useDeleteConfirm();

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onRetry={refetch} />;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-gray-50">Custom Intents</h2>
        <button
          onClick={() => setShowForm(!showForm)}
          className="bg-accent-500 text-gray-950 px-4 py-2 rounded-lg text-sm font-medium hover:bg-accent-400"
        >
          {showForm ? 'Cancel' : 'New Intent'}
        </button>
      </div>

      {createError && <ErrorBanner message={createError} onRetry={() => setCreateError(null)} />}
      {deleteError && <ErrorBanner message={deleteError} onRetry={() => setDeleteError(null)} />}

      {showForm && (
        <div className="bg-gray-900 rounded-lg border border-gray-700 p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Name</label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="summarization"
              className="w-full border border-gray-700 rounded-lg px-3 py-2 text-sm bg-gray-900"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Description</label>
            <textarea
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              placeholder="Requests asking to summarize content"
              className="w-full border border-gray-700 rounded-lg px-3 py-2 text-sm bg-gray-900"
              rows={2}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Examples</label>
            {formData.examples.map((ex, i) => (
              <div key={i} className="flex gap-2 mb-2">
                <input
                  type="text"
                  value={ex}
                  onChange={(e) => {
                    const newExamples = [...formData.examples];
                    newExamples[i] = e.target.value;
                    setFormData({ ...formData, examples: newExamples });
                  }}
                  placeholder="e.g., 'Please summarize this...'"
                  className="flex-1 border border-gray-700 rounded-lg px-3 py-2 text-sm bg-gray-900"
                />
                {formData.examples.length > 1 && (
                  <button
                    type="button"
                    onClick={() => {
                      const newExamples = formData.examples.filter((_, j) => j !== i);
                      setFormData({ ...formData, examples: newExamples });
                    }}
                    className="text-red-400 hover:text-red-300"
                  >
                    ✕
                  </button>
                )}
              </div>
            ))}
            <button
              type="button"
              onClick={() => setFormData({ ...formData, examples: [...formData.examples, ''] })}
              className="text-accent-500 text-sm hover:text-accent-400"
            >
              + Add Example
            </button>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              Target Model (optional)
            </label>
            <input
              type="text"
              value={formData.target_model}
              onChange={(e) => setFormData({ ...formData, target_model: e.target.value })}
              placeholder="gpt-4o"
              className="w-full border border-gray-700 rounded-lg px-3 py-2 text-sm bg-gray-900"
            />
          </div>
          <button
            onClick={handleCreate}
            disabled={submitting || !formData.name.trim() || formData.examples.every(e => !e.trim())}
            className="bg-accent-500 text-gray-950 px-4 py-2 rounded-lg text-sm font-medium hover:bg-accent-400 disabled:opacity-50"
          >
            {submitting ? 'Creating...' : 'Create Intent'}
          </button>
        </div>
      )}

      <div className="bg-gray-900 rounded-lg border border-gray-700">
        {Array.isArray(intents) && intents.length > 0 ? (
          <div className="divide-y divide-gray-800">
            {intents.map((intent) => (
              <div key={intent.id} className="p-4 flex items-center justify-between hover:bg-gray-800/50 transition-colors">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-gray-50">{intent.name}</span>
                    {!intent.is_active && (
                      <span className="text-xs bg-red-500/15 text-red-400 px-2 py-0.5 rounded">
                        inactive
                      </span>
                    )}
                  </div>
                  {intent.description && (
                    <p className="text-sm text-gray-500 mt-1">{intent.description}</p>
                  )}
                  <p className="text-xs text-gray-500 mt-1">threshold: {intent.threshold}</p>
                </div>
                <button
                  onClick={() => onDelete(intent.id, () => intentsApi.delete(tid, intent.id), refetch)}
                  className={`text-sm ${
                    deleting === intent.id
                      ? 'text-white bg-red-600 px-3 py-1 rounded'
                      : 'text-red-400 hover:text-red-300'
                  }`}
                >
                  {deleting === intent.id ? 'Confirm?' : 'Delete'}
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-gray-500 text-center py-8">No intents defined</p>
        )}
      </div>
    </div>
  );
}
