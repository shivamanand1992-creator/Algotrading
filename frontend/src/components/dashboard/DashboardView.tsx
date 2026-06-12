import React, { useEffect, useState, useRef, useCallback } from 'react';
import { motion, type Variants } from 'framer-motion';
import {
  AreaChart, Area, ResponsiveContainer,
  XAxis, YAxis, Tooltip,
} from 'recharts';
import { useWebSocket } from '../../hooks/useWebSocket';
import { marketApi, niftyBeesApi, stocksApi, systemApi } from '../../api/client';
import { formatCurrency } from '../../utils/formatters';
import type { MarketData, GlobalCue, NewsItem, NiftyBeesStatus, SwingPosition } from '../../types/api';
import { OrderFlowVectors } from '../ui/OrderFlowVectors';
import { ExecutionLogFeed, type LogEntry } from '../ui/ExecutionLogFeed';
import { useTilt } from '../../hooks/useTilt';
import { VaayuGlobe } from '../ui/VaayuGlobe';

const staggerContainer: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.07 } },
};
const staggerItem: Variants = {
  hidden: { opacity: 0, y: 20 },
  show:   { opacity: 1, y: 0, transition: { duration: 0.4, ease: 'easeOut' } },
};

// ── HUD Stat panel ────────────────────────────────────────────────────────────
function HudStat({
  label, value, color = '#00e5ff', sublabel, pulse,
}: {
  label: string; value: string; color?: string; sublabel?: string; pulse?: boolean;
}) {
  return (
    <motion.div
      style={{
        padding: '10px 14px',
        background: 'rgba(0,229,255,0.025)',
        border: '1px solid rgba(0,229,255,0.07)',
        borderLeft: `2px solid ${color}`,
        borderRadius: '0 8px 8px 0',
        position: 'relative',
        overflow: 'hidden',
      }}
      animate={pulse ? { opacity: [1, 0.6, 1] } : {}}
      transition={pulse ? { duration: 2, repeat: Infinity } : {}}
    >
      <div style={{
        position: 'absolute', inset: 0,
        background: `linear-gradient(90deg, ${color}08, transparent 60%)`,
      }} />
      <div style={{
        fontSize: 9, color: 'rgba(160,196,224,0.45)',
        letterSpacing: '0.15em', textTransform: 'uppercase',
        marginBottom: 5, fontFamily: 'monospace',
      }}>
        {label}
      </div>
      <div style={{
        fontSize: 20, fontFamily: "'Courier New', monospace",
        fontWeight: 900, color, lineHeight: 1,
      }}>
        {value}
      </div>
      {sublabel && (
        <div style={{ fontSize: 9.5, color: 'rgba(160,196,224,0.4)', marginTop: 4, fontFamily: 'monospace' }}>
          {sublabel}
        </div>
      )}
    </motion.div>
  );
}

