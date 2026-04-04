import { Link, useLocation } from 'react-router-dom';

const navItems = [
  { path: '/', label: 'Dashboard', icon: 'dashboard' },
  { path: '/rules', label: 'Rules', icon: 'rule' },
  { path: '/models', label: 'Models', icon: 'model_training' },
  { path: '/test', label: 'Routing Test', icon: 'route' },
  { path: '/usage', label: 'Analytics', icon: 'bar_chart' },
  { path: '/api-keys', label: 'API Keys', icon: 'vpn_key' },
  { path: '/audit', label: 'Audit Log', icon: 'receipt_long' },
];

interface SidebarProps {
  onLogout?: () => void;
  tenantSlug?: string | null;
  tenantName?: string | null;
  isOpen: boolean;
  onClose: () => void;
}

export function Sidebar({ onLogout, tenantSlug, tenantName, isOpen, onClose }: SidebarProps) {
  const location = useLocation();

  return (
    <>
      {/* Backdrop - mobile only */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 md:hidden"
          onClick={onClose}
        />
      )}
    <aside className={`fixed left-0 top-0 h-screen w-64 bg-[#121317] flex flex-col z-50 transform transition-transform duration-200 ${isOpen ? 'translate-x-0' : '-translate-x-full'} md:translate-x-0`}>
      {/* Logo */}
      <div className="p-6 flex items-center gap-3">
        <div className="w-8 h-8 rounded bg-primary-container flex items-center justify-center">
          <span className="material-symbols-outlined text-on-primary text-xl">hub</span>
        </div>
        <div>
          <h1 className="text-xl font-bold tracking-tighter text-amber-500 leading-none">
            BS<span className="text-amber-500">Gateway</span>
          </h1>
          {tenantName ? (
            <p className="text-[10px] text-slate-500 truncate mt-1 max-w-[130px] uppercase tracking-widest" title={tenantSlug || ''}>
              {tenantName}
            </p>
          ) : (
            <p className="text-[10px] uppercase tracking-widest text-slate-500 mt-1">LLM Routing</p>
          )}
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-4 py-4 space-y-1">
        {navItems.map((item) => {
          const isActive =
            item.path === '/'
              ? location.pathname === '/'
              : location.pathname.startsWith(item.path);
          return (
            <Link
              key={item.path}
              to={item.path}
              onClick={onClose}
              className={`flex items-center gap-3 px-4 py-3 rounded text-sm transition-all duration-200 ${
                isActive
                  ? 'text-amber-500 bg-amber-500/10 border-r-2 border-amber-500 font-semibold'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-[#1f1f24] active:scale-95'
              }`}
            >
              <span className="material-symbols-outlined">{item.icon}</span>
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      {onLogout && (
        <div className="p-4 border-t border-amber-900/10">
          <button
            onClick={onLogout}
            className="w-full flex items-center gap-3 px-4 py-3 rounded text-sm text-slate-400 hover:text-slate-200 hover:bg-[#1f1f24] transition-colors"
          >
            <span className="material-symbols-outlined">logout</span>
            <span>Logout</span>
          </button>
        </div>
      )}
    </aside>
    </>
  );
}
