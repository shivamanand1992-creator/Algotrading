import React, { useEffect, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { marketApi } from '../../api/client';
import type { NewsItem, GlobalCue } from '../../types/api';

type Tab = 'all' | 'indian' | 'global';

function timeAgo(pub: string): string {
  if (!pub) return '';
  try {
    const d = new Date(pub);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 3600)  return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
  } catch {
    return pub.slice(0, 16);
  }
}

function CueCard({ cue }: { cue: GlobalCue }) {
  const up = (cue.change_pct ?? 0) >= 0;
  const border = cue.ltp === null ? 'rgba(0,229,255,0.06)'
    : up ? 'rgba(74,222,128,0.15)' : 'rgba(248,113,113,0.15)';
  return (
    <motion.div
      className="rounded-xl px-4 py-3"
      style={{ background: 'rgba(0,229,255,0.025)', border: `1px solid ${border}` }}
      whileHover={{ scale: 1.03 }}
      transition={{ type: 'spring', stiffness: 350 }}
    >
      <div className="flex justify-between items-start mb-1">
        <span className="text-[10px] font-bold text-jarvis-text-secondary uppercase tracking-wider leading-tight">{cue.name}</span>
        <span className={`text-[8px] font-bold px-1.5 py-0.5 rounded ${cue.type === 'index' ? 'bg-blue-400/10 text-blue-400' : cue.type === 'commodity' ? 'bg-amber-400/10 text-amber-400' : 'bg-purple-400/10 text-purple-400'}`}>
          {cue.type.toUpperCase()}
        </span>
      </div>
      <div>
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
}

export function MarketNewsView() {
  const [news, setNews]         = useState<NewsItem[]>([]);
  const [cues, setCues]         = useState<GlobalCue[]>([]);
  const [tab, setTab]           = useState<Tab>('all');
  const [loading, setLoading]   = useState(true);
  const [cuesLoading, setCuesLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [refreshing, setRefreshing]   = useState(false);

  const fetchNews = useCallback(async () => {
    try {
      const res = await marketApi.getNews();
      setNews(res.data ?? []);
      setLastRefresh(new Date());
    } catch {}
  }, []);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      marketApi.getNews().then(r => { setNews(r.data ?? []); setLastRefresh(new Date()); }),
      marketApi.getGlobalCues().then(r => setCues(r.data ?? [])).finally(() => setCuesLoading(false)),
    ]).finally(() => setLoading(false));

    // Refresh every 10 minutes
    const iv = setInterval(() => {
      marketApi.getNews().then(r => { setNews(r.data ?? []); setLastRefresh(new Date()); }).catch(() => {});
      marketApi.getGlobalCues().then(r => setCues(r.data ?? [])).catch(() => {});
    }, 600000);
    return () => clearInterval(iv);
  }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    await fetchNews();
    setRefreshing(false);
  };

  const filtered = tab === 'all' ? news
    : tab === 'indian' ? news.filter(n => n.category === 'indian' || !n.category)
    : news.filter(n => n.category === 'global');

  // Overall market sentiment from global cues
  const risingCues = cues.filter(c => (c.change_pct ?? 0) > 0).length;
  const totalCues  = cues.filter(c => c.ltp !== null).length;
  const sentimentRatio = totalCues > 0 ? risingCues / totalCues : 0.5;
  const globalSentiment = sentimentRatio >= 0.65 ? 'POSITIVE' : sentimentRatio <= 0.35 ? 'NEGATIVE' : 'MIXED';
  const sentimentColor  = globalSentiment === 'POSITIVE' ? '#4ade80' : globalSentiment === 'NEGATIVE' ? '#f87171' : '#facc15';

  return (
    <motion.div
      className="space-y-5"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
    >
      {/* ── Header ─────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-black text-jarvis-primary tracking-widest uppercase glow-text">
            Market Intelligence
          </h2>
          <p className="text-xs text-jarvis-text-secondary mt-0.5 tracking-wider">
            Global & Indian market news · analyst ratings · results
          </p>
        </div>
        <div className="flex items-center gap-3">
          {lastRefresh && (
            <span className="text-[10px] text-jarvis-text-secondary/50">
              Updated {lastRefresh.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="px-4 py-2 rounded-lg text-xs font-bold uppercase tracking-widest transition-all"
            style={{ background: 'rgba(0,229,255,0.08)', border: '1px solid rgba(0,229,255,0.3)', color: '#00e5ff' }}
          >
            {refreshing ? 'Fetching…' : '↺ Refresh'}
          </button>
        </div>
      </div>

      {/* ── Global Sentiment Banner ─────────────────────────────────── */}
      {!cuesLoading && cues.length > 0 && (
        <motion.div
          className="rounded-xl px-5 py-3 flex items-center justify-between"
          style={{
            background: `${sentimentColor}08`,
            border: `1px solid ${sentimentColor}30`,
          }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
        >
          <div className="flex items-center gap-3">
            <motion.div
              className="w-3 h-3 rounded-full"
              style={{ background: sentimentColor, boxShadow: `0 0 10px ${sentimentColor}` }}
              animate={{ scale: [1, 1.3, 1] }}
              transition={{ duration: 2, repeat: Infinity }}
            />
            <span className="text-sm font-bold tracking-widest uppercase" style={{ color: sentimentColor }}>
              Global Sentiment: {globalSentiment}
            </span>
            <span className="text-xs text-jarvis-text-secondary/60">
              {risingCues}/{totalCues} markets up
            </span>
          </div>
          <div className="flex gap-2">
            {cues.filter(c => c.type === 'index').slice(0, 4).map(c => (
              <span key={c.symbol} className="text-xs font-mono" style={{ color: (c.change_pct ?? 0) >= 0 ? '#4ade80' : '#f87171' }}>
                {c.name.split(' ')[0]} {(c.change_pct ?? 0) >= 0 ? '+' : ''}{(c.change_pct ?? 0).toFixed(1)}%
              </span>
            ))}
          </div>
        </motion.div>
      )}

      {/* ── Global Cues Grid ───────────────────────────────────────── */}
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
            {cues.map(c => <CueCard key={c.symbol} cue={c} />)}
          </div>
        )}
      </div>

      {/* ── News Feed ─────────────────────────────────────────────── */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-bold tracking-[0.25em] text-jarvis-primary/50 uppercase">News Feed</span>
            <div className="h-px bg-jarvis-primary/10 w-16" />
          </div>
          {/* Tab selector */}
          <div className="flex gap-1">
            {(['all', 'indian', 'global'] as Tab[]).map(t => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className="px-3 py-1 rounded-md text-[10px] font-bold uppercase tracking-widest transition-all"
                style={{
                  background: tab === t ? 'rgba(0,229,255,0.15)' : 'transparent',
                  border: tab === t ? '1px solid rgba(0,229,255,0.4)' : '1px solid transparent',
                  color: tab === t ? '#00e5ff' : 'rgba(160,196,224,0.4)',
                }}
              >
                {t === 'all' ? 'All' : t === 'indian' ? '🇮🇳 India' : '🌐 Global'}
              </button>
            ))}
          </div>
        </div>

        <div className="rounded-2xl overflow-hidden" style={{ background: 'rgba(0,5,18,0.97)', border: '1px solid rgba(0,229,255,0.08)' }}>
          {loading ? (
            <div className="p-6 space-y-4">
              {[...Array(8)].map((_, i) => (
                <div key={i} className="flex gap-3">
                  <div className="w-4 h-3 rounded animate-pulse" style={{ background: 'rgba(0,229,255,0.06)', flexShrink: 0, marginTop: 2 }} />
                  <div className="flex-1 h-4 rounded animate-pulse" style={{ background: 'rgba(0,229,255,0.04)', width: `${88 - i * 4}%` }} />
                </div>
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <div className="p-10 text-center">
              <div className="text-3xl mb-3">📰</div>
              <p className="text-sm text-jarvis-text-secondary">No news articles found</p>
              <p className="text-xs text-jarvis-text-secondary/50 mt-1">RSS feeds may be temporarily unavailable. Try refreshing.</p>
            </div>
          ) : (
            <div className="divide-y divide-white/5">
              <AnimatePresence>
                {filtered.map((item, i) => (
                  <motion.a
                    key={`${item.source}-${i}`}
                    href={item.link || '#'}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-start gap-4 px-5 py-3.5 group transition-colors"
                    style={{ cursor: item.link ? 'pointer' : 'default' }}
                    onMouseEnter={e => (e.currentTarget.style.background = 'rgba(0,229,255,0.03)')}
                    onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                    initial={{ opacity: 0, x: -6 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: Math.min(i * 0.03, 0.4) }}
                  >
                    {/* Index */}
                    <span className="text-jarvis-primary/25 text-[10px] font-mono mt-1 flex-shrink-0 w-5 text-right">
                      {i + 1}
                    </span>

                    {/* Content */}
                    <div className="flex-1 min-w-0">
                      <p className="text-xs text-jarvis-text-secondary group-hover:text-jarvis-primary transition-colors leading-relaxed">
                        {item.title}
                      </p>
                      <div className="flex items-center gap-3 mt-1">
                        {item.source && (
                          <span className="text-[9px] font-bold px-1.5 py-0.5 rounded" style={{ background: 'rgba(0,229,255,0.07)', color: 'rgba(0,229,255,0.5)' }}>
                            {item.source}
                          </span>
                        )}
                        {item.category && (
                          <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${item.category === 'global' ? 'bg-blue-400/10 text-blue-400/70' : 'bg-green-400/10 text-green-400/70'}`}>
                            {item.category === 'global' ? '🌐' : '🇮🇳'}
                          </span>
                        )}
                        {item.published && (
                          <span className="text-[9px] text-jarvis-text-secondary/35">
                            {timeAgo(item.published) || item.published.slice(0, 20)}
                          </span>
                        )}
                        {item.link && (
                          <span className="text-[9px] text-jarvis-primary/30 group-hover:text-jarvis-primary/60 transition-colors ml-auto">
                            Read →
                          </span>
                        )}
                      </div>
                    </div>
                  </motion.a>
                ))}
              </AnimatePresence>
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
}
