'use client';

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
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
        <div>
          <h2 className="text-4xl font-extrabold tracking-tight text-on-surface mb-2">Custom Intents</h2>
          <p className="text-on-surface-variant">Define intent patterns for semantic routing.</p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className={`px-6 py-3 rounded-xl font-bold flex items-center gap-2 transition-all active:scale-95 ${
            showForm
              ? 'bg-surface-container-high text-on-surface-variant hover:bg-surface-container-highest'
              : 'bg-primary-container text-on-primary hover:brightness-110'
          }`}
        >
          <span className="material-symbols-outlined text-sm">{showForm ? 'close' : 'add_circle'}</span>
          {showForm ? 'Cancel' : 'New Intent'}
        </button>
      </div>

      {createError && <ErrorBanner message={createError} onRetry={() => setCreateError(null)} />}
      {deleteError && <ErrorBanner message={deleteError} onRetry={() => setDeleteError(null)} />}

      {showForm && (
        <div className="bg-surface-container-low rounded-2xl border border-primary/20 p-8 space-y-6">
          <div className="space-y-2">
            <label className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">Name</label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="summarization"
              className="w-full bg-surface-container-highest border-none rounded-xl py-3 px-4 text-sm focus:ring-1 focus:ring-primary/40 placeholder:text-on-surface-variant/20"
            />
          </div>
          <div className="space-y-2">
            <label className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">Description</label>
            <textarea
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              placeholder="Requests asking to summarize content"
              className="w-full bg-surface-container-highest border-none rounded-xl py-3 px-4 text-sm focus:ring-1 focus:ring-primary/40 placeholder:text-on-surface-variant/20 resize-none"
              rows={2}
            />
          </div>
          <div className="space-y-2">
            <label className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">Examples</label>
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
                  className="flex-1 bg-surface-container-highest border-none rounded-xl py-3 px-4 text-sm focus:ring-1 focus:ring-primary/40 placeholder:text-on-surface-variant/20"
                />
                {formData.examples.length > 1 && (
                  <button
                    type="button"
                    onClick={() => {
                      const newExamples = formData.examples.filter((_, j) => j !== i);
                      setFormData({ ...formData, examples: newExamples });
                    }}
                    className="text-error hover:text-error/80 transition-colors"
                  >
                    <span className="material-symbols-outlined">close</span>
                  </button>
                )}
              </div>
            ))}
            <button
              type="button"
              onClick={() => setFormData({ ...formData, examples: [...formData.examples, ''] })}
              className="text-primary text-xs font-bold flex items-center gap-1 hover:text-primary/80"
            >
              <span className="material-symbols-outlined text-sm">add</span> Add Example
            </button>
          </div>
          <div className="space-y-2">
            <label className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">
              Target Model <span className="text-on-surface-variant/40 font-normal normal-case">(optional)</span>
            </label>
            <input
              type="text"
              value={formData.target_model}
              onChange={(e) => setFormData({ ...formData, target_model: e.target.value })}
              placeholder="gpt-4o"
              className="w-full bg-surface-container-highest border-none rounded-xl py-3 px-4 text-sm font-mono focus:ring-1 focus:ring-primary/40 placeholder:text-on-surface-variant/20"
            />
          </div>
          <button
            onClick={handleCreate}
            disabled={submitting || !formData.name.trim() || formData.examples.every(e => !e.trim())}
            className="bg-primary-container text-on-primary px-6 py-3 rounded-xl font-bold hover:brightness-110 active:scale-95 transition-all disabled:opacity-50"
          >
            {submitting ? 'Creating...' : 'Create Intent'}
          </button>
        </div>
      )}

      <div className="bg-surface-container-low rounded-2xl border border-outline-variant/5 overflow-hidden">
        {Array.isArray(intents) && intents.length > 0 ? (
          <div className="divide-y divide-outline-variant/5">
            {intents.map((intent) => (
              <div key={intent.id} className="p-6 flex items-center justify-between hover:bg-surface-container/30 transition-colors group">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-on-surface">{intent.name}</span>
                    {!intent.is_active && (
                      <span className="text-[10px] bg-error/15 text-error px-2 py-0.5 rounded-full font-bold">
                        inactive
                      </span>
                    )}
                  </div>
                  {intent.description && (
                    <p className="text-sm text-on-surface-variant mt-1">{intent.description}</p>
                  )}
                  <p className="text-xs text-on-surface-variant/60 mt-1">threshold: {intent.threshold}</p>
                </div>
                <button
                  onClick={() => onDelete(intent.id, () => intentsApi.delete(tid, intent.id), refetch)}
                  className={`transition-colors opacity-0 group-hover:opacity-100 ${
                    deleting === intent.id
                      ? 'text-error'
                      : 'text-on-surface-variant hover:text-error'
                  }`}
                >
                  <span className="material-symbols-outlined">
                    {deleting === intent.id ? 'check_circle' : 'delete'}
                  </span>
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-16">
            <span className="material-symbols-outlined text-5xl text-on-surface-variant/30 mb-4">target</span>
            <p className="text-sm text-on-surface-variant">No intents defined</p>
          </div>
        )}
      </div>
    </div>
  );
}
