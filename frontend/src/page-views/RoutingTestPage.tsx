'use client';

import { useState } from 'react';
import { useT } from '@bsvibe/i18n';
import { useAuth } from '../hooks/useAuth';
import { rulesApi } from '../api/rules';
import { ErrorBanner } from '../components/common/ErrorBanner';

interface TestMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

interface MatchedRule {
  id: string;
  name: string;
  priority: number;
}

interface TestResult {
  matched_rule: MatchedRule | null;
  target_model: string | null;
  evaluation_trace: Record<string, unknown>[];
  context: Record<string, unknown>;
}

export function RoutingTestPage() {
  const t = useT('gateway');
  const { tenantId } = useAuth();
  const tid = tenantId || '';
  const [messages, setMessages] = useState<TestMessage[]>([{ role: 'user', content: '' }]);
  const [result, setResult] = useState<TestResult | null>(null);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleTest = async () => {
    if (!messages[0]?.content) {
      setError(t('test.validation'));
      return;
    }

    setTesting(true);
    setError(null);
    try {
      // Always test with model="auto" — the whole point is to see which
      // concrete model the router picks. The model is the OUTPUT of the
      // simulation, not an input.
      const data = await rulesApi.test(tid, {
        model: 'auto',
        messages: messages.filter((m) => m.content.trim()),
      });
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('test.failed'));
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="p-4 sm:p-8 space-y-4 sm:space-y-8">
      {/* Header */}
      <div>
        <h2 className="text-2xl sm:text-4xl font-extrabold tracking-tight text-on-surface mb-2">{t('test.title')}</h2>
        <p className="text-on-surface-variant">{t('test.subtitle')}</p>
      </div>

      {error && <ErrorBanner message={error} onRetry={() => setError(null)} />}

      <div className="grid grid-cols-12 gap-4 sm:gap-8">
        {/* Left Panel: Input */}
        <section className="col-span-12 lg:col-span-5 flex flex-col gap-4">
          <div className="bg-surface-container-lowest p-6 rounded-xl border border-outline-variant/15 flex flex-col h-full">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-bold text-on-surface flex items-center gap-2">
                <span className="material-symbols-outlined text-amber-500">input</span>
                {t('test.input')}
              </h3>
              <span className="text-[10px] text-slate-500 font-mono tracking-widest uppercase">{t('test.requestContext')}</span>
            </div>

            <div className="space-y-6 flex-1 flex flex-col">
              {/* Messages */}
              <div className="space-y-2 flex-1 flex flex-col">
                <label className="text-xs font-semibold text-on-surface-variant uppercase tracking-wider">{t('test.promptContent')}</label>
                {messages.map((msg, i) => (
                  <div key={i} className="flex-1 flex flex-col">
                    <div className="flex items-center gap-2 mb-2">
                      <select
                        value={msg.role}
                        onChange={(e) => {
                          const newMsgs = [...messages];
                          newMsgs[i].role = e.target.value as 'user' | 'assistant' | 'system';
                          setMessages(newMsgs);
                        }}
                        className="min-h-10 text-xs bg-surface-container-low border border-outline-variant/15 rounded px-3 py-1 font-medium text-on-surface"
                      >
                        <option value="user">user</option>
                        <option value="assistant">assistant</option>
                        <option value="system">system</option>
                      </select>
                      {messages.length > 1 && (
                        <button
                          onClick={() => setMessages(messages.filter((_, j) => j !== i))}
                          className="inline-flex min-h-10 min-w-10 items-center justify-center rounded text-on-surface-variant hover:bg-surface-container-high hover:text-error transition-colors"
                        >
                          <span className="material-symbols-outlined text-sm">close</span>
                        </button>
                      )}
                    </div>
                    <textarea
                      value={msg.content}
                      onChange={(e) => {
                        const newMsgs = [...messages];
                        newMsgs[i].content = e.target.value;
                        setMessages(newMsgs);
                      }}
                      placeholder={t('test.rolePlaceholder')}
                      className="flex-1 w-full bg-surface-container-low border-none rounded-lg p-4 text-sm font-mono text-amber-200/80 focus:ring-1 focus:ring-amber-500 min-h-[200px] border border-outline-variant/15"
                    />
                  </div>
                ))}
                <button
                  type="button"
                  onClick={() => setMessages([...messages, { role: 'user', content: '' }])}
                  className="flex min-h-11 items-center justify-center gap-1 text-xs text-primary hover:text-primary/80 transition-colors"
                >
                  <span className="material-symbols-outlined text-sm">add</span>
                  {t('test.addMessage')}
                </button>
              </div>

              <button
                onClick={handleTest}
                disabled={testing || !messages[0]?.content}
                className="w-full bg-gradient-to-r from-primary to-primary-container text-on-primary py-4 rounded-lg font-bold text-sm flex items-center justify-center gap-2 active:scale-95 transition-transform shadow-lg shadow-amber-900/20 disabled:opacity-50"
              >
                {testing ? (
                  <>
                    <span className="material-symbols-outlined animate-spin text-sm">progress_activity</span>
                    {t('test.testing')}
                  </>
                ) : (
                  <>
                    <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 1" }}>play_arrow</span>
                    {t('test.runSimulation')}
                  </>
                )}
              </button>
            </div>
          </div>
        </section>

        {/* Right Panel: Result */}
        <section className="col-span-12 lg:col-span-7 flex flex-col gap-6">
          {result ? (
            <div className="bg-surface-container-high p-6 rounded-xl border border-outline-variant/15 relative overflow-hidden">
              <div className="absolute -right-20 -top-20 w-64 h-64 bg-amber-500/5 blur-[100px]" />
              <div className="flex items-center justify-between mb-8 relative z-10">
                <h3 className="text-lg font-bold text-on-surface flex items-center gap-2">
                  <span className="material-symbols-outlined text-amber-500">analytics</span>
                  {t('test.result.title')}
                </h3>
              </div>

              <div className="space-y-8 relative z-10">
                {/* Primary result */}
                <div className="bg-surface-container-lowest p-6 rounded-lg border border-outline-variant/15">
                  <div className="flex justify-between items-start mb-3">
                    <span className="text-xs text-slate-500">{t('test.result.routedTo')}</span>
                    {result.matched_rule ? (
                      <span className="bg-amber-500/10 text-amber-500 text-[10px] px-2 py-0.5 rounded font-bold border border-amber-500/20">
                        {t('test.result.matched')}
                      </span>
                    ) : (
                      <span className="bg-error/10 text-error text-[10px] px-2 py-0.5 rounded font-bold border border-error/20">
                        {t('test.result.noMatch')}
                      </span>
                    )}
                  </div>
                  <div className="text-2xl font-bold text-on-surface tracking-tight font-mono">
                    {result.target_model || t('test.result.noModelSelected')}
                  </div>
                  {result.matched_rule && (
                    <p className="mt-3 text-sm text-on-surface-variant">
                      {t('test.result.matchedRule')} <span className="text-on-surface font-medium">{result.matched_rule.name}</span>
                    </p>
                  )}
                  {typeof result.context?.classified_intent === 'string' && result.context.classified_intent && (
                    <p className="mt-1 text-sm text-on-surface-variant">
                      {t('test.result.detectedIntent')} <span className="text-amber-500 font-medium">{result.context.classified_intent}</span>
                    </p>
                  )}
                </div>

                {/* Routing path */}
                <div className="space-y-4">
                  <h4 className="text-xs font-bold text-slate-400 uppercase tracking-widest">{t('test.result.routingPath')}</h4>
                  <div className="flex items-center justify-between px-2">
                    <div className="flex flex-col items-center gap-1">
                      <div className="w-8 h-8 rounded-full bg-surface-container-lowest flex items-center justify-center border border-slate-700">
                        <span className="material-symbols-outlined text-xs">input</span>
                      </div>
                      <span className="text-[9px] text-slate-500">{t('test.result.stepInput')}</span>
                    </div>
                    <div className="h-px flex-1 bg-gradient-to-r from-slate-700 to-amber-500/50 mx-1" />
                    <div className="flex flex-col items-center gap-1">
                      <div className="w-8 h-8 rounded-full bg-amber-500/10 flex items-center justify-center border border-amber-500/30">
                        <span className="material-symbols-outlined text-xs text-amber-500">psychology</span>
                      </div>
                      <span className="text-[9px] text-amber-500">{t('test.result.stepClassifier')}</span>
                    </div>
                    <div className="h-px flex-1 bg-gradient-to-r from-amber-500/50 to-amber-500/50 mx-1" />
                    <div className="flex flex-col items-center gap-1">
                      <div className="w-8 h-8 rounded-full bg-amber-500/10 flex items-center justify-center border border-amber-500/30">
                        <span className="material-symbols-outlined text-xs text-amber-500">gavel</span>
                      </div>
                      <span className="text-[9px] text-amber-500">{t('test.result.stepRules')}</span>
                    </div>
                    <div className="h-px flex-1 bg-gradient-to-r from-amber-500/50 to-slate-700 mx-1" />
                    <div className="flex flex-col items-center gap-1">
                      <div className="w-8 h-8 rounded-full bg-surface-container-lowest flex items-center justify-center border border-slate-700">
                        <span className="material-symbols-outlined text-xs">memory</span>
                      </div>
                      <span className="text-[9px] text-slate-500 truncate max-w-[60px]">{result.target_model || t('test.result.stepNone')}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="bg-surface-container-high rounded-xl border border-outline-variant/15 flex flex-col items-center justify-center h-full min-h-[400px]">
              <span className="material-symbols-outlined text-5xl text-on-surface-variant/20 mb-4">terminal</span>
              <p className="text-sm text-on-surface-variant font-medium">{t('test.empty.noRun')}</p>
              <p className="text-xs text-on-surface-variant/60 mt-1">{t('test.empty.configureRequest')}</p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
