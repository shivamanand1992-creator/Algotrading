import React, { useEffect, useState } from 'react';
import { Card } from '../ui/Card';
import { api } from '../../api/client';

interface HermesStatus {
  enabled: boolean;
  instrument: string;
  position: any | null;
  trades_today: number;
  daily_pnl: number;
  last_analysis: string | null;
}

interface HermesTrade {
  symbol: string;
  entry_price: number;
  exit_price: number;
  entry_time: string;
  exit_time: string;
  qty: number;
  pnl: number;
  pnl_pct: number;
  setup_type: string;
  exit_reason: string;
  mode: string;
}

export function HermesDashboard() {
  const [status, setStatus] = useState<HermesStatus | null>(null);
  const [trades, setTrades] = useState<HermesTrade[]>([]);
  const [loading, setLoading] = useState(true);
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    fetchStatus();
    fetchTrades();
    const interval = setInterval(() => {
      fetchStatus();
      fetchTrades();
    }, 10000); // Refresh every 10 seconds
    return () => clearInterval(interval);
  }, []);

  const fetchStatus = async () => {
    try {
      const response = await api.get('/api/hermes/status');
      setStatus(response.data);
      setEnabled(response.data.enabled);
      setLoading(false);
    } catch (err) {
      console.error('Failed to fetch Hermes status:', err);
      setLoading(false);
    }
  };

  const fetchTrades = async () => {
    try {
      const response = await api.get('/api/hermes/trades/today');
      setTrades(response.data.trades || []);
    } catch (err) {
      console.error('Failed to fetch trades:', err);
    }
  };

  const handleToggle = async () => {
    try {
      await api.post('/api/hermes/config', { enabled: !enabled });
      setEnabled(!enabled);
      fetchStatus();
    } catch (err) {
      console.error('Failed to toggle Hermes:', err);
    }
  };

  const handleForceExit = async () => {
    if (!window.confirm('Force exit current position?')) return;
    try {
      await api.post('/api/hermes/force-exit');
      fetchStatus();
      fetchTrades();
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to exit position');
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-jarvis-primary font-mono">LOADING HERMES...</div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-4 py-6">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-3xl font-black text-jarvis-primary font-mono tracking-wider mb-2">
          🤖 HERMES AI AGENT
        </h1>
        <p className="text-sm text-jarvis-text-secondary font-mono">
          Fully automated intraday trading powered by AI reasoning
        </p>
      </div>

      {/* Control Panel */}
      <Card title="Control Panel" className="mb-6">
        <div className="flex items-center gap-6 flex-wrap">
          {/* Enable/Disable Toggle */}
          <div className="flex items-center gap-3">
            <span className="text-sm font-bold text-jarvis-text-secondary">STATUS:</span>
            <button
              onClick={handleToggle}
              className="relative inline-flex h-7 w-14 items-center rounded-full transition-all"
              style={{
                background: enabled ? 'rgba(0,230,118,0.2)' : 'rgba(255,255,255,0.1)',
                border: enabled ? '2px solid #00e676' : '2px solid rgba(255,255,255,0.2)',
              }}
            >
              <span
                className="inline-block h-5 w-5 rounded-full transition-transform"
                style={{
                  background: enabled ? '#00e676' : '#8aa5c0',
                  transform: enabled ? 'translateX(30px)' : 'translateX(3px)',
                  boxShadow: enabled ? '0 0 10px #00e676' : 'none',
                }}
              />
            </button>
            <span
              className="text-sm font-black font-mono"
              style={{ color: enabled ? '#00e676' : '#ff5252' }}
            >
              {enabled ? 'ACTIVE' : 'DISABLED'}
            </span>
          </div>

          {/* Instrument */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-jarvis-text-secondary">INSTRUMENT:</span>
            <span className="text-sm font-bold text-jarvis-primary font-mono">
              {status?.instrument || 'N/A'}
            </span>
          </div>

          {/* Daily P&L */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-jarvis-text-secondary">TODAY'S P&L:</span>
            <span
              className="text-lg font-black font-mono"
              style={{
                color: (status?.daily_pnl || 0) >= 0 ? '#00e676' : '#ff5252',
              }}
            >
              ₹{(status?.daily_pnl || 0).toFixed(2)}
            </span>
          </div>

          {/* Trades Count */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-jarvis-text-secondary">TRADES:</span>
            <span className="text-sm font-bold text-jarvis-primary font-mono">
              {status?.trades_today || 0} / 4
            </span>
          </div>

          {/* Force Exit Button */}
          {status?.position && (
            <button
              onClick={handleForceExit}
              className="px-4 py-2 text-xs font-bold rounded-lg transition-all"
              style={{
                background: 'rgba(255,82,82,0.15)',
                border: '1px solid rgba(255,82,82,0.4)',
                color: '#ff5252',
              }}
            >
              🚪 FORCE EXIT
            </button>
          )}
        </div>
      </Card>

      {/* Current Position */}
      {status?.position && (
        <Card title="Current Position" className="mb-6 border-l-4 border-jarvis-primary">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <div className="text-xs text-jarvis-text-secondary mb-1">SYMBOL</div>
              <div className="text-lg font-bold text-jarvis-primary font-mono">
                {status.position.symbol}
              </div>
            </div>
            <div>
              <div className="text-xs text-jarvis-text-secondary mb-1">QTY</div>
              <div className="text-lg font-bold font-mono">{status.position.qty}</div>
            </div>
            <div>
              <div className="text-xs text-jarvis-text-secondary mb-1">ENTRY</div>
              <div className="text-lg font-bold text-green-400 font-mono">
                ₹{status.position.entry_price.toFixed(2)}
              </div>
            </div>
            <div>
              <div className="text-xs text-jarvis-text-secondary mb-1">STOP LOSS</div>
              <div className="text-lg font-bold text-red-400 font-mono">
                ₹{status.position.stop_loss.toFixed(2)}
              </div>
            </div>
            <div>
              <div className="text-xs text-jarvis-text-secondary mb-1">TARGET</div>
              <div className="text-lg font-bold text-green-300 font-mono">
                ₹{status.position.target.toFixed(2)}
              </div>
            </div>
            <div>
              <div className="text-xs text-jarvis-text-secondary mb-1">SETUP</div>
              <div className="text-sm font-mono">{status.position.setup_type}</div>
            </div>
            <div>
              <div className="text-xs text-jarvis-text-secondary mb-1">MODE</div>
              <div
                className="text-sm font-bold font-mono"
                style={{ color: status.position.mode === 'live' ? '#ff1744' : '#00e5ff' }}
              >
                {status.position.mode.toUpperCase()}
              </div>
            </div>
            <div>
              <div className="text-xs text-jarvis-text-secondary mb-1">ENTRY TIME</div>
              <div className="text-xs font-mono">
                {new Date(status.position.entry_time).toLocaleTimeString()}
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* Today's Trades */}
      <Card title={`Today's Trades (${trades.length})`}>
        {trades.length === 0 ? (
          <div className="text-center py-12 text-jarvis-text-secondary">
            <div className="text-4xl mb-4">📊</div>
            <div className="font-semibold">No trades executed yet today</div>
            <div className="text-xs mt-2">
              Hermes will trade when AI confidence ≥ 70% during market hours
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-jarvis-text-secondary border-b border-white/10">
                  <th className="pb-3 text-left">Symbol</th>
                  <th className="pb-3 text-right">Entry</th>
                  <th className="pb-3 text-right">Exit</th>
                  <th className="pb-3 text-right">Qty</th>
                  <th className="pb-3 text-right">P&L</th>
                  <th className="pb-3 text-right">P&L %</th>
                  <th className="pb-3 text-left">Setup</th>
                  <th className="pb-3 text-left">Exit Reason</th>
                  <th className="pb-3 text-center">Mode</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((trade, idx) => (
                  <tr key={idx} className="border-b border-white/5 hover:bg-white/5">
                    <td className="py-3 font-bold text-jarvis-primary">{trade.symbol}</td>
                    <td className="py-3 text-right font-mono text-green-400">
                      ₹{trade.entry_price.toFixed(2)}
                    </td>
                    <td className="py-3 text-right font-mono">
                      ₹{trade.exit_price.toFixed(2)}
                    </td>
                    <td className="py-3 text-right font-mono">{trade.qty}</td>
                    <td
                      className="py-3 text-right font-mono font-bold"
                      style={{ color: trade.pnl >= 0 ? '#00e676' : '#ff5252' }}
                    >
                      {trade.pnl >= 0 ? '+' : ''}₹{trade.pnl.toFixed(2)}
                    </td>
                    <td
                      className="py-3 text-right font-mono"
                      style={{ color: trade.pnl_pct >= 0 ? '#00e676' : '#ff5252' }}
                    >
                      {trade.pnl_pct >= 0 ? '+' : ''}{trade.pnl_pct.toFixed(2)}%
                    </td>
                    <td className="py-3 font-mono text-xs">{trade.setup_type}</td>
                    <td className="py-3 text-xs">{trade.exit_reason}</td>
                    <td className="py-3 text-center">
                      <span
                        className="px-2 py-1 text-xs font-bold rounded"
                        style={{
                          background:
                            trade.mode === 'live'
                              ? 'rgba(255,23,68,0.15)'
                              : 'rgba(0,229,255,0.1)',
                          color: trade.mode === 'live' ? '#ff1744' : '#00e5ff',
                        }}
                      >
                        {trade.mode.toUpperCase()}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Info Footer */}
      <div className="mt-6 p-4 rounded-lg" style={{ background: 'rgba(0,229,255,0.05)' }}>
        <div className="text-xs text-jarvis-text-secondary space-y-1">
          <div>
            <strong className="text-jarvis-primary">Last Analysis:</strong>{' '}
            {status?.last_analysis
              ? new Date(status.last_analysis).toLocaleString()
              : 'Never'}
          </div>
          <div>
            <strong className="text-jarvis-primary">Trading Hours:</strong> 9:15 AM - 3:15 PM
            IST
          </div>
          <div>
            <strong className="text-jarvis-primary">Analysis Frequency:</strong> Every 30
            seconds
          </div>
          <div>
            <strong className="text-jarvis-primary">Note:</strong> All positions are force-exited
            at market close (3:15 PM)
          </div>
        </div>
      </div>
    </div>
  );
}
