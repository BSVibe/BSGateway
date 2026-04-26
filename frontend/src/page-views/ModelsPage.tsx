'use client';

import { useState, useCallback } from 'react';
import { tenantsApi } from '../api/tenants';
import { executorsApi } from '../api/executors';
import { useAuth } from '../hooks/useAuth';
import { useApi } from '../hooks/useApi';
import { useForm } from '../hooks/useForm';
import { useDeleteConfirm } from '../hooks/useDeleteConfirm';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorBanner } from '../components/common/ErrorBanner';
import type { TenantModelCreate } from '../types/api';

const INITIAL_MODEL: TenantModelCreate = { model_name: '', litellm_model: '' };

const PROVIDER_COLORS: Record<string, string> = {
  openai: 'bg-green-500/15 text-green-400',
  anthropic: 'bg-violet-500/15 text-violet-400',
  google: 'bg-blue-500/15 text-blue-400',
  azure: 'bg-sky-500/15 text-sky-400',
  ollama: 'bg-orange-500/15 text-orange-400',
  cohere: 'bg-pink-500/15 text-pink-400',
  executor: 'bg-cyan-500/15 text-cyan-400',
};

function getProviderBadgeClass(litellmModel: string): string {
  const provider = litellmModel.split('/')[0].toLowerCase();
  return PROVIDER_COLORS[provider] || 'bg-secondary-container text-on-secondary-container';
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function ModelsPage() {
  const { tenantId } = useAuth();
  const tid = tenantId || '';
  const { data: models, loading, error, refetch } = useApi(
    () => tenantsApi.listModels(tid),
    [tid],
  );
  const { data: workers, refetch: refetchWorkers } = useApi(
    () => executorsApi.listWorkers(),
    [tid],
  );
  const { data: sparklines } = useApi(
    () => tenantsApi.getSparklines(tid, 7),
    [tid],
  );

  const {
    formData, setFormData, showForm, setShowForm,
    submitting, createError, setCreateError, handleCreate,
  } = useForm<TenantModelCreate>({
    initialValues: INITIAL_MODEL,
    validate: (v) => (!v.model_name.trim() || !v.litellm_model.trim()) ? 'Alias and model name are required' : null,
    onSubmit: async (v) => { await tenantsApi.createModel(tid, v); refetch(); },
  });

  const { deleting, deleteError, handleDelete: onDelete, setDeleteError } = useDeleteConfirm();

  const [showInstall, setShowInstall] = useState(false);
  const [copied, setCopied] = useState(false);

  // Install token state
  const { data: tokenStatus, refetch: refetchToken } = useApi(
    () => executorsApi.getInstallToken(),
    [tid],
  );
  const [mintedToken, setMintedToken] = useState<string | null>(null);
  const [tokenBusy, setTokenBusy] = useState(false);
  const [tokenCopied, setTokenCopied] = useState(false);

  const generateToken = useCallback(async () => {
    setTokenBusy(true);
    try {
      const res = await executorsApi.createInstallToken();
      setMintedToken(res.token);
      refetchToken();
    } finally {
      setTokenBusy(false);
    }
  }, [refetchToken]);

  const revokeToken = useCallback(async () => {
    setTokenBusy(true);
    try {
      await executorsApi.revokeInstallToken();
      setMintedToken(null);
      refetchToken();
    } finally {
      setTokenBusy(false);
    }
  }, [refetchToken]);

  const copyToken = useCallback(() => {
    if (!mintedToken) return;
    navigator.clipboard.writeText(mintedToken).then(() => {
      setTokenCopied(true);
      setTimeout(() => setTokenCopied(false), 2000);
    });
  }, [mintedToken]);

  // Use the current frontend origin. Vercel rewrites route
  // /api/v1/workers/install.sh and /source.tar.gz to the backend,
  // so curl against the frontend domain works in production.
  const gatewayOrigin = typeof window !== 'undefined' ? window.location.origin : '';
  const tokenPlaceholder = mintedToken ?? '<paste-install-token>';
  const installSnippet = `# Prereqs: python3.11+ and at least one of:
#   npm install -g @anthropic-ai/claude-code
#   npm install -g @openai/codex

# 1) Install (one-liner) — downloads sources, installs to ~/.bsgateway-worker
curl -fsSL ${gatewayOrigin}/api/v1/workers/install.sh | bash

# 2) Run — paste the install token minted above:
BSGATEWAY_INSTALL_TOKEN=${tokenPlaceholder} ~/.bsgateway-worker/bsgateway-worker

# Subsequent runs — the worker token is cached in ~/.bsgateway-worker/.env:
# ~/.bsgateway-worker/bsgateway-worker`;

  const copyInstall = useCallback(() => {
    navigator.clipboard.writeText(installSnippet).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [installSnippet]);

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onRetry={refetch} />;

  // Executor-backed models duplicate the Executor Workers section below,
  // so only show LLM models in the main grid.
  const llmModels = (models ?? []).filter((m) => m.provider !== 'executor');
  const modelCount = llmModels.length;
  const workerCount = workers?.length ?? 0;

  // Build a 7-bucket normalized sparkline for a given model name.
  // ``raw`` is an array of daily request counts (index 0 = oldest, last = today).
  // Returns percent heights (3..100) per bucket for visual display.
  // TODO: extract a <Sparkline bars color enabled /> component when a third
  // sparkline consumer appears (currently only LLM and executor worker cards).
  const sparkBarsFor = (name: string): { h: number; active: boolean }[] => {
    const raw: number[] = sparklines?.[name] ?? [];
    const len = 7;
    const values: number[] = Array.from({ length: len }, (_, i) => raw[i] ?? 0);
    const max = Math.max(...values, 1);
    return values.map((v) => ({
      // 3% minimum so empty days are still visible as a thin line
      h: Math.max(3, Math.round((v / max) * 100)),
      active: v > 0,
    }));
  };

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
        <div>
          <h2 className="text-4xl font-extrabold tracking-tight text-on-surface mb-2">Model Registry</h2>
          <p className="text-on-surface-variant max-w-2xl">
            Manage and monitor deployment-ready LLMs across your distributed infrastructure.
            {(modelCount > 0 || workerCount > 0) && (
              <>
                <br />
                {modelCount} model{modelCount !== 1 ? 's' : ''} · {workerCount} worker
                {workerCount !== 1 ? 's' : ''} registered.
              </>
            )}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setShowInstall(!showInstall)}
            className={`px-6 py-3 rounded-xl font-bold flex items-center gap-2 transition-all active:scale-95 ${
              showInstall
                ? 'bg-surface-container-high text-on-surface-variant hover:bg-surface-container-highest'
                : 'bg-surface-container text-on-surface hover:bg-surface-container-high border border-outline-variant/20'
            }`}
          >
            <span className="material-symbols-outlined text-sm">
              {showInstall ? 'close' : 'terminal'}
            </span>
            {showInstall ? 'Hide' : 'Install Worker'}
          </button>
          <button
            onClick={() => setShowForm(!showForm)}
            className={`px-6 py-3 rounded-xl font-bold flex items-center gap-2 transition-all active:scale-95 ${
              showForm
                ? 'bg-surface-container-high text-on-surface-variant hover:bg-surface-container-highest'
                : 'bg-primary-container text-on-primary hover:brightness-110'
            }`}
          >
            <span className="material-symbols-outlined text-sm">{showForm ? 'close' : 'add_circle'}</span>
            {showForm ? 'Cancel' : 'Register Model'}
          </button>
        </div>
      </div>

      {createError && <ErrorBanner message={createError} onRetry={() => setCreateError(null)} />}

      {/* Install Worker Guide */}
      {showInstall && (
        <div className="bg-surface-container-low rounded-2xl border border-primary/20 p-8 space-y-6">
          <div>
            <h3 className="text-xs font-bold uppercase tracking-widest text-on-surface-variant mb-2">
              Register a Worker
            </h3>
            <p className="text-sm text-on-surface-variant max-w-2xl">
              Workers run Claude Code or Codex CLI on any machine, poll this gateway for tasks,
              and report results back.
            </p>
          </div>

          {/* Step 1: Install token */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">
                Step 1 — Install Token
              </h4>
              {tokenStatus?.has_token && !mintedToken && (
                <button
                  onClick={revokeToken}
                  disabled={tokenBusy}
                  className="text-[10px] text-on-surface-variant/60 hover:text-red-400 disabled:opacity-50"
                >
                  Revoke
                </button>
              )}
            </div>
            {mintedToken ? (
              <div className="space-y-2">
                <div className="flex items-center gap-2 bg-surface-container-highest rounded-xl p-3">
                  <code className="text-xs font-mono text-on-surface flex-1 break-all">{mintedToken}</code>
                  <button
                    onClick={copyToken}
                    className="px-3 py-1.5 rounded-lg text-xs font-bold bg-primary-container text-on-primary hover:brightness-110 whitespace-nowrap"
                  >
                    {tokenCopied ? 'Copied!' : 'Copy'}
                  </button>
                </div>
                <p className="text-[10px] text-yellow-400/80">
                  ⚠ Copy this token now — it won't be shown again. Store it securely.
                </p>
              </div>
            ) : (
              <div className="flex items-center gap-3">
                <button
                  onClick={generateToken}
                  disabled={tokenBusy}
                  className="bg-primary-container text-on-primary px-5 py-2.5 rounded-xl font-bold hover:brightness-110 active:scale-95 transition-all disabled:opacity-50 text-sm"
                >
                  {tokenBusy
                    ? 'Working...'
                    : tokenStatus?.has_token
                      ? 'Regenerate Token'
                      : 'Generate Token'}
                </button>
                <p className="text-xs text-on-surface-variant/60">
                  {tokenStatus?.has_token
                    ? 'A token is already minted (hidden). Regenerate to get a new one — the old one stops working.'
                    : 'Mint a token, then paste it on the worker machine.'}
                </p>
              </div>
            )}
          </div>

          {/* Step 2: Install snippet */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">
                Step 2 — Install &amp; Run on the Worker Machine
              </h4>
              <button
                onClick={copyInstall}
                className="px-3 py-1.5 rounded-lg text-xs font-bold bg-surface-container-high hover:bg-surface-container-highest text-on-surface-variant whitespace-nowrap"
              >
                {copied ? 'Copied!' : 'Copy Snippet'}
              </button>
            </div>
            <pre className="text-xs text-on-surface whitespace-pre-wrap font-mono bg-surface-container-highest rounded-xl p-4 overflow-x-auto">
              {installSnippet}
            </pre>
          </div>
          <div className="flex items-start gap-2 text-xs text-on-surface-variant/80">
            <span className="material-symbols-outlined text-sm mt-0.5">info</span>
            <span>
              The worker auto-detects available CLIs via <span className="font-mono">shutil.which</span>{' '}
              and reports them as capabilities. First run saves a persistent token to{' '}
              <span className="font-mono">worker/.env</span>.
            </span>
          </div>
        </div>
      )}

      {/* Create Form */}
      {showForm && (
        <div className="bg-surface-container-low rounded-2xl border border-primary/20 p-8 space-y-6">
          <h3 className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">Register New Model</h3>
          <p className="text-xs text-on-surface-variant/80 -mt-2">
            This form is for LLM providers (OpenAI, Anthropic, Ollama, …). Executor
            workers (Claude Code / Codex) auto-register as models when you run their
            install script — use the <span className="font-bold">Install Worker</span> button above.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">Alias</label>
              <input
                type="text"
                value={formData.model_name}
                onChange={(e) => setFormData({ ...formData, model_name: e.target.value })}
                placeholder="gpt-4o"
                className="w-full bg-surface-container-highest border-none rounded-xl py-3 px-4 text-sm focus:ring-1 focus:ring-primary/40 placeholder:text-on-surface-variant/20"
              />
              <p className="text-[10px] text-on-surface-variant/60">Internal alias for routing</p>
            </div>
            <div className="space-y-2">
              <label className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">LiteLLM Model ID</label>
              <input
                type="text"
                value={formData.litellm_model}
                onChange={(e) => setFormData({ ...formData, litellm_model: e.target.value })}
                placeholder="openai/gpt-4o"
                className="w-full bg-surface-container-highest border-none rounded-xl py-3 px-4 text-sm font-mono focus:ring-1 focus:ring-primary/40 placeholder:text-on-surface-variant/20"
              />
              <p className="text-[10px] text-on-surface-variant/60">provider/model format</p>
            </div>
            <div className="space-y-2">
              <label className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">
                API Base <span className="text-on-surface-variant/40 font-normal normal-case">(optional)</span>
              </label>
              <input
                type="text"
                value={formData.api_base || ''}
                onChange={(e) => setFormData({ ...formData, api_base: e.target.value || undefined })}
                placeholder="http://localhost:11434"
                className="w-full bg-surface-container-highest border-none rounded-xl py-3 px-4 text-sm font-mono focus:ring-1 focus:ring-primary/40 placeholder:text-on-surface-variant/20"
              />
            </div>
            <div className="space-y-2">
              <label className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">
                API Key <span className="text-on-surface-variant/40 font-normal normal-case">(optional)</span>
              </label>
              <input
                type="password"
                value={formData.api_key || ''}
                onChange={(e) => setFormData({ ...formData, api_key: e.target.value || undefined })}
                placeholder="sk-..."
                className="w-full bg-surface-container-highest border-none rounded-xl py-3 px-4 text-sm focus:ring-1 focus:ring-primary/40 placeholder:text-on-surface-variant/20"
              />
            </div>
          </div>
          <button
            onClick={handleCreate}
            disabled={submitting || !formData.model_name.trim() || !formData.litellm_model.trim()}
            className="bg-primary-container text-on-primary px-6 py-3 rounded-xl font-bold hover:brightness-110 active:scale-95 transition-all disabled:opacity-50"
          >
            {submitting ? 'Registering...' : 'Register Model'}
          </button>
        </div>
      )}

      {deleteError && <ErrorBanner message={deleteError} onRetry={() => setDeleteError(null)} />}

      {/* Models Grid */}
      {llmModels.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {llmModels.map((model) => {
            const provider = model.litellm_model.split('/')[0];
            const modelId = model.litellm_model.split('/').slice(1).join('/');
            return (
              <div
                key={model.id}
                className={`bg-surface-container rounded-xl p-6 hover:bg-surface-container-high transition-colors group cursor-pointer border border-outline-variant/10 ${
                  !model.is_active ? 'opacity-60' : ''
                }`}
              >
                <div className="flex justify-between items-start mb-6">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <h3 className="text-lg font-bold">{model.model_name}</h3>
                      <div className={`w-2 h-2 rounded-full ${model.is_active ? 'bg-green-500' : 'bg-slate-600'}`} />
                    </div>
                    <div className="flex gap-2">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${getProviderBadgeClass(model.litellm_model)}`}>
                        {provider}
                      </span>
                    </div>
                  </div>
                  <button
                    onClick={() => onDelete(model.id, () => tenantsApi.deleteModel(tid, model.id), refetch)}
                    className={`transition-colors ${
                      deleting === model.id
                        ? 'text-error'
                        : 'text-slate-500 group-hover:text-amber-500 opacity-0 group-hover:opacity-100'
                    }`}
                  >
                    <span className="material-symbols-outlined">
                      {deleting === model.id ? 'check_circle' : 'more_vert'}
                    </span>
                  </button>
                </div>
                <div className="mb-6">
                  <p className="text-[10px] text-slate-500 uppercase tracking-widest font-bold mb-1">Model ID</p>
                  <p className="text-on-surface font-mono text-sm">{modelId || model.litellm_model}</p>
                </div>
                {model.api_base && (
                  <p className="text-[10px] text-on-surface-variant font-mono truncate" title={model.api_base}>
                    {model.api_base}
                  </p>
                )}
                {/* Sparkline — daily request counts over the last 7 days */}
                <div
                  className="h-16 w-full flex items-end gap-1 mt-4"
                  title="Requests per day (last 7 days)"
                >
                  {sparkBarsFor(model.model_name).map(({ h, active }, i) => (
                    <div
                      key={i}
                      className={`flex-1 rounded-t transition-colors ${
                        model.is_active && active
                          ? 'bg-amber-500'
                          : model.is_active
                            ? 'bg-amber-500/15'
                            : 'bg-slate-500/20'
                      }`}
                      style={{ height: `${h}%` }}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="bg-surface-container-low rounded-2xl border border-outline-variant/5 flex flex-col items-center justify-center py-16">
          <span className="material-symbols-outlined text-5xl text-on-surface-variant/30 mb-4">category</span>
          <p className="text-sm text-on-surface-variant font-medium">No models registered</p>
          <p className="text-xs text-on-surface-variant/60 mt-1">Add a model to start routing</p>
          <button
            onClick={() => setShowForm(true)}
            className="mt-4 bg-primary-container text-on-primary px-6 py-3 rounded-xl font-bold hover:brightness-110 transition-all"
          >
            Register First Model
          </button>
        </div>
      )}

      {/* Workers Section */}
      {workers && workers.length > 0 && (
        <div className="space-y-4 pt-4">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">
              Executor Workers
            </h3>
            <button
              onClick={refetchWorkers}
              className="text-[10px] text-on-surface-variant/60 hover:text-on-surface-variant flex items-center gap-1"
            >
              <span className="material-symbols-outlined text-xs">refresh</span>
              Refresh
            </button>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {workers.map((w) => {
              const online = w.status === 'online' || w.is_active;
              return (
                <div
                  key={w.id}
                  className={`bg-surface-container rounded-xl p-5 border border-outline-variant/10 ${
                    !online ? 'opacity-60' : ''
                  }`}
                >
                  <div className="flex items-center gap-3 mb-3">
                    <div className={`w-2.5 h-2.5 rounded-full ${online ? 'bg-green-500' : 'bg-slate-600'}`} />
                    <h3 className="text-base font-bold text-on-surface">{w.name}</h3>
                  </div>
                  <div className="flex flex-wrap gap-1.5 mb-3">
                    {w.capabilities.map((cap) => (
                      <span
                        key={cap}
                        className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-cyan-500/15 text-cyan-400"
                      >
                        {cap}
                      </span>
                    ))}
                  </div>
                  {w.labels.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {w.labels.map((label) => (
                        <span
                          key={label}
                          className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-secondary-container text-on-secondary-container"
                        >
                          {label}
                        </span>
                      ))}
                    </div>
                  )}
                  {w.last_heartbeat && (
                    <p className="text-[10px] text-on-surface-variant/60 mt-3">
                      Last heartbeat: {formatTime(w.last_heartbeat)}
                    </p>
                  )}
                  {/* Sparkline — tasks dispatched per day (last 7 days) */}
                  <div
                    className="h-12 w-full flex items-end gap-1 mt-3"
                    title="Tasks per day (last 7 days)"
                  >
                    {sparkBarsFor(w.name).map(({ h, active }, i) => (
                      <div
                        key={i}
                        className={`flex-1 rounded-t transition-colors ${
                          online && active
                            ? 'bg-cyan-400'
                            : online
                              ? 'bg-cyan-400/15'
                              : 'bg-slate-500/20'
                        }`}
                        style={{ height: `${h}%` }}
                      />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
