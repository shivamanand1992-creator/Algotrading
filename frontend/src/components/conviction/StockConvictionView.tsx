import React, { useState, useCallback, useRef, useEffect } from 'react';
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer,
} from 'recharts';
import { api } from '../../api/client';
import { useBalanceVisibility, maskAmount } from '../../context/BalanceVisibilityContext';

// ── Types ─────────────────────────────────────────────────────────────────────

interface ConvictionInfo {
  score: number;
  action: string;
  action_detail: string;
  why_matters: string[];
  risk_reward: string;
  estimated_fair_value: number;
  upside_pct: number;
}

interface ThesisCase {
  score: number;
  probability: number;
  points: string[];
  fair_value: number;
  trigger: string;
}

interface RedFlag {
  name: string;
  detail: string;
  severity: 'high' | 'medium' | 'low';
  action: string;
}

interface Catalyst {
  date: string;
  event: string;
  probability: number;
  impact_yes_pct: number;
  impact_no_pct: number;
}

interface EntryZone { min: number; max: number; reason: string; allocation?: string; }
interface EntryZones {
  avoid: EntryZone;
  accumulate: EntryZone;
  strong_buy: EntryZone;
}

interface PriceDistribution {
  bear_case_pct: number;   bear_case_range: string;
  base_low_pct: number;    base_range: string;
  bull_pct: number;        bull_range: string;
  extreme_bull_pct: number; extreme_bull_range: string;
}

interface Peer {
  ticker: string; name: string;
  pe: number | null; pb: number | null;
  growth: number | null; roe: number | null;
  market_cap: number | null; current_price: number | null;
}

interface Technical {
  rsi: number; rsi_signal: string; macd_bullish: boolean; bb_position: string;
  sma_20: number | null; sma_50: number | null;
  above_sma20: boolean; above_sma50: boolean | null;
  high_52w: number | null; low_52w: number | null; pct_from_52w_high: number;
}

interface ConvictionResult {
  symbol: string; full_name: string; sector: string | null; industry: string | null;
  current_price: number; market_cap_fmt: string | null;
  trailing_pe: number | null; revenue_growth_pct: number | null; roe_pct: number | null;
  technical: Technical;
  conviction: ConvictionInfo;
  thesis: { bull: ThesisCase; bear: ThesisCase; base: ThesisCase };
  red_flags: RedFlag[]; green_flags: string[];
  catalysts: Catalyst[];
  entry_zones: EntryZones;
  price_distribution: PriceDistribution;
  peers: Peer[];
  analyzed_at: string;
}

interface WatchedStock {
  ticker: string; full_name: string; price: number;
  score: number; action: string; timestamp: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const WATCH_KEY = 'vaayu_conviction_watchlist';

const scoreColor  = (s: number) => s >= 7 ? '#4ade80' : s >= 4 ? '#fbbf24' : '#f87171';
const scoreLabel  = (s: number) => s >= 7 ? 'BUY' : s >= 4 ? 'HOLD / WAIT' : 'AVOID';
const sevColor    = (s: string) => s === 'high' ? '#f87171' : s === 'medium' ? '#fbbf24' : '#a0c4e0';
const INR         = (n: number) =>
  new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(n);

function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ color: 'rgba(0,229,255,0.55)', fontFamily: 'monospace', fontSize: 10, letterSpacing: 3, fontWeight: 700, whiteSpace: 'nowrap' }}>
          {title}
        </span>
        <div style={{ flex: 1, height: 1, background: 'rgba(0,229,255,0.1)' }} />
      </div>
      {subtitle && <div style={{ color: 'rgba(160,196,224,0.35)', fontSize: 10, marginTop: 2 }}>{subtitle}</div>}
    </div>
  );
}

function Card({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{
      background: 'rgba(2,6,18,0.9)',
      border: '1px solid rgba(0,229,255,0.1)',
      borderRadius: 10, padding: 18,
      ...style,
    }}>
      {children}
    </div>
  );
}

// ── Score Ring ────────────────────────────────────────────────────────────────

function ScoreRing({ score }: { score: number }) {
  const color = scoreColor(score);
  const r = 36, circ = 2 * Math.PI * r;
  const arc = (score / 10) * circ;
  return (
    <svg width={92} height={92} viewBox="0 0 92 92" style={{ flexShrink: 0 }}>
      <circle cx={46} cy={46} r={r} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth={8} />
      <circle cx={46} cy={46} r={r} fill="none" stroke={color} strokeWidth={8}
        strokeDasharray={`${arc} ${circ}`} strokeLinecap="round"
        transform="rotate(-90 46 46)"
        style={{ transition: 'stroke-dasharray 0.7s ease' }}
      />
      <text x={46} y={42} textAnchor="middle"
        style={{ fill: color, fontSize: 22, fontWeight: 900, fontFamily: 'monospace' }}>{score}</text>
      <text x={46} y={58} textAnchor="middle"
        style={{ fill: 'rgba(160,196,224,0.4)', fontSize: 10, fontFamily: 'monospace' }}>/10</text>
    </svg>
  );
}

// ── Conviction Card ───────────────────────────────────────────────────────────

