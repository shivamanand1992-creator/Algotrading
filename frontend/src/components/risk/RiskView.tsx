import React, { useEffect, useState } from 'react';
import { riskApi } from '../../api/client';
import { Card } from '../ui/Card';
import type { RiskLimits } from '../../types/api';

function LimitBar({ label, used, limit, unit = '' }: { label: string; used: number; limit: number; unit?: string }) {
  const pct = limit > 0 ? Math.min((used / limit) * 100, 100) : 0;
  const color = pct > 80 ? 'bg-red-500' : pct > 50 ? 'bg-yellow-400' : 'bg-green-400';

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-sm">
        <span className="text-jarvis-text-secondary">{label}</span>
        <span className="font-mono text-jarvis-text-primary">
          {unit}{used.toFixed(1)} / {unit}{limit} ({pct.toFixed(1)}%)
        </span>
      </div>
      <div className="w-full bg-jarvis-primary/10 rounded-full h-2">
        <div className={`${color} h-2 rounded-full transition-all duration-500`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function RiskView() {
  const [limits, setLimits] = useState<RiskLimits | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await riskApi.getLimits();
        setLimits(res.data);
      } catch (err) {
        console.error('Failed to fetch risk data:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-jarvis-primary animate-pulse text-xl">Loading risk metrics...</div>
      </div>
    );
  }

  const safe = !limits || limits.daily_loss_percentage < 50;

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-jarvis-primary tracking-widest uppercase">Risk Management</h2>

      {limits && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Card className="text-center">
              <div className="text-xs text-jarvis-text-secondary uppercase tracking-wider mb-1">Daily Loss Used</div>
              <div className={`text-2xl font-mono font-bold ${limits.daily_loss_percentage > 80 ? 'text-red-400' : limits.daily_loss_percentage > 50 ? 'text-yellow-400' : 'text-green-400'}`}>
                {limits.daily_loss_percentage.toFixed(2)}%
              </div>
            </Card>
            <Card className="text-center">
              <div className="text-xs text-jarvis-text-secondary uppercase tracking-wider mb-1">Per-Trade Risk</div>
              <div className="text-2xl font-mono font-bold text-jarvis-accent">
                {limits.per_trade_risk_limit}%
              </div>
            </Card>
            <Card className="text-center">
              <div className="text-xs text-jarvis-text-secondary uppercase tracking-wider mb-1">Positions</div>
              <div className="text-2xl font-mono font-bold text-jarvis-primary">
                {limits.current_positions} / {limits.max_positions}
              </div>
            </Card>
          </div>

          <Card title="Limit Usage">
            <div className="space-y-4">
              <LimitBar
                label="Daily Loss Limit"
                used={limits.daily_loss_used}
                limit={limits.daily_loss_limit}
                unit="₹"
              />
              <LimitBar
                label="Position Slots"
                used={limits.current_positions}
                limit={limits.max_positions}
              />
            </div>
          </Card>

          <Card title="System Health">
            <div className={`text-center py-4 font-bold text-lg ${safe ? 'text-green-400' : 'text-yellow-400'}`}>
              {safe ? 'All systems within safe limits' : 'Approaching risk thresholds — monitor closely'}
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
