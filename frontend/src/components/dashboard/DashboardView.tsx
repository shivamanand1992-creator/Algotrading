import React, { useEffect, useState, useRef, useCallback } from 'react';
import { motion, type Variants } from 'framer-motion';
import {
  ComposedChart, Area, Line, ResponsiveContainer,
  XAxis, YAxis, Tooltip,
} from 'recharts';
import { useWebSocket } from '../../hooks/useWebSocket';
import { marketApi, niftyBeesApi, stocksApi, systemApi } from '../../api/client';
import { formatCurrency } from '../../utils/formatters';
import type { MarketData, GlobalCue, NewsItem, NiftyBeesStatus, SwingPosition, NiftyTechCandle } from '../../types/api';

const staggerContainer: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.07 } },
};
const staggerItem: Variants = {
  hidden: { opacity: 0, y: 20 },
  show:   { opacity: 1, y: 0, transition: { duration: 0.4, ease: 'easeOut' } },
};

function calcEMA(prices: number[], period: number): (number | null)[] {
  const k = 2 / (period + 1);
  const out: (number | null)[] = new Array(prices.length).fill(null);
  if (prices.length < period) return out;
  let prev = prices.slice(0, period).reduce((a, b) => a + b, 0) / period;
  out[period - 1] = prev;
  for (let i = period; i < prices.length; i++) {
    prev = prices[i] * k + prev * (1 - k);
    out[i] = parseFloat(prev.toFixed(2));
  }
  return out;
}

interface Balance { available_cash: number; net: number; used_margin: number; error?: string; }

