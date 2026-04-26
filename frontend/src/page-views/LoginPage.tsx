'use client';

import { useAuth } from '../hooks/useAuth';

const features = [
  {
    icon: 'schedule',
    title: 'Cost Optimization',
    description: 'Route requests to the most cost-effective model automatically',
  },
  {
    icon: 'show_chart',
    title: 'Complexity Analysis',
    description: 'Classify prompt complexity to select the right model tier',
  },
  {
    icon: 'hub',
    title: 'Multi-Model Routing',
    description: 'Seamlessly switch between OpenAI, Anthropic, and more',
  },
];

export function LoginPage() {
  const { login, signup } = useAuth();

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-surface px-4 relative overflow-hidden">
      {/* Ambient glow */}
      <div
        aria-hidden="true"
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            'radial-gradient(ellipse 700px 500px at 50% 40%, rgba(245,158,11,0.07) 0%, transparent 70%)',
        }}
      />

      {/* Card */}
      <div className="relative w-full max-w-md rounded-2xl border border-outline-variant/10 p-8 bg-surface-container-low">
        {/* Logo */}
        <div className="flex items-center justify-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-lg bg-primary-container flex items-center justify-center">
            <span className="material-symbols-outlined text-on-primary text-xl">hub</span>
          </div>
          <div>
            <span className="text-xl font-bold text-on-surface tracking-tight">
              BS<span className="text-amber-500">Gateway</span>
            </span>
          </div>
        </div>

        {/* Headline */}
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-on-surface mb-2 leading-tight">
            Smart routing,{' '}
            <span className="text-amber-500">lower costs</span>
          </h1>
          <p className="text-sm text-on-surface-variant leading-relaxed">
            Automatically route LLM requests to the most cost-effective model
            based on complexity analysis.
          </p>
        </div>

        {/* Feature highlights */}
        <div className="space-y-3 mb-8">
          {features.map((feature) => (
            <div
              key={feature.title}
              className="flex items-start gap-3 p-3 rounded-xl bg-surface-container border border-outline-variant/10"
            >
              <div className="flex-shrink-0 mt-0.5 text-amber-500">
                <span className="material-symbols-outlined text-xl">{feature.icon}</span>
              </div>
              <div>
                <p className="text-sm font-medium text-on-surface">{feature.title}</p>
                <p className="text-xs text-on-surface-variant mt-0.5 leading-relaxed">{feature.description}</p>
              </div>
            </div>
          ))}
        </div>

        {/* CTA */}
        <button
          onClick={login}
          className="w-full flex items-center justify-center gap-2 py-3 rounded-xl font-bold text-sm transition-all bg-primary-container hover:brightness-110 text-on-primary active:scale-95"
        >
          <span className="material-symbols-outlined text-lg">login</span>
          Sign in with BSVibe
        </button>

        <p className="text-center text-sm text-on-surface-variant mt-4">
          Don't have an account?{' '}
          <button
            onClick={signup}
            className="text-amber-500 hover:text-amber-400 font-medium transition-colors"
          >
            Sign up
          </button>
        </p>
      </div>

      {/* Footer */}
      <p className="mt-6 text-xs text-on-surface-variant/60">
        Powered by{' '}
        <span className="text-on-surface-variant font-medium">BSVibe</span>
      </p>
    </div>
  );
}
