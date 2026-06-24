import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { systemApi } from '../../api/client';
import type { SystemStatus } from '../../types/api';
import { useBalanceVisibility } from '../../context/BalanceVisibilityContext';

interface HeaderProps {
  onLogout?: () => void;
}

export function Header({ onLogout }: HeaderProps) {
  const [currentTime, setCurrentTime] = useState(new Date());
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const { balVisible, toggleBalVisible } = useBalanceVisibility();

  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const res = await systemApi.getStatus();
        setSystemStatus(res.data);
      } catch (e) {}
    };
    fetchStatus();
    const interval = setInterval(fetchStatus, 10000);
    return () => clearInterval(interval);
  }, []);

  const brokerOk = systemStatus?.broker_connected;
  const sysOk    = systemStatus?.status === 'healthy';

  return (
    <header
      className="site-header"
      style={{
        height: 52,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 20px 0 16px',
        background: 'rgba(2,4,16,0.92)',
        borderBottom: '1px solid rgba(0,229,255,0.1)',
        position: 'relative',
        zIndex: 10,
        flexShrink: 0,
      }}
    >
      {/* Scanning beam */}
      <div className="diagonal-beam" />

      {/* Left — VAAYU wordmark */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        {/* Hexagon logo */}
        <svg width={30} height={30} viewBox="0 0 30 30" style={{ flexShrink: 0 }}>
          <defs>
            <filter id="hdr-glow">
              <feGaussianBlur stdDeviation="1.5" result="blur" />
              <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
            </filter>
          </defs>
          <polygon points="15,2 27,8.5 27,21.5 15,28 3,21.5 3,8.5"
            fill="rgba(0,229,255,0.08)" stroke="rgba(0,229,255,0.5)" strokeWidth="1"
            filter="url(#hdr-glow)" />
          <polygon points="15,6 24,11 24,19 15,24 6,19 6,11"
            fill="none" stroke="rgba(0,229,255,0.2)" strokeWidth="0.5" />
          <text x="15" y="19" textAnchor="middle"
            style={{ fontFamily: 'monospace', fontSize: 10, fontWeight: 900, fill: '#00e5ff', letterSpacing: 1 }}>
            V
          </text>
        </svg>

        <div>
          <div style={{
            fontSize: 14,
            fontFamily: "'Courier New', monospace",
            fontWeight: 900,
            color: '#00e5ff',
            letterSpacing: '0.35em',
            lineHeight: 1,
            textShadow: '0 0 12px rgba(0,229,255,0.5)',
          }}>
            VAAYU
          </div>
          <div style={{
            fontSize: 8,
            fontFamily: 'monospace',
            color: 'rgba(160,196,224,0.4)',
            letterSpacing: '0.2em',
            marginTop: 1,
          }}>
            ALGOTRADING
          </div>
        </div>
      </div>

      {/* Center — clock */}
      <div className="hdr-clock" style={{ textAlign: 'center', position: 'absolute', left: '50%', transform: 'translateX(-50%)' }}>
        <motion.div
          style={{
            fontSize: 20,
            fontFamily: "'Courier New', monospace",
            fontWeight: 700,
            color: '#00e5ff',
            letterSpacing: '0.1em',
            textShadow: '0 0 10px rgba(0,229,255,0.4)',
            tabularNums: true,
          } as React.CSSProperties}
          key={currentTime.getSeconds()}
          animate={{ opacity: [0.85, 1] }}
          transition={{ duration: 0.5 }}
        >
          {currentTime.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
        </motion.div>
        <div style={{ fontSize: 8, color: 'rgba(160,196,224,0.35)', marginTop: 1, letterSpacing: '0.1em' }}>
          {currentTime.toLocaleDateString('en-IN', { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' }).toUpperCase()}
        </div>
      </div>

      {/* Right — status + logout */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        {/* Status indicators */}
        <div className="hdr-status" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <StatusPill label="SYS" ok={sysOk} />
          <StatusPill label="BROKER" ok={!!brokerOk} />
        </div>

        {/* Balance visibility toggle */}
        <div style={{ width: 1, height: 20, background: 'rgba(0,229,255,0.12)' }} />
        <button
          onClick={toggleBalVisible}
          title={balVisible ? 'Hide balances' : 'Show balances'}
          style={{
            background: balVisible ? 'rgba(0,229,255,0.1)' : 'transparent',
            border: `1px solid ${balVisible ? 'rgba(0,229,255,0.4)' : 'rgba(0,229,255,0.2)'}`,
            color: balVisible ? '#00e5ff' : 'rgba(0,229,255,0.4)',
            width: 28, height: 28,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            cursor: 'pointer', borderRadius: 4, flexShrink: 0,
            transition: 'all 0.2s',
          }}
          onMouseEnter={e => {
            if (!balVisible) {
              (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(0,229,255,0.5)';
              (e.currentTarget as HTMLButtonElement).style.color = 'rgba(0,229,255,0.8)';
            }
          }}
          onMouseLeave={e => {
            if (!balVisible) {
              (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(0,229,255,0.2)';
              (e.currentTarget as HTMLButtonElement).style.color = 'rgba(0,229,255,0.4)';
            }
          }}
        >
          {balVisible ? (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
              <circle cx="12" cy="12" r="3"/>
            </svg>
          ) : (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/>
              <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/>
              <line x1="1" y1="1" x2="23" y2="23"/>
            </svg>
          )}
        </button>

        {onLogout && (
          <>
            <div style={{ width: 1, height: 20, background: 'rgba(0,229,255,0.12)' }} />
            <button
              onClick={onLogout}
              title="Sign out"
              style={{
                background: 'transparent',
                border: '1px solid rgba(0,229,255,0.2)',
                color: 'rgba(0,229,255,0.5)',
                padding: '4px 10px',
                fontSize: 9,
                letterSpacing: '0.15em',
                cursor: 'pointer',
                fontFamily: "'Courier New', monospace",
                borderRadius: 4,
                transition: 'all 0.2s',
              }}
              onMouseEnter={e => {
                (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(0,229,255,0.5)';
                (e.currentTarget as HTMLButtonElement).style.color = '#00e5ff';
              }}
              onMouseLeave={e => {
                (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(0,229,255,0.2)';
                (e.currentTarget as HTMLButtonElement).style.color = 'rgba(0,229,255,0.5)';
              }}
            >
              EXIT
            </button>
          </>
        )}
      </div>
    </header>
  );
}

function StatusPill({ label, ok }: { label: string; ok: boolean }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
      <motion.div
        style={{
          width: 5, height: 5,
          borderRadius: '50%',
          background: ok ? '#4ade80' : '#6b7280',
          flexShrink: 0,
        }}
        animate={ok ? { scale: [1, 1.5, 1], opacity: [1, 0.5, 1] } : {}}
        transition={{ duration: 2, repeat: Infinity }}
      />
      <span style={{
        fontSize: 8,
        fontFamily: 'monospace',
        letterSpacing: '0.1em',
        color: ok ? 'rgba(74,222,128,0.7)' : 'rgba(107,114,128,0.7)',
      }}>
        {label}
      </span>
    </div>
  );
}
