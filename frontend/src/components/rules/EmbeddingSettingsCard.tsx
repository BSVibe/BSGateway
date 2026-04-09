import { useCallback, useEffect, useState } from 'react';
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
      setError(err instanceof Error ? err.message : 'Failed to load embedding settings');
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleSave = async () => {
    if (!model.trim()) {
      setError('Model is required');
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
      setStatus(`Saved. Run "Re-embed" if you swapped models.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save settings');
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
      setStatus('Embedding disabled for this tenant.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to clear settings');
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
        `Re-embed complete: ${result.refreshed} refreshed, ${result.failed} failed (model: ${result.model}).`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to re-embed');
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
              Embedding model
              {isConfigured ? (
                <span className="text-[10px] px-2 py-0.5 bg-tertiary/15 text-tertiary rounded font-bold uppercase">
                  active
                </span>
              ) : (
                <span className="text-[10px] px-2 py-0.5 bg-on-surface-variant/10 text-on-surface-variant rounded font-bold uppercase">
                  disabled
                </span>
              )}
            </div>
            <div className="text-xs text-on-surface-variant mt-0.5">
              {isConfigured
                ? `${settings.model} — used to classify intents on incoming chat requests`
                : 'No embedding model configured. Intent rules will not match live traffic.'}
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
              Model
            </label>
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="text-embedding-3-small"
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
              API base <span className="text-on-surface-variant/40 normal-case font-normal">(optional, for self-hosted)</span>
            </label>
            <input
              type="text"
              value={apiBase}
              onChange={(e) => setApiBase(e.target.value)}
              placeholder="http://host.docker.internal:11434"
              className="w-full bg-surface-container-highest border-none rounded-xl py-3 px-4 text-sm font-mono focus:ring-1 focus:ring-primary/40 placeholder:text-on-surface-variant/30"
            />
          </div>

          <div className="flex flex-wrap items-center gap-3 pt-2">
            <button
              onClick={handleSave}
              disabled={saving || !model.trim()}
              className="px-5 py-2.5 bg-primary-container text-on-primary rounded-xl text-sm font-bold hover:brightness-110 active:scale-95 transition-all disabled:opacity-50"
            >
              {saving ? 'Saving...' : 'Save'}
            </button>
            <button
              onClick={handleReembed}
              disabled={reembedding || !isConfigured}
              className="px-5 py-2.5 bg-surface-container-highest text-on-surface rounded-xl text-sm font-bold hover:bg-surface-container-high active:scale-95 transition-all disabled:opacity-50"
              title="Backfill all examples with the current embedding model. Run after swapping models."
            >
              {reembedding ? 'Re-embedding...' : 'Re-embed examples'}
            </button>
            {isConfigured && (
              <button
                onClick={handleClear}
                disabled={saving}
                className="px-5 py-2.5 text-sm font-bold text-on-surface-variant hover:text-error transition-colors"
              >
                Disable
              </button>
            )}
          </div>

          <p className="text-[11px] text-on-surface-variant/70 leading-relaxed pt-1">
            Changing the model invalidates existing example embeddings — they are tagged with
            the model that produced them and skipped at classification time. Click{' '}
            <span className="font-bold">Re-embed examples</span> after a swap to refresh them
            with the new model in a single batch call.
          </p>
        </div>
      )}
    </div>
  );
}
