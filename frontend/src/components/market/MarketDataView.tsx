import React, { useEffect, useState } from 'react';
import { marketApi } from '../../api/client';
import { Card } from '../ui/Card';
import type { MarketData, MarketRegime, Prediction } from '../../types/api';

export function MarketDataView() {
  const [market, setMarket] = useState<MarketData | null>(null);
  const [regime, setRegime] = useState<MarketRegime | null>(null);
  const [prediction, setPrediction] = useState<Prediction | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [mRes, rRes, pRes] = await Promise.all([
          marketApi.getCurrent(),
          marketApi.getRegime(),
          marketApi.getPredictions(),
        ]);
        setMarket(mRes.data);
        setRegime(rRes.data);
        setPrediction(pRes.data);
      } catch (err) {
        console.error('Failed to fetch market data:', err);
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
        <div className="text-jarvis-primary animate-pulse text-xl">Loading market data...</div>
      </div>
    );
  }

  const regimeColor = (r: string) => {
    const lower = r?.toLowerCase() ?? '';
    if (lower.includes('up') || lower === 'bullish') return 'text-green-400';
    if (lower.includes('down') || lower === 'bearish') return 'text-red-400';
    return 'text-yellow-400';
  };

  const directionIcon = (dir: string) => {
    const d = dir?.toLowerCase() ?? '';
    if (d === 'bullish' || d === 'up') return '▲';
    if (d === 'bearish' || d === 'down') return '▼';
    return '→';
  };

  const confidencePct = (c: number) => c > 1 ? c : Math.round(c * 100);

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-jarvis-primary tracking-widest uppercase">Market Analytics</h2>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card title="Live Market">
          {market ? (
            <div className="space-y-4">
              <div className="flex items-end space-x-3">
                <span className="text-4xl font-mono font-bold text-jarvis-primary glow-text">
                  {market.ltp.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                </span>
                <span className={`text-lg font-mono ${market.change >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {market.change >= 0 ? '+' : ''}{market.change.toFixed(2)} ({market.change_percentage.toFixed(2)}%)
                </span>
              </div>
              <div className="grid grid-cols-2 gap-4 mt-4">
                <div>
                  <div className="text-xs text-jarvis-text-secondary uppercase">IV Percentile</div>
                  <div className="text-xl font-mono text-jarvis-accent">{market.iv_percentile}%</div>
                </div>
                <div>
                  <div className="text-xs text-jarvis-text-secondary uppercase">PCR</div>
                  <div className="text-xl font-mono text-jarvis-accent">{market.pcr?.toFixed(2) ?? 'N/A'}</div>
                </div>
              </div>
            </div>
          ) : (
            <div className="text-jarvis-text-secondary">No data available</div>
          )}
        </Card>

        <Card title="Market Regime">
          {regime ? (
            <div className="space-y-4">
              <div className={`text-3xl font-bold uppercase tracking-widest ${regimeColor(regime.current_regime)}`}>
                {regime.current_regime?.replace(/_/g, ' ') || 'Unknown'}
              </div>
              <div className="w-full bg-jarvis-primary/10 rounded-full h-2">
                <div
                  className="bg-jarvis-primary h-2 rounded-full transition-all duration-500"
                  style={{ width: `${confidencePct(regime.confidence)}%` }}
                />
              </div>
              <div className="text-xs text-jarvis-text-secondary">
                Confidence: {confidencePct(regime.confidence)}%
              </div>
            </div>
          ) : (
            <div className="text-jarvis-text-secondary">No data available</div>
          )}
        </Card>
      </div>

      {prediction && (
        <Card title="ML Prediction">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="text-center">
              <div className="text-xs text-jarvis-text-secondary uppercase mb-2">Direction</div>
              <div className={`text-5xl font-bold ${regimeColor(prediction.direction_label)}`}>
                {directionIcon(prediction.direction_label)}
              </div>
              <div className={`text-lg uppercase mt-2 font-bold ${regimeColor(prediction.direction_label)}`}>
                {prediction.direction_label}
              </div>
            </div>
            <div className="text-center">
              <div className="text-xs text-jarvis-text-secondary uppercase mb-2">Confidence</div>
              <div className="text-4xl font-mono font-bold text-jarvis-primary glow-text">
                {confidencePct(prediction.confidence)}%
              </div>
              <div className="w-full bg-jarvis-primary/10 rounded-full h-2 mt-3">
                <div
                  className="bg-jarvis-primary h-2 rounded-full"
                  style={{ width: `${confidencePct(prediction.confidence)}%` }}
                />
              </div>
            </div>
            <div className="text-center">
              <div className="text-xs text-jarvis-text-secondary uppercase mb-2">Model Agreement</div>
              <div className="text-3xl font-mono font-bold text-jarvis-accent">
                {confidencePct(prediction.model_agreement ?? 0)}%
              </div>
              <div className="text-xs text-jarvis-text-secondary mt-2">
                Predicted move: {prediction.predicted_move?.toFixed(2) ?? 'N/A'}%
              </div>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
