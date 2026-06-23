import React, { ReactNode } from 'react';
import { Header } from './Header';
import { ParticleCanvas } from '../ui/ParticleCanvas';
import { CityBackground } from '../ui/CityBackground';
import { JarvisVoicePanel } from '../jarvis/JarvisVoicePanel';

const NAV_ITEMS = [
  { id: 'dashboard', label: 'DASHBOARD', icon: '◈' },
  { id: 'niftybees', label: 'NIFTYBEES', icon: '⬡' },
  { id: 'stocks',    label: 'EQUITY',    icon: '↗' },
  { id: 'market',    label: 'MARKET',    icon: '⊕' },
  { id: 'sectors',   label: 'SECTORS',   icon: '↻' },
  { id: 'news',      label: 'NEWS',      icon: '≡' },
  { id: 'holdings',  label: 'ETF HOLDINGS', icon: '⊞' },
  { id: 'portfolio', label: 'PORTFOLIO', icon: '◫' },
  { id: 'help',      label: 'HELP',      icon: '?' },
];

function TopNav({ activeView, onNavigate }: { activeView: string; onNavigate: (v: string) => void }) {
  return (
    <nav
      style={{
        height: 40,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 2,
        background: 'rgba(0,3,10,0.90)',
        borderBottom: '1px solid rgba(0,229,255,0.08)',
        flexShrink: 0,
        padding: '0 16px',
        position: 'relative',
        zIndex: 9,
      }}
    >
      {/* Accent line top */}
      <div style={{
        position: 'absolute',
        top: 0, left: 0, right: 0,
        height: 1,
        background: 'linear-gradient(90deg, transparent 0%, rgba(0,229,255,0.18) 30%, rgba(0,229,255,0.18) 70%, transparent 100%)',
      }} />

      {NAV_ITEMS.map(item => {
        const active = activeView === item.id;
        return (
          <button
            key={item.id}
            onClick={() => onNavigate(item.id)}
            title={item.label}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '0 13px',
              height: 36,
              background: active ? 'rgba(0,229,255,0.07)' : 'transparent',
              border: 'none',
              borderBottom: active ? '2px solid #00e5ff' : '2px solid transparent',
              color: active ? '#00e5ff' : 'rgba(160,196,224,0.45)',
              cursor: 'pointer',
              fontFamily: "'Courier New', monospace",
              fontSize: 11,
              letterSpacing: '0.12em',
              fontWeight: active ? 700 : 400,
              transition: 'all 0.15s ease',
              textShadow: active ? '0 0 10px rgba(0,229,255,0.6)' : 'none',
              boxShadow: active ? '0 -1px 0 rgba(0,229,255,0.15) inset' : 'none',
              borderRadius: '2px 2px 0 0',
              whiteSpace: 'nowrap',
            }}
            onMouseEnter={e => {
              if (!active) {
                (e.currentTarget as HTMLButtonElement).style.color = 'rgba(0,229,255,0.7)';
                (e.currentTarget as HTMLButtonElement).style.background = 'rgba(0,229,255,0.04)';
              }
            }}
            onMouseLeave={e => {
              if (!active) {
                (e.currentTarget as HTMLButtonElement).style.color = 'rgba(160,196,224,0.4)';
                (e.currentTarget as HTMLButtonElement).style.background = 'transparent';
              }
            }}
          >
            <span style={{ fontSize: 15 }}>{item.icon}</span>
            <span>{item.label}</span>
          </button>
        );
      })}
    </nav>
  );
}

interface MainLayoutProps {
  children: ReactNode;
  activeView: string;
  onNavigate: (view: string) => void;
  onLogout?: () => void;
}

export function MainLayout({ children, activeView, onNavigate, onLogout }: MainLayoutProps) {
  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', position: 'relative', overflow: 'hidden' }}>
      {/* Layered backgrounds */}
      <CityBackground />
      <ParticleCanvas />

      {/* App shell */}
      <div style={{ position: 'relative', zIndex: 2, display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
        <Header onLogout={onLogout} />
        <TopNav activeView={activeView} onNavigate={onNavigate} />
        <main style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
          {children}
        </main>
      </div>

      {/* VAAYU voice panel — fixed bottom-right */}
      <JarvisVoicePanel />
    </div>
  );
}
