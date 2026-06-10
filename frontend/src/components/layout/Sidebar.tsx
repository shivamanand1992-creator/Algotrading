import React from 'react';
import { HUDCorners } from '../ui/HUDCorners';

interface NavItem {
  id: string;
  label: string;
  icon: string;
  section?: string;
}

const navItems: NavItem[] = [
  { id: 'dashboard',  label: 'Dashboard',      icon: '📊' },
  // Equity section
  { id: 'niftybees',  label: 'NiftyBees ETF',   icon: '🐝', section: 'EQUITY' },
  { id: 'stocks',     label: 'Equity Swing',    icon: '📈' },
  // Analysis section
  { id: 'market',     label: 'Market',          icon: '🌐', section: 'ANALYSIS' },
  { id: 'sectors',    label: 'Sector Rotation', icon: '🔄' },
  { id: 'news',       label: 'Market News',     icon: '📰' },
  // Portfolio section
  { id: 'holdings',   label: 'ETF Holdings',    icon: '🗂️', section: 'PORTFOLIO' },
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
    <aside className="w-64 glass-panel border-r border-jarvis-primary/30 flex flex-col" style={{ position: 'relative' }}>
      <nav className="flex-1 py-4">
        {navItems.map((item) => {
          const showDivider = item.section && item.section !== lastSection;
          lastSection = item.section ?? lastSection;
          const isActive = activeView === item.id;
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
              {isActive ? (
                <HUDCorners
                  className="mx-1 rounded-lg"
                  color="rgba(0,229,255,0.6)"
                  style={{ display: 'block' }}
                >
                  <button
                    onClick={() => onNavigate(item.id)}
                    className="w-full px-5 py-3.5 flex items-center space-x-3 transition-all duration-300 rounded-lg bg-jarvis-primary/20 border-r-4 border-jarvis-primary text-jarvis-primary deep-glow"
                  >
                    <span className="text-xl">{item.icon}</span>
                    <span className="font-medium text-sm">{item.label}</span>
                    {/* Active glow pulse */}
                    <span
                      className="live-dot ml-auto"
                      style={{ width: 6, height: 6, background: '#00e5ff', color: '#00e5ff', flexShrink: 0 }}
                    />
                  </button>
                </HUDCorners>
              ) : (
                <button
                  onClick={() => onNavigate(item.id)}
                  className="w-full px-6 py-3.5 flex items-center space-x-3 transition-all duration-300 text-jarvis-text-secondary hover:bg-jarvis-primary/10 hover:text-jarvis-primary hover-glitch"
                >
                  <span className="text-xl">{item.icon}</span>
                  <span className="font-medium text-sm">{item.label}</span>
                </button>
              )}
            </React.Fragment>
          );
        })}
      </nav>

      <div className="border-t border-jarvis-primary/30">
        {bottomNavItems.map((item) => {
          const isActive = activeView === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              className={`w-full px-6 py-4 flex items-center space-x-3 transition-all duration-300 ${
                isActive
                  ? 'bg-jarvis-primary/20 border-r-4 border-jarvis-primary text-jarvis-primary'
                  : 'text-jarvis-text-secondary hover:bg-jarvis-primary/10 hover:text-jarvis-primary'
              }`}
            >
              <span className="text-xl">{item.icon}</span>
              <span className="font-medium text-sm">{item.label}</span>
            </button>
          );
        })}
        <div className="p-5 border-t border-jarvis-primary/30">
          <div className="text-xs text-jarvis-text-secondary text-center">
            <div className="data-readout">v1.0.0</div>
            <div className="mt-1 data-readout">Shivam Trading System</div>
          </div>
        </div>
      </div>
    </aside>
  );
}
