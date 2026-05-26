import React, { useEffect, useState, useCallback } from 'react';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { motion } from 'framer-motion';
import { marketApi } from '../../api/client';
import { Card } from '../ui/Card';
import { useWebSocket } from '../../hooks/useWebSocket';
import type { MarketData, MarketRegime, Prediction, OHLCVCandle } from '../../types/api';

type Interval = 'FIVE_MINUTE' | 'FIFTEEN_MINUTE' | 'ONE_HOUR' | 'ONE_DAY';
const INTERVAL_OPTIONS: { label: string; value: Interval; days: number }[] = [
  { label: '1D',  value: 'FIVE_MINUTE',    days: 1  },
  { label: '5D',  value: 'FIFTEEN_MINUTE', days: 5  },
  { label: '1M',  value: 'ONE_HOUR',       days: 30 },
];

function fmtTime(ts: string, interval: Interval): string {
  try {
    const d = new Date(ts);
    if (interval === 'ONE_DAY') return d.toLocaleDateString('en-IN', { month: 'short', day: 'numeric' });
    if (interval === 'ONE_HOUR') return d.toLocaleDateString('en-IN', { month: 'short', day: 'numeric' }) + ' ' + d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false });
    return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false });
  } catch { return ts.slice(11, 16); }
}

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload as OHLCVCandle & { displayTime: string };
  return (
    <div className="rounded-xl px-4 py-3 text-xs" style={{ background: 'rgba(0,15,35,0.95)', border: '1px solid rgba(0,229,255,0.3)', minWidth: 160 }}>
      <p className="text-jarvis-text-secondary mb-2">{d?.displayTime ?? label}</p>
      <div className="space-y-0.5 font-mono">
        <div className="flex justify-between gap-4"><span className="text-jarvis-text-secondary">Open</span><span className="text-white">{d?.open?.toFixed(2)}</span></div>
        <div className="flex justify-between gap-4"><span className="text-green-400">High</span><span className="text-green-400">{d?.high?.toFixed(2)}</span></div>
        <div className="flex justify-between gap-4"><span className="text-red-400">Low</span><span className="text-red-400">{d?.low?.toFixed(2)}</span></div>
        <div className="flex justify-between gap-4"><span className="text-jarvis-primary">Close</span><span className="text-jarvis-primary font-bold">{d?.close?.toFixed(2)}</span></div>
        <div className="flex justify-between gap-4"><span className="text-jarvis-text-secondary">Vol</span><span className="text-jarvis-accent">{d?.volume?.toLocaleString()}</span></div>
      </div>
    </div>
  );
}

const regimeColor = (r: string) => {
  const l = r?.toLowerCase() ?? '';
  if (l.includes('up') || l === 'bullish') return 'text-green-400';
  if (l.includes('down') || l === 'bearish') return 'text-red-400';
  if (l.includes('volatile')) return 'text-yellow-400';
  return 'text-yellow-400';
};

const directionIcon = (dir: string) => {
  const d = dir?.toLowerCase() ?? '';
  if (d === 'up' || d === 'bullish') return '▲';
  if (d === 'down' || d === 'bearish') return '▼';
  return '→';
};

const confidencePct = (c: number) => c > 1 ? c : Math.round(c * 100);

