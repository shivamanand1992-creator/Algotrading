import React from 'react';

interface NavItem {
  id: string;
  label: string;
  icon: string;
  section?: string;
}

// Navigation items - updated 2026-07-17 to include Hermes Monitor
const navItems: NavItem[] = [
  { id: 'dashboard',  label: 'Dashboard',      icon: '◈' },
  { id: 'intraday',   label: 'Intraday Intel',  icon: '⚡', section: 'TRADING' },
  { id: 'hermes',     label: 'Hermes Control', icon: '🤖' },
  { id: 'hermes-monitor', label: 'Hermes Monitor', icon: '👁️' },
  { id: 'claude-usage', label: 'Claude API Usage', icon: '📊', section: 'SYSTEM' },
  { id: 'stocks',     label: 'Equity Swing',    icon: '↗' },
  { id: 'niftybees',  label: 'NiftyBees ETF',   icon: '⬡' },
  { id: 'market',     label: 'Market',          icon: '⊕', section: 'ANALYSIS' },
  { id: 'sectors',    label: 'Sector Rotation', icon: '↻' },
  { id: 'news',       label: 'Market News',     icon: '≡' },
  { id: 'holdings',   label: 'ETF Holdings',    icon: '⊞', section: 'PORTFOLIO' },
  { id: 'portfolio',  label: 'Portfolio',        icon: '◫' },
];

const bottomNavItems: NavItem[] = [
  { id: 'help', label: 'Help & Guide', icon: '?' },
];

interface SidebarProps {
  activeView: string;
  onNavigate: (view: string) => void;
}

export function Sidebar({ activeView, onNavigate }: SidebarProps) {
  let lastSection: string | undefined;

  return (
    <aside
      style={{
        width: 56,
        minWidth: 56,
        display: 'flex',
        flexDirection: 'column',
        background: 'rgba(2,6,18,0.85)',
        borderRight: '1px solid rgba(0,229,255,0.1)',
        position: 'relative',
        zIndex: 10,
      }}
    >
      {/* Top accent line */}
      <div style={{ height: 2, background: 'linear-gradient(90deg, transparent, rgba(0,229,255,0.6), transparent)' }} />

      <nav style={{ flex: 1, paddingTop: 8, paddingBottom: 8 }}>
        {navItems.map((item) => {
          const showDivider = item.section && item.section !== lastSection;
          lastSection = item.section ?? lastSection;
          const isActive = activeView === item.id;

          return (
            <React.Fragment key={item.id}>
              {showDivider && (
                <div style={{ margin: '8px 8px', height: 1, background: 'rgba(0,229,255,0.08)' }} />
              )}
              <div style={{ position: 'relative', display: 'flex', justifyContent: 'center' }}>
                <button
                  onClick={() => onNavigate(item.id)}
                  title={item.label}
                  style={{
                    width: 40,
                    height: 40,
                    margin: '2px 0',
                    borderRadius: 8,
                    border: isActive ? '1px solid rgba(0,229,255,0.35)' : '1px solid transparent',
                    background: isActive ? 'rgba(0,229,255,0.12)' : 'transparent',
                    color: isActive ? '#00e5ff' : 'rgba(160,196,224,0.45)',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: 18,
                    fontFamily: 'monospace',
                    fontWeight: isActive ? 900 : 400,
                    transition: 'all 0.2s',
                    position: 'relative',
                    boxShadow: isActive ? '0 0 12px rgba(0,229,255,0.2)' : 'none',
                  }}
                  onMouseEnter={e => {
                    if (!isActive) {
                      (e.currentTarget as HTMLButtonElement).style.background = 'rgba(0,229,255,0.06)';
                      (e.currentTarget as HTMLButtonElement).style.color = 'rgba(0,229,255,0.75)';
                    }
                  }}
                  onMouseLeave={e => {
                    if (!isActive) {
                      (e.currentTarget as HTMLButtonElement).style.background = 'transparent';
                      (e.currentTarget as HTMLButtonElement).style.color = 'rgba(160,196,224,0.45)';
                    }
                  }}
                >
                  {item.icon}
                  {/* Active left-bar indicator */}
                  {isActive && (
                    <div style={{
                      position: 'absolute',
                      left: -9,
                      top: '20%',
                      width: 2,
                      height: '60%',
                      background: '#00e5ff',
                      borderRadius: 1,
                      boxShadow: '0 0 6px #00e5ff',
                    }} />
                  )}
                </button>
              </div>
            </React.Fragment>
          );
        })}
      </nav>

      {/* Bottom section */}
      <div style={{ borderTop: '1px solid rgba(0,229,255,0.08)', paddingTop: 8, paddingBottom: 8 }}>
        {bottomNavItems.map((item) => {
          const isActive = activeView === item.id;
          return (
            <div key={item.id} style={{ display: 'flex', justifyContent: 'center' }}>
              <button
                onClick={() => onNavigate(item.id)}
                title={item.label}
                style={{
                  width: 40,
                  height: 40,
                  margin: '2px 0',
                  borderRadius: 8,
                  border: isActive ? '1px solid rgba(0,229,255,0.35)' : '1px solid transparent',
                  background: isActive ? 'rgba(0,229,255,0.12)' : 'transparent',
                  color: isActive ? '#00e5ff' : 'rgba(160,196,224,0.35)',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 15,
                  fontFamily: 'monospace',
                  fontWeight: 700,
                  transition: 'all 0.2s',
                }}
                onMouseEnter={e => {
                  if (!isActive) {
                    (e.currentTarget as HTMLButtonElement).style.background = 'rgba(0,229,255,0.06)';
                    (e.currentTarget as HTMLButtonElement).style.color = 'rgba(0,229,255,0.7)';
                  }
                }}
                onMouseLeave={e => {
                  if (!isActive) {
                    (e.currentTarget as HTMLButtonElement).style.background = 'transparent';
                    (e.currentTarget as HTMLButtonElement).style.color = 'rgba(160,196,224,0.35)';
                  }
                }}
              >
                {item.icon}
              </button>
            </div>
          );
        })}

        {/* Version dot */}
        <div style={{ textAlign: 'center', paddingTop: 8 }}>
          <div style={{
            width: 6, height: 6,
            borderRadius: '50%',
            background: 'rgba(0,229,255,0.3)',
            margin: '0 auto',
            boxShadow: '0 0 6px rgba(0,229,255,0.2)',
          }} />
        </div>
      </div>
    </aside>
  );
}
