import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { systemApi } from '../../api/client';
import { ModeToggle } from '../ui/ModeToggle';
import type { SystemStatus } from '../../types/api';

function STSLogo() {
  return (
    <svg width="44" height="44" viewBox="0 0 42 42" fill="none" xmlns="http://www.w3.org/2000/svg">
      <polygon points="21,2 38,11.5 38,30.5 21,40 4,30.5 4,11.5"
        fill="rgba(0,229,255,0.07)" stroke="#00e5ff" strokeWidth="1.2" />
      <polygon points="21,7 34,14.5 34,27.5 21,35 8,27.5 8,14.5"
        fill="none" stroke="rgba(0,229,255,0.25)" strokeWidth="0.6" />
      <polyline points="10,29 16,22 22,25 32,13"
        stroke="#00e5ff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"
        filter="url(#glow)" />
      <circle cx="16" cy="22" r="2.2" fill="#00e5ff" />
      <circle cx="22" cy="25" r="1.6" fill="#1de9b6" />
      <circle cx="32" cy="13" r="2.5" fill="#00e5ff" filter="url(#glow)" />
      <polyline points="29,11 32,13 30,16"
        stroke="#00e5ff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <defs>
        <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="1.8" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
    </svg>
  );
}

export function Header() {
  const [currentTime, setCurrentTime] = useState(new Date());
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [mode, setMode] = useState<string>('demo');

  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const res = await systemApi.getStatus();
        setSystemStatus(res.data);
        setMode(res.data.current_mode || 'demo');
      } catch (e) {
        console.error('Failed to fetch system status:', e);
      }
    };
    fetchStatus();
    const interval = setInterval(fetchStatus, 10000);
    return () => clearInterval(interval);
  }, []);

  const statusColor = (s?: string) =>
    s === 'healthy' ? 'bg-green-400' : s === 'degraded' ? 'bg-yellow-400' : 'bg-gray-500';

  return (
    <motion.header
      className="glass-panel border-b border-jarvis-primary/20 px-6 py-3"
      initial={{ y: -60, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.5, ease: 'easeOut' }}
      style={{ borderRadius: 0 }}
    >
      <div className="flex items-center justify-between gap-4">
        {/* Logo */}
        <div className="flex items-center space-x-3 min-w-fit">
          <motion.div
            className="sts-logo-badge"
            animate={{ rotate: [0, 3, -3, 0] }}
            transition={{ duration: 6, repeat: Infinity, ease: 'easeInOut' }}
          >
            <STSLogo />
          </motion.div>
          <div>
            <h1 className="text-lg font-black text-jarvis-primary glow-text tracking-widest neon-flicker">
              SHIVAM TRADING
            </h1>
            <p className="text-xs text-jarvis-text-secondary tracking-wider">
              Algorithmic Trading System
            </p>
          </div>
        </div>

        {/* Center — clock */}
        <div className="text-center flex-1">
          <motion.div
            className="text-2xl font-mono text-jarvis-primary glow-text tabular-nums"
            key={currentTime.getSeconds()}
            animate={{ opacity: [0.85, 1] }}
            transition={{ duration: 0.5 }}
          >
            {currentTime.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
          </motion.div>
          <div className="text-xs text-jarvis-text-secondary mt-0.5">
            {currentTime.toLocaleDateString('en-IN', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}
          </div>
        </div>

        {/* Right — status + mode toggle */}
        <div className="flex items-center space-x-5 min-w-fit">
          <div className="text-right">
            <div className="text-xs font-semibold text-jarvis-text-secondary uppercase tracking-wider">System</div>
            <div className="flex items-center justify-end space-x-2 mt-1">
              <span className={`w-2 h-2 rounded-full ${statusColor(systemStatus?.status)} pulse-glow`} />
              <span className="text-xs font-mono text-jarvis-text-primary uppercase">
                {systemStatus?.status || 'Unknown'}
              </span>
            </div>
          </div>
          <div className="w-px h-8 bg-jarvis-primary/20" />
          <ModeToggle currentMode={mode} onModeChange={setMode} />
        </div>
      </div>
    </motion.header>
  );
}
