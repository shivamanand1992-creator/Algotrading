import React, { useState, useEffect } from 'react';
import { systemApi } from '../../api/client';
import type { SystemStatus } from '../../types/api';

export function Header() {
  const [currentTime, setCurrentTime] = useState(new Date());
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);

  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(new Date());
    }, 1000);

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
      case 'healthy':
        return 'bg-green-400';
      case 'degraded':
        return 'bg-yellow-400';
      case 'down':
        return 'bg-red-400';
      default:
        return 'bg-gray-400';
    }
  };

  return (
    <header className="glass-panel border-b border-jarvis-primary/30 px-6 py-4">
      <div className="flex items-center justify-between">
        {/* Logo */}
        <div className="flex items-center space-x-3">
          <div className="w-10 h-10 rounded-full bg-gradient-to-br from-jarvis-primary to-jarvis-accent flex items-center justify-center glow">
            <span className="text-jarvis-bg-dark font-bold text-xl">J</span>
          </div>
          <div>
            <h1 className="text-xl font-bold text-jarvis-primary glow-text">
              JARVIS TRADING
            </h1>
            <p className="text-xs text-jarvis-text-secondary">
              Algorithmic Trading Platform
            </p>
          </div>
        </div>

        {/* Center - Date/Time */}
        <div className="text-center">
          <div className="text-2xl font-mono text-jarvis-primary glow-text">
            {currentTime.toLocaleTimeString('en-IN', {
              hour: '2-digit',
              minute: '2-digit',
              second: '2-digit',
            })}
          </div>
          <div className="text-sm text-jarvis-text-secondary">
            {currentTime.toLocaleDateString('en-IN', {
              weekday: 'long',
              year: 'numeric',
              month: 'long',
              day: 'numeric',
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
                className={`inline-block w-2 h-2 rounded-full ${getStatusColor(
                  systemStatus?.status
                )} pulse-glow`}
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
