import { useState } from 'react';
import { intentsApi } from '../api/intents';
import { useApi } from '../hooks/useApi';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorBanner } from '../components/common/ErrorBanner';
import type { Intent, IntentCreate } from '../types/api';

const TENANT_ID = localStorage.getItem('bsg_tenant_id') || '';

export function IntentsPage() {
  const { data: intents, loading, error, refetch } = useApi(
    () => intentsApi.list(TENANT_ID),
    [TENANT_ID],
  );
  const [showForm, setShowForm] = useState(false);
  const [formData, setFormData] = useState<IntentCreate>({
    name: '',
    description: '',
    threshold: 0.7,
    examples: [],
  });
  const [exampleInput, setExampleInput] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleCreate = async () => {
    setSubmitting(true);
    try {
      await intentsApi.create(TENANT_ID, formData);
      setShowForm(false);
      setFormData({ name: '', description: '', threshold: 0.7, examples: [] });
      refetch();
    } catch {
      alert('Failed to create intent');
    } finally {
      setSubmitting(false);
    }
  };

  const addExample = () => {
    if (exampleInput.trim()) {
      setFormData({
        ...formData,
        examples: [...(formData.examples || []), exampleInput.trim()],
      });
      setExampleInput('');
    }
  };

  const handleDelete = async (intent: Intent) => {
    if (!confirm(`Delete intent "${intent.name}"?`)) return;
    try {
      await intentsApi.delete(TENANT_ID, intent.id);
      refetch();
    } catch {
      alert('Failed to delete intent');
    }
  };

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onRetry={refetch} />;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-gray-900">Intents</h2>
        <button
          onClick={() => setShowForm(!showForm)}
          className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-blue-700"
        >
          {showForm ? 'Cancel' : 'New Intent'}
        </button>
      </div>

      {showForm && (
        <div className="bg-white rounded-lg shadow p-6 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
              <input
                type="text"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full border rounded-lg px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Threshold</label>
              <input
                type="number"
                step="0.1"
                min="0"
                max="1"
                value={formData.threshold}
                onChange={(e) => setFormData({ ...formData, threshold: parseFloat(e.target.value) || 0.7 })}
                className="w-full border rounded-lg px-3 py-2 text-sm"
              />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
            <input
              type="text"
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              className="w-full border rounded-lg px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Examples</label>
            <div className="flex gap-2">
              <input
                type="text"
                value={exampleInput}
                onChange={(e) => setExampleInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && addExample()}
                placeholder="Type an example and press Enter"
                className="flex-1 border rounded-lg px-3 py-2 text-sm"
              />
              <button onClick={addExample} className="px-3 py-2 bg-gray-200 rounded-lg text-sm">
                Add
              </button>
            </div>
            {formData.examples && formData.examples.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2">
                {formData.examples.map((ex, i) => (
                  <span key={i} className="bg-gray-100 text-sm px-2 py-1 rounded flex items-center gap-1">
                    {ex}
                    <button
                      onClick={() =>
                        setFormData({
                          ...formData,
                          examples: formData.examples?.filter((_, j) => j !== i),
                        })
                      }
                      className="text-gray-500 hover:text-red-500"
                    >
                      x
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>
          <button
            onClick={handleCreate}
            disabled={submitting || !formData.name}
            className="bg-green-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-green-700 disabled:opacity-50"
          >
            {submitting ? 'Creating...' : 'Create Intent'}
          </button>
        </div>
      )}

      <div className="bg-white rounded-lg shadow">
        {intents && intents.length > 0 ? (
          <div className="divide-y">
            {intents.map((intent) => (
              <div key={intent.id} className="p-4 flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{intent.name}</span>
                    <span className="text-xs bg-purple-100 text-purple-800 px-2 py-0.5 rounded">
                      threshold: {intent.threshold}
                    </span>
                    {!intent.is_active && (
                      <span className="text-xs bg-red-100 text-red-800 px-2 py-0.5 rounded">
                        inactive
                      </span>
                    )}
                  </div>
                  {intent.description && (
                    <p className="text-sm text-gray-500 mt-1">{intent.description}</p>
                  )}
                </div>
                <button
                  onClick={() => handleDelete(intent)}
                  className="text-red-500 hover:text-red-700 text-sm"
                >
                  Delete
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-gray-500 text-center py-8">No intents configured</p>
        )}
      </div>
    </div>
  );
}
