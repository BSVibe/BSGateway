import { useState } from 'react';
import type { TenantModel } from '../../types/api';
import type { RouteCard as RouteCardType } from '../../api/routes';
import { routesApi } from '../../api/routes';
import { useDeleteConfirm } from '../../hooks/useDeleteConfirm';

interface RouteCardProps {
  card: RouteCardType;
  tenantId: string;
  models: TenantModel[];
  onUpdate: () => void;
  onDelete: (intentId: string | null, ruleId: string) => void;
  onMoveUp?: () => void;
  onMoveDown?: () => void;
  canMoveUp?: boolean;
  canMoveDown?: boolean;
}

export function RouteCard({
  card,
  tenantId,
  models,
  onUpdate,
  onDelete,
  onMoveUp,
  onMoveDown,
  canMoveUp = false,
  canMoveDown = false,
}: RouteCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [newExample, setNewExample] = useState('');
  const [savingExample, setSavingExample] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [updatingModel, setUpdatingModel] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { deleting, handleDelete } = useDeleteConfirm();

  const handleToggle = async () => {
    if (toggling) return;
    setToggling(true);
    setError(null);
    try {
      await routesApi.toggleActive(tenantId, card.ruleId, !card.isActive);
      onUpdate();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to toggle');
    } finally {
      setToggling(false);
    }
  };

  const handleModelChange = async (newModel: string) => {
    if (newModel === card.targetModel || updatingModel) return;
    setUpdatingModel(true);
    setError(null);
    try {
      await routesApi.updateModel(tenantId, card.ruleId, newModel);
      onUpdate();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update model');
    } finally {
      setUpdatingModel(false);
    }
  };

  const handleAddExample = async () => {
    if (!newExample.trim() || !card.intentId || savingExample) return;
    setSavingExample(true);
    setError(null);
    try {
      await routesApi.addExample(tenantId, card.intentId, newExample.trim());
      setNewExample('');
      onUpdate();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add example');
    } finally {
      setSavingExample(false);
    }
  };

  const handleRemoveExample = async (exampleId: string) => {
    if (!card.intentId) return;
    try {
      await routesApi.removeExample(tenantId, card.intentId, exampleId);
      onUpdate();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to remove example');
    }
  };

  // Default fallback rules are rendered separately by DefaultFallbackCard;
  // RoutesPage filters them out before passing into this component.
  if (card.isDefault) return null;

  return (
    <div className="bg-surface-container-low rounded-2xl border border-outline-variant/5 hover:border-outline-variant/20 transition-colors group">
      <div className="p-6 flex items-start gap-4">
        {/* Active toggle dot */}
        <button
          onClick={handleToggle}
          disabled={toggling}
          className={`mt-1.5 w-3 h-3 rounded-full flex-shrink-0 transition-all ${
            card.isActive
              ? 'bg-tertiary shadow-[0_0_8px_rgba(143,213,255,0.5)]'
              : 'bg-on-surface-variant/40'
          } ${toggling ? 'opacity-60' : 'hover:scale-125'}`}
          title={card.isActive ? 'Active — click to disable' : 'Inactive — click to enable'}
        />

        {/* Center: description + model */}
        <div className="flex-1 min-w-0">
          <p className="text-on-surface text-sm leading-relaxed">{card.description}</p>
          <div className="mt-3 flex items-center gap-3 flex-wrap">
            <div className="flex items-center gap-2 bg-surface-container-highest rounded-xl px-3 py-1.5">
              <span className="material-symbols-outlined text-on-surface-variant text-sm">
                arrow_forward
              </span>
              <select
                value={card.targetModel}
                onChange={(e) => handleModelChange(e.target.value)}
                disabled={updatingModel}
                className="bg-transparent border-none text-xs font-mono text-on-surface focus:outline-none disabled:opacity-50 cursor-pointer"
              >
                {!models.some((m) => m.model_name === card.targetModel) && (
                  <option value={card.targetModel}>{card.targetModel}</option>
                )}
                {models.map((m) => (
                  <option key={m.id} value={m.model_name}>
                    {m.model_name}
                  </option>
                ))}
              </select>
            </div>
            <span className="px-2 py-0.5 bg-on-surface-variant/10 text-on-surface-variant text-[10px] font-black rounded border border-outline-variant/10 uppercase">
              P{card.priority}
            </span>
            {card.intentId && (
              <button
                onClick={() => setExpanded(!expanded)}
                className="flex items-center gap-1 text-xs text-on-surface-variant hover:text-on-surface transition-colors"
              >
                <span className="material-symbols-outlined text-sm">
                  {expanded ? 'expand_less' : 'expand_more'}
                </span>
                <span>
                  {card.examples.length} example{card.examples.length !== 1 ? 's' : ''}
                </span>
              </button>
            )}
          </div>
        </div>

        {/* Reorder + Delete buttons */}
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          {onMoveUp && (
            <button
              onClick={onMoveUp}
              disabled={!canMoveUp}
              className="p-1.5 rounded-lg hover:bg-surface-container-highest text-on-surface-variant hover:text-on-surface transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
              title="Move up (higher priority)"
            >
              <span className="material-symbols-outlined text-sm">arrow_upward</span>
            </button>
          )}
          {onMoveDown && (
            <button
              onClick={onMoveDown}
              disabled={!canMoveDown}
              className="p-1.5 rounded-lg hover:bg-surface-container-highest text-on-surface-variant hover:text-on-surface transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
              title="Move down (lower priority)"
            >
              <span className="material-symbols-outlined text-sm">arrow_downward</span>
            </button>
          )}
          <button
            onClick={() =>
              handleDelete(card.ruleId, () =>
                routesApi.delete(tenantId, card.intentId, card.ruleId).then(() => {
                  onDelete(card.intentId, card.ruleId);
                }),
              )
            }
            className={`p-2 rounded-lg transition-all ${
              deleting === card.ruleId
                ? 'bg-error/20 text-error'
                : 'hover:bg-error/10 text-on-surface-variant hover:text-error'
            }`}
            title="Delete rule"
          >
            <span className="material-symbols-outlined text-sm">
              {deleting === card.ruleId ? 'check' : 'delete'}
            </span>
          </button>
        </div>
      </div>

      {/* Expandable examples section */}
      {expanded && card.intentId && (
        <div className="px-6 pb-6 pl-[3.25rem] space-y-3 border-t border-outline-variant/5 pt-4">
          <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">
            Example phrases
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
                    title="Remove example"
                  >
                    <span className="material-symbols-outlined text-sm">close</span>
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-on-surface-variant/60 italic">
              No examples yet — add one below to improve intent matching.
            </p>
          )}
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={newExample}
              onChange={(e) => setNewExample(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleAddExample();
              }}
              placeholder="Add an example phrase..."
              className="flex-1 bg-surface-container-highest border-none rounded-xl py-2 px-3 text-sm focus:ring-1 focus:ring-primary/40 placeholder:text-on-surface-variant/30"
            />
            <button
              onClick={handleAddExample}
              disabled={savingExample || !newExample.trim()}
              className="px-3 py-2 bg-primary-container text-on-primary rounded-xl text-xs font-bold hover:brightness-110 active:scale-95 transition-all disabled:opacity-50"
            >
              {savingExample ? 'Adding...' : 'Add'}
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="px-6 pb-4 text-xs text-error">{error}</div>
      )}
    </div>
  );
}
