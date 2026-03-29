import { auth } from '../hooks/useAuth';

const features = [
  {
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <path d="M12 6v6l4 2" />
      </svg>
    ),
    title: 'Cost Optimization',
    description: 'Route requests to the most cost-effective model automatically',
  },
  {
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
      </svg>
    ),
    title: 'Complexity Analysis',
    description: 'Classify prompt complexity to select the right model tier',
  },
  {
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="3" width="7" height="7" rx="1" />
        <rect x="15" y="3" width="7" height="7" rx="1" />
        <rect x="2" y="14" width="7" height="7" rx="1" />
        <rect x="15" y="14" width="7" height="7" rx="1" />
      </svg>
    ),
    title: 'Multi-Model Routing',
    description: 'Seamlessly switch between OpenAI, Anthropic, and more',
  },
];

export function LoginPage() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gray-950 px-4 relative overflow-hidden">
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
      <div
        className="relative w-full max-w-md rounded-xl border border-gray-700 p-8"
        style={{ background: '#111218' }}
      >
        {/* Logo */}
        <div className="flex items-center justify-center gap-3 mb-6">
          {/* Network/routing icon */}
          <div
            className="flex items-center justify-center w-10 h-10 rounded-lg"
            style={{ background: 'rgba(245,158,11,0.12)', border: '1px solid rgba(245,158,11,0.25)' }}
          >
            <svg
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#f59e0b"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="18" cy="5" r="2" />
              <circle cx="6" cy="12" r="2" />
              <circle cx="18" cy="19" r="2" />
              <line x1="8" y1="11" x2="16" y2="6" />
              <line x1="8" y1="13" x2="16" y2="18" />
            </svg>
          </div>
          <div>
            <span className="text-xl font-bold text-gray-50 tracking-tight">
              BS<span className="text-accent-500">Gateway</span>
            </span>
          </div>
        </div>

        {/* Headline */}
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-gray-50 mb-2 leading-tight">
            Smart routing,{' '}
            <span className="text-accent-500">lower costs</span>
          </h1>
          <p className="text-sm text-gray-400 leading-relaxed">
            Automatically route LLM requests to the most cost-effective model
            based on complexity analysis.
          </p>
        </div>

        {/* Feature highlights */}
        <div className="space-y-3 mb-8">
          {features.map((feature) => (
            <div
              key={feature.title}
              className="flex items-start gap-3 p-3 rounded-lg"
              style={{ background: '#181926', border: '1px solid #2a2d42' }}
            >
              <div className="flex-shrink-0 mt-0.5 text-accent-500">{feature.icon}</div>
              <div>
                <p className="text-sm font-medium text-gray-50">{feature.title}</p>
                <p className="text-xs text-gray-400 mt-0.5 leading-relaxed">{feature.description}</p>
              </div>
            </div>
          ))}
        </div>

        {/* CTA */}
        <button
          onClick={() => auth.redirectToLogin()}
          className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg font-semibold text-sm transition-colors bg-accent-500 hover:bg-accent-400 text-gray-950"
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.25"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" />
            <polyline points="10 17 15 12 10 7" />
            <line x1="15" y1="12" x2="3" y2="12" />
          </svg>
          Sign in with BSVibe
        </button>
      </div>

      {/* Footer */}
      <p className="mt-6 text-xs text-gray-500">
        Powered by{' '}
        <span className="text-gray-400 font-medium">BSVibe</span>
      </p>
    </div>
  );
}