export function DashboardView() {
  const { connected, marketData: wsMarketData } = useWebSocket();
  const [marketData, setMarketData]     = useState<MarketData | null>(null);
  const [emaCandles, setEmaCandles]     = useState<NiftyTechCandle[]>([]);
  const [globalCues, setGlobalCues]     = useState<GlobalCue[]>([]);
  const [news, setNews]                 = useState<NewsItem[]>([]);
  const [nbStatus, setNbStatus]         = useState<NiftyBeesStatus | null>(null);
  const [swingPositions, setSwingPositions] = useState<SwingPosition[]>([]);
  const [balance, setBalance]           = useState<Balance | null>(null);
  const [cuesLoading, setCuesLoading]   = useState(true);
  const [newsLoading, setNewsLoading]   = useState(true);
  const [syncing, setSyncing]           = useState(false);
  const [syncMsg, setSyncMsg]           = useState('');
  const [lastUpdated, setLastUpdated]   = useState<Date | null>(null);
  const prevLtp = useRef<number>(0);

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

  // ── EMA chart: daily OHLCV 30d (5 min) ──────────────────────────
  useEffect(() => {
    const f = async () => {
      try {
        const res = await marketApi.getOHLCV('ONE_DAY', 30);
        const candles = res.data ?? [];
        if (candles.length < 9) return;
        const closes = candles.map(c => c.close);
        const ema9   = calcEMA(closes, 9);
        const ema21  = calcEMA(closes, 21);
        setEmaCandles(candles.map((c, i) => ({
          date: c.timestamp.slice(0, 10),
          close: c.close,
          ema9:  ema9[i],
          ema21: ema21[i],
          bb_up: null, bb_lo: null,
        })));
      } catch {}
    };
    f();
    const iv = setInterval(f, 300000);
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

  // ── News (once on mount) ─────────────────────────────────────────
  useEffect(() => {
    setNewsLoading(true);
    marketApi.getNews()
      .then(r => setNews(r.data))
      .catch(() => {})
      .finally(() => setNewsLoading(false));
  }, []);

  // ── WS tick → market data ────────────────────────────────────────
  useEffect(() => {
    if (wsMarketData) {
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
      // Refresh data after sync
      const [nbRes, swRes, balRes] = await Promise.allSettled([
        niftyBeesApi.getStatus(),
        stocksApi.getPositions(),
        systemApi.getBalance(),
      ]);
      if (nbRes.status === 'fulfilled')   setNbStatus(nbRes.value.data);
      if (swRes.status === 'fulfilled')   setSwingPositions(Array.isArray(swRes.value.data) ? swRes.value.data : []);
      if (balRes.status === 'fulfilled')  setBalance(balRes.value.data);
    } catch {
      setSyncMsg('✗ Sync failed');
    } finally {
      setSyncing(false);
      setTimeout(() => setSyncMsg(''), 4000);
    }
  };

  const ltp       = marketData?.ltp ?? 0;
  const change    = marketData?.change ?? 0;
  const changePct = marketData?.change_percentage ?? 0;
  const isUp      = change >= 0;
  const ltpFlash  = ltp !== prevLtp.current && ltp > 0;
  prevLtp.current = ltp;

  const nb       = nbStatus?.position ?? null;
  const nbConf   = nbStatus?.config;
  const nbTarget = nbConf?.target_gain_pct ?? 5;
  const nbPnlPct = nb?.pnl_pct ?? 0;
  const nbProgress = Math.min((nbPnlPct / nbTarget) * 100, 100);

  const openSwings      = swingPositions.filter(p => p.status === 'open');
  const swingDeployed   = openSwings.reduce((s, p) => s + (p.entry_price * p.qty), 0);
  const swingPnl        = openSwings.reduce((s, p) => s + (p.unrealized_pnl ?? 0), 0);
  const swingPnlPct     = openSwings.length > 0
    ? openSwings.reduce((s, p) => s + (p.pnl_pct ?? 0), 0) / openSwings.length : 0;

  const balLow = balance && nbConf && balance.available_cash < nbConf.capital_amount * 1.1;

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

      {/* ── HERO: Nifty 50 ────────────────────────────────────────── */}
      <motion.div variants={staggerItem}>
        <div
          className="relative overflow-hidden rounded-2xl neon-border"
          style={{ background: 'linear-gradient(135deg, rgba(0,8,24,0.97) 0%, rgba(0,20,45,0.97) 100%)' }}
        >
          <div className="scan-line" />
          <div className="px-8 py-6 grid grid-cols-3 gap-6 items-center">
            {/* Price */}
            <div className="col-span-2">
              <div className="flex items-center gap-3 mb-1">
                <span className="text-[10px] font-bold tracking-[0.3em] text-jarvis-primary/60 uppercase">Nifty 50 Index</span>
              </div>
              <div className="flex items-end gap-5">
                <motion.div
                  className="text-6xl font-black font-mono tabular-nums glow-text"
                  style={{ color: '#00e5ff', letterSpacing: '-1px' }}
                  key={ltp}
                  animate={ltpFlash ? { scale: [1, 1.02, 1] } : {}}
                  transition={{ duration: 0.25 }}
                >
                  {ltp > 0 ? ltp.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}
                </motion.div>
                <div className="mb-2">
                  <div className={`text-2xl font-mono font-bold tabular-nums ${isUp ? 'text-green-400' : 'text-red-400'}`}>
                    {isUp ? '+' : ''}{change.toFixed(2)}
                  </div>
                  <div className={`text-base font-mono ${isUp ? 'text-green-400' : 'text-red-400'}`}>
                    {isUp ? '▲' : '▼'} {Math.abs(changePct).toFixed(2)}%
                  </div>
                </div>
              </div>
            </div>

            {/* EMA9 + EMA21 chart */}
            <div>
              {emaCandles.length > 8 ? (
                <>
                  <div className="flex items-center gap-3 mb-1.5 justify-end">
                    <span className="flex items-center gap-1 text-[9px] font-bold text-green-400/80"><span className="inline-block w-3 h-0.5 bg-green-400" />EMA 9</span>
                    <span className="flex items-center gap-1 text-[9px] font-bold text-yellow-400/80"><span className="inline-block w-3 h-0.5 bg-yellow-400" />EMA 21</span>
                    <span className="flex items-center gap-1 text-[9px] text-jarvis-text-secondary/50">30D</span>
                  </div>
                  <ResponsiveContainer width="100%" height={82}>
                    <ComposedChart data={emaCandles} margin={{ top: 2, right: 2, left: 2, bottom: 0 }}>
                      <defs>
                        <linearGradient id="heroCloseGrad" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%"   stopColor={isUp ? '#4ade80' : '#f87171'} stopOpacity={0.18} />
                          <stop offset="100%" stopColor={isUp ? '#4ade80' : '#f87171'} stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <XAxis dataKey="date" hide />
                      <YAxis domain={['auto', 'auto']} hide />
                      <Tooltip
                        content={({ active, payload }) => {
                          if (!active || !payload?.length) return null;
                          const d = payload[0]?.payload as NiftyTechCandle;
                          return (
                            <div style={{ background: 'rgba(0,5,20,0.95)', border: '1px solid rgba(0,229,255,0.2)', borderRadius: 6, padding: '5px 10px', fontSize: 10, fontFamily: 'monospace' }}>
                              <div style={{ color: '#a0c4e0', marginBottom: 2 }}>{d?.date}</div>
                              <div style={{ color: '#00e5ff' }}>Close: {d?.close?.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</div>
                              {d?.ema9  && <div style={{ color: '#4ade80' }}>EMA9:  {d.ema9?.toLocaleString('en-IN',  { maximumFractionDigits: 0 })}</div>}
                              {d?.ema21 && <div style={{ color: '#facc15' }}>EMA21: {d.ema21?.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</div>}
                            </div>
                          );
                        }}
                      />
                      <Area type="monotone" dataKey="close"
                        stroke={isUp ? '#4ade80' : '#f87171'} strokeWidth={1.5}
                        fill="url(#heroCloseGrad)" dot={false} isAnimationActive={false}
                      />
                      <Line type="monotone" dataKey="ema9"  stroke="#4ade80" strokeWidth={1.5} dot={false} isAnimationActive={false} connectNulls />
                      <Line type="monotone" dataKey="ema21" stroke="#facc15" strokeWidth={1.5} dot={false} isAnimationActive={false} connectNulls />
                    </ComposedChart>
                  </ResponsiveContainer>
                </>
              ) : (
                <div className="h-20 flex items-center justify-center text-xs text-jarvis-text-secondary/40 tracking-widest uppercase">
                  Loading EMA chart…
                </div>
              )}
            </div>
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
              <div className={`text-base font-mono font-bold ${balLow ? 'text-red-400' : 'text-green-400'}`}>
                {balance ? `₹${balance.available_cash.toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—'}
              </div>
            </div>
            <div className="text-right">
              <div className="text-[9px] text-jarvis-text-secondary/50 uppercase">Net Value</div>
              <div className="text-base font-mono font-bold text-jarvis-primary">
                {balance?.net ? `₹${balance.net.toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—'}
              </div>
            </div>
            <div className="text-right">
              <div className="text-[9px] text-jarvis-text-secondary/50 uppercase">Next DCA Chunk</div>
              <div className="text-base font-mono font-bold text-jarvis-accent">
                {nbConf ? `₹${nbConf.capital_amount.toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—'}
              </div>
            </div>
            {balance && nbConf && (
              <div className="text-right">
                <div className="text-[9px] text-jarvis-text-secondary/50 uppercase">Chunks Available</div>
                <div className={`text-base font-mono font-bold ${balLow ? 'text-red-400' : 'text-jarvis-secondary'}`}>
                  {Math.floor(balance.available_cash / nbConf.capital_amount)}×
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
          <div className="grid grid-cols-4 gap-3">
            {globalCues.map(cue => {
              const up = (cue.change_pct ?? 0) >= 0;
              return (
                <motion.div
                  key={cue.symbol}
                  className="rounded-xl px-4 py-3 flex flex-col justify-between"
                  style={{ background: 'rgba(0,229,255,0.03)', border: `1px solid ${cue.ltp === null ? 'rgba(0,229,255,0.06)' : up ? 'rgba(74,222,128,0.12)' : 'rgba(248,113,113,0.12)'}` }}
                  whileHover={{ scale: 1.02 }}
                  transition={{ type: 'spring', stiffness: 300 }}
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
                </motion.div>
              );
            })}
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
              {/* Main P&L row */}
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

              {/* Capital stats */}
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

              {/* Progress toward target */}
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
              {/* Summary row */}
              <div className="flex justify-between text-[10px] text-jarvis-text-secondary px-2 pb-1 border-b border-white/5">
                <span>Total Deployed: <span className="text-yellow-400 font-mono font-bold">{formatCurrency(swingDeployed)}</span></span>
                <span className={`font-mono font-bold ${swingPnlPct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  Avg P&L: {swingPnlPct >= 0 ? '+' : ''}{swingPnlPct.toFixed(2)}%
                </span>
              </div>
              {/* Position rows */}
              {openSwings.slice(0, 5).map(pos => {
                const up      = (pos.pnl_pct ?? 0) >= 0;
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

      {/* ── MARKET NEWS ───────────────────────────────────────────── */}
      <motion.div variants={staggerItem}>
        <div className="flex items-center gap-2 mb-3">
          <span className="text-[10px] font-bold tracking-[0.25em] text-jarvis-primary/50 uppercase">Market Intelligence</span>
          <div className="flex-1 h-px bg-jarvis-primary/10" />
          <span className="text-[9px] text-jarvis-text-secondary/40">ET Markets · auto-refreshed at 09:00 IST</span>
        </div>
        <div className="rounded-2xl p-4" style={{ background: 'rgba(0,8,24,0.97)', border: '1px solid rgba(0,229,255,0.08)' }}>
          {newsLoading ? (
            <div className="space-y-3">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="h-5 rounded animate-pulse" style={{ background: 'rgba(0,229,255,0.04)', width: `${85 - i * 7}%` }} />
              ))}
            </div>
          ) : news.length > 0 ? (
            <div className="divide-y divide-white/5">
              {news.slice(0, 7).map((item, i) => (
                <motion.a
                  key={i}
                  href={item.link || '#'}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-start gap-3 py-2.5 group cursor-pointer"
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.05 }}
                >
                  <span className="text-jarvis-primary/30 text-xs font-mono mt-0.5 flex-shrink-0 w-4">{i + 1}</span>
                  <span className="text-xs text-jarvis-text-secondary group-hover:text-jarvis-primary transition-colors leading-relaxed flex-1">
                    {item.title}
                  </span>
                  {item.source && (
                    <span className="text-[9px] text-jarvis-text-secondary/40 flex-shrink-0 whitespace-nowrap">{item.source}</span>
                  )}
                </motion.a>
              ))}
            </div>
          ) : (
            <p className="text-xs text-jarvis-text-secondary/50 text-center py-4">
              News will appear here at 09:00 IST on trading days
            </p>
          )}
        </div>
      </motion.div>
    </motion.div>
  );
}
