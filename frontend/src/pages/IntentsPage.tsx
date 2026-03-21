import { useState } from 'react';
import { useApi } from '../hooks/useApi';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorBanner } from '../components/common/ErrorBanner';
import { intentsApi } from '../api/intents';
import { SESSION_KEYS } from '../api/client';
import type { Intent } from '../types/api';

export function IntentsPage() {
  const tenantId = sessionStorage.getItem(SESSION_KEYS.tenantId) || '';
  const { data: intents, loading, error, refetch } = useApi(
    () => intentsApi.list(tenantId).catch(() => []),
    [tenantId],
  );

  const [showForm, setShowForm] = useState(false);
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    examples: [''],
    target_model: '',
  });
  const [submitting, setSubmitting] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const handleCreate = async () => {
    setSubmitting(true);
    setCreateError(null);
    try {
      await intentsApi.create(tenantId, {
        ...formData,
        examples: formData.examples.filter(e => e.trim()),
      });
      setShowForm(false);
      setFormData({ name: '', description: '', examples: [''], target_model: '' });
      refetch();
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : 'Failed to create intent');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (intent: Intent) => {
    if (deleting === intent.id) {
      setDeleteError(null);
      try {
        await intentsApi.delete(tenantId, intent.id);
        setDeleting(null);
        refetch();
      } catch (err) {
        setDeleteError(err instanceof Error ? err.message : 'Delete failed');
      }
    } else {
      setDeleting(intent.id);
      setDeleteError(null);
    }
  };

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onRetry={refetch} />;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-gray-900">Custom Intents</h2>
        <button
          onClick={() => setShowForm(!showForm)}
          className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-blue-700"
        >
          {showForm ? 'Cancel' : 'New Intent'}
        </button>
      </div>

      {createError && <ErrorBanner message={createError} onRetry={() => setCreateError(null)} />}
      {deleteError && <ErrorBanner message={deleteError} onRetry={() => setDeleteError(null)} />}

      {showForm && (
        <div className="bg-white rounded-lg shadow p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="summarization"
              className="w-full border rounded-lg px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
            <textarea
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              placeholder="Requests asking to summarize content"
              className="w-full border rounded-lg px-3 py-2 text-sm"
              rows={2}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Examples</label>
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
                  className="flex-1 border rounded-lg px-3 py-2 text-sm"
                />
                {formData.examples.length > 1 && (
                  <button
                    type="button"
                    onClick={() => {
                      const newExamples = formData.examples.filter((_, j) => j !== i);
                      setFormData({ ...formData, examples: newExamples });
                    }}
                    className="text-red-500 hover:text-red-700"
                  >
                    ✕
                  </button>
                )}
              </div>
            ))}
            <button
              type="button"
              onClick={() => setFormData({ ...formData, examples: [...formData.examples, ''] })}
              className="text-blue-600 text-sm hover:text-blue-700"
            >
              + Add Example
            </button>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Target Model (optional)
            </label>
            <input
              type="text"
              value={formData.target_model}
              onChange={(e) => setFormData({ ...formData, target_model: e.target.value })}
              placeholder="gpt-4o"
              className="w-full border rounded-lg px-3 py-2 text-sm"
            />
          </div>
          <button
            onClick={handleCreate}
            disabled={submitting || !formData.name || formData.examples.every(e => !e.trim())}
            className="bg-green-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-green-700 disabled:opacity-50"
          >
            {submitting ? 'Creating...' : 'Create Intent'}
          </button>
        </div>
      )}

      <div className="bg-white rounded-lg shadow">
        {Array.isArray(intents) && intents.length > 0 ? (
          <div className="divide-y">
            {intents.map((intent) => (
              <div key={intent.id} className="p-4 flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{intent.name}</span>
                    {!intent.is_active && (
                      <span className="text-xs bg-red-100 text-red-800 px-2 py-0.5 rounded">
                        inactive
                      </span>
                    )}
                  </div>
                  {intent.description && (
                    <p className="text-sm text-gray-500 mt-1">{intent.description}</p>
                  )}
                  <p className="text-xs text-gray-400 mt-1">threshold: {intent.threshold}</p>
                </div>
                <button
                  onClick={() => handleDelete(intent)}
                  onBlur={() => setDeleting(null)}
                  className={`text-sm ${
                    deleting === intent.id
                      ? 'text-white bg-red-600 px-3 py-1 rounded'
                      : 'text-red-500 hover:text-red-700'
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
