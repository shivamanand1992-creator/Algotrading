import React, { useEffect, useState } from 'react';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { strategiesApi } from '../../api/client';
import type { StrategyStatus } from '../../types/api';
import { formatDuration } from '../../utils/formatters';

export function StrategyPanel() {
  const [strategies, setStrategies] = useState<StrategyStatus[]>([]);
  const [loading, setLoading] = useState<string | null>(null);

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
      await strategiesApi.start(name, 'paper');
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
      <h2 className="text-3xl font-bold text-jarvis-primary glow-text">
        Strategy Control
      </h2>

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
                    disabled={loading === strategy.name}
                  >
                    {loading === strategy.name ? 'Starting...' : 'Start (Paper)'}
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
