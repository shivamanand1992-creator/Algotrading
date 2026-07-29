import React, { useState, useCallback } from 'react';
import { api } from '../../api/client';
import { NiftyGrowsectHeatmap } from '../growsect/NiftyGrowsectHeatmap';

// ── Types ────────────────────────────────────────────────────────────────────

interface CycleInfo {
  phase: string;
  description: string;
  advice: string;
  confidence: string;
  nifty_price: number;
  nifty_ret_4w: number;
  nifty_ret_12w: number;
  nifty_ret_26w: number;
  nifty_ret_52w: number;
  above_ema200: boolean;
  weeks_above_ema200: number;
  ema200: number;
}

interface SectorResult {
  id: string;
  name: string;
  theme: string;
  etf: string | null;
  etf_name: string | null;
  rank: number;
  signal: string;
  total_score: number;
  momentum_score: number;
  technical_score: number;
  cycle_score: number;
  ret_4w: number;
  ret_12w: number;
  ret_26w: number;
  ret_4w_vs_nifty: number;
  ret_12w_vs_nifty: number;
  ret_26w_vs_nifty: number;
  rsi: number;
  adx: number;
  macd_hist: number;
  above_e10: boolean;
  above_e26: boolean;
  above_e52: boolean;
  ema_aligned: boolean;
  reasons: string[];
  data_error: boolean;
}

interface AnalysisResult {
  cycle: CycleInfo;
  sectors: SectorResult[];
  scan_time: string;
  elapsed_s: number;
  top_picks: string[];
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const SIGNAL_STYLES: Record<string, { bg: string; text: string; border: string }> = {
  BUY:        { bg: 'bg-green-500/20',  text: 'text-green-400',  border: 'border-green-500/50' },
  ACCUMULATE: { bg: 'bg-cyan-500/20',   text: 'text-cyan-400',   border: 'border-cyan-500/50'  },
  HOLD:       { bg: 'bg-yellow-500/20', text: 'text-yellow-400', border: 'border-yellow-500/50' },
  AVOID:      { bg: 'bg-red-500/20',    text: 'text-red-400',    border: 'border-red-500/50'   },
  'N/A':      { bg: 'bg-gray-500/20',   text: 'text-gray-400',   border: 'border-gray-500/50'  },
};

const PHASE_COLOURS: Record<string, string> = {
  expansion:      'text-green-400',
  recovery:       'text-cyan-400',
  late_expansion: 'text-yellow-400',
  contraction:    'text-red-400',
};

const PHASE_ICONS: Record<string, string> = {
  expansion:      '🚀',
  recovery:       '🌱',
  late_expansion: '⚠️',
  contraction:    '🛡️',
};

const THEME_COLOURS: Record<string, string> = {
  Financials:              'bg-blue-500/20 text-blue-300',
  Technology:              'bg-purple-500/20 text-purple-300',
  Defensive:               'bg-green-500/20 text-green-300',
  'Consumer Discretionary': 'bg-orange-500/20 text-orange-300',
  Cyclical:                'bg-yellow-500/20 text-yellow-300',
  Energy:                  'bg-red-500/20 text-red-300',
  'Broad Market':          'bg-cyan-500/20 text-cyan-300',
};

function pct(v: number) {
  return `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`;
}

// ── Subcomponents ─────────────────────────────────────────────────────────────

function CycleCard({ cycle }: { cycle: CycleInfo }) {
  const phaseLabel = cycle.phase.replace('_', ' ').replace(/\b\w/g, c => c.toUpperCase());
  const colour     = PHASE_COLOURS[cycle.phase] ?? 'text-cyan-400';
  const icon       = PHASE_ICONS[cycle.phase]   ?? '📊';

  return (
    <div className="glass-panel rounded-xl p-6 border border-jarvis-primary/30 mb-6">
      <div className="flex items-start justify-between flex-wrap gap-4">
        {/* Phase */}
        <div>
          <div className="text-xs text-jarvis-text-secondary uppercase tracking-widest mb-1">
            Market Cycle Phase
          </div>
          <div className={`text-2xl font-bold ${colour} flex items-center gap-2`}>
            <span>{icon}</span>
            <span>{phaseLabel}</span>
          </div>
          <p className="text-sm text-jarvis-text-secondary mt-2 max-w-lg">{cycle.description}</p>
          <p className="text-xs text-cyan-400/80 mt-1 italic">{cycle.advice}</p>
        </div>

        {/* Nifty stats */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            { label: 'Nifty 50',  value: `₹${cycle.nifty_price.toLocaleString('en-IN')}` },
            { label: '4W Return', value: pct(cycle.nifty_ret_4w),  colour: cycle.nifty_ret_4w  >= 0 ? 'text-green-400' : 'text-red-400' },
            { label: '12W Return', value: pct(cycle.nifty_ret_12w),  colour: cycle.nifty_ret_12w  >= 0 ? 'text-green-400' : 'text-red-400' },
            { label: '26W Return', value: pct(cycle.nifty_ret_26w),  colour: cycle.nifty_ret_26w  >= 0 ? 'text-green-400' : 'text-red-400' },
          ].map(item => (
            <div key={item.label} className="bg-jarvis-primary/5 rounded-lg p-3 text-center min-w-[80px]">
              <div className="text-[10px] text-jarvis-text-secondary uppercase tracking-wider">{item.label}</div>
              <div className={`text-sm font-bold mt-1 ${(item as any).colour ?? 'text-white'}`}>{item.value}</div>
            </div>
          ))}
        </div>
      </div>

      {/* EMA & Confirmation */}
      <div className="mt-4 space-y-2">
        <div className="flex items-center gap-2 text-xs">
          <div className={`w-2 h-2 rounded-full ${cycle.above_ema200 ? 'bg-green-400' : 'bg-red-400'}`} />
          <span className="text-jarvis-text-secondary">
            Nifty is <span className={cycle.above_ema200 ? 'text-green-400' : 'text-red-400'}>
              {cycle.above_ema200 ? 'above' : 'below'}
            </span> EMA200 ({cycle.weeks_above_ema200} weeks persistent)
          </span>
        </div>
        <div className={`text-xs px-2 py-1 rounded inline-block ${
          cycle.confidence === 'HIGH' ? 'bg-green-500/20 text-green-400' : 'bg-yellow-500/20 text-yellow-400'
        }`}>
          Cycle Confidence: {cycle.confidence}
        </div>
      </div>
    </div>
  );
}