export function MarketDataView() {
  const { marketData: wsMarket } = useWebSocket();
  const [market, setMarket]       = useState<MarketData | null>(null);
  const [regime, setRegime]       = useState<MarketRegime | null>(null);
  const [prediction, setPrediction] = useState<Prediction | null>(null);
  const [candles, setCandles]     = useState<(OHLCVCandle & { displayTime: string })[]>([]);
  const [interval, setSelectedInterval] = useState<Interval>('FIFTEEN_MINUTE');
  const [days, setDays]           = useState(5);
  const [chartLoading, setChartLoading] = useState(true);
  const [loading, setLoading]     = useState(true);

  const fetchAnalysis = useCallback(async () => {
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
      console.error('Market data fetch error:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchCandles = useCallback(async (iv: Interval, d: number) => {
    setChartLoading(true);
    try {
      const res = await marketApi.getOHLCV(iv, d);
      const data = (res.data ?? []).map(c => ({ ...c, displayTime: fmtTime(c.timestamp, iv) }));
      setCandles(data);
    } catch (err) {
      console.error('OHLCV fetch error:', err);
    } finally {
      setChartLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAnalysis();
    const iv = setInterval(fetchAnalysis, 15000);
    return () => clearInterval(iv);
  }, [fetchAnalysis]);

  useEffect(() => {
    fetchCandles(interval, days);
    const iv = setInterval(() => fetchCandles(interval, days), 30000);
    return () => clearInterval(iv);
  }, [interval, days, fetchCandles]);

  // Append live tick from WebSocket to chart
  useEffect(() => {
    if (!wsMarket) return;
    setMarket(wsMarket);
    if (candles.length > 0 && interval === 'FIVE_MINUTE') {
      setCandles(prev => {
        const last = prev[prev.length - 1];
        if (!last) return prev;
        const updated = { ...last, close: wsMarket.ltp, high: Math.max(last.high, wsMarket.ltp), low: Math.min(last.low, wsMarket.ltp) };
        return [...prev.slice(0, -1), updated];
      });
    }
  }, [wsMarket, candles.length, interval]);

  const handleIntervalChange = (opt: typeof INTERVAL_OPTIONS[0]) => {
    setSelectedInterval(opt.value);
    setDays(opt.days);
  };

  const firstClose = candles[0]?.close ?? 0;
  const lastClose  = candles[candles.length - 1]?.close ?? 0;
  const chartColor = lastClose >= firstClose ? '#4ade80' : '#f87171';
  const minY = candles.length ? Math.floor(Math.min(...candles.map(c => c.low)) / 50) * 50 : 0;
  const maxY = candles.length ? Math.ceil(Math.max(...candles.map(c => c.high)) / 50) * 50 : 0;

  const xTicks = candles.length > 20
    ? candles.filter((_, i) => i % Math.floor(candles.length / 8) === 0).map(c => c.displayTime)
    : candles.map(c => c.displayTime);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-jarvis-primary animate-pulse text-xl">Loading market data...</div>
      </div>
    );
  }

  return (
    <motion.div
      className="space-y-6"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
    >
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-jarvis-primary tracking-widest uppercase">Market Analytics</h2>
        {market && (
          <motion.div
            className="flex items-center gap-3"
            key={market.ltp}
            initial={{ scale: 1.05 }}
            animate={{ scale: 1 }}
          >
            <span className="text-3xl font-black font-mono text-jarvis-primary glow-text tabular-nums">
              {market.ltp.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
            </span>
            <span className={`text-lg font-mono font-bold ${market.change >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {market.change >= 0 ? '+' : ''}{market.change.toFixed(2)} ({market.change_percentage.toFixed(2)}%)
            </span>
          </motion.div>
        )}
      </div>

      {/* Nifty OHLCV Chart */}
      <div className="rounded-2xl p-5" style={{ background: 'rgba(0,15,35,0.7)', border: '1px solid rgba(0,229,255,0.2)' }}>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-jarvis-primary tracking-wider uppercase">NIFTY 50</span>
            <span className={`text-xs font-mono font-bold ${lastClose >= firstClose ? 'text-green-400' : 'text-red-400'}`}>
              {candles.length > 0 && firstClose > 0 && `${lastClose >= firstClose ? '+' : ''}${((lastClose - firstClose) / firstClose * 100).toFixed(2)}%`}
            </span>
          </div>
          <div className="flex gap-1">
            {INTERVAL_OPTIONS.map(opt => (
              <button
                key={opt.value}
                onClick={() => handleIntervalChange(opt)}
                className={`px-3 py-1 rounded text-xs font-bold transition-all ${
                  interval === opt.value
                    ? 'bg-jarvis-primary/20 text-jarvis-primary border border-jarvis-primary/50'
                    : 'text-jarvis-text-secondary hover:text-jarvis-primary border border-transparent hover:border-jarvis-primary/30'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {chartLoading ? (
          <div className="h-72 flex items-center justify-center">
            <div className="text-jarvis-primary animate-pulse text-sm">Fetching candles...</div>
          </div>
        ) : candles.length === 0 ? (
          <div className="h-72 flex items-center justify-center flex-col gap-2">
            <div className="text-jarvis-text-secondary text-sm">No chart data available</div>
            <div className="text-jarvis-text-secondary/50 text-xs">Market data is only available during trading hours (9:15–15:30 IST, weekdays)</div>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={candles} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
              <defs>
                <linearGradient id="priceGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor={chartColor} stopOpacity={0.3} />
                  <stop offset="95%" stopColor={chartColor} stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,229,255,0.06)" />
              <XAxis
                dataKey="displayTime"
                ticks={xTicks}
                tick={{ fill: 'rgba(160,196,224,0.7)', fontSize: 10 }}
                axisLine={{ stroke: 'rgba(0,229,255,0.15)' }}
                tickLine={false}
              />
              <YAxis
                domain={[minY, maxY]}
                tick={{ fill: 'rgba(160,196,224,0.7)', fontSize: 10 }}
                axisLine={{ stroke: 'rgba(0,229,255,0.15)' }}
                tickLine={false}
                tickFormatter={v => v.toLocaleString('en-IN')}
                width={70}
              />
              <Tooltip content={<CustomTooltip />} />
              {firstClose > 0 && (
                <ReferenceLine y={firstClose} stroke="rgba(160,196,224,0.3)" strokeDasharray="4 4" />
              )}
              <Area
                type="monotone"
                dataKey="close"
                stroke={chartColor}
                strokeWidth={2}
                fill="url(#priceGradient)"
                dot={false}
                activeDot={{ r: 4, fill: chartColor, strokeWidth: 0 }}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Regime + Prediction + Market Stats row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card title="Market Regime">
          {regime ? (
            <div className="space-y-3">
              <div className={`text-2xl font-bold uppercase tracking-widest ${regimeColor(regime.current_regime)}`}>
                {regime.current_regime?.replace(/_/g, ' ') || 'Unknown'}
              </div>
              <div>
                <div className="flex justify-between text-xs text-jarvis-text-secondary mb-1">
                  <span>Confidence</span>
                  <span>{confidencePct(regime.confidence)}%</span>
                </div>
                <div className="w-full bg-jarvis-primary/10 rounded-full h-2">
                  <motion.div
                    className="bg-jarvis-primary h-2 rounded-full"
                    initial={{ width: 0 }}
                    animate={{ width: `${confidencePct(regime.confidence)}%` }}
                    transition={{ duration: 0.6 }}
                  />
                </div>
              </div>
              <div className="space-y-1 pt-1">
                {Object.entries(regime.regime_probabilities || {}).map(([k, v]) => (
                  <div key={k} className="flex items-center gap-2">
                    <div className="text-xs text-jarvis-text-secondary w-28 truncate">{k.replace(/_/g, ' ')}</div>
                    <div className="flex-1 bg-jarvis-primary/10 rounded-full h-1.5">
                      <div className="bg-jarvis-primary/60 h-1.5 rounded-full" style={{ width: `${Math.round((v as number) * 100)}%` }} />
                    </div>
                    <div className="text-xs font-mono text-jarvis-text-secondary w-8 text-right">{Math.round((v as number) * 100)}%</div>
                  </div>
                ))}
              </div>
            </div>
          ) : <div className="text-jarvis-text-secondary text-sm">Awaiting data…</div>}
        </Card>

        <Card title="ML Prediction">
          {prediction ? (
            <div className="space-y-3">
              <div className="flex items-center gap-3">
                <span className={`text-4xl font-bold ${regimeColor(prediction.direction_label)}`}>
                  {directionIcon(prediction.direction_label)}
                </span>
                <div>
                  <div className={`text-xl font-bold uppercase ${regimeColor(prediction.direction_label)}`}>
                    {prediction.direction_label}
                  </div>
                  <div className="text-xs text-jarvis-text-secondary">Direction</div>
                </div>
              </div>
              <div>
                <div className="flex justify-between text-xs text-jarvis-text-secondary mb-1">
                  <span>Confidence</span>
                  <span className="text-jarvis-primary font-bold">{confidencePct(prediction.confidence)}%</span>
                </div>
                <div className="w-full bg-jarvis-primary/10 rounded-full h-2">
                  <motion.div
                    className="bg-jarvis-primary h-2 rounded-full"
                    initial={{ width: 0 }}
                    animate={{ width: `${confidencePct(prediction.confidence)}%` }}
                    transition={{ duration: 0.6 }}
                  />
                </div>
              </div>
              {prediction.direction_probabilities && (
                <div className="space-y-1 pt-1">
                  {Object.entries(prediction.direction_probabilities).map(([k, v]) => (
                    <div key={k} className="flex items-center gap-2">
                      <div className="text-xs w-10"
                        style={{ color: k === 'UP' ? '#4ade80' : k === 'DOWN' ? '#f87171' : '#a0c4e0' }}>
                        {k}
                      </div>
                      <div className="flex-1 bg-jarvis-primary/10 rounded-full h-1.5">
                        <div className="h-1.5 rounded-full"
                          style={{
                            width: `${Math.round((v as number) * 100)}%`,
                            background: k === 'UP' ? '#4ade80' : k === 'DOWN' ? '#f87171' : 'rgba(0,229,255,0.5)'
                          }} />
                      </div>
                      <div className="text-xs font-mono text-jarvis-text-secondary w-8 text-right">
                        {Math.round((v as number) * 100)}%
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : <div className="text-jarvis-text-secondary text-sm">Models not trained — click Train Now on Dashboard</div>}
        </Card>

        <Card title="Market Stats">
          {market ? (
            <div className="space-y-3">
              {[
                { label: 'IV Percentile', value: `${market.iv_percentile?.toFixed(1) ?? '—'}%`,
                  note: market.iv_percentile > 70 ? 'High — sell premium' : market.iv_percentile < 30 ? 'Low — buy options' : 'Normal' },
                { label: 'PCR Ratio', value: market.pcr?.toFixed(2) ?? '—',
                  note: (market.pcr ?? 1) > 1.2 ? 'Bearish sentiment' : (market.pcr ?? 1) < 0.7 ? 'Bullish sentiment' : 'Neutral' },
              ].map(item => (
                <div key={item.label} className="p-3 rounded-lg"
                  style={{ background: 'rgba(0,229,255,0.04)', border: '1px solid rgba(0,229,255,0.08)' }}>
                  <div className="text-xs text-jarvis-text-secondary uppercase tracking-widest">{item.label}</div>
                  <div className="text-2xl font-mono font-bold text-jarvis-accent mt-1">{item.value}</div>
                  <div className="text-xs text-jarvis-text-secondary/70 mt-0.5">{item.note}</div>
                </div>
              ))}
            </div>
          ) : <div className="text-jarvis-text-secondary text-sm">No data</div>}
        </Card>
      </div>
    </motion.div>
  );
}
