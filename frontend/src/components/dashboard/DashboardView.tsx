import React, { useEffect, useState, useRef } from 'react';
import { motion, type Variants } from 'framer-motion';
import { AreaChart, Area, ResponsiveContainer, XAxis, YAxis, Tooltip } from 'recharts';
import { useWebSocket } from '../../hooks/useWebSocket';
import { marketApi, niftyBeesApi, stocksApi } from '../../api/client';
import { formatCurrency } from '../../utils/formatters';
import type { MarketData, GlobalCue, NewsItem, NiftyBeesStatus, SwingPosition } from '../../types/api';

const staggerContainer: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.07 } },
};
const staggerItem: Variants = {
  hidden: { opacity: 0, y: 20 },
  show:   { opacity: 1, y: 0, transition: { duration: 0.4, ease: 'easeOut' } },
};

const SPARKLINE_MAX = 120;

function SparkTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: 'rgba(0,5,20,0.95)', border: '1px solid rgba(0,229,255,0.3)', borderRadius: 8, padding: '6px 12px', fontSize: 11, fontFamily: 'monospace', color: '#00e5ff' }}>
      {payload[0]?.value?.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
    </div>
  );
}

export function DashboardView() {
  const { connected, marketData: wsMarketData } = useWebSocket();
  const [marketData, setMarketData]     = useState<MarketData | null>(null);
  const [sparkline, setSparkline]       = useState<{ v: number; t: string }[]>([]);
  const [globalCues, setGlobalCues]     = useState<GlobalCue[]>([]);
  const [news, setNews]                 = useState<NewsItem[]>([]);
  const [nbStatus, setNbStatus]         = useState<NiftyBeesStatus | null>(null);
  const [swingPositions, setSwingPositions] = useState<SwingPosition[]>([]);
  const [cuesLoading, setCuesLoading]   = useState(true);
  const [newsLoading, setNewsLoading]   = useState(true);
  const prevLtp = useRef<number>(0);

  // Market data polling (30s)
  useEffect(() => {
    const fetch = async () => {
      try {
        const res = await marketApi.getCurrent();
        setMarketData(res.data);
      } catch {}
    };
    fetch();
    const iv = setInterval(fetch, 30000);
    return () => clearInterval(iv);
  }, []);

  // NiftyBees status (15s)
  useEffect(() => {
    const fetch = async () => {
      try {
        const res = await niftyBeesApi.getStatus();
        setNbStatus(res.data);
      } catch {}
    };
    fetch();
    const iv = setInterval(fetch, 15000);
    return () => clearInterval(iv);
  }, []);

  // Swing positions (30s)
  useEffect(() => {
    const fetch = async () => {
      try {
        const res = await stocksApi.getPositions();
        setSwingPositions(Array.isArray(res.data) ? res.data : []);
      } catch {}
    };
    fetch();
    const iv = setInterval(fetch, 30000);
    return () => clearInterval(iv);
  }, []);

  // Global cues once on mount + every 5 min
  useEffect(() => {
    const fetch = async () => {
      setCuesLoading(true);
      try {
        const res = await marketApi.getGlobalCues();
        setGlobalCues(res.data);
      } catch {} finally { setCuesLoading(false); }
    };
    fetch();
    const iv = setInterval(fetch, 300000);
    return () => clearInterval(iv);
  }, []);

  // News once on mount
  useEffect(() => {
    const fetch = async () => {
      setNewsLoading(true);
      try {
        const res = await marketApi.getNews();
        setNews(res.data);
      } catch {} finally { setNewsLoading(false); }
    };
    fetch();
  }, []);

  // Sparkline from WS ticks
  useEffect(() => {
    if (wsMarketData) {
      setMarketData(wsMarketData);
      setSparkline(prev => {
        const now = new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false });
        const next = [...prev, { v: wsMarketData.ltp, t: now }];
        return next.length > SPARKLINE_MAX ? next.slice(-SPARKLINE_MAX) : next;
      });
    }
  }, [wsMarketData]);

  const ltp        = marketData?.ltp ?? 0;
  const change     = marketData?.change ?? 0;
  const changePct  = marketData?.change_percentage ?? 0;
  const isUp       = change >= 0;
  const ltpChanged = ltp !== prevLtp.current;
  prevLtp.current  = ltp;

  const nb     = nbStatus?.position ?? null;
  const nbConf = nbStatus?.config;
  const nbTarget = nbConf?.target_gain_pct ?? 5;
  const nbPnlPct = nb?.pnl_pct ?? 0;
  const nbProgress = Math.min((nbPnlPct / nbTarget) * 100, 100);

  return (
    <motion.div
      className="space-y-5"
      variants={staggerContainer}
      initial="hidden"
      animate="show"
    >
      {/* ── HERO: Nifty 50 ──────────────────────────────────────────── */}
      <motion.div variants={staggerItem}>
        <div
          className="relative overflow-hidden rounded-2xl neon-border"
          style={{ background: 'linear-gradient(135deg, rgba(0,8,24,0.97) 0%, rgba(0,20,45,0.97) 100%)' }}
        >
          <div className="scan-line" />
          <div className="px-8 py-6 grid grid-cols-3 gap-6 items-center">
            {/* Left: Price */}
            <div className="col-span-2">
              <div className="flex items-center gap-3 mb-1">
                <span className="text-[10px] font-bold tracking-[0.3em] text-jarvis-primary/60 uppercase">Nifty 50 Index</span>
                <motion.div
                  className={`w-2 h-2 rounded-full ${connected ? 'bg-green-400' : 'bg-red-500'}`}
                  animate={connected ? { scale: [1, 1.4, 1], opacity: [1, 0.5, 1] } : {}}
                  transition={{ duration: 1.5, repeat: Infinity }}
                />
                <span className="text-[10px] text-jarvis-text-secondary/60">{connected ? 'LIVE' : 'OFFLINE'}</span>
              </div>
              <div className="flex items-end gap-5">
                <motion.div
                  className="text-6xl font-black font-mono tabular-nums glow-text"
                  style={{ color: '#00e5ff', letterSpacing: '-1px' }}
                  key={ltp}
                  animate={ltpChanged ? { scale: [1, 1.02, 1] } : {}}
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

            {/* Right: Sparkline */}
            <div>
              {sparkline.length > 4 ? (
                <ResponsiveContainer width="100%" height={90}>
                  <AreaChart data={sparkline} margin={{ top: 2, right: 2, left: 2, bottom: 2 }}>
                    <defs>
                      <linearGradient id="heroGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%"  stopColor={isUp ? '#4ade80' : '#f87171'} stopOpacity={0.3} />
                        <stop offset="95%" stopColor={isUp ? '#4ade80' : '#f87171'} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <XAxis dataKey="t" hide />
                    <YAxis domain={['auto', 'auto']} hide />
                    <Tooltip content={<SparkTooltip />} />
                    <Area
                      type="monotone" dataKey="v"
                      stroke={isUp ? '#4ade80' : '#f87171'} strokeWidth={2}
                      fill="url(#heroGrad)" dot={false} isAnimationActive={false}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-20 flex items-center justify-center text-xs text-jarvis-text-secondary/40 tracking-widest uppercase">
                  Waiting for ticks…
                </div>
              )}
            </div>
          </div>
        </div>
      </motion.div>

      {/* ── GLOBAL CUES ─────────────────────────────────────────────── */}
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

      {/* ── NIFTYBEES + SWING POSITIONS ─────────────────────────────── */}
      <motion.div variants={staggerItem} className="grid grid-cols-2 gap-5">
        {/* NiftyBees Card */}
        <div
          className="rounded-2xl p-5 relative overflow-hidden"
          style={{ background: 'linear-gradient(135deg, rgba(0,8,24,0.97) 0%, rgba(0,30,50,0.97) 100%)', border: nb?.active ? '1px solid rgba(0,229,255,0.3)' : '1px solid rgba(0,229,255,0.1)' }}
        >
          {nb?.active && <div className="scan-line" />}
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <span className="text-base">🐝</span>
              <span className="text-xs font-bold tracking-[0.2em] text-jarvis-primary uppercase">NiftyBees ETF</span>
            </div>
            {nbConf?.enabled ? (
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full" style={{ background: 'rgba(0,229,255,0.1)', color: '#00e5ff' }}>
                AUTOPILOT ON
              </span>
            ) : (
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full" style={{ background: 'rgba(255,100,100,0.1)', color: '#f87171' }}>
                DISABLED
              </span>
            )}
          </div>

          {nb?.active ? (
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <div>
                  <div className="text-[10px] text-jarvis-text-secondary uppercase tracking-wider">DCA Position</div>
                  <div className="text-2xl font-black font-mono text-jarvis-primary tabular-nums mt-0.5">
                    {nb.total_qty} <span className="text-base font-normal">units</span>
                  </div>
                  <div className="text-xs text-jarvis-text-secondary mt-0.5">
                    {nb.buys?.length ?? 1} {(nb.buys?.length ?? 1) === 1 ? 'buy' : 'buys'} · avg ₹{nb.avg_entry_price?.toFixed(2)}
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-[10px] text-jarvis-text-secondary uppercase tracking-wider">Unrealised P&L</div>
                  <div className={`text-xl font-mono font-bold tabular-nums mt-0.5 ${(nb.pnl_pct ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {(nb.pnl_pct ?? 0) >= 0 ? '+' : ''}{(nb.pnl_pct ?? 0).toFixed(2)}%
                  </div>
                  <div className={`text-xs font-mono ${(nb.unrealized_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {formatCurrency(nb.unrealized_pnl ?? 0)}
                  </div>
                </div>
              </div>

              {/* Progress toward target */}
              <div>
                <div className="flex justify-between text-[10px] text-jarvis-text-secondary mb-1.5">
                  <span>Progress toward {nbTarget}% target</span>
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

              <div className="flex items-center gap-4 text-xs text-jarvis-text-secondary border-t border-white/5 pt-2 mt-1">
                <span>Invested: <span className="text-jarvis-primary font-mono">{formatCurrency(nb.total_invested ?? 0)}</span></span>
                <span>Mode: <span className={nb.mode === 'live' ? 'text-red-400 font-bold' : 'text-jarvis-accent'}>{(nb.mode ?? 'paper').toUpperCase()}</span></span>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-6">
              <div className="text-3xl mb-2">🐝</div>
              <p className="text-xs text-jarvis-text-secondary/70 text-center">No active position<br />
                <span className="text-jarvis-text-secondary/40">Autopilot will buy when Nifty dips {nbConf?.dip_threshold_pct ?? 1}%+</span>
              </p>
            </div>
          )}
        </div>

        {/* Swing Positions Summary */}
        <div className="rounded-2xl p-5" style={{ background: 'rgba(0,8,24,0.97)', border: '1px solid rgba(0,229,255,0.1)' }}>
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <span className="text-base">📈</span>
              <span className="text-xs font-bold tracking-[0.2em] text-jarvis-primary uppercase">Equity Swing</span>
            </div>
            {swingPositions.length > 0 && (
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full" style={{ background: 'rgba(0,229,255,0.1)', color: '#00e5ff' }}>
                {swingPositions.length} OPEN
              </span>
            )}
          </div>

          {swingPositions.length > 0 ? (
            <div className="space-y-2">
              {swingPositions.slice(0, 4).map(pos => {
                const up = (pos.pnl_pct ?? 0) >= 0;
                return (
                  <div key={pos.symbol} className="flex items-center justify-between py-2 px-3 rounded-lg" style={{ background: 'rgba(0,229,255,0.03)', border: '1px solid rgba(0,229,255,0.06)' }}>
                    <div>
                      <span className="text-xs font-bold text-jarvis-primary">{pos.symbol}</span>
                      <div className="text-[10px] text-jarvis-text-secondary mt-0.5">
                        ₹{pos.entry_price?.toFixed(2)} → ₹{pos.current_price?.toFixed(2)}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className={`text-sm font-mono font-bold ${up ? 'text-green-400' : 'text-red-400'}`}>
                        {up ? '+' : ''}{(pos.pnl_pct ?? 0).toFixed(2)}%
                      </div>
                      <div className={`text-[10px] font-mono ${up ? 'text-green-400/70' : 'text-red-400/70'}`}>
                        {formatCurrency(pos.unrealized_pnl ?? 0)}
                      </div>
                    </div>
                  </div>
                );
              })}
              {swingPositions.length > 4 && (
                <p className="text-[10px] text-jarvis-text-secondary/50 text-center pt-1">
                  +{swingPositions.length - 4} more — view in Equity Swing
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

      {/* ── MARKET NEWS ─────────────────────────────────────────────── */}
      <motion.div variants={staggerItem}>
        <div className="flex items-center gap-2 mb-3">
          <span className="text-[10px] font-bold tracking-[0.25em] text-jarvis-primary/50 uppercase">Market Intelligence</span>
          <div className="flex-1 h-px bg-jarvis-primary/10" />
          <span className="text-[9px] text-jarvis-text-secondary/40">ET Markets · refreshed at 09:00 IST</span>
        </div>
        <div
          className="rounded-2xl p-4"
          style={{ background: 'rgba(0,8,24,0.97)', border: '1px solid rgba(0,229,255,0.08)' }}
        >
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
                  {item.published && (
                    <span className="text-[10px] text-jarvis-text-secondary/40 flex-shrink-0 whitespace-nowrap ml-2">{item.published.slice(0, 20)}</span>
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
