'use client';

import { useCallback } from 'react';
import { useT } from '@bsvibe/i18n';
import { ResponsiveTable } from '@bsvibe/ui';
import type { ResponsiveTableColumn } from '@bsvibe/ui';
import { useApi } from '../hooks/useApi';
import { useForm } from '../hooks/useForm';
import { useDeleteConfirm } from '../hooks/useDeleteConfirm';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorBanner } from '../components/common/ErrorBanner';
import { intentsApi } from '../api/intents';
import { useAuth } from '../hooks/useAuth';
import type { Intent } from '../types/api';


interface IntentFormData {
  name: string;
  description: string;
  examples: string[];
  target_model: string;
}

const INITIAL_INTENT: IntentFormData = { name: '', description: '', examples: [''], target_model: '' };

export function IntentsPage() {
  const t = useT('gateway');
  const { tenantId } = useAuth();
  const tid = tenantId || '';
  const loadIntents = useCallback(() => intentsApi.list(tid).catch(() => []), [tid]);
  const { data: intents, loading, error, refetch } = useApi(loadIntents);

  const {
    formData, setFormData, showForm, setShowForm,
    submitting, createError, setCreateError, handleCreate,
  } = useForm<IntentFormData>({
    initialValues: INITIAL_INTENT,
    validate: (v) => !v.name.trim() ? t('intents.form.validation') : null,
    onSubmit: async (v) => {
      await intentsApi.create(tid, { ...v, examples: v.examples.filter(e => e.trim()) });
      refetch();
    },
  });
  const { deleting, deleteError, handleDelete: onDelete, setDeleteError } = useDeleteConfirm();

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onRetry={refetch} />;

  const intentList: Intent[] = Array.isArray(intents) ? intents : [];

  const renderDeleteButton = (intent: Intent) => (
    <button
      onClick={() => onDelete(intent.id, () => intentsApi.delete(tid, intent.id), refetch)}
      className={`transition-colors ${
        deleting === intent.id ? 'text-error' : 'text-on-surface-variant hover:text-error'
      }`}
    >
      <span className="material-symbols-outlined">
        {deleting === intent.id ? 'check_circle' : 'delete'}
      </span>
    </button>
  );

  const columns: ResponsiveTableColumn<Intent>[] = [
    {
      key: 'name',
      header: t('intents.form.name'),
      cell: (intent) => (
        <div className="flex items-center gap-2">
          <span className="font-semibold text-on-surface">{intent.name}</span>
          {!intent.is_active && (
            <span className="text-[10px] bg-error/15 text-error px-2 py-0.5 rounded-full font-bold">
              {t('intents.list.inactive')}
            </span>
          )}
        </div>
      ),
    },
    {
      key: 'description',
      header: t('intents.form.description'),
      cellClassName: 'text-sm text-on-surface-variant',
      cell: (intent) => intent.description || '—',
    },
    {
      key: 'threshold',
      header: t('intents.table.threshold'),
      cellClassName: 'text-xs text-on-surface-variant/60',
      cell: (intent) => t('intents.list.threshold', { value: intent.threshold }),
    },
    {
      key: 'actions',
      header: t('intents.table.actions'),
      cellClassName: 'text-right',
      cell: renderDeleteButton,
    },
  ];

  const renderIntentCard = (intent: Intent) => (
    <div className="p-6 flex items-center justify-between hover:bg-surface-container/30 transition-colors">
      <div>
        <div className="flex items-center gap-2">
          <span className="font-semibold text-on-surface">{intent.name}</span>
          {!intent.is_active && (
            <span className="text-[10px] bg-error/15 text-error px-2 py-0.5 rounded-full font-bold">
              {t('intents.list.inactive')}
            </span>
          )}
        </div>
        {intent.description && (
          <p className="text-sm text-on-surface-variant mt-1">{intent.description}</p>
        )}
        <p className="text-xs text-on-surface-variant/60 mt-1">{t('intents.list.threshold', { value: intent.threshold })}</p>
      </div>
      {renderDeleteButton(intent)}
    </div>
  );

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
        <div>
          <h2 className="text-4xl font-extrabold tracking-tight text-on-surface mb-2">{t('intents.title')}</h2>
          <p className="text-on-surface-variant">{t('intents.subtitle')}</p>
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
          {showForm ? t('common.cancel') : t('intents.newIntent')}
        </button>
      </div>

      {createError && <ErrorBanner message={createError} onRetry={() => setCreateError(null)} />}
      {deleteError && <ErrorBanner message={deleteError} onRetry={() => setDeleteError(null)} />}

      {showForm && (
        <div className="bg-surface-container-low rounded-2xl border border-primary/20 p-8 space-y-6">
          <div className="space-y-2">
            <label className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">{t('intents.form.name')}</label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder={t('intents.form.namePlaceholder')}
              className="w-full bg-surface-container-highest border-none rounded-xl py-3 px-4 text-sm focus:ring-1 focus:ring-primary/40 placeholder:text-on-surface-variant/20"
            />
          </div>
          <div className="space-y-2">
            <label className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">{t('intents.form.description')}</label>
            <textarea
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              placeholder={t('intents.form.descriptionPlaceholder')}
              className="w-full bg-surface-container-highest border-none rounded-xl py-3 px-4 text-sm focus:ring-1 focus:ring-primary/40 placeholder:text-on-surface-variant/20 resize-none"
              rows={2}
            />
          </div>
          <div className="space-y-2">
            <label className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">{t('intents.form.examples')}</label>
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
                  placeholder={t('intents.form.examplePlaceholder')}
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
              <span className="material-symbols-outlined text-sm">add</span> {t('common.addExample')}
            </button>
          </div>
          <div className="space-y-2">
            <label className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">
              {t('intents.form.targetModel')} <span className="text-on-surface-variant/40 font-normal normal-case">{t('common.optional')}</span>
            </label>
            <input
              type="text"
              value={formData.target_model}
              onChange={(e) => setFormData({ ...formData, target_model: e.target.value })}
              placeholder={t('intents.form.targetModelPlaceholder')}
              className="w-full bg-surface-container-highest border-none rounded-xl py-3 px-4 text-sm font-mono focus:ring-1 focus:ring-primary/40 placeholder:text-on-surface-variant/20"
            />
          </div>
          <button
            onClick={handleCreate}
            disabled={submitting || !formData.name.trim() || formData.examples.every(e => !e.trim())}
            className="bg-primary-container text-on-primary px-6 py-3 rounded-xl font-bold hover:brightness-110 active:scale-95 transition-all disabled:opacity-50"
          >
            {submitting ? t('common.creating') : t('intents.form.create')}
          </button>
        </div>
      )}

      <div className="bg-surface-container-low rounded-2xl border border-outline-variant/5 overflow-hidden">
        <ResponsiveTable
          columns={columns}
          rows={intentList}
          rowKey={(intent) => intent.id}
          renderMobileCard={renderIntentCard}
          emptyMessage={
            <span className="flex flex-col items-center justify-center gap-4 py-8">
              <span className="material-symbols-outlined text-5xl text-on-surface-variant/30">target</span>
              <span className="text-sm text-on-surface-variant">{t('intents.empty.noIntents')}</span>
            </span>
          }
        />
      </div>
    </div>
  );
}
