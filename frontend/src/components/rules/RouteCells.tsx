'use client';

/**
 * Desktop-table cell renderers for the RoutesPage <ResponsiveTable>.
 *
 * RoutesPage dual-renders each RouteCard: the existing <RouteCard> card layout
 * is reused verbatim on mobile (via ResponsiveTable's renderMobileCard), while
 * the desktop `<table>` composes these small, individually-stateful cell
 * components. Each cell owns exactly the state RouteCard owned for that piece
 * (model-update in-flight, examples-panel expansion, …) so behavior — toggle,
 * model change, reorder, delete, add/remove example — is preserved 1:1.
 */

import { useState } from 'react';
import { useT } from '@bsvibe/i18n';
import type { TenantModel } from '../../types/api';
import type { RouteCard as RouteCardType } from '../../api/routes';
import { routesApi } from '../../api/routes';
import { useDeleteConfirm } from '../../hooks/useDeleteConfirm';
import { modelDisplayLabel } from '../../utils/modelLabel';

interface BaseProps {
  card: RouteCardType;
  tenantId: string;
  onUpdate: () => void;
}

/** Active/inactive status dot — click to toggle the rule. */
export function RouteStatusCell({ card, tenantId, onUpdate }: BaseProps) {
  const t = useT('gateway');
  const [toggling, setToggling] = useState(false);

  const handleToggle = async () => {
    if (toggling) return;
    setToggling(true);
    try {
      await routesApi.toggleActive(tenantId, card.ruleId, !card.isActive);
      onUpdate();
    } finally {
      setToggling(false);
    }
  };

  return (
    <button
      onClick={handleToggle}
      disabled={toggling}
      className={`w-3 h-3 rounded-full flex-shrink-0 transition-all ${
        card.isActive
          ? 'bg-tertiary shadow-[0_0_8px_rgba(143,213,255,0.5)]'
          : 'bg-on-surface-variant/40'
      } ${toggling ? 'opacity-60' : 'hover:scale-125'}`}
      title={card.isActive ? t('routes.card.active') : t('routes.card.inactive')}
    />
  );
}

/** Target-model selector. */
export function RouteModelCell({
  card,
  tenantId,
  onUpdate,
  models,
}: BaseProps & { models: TenantModel[] }) {
  const [updating, setUpdating] = useState(false);

  const handleModelChange = async (newModel: string) => {
    if (newModel === card.targetModel || updating) return;
    setUpdating(true);
    try {
      await routesApi.updateModel(tenantId, card.ruleId, newModel);
      onUpdate();
    } finally {
      setUpdating(false);
    }
  };

  return (
    <div className="inline-flex items-center gap-2 bg-surface-container-highest rounded-xl px-3 py-1.5">
      <span className="material-symbols-outlined text-on-surface-variant text-sm">arrow_forward</span>
      <select
        value={card.targetModel}
        onChange={(e) => handleModelChange(e.target.value)}
        disabled={updating}
        className="bg-transparent border-none text-xs font-mono text-on-surface focus:outline-none disabled:opacity-50 cursor-pointer"
      >
        {!models.some((m) => m.model_name === card.targetModel) && (
          <option value={card.targetModel}>{card.targetModel}</option>
        )}
        {models.map((m) => (
          <option key={m.id} value={m.model_name}>
            {modelDisplayLabel(m)}
          </option>
        ))}
      </select>
    </div>
  );
}