function ConvictionCard({ result }: { result: ConvictionResult }) {
  const { balVisible } = useBalanceVisibility();
  const M = (v: string) => maskAmount(v, balVisible);
  const c   = result.conviction;
  const ta  = result.technical;
  const col = scoreColor(c.score);

  return (
    <div style={{
      background: 'rgba(2,6,18,0.95)',
      border: `1px solid ${col}44`,
      borderRadius: 12, padding: 20,
      boxShadow: `0 0 28px ${col}12`,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ color: '#00e5ff', fontFamily: 'monospace', fontWeight: 900, fontSize: 20, letterSpacing: 2 }}>
              {result.symbol}
            </span>
            <span style={{
              background: `${col}22`, border: `1px solid ${col}55`,
              color: col, fontSize: 9, fontFamily: 'monospace', letterSpacing: 2,
              padding: '3px 10px', borderRadius: 20, fontWeight: 700,
            }}>{scoreLabel(c.score)}</span>
          </div>
          <div style={{ color: 'rgba(160,196,224,0.55)', fontSize: 12, marginTop: 4 }}>{result.full_name}</div>
          <div style={{ color: 'rgba(160,196,224,0.3)', fontSize: 10, marginTop: 2 }}>
            {[result.sector, result.industry, result.market_cap_fmt].filter(Boolean).join(' · ')}
          </div>
        </div>
        <ScoreRing score={c.score} />
      </div>

      {/* Key metrics row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginBottom: 16 }}>
        {[
          { label: 'Current Price', value: `₹${result.current_price.toLocaleString('en-IN')}`, color: '#00e5ff', raw: false },
          { label: 'Est. Fair Value', value: M(INR(c.estimated_fair_value)), color: '#a78bfa', raw: false,
            sub: `${c.upside_pct >= 0 ? '+' : ''}${c.upside_pct?.toFixed(1)}% ${c.upside_pct >= 0 ? 'upside' : 'overvalued'}`,
            subColor: c.upside_pct >= 0 ? '#4ade80' : '#f87171' },
          { label: 'Risk / Reward', value: c.risk_reward, color: '#fbbf24', raw: false,
            sub: `RSI ${ta.rsi} · ${ta.rsi_signal}`, subColor: 'rgba(160,196,224,0.4)' },
        ].map(item => (
          <div key={item.label} style={{
            background: 'rgba(0,229,255,0.03)', border: '1px solid rgba(0,229,255,0.09)',
            borderRadius: 8, padding: '10px 14px',
          }}>
            <div style={{ color: 'rgba(160,196,224,0.4)', fontSize: 9, letterSpacing: 2, textTransform: 'uppercase' }}>{item.label}</div>
            <div style={{ color: item.color, fontSize: 17, fontWeight: 900, fontFamily: 'monospace', marginTop: 4 }}>{item.value}</div>
            {item.sub && <div style={{ color: item.subColor, fontSize: 10, marginTop: 3 }}>{item.sub}</div>}
          </div>
        ))}
      </div>

      {/* Action banner */}
      <div style={{
        background: `${col}0f`, border: `1px solid ${col}33`,
        borderRadius: 8, padding: '10px 14px', marginBottom: 14,
        display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
      }}>
        <span style={{ color: col, fontFamily: 'monospace', fontWeight: 900, fontSize: 14, letterSpacing: 1 }}>
          {c.action}
        </span>
        <span style={{ color: 'rgba(160,196,224,0.65)', fontSize: 12 }}>{c.action_detail}</span>
      </div>

      {/* Why it matters */}
      <div style={{ marginBottom: 14 }}>
        <div style={{ color: 'rgba(160,196,224,0.35)', fontSize: 9, letterSpacing: 2, textTransform: 'uppercase', marginBottom: 6 }}>
          WHY IT MATTERS NOW
        </div>
        {c.why_matters?.map((pt, i) => (
          <div key={i} style={{ display: 'flex', gap: 7, marginBottom: 5 }}>
            <span style={{ color: col, fontSize: 9, marginTop: 2, flexShrink: 0 }}>▸</span>
            <span style={{ color: 'rgba(160,196,224,0.75)', fontSize: 12, lineHeight: 1.4 }}>{pt}</span>
          </div>
        ))}
      </div>

      {/* TA quick strip */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 }}>
        {[
          { label: 'MACD', value: ta.macd_bullish ? '▲ Bullish' : '▼ Bearish', color: ta.macd_bullish ? '#4ade80' : '#f87171' },
          { label: 'BB', value: ta.bb_position, color: ta.bb_position?.includes('Above') ? '#f87171' : ta.bb_position?.includes('Below') ? '#4ade80' : 'rgba(160,196,224,0.6)' },
          { label: 'SMA-20', value: ta.above_sma20 ? '▲ Above' : '▼ Below', color: ta.above_sma20 ? '#4ade80' : '#f87171' },
          { label: '52W High', value: `${ta.pct_from_52w_high}%`, color: (ta.pct_from_52w_high ?? 0) > -10 ? '#fbbf24' : 'rgba(160,196,224,0.6)' },
        ].map(item => (
          <div key={item.label} style={{
            background: 'rgba(0,229,255,0.03)', border: '1px solid rgba(0,229,255,0.07)',
            borderRadius: 6, padding: '7px 8px', textAlign: 'center',
          }}>
            <div style={{ color: 'rgba(160,196,224,0.35)', fontSize: 8, letterSpacing: 1, textTransform: 'uppercase' }}>{item.label}</div>
            <div style={{ color: item.color, fontSize: 10, fontFamily: 'monospace', fontWeight: 700, marginTop: 3 }}>{item.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Thesis Scorecard ──────────────────────────────────────────────────────────

function ThesisScorecard({ thesis, currentPrice }: { thesis: ConvictionResult['thesis']; currentPrice: number }) {
  const { balVisible } = useBalanceVisibility();
  const M = (v: string) => maskAmount(v, balVisible);

  const cases = [
    { label: '🐂 BULL CASE', data: thesis.bull, color: '#4ade80' },
    { label: '📊 BASE CASE', data: thesis.base, color: '#00e5ff' },
    { label: '🐻 BEAR CASE', data: thesis.bear, color: '#f87171' },
  ] as const;

  return (
    <div>
      <SectionHeader title="THESIS SCORECARD" subtitle="Three competing scenarios — probabilities must sum to 100%" />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
        {cases.map(({ label, data, color }) => {
          const upPct = data.fair_value ? ((data.fair_value - currentPrice) / currentPrice * 100) : null;
          return (
            <Card key={label} style={{ border: `1px solid ${color}33` }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                <span style={{ color, fontFamily: 'monospace', fontWeight: 700, fontSize: 11, letterSpacing: 1 }}>{label}</span>
                <span style={{
                  background: `${color}22`, color, fontFamily: 'monospace',
                  fontSize: 9, padding: '2px 8px', borderRadius: 12, fontWeight: 700,
                }}>{data.probability}%</span>
              </div>
              <div style={{ height: 3, background: 'rgba(255,255,255,0.06)', borderRadius: 2, marginBottom: 14 }}>
                <div style={{ height: '100%', width: `${data.probability}%`, background: color, borderRadius: 2, transition: 'width 0.7s ease' }} />
              </div>
              <div style={{ marginBottom: 12 }}>
                {data.points?.map((pt, i) => (
                  <div key={i} style={{ display: 'flex', gap: 6, marginBottom: 5 }}>
                    <span style={{ color, fontSize: 9, flexShrink: 0, marginTop: 2 }}>▸</span>
                    <span style={{ color: 'rgba(160,196,224,0.7)', fontSize: 11, lineHeight: 1.4 }}>{pt}</span>
                  </div>
                ))}
              </div>
              <div style={{ borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
                  <div>
                    <div style={{ color: 'rgba(160,196,224,0.35)', fontSize: 8, letterSpacing: 1 }}>FAIR VALUE</div>
                    <div style={{ color, fontFamily: 'monospace', fontWeight: 700, fontSize: 14, marginTop: 3 }}>
                      {M(INR(data.fair_value))}
                    </div>
                    {upPct !== null && (
                      <div style={{ color: upPct >= 0 ? '#4ade80' : '#f87171', fontSize: 10, marginTop: 2 }}>
                        {upPct >= 0 ? '+' : ''}{upPct.toFixed(1)}%
                      </div>
                    )}
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ color: 'rgba(160,196,224,0.35)', fontSize: 8, letterSpacing: 1 }}>SCORE</div>
                    <div style={{ color, fontFamily: 'monospace', fontWeight: 900, fontSize: 20, marginTop: 3 }}>{data.score}</div>
                  </div>
                </div>
                <div style={{ color: 'rgba(160,196,224,0.4)', fontSize: 10, marginTop: 10, fontStyle: 'italic', lineHeight: 1.4 }}>
                  {data.trigger}
                </div>
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

// ── Red Flags + Green Flags ───────────────────────────────────────────────────

function SignalDetector({ redFlags, greenFlags }: { redFlags: RedFlag[]; greenFlags: string[] }) {
  return (
    <div>
      <SectionHeader title="SIGNAL DETECTOR" subtitle="Auto-detected risks and strengths" />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <Card style={{ border: '1px solid rgba(248,113,113,0.2)' }}>
          <div style={{ color: '#f87171', fontFamily: 'monospace', fontWeight: 700, fontSize: 10, letterSpacing: 2, marginBottom: 14 }}>
            🚨 RED FLAGS ({redFlags.length})
          </div>
          {redFlags.length === 0
            ? <div style={{ color: 'rgba(160,196,224,0.35)', fontSize: 11 }}>No significant red flags detected.</div>
            : redFlags.map((flag, i) => (
              <div key={i} style={{ borderLeft: `3px solid ${sevColor(flag.severity)}`, paddingLeft: 10, marginBottom: 14 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 }}>
                  <span style={{ color: 'rgba(160,196,224,0.85)', fontSize: 12, fontWeight: 600 }}>{flag.name}</span>
                  <span style={{
                    background: `${sevColor(flag.severity)}22`, color: sevColor(flag.severity),
                    fontSize: 8, fontFamily: 'monospace', letterSpacing: 1, padding: '1px 6px', borderRadius: 8,
                  }}>{flag.severity.toUpperCase()}</span>
                </div>
                <div style={{ color: 'rgba(160,196,224,0.55)', fontSize: 11, lineHeight: 1.4 }}>{flag.detail}</div>
                <div style={{ color: '#fbbf24', fontSize: 10, marginTop: 4 }}>→ {flag.action}</div>
              </div>
            ))}
        </Card>

        <Card style={{ border: '1px solid rgba(74,222,128,0.2)' }}>
          <div style={{ color: '#4ade80', fontFamily: 'monospace', fontWeight: 700, fontSize: 10, letterSpacing: 2, marginBottom: 14 }}>
            ✅ GREEN FLAGS ({greenFlags.length})
          </div>
          {greenFlags.length === 0
            ? <div style={{ color: 'rgba(160,196,224,0.35)', fontSize: 11 }}>No significant green flags detected.</div>
            : greenFlags.map((flag, i) => (
              <div key={i} style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
                <span style={{ color: '#4ade80', fontSize: 9, marginTop: 2, flexShrink: 0 }}>▸</span>
                <span style={{ color: 'rgba(160,196,224,0.75)', fontSize: 12, lineHeight: 1.4 }}>{flag}</span>
              </div>
            ))}
        </Card>
      </div>
    </div>
  );
}

// ── Catalyst Timeline ─────────────────────────────────────────────────────────

function CatalystTimeline({ catalysts }: { catalysts: Catalyst[] }) {
  if (!catalysts?.length) return null;
  return (
    <div>
      <SectionHeader title="CATALYST TRACKER" subtitle="Key events & impact (next 12 months)" />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 10 }}>
        {catalysts.map((c, i) => {
          const probColor = c.probability >= 70 ? '#4ade80' : c.probability >= 40 ? '#fbbf24' : '#f87171';
          return (
            <Card key={i}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <span style={{ color: '#00e5ff', fontFamily: 'monospace', fontSize: 10, fontWeight: 700, letterSpacing: 1 }}>
                  📅 {c.date}
                </span>
                <span style={{ color: probColor, fontFamily: 'monospace', fontSize: 12, fontWeight: 700 }}>
                  {c.probability}%
                </span>
              </div>
              <div style={{ color: 'rgba(160,196,224,0.8)', fontSize: 12, lineHeight: 1.4, marginBottom: 10 }}>{c.event}</div>
              <div style={{ height: 4, background: 'rgba(255,255,255,0.05)', borderRadius: 2, marginBottom: 10 }}>
                <div style={{ height: '100%', width: `${c.probability}%`, background: probColor, borderRadius: 2, transition: 'width 0.7s ease' }} />
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: '#4ade80', fontSize: 10, fontFamily: 'monospace' }}>YES: +{c.impact_yes_pct}%</span>
                <span style={{ color: '#f87171', fontSize: 10, fontFamily: 'monospace' }}>NO: {c.impact_no_pct}%</span>
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

// ── Entry Zones ───────────────────────────────────────────────────────────────

function EntryZonesPanel({ zones, currentPrice }: { zones: EntryZones; currentPrice: number }) {
  const { balVisible } = useBalanceVisibility();
  const M = (v: string) => maskAmount(v, balVisible);

  const allMin = zones.strong_buy?.min ?? currentPrice * 0.5;
  const allMax = zones.avoid?.max ?? currentPrice * 1.3;
  const range  = allMax - allMin || 1;
  const toPct  = (v: number) => Math.max(0, Math.min(100, ((v - allMin) / range) * 100));
  const curPct = toPct(currentPrice);

  const zoneConfig = [
    { z: zones.avoid,       color: '#f87171', label: '🔴 AVOID ZONE',    defaultReason: 'Risk exceeds reward at current levels' },
    { z: zones.accumulate,  color: '#fbbf24', label: '🟡 ACCUMULATE',     defaultReason: 'Risk/reward becomes attractive' },
    { z: zones.strong_buy,  color: '#4ade80', label: '🟢 STRONG BUY',     defaultReason: 'Exceptional entry (panic scenario)' },
  ];

  return (
    <Card>
      <div style={{ color: 'rgba(160,196,224,0.4)', fontSize: 9, letterSpacing: 2, textTransform: 'uppercase', marginBottom: 16 }}>
        ENTRY / EXIT ZONES
      </div>

      {/* Visual price bar */}
      <div style={{ position: 'relative', height: 24, background: 'rgba(255,255,255,0.04)', borderRadius: 6, marginBottom: 28, overflow: 'visible' }}>
        {zones.strong_buy && <div style={{ position: 'absolute', left: `${toPct(zones.strong_buy.min)}%`, width: `${toPct(zones.strong_buy.max) - toPct(zones.strong_buy.min)}%`, height: '100%', background: 'rgba(74,222,128,0.22)', borderRadius: 4 }} />}
        {zones.accumulate && <div style={{ position: 'absolute', left: `${toPct(zones.accumulate.min)}%`, width: `${toPct(zones.accumulate.max) - toPct(zones.accumulate.min)}%`, height: '100%', background: 'rgba(251,191,36,0.22)', borderRadius: 4 }} />}
        {zones.avoid && <div style={{ position: 'absolute', left: `${toPct(zones.avoid.min)}%`, width: `${toPct(zones.avoid.max) - toPct(zones.avoid.min)}%`, height: '100%', background: 'rgba(248,113,113,0.22)', borderRadius: 4 }} />}

        {/* Current price pin */}
        <div style={{ position: 'absolute', left: `${curPct}%`, top: -5, bottom: -5, width: 2, background: '#00e5ff', boxShadow: '0 0 8px rgba(0,229,255,0.7)' }} />
        <div style={{ position: 'absolute', left: `${curPct}%`, top: -22, transform: 'translateX(-50%)', color: '#00e5ff', fontSize: 9, fontFamily: 'monospace', whiteSpace: 'nowrap' }}>▼ NOW</div>
      </div>

      {/* Zone details */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {zoneConfig.map(({ z, color, label, defaultReason }) => z && (
          <div key={label} style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            border: `1px solid ${color}33`, borderRadius: 8, padding: '10px 14px', gap: 10, flexWrap: 'wrap',
          }}>
            <div>
              <div style={{ color, fontFamily: 'monospace', fontWeight: 700, fontSize: 11 }}>{label}</div>
              <div style={{ color: 'rgba(160,196,224,0.45)', fontSize: 10, marginTop: 2 }}>{z.reason || defaultReason}</div>
              {z.allocation && <div style={{ color: 'rgba(160,196,224,0.4)', fontSize: 10, marginTop: 1 }}>Position: {z.allocation}</div>}
            </div>
            <div style={{ color, fontFamily: 'monospace', fontWeight: 700, fontSize: 13, textAlign: 'right' }}>
              {M(`${INR(z.min)} – ${INR(z.max)}`)}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

// ── Price Distribution ────────────────────────────────────────────────────────

function PriceDistributionPanel({ dist }: { dist: PriceDistribution }) {
  const bars = [
    { label: dist.bear_case_range,    pct: dist.bear_case_pct,    color: '#f87171' },
    { label: dist.base_range,         pct: dist.base_low_pct,     color: '#fbbf24' },
    { label: dist.bull_range,         pct: dist.bull_pct,         color: '#4ade80' },
    { label: dist.extreme_bull_range, pct: dist.extreme_bull_pct, color: '#a78bfa' },
  ];
  return (
    <Card>
      <div style={{ color: 'rgba(160,196,224,0.4)', fontSize: 9, letterSpacing: 2, textTransform: 'uppercase', marginBottom: 14 }}>
        PRICE DISTRIBUTION · 12 MONTHS
      </div>
      {bars.map((b, i) => (
        <div key={i} style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ color: 'rgba(160,196,224,0.65)', fontSize: 11 }}>{b.label}</span>
            <span style={{ color: b.color, fontFamily: 'monospace', fontSize: 11, fontWeight: 700 }}>{b.pct}%</span>
          </div>
          <div style={{ height: 5, background: 'rgba(255,255,255,0.05)', borderRadius: 3 }}>
            <div style={{ height: '100%', width: `${b.pct}%`, background: b.color, borderRadius: 3, transition: 'width 0.7s ease' }} />
          </div>
        </div>
      ))}
    </Card>
  );
}

// ── Peer Scatter Plot ─────────────────────────────────────────────────────────

function PeerScatterPlot({ peers, mainSymbol, mainPE, mainGrowth }: {
  peers: Peer[]; mainSymbol: string; mainPE: number | null; mainGrowth: number | null;
}) {
  const allPoints = [
    ...(mainPE != null && mainGrowth != null
      ? [{ ticker: mainSymbol, pe: mainPE, growth: mainGrowth, isMain: true }] : []),
    ...peers
      .filter(p => p.pe != null && p.growth != null)
      .map(p => ({ ticker: p.ticker, pe: p.pe!, growth: p.growth!, isMain: false })),
  ];

  if (allPoints.length < 2) return (
    <div style={{ color: 'rgba(160,196,224,0.3)', fontSize: 11, textAlign: 'center', padding: '30px 0' }}>
      Not enough peer data to render scatter plot.
    </div>
  );

  const CustomDot = (props: any) => {
    const { cx, cy, payload } = props;
    const color = payload.isMain ? '#00e5ff' : '#a78bfa';
    const r = payload.isMain ? 10 : 7;
    return (
      <g>
        <circle cx={cx} cy={cy} r={r} fill={`${color}28`} stroke={color} strokeWidth={payload.isMain ? 2.5 : 1.5} />
        <text x={cx} y={cy - r - 4} textAnchor="middle"
          style={{ fill: color, fontSize: 9, fontFamily: 'monospace', fontWeight: payload.isMain ? 700 : 400 }}>
          {payload.ticker}
        </text>
      </g>
    );
  };

  const TooltipContent = ({ active, payload }: any) => {
    if (!active || !payload?.length) return null;
    const d = payload[0]?.payload;
    return (
      <div style={{ background: 'rgba(2,6,18,0.96)', border: '1px solid rgba(0,229,255,0.2)', borderRadius: 8, padding: '8px 12px' }}>
        <div style={{ color: d.isMain ? '#00e5ff' : '#a78bfa', fontFamily: 'monospace', fontWeight: 700, fontSize: 12 }}>{d.ticker}</div>
        <div style={{ color: 'rgba(160,196,224,0.7)', fontSize: 11, marginTop: 4 }}>P/E: {d.pe?.toFixed(1) ?? 'N/A'}</div>
        <div style={{ color: 'rgba(160,196,224,0.7)', fontSize: 11 }}>Growth: {d.growth?.toFixed(1) ?? 'N/A'}%</div>
      </div>
    );
  };

  return (
    <div style={{ height: 280 }}>
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 24, right: 16, bottom: 24, left: 16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,229,255,0.05)" />
          <XAxis type="number" dataKey="pe" name="P/E"
            tick={{ fill: 'rgba(160,196,224,0.4)', fontSize: 9, fontFamily: 'monospace' }}
            label={{ value: 'P/E Ratio', position: 'insideBottom', offset: -12, style: { fill: 'rgba(160,196,224,0.3)', fontSize: 9 } }}
          />
          <YAxis type="number" dataKey="growth" name="Growth %"
            tick={{ fill: 'rgba(160,196,224,0.4)', fontSize: 9, fontFamily: 'monospace' }}
            label={{ value: 'Growth %', angle: -90, position: 'insideLeft', style: { fill: 'rgba(160,196,224,0.3)', fontSize: 9 } }}
          />
          <Tooltip content={<TooltipContent />} />
          <Scatter data={allPoints} shape={<CustomDot />} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Peer League Table ─────────────────────────────────────────────────────────

function PeerLeagueTable({ peers, mainSymbol, mainPE, mainGrowth, mainROE }: {
  peers: Peer[]; mainSymbol: string;
  mainPE: number | null; mainGrowth: number | null; mainROE: number | null;
}) {
  const [sortBy, setSortBy] = useState<'pe' | 'growth' | 'roe'>('growth');

  const rows = [
    { ticker: mainSymbol, name: mainSymbol, pe: mainPE, growth: mainGrowth, roe: mainROE, isMain: true },
    ...peers.map(p => ({ ...p, isMain: false })),
  ];

  const sorted = [...rows].sort((a, b) => {
    if (sortBy === 'pe')     return (a.pe     ?? 9999) - (b.pe     ?? 9999);
    if (sortBy === 'growth') return (b.growth ?? -999) - (a.growth ?? -999);
    return                          (b.roe    ?? -999) - (a.roe    ?? -999);
  });

  const medal = (i: number) => i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : `${i + 1}.`;

  const SortBtn = ({ id, label }: { id: typeof sortBy; label: string }) => (
    <button onClick={() => setSortBy(id)} style={{
      background: sortBy === id ? 'rgba(0,229,255,0.1)' : 'transparent',
      border: `1px solid ${sortBy === id ? 'rgba(0,229,255,0.4)' : 'rgba(0,229,255,0.15)'}`,
      color: sortBy === id ? '#00e5ff' : 'rgba(160,196,224,0.4)',
      padding: '3px 10px', borderRadius: 4, fontSize: 9,
      fontFamily: 'monospace', letterSpacing: 1, cursor: 'pointer',
    }}>{label}</button>
  );

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <div style={{ color: 'rgba(160,196,224,0.35)', fontSize: 9, letterSpacing: 2, textTransform: 'uppercase' }}>PEER RANKING</div>
        <div style={{ display: 'flex', gap: 6 }}>
          <SortBtn id="growth" label="GROWTH" />
          <SortBtn id="pe"     label="P/E"    />
          <SortBtn id="roe"    label="ROE"    />
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {sorted.map((row, i) => (
          <div key={row.ticker} style={{
            display: 'grid', gridTemplateColumns: '28px 1fr 70px 70px 70px',
            alignItems: 'center', gap: 8,
            background: row.isMain ? 'rgba(0,229,255,0.06)' : 'rgba(0,229,255,0.02)',
            border: `1px solid ${row.isMain ? 'rgba(0,229,255,0.25)' : 'rgba(0,229,255,0.07)'}`,
            borderRadius: 8, padding: '10px 14px',
          }}>
            <div style={{ fontSize: 12 }}>{medal(i)}</div>
            <div>
              <div style={{ color: row.isMain ? '#00e5ff' : 'rgba(160,196,224,0.8)', fontFamily: 'monospace', fontWeight: row.isMain ? 700 : 400, fontSize: 12 }}>
                {row.ticker}
              </div>
              {!row.isMain && (
                <div style={{ color: 'rgba(160,196,224,0.3)', fontSize: 9, marginTop: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {(row as Peer).name}
                </div>
              )}
            </div>
            {[
              { label: 'P/E', val: row.pe?.toFixed(1), highlight: false },
              { label: 'GROWTH', val: row.growth != null ? `${row.growth.toFixed(1)}%` : '—', highlight: (row.growth ?? 0) > 20 },
              { label: 'ROE', val: row.roe != null ? `${row.roe.toFixed(1)}%` : '—', highlight: (row.roe ?? 0) > 15 },
            ].map(col => (
              <div key={col.label} style={{ textAlign: 'right' }}>
                <div style={{ color: 'rgba(160,196,224,0.3)', fontSize: 8, letterSpacing: 1 }}>{col.label}</div>
                <div style={{ color: col.highlight ? '#4ade80' : 'rgba(160,196,224,0.7)', fontFamily: 'monospace', fontSize: 11, marginTop: 2 }}>
                  {col.val ?? '—'}
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Watch List Pills ──────────────────────────────────────────────────────────

function WatchListPills({ onSelect, refreshKey }: { onSelect: (t: string) => void; refreshKey: number }) {
  const [list, setList] = useState<WatchedStock[]>([]);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(WATCH_KEY);
      if (saved) setList(JSON.parse(saved));
    } catch {}
  }, [refreshKey]);

  const remove = (ticker: string) => {
    const updated = list.filter(s => s.ticker !== ticker);
    setList(updated);
    localStorage.setItem(WATCH_KEY, JSON.stringify(updated));
  };

  if (!list.length) return null;

  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ color: 'rgba(160,196,224,0.35)', fontSize: 9, letterSpacing: 2, textTransform: 'uppercase', marginBottom: 7 }}>RECENT WATCHLIST</div>
      <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap' }}>
        {list.slice(0, 10).map(s => {
          const col = scoreColor(s.score);
          return (
            <div key={s.ticker} style={{
              display: 'flex', alignItems: 'center', gap: 6,
              background: `${col}0f`, border: `1px solid ${col}33`,
              borderRadius: 20, padding: '4px 10px 4px 12px',
            }}>
              <span onClick={() => onSelect(s.ticker)} style={{ color: col, fontFamily: 'monospace', fontSize: 11, fontWeight: 700, cursor: 'pointer' }}>
                {s.ticker}
              </span>
              <span onClick={() => onSelect(s.ticker)} style={{ color: 'rgba(160,196,224,0.45)', fontSize: 10, cursor: 'pointer' }}>
                {s.score}/10
              </span>
              <button onClick={() => remove(s.ticker)} style={{
                background: 'transparent', border: 'none', color: 'rgba(160,196,224,0.3)',
                cursor: 'pointer', padding: 0, fontSize: 11, lineHeight: 1,
              }}>×</button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Main View ─────────────────────────────────────────────────────────────────

export function StockConvictionView() {
  const [ticker,     setTicker]     = useState('');
  const [loading,    setLoading]    = useState(false);
  const [result,     setResult]     = useState<ConvictionResult | null>(null);
  const [error,      setError]      = useState<string | null>(null);
  const [watchKey,   setWatchKey]   = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const analyze = useCallback(async (sym?: string) => {
    const t = (sym ?? ticker).trim().toUpperCase();
    if (!t) return;
    if (sym) setTicker(sym);
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const res = await api.post('/api/stocks/conviction', { ticker: t });
      const data = res.data as ConvictionResult;
      setResult(data);

      // Persist to watchlist
      try {
        const saved = localStorage.getItem(WATCH_KEY);
        const list: WatchedStock[] = saved ? JSON.parse(saved) : [];
        const entry: WatchedStock = {
          ticker: data.symbol,
          full_name: data.full_name,
          price: data.current_price,
          score: data.conviction?.score ?? 5,
          action: data.conviction?.action ?? '—',
          timestamp: new Date().toISOString(),
        };
        const updated = [entry, ...list.filter(s => s.ticker !== data.symbol)].slice(0, 20);
        localStorage.setItem(WATCH_KEY, JSON.stringify(updated));
        setWatchKey(k => k + 1);
      } catch {}
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? 'Analysis failed — check the ticker and try again.');
    } finally {
      setLoading(false);
    }
  }, [ticker]);

  const handleKey = (e: React.KeyboardEvent) => { if (e.key === 'Enter') analyze(); };

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', fontFamily: "'Courier New', monospace" }}>

      {/* Page header */}
      <div style={{ marginBottom: 22 }}>
        <div style={{ color: '#00e5ff', fontSize: 13, letterSpacing: 4, fontWeight: 900, textTransform: 'uppercase', marginBottom: 4 }}>
          ⊛ STOCK CONVICTION ENGINE
        </div>
        <div style={{ color: 'rgba(160,196,224,0.35)', fontSize: 11 }}>
          Enter any NSE ticker — get instant conviction score, thesis, red flags, entry zones and peer comparison
        </div>
      </div>

      {/* Watchlist pills */}
      <WatchListPills onSelect={(t) => analyze(t)} refreshKey={watchKey} />

      {/* Search */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 28 }}>
        <input
          ref={inputRef}
          value={ticker}
          onChange={e => setTicker(e.target.value.toUpperCase())}
          onKeyDown={handleKey}
          placeholder="e.g. SOLARINDS  HDFCBANK  RELIANCE  INFY"
          disabled={loading}
          style={{
            flex: 1,
            background: 'rgba(0,229,255,0.04)', border: '1px solid rgba(0,229,255,0.2)',
            borderRadius: 6, padding: '11px 14px',
            color: '#00e5ff', fontFamily: "'Courier New', monospace", fontSize: 13,
            letterSpacing: 1, outline: 'none',
          }}
        />
        <button
          onClick={() => analyze()}
          disabled={loading || !ticker.trim()}
          style={{
            background: loading ? 'rgba(0,229,255,0.03)' : 'rgba(0,229,255,0.1)',
            border: '1px solid rgba(0,229,255,0.3)',
            color: loading ? 'rgba(0,229,255,0.35)' : '#00e5ff',
            padding: '11px 26px', borderRadius: 6,
            cursor: loading || !ticker.trim() ? 'not-allowed' : 'pointer',
            fontFamily: "'Courier New', monospace", fontSize: 11, letterSpacing: 3, fontWeight: 700,
            transition: 'all 0.2s', whiteSpace: 'nowrap',
          }}
        >
          {loading ? '⟳ ANALYSING…' : '⊛ ANALYSE'}
        </button>
      </div>

      {/* Loading */}
      {loading && (
        <div style={{
          background: 'rgba(2,6,18,0.9)', border: '1px solid rgba(0,229,255,0.1)',
          borderRadius: 12, padding: '44px 24px', textAlign: 'center',
        }}>
          <div style={{ fontSize: 36, marginBottom: 14 }}>🔍</div>
          <div style={{ color: '#00e5ff', fontSize: 13, letterSpacing: 4, marginBottom: 10 }}>ANALYSING {ticker}…</div>
          <div style={{ color: 'rgba(160,196,224,0.4)', fontSize: 11, lineHeight: 1.7 }}>
            Fetching 1 year of price data · Computing RSI / MACD / Bollinger Bands<br />
            Fetching fundamentals · Generating AI conviction thesis
          </div>
          <div style={{ marginTop: 20, height: 2, background: 'rgba(0,229,255,0.07)', borderRadius: 1, overflow: 'hidden' }}>
            <div style={{
              height: '100%', width: '35%', background: 'linear-gradient(90deg, transparent, rgba(0,229,255,0.5), transparent)',
              animation: 'scan-loading 1.8s ease-in-out infinite',
            }} />
          </div>
          <style>{`@keyframes scan-loading { 0%{transform:translateX(-200%)} 100%{transform:translateX(400%)} }`}</style>
        </div>
      )}

      {/* Error */}
      {error && !loading && (
        <div style={{
          background: 'rgba(248,113,113,0.05)', border: '1px solid rgba(248,113,113,0.3)',
          borderRadius: 8, padding: '14px 18px', color: '#f87171', fontSize: 12,
        }}>
          ⚠ {error}
        </div>
      )}

      {/* Results */}
      {result && !loading && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>

          {/* 1. Conviction card */}
          <ConvictionCard result={result} />

          {/* 2. Thesis */}
          {result.thesis && (
            <ThesisScorecard thesis={result.thesis} currentPrice={result.current_price} />
          )}

          {/* 3. Signals */}
          <SignalDetector redFlags={result.red_flags ?? []} greenFlags={result.green_flags ?? []} />

          {/* 4. Catalysts */}
          {result.catalysts?.length > 0 && <CatalystTimeline catalysts={result.catalysts} />}

          {/* 5. Entry zones + price distribution */}
          {result.entry_zones && (
            <div>
              <SectionHeader title="ENTRY / EXIT ZONES" subtitle="Price zones with risk/reward context" />
              <div style={{ display: 'grid', gridTemplateColumns: '3fr 2fr', gap: 14 }}>
                <EntryZonesPanel zones={result.entry_zones} currentPrice={result.current_price} />
                {result.price_distribution && <PriceDistributionPanel dist={result.price_distribution} />}
              </div>
            </div>
          )}

          {/* 6. Peer comparison */}
          {result.peers?.length > 0 && (
            <div>
              <SectionHeader title="PEER COMPARISON" subtitle="Valuation vs growth — cyan dot = this stock, purple = peers" />
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
                <Card>
                  <PeerScatterPlot
                    peers={result.peers}
                    mainSymbol={result.symbol}
                    mainPE={result.trailing_pe}
                    mainGrowth={result.revenue_growth_pct}
                  />
                </Card>
                <PeerLeagueTable
                  peers={result.peers}
                  mainSymbol={result.symbol}
                  mainPE={result.trailing_pe}
                  mainGrowth={result.revenue_growth_pct}
                  mainROE={result.roe_pct}
                />
              </div>
            </div>
          )}

          {/* Footer */}
          <div style={{ color: 'rgba(160,196,224,0.2)', fontSize: 9, textAlign: 'center', letterSpacing: 1, paddingBottom: 8 }}>
            Analysis generated {result.analyzed_at} · Powered by Claude AI + yfinance · 2h cache · Not financial advice
          </div>
        </div>
      )}
    </div>
  );
}
