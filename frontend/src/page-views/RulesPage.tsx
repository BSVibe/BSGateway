'use client';

import { useState } from 'react';
import { rulesApi } from '../api/rules';
import { useAuth } from '../hooks/useAuth';
import { useApi } from '../hooks/useApi';
import { useDeleteConfirm } from '../hooks/useDeleteConfirm';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorBanner } from '../components/common/ErrorBanner';
import type { Rule, RuleCreate } from '../types/api';

const INITIAL_RULE: RuleCreate = { name: '', priority: 0, target_model: '', is_default: false };

function CreateModal({
  onClose,
  onCreated,
  tenantId,
}: {
  onClose: () => void;
  onCreated: () => void;
  tenantId: string;
}) {
  const [formData, setFormData] = useState<RuleCreate>(INITIAL_RULE);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleCreate = async () => {
    if (!formData.name.trim() || !formData.target_model.trim()) {
      setError('Name and target model are required');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await rulesApi.create(tenantId, formData);
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
        {/* Header */}
        <div className="px-8 py-6 border-b border-outline-variant/10 flex items-center justify-between bg-surface-container/30">
          <div>
            <h3 className="text-2xl font-bold text-on-surface">Create Routing Rule</h3>
            <p className="text-xs text-on-surface-variant uppercase tracking-widest font-bold mt-1">New Rule</p>
          </div>
          <button
            onClick={onClose}
            className="w-10 h-10 flex items-center justify-center rounded-xl hover:bg-surface-container-highest transition-colors"
          >
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>

        {/* Body */}
        <div className="p-8 space-y-6 max-h-[70vh] overflow-y-auto">
          {error && (
            <div className="text-xs text-error bg-error-container/20 border border-error/20 rounded-xl px-4 py-3">
              {error}
            </div>
          )}

          <div className="space-y-2">
            <label className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">Rule Name</label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="e.g. High Priority Customer Router"
              className="w-full bg-surface-container-highest border-none rounded-xl py-3 px-4 text-sm focus:ring-1 focus:ring-primary/40 placeholder:text-on-surface-variant/20"
            />
          </div>

          <div className="space-y-2">
            <label className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">Target Model</label>
            <input
              type="text"
              value={formData.target_model}
              onChange={(e) => setFormData({ ...formData, target_model: e.target.value })}
              placeholder="e.g. openai/gpt-4o"
              className="w-full bg-surface-container-highest border-none rounded-xl py-3 px-4 text-sm font-mono focus:ring-1 focus:ring-primary/40 placeholder:text-on-surface-variant/20"
            />
          </div>

          <div className="space-y-4">
            <div className="flex justify-between items-center">
              <label className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">Execution Priority</label>
              <span className="text-primary font-black px-2 py-0.5 bg-primary/10 rounded text-xs">P{formData.priority}</span>
            </div>
            <input
              type="range"
              min="0"
              max="10"
              step="1"
              value={formData.priority}
              onChange={(e) => setFormData({ ...formData, priority: parseInt(e.target.value) || 0 })}
              className="w-full h-2 bg-surface-container-highest rounded-lg appearance-none cursor-pointer accent-primary"
            />
            <div className="flex justify-between text-[10px] text-on-surface-variant font-bold px-1">
              <span>HIGHEST</span>
              <span>LOWEST</span>
            </div>
          </div>

          <label className="flex items-center gap-3 cursor-pointer select-none">
            <div
              onClick={() => setFormData({ ...formData, is_default: !formData.is_default })}
              className={`w-10 h-5 rounded-full relative p-1 cursor-pointer transition-colors ${
                formData.is_default ? 'bg-primary-container/20' : 'bg-outline-variant/20'
              }`}
            >
              <div className={`absolute top-1 w-3 h-3 rounded-full transition-all ${
                formData.is_default ? 'right-1 bg-primary-container' : 'left-1 bg-on-surface-variant/40'
              }`} />
            </div>
            <span className="text-sm text-on-surface">Default rule (fallback)</span>
          </label>
        </div>

        {/* Footer */}
        <div className="px-8 py-6 border-t border-outline-variant/10 bg-surface-container/50 flex items-center justify-end gap-4">
          <button
            onClick={onClose}
            className="px-6 py-3 text-sm font-bold text-on-surface-variant hover:text-on-surface transition-colors"
          >
            Discard
          </button>
          <button
            onClick={handleCreate}
            disabled={submitting || !formData.name.trim() || !formData.target_model.trim()}
            className="px-8 py-3 bg-primary-container text-on-primary rounded-xl font-bold shadow-lg shadow-primary-container/20 hover:scale-[1.02] active:scale-95 transition-all disabled:opacity-50"
          >
            {submitting ? 'Creating...' : 'Save & Deploy'}
          </button>
        </div>
      </div>
    </div>
  );
}

function StatusToggle({ rule, tenantId, onToggled }: { rule: Rule; tenantId: string; onToggled: () => void }) {
  const [toggling, setToggling] = useState(false);

  const handleToggle = async () => {
    if (toggling) return;
    setToggling(true);
    try {
      await (rulesApi.update as (tid: string, id: string, data: Record<string, unknown>) => Promise<Rule>)(
        tenantId,
        rule.id,
        { is_active: !rule.is_active },
      );
      onToggled();
    } finally {
      setToggling(false);
    }
  };

  return (
    <div
      onClick={handleToggle}
      className={`w-10 h-5 rounded-full relative p-1 cursor-pointer transition-colors ${
        toggling ? 'opacity-60' : ''
      } ${rule.is_active ? 'bg-primary-container/20' : 'bg-outline-variant/20'}`}
    >
      <div className={`absolute top-1 w-3 h-3 rounded-full transition-all ${
        rule.is_active ? 'right-1 bg-primary-container' : 'left-1 bg-on-surface-variant/40'
      }`} />
    </div>
  );
}

export function RulesPage() {
  const { tenantId } = useAuth();
  const tid = tenantId || '';
  const { data: rules, loading, error, refetch } = useApi(
    () => rulesApi.list(tid),
    [tid],
  );

  const [showModal, setShowModal] = useState(false);
  const { deleting, deleteError, handleDelete: onDelete, setDeleteError } = useDeleteConfirm();

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onRetry={refetch} />;

  const sortedRules = rules ? [...rules].sort((a, b) => a.priority - b.priority) : [];

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      {showModal && (
        <CreateModal
          tenantId={tid}
          onClose={() => setShowModal(false)}
          onCreated={refetch}
        />
      )}

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
        <div>
          <h2 className="text-4xl font-extrabold tracking-tight text-on-surface mb-2">Routing Rules</h2>
          <p className="text-on-surface-variant max-w-xl">
            Configure intelligent traffic distribution based on prompt complexity, metadata, and token density.
            {sortedRules.length > 0 && ` ${sortedRules.length} rule${sortedRules.length !== 1 ? 's' : ''} configured.`}
          </p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="bg-primary-container text-on-primary px-6 py-3 rounded-xl font-bold flex items-center gap-2 hover:brightness-110 transition-all active:scale-95"
        >
          <span className="material-symbols-outlined">add_circle</span>
          Create Rule
        </button>
      </div>

      {deleteError && <ErrorBanner message={deleteError} onRetry={() => setDeleteError(null)} />}

      {/* Rules Table */}
      <div className="bg-surface-container-low rounded-2xl overflow-hidden border border-outline-variant/5">
        {sortedRules.length > 0 ? (
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-surface-container/50">
                <th className="px-6 py-4 text-[10px] uppercase tracking-widest text-on-surface-variant font-bold">Name</th>
                <th className="px-6 py-4 text-[10px] uppercase tracking-widest text-on-surface-variant font-bold">Target Model</th>
                <th className="px-6 py-4 text-[10px] uppercase tracking-widest text-on-surface-variant font-bold">Priority</th>
                <th className="px-6 py-4 text-[10px] uppercase tracking-widest text-on-surface-variant font-bold">Status</th>
                <th className="px-6 py-4 text-[10px] uppercase tracking-widest text-on-surface-variant font-bold text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/5">
              {sortedRules.map((rule) => (
                <tr key={rule.id} className="hover:bg-surface-container/30 transition-colors group">
                  <td className="px-6 py-5">
                    <div className="flex items-center gap-3">
                      <span className="font-semibold text-on-surface">{rule.name}</span>
                      {rule.is_default && (
                        <span className="px-2 py-0.5 bg-primary/10 text-primary text-[10px] font-bold rounded border border-primary/20 uppercase">
                          default
                        </span>
                      )}
                    </div>
                    {rule.conditions?.length > 0 && (
                      <p className="text-xs text-on-surface-variant mt-1 italic">
                        {rule.conditions.length} condition{rule.conditions.length !== 1 ? 's' : ''}
                      </p>
                    )}
                  </td>
                  <td className="px-6 py-5">
                    <div className="flex items-center gap-2">
                      <div className={`w-2 h-2 rounded-full ${rule.is_active ? 'bg-tertiary shadow-[0_0_8px_rgba(143,213,255,0.4)]' : 'bg-on-surface-variant/40'}`} />
                      <span className="text-sm font-medium font-mono">{rule.target_model}</span>
                    </div>
                  </td>
                  <td className="px-6 py-5">
                    <span className={`text-[10px] font-black px-2 py-1 rounded border uppercase ${
                      rule.priority <= 2
                        ? 'bg-primary/10 text-primary border-primary/20'
                        : 'bg-on-surface-variant/10 text-on-surface-variant border-outline-variant/10'
                    }`}>
                      P{rule.priority}
                    </span>
                  </td>
                  <td className="px-6 py-5">
                    <StatusToggle rule={rule} tenantId={tid} onToggled={refetch} />
                  </td>
                  <td className="px-6 py-5 text-right">
                    <div className="flex items-center justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={() => onDelete(rule.id, () => rulesApi.delete(tid, rule.id), refetch)}
                        className={`p-2 rounded-lg transition-colors ${
                          deleting === rule.id
                            ? 'bg-error/20 text-error'
                            : 'hover:bg-error/10 text-on-surface-variant hover:text-error'
                        }`}
                      >
                        <span className="material-symbols-outlined text-sm">
                          {deleting === rule.id ? 'check' : 'delete'}
                        </span>
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="flex flex-col items-center justify-center py-16 min-h-[400px]">
            <div className="relative w-32 h-32 mb-8">
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="w-24 h-24 rounded-full border-2 border-primary/20 animate-pulse flex items-center justify-center">
                  <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center">
                    <span className="material-symbols-outlined text-primary text-2xl">hub</span>
                  </div>
                </div>
              </div>
            </div>
            <h3 className="text-xl font-bold mb-2 text-on-surface">No routing rules yet</h3>
            <p className="text-on-surface-variant text-center max-w-sm mb-6">
              Create a rule to start intelligently routing your LLM requests.
            </p>
            <button
              onClick={() => setShowModal(true)}
              className="text-primary font-bold hover:underline"
            >
              Create First Rule
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
