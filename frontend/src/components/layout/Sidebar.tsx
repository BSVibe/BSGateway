import { Link, useLocation } from 'react-router-dom';

const navItems = [
  { path: '/', label: 'Dashboard', icon: 'D' },
  { path: '/rules', label: 'Rules', icon: 'R' },
  { path: '/models', label: 'Models', icon: 'M' },
  { path: '/intents', label: 'Intents', icon: 'I' },
  { path: '/test', label: 'Route Test', icon: 'T' },
  { path: '/api-keys', label: 'API Keys', icon: 'K' },
  { path: '/usage', label: 'Usage', icon: 'U' },
  { path: '/audit', label: 'Audit Log', icon: 'A' },
];

interface SidebarProps {
  onLogout?: () => void;
  tenantSlug?: string | null;
  tenantName?: string | null;
}

export function Sidebar({ onLogout, tenantSlug, tenantName }: SidebarProps) {
  const location = useLocation();

  return (
    <aside className="w-56 bg-gray-900 text-gray-400 flex flex-col min-h-screen border-r border-gray-700">
      <div className="p-4 border-b border-gray-700">
        <h1 className="text-lg font-bold text-gray-50">
          BS<span className="text-accent-500">Gateway</span>
        </h1>
        {tenantName ? (
          <p className="text-xs text-gray-400 truncate" title={tenantSlug || ''}>
            {tenantName}
          </p>
        ) : (
          <p className="text-xs text-gray-500">LLM Routing Dashboard</p>
        )}
      </div>
      <nav className="flex-1 py-4">
        {navItems.map((item) => {
          const isActive =
            item.path === '/'
              ? location.pathname === '/'
              : location.pathname.startsWith(item.path);
          return (
            <Link
              key={item.path}
              to={item.path}
              className={`flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
                isActive
                  ? 'bg-gray-800 text-gray-50 border-r-2 border-accent-500'
                  : 'hover:bg-gray-800 hover:text-gray-50'
              }`}
            >
              <span className={`w-5 h-5 flex items-center justify-center rounded text-xs font-bold ${
                isActive ? 'bg-accent-500/20 text-accent-500' : 'bg-gray-700 text-gray-400'
              }`}>
                {item.icon}
              </span>
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>
      {onLogout && (
        <div className="p-4 border-t border-gray-700">
          <button
            onClick={onLogout}
            className="text-sm text-gray-500 hover:text-gray-300 transition-colors"
          >
            Logout
          </button>
        </div>
      )}
    </aside>
  );
}
