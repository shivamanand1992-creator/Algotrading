import React, { useState, useEffect } from 'react';
import { systemApi } from '../../api/client';
import type { SystemStatus } from '../../types/api';

function STSLogo() {
  return (
    <svg width="42" height="42" viewBox="0 0 42 42" fill="none" xmlns="http://www.w3.org/2000/svg">
      {/* Outer hexagon */}
      <polygon
        points="21,2 38,11.5 38,30.5 21,40 4,30.5 4,11.5"
        fill="rgba(0,229,255,0.08)"
        stroke="#00e5ff"
        strokeWidth="1.2"
      />
      {/* Inner glow hexagon */}
      <polygon
        points="21,7 34,14.5 34,27.5 21,35 8,27.5 8,14.5"
        fill="none"
        stroke="rgba(0,229,255,0.3)"
        strokeWidth="0.6"
      />
      {/* Chart line — rising trend */}
      <polyline
        points="10,29 16,22 22,25 32,13"
        stroke="#00e5ff"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        filter="url(#glow)"
      />
      {/* Nodes */}
      <circle cx="16" cy="22" r="2" fill="#00e5ff" />
      <circle cx="22" cy="25" r="1.5" fill="#1de9b6" />
      <circle cx="32" cy="13" r="2.2" fill="#00e5ff" filter="url(#glow)" />
      {/* Arrow tip */}
      <polyline
        points="29,11 32,13 30,16"
        stroke="#00e5ff"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <defs>
        <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="1.5" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
    </svg>
  );
}

export function Header() {
  const [currentTime, setCurrentTime] = useState(new Date());
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);

  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const response = await systemApi.getStatus();
        setSystemStatus(response.data);
      } catch (error) {
        console.error('Failed to fetch system status:', error);
      }
    };
    fetchStatus();
    const interval = setInterval(fetchStatus, 10000);
    return () => clearInterval(interval);
  }, []);

  const getStatusColor = (status?: string) => {
    switch (status) {
      case 'healthy': return 'bg-green-400';
      case 'degraded': return 'bg-yellow-400';
      case 'down': return 'bg-red-400';
      default: return 'bg-gray-400';
    }
  };

  return (
    <header className="glass-panel border-b border-jarvis-primary/30 px-6 py-4">
      <div className="flex items-center justify-between">
        {/* Logo */}
        <div className="flex items-center space-x-3">
          <div className="sts-logo-badge">
            <STSLogo />
          </div>
          <div>
            <h1 className="text-xl font-bold text-jarvis-primary glow-text tracking-widest">
              SHIVAM TRADING
            </h1>
            <p className="text-xs text-jarvis-text-secondary tracking-wider">
              Algorithmic Trading System
            </p>
          </div>
        </div>

        {/* Center - Date/Time */}
        <div className="text-center">
          <div className="text-2xl font-mono text-jarvis-primary glow-text">
            {currentTime.toLocaleTimeString('en-IN', {
              hour: '2-digit', minute: '2-digit', second: '2-digit',
            })}
          </div>
          <div className="text-sm text-jarvis-text-secondary">
            {currentTime.toLocaleDateString('en-IN', {
              weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
            })}
          </div>
        </div>

        {/* System Status */}
        <div className="flex items-center space-x-4">
          <div className="text-right">
            <div className="text-sm font-medium text-jarvis-text-primary">
              System Status
            </div>
            <div className="flex items-center justify-end space-x-2 mt-1">
              <span
                className={`inline-block w-2 h-2 rounded-full ${getStatusColor(systemStatus?.status)} pulse-glow`}
              />
              <span className="text-xs text-jarvis-text-secondary uppercase">
                {systemStatus?.status || 'Unknown'}
              </span>
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs text-jarvis-text-secondary">Mode</div>
            <div className="text-sm font-mono text-jarvis-accent">
              {systemStatus?.current_mode?.toUpperCase() || 'N/A'}
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}
