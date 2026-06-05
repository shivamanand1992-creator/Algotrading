import React, { useEffect, useState, useCallback, useMemo } from 'react';
import {
  ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, ReferenceArea,
} from 'recharts';
import { motion, AnimatePresence } from 'framer-motion';
import { marketApi } from '../../api/client';
import { Card } from '../ui/Card';
import { useWebSocket } from '../../hooks/useWebSocket';
import type { MarketData, MarketRegime, Prediction, OHLCVCandle, GlobalCue, NewsItem } from '../../types/api';

type Interval = 'FIVE_MINUTE' | 'FIFTEEN_MINUTE' | 'ONE_HOUR' | 'ONE_DAY';

interface VixCandle { timestamp: string; open: number; high: number; low: number; close: number; }
interface MergedCandle extends OHLCVCandle { displayTime: string; vix: number | null; }

const INTERVAL_OPTIONS: { label: string; value: Interval; days: number }[] = [
  { label: '1D', value: 'FIVE_MINUTE',    days: 1  },
  { label: '5D', value: 'FIFTEEN_MINUTE', days: 5  },
  { label: '1M', value: 'ONE_HOUR',       days: 30 },
];

function fmtTime(ts: string, interval: Interval): string {
  try {
    const d = new Date(ts);
    if (interval === 'ONE_DAY')  return d.toLocaleDateString('en-IN', { month: 'short', day: 'numeric' });
    if (interval === 'ONE_HOUR') return d.toLocaleDateString('en-IN', { month: 'short', day: 'numeric' }) + ' ' + d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false });
    return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false });
  } catch { return ts.slice(11, 16); }
}

function vixColor(v: number | null) {
  if (v === null) return '#a0c4e0';
  if (v > 20) return '#ef4444';
  if (v > 15) return '#f59e0b';
  return '#4ade80';
}
function vixStatus(v: number | null) {
  if (v === null) return '—';
  if (v > 20) return 'DANGER';
  if (v > 15) return 'ELEVATED';
  return 'CALM';
}

function DualTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload as MergedCandle;
  const vix = d?.vix;
  return (
    <div style={{
      background: 'rgba(0,5,20,0.97)', border: '1px solid rgba(0,229,255,0.25)',
      borderRadius: 12, padding: '12px 16px', minWidth: 200,
      boxShadow: '0 0 24px rgba(0,229,255,0.15)',
    }}>
      <p style={{ color: 'rgba(160,196,224,0.8)', fontSize: 11, marginBottom: 8, letterSpacing: 1 }}>
        {d?.displayTime ?? label}
      </p>
      <div style={{ fontSize: 11, fontFamily: 'monospace' }}>
        <div style={{ color: 'rgba(160,196,224,0.6)', marginBottom: 6, letterSpacing: 1 }}>NIFTY 50</div>
        {[
          ['O', d?.open?.toFixed(2), '#a0c4e0'],
          ['H', d?.high?.toFixed(2), '#4ade80'],
          ['L', d?.low?.toFixed(2),  '#f87171'],
          ['C', d?.close?.toFixed(2), '#00e5ff'],
          ['V', d?.volume?.toLocaleString(), '#00b0ff'],
        ].map(([k, v, c]) => (
          <div key={k as string} style={{ display: 'flex', justifyContent: 'space-between', gap: 16, marginBottom: 2 }}>
            <span style={{ color: 'rgba(160,196,224,0.5)' }}>{k}</span>
            <span style={{ color: c as string, fontWeight: 'bold' }}>{v}</span>
          </div>
        ))}
        {vix !== null && vix !== undefined && (
          <>
            <div style={{ borderTop: '1px solid rgba(0,229,255,0.1)', margin: '8px 0 6px', color: 'rgba(160,196,224,0.6)', letterSpacing: 1 }}>
              INDIA VIX
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16 }}>
              <span style={{ color: 'rgba(160,196,224,0.5)' }}>VIX</span>
              <span style={{ color: vixColor(vix), fontWeight: 'bold' }}>{(vix as number).toFixed(2)}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, marginTop: 2 }}>
              <span style={{ color: 'rgba(160,196,224,0.5)' }}>STATUS</span>
              <span style={{ color: vixColor(vix), fontWeight: 'bold', fontSize: 10 }}>{vixStatus(vix)}</span>
            </div>
          </>
        )}
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
  if (d === 'up'   || d === 'bullish') return '▲';
  if (d === 'down' || d === 'bearish') return '▼';
  return '→';
};
const confidencePct = (c: number) => c > 1 ? c : Math.round(c * 100);

