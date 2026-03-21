import { rulesApi } from '../api/rules';
import { useAuth } from '../hooks/useAuth';
import { useApi } from '../hooks/useApi';
import { useForm } from '../hooks/useForm';
import { useDeleteConfirm } from '../hooks/useDeleteConfirm';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorBanner } from '../components/common/ErrorBanner';
import type { RuleCreate } from '../types/api';

const INITIAL_RULE: RuleCreate = { name: '', priority: 0, target_model: '', is_default: false };

export function RulesPage() {
  const { tenantId } = useAuth();
  const tid = tenantId || '';
  const { data: rules, loading, error, refetch } = useApi(
    () => rulesApi.list(tid),
    [tid],
  );

  const {
    formData, setFormData, showForm, setShowForm,
    submitting, createError, setCreateError, handleCreate,
  } = useForm<RuleCreate>({
    initialValues: INITIAL_RULE,
    validate: (v) => (!v.name.trim() || !v.target_model.trim()) ? 'Name and target model are required' : null,
    onSubmit: async (v) => { await rulesApi.create(tid, v); refetch(); },
  });

  const { deleting, deleteError, handleDelete: onDelete, setDeleteError } = useDeleteConfirm();

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onRetry={refetch} />;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-gray-900">Routing Rules</h2>
        <button
          onClick={() => setShowForm(!showForm)}
          className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-blue-700"
        >
          {showForm ? 'Cancel' : 'New Rule'}
        </button>
      </div>

      {createError && <ErrorBanner message={createError} onRetry={() => setCreateError(null)} />}

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
              <label className="block text-sm font-medium text-gray-700 mb-1">Target Model</label>
              <input
                type="text"
                value={formData.target_model}
                onChange={(e) => setFormData({ ...formData, target_model: e.target.value })}
                className="w-full border rounded-lg px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Priority</label>
              <input
                type="number"
                value={formData.priority}
                onChange={(e) => setFormData({ ...formData, priority: parseInt(e.target.value) || 0 })}
                className="w-full border rounded-lg px-3 py-2 text-sm"
              />
            </div>
            <div className="flex items-end">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={formData.is_default}
                  onChange={(e) => setFormData({ ...formData, is_default: e.target.checked })}
                />
                <span className="text-sm text-gray-700">Default rule</span>
              </label>
            </div>
          </div>
          <button
            onClick={handleCreate}
            disabled={submitting || !formData.name.trim() || !formData.target_model.trim()}
            className="bg-green-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-green-700 disabled:opacity-50"
          >
            {submitting ? 'Creating...' : 'Create Rule'}
          </button>
        </div>
      )}

      {deleteError && <ErrorBanner message={deleteError} onRetry={() => setDeleteError(null)} />}

      <div className="bg-white rounded-lg shadow">
        {rules && rules.length > 0 ? (
          <div className="divide-y">
            {rules.sort((a, b) => a.priority - b.priority).map((rule) => (
              <div key={rule.id} className="p-4 flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs bg-gray-200 text-gray-700 px-2 py-0.5 rounded font-mono">
                      P{rule.priority}
                    </span>
                    <span className="font-medium">{rule.name}</span>
                    {rule.is_default && (
                      <span className="text-xs bg-yellow-100 text-yellow-800 px-2 py-0.5 rounded">
                        default
                      </span>
                    )}
                    {!rule.is_active && (
                      <span className="text-xs bg-red-100 text-red-800 px-2 py-0.5 rounded">
                        disabled
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-gray-500 mt-1">
                    Target: <span className="font-mono">{rule.target_model}</span>
                    {rule.conditions.length > 0 && ` · ${rule.conditions.length} condition(s)`}
                  </p>
                </div>
                <button
                  onClick={() => onDelete(rule.id, () => rulesApi.delete(tid, rule.id), refetch)}
                  className={`text-sm ${
                    deleting === rule.id
                      ? 'text-white bg-red-600 px-3 py-1 rounded'
                      : 'text-red-500 hover:text-red-700'
                  }`}
                >
                  {deleting === rule.id ? 'Confirm?' : 'Delete'}
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-gray-500 text-center py-8">No rules configured</p>
        )}
      </div>
    </div>
  );
}
