import React, { ReactNode, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Header } from './Header';
import { Sidebar } from './Sidebar';
import { ParticleCanvas } from '../ui/ParticleCanvas';
import { CityBackground } from '../ui/CityBackground';
import { JarvisVoicePanel } from '../jarvis/JarvisVoicePanel';

const NAV_ITEMS = [
  { id: 'dashboard', label: 'DASHBOARD',    icon: '◈' },
  { id: 'market',    label: 'MARKET',       icon: '⊕' },
  { id: 'intraday',  label: 'INTRADAY',     icon: '⚡' },
  { id: 'ml-intraday', label: 'ML INTRADAY', icon: '🎯' },
  { id: 'niftybees', label: 'NIFTYBEES',    icon: '⬡' },
  { id: 'stocks',    label: 'EQUITY',       icon: '↗' },
  { id: 'sectors',   label: 'SECTORS',      icon: '↻' },
  { id: 'news',      label: 'NEWS',         icon: '≡' },
  { id: 'holdings',  label: 'ETF HOLDINGS', icon: '⊞' },
  { id: 'portfolio', label: 'PORTFOLIO',    icon: '◫' },
  { id: 'conviction', label: 'ANALYSE',     icon: '⊛' },
  { id: 'help',      label: 'HELP',         icon: '?' },
];

function TopNav({ activeView, onNavigate }: { activeView: string; onNavigate: (v: string) => void }) {
  return (
    <nav
      className="top-nav-bar"
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
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, height: 1,
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
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '0 13px', height: 36,
              background: active ? 'rgba(0,229,255,0.07)' : 'transparent',
              border: 'none',
              borderBottom: active ? '2px solid #00e5ff' : '2px solid transparent',
              color: active ? '#00e5ff' : 'rgba(160,196,224,0.45)',
              cursor: 'pointer', fontFamily: "'Courier New', monospace",
              fontSize: 11, letterSpacing: '0.12em',
              fontWeight: active ? 700 : 400,
              transition: 'all 0.15s ease',
              textShadow: active ? '0 0 10px rgba(0,229,255,0.6)' : 'none',
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

function MobileNavDrawer({
  activeView, onNavigate, onClose,
}: {
  activeView: string; onNavigate: (v: string) => void; onClose: () => void;
}) {
  return (
    <AnimatePresence>
      {/* Backdrop */}
      <motion.div
        key="backdrop"
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0, zIndex: 200,
          background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(4px)',
        }}
      />

      {/* Drawer panel */}
      <motion.div
        key="drawer"
        initial={{ x: '-100%' }} animate={{ x: 0 }} exit={{ x: '-100%' }}
        transition={{ type: 'spring', stiffness: 320, damping: 30 }}
        style={{
          position: 'fixed', top: 0, left: 0, bottom: 0, width: 280, zIndex: 201,
          background: 'rgba(2,4,18,0.98)',
          borderRight: '1px solid rgba(0,229,255,0.12)',
          display: 'flex', flexDirection: 'column',
          overflowY: 'auto',
        }}
      >
        {/* Drawer header */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '20px 20px 16px',
          borderBottom: '1px solid rgba(0,229,255,0.08)',
          flexShrink: 0,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <svg width={26} height={26} viewBox="0 0 30 30">
              <polygon points="15,2 27,8.5 27,21.5 15,28 3,21.5 3,8.5"
                fill="rgba(0,229,255,0.08)" stroke="rgba(0,229,255,0.5)" strokeWidth="1" />
              <text x="15" y="19" textAnchor="middle"
                style={{ fontFamily: 'monospace', fontSize: 10, fontWeight: 900, fill: '#00e5ff', letterSpacing: 1 }}>V</text>
            </svg>
            <div>
              <div style={{ color: '#00e5ff', fontSize: 13, fontFamily: "'Courier New', monospace", fontWeight: 900, letterSpacing: '0.3em' }}>
                VAAYU
              </div>
              <div style={{ color: 'rgba(160,196,224,0.35)', fontSize: 8, letterSpacing: '0.2em', fontFamily: 'monospace' }}>
                ALGOTRADING
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'transparent', border: '1px solid rgba(0,229,255,0.2)',
              color: 'rgba(0,229,255,0.5)', width: 32, height: 32, borderRadius: 6,
              cursor: 'pointer', fontSize: 16, display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >
            ✕
          </button>
        </div>

        {/* Nav items */}
        <div style={{ padding: '12px 0', flex: 1 }}>
          {NAV_ITEMS.map(item => {
            const active = activeView === item.id;
            return (
              <button
                key={item.id}
                onClick={() => { onNavigate(item.id); onClose(); }}
                style={{
                  display: 'flex', alignItems: 'center', gap: 14,
                  width: '100%', padding: '14px 20px',
                  background: active ? 'rgba(0,229,255,0.07)' : 'transparent',
                  border: 'none',
                  borderLeft: `3px solid ${active ? '#00e5ff' : 'transparent'}`,
                  color: active ? '#00e5ff' : 'rgba(160,196,224,0.65)',
                  cursor: 'pointer', textAlign: 'left',
                  transition: 'all 0.15s',
                }}
              >
                <span style={{ fontSize: 20, width: 24, textAlign: 'center', flexShrink: 0 }}>{item.icon}</span>
                <span style={{
                  fontFamily: "'Courier New', monospace", fontSize: 12,
                  letterSpacing: '0.2em', fontWeight: active ? 700 : 400,
                  textShadow: active ? '0 0 10px rgba(0,229,255,0.5)' : 'none',
                }}>
                  {item.label}
                </span>
                {active && (
                  <div style={{ marginLeft: 'auto', width: 6, height: 6, borderRadius: '50%', background: '#00e5ff', boxShadow: '0 0 8px rgba(0,229,255,0.8)' }} />
                )}
              </button>
            );
          })}
        </div>

        {/* Footer */}
        <div style={{
          padding: '14px 20px',
          borderTop: '1px solid rgba(0,229,255,0.06)',
          color: 'rgba(160,196,224,0.2)', fontSize: 9, letterSpacing: '0.15em',
          fontFamily: 'monospace', textAlign: 'center', flexShrink: 0,
        }}>
          VAAYU · ALGOTRADING SYSTEM
        </div>
      </motion.div>
    </AnimatePresence>
  );
}

interface MainLayoutProps {
  children: ReactNode;
  activeView: string;
  onNavigate: (view: string) => void;
  onLogout?: () => void;
}

export function MainLayout({ children, activeView, onNavigate, onLogout }: MainLayoutProps) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', position: 'relative', overflow: 'hidden' }}>
      <CityBackground />
      <ParticleCanvas />

      <div style={{ position: 'relative', zIndex: 2, display: 'flex', minHeight: '100vh' }}>
        {/* Left sidebar navigation */}
        <Sidebar activeView={activeView} onNavigate={onNavigate} />

        {/* Main content area */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          <Header onLogout={onLogout} onHamburger={() => setMenuOpen(true)} />
          <main style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
            {children}
          </main>
        </div>
      </div>

      {/* Mobile slide-in nav drawer */}
      {menuOpen && (
        <MobileNavDrawer
          activeView={activeView}
          onNavigate={onNavigate}
          onClose={() => setMenuOpen(false)}
        />
      )}

      <JarvisVoicePanel />
    </div>
  );
}
