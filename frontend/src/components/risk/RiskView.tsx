import React, { useEffect, useState } from 'react';
import { riskApi } from '../../api/client';
import { Card } from '../ui/Card';

interface RiskLimit {
  name: string;
  current: number;
  limit: number;
  pct_used: number;
  unit: string;
}

interface RiskMetrics {
  daily_limits: RiskLimit[];
  max_drawdown: number;
  var_95: number;
  position_count: number;
  alerts: string[];
}

function RiskBar({ item }: { item: RiskLimit }) {
  const color =
    item.pct_used > 80 ? 'bg-red-500' : item.pct_used > 50 ? 'bg-yellow-400' : 'bg-green-400';

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-sm">
        <span className="text-jarvis-text-secondary">{item.name}</span>
        <span className="font-mono text-jarvis-text-primary">
          {item.current.toFixed(1)}{item.unit} / {item.limit}{item.unit} ({item.pct_used.toFixed(1)}%)
        </span>
      </div>
      <div className="w-full bg-jarvis-primary/10 rounded-full h-2">
        <div
          className={`${color} h-2 rounded-full transition-all duration-500`}
          style={{ width: `${Math.min(item.pct_used, 100)}%` }}
        />
      </div>
    </div>
  );
}

export function RiskView() {
  const [metrics, setMetrics] = useState<RiskMetrics | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await riskApi.getLimits();
        setMetrics(res.data);
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

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-jarvis-primary tracking-widest uppercase">Risk Management</h2>

      {metrics && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Card className="text-center">
              <div className="text-xs text-jarvis-text-secondary uppercase tracking-wider mb-1">Max Drawdown</div>
              <div className="text-2xl font-mono font-bold text-red-400">
                {metrics.max_drawdown?.toFixed(2) ?? '0.00'}%
              </div>
            </Card>
            <Card className="text-center">
              <div className="text-xs text-jarvis-text-secondary uppercase tracking-wider mb-1">VaR (95%)</div>
              <div className="text-2xl font-mono font-bold text-yellow-400">
                ₹{metrics.var_95?.toLocaleString('en-IN') ?? '0'}
              </div>
            </Card>
            <Card className="text-center">
              <div className="text-xs text-jarvis-text-secondary uppercase tracking-wider mb-1">Open Positions</div>
              <div className="text-2xl font-mono font-bold text-jarvis-primary">
                {metrics.position_count ?? 0}
              </div>
            </Card>
          </div>

          <Card title="Daily Limits">
            <div className="space-y-4">
              {(metrics.daily_limits || []).map((limit) => (
                <RiskBar key={limit.name} item={limit} />
              ))}
            </div>
          </Card>

          {metrics.alerts && metrics.alerts.length > 0 && (
            <Card title="Active Alerts">
              <div className="space-y-2">
                {metrics.alerts.map((alert, i) => (
                  <div key={i} className="flex items-center space-x-2 text-red-400">
                    <span>⚠</span>
                    <span className="text-sm">{alert}</span>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {(!metrics.alerts || metrics.alerts.length === 0) && (
            <Card title="Active Alerts">
              <div className="text-green-400 text-center py-4">All systems within safe limits</div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