function CueCard({ cue }: { cue: GlobalCue }) {
  const up   = (cue.change_pct ?? 0) >= 0;
  const tilt = useTilt(6);
  return (
    <div
      ref={tilt.ref}
      onMouseMove={tilt.onMouseMove}
      onMouseLeave={tilt.onMouseLeave}
      className="scan-wipe tilt-card rounded-xl px-4 py-3 flex flex-col justify-between"
      style={{
        background: 'rgba(0,229,255,0.03)',
        border: `1px solid ${cue.ltp === null ? 'rgba(0,229,255,0.06)' : up ? 'rgba(74,222,128,0.12)' : 'rgba(248,113,113,0.12)'}`,
      }}
    >
      <div className="flex justify-between items-start">
        <span className="text-[10px] font-bold text-jarvis-text-secondary uppercase tracking-wider">{cue.name}</span>
        <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${cue.type === 'index' ? 'bg-blue-400/10 text-blue-400' : cue.type === 'commodity' ? 'bg-amber-400/10 text-amber-400' : 'bg-purple-400/10 text-purple-400'}`}>
          {cue.type.toUpperCase()}
        </span>
      </div>
      <div className="mt-1">
        <span className="text-sm font-mono font-bold text-jarvis-primary tabular-nums">
          {cue.ltp !== null ? cue.ltp.toLocaleString('en-IN', { maximumFractionDigits: 2 }) : '—'}
        </span>
        {cue.change_pct !== null && (
          <span className={`ml-2 text-xs font-mono font-bold ${up ? 'text-green-400' : 'text-red-400'}`}>
            {up ? '+' : ''}{cue.change_pct.toFixed(2)}%
          </span>
        )}
      </div>
    </div>
  );
}

interface Balance { available_cash: number; net: number; used_margin: number; error?: string; source?: string; }

interface IntradayCandle {
  timestamp: string;
  time: string;
  open: number; high: number; low: number; close: number;
  volume?: number;
}

export function DashboardView() {
  const { connected, marketData: wsMarketData } = useWebSocket();
  const [marketData, setMarketData]         = useState<MarketData | null>(null);
  const [intradayCandles, setIntradayCandles] = useState<IntradayCandle[]>([]);
  const [globalCues, setGlobalCues]         = useState<GlobalCue[]>([]);
  const [news, setNews]                     = useState<NewsItem[]>([]);
  const [nbStatus, setNbStatus]             = useState<NiftyBeesStatus | null>(null);
  const [swingPositions, setSwingPositions] = useState<SwingPosition[]>([]);
  const [balance, setBalance]               = useState<Balance | null>(null);
  const [cuesLoading, setCuesLoading]       = useState(true);
  const [newsLoading, setNewsLoading]       = useState(true);
  const [syncing, setSyncing]               = useState(false);
  const [syncMsg, setSyncMsg]               = useState('');
  const [lastUpdated, setLastUpdated]       = useState<Date | null>(null);
  const [logEntries, setLogEntries]         = useState<LogEntry[]>([]);
  const [ltpFlashDir, setLtpFlashDir]       = useState<'up' | 'down' | null>(null);
  const prevLtp  = useRef<number>(0);
  const logCounter = useRef<number>(0);

  // ── Market data (30s) ────────────────────────────────────────────
  const fetchMarket = useCallback(async () => {
    try {
      const res = await marketApi.getCurrent();
      setMarketData(res.data);
      setLastUpdated(new Date());
    } catch {}
  }, []);

  useEffect(() => {
    fetchMarket();
    const iv = setInterval(fetchMarket, 30000);
    return () => clearInterval(iv);
  }, [fetchMarket]);

  // ── 15-min intraday chart ────────────────────────────────────────
  useEffect(() => {
    const f = async () => {
      try {
        const res = await marketApi.getOHLCV('FIFTEEN_MINUTE', 1);
        const candles: Array<{timestamp: string; open: number; high: number; low: number; close: number; volume?: number}> = res.data ?? [];
        if (!candles.length) return;
        setIntradayCandles(candles.map(c => {
          const d = new Date(c.timestamp);
          const time = d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false });
          return { ...c, time };
        }));
      } catch {}
    };
    f();
    const iv = setInterval(f, 300000);
    return () => clearInterval(iv);
  }, []);

  // ── NiftyBees (15s) ──────────────────────────────────────────────
  useEffect(() => {
    const f = async () => {
      try { const r = await niftyBeesApi.getStatus(); setNbStatus(r.data); } catch {}
    };
    f();
    const iv = setInterval(f, 15000);
    return () => clearInterval(iv);
  }, []);

  // ── Swing positions (30s) ────────────────────────────────────────
  useEffect(() => {
    const f = async () => {
      try {
        const r = await stocksApi.getPositions();
        setSwingPositions(Array.isArray(r.data) ? r.data : []);
      } catch {}
    };
    f();
    const iv = setInterval(f, 30000);
    return () => clearInterval(iv);
  }, []);

  // ── Balance (2 min) ──────────────────────────────────────────────
  useEffect(() => {
    const f = async () => {
      try { const r = await systemApi.getBalance(); setBalance(r.data); } catch {}
    };
    f();
    const iv = setInterval(f, 120000);
    return () => clearInterval(iv);
  }, []);

  // ── Global cues (5 min) ──────────────────────────────────────────
  useEffect(() => {
    const f = async () => {
      setCuesLoading(true);
      try { const r = await marketApi.getGlobalCues(); setGlobalCues(r.data); }
      catch {} finally { setCuesLoading(false); }
    };
    f();
    const iv = setInterval(f, 300000);
    return () => clearInterval(iv);
  }, []);

  // ── News (once) ──────────────────────────────────────────────────
  useEffect(() => {
    setNewsLoading(true);
    marketApi.getNews()
      .then(r => setNews(r.data))
      .catch(() => {})
      .finally(() => setNewsLoading(false));
  }, []);

  // ── WS tick → market data + log ─────────────────────────────────
  useEffect(() => {
    if (wsMarketData) {
      const prev = prevLtp.current;
      if (prev > 0 && wsMarketData.ltp !== prev) {
        const dir = wsMarketData.ltp > prev ? 'up' : 'down';
        setLtpFlashDir(dir);
        setTimeout(() => setLtpFlashDir(null), 650);
        const t = new Date().toTimeString().slice(0, 8);
        setLogEntries(p => [
          ...p.slice(-19),
          {
            id: ++logCounter.current, time: t, type: 'info',
            message: `NIFTY50 ${dir === 'up' ? '▲' : '▼'} ${wsMarketData.ltp.toLocaleString('en-IN', { maximumFractionDigits: 2 })} (${wsMarketData.change_percentage >= 0 ? '+' : ''}${wsMarketData.change_percentage.toFixed(2)}%)`,
          },
        ]);
      }
      setMarketData(wsMarketData);
      setLastUpdated(new Date());
    }
  }, [wsMarketData]);

  // ── Sync from broker ─────────────────────────────────────────────
  const handleSync = async () => {
    setSyncing(true);
    setSyncMsg('');
    try {
      const r = await systemApi.syncAll();
      setSyncMsg(r.data.success ? '✓ Sync complete' : `⚠ ${r.data.errors?.[0] ?? 'Partial sync'}`);
      const [nbRes, swRes, balRes] = await Promise.allSettled([
        niftyBeesApi.getStatus(), stocksApi.getPositions(), systemApi.getBalance(),
      ]);
      if (nbRes.status === 'fulfilled')  setNbStatus(nbRes.value.data);
      if (swRes.status === 'fulfilled')  setSwingPositions(Array.isArray(swRes.value.data) ? swRes.value.data : []);
      if (balRes.status === 'fulfilled') setBalance(balRes.value.data);
    } catch { setSyncMsg('✗ Sync failed'); }
    finally { setSyncing(false); setTimeout(() => setSyncMsg(''), 4000); }
  };

  const ltp       = marketData?.ltp ?? 0;
  const change    = marketData?.change ?? 0;
  const changePct = marketData?.change_percentage ?? 0;
  const isUp      = change >= 0;
  if (ltp > 0 && ltp !== prevLtp.current) prevLtp.current = ltp;

  const nb          = nbStatus?.position ?? null;
  const nbConf      = nbStatus?.config;
  const nbTarget    = nbConf?.target_gain_pct ?? 5;
  const nbPnlPct    = nb?.pnl_pct ?? 0;
  const nbProgress  = Math.min((nbPnlPct / nbTarget) * 100, 100);

  const openSwings    = swingPositions.filter(p => p.status === 'open');
  const swingDeployed = openSwings.reduce((s, p) => s + (p.entry_price * p.qty), 0);
  const swingPnl      = openSwings.reduce((s, p) => s + (p.unrealized_pnl ?? 0), 0);
  const swingPnlPct   = openSwings.length > 0
    ? openSwings.reduce((s, p) => s + (p.pnl_pct ?? 0), 0) / openSwings.length : 0;

  const balDataAvail = balance !== null && balance.source === 'live' && (balance.available_cash > 0 || balance.net > 0);
  const balLow = balDataAvail && nbConf && balance!.available_cash < nbConf.capital_amount * 1.1;

  // Intraday chart Y-domain
  const closes = intradayCandles.map(c => c.close).filter(Boolean);
  const chartMin = closes.length ? Math.min(...closes) * 0.9995 : 'auto';
  const chartMax = closes.length ? Math.max(...closes) * 1.0005 : 'auto';

  return (
    <motion.div className="space-y-5" variants={staggerContainer} initial="hidden" animate="show">

      {/* ── STATUS BAR ─────────────────────────────────────────────── */}
      <motion.div variants={staggerItem} className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <motion.div
            className={`w-2.5 h-2.5 rounded-full ${connected ? 'bg-green-400' : 'bg-red-500'}`}
            animate={connected ? { scale: [1, 1.4, 1], opacity: [1, 0.5, 1] } : {}}
            transition={{ duration: 1.5, repeat: Infinity }}
          />
          <span className="text-[10px] font-bold tracking-widest uppercase text-jarvis-text-secondary">
            {connected ? 'Live Stream' : 'Disconnected'}
          </span>
          {lastUpdated && (
            <span className="text-[9px] text-jarvis-text-secondary/40">
              Updated {lastUpdated.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {syncMsg && (
            <span className={`text-[10px] font-bold px-2 py-1 rounded ${syncMsg.startsWith('✓') ? 'text-green-400' : 'text-yellow-400'}`}>
              {syncMsg}
            </span>
          )}
          <button
            onClick={handleSync}
            disabled={syncing}
            className="px-3 py-1.5 rounded-lg text-[10px] font-bold uppercase tracking-widest transition-all flex items-center gap-1.5"
            style={{ background: 'rgba(0,229,255,0.08)', border: '1px solid rgba(0,229,255,0.3)', color: '#00e5ff' }}
          >
            <motion.span animate={syncing ? { rotate: 360 } : {}} transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}>
              ↺
            </motion.span>
            {syncing ? 'Syncing…' : 'Sync Broker'}
          </button>
        </div>
      </motion.div>

      {/* ── GLOBE COMMAND CENTER ───────────────────────────────────── */}
      <motion.div variants={staggerItem}>
        <div
          className={`relative overflow-hidden rounded-2xl ${ltpFlashDir === 'up' ? 'flash-up' : ltpFlashDir === 'down' ? 'flash-down' : ''}`}
          style={{
            background: 'linear-gradient(160deg, rgba(0,5,18,0.92) 0%, rgba(0,12,35,0.92) 100%)',
            border: '1px solid rgba(0,229,255,0.1)',
            backdropFilter: 'blur(10px)',
          }}
        >
          <div className="scan-line" />
          <OrderFlowVectors count={8} buyBias={isUp ? 0.65 : 0.35} />

          {/* 3-column layout: left HUD | globe | right HUD */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '180px 1fr 180px',
              gap: 0,
              position: 'relative',
              zIndex: 2,
              minHeight: 480,
            }}
          >
            {/* Left HUD panel */}
            <div style={{
              display: 'flex', flexDirection: 'column',
              justifyContent: 'center', gap: 10,
              padding: '28px 16px 28px 20px',
              borderRight: '1px solid rgba(0,229,255,0.06)',
            }}>
              <HudStat
                label="PCR"
                value={marketData?.pcr ? marketData.pcr.toFixed(2) : '—'}
                color="#a78bfa"
                sublabel={marketData?.pcr ? (marketData.pcr >= 1.2 ? 'BEARISH' : marketData.pcr <= 0.8 ? 'BULLISH' : 'NEUTRAL') : ''}
              />
              <HudStat
                label="IV Percentile"
                value={marketData?.iv_percentile ? `${marketData.iv_percentile.toFixed(0)}%` : '—'}
                color="#fbbf24"
                sublabel={marketData?.iv_percentile ? (marketData.iv_percentile >= 70 ? 'HIGH VOL' : marketData.iv_percentile <= 30 ? 'LOW VOL' : 'NORMAL') : ''}
              />
              <HudStat
                label="Change"
                value={change !== 0 ? `${change >= 0 ? '+' : ''}${change.toFixed(1)}` : '—'}
                color={isUp ? '#4ade80' : '#f87171'}
                sublabel={changePct !== 0 ? `${changePct >= 0 ? '+' : ''}${changePct.toFixed(2)}%` : ''}
                pulse={Math.abs(changePct) > 1.5}
              />
              <HudStat
                label="Volume"
                value={marketData?.volume ? `${(marketData.volume / 1_000_000).toFixed(1)}M` : '—'}
                color="#22d3ee"
              />
            </div>

            {/* Center: Globe */}
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '16px 0',
            }}>
              <VaayuGlobe
                ltp={ltp}
                change={change}
                changePct={changePct}
                isUp={isUp}
                size={460}
              />
            </div>

            {/* Right HUD panel */}
            <div style={{
              display: 'flex', flexDirection: 'column',
              justifyContent: 'center', gap: 10,
              padding: '28px 20px 28px 16px',
              borderLeft: '1px solid rgba(0,229,255,0.06)',
            }}>
              <HudStat
                label="Open"
                value={marketData?.open ? marketData.open.toLocaleString('en-IN', { maximumFractionDigits: 0 }) : '—'}
                color="#00e5ff"
              />
              <HudStat
                label="Day High"
                value={marketData?.high ? marketData.high.toLocaleString('en-IN', { maximumFractionDigits: 0 }) : '—'}
                color="#4ade80"
              />
              <HudStat
                label="Day Low"
                value={marketData?.low ? marketData.low.toLocaleString('en-IN', { maximumFractionDigits: 0 }) : '—'}
                color="#f87171"
              />
              <HudStat
                label="Spread"
                value={
                  marketData?.high && marketData?.low
                    ? (marketData.high - marketData.low).toLocaleString('en-IN', { maximumFractionDigits: 0 })
                    : '—'
                }
                color="#a0c4e0"
                sublabel="Day Range"
              />
            </div>
          </div>

          {/* Intraday chart */}
          <div style={{
            borderTop: '1px solid rgba(0,229,255,0.07)',
            padding: '12px 20px 16px',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
              <span style={{ fontSize: 9, color: 'rgba(0,229,255,0.4)', fontFamily: 'monospace', letterSpacing: '0.25em', textTransform: 'uppercase' }}>
                Nifty 50 · Today · 15 min
              </span>
              <div style={{ flex: 1, height: 1, background: 'rgba(0,229,255,0.06)' }} />
              <span style={{ fontSize: 9, color: 'rgba(160,196,224,0.3)', fontFamily: 'monospace' }}>
                {intradayCandles.length > 0 ? `${intradayCandles[0].time} – ${intradayCandles[intradayCandles.length - 1].time}` : 'Loading...'}
              </span>
            </div>
            {intradayCandles.length > 2 ? (
              <ResponsiveContainer width="100%" height={130}>
                <AreaChart data={intradayCandles} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="intradayGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%"   stopColor={isUp ? '#4ade80' : '#f87171'} stopOpacity={0.25} />
                      <stop offset="100%" stopColor={isUp ? '#4ade80' : '#f87171'} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis
                    dataKey="time"
                    tick={{ fontSize: 9, fill: 'rgba(160,196,224,0.35)', fontFamily: 'monospace' }}
                    tickLine={false}
                    axisLine={false}
                    interval="preserveStartEnd"
                  />
                  <YAxis domain={[chartMin, chartMax]} hide />
                  <Tooltip
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const d = payload[0]?.payload as IntradayCandle;
                      return (
                        <div style={{
                          background: 'rgba(0,5,20,0.95)',
                          border: '1px solid rgba(0,229,255,0.2)',
                          borderRadius: 6, padding: '6px 10px',
                          fontSize: 10, fontFamily: 'monospace',
                        }}>
                          <div style={{ color: '#a0c4e0', marginBottom: 3 }}>{d?.time}</div>
                          <div style={{ color: '#00e5ff' }}>C: {d?.close?.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</div>
                          <div style={{ color: '#4ade80' }}>H: {d?.high?.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</div>
                          <div style={{ color: '#f87171' }}>L: {d?.low?.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</div>
                        </div>
                      );
                    }}
                  />
                  <Area
                    type="monotone" dataKey="close"
                    stroke={isUp ? '#4ade80' : '#f87171'} strokeWidth={1.5}
                    fill="url(#intradayGrad)"
                    dot={false} isAnimationActive={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div style={{ height: 130, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <span style={{ fontSize: 10, color: 'rgba(160,196,224,0.3)', fontFamily: 'monospace', letterSpacing: '0.2em' }}>
                  {intradayCandles.length === 0 ? 'AWAITING MARKET DATA...' : 'NOT ENOUGH DATA'}
                </span>
              </div>
            )}
          </div>
        </div>
      </motion.div>

      {/* ── BALANCE STRIP ─────────────────────────────────────────── */}
      <motion.div variants={staggerItem}>
        <div
          className="rounded-xl px-5 py-3 flex items-center justify-between"
          style={{
            background: balLow ? 'rgba(248,113,113,0.05)' : 'rgba(0,229,255,0.03)',
            border: `1px solid ${balLow ? 'rgba(248,113,113,0.25)' : 'rgba(0,229,255,0.1)'}`,
          }}
        >
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-bold text-jarvis-text-secondary uppercase tracking-widest">
              💰 Angel One Balance
            </span>
            {balLow && (
              <motion.span
                className="text-[10px] font-bold text-red-400 px-2 py-0.5 rounded-full"
                style={{ background: 'rgba(248,113,113,0.1)', border: '1px solid rgba(248,113,113,0.3)' }}
                animate={{ opacity: [1, 0.5, 1] }}
                transition={{ duration: 1.5, repeat: Infinity }}
              >
                ⚠ LOW BALANCE
              </motion.span>
            )}
          </div>
          <div className="flex items-center gap-6">
            <div className="text-right">
              <div className="text-[9px] text-jarvis-text-secondary/50 uppercase">Available Cash</div>
              <div className={`text-base font-mono font-bold ${balLow ? 'text-red-400' : balDataAvail ? 'text-green-400' : 'text-jarvis-text-secondary'}`}>
                {balDataAvail ? `₹${balance!.available_cash.toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—'}
              </div>
            </div>
            <div className="text-right">
              <div className="text-[9px] text-jarvis-text-secondary/50 uppercase">Net Value</div>
              <div className="text-base font-mono font-bold text-jarvis-primary">
                {balDataAvail ? `₹${balance!.net.toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—'}
              </div>
            </div>
            <div className="text-right">
              <div className="text-[9px] text-jarvis-text-secondary/50 uppercase">Next DCA Chunk</div>
              <div className="text-base font-mono font-bold text-jarvis-accent">
                {nbConf ? `₹${nbConf.capital_amount.toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—'}
              </div>
            </div>
            {balDataAvail && nbConf && (
              <div className="text-right">
                <div className="text-[9px] text-jarvis-text-secondary/50 uppercase">Chunks Available</div>
                <div className={`text-base font-mono font-bold ${balLow ? 'text-red-400' : 'text-jarvis-secondary'}`}>
                  {Math.floor(balance!.available_cash / nbConf.capital_amount)}×
                </div>
              </div>
            )}
          </div>
        </div>
      </motion.div>

      {/* ── GLOBAL CUES ───────────────────────────────────────────── */}
      <motion.div variants={staggerItem}>
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
          <div className="grid grid-cols-4 gap-3 reveal-grid">
            {globalCues.map(cue => (
              <CueCard key={cue.symbol} cue={cue} />
            ))}
          </div>
        )}
      </motion.div>

      {/* ── NIFTYBEES + SWING ─────────────────────────────────────── */}
      <motion.div variants={staggerItem} className="grid grid-cols-2 gap-5">

        {/* NiftyBees Card */}
        <div
          className="rounded-2xl p-5 relative overflow-hidden"
          style={{
            background: 'linear-gradient(135deg, rgba(0,8,24,0.97) 0%, rgba(0,30,50,0.97) 100%)',
            border: nb?.active ? '1px solid rgba(0,229,255,0.3)' : '1px solid rgba(0,229,255,0.1)',
          }}
        >
          {nb?.active && <div className="scan-line" />}
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <span className="text-base">🐝</span>
              <span className="text-xs font-bold tracking-[0.2em] text-jarvis-primary uppercase">NiftyBees ETF</span>
            </div>
            <div className="flex items-center gap-2">
              {nb?.mode && (
                <span className="text-[9px] font-bold px-1.5 py-0.5 rounded" style={{ background: nb.mode === 'live' ? 'rgba(255,23,68,0.15)' : 'rgba(0,229,255,0.1)', color: nb.mode === 'live' ? '#ff1744' : '#00e5ff' }}>
                  {nb.mode.toUpperCase()}
                </span>
              )}
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full" style={{ background: nbConf?.enabled ? 'rgba(0,229,255,0.1)' : 'rgba(255,100,100,0.1)', color: nbConf?.enabled ? '#00e5ff' : '#f87171' }}>
                {nbConf?.enabled ? 'AUTOPILOT ON' : 'DISABLED'}
              </span>
            </div>
          </div>

          {nb?.active ? (
            <div className="space-y-3">
              <div className="flex justify-between items-start">
                <div>
                  <div className="text-[10px] text-jarvis-text-secondary uppercase tracking-wider">Holdings</div>
                  <div className="text-3xl font-black font-mono text-jarvis-primary tabular-nums mt-0.5">
                    {nb.total_qty} <span className="text-base font-normal text-jarvis-text-secondary">units</span>
                  </div>
                  <div className="text-xs text-jarvis-text-secondary mt-0.5">
                    Avg ₹{nb.avg_entry_price?.toFixed(2)} · {nb.buys?.length ?? 1} DCA buy{(nb.buys?.length ?? 1) !== 1 ? 's' : ''}
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-[10px] text-jarvis-text-secondary uppercase tracking-wider">P&L</div>
                  <div className={`text-2xl font-mono font-bold tabular-nums mt-0.5 ${nbPnlPct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {nbPnlPct >= 0 ? '+' : ''}{nbPnlPct.toFixed(2)}%
                  </div>
                  <div className={`text-xs font-mono ${(nb.unrealized_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {(nb.unrealized_pnl ?? 0) >= 0 ? '+' : ''}{formatCurrency(nb.unrealized_pnl ?? 0)}
                  </div>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-2">
                {[
                  { label: 'Deployed', value: formatCurrency(nb.total_invested ?? 0), color: 'text-yellow-400' },
                  { label: 'Curr Value', value: formatCurrency((nb.total_qty ?? 0) * (nb.current_price ?? nb.avg_entry_price ?? 0)), color: 'text-jarvis-primary' },
                  { label: 'CMP', value: `₹${(nb.current_price ?? 0).toFixed(2)}`, color: 'text-jarvis-accent' },
                ].map(item => (
                  <div key={item.label} className="rounded-lg px-2 py-2 text-center" style={{ background: 'rgba(0,229,255,0.04)', border: '1px solid rgba(0,229,255,0.07)' }}>
                    <div className="text-[9px] text-jarvis-text-secondary uppercase">{item.label}</div>
                    <div className={`text-xs font-mono font-bold mt-0.5 ${item.color}`}>{item.value}</div>
                  </div>
                ))}
              </div>
              <div>
                <div className="flex justify-between text-[10px] text-jarvis-text-secondary mb-1.5">
                  <span>Progress toward {nbTarget}% sell target</span>
                  <span className="font-mono">{nbPnlPct.toFixed(2)}% / {nbTarget}%</span>
                </div>
                <div className="h-2 rounded-full" style={{ background: 'rgba(0,229,255,0.08)' }}>
                  <motion.div
                    className="h-2 rounded-full"
                    style={{ background: nbProgress >= 80 ? 'linear-gradient(90deg, #4ade80, #22c55e)' : 'linear-gradient(90deg, #00e5ff, #00b0ff)' }}
                    initial={{ width: 0 }}
                    animate={{ width: `${nbProgress}%` }}
                    transition={{ duration: 0.8, ease: 'easeOut' }}
                  />
                </div>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-6">
              <div className="text-3xl mb-2">🐝</div>
              <p className="text-xs text-jarvis-text-secondary/70 text-center">
                No active position<br />
                <span className="text-jarvis-text-secondary/40">Buys when Nifty dips {nbConf?.dip_threshold_pct ?? 1}%+</span>
              </p>
            </div>
          )}
        </div>

        {/* Swing Positions Card */}
        <div
          className="rounded-2xl p-5"
          style={{ background: 'rgba(0,8,24,0.97)', border: '1px solid rgba(0,229,255,0.1)' }}
        >
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <span className="text-base">📈</span>
              <span className="text-xs font-bold tracking-[0.2em] text-jarvis-primary uppercase">Equity Swing</span>
            </div>
            {openSwings.length > 0 && (
              <div className="flex items-center gap-2">
                <span className={`text-xs font-mono font-bold ${swingPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {swingPnl >= 0 ? '+' : ''}{formatCurrency(swingPnl)}
                </span>
                <span className="text-[10px] font-bold px-2 py-0.5 rounded-full" style={{ background: 'rgba(0,229,255,0.1)', color: '#00e5ff' }}>
                  {openSwings.length} OPEN
                </span>
              </div>
            )}
          </div>

          {openSwings.length > 0 ? (
            <div className="space-y-1.5">
              <div className="flex justify-between text-[10px] text-jarvis-text-secondary px-2 pb-1 border-b border-white/5">
                <span>Total Deployed: <span className="text-yellow-400 font-mono font-bold">{formatCurrency(swingDeployed)}</span></span>
                <span className={`font-mono font-bold ${swingPnlPct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  Avg P&L: {swingPnlPct >= 0 ? '+' : ''}{swingPnlPct.toFixed(2)}%
                </span>
              </div>
              {openSwings.slice(0, 5).map(pos => {
                const up       = (pos.pnl_pct ?? 0) >= 0;
                const deployed = pos.entry_price * pos.qty;
                return (
                  <div key={pos.symbol} className="grid grid-cols-4 items-center py-1.5 px-2 rounded-lg gap-2" style={{ background: 'rgba(0,229,255,0.025)', border: '1px solid rgba(0,229,255,0.05)' }}>
                    <div>
                      <div className="text-xs font-bold text-jarvis-primary">{pos.symbol}</div>
                      <div className="text-[9px] text-jarvis-text-secondary">{pos.qty} units</div>
                    </div>
                    <div>
                      <div className="text-[9px] text-jarvis-text-secondary">Deployed</div>
                      <div className="text-xs font-mono text-yellow-400">{formatCurrency(deployed)}</div>
                    </div>
                    <div>
                      <div className="text-[9px] text-jarvis-text-secondary">Entry→CMP</div>
                      <div className="text-[10px] font-mono text-jarvis-text-secondary">
                        ₹{pos.entry_price?.toFixed(0)} → ₹{pos.current_price?.toFixed(0)}
                      </div>
                    </div>
                    <div className="text-right">
                      <span className={`text-xs font-mono font-bold ${up ? 'text-green-400' : 'text-red-400'}`}>
                        {up ? '+' : ''}{(pos.pnl_pct ?? 0).toFixed(2)}%
                      </span>
                      <div className={`text-[9px] font-mono ${up ? 'text-green-400/70' : 'text-red-400/70'}`}>
                        {formatCurrency(pos.unrealized_pnl ?? 0)}
                      </div>
                    </div>
                  </div>
                );
              })}
              {openSwings.length > 5 && (
                <p className="text-[10px] text-jarvis-text-secondary/50 text-center pt-1">
                  +{openSwings.length - 5} more — view in Equity Swing
                </p>
              )}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-6">
              <div className="text-3xl mb-2">📈</div>
              <p className="text-xs text-jarvis-text-secondary/70 text-center">No open swing positions</p>
            </div>
          )}
        </div>
      </motion.div>

      {/* ── MARKET NEWS CARDS ─────────────────────────────────────── */}
      <motion.div variants={staggerItem}>
        <div className="flex items-center gap-2 mb-3">
          <span className="text-[10px] font-bold tracking-[0.25em] text-jarvis-primary/50 uppercase">Market Intelligence</span>
          <div className="flex-1 h-px bg-jarvis-primary/10" />
          <span className="text-[9px] text-jarvis-text-secondary/40">ET Markets · refreshed at open</span>
        </div>
        {newsLoading ? (
          <div className="grid grid-cols-2 gap-3">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="h-24 rounded-xl animate-pulse" style={{ background: 'rgba(0,229,255,0.04)' }} />
            ))}
          </div>
        ) : news.length > 0 ? (
          <div className="grid grid-cols-2 gap-3">
            {news.slice(0, 8).map((item, i) => (
              <motion.a
                key={i}
                href={item.link || '#'}
                target="_blank"
                rel="noopener noreferrer"
                className="block group cursor-pointer rounded-xl p-4"
                style={{
                  background: 'rgba(0,8,24,0.97)',
                  border: '1px solid rgba(0,229,255,0.07)',
                  textDecoration: 'none',
                  transition: 'all 0.2s',
                }}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.04 }}
                onMouseEnter={e => {
                  (e.currentTarget as HTMLElement).style.borderColor = 'rgba(0,229,255,0.2)';
                  (e.currentTarget as HTMLElement).style.background  = 'rgba(0,229,255,0.04)';
                }}
                onMouseLeave={e => {
                  (e.currentTarget as HTMLElement).style.borderColor = 'rgba(0,229,255,0.07)';
                  (e.currentTarget as HTMLElement).style.background  = 'rgba(0,8,24,0.97)';
                }}
              >
                {/* Source + index */}
                <div className="flex items-center justify-between mb-2">
                  <span
                    className="text-[9px] font-bold px-2 py-0.5 rounded-full"
                    style={{ background: 'rgba(0,229,255,0.08)', color: 'rgba(0,229,255,0.6)', letterSpacing: '0.1em' }}
                  >
                    {item.source || 'NEWS'}
                  </span>
                  <span className="text-[9px] font-mono text-jarvis-primary/25">#{i + 1}</span>
                </div>
                {/* Headline */}
                <p
                  className="text-xs leading-relaxed m-0 group-hover:text-jarvis-primary transition-colors"
                  style={{ color: 'rgba(200,220,240,0.85)', lineHeight: 1.5 }}
                >
                  {item.title}
                </p>
              </motion.a>
            ))}
          </div>
        ) : (
          <div className="rounded-2xl p-6 text-center" style={{ background: 'rgba(0,8,24,0.97)', border: '1px solid rgba(0,229,255,0.08)' }}>
            <p className="text-xs text-jarvis-text-secondary/50">News will appear here on trading days</p>
          </div>
        )}
      </motion.div>

      {/* ── EXECUTION LOG ─────────────────────────────────────────── */}
      <motion.div variants={staggerItem}>
        <div className="flex items-center gap-2 mb-3">
          <span className="text-[10px] font-bold tracking-[0.25em] text-jarvis-primary/50 uppercase">Live Stream</span>
          <div className="flex-1 h-px bg-jarvis-primary/10" />
        </div>
        <ExecutionLogFeed entries={logEntries} maxLines={6} title="Market Tick Feed" />
      </motion.div>

    </motion.div>
  );
}