function ScoreBar({ label, score, colour }: { label: string; score: number; colour: string }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="text-jarvis-text-secondary w-20 shrink-0">{label}</span>
      <div className="flex-1 bg-white/10 rounded-full h-1.5">
        <div className={`h-1.5 rounded-full ${colour}`} style={{ width: `${Math.round(score * 100)}%` }} />
      </div>
      <span className="text-jarvis-text-secondary w-8 text-right">{Math.round(score * 100)}%</span>
    </div>
  );
}

function SectorCard({ sector, expanded, onToggle }: {
  sector: SectorResult;
  expanded: boolean;
  onToggle: () => void;
}) {
  const sig = SIGNAL_STYLES[sector.signal] ?? SIGNAL_STYLES['N/A'];

  if (sector.data_error) {
    return (
      <div className="glass-panel rounded-xl p-4 border border-white/10 opacity-50">
        <div className="flex items-center justify-between">
          <span className="text-sm text-jarvis-text-secondary">#{sector.rank ?? '–'} {sector.name}</span>
          <span className="text-xs text-red-400">Data unavailable</span>
        </div>
      </div>
    );
  }

  const retColour = (v: number) => v >= 0 ? 'text-green-400' : 'text-red-400';
  const vsColour  = (v: number) => v >= 2 ? 'text-green-400' : v <= -2 ? 'text-red-400' : 'text-yellow-400';

  return (
    <div
      className={`glass-panel rounded-xl border transition-all duration-200 ${sig.border} ${
        sector.rank <= 3 ? 'border-opacity-60' : 'border-opacity-30'
      }`}
    >
      {/* Header row */}
      <div
        className="p-4 cursor-pointer"
        onClick={onToggle}
      >
        <div className="flex items-start gap-3">
          {/* Rank */}
          <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
            sector.rank === 1 ? 'bg-yellow-500/30 text-yellow-300' :
            sector.rank === 2 ? 'bg-gray-400/30 text-gray-300' :
            sector.rank === 3 ? 'bg-orange-500/30 text-orange-300' :
            'bg-white/10 text-jarvis-text-secondary'
          }`}>
            #{sector.rank}
          </div>

          {/* Name + theme */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-semibold text-white">{sector.name}</span>
              <span className={`text-[10px] px-2 py-0.5 rounded-full ${THEME_COLOURS[sector.theme] ?? 'bg-white/10 text-white'}`}>
                {sector.theme}
              </span>
            </div>
            {sector.etf_name && (
              <div className="text-xs text-jarvis-text-secondary mt-0.5">
                ETF: <span className="text-cyan-400">{sector.etf_name}</span>
                {sector.etf && <span className="text-white/40 ml-1">({sector.etf})</span>}
              </div>
            )}
            {!sector.etf && (
              <div className="text-xs text-white/30 mt-0.5">No direct ETF — via sector mutual funds</div>
            )}
          </div>

          {/* Signal badge */}
          <div className={`px-3 py-1 rounded-lg border text-xs font-bold ${sig.bg} ${sig.text} ${sig.border} shrink-0`}>
            {sector.signal}
          </div>

          {/* Chevron */}
          <div className={`text-jarvis-text-secondary transition-transform ${expanded ? 'rotate-180' : ''}`}>▼</div>
        </div>

        {/* Score bar + quick stats */}
        <div className="mt-3 flex items-center gap-4 flex-wrap">
          {/* Total score bar */}
          <div className="flex-1 min-w-[120px]">
            <div className="flex items-center justify-between text-[10px] text-jarvis-text-secondary mb-1">
              <span>Score</span>
              <span className={sig.text}>{Math.round(sector.total_score * 100)}/100</span>
            </div>
            <div className="bg-white/10 rounded-full h-2">
              <div
                className={`h-2 rounded-full ${sig.bg.replace('/20', '/60')}`}
                style={{ width: `${Math.round(sector.total_score * 100)}%` }}
              />
            </div>
          </div>

          {/* Quick stats */}
          <div className="flex gap-3 text-xs flex-wrap">
            <span>
              12W: <span className={retColour(sector.ret_12w)}>{pct(sector.ret_12w)}</span>
              {' '}(<span className={vsColour(sector.ret_12w_vs_nifty)}>{pct(sector.ret_12w_vs_nifty)} vs Nifty</span>)
            </span>
            <span className="text-jarvis-text-secondary">RSI: <span className="text-white">{sector.rsi}</span></span>
            <span className="text-jarvis-text-secondary">ADX: <span className="text-white">{sector.adx}</span></span>
          </div>
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-4 pb-4 border-t border-white/10 pt-3 space-y-4">
          {/* Score breakdown */}
          <div>
            <div className="text-xs text-jarvis-text-secondary uppercase tracking-wider mb-2">Score Breakdown</div>
            <div className="space-y-1.5">
              <ScoreBar label="Momentum" score={sector.momentum_score / 0.20} colour="bg-cyan-400" />
              <ScoreBar label="Technical" score={sector.technical_score / 0.55} colour="bg-blue-400" />
              <ScoreBar label="Cycle Fit" score={sector.cycle_score / 0.25} colour="bg-purple-400" />
            </div>
          </div>

          {/* Returns table */}
          <div>
            <div className="text-xs text-jarvis-text-secondary uppercase tracking-wider mb-2">Weekly Returns vs Nifty</div>
            <div className="grid grid-cols-3 gap-2">
              {[
                { label: '4 Weeks', abs: sector.ret_4w, vs: sector.ret_4w_vs_nifty },
                { label: '12 Weeks', abs: sector.ret_12w, vs: sector.ret_12w_vs_nifty },
                { label: '26 Weeks', abs: sector.ret_26w, vs: sector.ret_26w_vs_nifty },
              ].map(r => (
                <div key={r.label} className="bg-white/5 rounded-lg p-2 text-center">
                  <div className="text-[10px] text-jarvis-text-secondary">{r.label}</div>
                  <div className={`text-sm font-bold ${retColour(r.abs)}`}>{pct(r.abs)}</div>
                  {r.vs !== 0 && <div className={`text-[10px] ${vsColour(r.vs)}`}>{pct(r.vs)} vs N</div>}
                </div>
              ))}
            </div>
          </div>

          {/* Technical indicators (Weekly) */}
          <div>
            <div className="text-xs text-jarvis-text-secondary uppercase tracking-wider mb-2">Weekly Technical</div>
            <div className="flex gap-3 flex-wrap text-xs">
              <span className={sector.ema_aligned ? 'text-green-400' : 'text-yellow-400'}>
                {sector.ema_aligned ? '✓ EMA Aligned (E10>E26>E52)' : '○ EMA Partial'}
              </span>
              <span className={sector.above_e26 ? 'text-green-400' : 'text-red-400'}>
                {sector.above_e26 ? '✓ Above EMA26' : '✗ Below EMA26'}
              </span>
              <span>RSI: <span className={
                sector.rsi >= 50 && sector.rsi <= 65 ? 'text-green-400' :
                sector.rsi > 70 ? 'text-red-400' : 'text-yellow-400'
              }>{sector.rsi}</span></span>
              <span>ADX: <span className={sector.adx > 22 ? 'text-green-400' : 'text-yellow-400'}>{sector.adx}</span></span>
              <span>MACD: <span className={sector.macd_hist > 0 ? 'text-green-400' : 'text-red-400'}>
                {sector.macd_hist > 0 ? '▲ Positive' : '▼ Negative'}
              </span></span>
            </div>
          </div>

          {/* Reasons */}
          {sector.reasons.length > 0 && (
            <div>
              <div className="text-xs text-jarvis-text-secondary uppercase tracking-wider mb-2">Key Factors</div>
              <ul className="space-y-1">
                {sector.reasons.map((r, i) => (
                  <li key={i} className="text-xs text-jarvis-text-secondary flex items-start gap-1.5">
                    <span className="text-cyan-400 mt-0.5">›</span>
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main view ─────────────────────────────────────────────────────────────────

export function SectorAnalysisView() {
  const [result, setResult]     = useState<AnalysisResult | null>(null);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [filter, setFilter]     = useState<'all' | 'buy' | 'etf'>('all');

  const runAnalysis = useCallback(async (force = false) => {
    setLoading(true);
    setError(null);
    try {
      const resp = await api.get<AnalysisResult>(
        `/api/sectors/analysis${force ? '?force=true' : ''}`,
        { timeout: 120000 }
      );
      setResult(resp.data);
      // Auto-expand top 3
      const top3 = resp.data.sectors.slice(0, 3).map(s => s.id);
      setExpanded(new Set(top3));
    } catch (err: any) {
      setError(err.response?.data?.detail ?? err.message ?? 'Analysis failed');
    } finally {
      setLoading(false);
    }
  }, []);

  const toggleExpand = (id: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const filtered = result?.sectors.filter(s => {
    if (filter === 'buy')  return s.signal === 'BUY' || s.signal === 'ACCUMULATE';
    if (filter === 'etf')  return s.etf !== null && !s.data_error;
    return !s.data_error;
  }) ?? [];

  return (
    <div className="p-6 space-y-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Sector & Index Rotation</h1>
          <p className="text-sm text-jarvis-text-secondary mt-1">
            Momentum + Technical + Market Cycle analysis across 11 Indian sectors
          </p>
        </div>

        <div className="flex items-center gap-3">
          {result && (
            <button
              onClick={() => runAnalysis(true)}
              disabled={loading}
              className="px-4 py-2 text-xs rounded-lg border border-jarvis-primary/40 text-jarvis-text-secondary hover:text-jarvis-primary hover:border-jarvis-primary transition-colors disabled:opacity-40"
            >
              Refresh
            </button>
          )}
          <button
            onClick={() => runAnalysis(false)}
            disabled={loading}
            className="px-6 py-2.5 rounded-lg font-semibold text-sm bg-jarvis-primary/20 border border-jarvis-primary text-jarvis-primary hover:bg-jarvis-primary/30 transition-all disabled:opacity-50 flex items-center gap-2"
          >
            {loading ? (
              <>
                <span className="animate-spin">◌</span>
                <span>Analysing 11 sectors…</span>
              </>
            ) : (
              <>
                <span>🔍</span>
                <span>{result ? 'Re-run Analysis' : 'Run Analysis'}</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Loading hint */}
      {loading && (
        <div className="glass-panel rounded-xl p-5 border border-jarvis-primary/20 text-center">
          <div className="text-sm text-jarvis-text-secondary animate-pulse">
            Fetching 400 days of OHLCV data for 11 sector indices from Yahoo Finance…
          </div>
          <div className="text-xs text-white/30 mt-1">This takes ~15–20 seconds</div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="glass-panel rounded-xl p-4 border border-red-500/40 text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Empty state */}
      {!result && !loading && !error && (
        <div className="glass-panel rounded-xl p-10 text-center border border-jarvis-primary/20">
          <div className="text-4xl mb-3">📊</div>
          <div className="text-white font-semibold mb-2">No analysis yet</div>
          <div className="text-sm text-jarvis-text-secondary max-w-sm mx-auto">
            Click "Run Analysis" to score all 11 Indian sector indices using momentum,
            technical, and market cycle factors.
          </div>
        </div>
      )}

      {/* NIFTY GROWSECT 15 REAL-TIME HEATMAP - Always show when NOT loading */}
      {!loading && !error && (
        <div className="mb-8">
          <NiftyGrowsectHeatmap />
        </div>
      )}

      {result && (
        <>
          {/* Divider */}
          <div style={{
            height: '1px',
            background: 'linear-gradient(90deg, transparent, rgba(0,229,255,0.3), transparent)',
            margin: '20px 0 30px 0',
          }} />

          {/* Cycle card */}
          <CycleCard cycle={result.cycle} />

          {/* Top picks banner */}
          {result.top_picks.length > 0 && (
            <div className="glass-panel rounded-xl p-4 border border-cyan-500/30 bg-cyan-500/5">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs text-cyan-400 font-bold uppercase tracking-wider">Top Picks</span>
                {result.top_picks.map(name => (
                  <span key={name} className="text-xs px-3 py-1 rounded-full bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">
                    {name}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Filter tabs + scan time */}
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div className="flex gap-1 bg-white/5 rounded-lg p-1">
              {(['all', 'buy', 'etf'] as const).map(f => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={`px-4 py-1.5 text-xs rounded-md transition-all ${
                    filter === f
                      ? 'bg-jarvis-primary/30 text-jarvis-primary'
                      : 'text-jarvis-text-secondary hover:text-white'
                  }`}
                >
                  {f === 'all' ? 'All Sectors' : f === 'buy' ? 'BUY / ACCUMULATE' : 'ETF Available'}
                </button>
              ))}
            </div>
            <div className="text-xs text-jarvis-text-secondary">
              Scanned {result.scan_time} · {result.elapsed_s}s
            </div>
          </div>

          {/* Sector cards */}
          <div className="space-y-3">
            {filtered.length === 0 && (
              <div className="text-center text-sm text-jarvis-text-secondary py-8">
                No sectors match this filter.
              </div>
            )}
            {filtered.map(sector => (
              <SectorCard
                key={sector.id}
                sector={sector}
                expanded={expanded.has(sector.id)}
                onToggle={() => toggleExpand(sector.id)}
              />
            ))}
          </div>

          {/* Disclaimer */}
          <div className="text-xs text-white/25 text-center pb-4">
            Analysis based on historical price data. Not financial advice. Past sector rotation
            patterns may not repeat. Always do your own research before investing.
          </div>
        </>
      )}
    </div>
  );
}
