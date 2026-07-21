import React from 'react';

interface NavItem {
  id: string;
  label: string;
  icon: string;
  section?: string;
}

// Navigation items with proper organization and labels
const navItems: NavItem[] = [
  { id: 'dashboard',  label: 'Dashboard',      icon: '◈' },

  { id: 'market',     label: 'Market Data',    icon: '⊕', section: 'MARKETS' },
  { id: 'sectors',    label: 'Sector Rotation', icon: '↻' },
  { id: 'news',       label: 'Market News',    icon: '≡' },

  { id: 'intraday',   label: 'Intraday Intel', icon: '⚡', section: 'TRADING' },
  { id: 'ml-intraday', label: 'ML Intraday',    icon: '🎯' },

  { id: 'stocks',     label: 'Equity Swing',   icon: '↗', section: 'PORTFOLIOS' },
  { id: 'niftybees',  label: 'NiftyBees ETF',  icon: '⬡' },
  { id: 'holdings',   label: 'ETF Holdings',   icon: '⊞' },
  { id: 'portfolio',  label: 'Positions',      icon: '◫' },

  { id: 'conviction', label: 'Analysis',       icon: '⊛', section: 'ANALYSIS' },
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
        width: 220,
        minWidth: 220,
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

      <nav style={{ flex: 1, paddingTop: 8, paddingBottom: 8, overflowY: 'auto' }}>
        {navItems.map((item) => {
          const showDivider = item.section && item.section !== lastSection;
          lastSection = item.section ?? lastSection;
          const isActive = activeView === item.id;

          return (
            <React.Fragment key={item.id}>
              {showDivider && (
                <div style={{
                  margin: '12px 12px 8px',
                  fontSize: 10,
                  letterSpacing: '0.15em',
                  color: 'rgba(0,229,255,0.35)',
                  fontFamily: 'monospace',
                  fontWeight: 700,
                  textTransform: 'uppercase',
                }}>
                  {item.section}
                </div>
              )}
              <button
                onClick={() => onNavigate(item.id)}
                title={item.label}
                style={{
                  width: '100%',
                  padding: '10px 12px',
                  marginBottom: 2,
                  borderRadius: 8,
                  border: isActive ? '1px solid rgba(0,229,255,0.35)' : '1px solid transparent',
                  background: isActive ? 'rgba(0,229,255,0.12)' : 'transparent',
                  color: isActive ? '#00e5ff' : 'rgba(160,196,224,0.45)',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  fontSize: 13,
                  fontFamily: 'monospace',
                  fontWeight: isActive ? 700 : 400,
                  transition: 'all 0.2s',
                  position: 'relative',
                  boxShadow: isActive ? '0 0 12px rgba(0,229,255,0.2)' : 'none',
                  textAlign: 'left',
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
                <span style={{ fontSize: 16, flexShrink: 0 }}>{item.icon}</span>
                <span style={{ flex: 1 }}>{item.label}</span>
                {/* Active right-bar indicator */}
                {isActive && (
                  <div style={{
                    position: 'absolute',
                    right: 0,
                    top: '20%',
                    width: 2,
                    height: '60%',
                    background: '#00e5ff',
                    borderRadius: 1,
                    boxShadow: '0 0 6px #00e5ff',
                  }} />
                )}
              </button>
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
