import React, { useEffect, useState } from 'react';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { strategiesApi } from '../../api/client';
import type { StrategyStatus } from '../../types/api';
import { formatDuration } from '../../utils/formatters';

export function StrategyPanel() {
  const [strategies, setStrategies] = useState<StrategyStatus[]>([]);
  const [loading, setLoading] = useState<string | null>(null);
  const [optionsEnabled, setOptionsEnabled] = useState<boolean>(() => {
    return localStorage.getItem('options_trading_enabled') !== 'false';
  });
  const [execMode, setExecMode] = useState<'paper' | 'live'>(() => {
    return (localStorage.getItem('options_exec_mode') as 'paper' | 'live') || 'paper';
  });

  const toggleOptions = () => {
    const next = !optionsEnabled;
    setOptionsEnabled(next);
    localStorage.setItem('options_trading_enabled', String(next));
  };

  const toggleExecMode = (m: 'paper' | 'live') => {
    setExecMode(m);
    localStorage.setItem('options_exec_mode', m);
  };

  useEffect(() => {
    fetchStrategies();
    const interval = setInterval(fetchStrategies, 5000);
    return () => clearInterval(interval);
  }, []);

  const fetchStrategies = async () => {
    try {
      const response = await strategiesApi.getAll();
      setStrategies(response.data);
    } catch (error) {
      console.error('Failed to fetch strategies:', error);
    }
  };

  const handleStart = async (name: string) => {
    setLoading(name);
    try {
      await strategiesApi.start(name, execMode);
      await fetchStrategies();
    } catch (error) {
      console.error(`Failed to start strategy ${name}:`, error);
      alert('Failed to start strategy');
    } finally {
      setLoading(null);
    }
  };

  const handleStop = async (name: string) => {
    setLoading(name);
    try {
      await strategiesApi.stop(name);
      await fetchStrategies();
    } catch (error) {
      console.error(`Failed to stop strategy ${name}:`, error);
      alert('Failed to stop strategy');
    } finally {
      setLoading(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h2 className="text-3xl font-bold text-jarvis-primary glow-text">
            Nifty Options
          </h2>
          <p className="text-xs text-jarvis-text-secondary mt-1 tracking-wider">
            Intraday F&amp;O strategies — Trend / Premium / Scalping
          </p>
        </div>

        <div className="flex items-center gap-5 flex-wrap">
          {/* Paper / Live mode selector */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-jarvis-text-secondary uppercase tracking-wider">Mode:</span>
            <div className="flex rounded overflow-hidden border border-jarvis-primary/30">
              <button
                onClick={() => toggleExecMode('paper')}
                className={`px-3 py-1.5 text-xs font-bold uppercase tracking-wider transition-colors ${
                  execMode === 'paper'
                    ? 'bg-jarvis-primary/20 text-jarvis-primary'
                    : 'text-jarvis-text-secondary hover:text-jarvis-primary'
                }`}
              >
                Paper
              </button>
              <button
                onClick={() => toggleExecMode('live')}
                className={`px-3 py-1.5 text-xs font-bold uppercase tracking-wider transition-colors ${
                  execMode === 'live'
                    ? 'bg-red-500/20 text-red-400 border-l border-red-500/30'
                    : 'text-jarvis-text-secondary hover:text-red-400 border-l border-jarvis-primary/30'
                }`}
              >
                Live
              </button>
            </div>
            {execMode === 'live' && (
              <span className="text-[10px] text-red-400 font-bold tracking-wider">REAL ORDERS</span>
            )}
          </div>

          {/* Enable/disable options trading */}
          <div className="flex items-center gap-3">
            <span className="text-sm text-jarvis-text-secondary">Enable Trading</span>
            <button
              onClick={toggleOptions}
              className="relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none"
              style={{
                background: optionsEnabled ? 'rgba(0,229,255,0.3)' : 'rgba(255,255,255,0.1)',
                border: optionsEnabled ? '1px solid rgba(0,229,255,0.6)' : '1px solid rgba(255,255,255,0.2)',
              }}
              title={optionsEnabled ? 'Click to disable Nifty options trading' : 'Click to enable Nifty options trading'}
            >
            <span
              className="inline-block h-4 w-4 rounded-full transition-transform"
              style={{
                background: optionsEnabled ? '#00e5ff' : '#8aa5c0',
                transform: optionsEnabled ? 'translateX(24px)' : 'translateX(4px)',
              }}
            />
          </button>
          <span
            className="text-xs font-bold uppercase"
            style={{ color: optionsEnabled ? '#00e5ff' : '#8aa5c0' }}
          >
            {optionsEnabled ? 'ON' : 'OFF'}
          </span>
          </div>
        </div>{/* end flex items-center gap-5 */}
      </div>{/* end header row */}

      {!optionsEnabled && (
        <div
          className="p-4 rounded-lg text-sm font-semibold"
          style={{ background: 'rgba(255,214,0,0.08)', border: '1px solid rgba(255,214,0,0.3)', color: '#ffd600' }}
        >
          ⚠ Nifty options trading is disabled. Strategies cannot be started. Toggle above to re-enable.
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {strategies.map((strategy) => (
          <Card key={strategy.name} title={strategy.display_name}>
            <div className="space-y-4">
              {/* Status Indicator */}
              <div className="flex items-center justify-between">
                <span className="text-sm text-jarvis-text-secondary">
                  Status
                </span>
                <div className="flex items-center space-x-2">
                  <div
                    className={`w-3 h-3 rounded-full ${
                      strategy.status === 'running'
                        ? 'bg-green-400 pulse-glow'
                        : 'bg-gray-400'
                    }`}
                  />
                  <span
                    className={`text-sm font-medium ${
                      strategy.status === 'running'
                        ? 'status-running'
                        : 'status-stopped'
                    }`}
                  >
                    {strategy.status.toUpperCase()}
                  </span>
                </div>
              </div>

              {/* Mode */}
              {strategy.mode && (
                <div className="flex items-center justify-between">
                  <span className="text-sm text-jarvis-text-secondary">
                    Mode
                  </span>
                  <span className="text-sm font-mono text-jarvis-accent">
                    {strategy.mode.toUpperCase()}
                  </span>
                </div>
              )}

              {/* Uptime */}
              {strategy.uptime_seconds !== null && (
                <div className="flex items-center justify-between">
                  <span className="text-sm text-jarvis-text-secondary">
                    Uptime
                  </span>
                  <span className="text-sm font-mono text-jarvis-primary">
                    {formatDuration(strategy.uptime_seconds)}
                  </span>
                </div>
              )}

              {/* Signals Generated */}
              <div className="flex items-center justify-between">
                <span className="text-sm text-jarvis-text-secondary">
                  Signals
                </span>
                <span className="text-sm font-mono text-jarvis-primary">
                  {strategy.signals_generated}
                </span>
              </div>

              {/* Active Positions */}
              <div className="flex items-center justify-between">
                <span className="text-sm text-jarvis-text-secondary">
                  Active Positions
                </span>
                <span className="text-sm font-mono text-jarvis-primary">
                  {strategy.active_positions}
                </span>
              </div>

              {/* Control Button */}
              <div className="pt-4 border-t border-jarvis-primary/20">
                {strategy.status === 'running' ? (
                  <Button
                    variant="outline"
                    className="w-full"
                    onClick={() => handleStop(strategy.name)}
                    disabled={loading === strategy.name}
                  >
                    {loading === strategy.name ? 'Stopping...' : 'Stop'}
                  </Button>
                ) : (
                  <Button
                    variant="primary"
                    className="w-full"
                    onClick={() => handleStart(strategy.name)}
                    disabled={loading === strategy.name || !optionsEnabled}
                    title={!optionsEnabled ? 'Options trading is disabled' : undefined}
                  >
                    {loading === strategy.name ? 'Starting...' : `Start (${execMode === 'live' ? 'Live' : 'Paper'})`}
                  </Button>
                )}
              </div>
            </div>
          </Card>
        ))}
      </div>

      {/* Description */}
      <Card title="Strategy Descriptions">
        <div className="space-y-4">
          <div>
            <h4 className="font-semibold text-jarvis-primary mb-2">
              Trend Following
            </h4>
            <p className="text-sm text-jarvis-text-secondary">
              Trades directional market moves using EMA, RSI, MACD, and VWAP
              indicators. Buys call options on uptrends and put options on
              downtrends.
            </p>
          </div>
          <div>
            <h4 className="font-semibold text-jarvis-primary mb-2">
              Premium Selling
            </h4>
            <p className="text-sm text-jarvis-text-secondary">
              Sells option strangles in ranging markets with high IV. Targets
              premium decay and profits from time value erosion.
            </p>
          </div>
          <div>
            <h4 className="font-semibold text-jarvis-primary mb-2">
              Scalping
            </h4>
            <p className="text-sm text-jarvis-text-secondary">
              High-frequency 1-2 minute scalping strategy using support/
              resistance levels. Uses tight stop-losses for quick profits.
            </p>
          </div>
        </div>
      </Card>
    </div>
  );
}
