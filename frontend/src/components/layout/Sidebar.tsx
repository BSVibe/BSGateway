import { Link, useLocation } from 'react-router-dom';

const navItems = [
  { path: '/', label: 'Dashboard', icon: 'D' },
  { path: '/rules', label: 'Rules', icon: 'R' },
  { path: '/models', label: 'Models', icon: 'M' },
  { path: '/intents', label: 'Intents', icon: 'I' },
  { path: '/test', label: 'Route Test', icon: 'T' },
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
    <aside className="w-56 bg-gray-900 text-gray-300 flex flex-col min-h-screen">
      <div className="p-4 border-b border-gray-700">
        <h1 className="text-lg font-bold text-white">BSGateway</h1>
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
                  ? 'bg-gray-800 text-white border-r-2 border-blue-500'
                  : 'hover:bg-gray-800 hover:text-white'
              }`}
            >
              <span className="w-5 h-5 flex items-center justify-center bg-gray-700 rounded text-xs font-bold">
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
            className="text-sm text-gray-400 hover:text-white transition-colors"
          >
            Logout
          </button>
        </div>
      )}
    </aside>
  );
}
