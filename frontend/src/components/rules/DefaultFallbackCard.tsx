'use client';

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { routesApi } from '../../api/routes';
import type { RouteCard as RouteCardType } from '../../api/routes';
import type { TenantModel } from '../../types/api';
import { modelDisplayLabel } from '../../utils/modelLabel';

interface Props {
  tenantId: string;
  card: RouteCardType | null;
  models: TenantModel[];
  onChange: () => void;
}

/**
 * Always-visible card at the bottom of the routes list. Wraps the
 * `is_default=true` rule that the engine falls back to when no other rule
 * matches. If no default exists yet, prompts the operator to pick one —
 * without it, every unmatched chat request returns 400.
 */
export function DefaultFallbackCard({ tenantId, card, models, onChange }: Props) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedModel, setSelectedModel] = useState(card?.targetModel || '');

  const isConfigured = !!card;

  const handleSave = async (model: string) => {
    if (!model) return;
    setBusy(true);
    setError(null);
    try {
      await routesApi.setDefaultModel(tenantId, model);
      setSelectedModel(model);
      onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : t('routes.default.saveFailed'));
    } finally {
      setBusy(false);
    }
  };

  const handleClear = async () => {
    setBusy(true);
    setError(null);
    try {
      await routesApi.clearDefaultModel(tenantId);
      setSelectedModel('');
      onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : t('routes.default.clearFailed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="bg-surface-container-low rounded-2xl border border-primary/15 p-6 flex flex-col md:flex-row md:items-center gap-4 group">
      <div className="flex items-center gap-3 flex-1 min-w-0">
        <span className="material-symbols-outlined text-primary">flag</span>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-on-surface">{t('routes.default.title')}</span>
            {isConfigured ? (
              <span className="px-2 py-0.5 bg-primary/10 text-primary text-[10px] font-bold rounded border border-primary/20 uppercase">
                {t('routes.default.active')}
              </span>
            ) : (
              <span className="px-2 py-0.5 bg-error/10 text-error text-[10px] font-bold rounded border border-error/20 uppercase">
                {t('routes.default.missing')}
              </span>
            )}
          </div>
          <p className="text-xs text-on-surface-variant mt-1">
            {isConfigured
              ? t('routes.default.configured')
              : t('routes.default.missingHint')}
          </p>
        </div>
      </div>

      <div className="flex items-center gap-3 w-full min-w-0 md:w-auto">
        <select
          value={selectedModel}
          onChange={(e) => handleSave(e.target.value)}
          disabled={busy || models.length === 0}
          className="bg-surface-container-highest border-none rounded-xl py-2 px-3 text-sm font-mono w-full min-w-0 max-w-full focus:ring-1 focus:ring-primary/40 disabled:opacity-50"
        >
          {models.map((m) => (
            <option key={m.id} value={m.model_name}>
              {modelDisplayLabel(m)}
            </option>
          ))}
        </select>
        {isConfigured && (
          <button
            onClick={handleClear}
            disabled={busy}
            className="text-xs font-bold text-on-surface-variant hover:text-error transition-colors px-2 shrink-0"
            title={t('routes.default.clearTitle')}
          >
            {t('routes.default.clear')}
          </button>
        )}
      </div>

      {error && <div className="text-xs text-error w-full">{error}</div>}
    </div>
  );
}