/** Examples toggle + inline expandable add/remove panel. */
export function RouteExamplesCell({ card, tenantId, onUpdate }: BaseProps) {
  const t = useT('gateway');
  const [expanded, setExpanded] = useState(false);
  const [newExample, setNewExample] = useState('');
  const [savingExample, setSavingExample] = useState(false);

  const handleAddExample = async () => {
    if (!newExample.trim() || !card.intentId || savingExample) return;
    setSavingExample(true);
    try {
      await routesApi.addExample(tenantId, card.intentId, newExample.trim());
      setNewExample('');
      onUpdate();
    } finally {
      setSavingExample(false);
    }
  };

  const handleRemoveExample = async (exampleId: string) => {
    if (!card.intentId) return;
    await routesApi.removeExample(tenantId, card.intentId, exampleId);
    onUpdate();
  };

  if (!card.intentId) {
    return <span className="text-xs text-on-surface-variant/40">—</span>;
  }

  return (
    <div className="space-y-3">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-xs text-on-surface-variant hover:text-on-surface transition-colors"
      >
        <span className="material-symbols-outlined text-sm">
          {expanded ? 'expand_less' : 'expand_more'}
        </span>
        <span>{t('routes.card.exampleCount', { count: card.examples.length })}</span>
      </button>

      {expanded && (
        <div className="space-y-3 border-t border-outline-variant/5 pt-3">
          <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">
            {t('routes.card.examplesHeader')}
          </div>
          {card.examples.length > 0 ? (
            <div className="space-y-2">
              {card.examples.map((ex) => (
                <div
                  key={ex.id}
                  className="flex items-center gap-2 bg-surface-container-highest/50 rounded-xl px-3 py-2 group/ex"
                >
                  <span className="material-symbols-outlined text-on-surface-variant/40 text-sm">
                    format_quote
                  </span>
                  <span className="text-sm text-on-surface flex-1">{ex.text}</span>
                  <button
                    onClick={() => handleRemoveExample(ex.id)}
                    className="opacity-0 group-hover/ex:opacity-100 text-on-surface-variant hover:text-error transition-all"
                    title={t('routes.card.removeExample')}
                  >
                    <span className="material-symbols-outlined text-sm">close</span>
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-on-surface-variant/60 italic">{t('routes.card.noExamples')}</p>
          )}
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={newExample}
              onChange={(e) => setNewExample(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleAddExample();
              }}
              placeholder={t('routes.card.addExamplePlaceholder')}
              className="flex-1 bg-surface-container-highest border-none rounded-xl py-2 px-3 text-sm focus:ring-1 focus:ring-primary/40 placeholder:text-on-surface-variant/30"
            />
            <button
              onClick={handleAddExample}
              disabled={savingExample || !newExample.trim()}
              className="px-3 py-2 bg-primary-container text-on-primary rounded-xl text-xs font-bold hover:brightness-110 active:scale-95 transition-all disabled:opacity-50"
            >
              {savingExample ? t('routes.card.adding') : t('routes.card.add')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** Reorder (up/down) + delete actions. */
export function RouteActionsCell({
  card,
  tenantId,
  onDelete,
  onMoveUp,
  onMoveDown,
  canMoveUp,
  canMoveDown,
}: {
  card: RouteCardType;
  tenantId: string;
  onDelete: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  canMoveUp: boolean;
  canMoveDown: boolean;
}) {
  const t = useT('gateway');
  const { deleting, handleDelete } = useDeleteConfirm();

  return (
    <div className="flex items-center justify-end gap-1">
      <button
        onClick={onMoveUp}
        disabled={!canMoveUp}
        className="p-1.5 rounded-lg hover:bg-surface-container-highest text-on-surface-variant hover:text-on-surface transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
        title={t('routes.card.moveUp')}
      >
        <span className="material-symbols-outlined text-sm">arrow_upward</span>
      </button>
      <button
        onClick={onMoveDown}
        disabled={!canMoveDown}
        className="p-1.5 rounded-lg hover:bg-surface-container-highest text-on-surface-variant hover:text-on-surface transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
        title={t('routes.card.moveDown')}
      >
        <span className="material-symbols-outlined text-sm">arrow_downward</span>
      </button>
      <button
        onClick={() =>
          handleDelete(card.ruleId, () =>
            routesApi.delete(tenantId, card.intentId, card.ruleId).then(() => {
              onDelete();
            }),
          )
        }
        className={`p-2 rounded-lg transition-all ${
          deleting === card.ruleId
            ? 'bg-error/20 text-error'
            : 'hover:bg-error/10 text-on-surface-variant hover:text-error'
        }`}
        title={t('routes.card.deleteRule')}
      >
        <span className="material-symbols-outlined text-sm">
          {deleting === card.ruleId ? 'check' : 'delete'}
        </span>
      </button>
    </div>
  );
}
