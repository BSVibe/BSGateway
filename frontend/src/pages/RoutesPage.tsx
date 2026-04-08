import { useState } from 'react';
import { useAuth } from '../hooks/useAuth';
import { useApi } from '../hooks/useApi';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorBanner } from '../components/common/ErrorBanner';
import { RouteCard } from '../components/rules/RouteCard';
import { routesApi } from '../api/routes';
import type { TenantModel } from '../types/api';

interface CreateFormData {
  description: string;
  targetModel: string;
  examples: string[];
}

const INITIAL_FORM: CreateFormData = {
  description: '',
  targetModel: '',
  examples: [''],
};

function CreateModal({
  tenantId,
  models,
  onClose,
  onCreated,
}: {
  tenantId: string;
  models: TenantModel[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [formData, setFormData] = useState<CreateFormData>({
    ...INITIAL_FORM,
    targetModel: models[0]?.model_name || '',
  });
  const [showExamples, setShowExamples] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleCreate = async () => {
    if (!formData.description.trim()) {
      setError('Description is required');
      return;
    }
    if (!formData.targetModel.trim()) {
      setError('Target model is required');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await routesApi.create(tenantId, {
        description: formData.description,
        targetModel: formData.targetModel,
        examples: formData.examples.filter((e) => e.trim()),
      });
      onCreated();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create rule');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-surface/80 backdrop-blur-sm z-[60] flex items-center justify-center p-4">
      <div className="bg-surface-container-low w-full max-w-2xl rounded-3xl border border-outline-variant/10 shadow-2xl overflow-hidden">
        <div className="px-8 py-6 border-b border-outline-variant/10 flex items-center justify-between bg-surface-container/30">
          <div>
            <h3 className="text-2xl font-bold text-on-surface">Add Routing Rule</h3>
            <p className="text-xs text-on-surface-variant uppercase tracking-widest font-bold mt-1">
              New Rule
            </p>
          </div>
          <button
            onClick={onClose}
            className="w-10 h-10 flex items-center justify-center rounded-xl hover:bg-surface-container-highest transition-colors"
          >
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>

        <div className="p-8 space-y-6 max-h-[70vh] overflow-y-auto">
          {error && (
            <div className="text-xs text-error bg-error-container/20 border border-error/20 rounded-xl px-4 py-3">
              {error}
            </div>
          )}

          <div className="space-y-2">
            <label className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">
              어떤 요청을 라우팅할까요?
            </label>
            <textarea
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              placeholder="e.g. 코드 리뷰나 디버깅 관련 요청"
              rows={3}
              className="w-full bg-surface-container-highest border-none rounded-xl py-3 px-4 text-sm focus:ring-1 focus:ring-primary/40 placeholder:text-on-surface-variant/30 resize-none"
            />
          </div>

          <div className="space-y-2">
            <label className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">
              어떤 모델로 보낼까요?
            </label>
            {models.length > 0 ? (
              <select
                value={formData.targetModel}
                onChange={(e) => setFormData({ ...formData, targetModel: e.target.value })}
                className="w-full bg-surface-container-highest border-none rounded-xl py-3 px-4 text-sm font-mono focus:ring-1 focus:ring-primary/40"
              >
                <option value="">Select a model...</option>
                {models.map((m) => (
                  <option key={m.id} value={m.model_name}>
                    {m.model_name} ({m.provider})
                  </option>
                ))}
              </select>
            ) : (
              <div className="bg-surface-container-highest rounded-xl p-4 text-sm text-on-surface-variant">
                No models registered yet.{' '}
                <a href="/models" className="text-primary font-bold hover:underline">
                  Register a model first
                </a>
                .
              </div>
            )}
          </div>

          <div className="space-y-2">
            <button
              type="button"
              onClick={() => setShowExamples(!showExamples)}
              className="text-xs font-bold uppercase tracking-widest text-on-surface-variant hover:text-on-surface flex items-center gap-1 transition-colors"
            >
              <span className="material-symbols-outlined text-sm">
                {showExamples ? 'expand_less' : 'expand_more'}
              </span>
              예시 문장 추가 (선택)
            </button>
            {showExamples && (
              <div className="space-y-2 pt-2">
                {formData.examples.map((ex, i) => (
                  <div key={i} className="flex gap-2">
                    <input
                      type="text"
                      value={ex}
                      onChange={(e) => {
                        const newExamples = [...formData.examples];
                        newExamples[i] = e.target.value;
                        setFormData({ ...formData, examples: newExamples });
                      }}
                      placeholder="e.g. '이 코드 리뷰해줘'"
                      className="flex-1 bg-surface-container-highest border-none rounded-xl py-3 px-4 text-sm focus:ring-1 focus:ring-primary/40 placeholder:text-on-surface-variant/30"
                    />
                    {formData.examples.length > 1 && (
                      <button
                        type="button"
                        onClick={() => {
                          const newExamples = formData.examples.filter((_, j) => j !== i);
                          setFormData({ ...formData, examples: newExamples });
                        }}
                        className="text-on-surface-variant hover:text-error transition-colors"
                      >
                        <span className="material-symbols-outlined">close</span>
                      </button>
                    )}
                  </div>
                ))}
                <button
                  type="button"
                  onClick={() =>
                    setFormData({ ...formData, examples: [...formData.examples, ''] })
                  }
                  className="text-primary text-xs font-bold flex items-center gap-1 hover:text-primary/80"
                >
                  <span className="material-symbols-outlined text-sm">add</span> Add Example
                </button>
              </div>
            )}
          </div>
        </div>

        <div className="px-8 py-6 border-t border-outline-variant/10 bg-surface-container/50 flex items-center justify-end gap-4">
          <button
            onClick={onClose}
            className="px-6 py-3 text-sm font-bold text-on-surface-variant hover:text-on-surface transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleCreate}
            disabled={
              submitting ||
              !formData.description.trim() ||
              !formData.targetModel.trim()
            }
            className="px-8 py-3 bg-primary-container text-on-primary rounded-xl font-bold shadow-lg shadow-primary-container/20 hover:scale-[1.02] active:scale-95 transition-all disabled:opacity-50"
          >
            {submitting ? 'Creating...' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  );
}

export function RoutesPage() {
  const { tenantId } = useAuth();
  const tid = tenantId || '';
  const {
    data: cards,
    loading,
    error,
    refetch,
  } = useApi(() => routesApi.list(tid), [tid]);
  const { data: models } = useApi(() => routesApi.listModels(tid), [tid]);

  const [showModal, setShowModal] = useState(false);

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onRetry={refetch} />;

  const allCards = cards || [];
  const modelList = models || [];

  return (
    <div className="p-8 max-w-4xl mx-auto space-y-8">
      {showModal && (
        <CreateModal
          tenantId={tid}
          models={modelList}
          onClose={() => setShowModal(false)}
          onCreated={refetch}
        />
      )}

      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
        <div>
          <h2 className="text-4xl font-extrabold tracking-tight text-on-surface mb-2">
            Routing Rules
          </h2>
          <p className="text-on-surface-variant max-w-xl">
            Describe what kind of requests should go to which model.
            {allCards.length > 0 &&
              ` ${allCards.length} rule${allCards.length !== 1 ? 's' : ''} configured.`}
          </p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="bg-primary-container text-on-primary px-6 py-3 rounded-xl font-bold flex items-center gap-2 hover:brightness-110 transition-all active:scale-95"
        >
          <span className="material-symbols-outlined">add_circle</span>
          Add Rule
        </button>
      </div>

      {allCards.length > 0 ? (
        <div className="space-y-3">
          {allCards.map((card) => (
            <RouteCard
              key={card.ruleId}
              card={card}
              tenantId={tid}
              models={modelList}
              onUpdate={refetch}
              onDelete={refetch}
            />
          ))}
        </div>
      ) : (
        <div className="bg-surface-container-low rounded-2xl border border-outline-variant/5 flex flex-col items-center justify-center py-16 min-h-[400px]">
          <div className="relative w-32 h-32 mb-8">
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="w-24 h-24 rounded-full border-2 border-primary/20 animate-pulse flex items-center justify-center">
                <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center">
                  <span className="material-symbols-outlined text-primary text-2xl">
                    alt_route
                  </span>
                </div>
              </div>
            </div>
          </div>
          <h3 className="text-xl font-bold mb-2 text-on-surface">No routing rules yet</h3>
          <p className="text-on-surface-variant text-center max-w-sm mb-6">
            Describe a kind of request and pick a model — that's it.
          </p>
          <button
            onClick={() => setShowModal(true)}
            className="text-primary font-bold hover:underline"
          >
            Create your first routing rule
          </button>
        </div>
      )}
    </div>
  );
}
