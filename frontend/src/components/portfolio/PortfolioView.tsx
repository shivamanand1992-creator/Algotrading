import React, { useEffect, useState } from 'react';
import { positionsApi } from '../../api/client';
import { Card } from '../ui/Card';
import type { Position, PortfolioSummary } from '../../types/api';

export function PortfolioView() {
  const [positions, setPositions] = useState<Position[]>([]);
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [loading, setLoading] = useState(true);

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
      <h2 className="text-2xl font-bold text-jarvis-primary tracking-widest uppercase">Portfolio</h2>

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
