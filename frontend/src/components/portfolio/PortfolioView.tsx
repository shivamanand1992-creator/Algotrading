import React, { useEffect, useState } from 'react';
import { positionsApi, api } from '../../api/client';
import { Card } from '../ui/Card';
import type { Position, PortfolioSummary } from '../../types/api';

export function PortfolioView() {
  const [positions, setPositions] = useState<Position[]>([]);
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [squaringOff, setSquaringOff] = useState(false);
  const [squareOffMsg, setSquareOffMsg] = useState<{ text: string; ok: boolean } | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [posRes, sumRes] = await Promise.all([
          positionsApi.getAll(),
          positionsApi.getPortfolio(),
        ]);
        setPositions(Array.isArray(posRes.data) ? posRes.data : []);
        setSummary(sumRes.data);
      } catch (err) {
        console.error('Failed to fetch portfolio data:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, []);

  const handleSquareOff = async () => {
    if (!window.confirm('Square off ALL open positions and stop all strategies now?')) return;
    setSquaringOff(true);
    setSquareOffMsg(null);
    try {
      const res = await api.post('/api/system/squareoff');
      setSquareOffMsg({ text: res.data.message, ok: res.data.success });
      // Refresh data immediately
      const [posRes, sumRes] = await Promise.all([positionsApi.getAll(), positionsApi.getPortfolio()]);
      setPositions(Array.isArray(posRes.data) ? posRes.data : []);
      setSummary(sumRes.data);
    } catch {
      setSquareOffMsg({ text: 'Square-off request failed — check logs.', ok: false });
    } finally {
      setSquaringOff(false);
    }
  };

  const fmt = (n: number) =>
    new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(n);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-jarvis-primary animate-pulse text-xl">Loading portfolio...</div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-jarvis-primary tracking-widest uppercase">F&amp;O Portfolio</h2>
          <p className="text-xs text-jarvis-text-secondary mt-1 tracking-wider">Open Nifty options positions · Capital allocation</p>
        </div>
        <div className="flex items-center gap-4">
          {squareOffMsg && (
            <span className={`text-xs font-mono tracking-wider ${squareOffMsg.ok ? 'text-green-400' : 'text-red-400'}`}>
              {squareOffMsg.text}
            </span>
          )}
          <button
            onClick={handleSquareOff}
            disabled={squaringOff || positions.length === 0}
            style={{
              padding: '8px 18px',
              background: 'transparent',
              border: '1px solid rgba(255,68,68,0.6)',
              color: 'rgba(255,68,68,0.9)',
              fontSize: 11,
              letterSpacing: 3,
              fontFamily: "'Courier New', monospace",
              cursor: positions.length === 0 ? 'not-allowed' : 'pointer',
              opacity: positions.length === 0 ? 0.4 : 1,
              transition: 'all 0.2s',
            }}
            onMouseEnter={e => { if (positions.length > 0) { (e.target as HTMLButtonElement).style.background = 'rgba(255,68,68,0.1)'; (e.target as HTMLButtonElement).style.boxShadow = '0 0 12px rgba(255,68,68,0.2)'; } }}
            onMouseLeave={e => { (e.target as HTMLButtonElement).style.background = 'transparent'; (e.target as HTMLButtonElement).style.boxShadow = 'none'; }}
          >
            {squaringOff ? 'CLOSING...' : '⬛ SQUARE OFF ALL'}
          </button>
        </div>
      </div>

      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'Total Capital', value: fmt(summary.total_capital), color: 'text-jarvis-primary' },
            { label: 'Used Capital', value: fmt(summary.used_capital), color: 'text-yellow-400' },
            { label: 'Available', value: fmt(summary.available_capital), color: 'text-jarvis-accent' },
            {
              label: 'Total P&L',
              value: `${summary.total_pnl >= 0 ? '+' : ''}${fmt(summary.total_pnl)} (${summary.total_pnl_percentage.toFixed(2)}%)`,
              color: summary.total_pnl >= 0 ? 'text-green-400' : 'text-red-400',
            },
          ].map((item) => (
            <Card key={item.label} className="text-center">
              <div className="text-xs text-jarvis-text-secondary uppercase tracking-wider mb-1">{item.label}</div>
              <div className={`text-lg font-mono font-bold ${item.color}`}>{item.value}</div>
            </Card>
          ))}
        </div>
      )}

      <Card title={`Open Positions (${positions.length})`}>
        {positions.length === 0 ? (
          <div className="text-jarvis-text-secondary text-center py-8">No open positions</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-jarvis-text-secondary text-xs uppercase border-b border-jarvis-primary/20">
                  <th className="text-left py-2 pr-4">Symbol</th>
                  <th className="text-right py-2 pr-4">Qty</th>
                  <th className="text-right py-2 pr-4">Entry</th>
                  <th className="text-right py-2 pr-4">LTP</th>
                  <th className="text-right py-2 pr-4">P&L</th>
                  <th className="text-left py-2">Strategy</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((pos) => (
                  <tr
                    key={pos.order_id}
                    className="border-b border-jarvis-primary/10 hover:bg-jarvis-primary/5 transition-colors"
                  >
                    <td className="py-3 pr-4 font-mono text-jarvis-primary">{pos.symbol}</td>
                    <td className="py-3 pr-4 text-right font-mono">{pos.qty}</td>
                    <td className="py-3 pr-4 text-right font-mono">{pos.entry_price.toFixed(2)}</td>
                    <td className="py-3 pr-4 text-right font-mono">{pos.current_price.toFixed(2)}</td>
                    <td className={`py-3 pr-4 text-right font-mono font-bold ${pos.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {pos.unrealized_pnl >= 0 ? '+' : ''}{pos.unrealized_pnl.toFixed(2)}
                    </td>
                    <td className="py-3 text-jarvis-text-secondary text-xs uppercase">{pos.strategy}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
