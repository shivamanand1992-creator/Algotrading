import React from 'react';

interface NavItem {
  id: string;
  label: string;
  icon: string;
  section?: string;
}

const navItems: NavItem[] = [
  { id: 'dashboard',  label: 'Dashboard',      icon: '📊' },
  // F&O section
  { id: 'strategies', label: 'Nifty Options',   icon: '⚡', section: 'F&O' },
  { id: 'portfolio',  label: 'F&O Portfolio',   icon: '💼' },
  { id: 'risk',       label: 'F&O Risk',        icon: '🛡️' },
  // Equity section
  { id: 'stocks',     label: 'Equity Swing',    icon: '📈', section: 'EQUITY' },
  // Market
  { id: 'market',     label: 'Market',          icon: '🌐' },
];

const bottomNavItems: NavItem[] = [
  { id: 'help', label: 'Help & Guide', icon: '❓' },
];

interface SidebarProps {
  activeView: string;
  onNavigate: (view: string) => void;
}

export function Sidebar({ activeView, onNavigate }: SidebarProps) {
  let lastSection: string | undefined;

  return (
    <aside className="w-64 glass-panel border-r border-jarvis-primary/30 flex flex-col">
      <nav className="flex-1 py-4">
        {navItems.map((item) => {
          const showDivider = item.section && item.section !== lastSection;
          lastSection = item.section ?? lastSection;
          return (
            <React.Fragment key={item.id}>
              {showDivider && (
                <div className="mx-4 my-2 flex items-center gap-2">
                  <div className="flex-1 h-px bg-jarvis-primary/15" />
                  <span className="text-[9px] font-bold tracking-widest text-jarvis-primary/40 uppercase">
                    {item.section}
                  </span>
                  <div className="flex-1 h-px bg-jarvis-primary/15" />
                </div>
              )}
              <button
                onClick={() => onNavigate(item.id)}
                className={`w-full px-6 py-3.5 flex items-center space-x-3 transition-all duration-300 ${
                  activeView === item.id
                    ? 'bg-jarvis-primary/20 border-r-4 border-jarvis-primary text-jarvis-primary'
                    : 'text-jarvis-text-secondary hover:bg-jarvis-primary/10 hover:text-jarvis-primary'
                }`}
              >
                <span className="text-xl">{item.icon}</span>
                <span className="font-medium text-sm">{item.label}</span>
              </button>
            </React.Fragment>
          );
        })}
      </nav>

      <div className="border-t border-jarvis-primary/30">
        {bottomNavItems.map((item) => (
          <button
            key={item.id}
            onClick={() => onNavigate(item.id)}
            className={`w-full px-6 py-4 flex items-center space-x-3 transition-all duration-300 ${
              activeView === item.id
                ? 'bg-jarvis-primary/20 border-r-4 border-jarvis-primary text-jarvis-primary'
                : 'text-jarvis-text-secondary hover:bg-jarvis-primary/10 hover:text-jarvis-primary'
            }`}
          >
            <span className="text-xl">{item.icon}</span>
            <span className="font-medium text-sm">{item.label}</span>
          </button>
        ))}
        <div className="p-5 border-t border-jarvis-primary/30">
          <div className="text-xs text-jarvis-text-secondary text-center">
            <div>v1.0.0</div>
            <div className="mt-1">Shivam Trading System</div>
          </div>
        </div>
      </div>
    </aside>
  );
}

