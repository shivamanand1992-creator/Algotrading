import React, { useEffect, useState } from 'react';
import { marketApi } from '../../api/client';
import { Card } from '../ui/Card';

interface MarketData {
  nifty_price: number;
  change: number;
  change_pct: number;
  iv_percentile: number;
  pcr: number;
  regime: string;
  regime_confidence: number;
}

interface Prediction {
  direction: string;
  confidence: number;
  target_price: number;
  model: string;
}

export function MarketDataView() {
  const [market, setMarket] = useState<MarketData | null>(null);
  const [prediction, setPrediction] = useState<Prediction | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [mRes, pRes] = await Promise.all([
          marketApi.getCurrent(),
          marketApi.getPredictions(),
        ]);
        setMarket(mRes.data);
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

  const regimeColor = (regime: string) => {
    if (regime?.includes('up') || regime === 'bullish') return 'text-green-400';
    if (regime?.includes('down') || regime === 'bearish') return 'text-red-400';
    return 'text-yellow-400';
  };

  const directionIcon = (dir: string) => {
    if (dir === 'bullish' || dir === 'up') return '▲';
    if (dir === 'bearish' || dir === 'down') return '▼';
    return '→';
  };

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-jarvis-primary tracking-widest uppercase">Market Analytics</h2>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card title="Live Market">
          {market ? (
            <div className="space-y-4">
              <div className="flex items-end space-x-3">
                <span className="text-4xl font-mono font-bold text-jarvis-primary glow-text">
                  {market.nifty_price.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                </span>
                <span className={`text-lg font-mono ${market.change >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {market.change >= 0 ? '+' : ''}{market.change.toFixed(2)} ({market.change_pct.toFixed(2)}%)
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
          {market ? (
            <div className="space-y-4">
              <div className={`text-3xl font-bold uppercase tracking-widest ${regimeColor(market.regime)}`}>
                {market.regime?.replace(/_/g, ' ') || 'Unknown'}
              </div>
              <div className="w-full bg-jarvis-primary/10 rounded-full h-2">
                <div
                  className="bg-jarvis-primary h-2 rounded-full transition-all duration-500"
                  style={{ width: `${market.regime_confidence ?? 0}%` }}
                />
              </div>
              <div className="text-xs text-jarvis-text-secondary">
                Confidence: {market.regime_confidence ?? 0}%
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
              <div className={`text-5xl font-bold ${regimeColor(prediction.direction)}`}>
                {directionIcon(prediction.direction)}
              </div>
              <div className={`text-lg uppercase mt-2 font-bold ${regimeColor(prediction.direction)}`}>
                {prediction.direction}
              </div>
            </div>
            <div className="text-center">
              <div className="text-xs text-jarvis-text-secondary uppercase mb-2">Confidence</div>
              <div className="text-4xl font-mono font-bold text-jarvis-primary glow-text">
                {prediction.confidence}%
              </div>
              <div className="w-full bg-jarvis-primary/10 rounded-full h-2 mt-3">
                <div
                  className="bg-jarvis-primary h-2 rounded-full"
                  style={{ width: `${prediction.confidence}%` }}
                />
              </div>
            </div>
            <div className="text-center">
              <div className="text-xs text-jarvis-text-secondary uppercase mb-2">Target Price</div>
              <div className="text-3xl font-mono font-bold text-jarvis-accent">
                {prediction.target_price?.toLocaleString('en-IN', { maximumFractionDigits: 0 }) ?? 'N/A'}
              </div>
              <div className="text-xs text-jarvis-text-secondary mt-2">{prediction.model}</div>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
