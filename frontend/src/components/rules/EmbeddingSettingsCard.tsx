'use client';

import { useCallback, useEffect, useState } from 'react';
import { useT } from '@bsvibe/i18n';
import { routesApi } from '../../api/routes';
import type { EmbeddingSettings } from '../../types/api';

interface Props {
  tenantId: string;
}

const PRESETS: { label: string; model: string; api_base?: string }[] = [
  { label: 'OpenAI text-embedding-3-small', model: 'text-embedding-3-small' },
  { label: 'OpenAI text-embedding-3-large', model: 'text-embedding-3-large' },
  {
    label: 'Ollama nomic-embed-text',
    model: 'ollama/nomic-embed-text',
    api_base: 'http://host.docker.internal:11434',
  },
];

export function EmbeddingSettingsCard({ tenantId }: Props) {
  const t = useT('gateway');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [reembedding, setReembedding] = useState(false);
  const [settings, setSettings] = useState<EmbeddingSettings | null>(null);
  const [model, setModel] = useState('');
  const [apiBase, setApiBase] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await routesApi.getEmbeddingSettings(tenantId);
      setSettings(result);
      setModel(result?.model ?? '');
      setApiBase(result?.api_base ?? '');
    } catch (err) {
      setError(err instanceof Error ? err.message : t('routes.embedding.loadFailed'));
    } finally {
      setLoading(false);
    }
    // `t` intentionally omitted — see DashboardPage.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);

  useEffect(() => {
    const id = window.setTimeout(() => {
      refresh();
    }, 0);
    return () => window.clearTimeout(id);
  }, [refresh]);

  const handleSave = async () => {
    if (!model.trim()) {
      setError(t('routes.embedding.modelRequired'));
      return;
    }
    setSaving(true);
    setError(null);
    setStatus(null);
    try {
      const result = await routesApi.putEmbeddingSettings(tenantId, {
        model: model.trim(),
        api_base: apiBase.trim() || null,
        timeout: 10,
        max_input_length: 8000,
      });
      setSettings(result);
      setStatus(t('routes.embedding.savedRunReembed'));
    } catch (err) {
      setError(err instanceof Error ? err.message : t('routes.embedding.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  const handleClear = async () => {
    setSaving(true);
    setError(null);
    setStatus(null);
    try {
      await routesApi.deleteEmbeddingSettings(tenantId);
      setSettings(null);
      setModel('');
      setApiBase('');
      setStatus(t('routes.embedding.disabledMessage'));
    } catch (err) {
      setError(err instanceof Error ? err.message : t('routes.embedding.clearFailed'));
    } finally {
      setSaving(false);
    }
  };

  const handleReembed = async () => {
    setReembedding(true);
    setError(null);
    setStatus(null);
    try {
      const result = await routesApi.reembed(tenantId);
      setStatus(
        t('routes.embedding.reembedComplete', {
          refreshed: result.refreshed,
          failed: result.failed,
          model: result.model,
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : t('routes.embedding.reembedFailed'));
    } finally {
      setReembedding(false);
    }
  };

  if (loading) return null;

  const isConfigured = !!settings;

  return (
    <div className="bg-surface-container-low rounded-2xl border border-outline-variant/10 overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full px-6 py-4 flex items-center justify-between hover:bg-surface-container/30 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className="material-symbols-outlined text-primary">tune</span>
          <div className="text-left">
            <div className="text-sm font-bold text-on-surface flex items-center gap-2">
              {t('routes.embedding.header')}
              {isConfigured ? (
                <span className="text-[10px] px-2 py-0.5 bg-tertiary/15 text-tertiary rounded font-bold uppercase">
                  {t('routes.embedding.active')}
                </span>
              ) : (
                <span className="text-[10px] px-2 py-0.5 bg-on-surface-variant/10 text-on-surface-variant rounded font-bold uppercase">
                  {t('routes.embedding.disabled')}
                </span>
              )}
            </div>
            <div className="text-xs text-on-surface-variant mt-0.5">
              {isConfigured
                ? t('routes.embedding.activeHint', { model: settings.model })
                : t('routes.embedding.disabledHint')}
            </div>
          </div>
        </div>
        <span className="material-symbols-outlined text-on-surface-variant">
          {expanded ? 'expand_less' : 'expand_more'}
        </span>
      </button>

      {expanded && (
        <div className="px-6 pb-6 pt-2 space-y-4 border-t border-outline-variant/10">
          {error && (
            <div className="text-xs text-error bg-error-container/20 border border-error/20 rounded-xl px-4 py-3">
              {error}
            </div>
          )}
          {status && (
            <div className="text-xs text-tertiary bg-tertiary-container/15 border border-tertiary/20 rounded-xl px-4 py-3">
              {status}
            </div>
          )}

          <div className="space-y-2">
            <label className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">
              {t('routes.embedding.modelLabel')}
            </label>
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder={t('routes.embedding.modelPlaceholder')}
              className="w-full bg-surface-container-highest border-none rounded-xl py-3 px-4 text-sm font-mono focus:ring-1 focus:ring-primary/40 placeholder:text-on-surface-variant/30"
            />
            <div className="flex flex-wrap gap-2 pt-1">
              {PRESETS.map((p) => (
                <button
                  key={p.model}
                  type="button"
                  onClick={() => {
                    setModel(p.model);
                    setApiBase(p.api_base ?? '');
                  }}
                  className="text-[10px] font-bold uppercase tracking-widest px-2 py-1 rounded border border-outline-variant/20 text-on-surface-variant hover:text-primary hover:border-primary/40 transition-colors"
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">
              {t('routes.embedding.apiBaseLabel')} <span className="text-on-surface-variant/40 normal-case font-normal">{t('routes.embedding.apiBaseSelfHosted')}</span>
            </label>
            <input
              type="text"
              value={apiBase}
              onChange={(e) => setApiBase(e.target.value)}
              placeholder={t('routes.embedding.apiBasePlaceholder')}
              className="w-full bg-surface-container-highest border-none rounded-xl py-3 px-4 text-sm font-mono focus:ring-1 focus:ring-primary/40 placeholder:text-on-surface-variant/30"
            />
          </div>

          <div className="flex flex-wrap items-center gap-3 pt-2">
            <button
              onClick={handleSave}
              disabled={saving || !model.trim()}
              className="px-5 py-2.5 bg-primary-container text-on-primary rounded-xl text-sm font-bold hover:brightness-110 active:scale-95 transition-all disabled:opacity-50"
            >
              {saving ? t('routes.embedding.saving') : t('routes.embedding.save')}
            </button>
            <button
              onClick={handleReembed}
              disabled={reembedding || !isConfigured}
              className="px-5 py-2.5 bg-surface-container-highest text-on-surface rounded-xl text-sm font-bold hover:bg-surface-container-high active:scale-95 transition-all disabled:opacity-50"
              title={t('routes.embedding.reembedTitle')}
            >
              {reembedding ? t('routes.embedding.reembedding') : t('routes.embedding.reembed')}
            </button>
            {isConfigured && (
              <button
                onClick={handleClear}
                disabled={saving}
                className="px-5 py-2.5 text-sm font-bold text-on-surface-variant hover:text-error transition-colors"
              >
                {t('routes.embedding.disable')}
              </button>
            )}
          </div>

          <p className="text-[11px] text-on-surface-variant/70 leading-relaxed pt-1">
            {t('routes.embedding.swapHint')}
          </p>
        </div>
      )}
    </div>
  );
}
