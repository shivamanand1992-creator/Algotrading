import React from 'react';

interface NavItem {
  id: string;
  label: string;
  icon: string;
}

const navItems: NavItem[] = [
  { id: 'dashboard', label: 'Dashboard', icon: '📊' },
  { id: 'strategies', label: 'Strategies', icon: '⚡' },
  { id: 'portfolio', label: 'Portfolio', icon: '💼' },
  { id: 'market', label: 'Market', icon: '📈' },
  { id: 'risk', label: 'Risk', icon: '🛡️' },
];

interface SidebarProps {
  activeView: string;
  onNavigate: (view: string) => void;
}

export function Sidebar({ activeView, onNavigate }: SidebarProps) {
  return (
    <aside className="w-64 glass-panel border-r border-jarvis-primary/30 flex flex-col">
      <nav className="flex-1 py-6">
        {navItems.map((item) => (
          <button
            key={item.id}
            onClick={() => onNavigate(item.id)}
            className={`w-full px-6 py-4 flex items-center space-x-3 transition-all duration-300 ${
              activeView === item.id
                ? 'bg-jarvis-primary/20 border-r-4 border-jarvis-primary text-jarvis-primary'
                : 'text-jarvis-text-secondary hover:bg-jarvis-primary/10 hover:text-jarvis-primary'
            }`}
          >
            <span className="text-2xl">{item.icon}</span>
            <span className="font-medium">{item.label}</span>
          </button>
        ))}
      </nav>

      <div className="p-6 border-t border-jarvis-primary/30">
        <div className="text-xs text-jarvis-text-secondary text-center">
          <div>v1.0.0</div>
          <div className="mt-1">Shivam Trading System</div>
        </div>
      </div>
    </aside>
  );
}