// ─── Custom legend ────────────────────────────────────────────────────────────
function ChartLegend({ currentVix }: { currentVix: number | null }) {
  const vc = vixColor(currentVix);
  const vs = vixStatus(currentVix);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 20, padding: '8px 4px 0', fontSize: 11 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <div style={{ width: 24, height: 2, background: '#00e5ff', boxShadow: '0 0 6px #00e5ff' }} />
        <span style={{ color: 'rgba(0,229,255,0.8)', letterSpacing: 1 }}>NIFTY 50</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <div style={{ width: 24, height: 2, background: '#ff6b00', boxShadow: '0 0 6px #ff6b00' }} />
        <span style={{ color: 'rgba(255,107,0,0.8)', letterSpacing: 1 }}>INDIA VIX</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <div style={{ width: 16, height: 1, background: '#f59e0b', borderTop: '1px dashed #f59e0b' }} />
        <span style={{ color: 'rgba(245,158,11,0.7)', fontSize: 10 }}>15 CAUTION</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <div style={{ width: 16, height: 1, borderTop: '1px dashed #ef4444' }} />
        <span style={{ color: 'rgba(239,68,68,0.7)', fontSize: 10 }}>20 DANGER</span>
      </div>
      {currentVix !== null && (
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
          <AnimatePresence>
            {(currentVix ?? 0) > 20 && (
              <motion.div
                key="pulse"
                animate={{ opacity: [1, 0.3, 1] }}
                transition={{ repeat: Infinity, duration: 1.2 }}
                style={{ width: 6, height: 6, borderRadius: '50%', background: '#ef4444', boxShadow: '0 0 8px #ef4444' }}
              />
            )}
          </AnimatePresence>
          <span style={{ color: vc, fontWeight: 'bold', letterSpacing: 2, fontSize: 12 }}>
            VIX {currentVix.toFixed(2)}
          </span>
          <span style={{
            background: `${vc}22`, border: `1px solid ${vc}55`,
            color: vc, borderRadius: 4, padding: '1px 6px', fontSize: 9, letterSpacing: 1,
          }}>
            {vs}
          </span>
        </div>
      )}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────
export function MarketDataView() {
  const { marketData: wsMarket } = useWebSocket();
  const [market,     setMarket]     = useState<MarketData | null>(null);
  const [regime,     setRegime]     = useState<MarketRegime | null>(null);
  const [prediction, setPrediction] = useState<Prediction | null>(null);
  const [candles,    setCandles]    = useState<(OHLCVCandle & { displayTime: string })[]>([]);
  const [vixCandles, setVixCandles] = useState<VixCandle[]>([]);
  const [interval,   setSelectedInterval] = useState<Interval>('FIFTEEN_MINUTE');
  const [days,       setDays]       = useState(5);
  const [chartLoading, setChartLoading] = useState(true);
  const [loading,    setLoading]    = useState(true);
  const [globalCues, setGlobalCues] = useState<GlobalCue[]>([]);
  const [news, setNews]             = useState<NewsItem[]>([]);
  const [cuesLoading, setCuesLoading] = useState(true);

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
      console.error('Market analysis fetch error:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchCandles = useCallback(async (iv: Interval, d: number) => {
    setChartLoading(true);
    try {
      const [niftyRes, vixRes] = await Promise.all([
        marketApi.getOHLCV(iv, d),
        marketApi.getVIX(iv, d),
      ]);
      const data = (niftyRes.data ?? []).map(c => ({ ...c, displayTime: fmtTime(c.timestamp, iv) }));
      setCandles(data);
      setVixCandles(vixRes.data ?? []);
    } catch (err) {
      console.error('Chart data fetch error:', err);
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

  // Live tick → update last candle
  useEffect(() => {
    if (!wsMarket) return;
    setMarket(wsMarket);
    if (candles.length > 0 && interval === 'FIVE_MINUTE') {
      setCandles(prev => {
        const last = prev[prev.length - 1];
        if (!last) return prev;
        return [
          ...prev.slice(0, -1),
          { ...last, close: wsMarket.ltp, high: Math.max(last.high, wsMarket.ltp), low: Math.min(last.low, wsMarket.ltp) },
        ];
      });
    }
  }, [wsMarket, candles.length, interval]);

  // Merge Nifty + VIX by timestamp prefix
  const mergedData: MergedCandle[] = useMemo(() => {
    if (!candles.length) return [];
    const vixMap = new Map(vixCandles.map(v => [v.timestamp.slice(0, 16), v.close]));
    return candles.map(c => ({
      ...c,
      vix: vixMap.get(c.timestamp.slice(0, 16)) ?? null,
    }));
  }, [candles, vixCandles]);

  const firstClose = candles[0]?.close ?? 0;
  const lastClose  = candles[candles.length - 1]?.close ?? 0;
  const isUp       = lastClose >= firstClose;
  const niftyColor = isUp ? '#00e5ff' : '#f87171';

  const validLows  = mergedData.filter(c => c.low  > 0).map(c => c.low);
  const validHighs = mergedData.filter(c => c.high > 0).map(c => c.high);
  const minY = validLows.length  ? Math.floor(Math.min(...validLows)  / 50) * 50 : 0;
  const maxY = validHighs.length ? Math.ceil (Math.max(...validHighs) / 50) * 50 : 0;

  const vixValues    = mergedData.map(c => c.vix).filter(v => v !== null) as number[];
  const currentVix   = vixValues[vixValues.length - 1] ?? null;
  const minVix       = vixValues.length ? Math.max(8,  Math.floor(Math.min(...vixValues) - 1)) : 8;
  const maxVix       = vixValues.length ? Math.min(50, Math.ceil (Math.max(...vixValues) + 2)) : 30;

  const xTicks = mergedData.length > 20
    ? mergedData.filter((_, i) => i % Math.floor(mergedData.length / 8) === 0).map(c => c.displayTime)
    : mergedData.map(c => c.displayTime);

  // Global cues
  useEffect(() => {
    const fetch = async () => {
      setCuesLoading(true);
      try { const r = await marketApi.getGlobalCues(); setGlobalCues(r.data); }
      catch {} finally { setCuesLoading(false); }
    };
    fetch();
    const iv = setInterval(fetch, 300000);
    return () => clearInterval(iv);
  }, []);

  // News
  useEffect(() => {
    marketApi.getNews().then(r => setNews(r.data)).catch(() => {});
  }, []);

  const handleIntervalChange = (opt: typeof INTERVAL_OPTIONS[0]) => {
    setSelectedInterval(opt.value);
    setDays(opt.days);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-jarvis-primary animate-pulse text-xl tracking-widest">LOADING MARKET DATA…</div>
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
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-jarvis-primary tracking-widest uppercase">
          Market Analytics
        </h2>
        {market && (
          <motion.div className="flex items-center gap-3" key={market.ltp} initial={{ scale: 1.06 }} animate={{ scale: 1 }}>
            <span className="text-3xl font-black font-mono text-jarvis-primary tabular-nums" style={{ textShadow: '0 0 20px rgba(0,229,255,0.7)' }}>
              {market.ltp.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
            </span>
            <span className={`text-lg font-mono font-bold ${market.change >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {market.change >= 0 ? '+' : ''}{market.change.toFixed(2)} ({market.change_percentage.toFixed(2)}%)
            </span>
          </motion.div>
        )}
      </div>

      {/* ── Dual-axis Nifty + VIX Chart ────────────────────────────────── */}
      <div style={{
        borderRadius: 20,
        padding: '20px 20px 16px',
        background: 'linear-gradient(135deg, rgba(0,5,20,0.97) 0%, rgba(0,10,30,0.95) 100%)',
        border: '1px solid rgba(0,229,255,0.18)',
        boxShadow: '0 0 40px rgba(0,229,255,0.06), inset 0 0 40px rgba(0,229,255,0.02)',
        position: 'relative',
        overflow: 'hidden',
      }}>
        {/* Corner accent glows */}
        <div style={{ position: 'absolute', top: 0, left: 0, width: 120, height: 1, background: 'linear-gradient(90deg, rgba(0,229,255,0.7), transparent)' }} />
        <div style={{ position: 'absolute', top: 0, left: 0, width: 1, height: 120, background: 'linear-gradient(180deg, rgba(0,229,255,0.7), transparent)' }} />
        <div style={{ position: 'absolute', bottom: 0, right: 0, width: 120, height: 1, background: 'linear-gradient(270deg, rgba(0,229,255,0.4), transparent)' }} />
        <div style={{ position: 'absolute', bottom: 0, right: 0, width: 1, height: 120, background: 'linear-gradient(0deg, rgba(0,229,255,0.4), transparent)' }} />

        {/* Chart header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ fontSize: 13, fontWeight: 'bold', color: '#00e5ff', letterSpacing: 3, textTransform: 'uppercase', textShadow: '0 0 10px rgba(0,229,255,0.5)' }}>
              NIFTY 50
            </span>
            {mergedData.length > 0 && firstClose > 0 && (
              <span style={{
                fontSize: 11, fontFamily: 'monospace', fontWeight: 'bold',
                color: isUp ? '#4ade80' : '#f87171',
                background: isUp ? 'rgba(74,222,128,0.1)' : 'rgba(248,113,113,0.1)',
                border: `1px solid ${isUp ? 'rgba(74,222,128,0.3)' : 'rgba(248,113,113,0.3)'}`,
                borderRadius: 4, padding: '2px 8px',
              }}>
                {isUp ? '+' : ''}{((lastClose - firstClose) / firstClose * 100).toFixed(2)}%
              </span>
            )}
          </div>
          {/* Interval buttons */}
          <div style={{ display: 'flex', gap: 4 }}>
            {INTERVAL_OPTIONS.map(opt => (
              <button
                key={opt.value}
                onClick={() => handleIntervalChange(opt)}
                style={{
                  padding: '4px 12px', borderRadius: 6, fontSize: 11, fontWeight: 'bold',
                  cursor: 'pointer', transition: 'all 0.2s',
                  background: interval === opt.value ? 'rgba(0,229,255,0.15)' : 'transparent',
                  color: interval === opt.value ? '#00e5ff' : 'rgba(160,196,224,0.5)',
                  border: interval === opt.value ? '1px solid rgba(0,229,255,0.4)' : '1px solid transparent',
                  boxShadow: interval === opt.value ? '0 0 10px rgba(0,229,255,0.2)' : 'none',
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Chart body */}
        {chartLoading ? (
          <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <div style={{ color: '#00e5ff', fontSize: 13, letterSpacing: 3 }} className="animate-pulse">
              LOADING CANDLES…
            </div>
          </div>
        ) : mergedData.length === 0 ? (
          <div style={{ height: 300, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
            <div style={{ color: 'rgba(160,196,224,0.5)', fontSize: 13 }}>No chart data available</div>
            <div style={{ color: 'rgba(160,196,224,0.3)', fontSize: 11 }}>Market hours: 9:15–15:30 IST, Mon–Fri</div>
          </div>
        ) : (
          <>
            {/* Glow styles injected via style tag */}
            <style>{`
              .jarvis-chart .recharts-area-area {
                filter: drop-shadow(0 0 10px rgba(0,229,255,0.4));
              }
              .jarvis-chart .recharts-area-curve {
                filter: drop-shadow(0 0 4px rgba(0,229,255,0.9));
              }
              .jarvis-chart .recharts-line-curve {
                filter: drop-shadow(0 0 6px rgba(255,107,0,0.8));
              }
            `}</style>
            <div className="jarvis-chart">
              <ResponsiveContainer width="100%" height={300}>
                <ComposedChart data={mergedData} margin={{ top: 8, right: 60, left: 10, bottom: 0 }}>
                  <defs>
                    <linearGradient id="niftyFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%"   stopColor={niftyColor} stopOpacity={0.30} />
                      <stop offset="50%"  stopColor={niftyColor} stopOpacity={0.10} />
                      <stop offset="100%" stopColor={niftyColor} stopOpacity={0.01} />
                    </linearGradient>
                  </defs>

                  <CartesianGrid strokeDasharray="2 6" stroke="rgba(0,229,255,0.05)" />

                  <XAxis
                    dataKey="displayTime"
                    ticks={xTicks}
                    tick={{ fill: 'rgba(160,196,224,0.5)', fontSize: 9 }}
                    axisLine={{ stroke: 'rgba(0,229,255,0.12)' }}
                    tickLine={false}
                  />

                  {/* Left axis — Nifty price */}
                  <YAxis
                    yAxisId="nifty"
                    orientation="left"
                    domain={[minY, maxY]}
                    tick={{ fill: 'rgba(0,229,255,0.6)', fontSize: 9 }}
                    axisLine={{ stroke: 'rgba(0,229,255,0.12)' }}
                    tickLine={false}
                    tickFormatter={v => v.toLocaleString('en-IN')}
                    width={68}
                    label={{ value: 'NIFTY', angle: -90, position: 'insideLeft', fill: 'rgba(0,229,255,0.35)', fontSize: 9, letterSpacing: 2, dy: 25 }}
                  />

                  {/* Right axis — VIX */}
                  <YAxis
                    yAxisId="vix"
                    orientation="right"
                    domain={[minVix, maxVix]}
                    tick={{ fill: 'rgba(255,107,0,0.6)', fontSize: 9 }}
                    axisLine={{ stroke: 'rgba(255,107,0,0.12)' }}
                    tickLine={false}
                    tickFormatter={v => v.toFixed(1)}
                    width={40}
                    label={{ value: 'VIX', angle: 90, position: 'insideRight', fill: 'rgba(255,107,0,0.35)', fontSize: 9, letterSpacing: 2, dy: -20 }}
                  />

                  <Tooltip content={<DualTooltip />} />

                  {/* VIX danger zone backgrounds */}
                  <ReferenceArea yAxisId="vix" y1={20} y2={maxVix} fill="rgba(239,68,68,0.05)" />
                  <ReferenceArea yAxisId="vix" y1={15}  y2={20}    fill="rgba(245,158,11,0.04)" />

                  {/* VIX threshold lines */}
                  <ReferenceLine yAxisId="vix" y={20}
                    stroke="rgba(239,68,68,0.6)" strokeDasharray="5 3" strokeWidth={1}
                    label={{ value: '⚠ 20', position: 'insideTopRight', fill: 'rgba(239,68,68,0.7)', fontSize: 9 }}
                  />
                  <ReferenceLine yAxisId="vix" y={15}
                    stroke="rgba(245,158,11,0.5)" strokeDasharray="5 3" strokeWidth={1}
                    label={{ value: '15', position: 'insideTopRight', fill: 'rgba(245,158,11,0.6)', fontSize: 9 }}
                  />

                  {/* Previous close dashed line */}
                  {firstClose > 0 && (
                    <ReferenceLine yAxisId="nifty" y={firstClose}
                      stroke="rgba(160,196,224,0.2)" strokeDasharray="4 4"
                    />
                  )}

                  {/* Nifty area */}
                  <Area
                    yAxisId="nifty"
                    type="monotone"
                    dataKey="close"
                    stroke={niftyColor}
                    strokeWidth={2.5}
                    fill="url(#niftyFill)"
                    dot={false}
                    activeDot={{ r: 5, fill: niftyColor, strokeWidth: 0, style: { filter: `drop-shadow(0 0 6px ${niftyColor})` } }}
                    isAnimationActive={false}
                  />

                  {/* India VIX line */}
                  <Line
                    yAxisId="vix"
                    type="monotone"
                    dataKey="vix"
                    stroke="#ff6b00"
                    strokeWidth={1.8}
                    dot={false}
                    activeDot={{ r: 4, fill: '#ff6b00', strokeWidth: 0, style: { filter: 'drop-shadow(0 0 6px #ff6b00)' } }}
                    isAnimationActive={false}
                    connectNulls
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>

            {/* Legend */}
            <ChartLegend currentVix={currentVix} />
          </>
        )}
      </div>

      {/* ── Analysis cards ─────────────────────────────────────────────── */}
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
                      <div className="text-xs w-10" style={{ color: k === 'UP' ? '#4ade80' : k === 'DOWN' ? '#f87171' : '#a0c4e0' }}>{k}</div>
                      <div className="flex-1 bg-jarvis-primary/10 rounded-full h-1.5">
                        <div className="h-1.5 rounded-full" style={{
                          width: `${Math.round((v as number) * 100)}%`,
                          background: k === 'UP' ? '#4ade80' : k === 'DOWN' ? '#f87171' : 'rgba(0,229,255,0.5)',
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
              {/* VIX live reading */}
              {currentVix !== null && (
                <div className="p-3 rounded-lg" style={{ background: `${vixColor(currentVix)}0d`, border: `1px solid ${vixColor(currentVix)}33` }}>
                  <div className="text-xs text-jarvis-text-secondary uppercase tracking-widest">India VIX</div>
                  <div className="flex items-end gap-3 mt-1">
                    <span className="text-2xl font-mono font-bold" style={{ color: vixColor(currentVix) }}>
                      {currentVix.toFixed(2)}
                    </span>
                    <span className="text-xs mb-1 font-bold tracking-widest" style={{ color: vixColor(currentVix) }}>
                      {vixStatus(currentVix)}
                    </span>
                  </div>
                  <div className="text-xs mt-1" style={{ color: 'rgba(160,196,224,0.5)' }}>
                    {(currentVix ?? 0) > 20 ? 'High fear — avoid naked longs' :
                     (currentVix ?? 0) > 15 ? 'Caution — reduce position size' :
                     'Normal — all strategies active'}
                  </div>
                </div>
              )}
              {[
                { label: 'IV Percentile', value: `${market.iv_percentile?.toFixed(1) ?? '—'}%`,
                  note: (market.iv_percentile ?? 50) > 70 ? 'High — sell premium' : (market.iv_percentile ?? 50) < 30 ? 'Low — buy options' : 'Normal' },
                { label: 'PCR Ratio', value: market.pcr?.toFixed(2) ?? '—',
                  note: (market.pcr ?? 1) > 1.2 ? 'Bearish sentiment' : (market.pcr ?? 1) < 0.7 ? 'Bullish sentiment' : 'Neutral' },
              ].map(item => (
                <div key={item.label} className="p-3 rounded-lg" style={{ background: 'rgba(0,229,255,0.04)', border: '1px solid rgba(0,229,255,0.08)' }}>
                  <div className="text-xs text-jarvis-text-secondary uppercase tracking-widest">{item.label}</div>
                  <div className="text-2xl font-mono font-bold text-jarvis-accent mt-1">{item.value}</div>
                  <div className="text-xs text-jarvis-text-secondary/70 mt-0.5">{item.note}</div>
                </div>
              ))}
            </div>
          ) : <div className="text-jarvis-text-secondary text-sm">No data</div>}
        </Card>

      </div>

      {/* ── Global Cues ─────────────────────────────────────────────── */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <span className="text-[10px] font-bold tracking-[0.25em] text-jarvis-primary/50 uppercase">Global Market Cues</span>
          <div className="flex-1 h-px bg-jarvis-primary/10" />
        </div>
        {cuesLoading ? (
          <div className="grid grid-cols-4 gap-3">
            {[...Array(8)].map((_, i) => (
              <div key={i} className="h-16 rounded-xl animate-pulse" style={{ background: 'rgba(0,229,255,0.04)' }} />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-4 gap-3">
            {globalCues.map(cue => {
              const up = (cue.change_pct ?? 0) >= 0;
              return (
                <motion.div key={cue.symbol}
                  className="rounded-xl px-4 py-3"
                  style={{ background: 'rgba(0,229,255,0.03)', border: `1px solid ${cue.ltp === null ? 'rgba(0,229,255,0.06)' : up ? 'rgba(74,222,128,0.12)' : 'rgba(248,113,113,0.12)'}` }}
                  whileHover={{ scale: 1.02 }}
                >
                  <div className="flex justify-between items-start mb-1">
                    <span className="text-[10px] font-bold text-jarvis-text-secondary uppercase tracking-wider">{cue.name}</span>
                    <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${cue.type === 'index' ? 'bg-blue-400/10 text-blue-400' : cue.type === 'commodity' ? 'bg-amber-400/10 text-amber-400' : 'bg-purple-400/10 text-purple-400'}`}>
                      {cue.type.toUpperCase()}
                    </span>
                  </div>
                  <span className="text-sm font-mono font-bold text-jarvis-primary tabular-nums">
                    {cue.ltp !== null ? cue.ltp.toLocaleString('en-IN', { maximumFractionDigits: 2 }) : '—'}
                  </span>
                  {cue.change_pct !== null && (
                    <span className={`ml-2 text-xs font-mono font-bold ${up ? 'text-green-400' : 'text-red-400'}`}>
                      {up ? '+' : ''}{cue.change_pct.toFixed(2)}%
                    </span>
                  )}
                </motion.div>
              );
            })}
          </div>
        )}
      </div>

      {/* ── News ───────────────────────────────────────────────────── */}
      {news.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <span className="text-[10px] font-bold tracking-[0.25em] text-jarvis-primary/50 uppercase">Market Intelligence</span>
            <div className="flex-1 h-px bg-jarvis-primary/10" />
            <span className="text-[9px] text-jarvis-text-secondary/40">ET Markets</span>
          </div>
          <div className="rounded-2xl p-4" style={{ background: 'rgba(0,8,24,0.97)', border: '1px solid rgba(0,229,255,0.08)' }}>
            <div className="divide-y divide-white/5">
              {news.slice(0, 8).map((item, i) => (
                <motion.a key={i} href={item.link || '#'} target="_blank" rel="noopener noreferrer"
                  className="flex items-start gap-3 py-2.5 group cursor-pointer"
                  initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.04 }}
                >
                  <span className="text-jarvis-primary/30 text-xs font-mono mt-0.5 flex-shrink-0 w-4">{i + 1}</span>
                  <span className="text-xs text-jarvis-text-secondary group-hover:text-jarvis-primary transition-colors leading-relaxed flex-1">
                    {item.title}
                  </span>
                  {item.published && (
                    <span className="text-[10px] text-jarvis-text-secondary/40 flex-shrink-0 whitespace-nowrap ml-2">{item.published.slice(0, 20)}</span>
                  )}
                </motion.a>
              ))}
            </div>
          </div>
        </div>
      )}
    </motion.div>
  );
}
