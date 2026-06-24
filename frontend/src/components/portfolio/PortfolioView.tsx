import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../../api/client';
import { useBalanceVisibility, maskAmount } from '../../context/BalanceVisibilityContext';

// ── Types ────────────────────────────────────────────────────────────────────

interface Holding {
  symbol: string;
  name: string;
  isin: string;
  qty: number;
  avg_price: number;
  current_price: number;
  invested_value: number;
  market_value: number;
  pnl: number;
  pnl_pct: number;
  token: string;
  exchange: string;
  instrument_type: string;
}

interface PortfolioData {
  holdings: Holding[];
  total_invested: number;
  total_market_value: number;
  total_pnl: number;
  total_pnl_pct: number;
  last_sync: string | null;
}

interface TAData {
  current_price?: number;
  rsi?: number;
  rsi_signal?: string;
  macd?: number;
  macd_signal?: number;
  macd_histogram?: number;
  macd_bullish?: boolean;
  bb_upper?: number;
  bb_lower?: number;
  bb_mid?: number;
  price_vs_bb?: string;
  sma_20?: number;
  sma_50?: number | null;
  ema_20?: number;
  above_sma20?: boolean;
  above_sma50?: boolean | null;
  high_52w?: number;
  low_52w?: number;
  pct_from_52w_high?: number;
  avg_volume_20d?: number;
  last_volume?: number;
  error?: string;
}

interface FAData {
  market_cap_fmt?: string | null;
  trailing_pe?: number | null;
  forward_pe?: number | null;
  price_to_book?: number | null;
  dividend_yield_pct?: number | null;
  roe_pct?: number | null;
  revenue_growth_pct?: number | null;
  earnings_growth_pct?: number | null;
  debt_to_equity?: number | null;
  current_ratio?: number | null;
  profit_margin_pct?: number | null;
  sector?: string | null;
  industry?: string | null;
  full_name?: string;
  error?: string;
}

interface AIData {
  recommendation: 'HOLD' | 'ADD MORE' | 'SELL';
  score: number;
  summary: string;
  technical_verdict: string;
  fundamental_verdict: string;
  key_risks: string[];
  key_positives: string[];
}

interface AnalysisData {
  symbol: string;
  technical: TAData;
  fundamental: FAData;
  ai: AIData;
  analyzed_at: string;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const INR = (n: number) =>
  new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(n);

const num = (n: number | null | undefined, d = 2): string =>
  n != null ? n.toFixed(d) : 'N/A';

const pnlCol  = (v: number) => (v >= 0 ? '#4ade80' : '#f87171');
const scoreCol = (s: number) => (s >= 8 ? '#4ade80' : s >= 6 ? '#a3e635' : s >= 4 ? '#facc15' : '#f87171');
const recCol   = (r: string) =>
  r === 'ADD MORE' ? '#4ade80' : r === 'SELL' ? '#f87171' : '#facc15';

// ── Sub-components ───────────────────────────────────────────────────────────

function MetricRow({
  label, value, note, noteColor,
}: {
  label: string; value: string; note?: string; noteColor?: string;
}) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '4px 0', borderBottom: '1px solid rgba(0,229,255,0.05)',
    }}>
      <span style={{ color: 'rgba(160,196,224,0.5)', fontSize: 10 }}>{label}</span>
      <div style={{ textAlign: 'right' }}>
        <span style={{ color: noteColor ?? '#e2e8f0', fontFamily: "'Courier New', monospace", fontSize: 11 }}>{value}</span>
        {note && (
          <span style={{ color: noteColor ?? 'rgba(160,196,224,0.5)', fontSize: 9, marginLeft: 5 }}>{note}</span>
        )}
      </div>
    </div>
  );
}

function AnalysisPanel({ analysis }: { analysis: AnalysisData }) {
  const { technical: ta, fundamental: fa, ai } = analysis;
  const rc = recCol(ai.recommendation);
  const sc = scoreCol(ai.score);

  return (
    <div>
      {/* AI banner */}
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', marginBottom: 20 }}>
        {/* Score ring */}
        <div style={{
          width: 64, height: 64, borderRadius: '50%',
          border: `2px solid ${sc}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexShrink: 0, boxShadow: `0 0 18px ${sc}40`,
        }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ color: sc, fontSize: 22, fontWeight: 900, fontFamily: "'Courier New', monospace", lineHeight: 1 }}>{ai.score}</div>
            <div style={{ color: 'rgba(160,196,224,0.4)', fontSize: 8, letterSpacing: 1 }}>/10</div>
          </div>
        </div>

        {/* Recommendation + summary */}
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <span style={{
              background: `${rc}22`, border: `1px solid ${rc}`, color: rc,
              fontSize: 11, fontWeight: 700, letterSpacing: 2,
              padding: '3px 10px', borderRadius: 4,
              fontFamily: "'Courier New', monospace",
            }}>
              {ai.recommendation}
            </span>
            <span style={{ color: 'rgba(160,196,224,0.35)', fontSize: 10 }}>
              analysed {analysis.analyzed_at}
            </span>
          </div>
          <p style={{ margin: 0, color: 'rgba(200,220,240,0.8)', fontSize: 12, lineHeight: 1.65 }}>
            {ai.summary}
          </p>
        </div>
      </div>

      {/* TA + FA columns */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
        {/* Technical */}
        <div style={{
          background: 'rgba(0,229,255,0.03)', border: '1px solid rgba(0,229,255,0.1)',
          borderRadius: 8, padding: 14,
        }}>
          <div style={{ color: '#00e5ff', fontSize: 10, letterSpacing: 3, textTransform: 'uppercase', marginBottom: 8, fontFamily: "'Courier New', monospace" }}>
            Technical
          </div>
          {ta.error ? (
            <div style={{ color: 'rgba(160,196,224,0.4)', fontSize: 11 }}>Unavailable: {ta.error}</div>
          ) : (
            <>
              <div style={{ color: 'rgba(200,220,240,0.6)', fontSize: 11, fontStyle: 'italic', marginBottom: 8, lineHeight: 1.5 }}>
                {ai.technical_verdict}
              </div>
              <MetricRow
                label="RSI (14)" value={num(ta.rsi, 1)}
                note={ta.rsi_signal}
                noteColor={ta.rsi_signal === 'Oversold' ? '#4ade80' : ta.rsi_signal === 'Overbought' ? '#f87171' : undefined}
              />
              <MetricRow
                label="MACD hist." value={num(ta.macd_histogram)}
                note={ta.macd_bullish ? 'Bullish ▲' : 'Bearish ▼'}
                noteColor={ta.macd_bullish ? '#4ade80' : '#f87171'}
              />
              <MetricRow label="Bollinger" value={ta.price_vs_bb ?? 'N/A'} />
              <MetricRow
                label="SMA 20" value={`₹${num(ta.sma_20)}`}
                note={ta.above_sma20 ? 'Above ↑' : 'Below ↓'}
                noteColor={ta.above_sma20 ? '#4ade80' : '#f87171'}
              />
              {ta.sma_50 != null && (
                <MetricRow
                  label="SMA 50" value={`₹${num(ta.sma_50)}`}
                  note={ta.above_sma50 ? 'Above ↑' : 'Below ↓'}
                  noteColor={ta.above_sma50 ? '#4ade80' : '#f87171'}
                />
              )}
              <MetricRow label="52W High" value={`₹${num(ta.high_52w)}`} note={`${ta.pct_from_52w_high}% away`} />
              <MetricRow label="52W Low"  value={`₹${num(ta.low_52w)}`} />
            </>
          )}
        </div>

        {/* Fundamental */}
        <div style={{
          background: 'rgba(167,139,250,0.03)', border: '1px solid rgba(167,139,250,0.12)',
          borderRadius: 8, padding: 14,
        }}>
          <div style={{ color: '#a78bfa', fontSize: 10, letterSpacing: 3, textTransform: 'uppercase', marginBottom: 8, fontFamily: "'Courier New', monospace" }}>
            Fundamental
          </div>
          {fa.error ? (
            <div style={{ color: 'rgba(160,196,224,0.4)', fontSize: 11 }}>Unavailable: {fa.error}</div>
          ) : (
            <>
              <div style={{ color: 'rgba(200,220,240,0.6)', fontSize: 11, fontStyle: 'italic', marginBottom: 8, lineHeight: 1.5 }}>
                {ai.fundamental_verdict}
              </div>
              {fa.sector         && <MetricRow label="Sector"     value={fa.sector} />}
              {fa.market_cap_fmt && <MetricRow label="Market Cap"  value={fa.market_cap_fmt} />}
              {fa.trailing_pe    && <MetricRow label="P/E (TTM)"   value={num(fa.trailing_pe, 1)} />}
              {fa.forward_pe     && <MetricRow label="Forward P/E" value={num(fa.forward_pe, 1)} />}
              {fa.price_to_book  && <MetricRow label="P/B"         value={num(fa.price_to_book)} />}
              {fa.roe_pct        && <MetricRow label="ROE"         value={`${num(fa.roe_pct, 1)}%`} />}
              {fa.revenue_growth_pct != null && (
                <MetricRow
                  label="Rev. Growth" value={`${num(fa.revenue_growth_pct, 1)}%`}
                  noteColor={(fa.revenue_growth_pct ?? 0) > 0 ? '#4ade80' : '#f87171'}
                />
              )}
              {fa.profit_margin_pct != null && (
                <MetricRow
                  label="Profit Margin" value={`${num(fa.profit_margin_pct, 1)}%`}
                  noteColor={(fa.profit_margin_pct ?? 0) > 10 ? '#4ade80' : undefined}
                />
              )}
              {fa.debt_to_equity != null && (
                <MetricRow
                  label="Debt/Equity" value={num(fa.debt_to_equity)}
                  noteColor={(fa.debt_to_equity ?? 0) > 2 ? '#f87171' : '#4ade80'}
                />
              )}
              {fa.dividend_yield_pct && (
                <MetricRow label="Div. Yield" value={`${num(fa.dividend_yield_pct)}%`} />
              )}
            </>
          )}
        </div>
      </div>

      {/* Key positives + risks */}
      {(ai.key_positives.length > 0 || ai.key_risks.length > 0) && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          {ai.key_positives.length > 0 && (
            <div>
              <div style={{ color: '#4ade80', fontSize: 10, letterSpacing: 2, textTransform: 'uppercase', marginBottom: 6, fontFamily: "'Courier New', monospace" }}>
                Key Positives
              </div>
              {ai.key_positives.map((p, i) => (
                <div key={i} style={{
                  color: 'rgba(200,220,240,0.7)', fontSize: 11, padding: '3px 0 3px 10px',
                  borderLeft: '2px solid rgba(74,222,128,0.4)', marginBottom: 5, lineHeight: 1.5,
                }}>{p}</div>
              ))}
            </div>
          )}
          {ai.key_risks.length > 0 && (
            <div>
              <div style={{ color: '#f87171', fontSize: 10, letterSpacing: 2, textTransform: 'uppercase', marginBottom: 6, fontFamily: "'Courier New', monospace" }}>
                Key Risks
              </div>
              {ai.key_risks.map((r, i) => (
                <div key={i} style={{
                  color: 'rgba(200,220,240,0.7)', fontSize: 11, padding: '3px 0 3px 10px',
                  borderLeft: '2px solid rgba(248,113,113,0.4)', marginBottom: 5, lineHeight: 1.5,
                }}>{r}</div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main view ────────────────────────────────────────────────────────────────

export function PortfolioView() {
  const { balVisible } = useBalanceVisibility();
  const M = (v: string) => maskAmount(v, balVisible);
  const [data, setData]               = useState<PortfolioData | null>(null);
  const [loading, setLoading]         = useState(true);
  const [syncing, setSyncing]         = useState(false);
  const [expandedSym, setExpandedSym] = useState<string | null>(null);
  const [analyses, setAnalyses]       = useState<Record<string, AnalysisData>>({});
  const [loadingA, setLoadingA]       = useState<Record<string, boolean>>({});

  const fetchCached = useCallback(async () => {
    try {
      const res = await api.get('/api/portfolio/holdings');
      setData(res.data);
    } catch (e) {
      console.error('Portfolio fetch failed:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchCached(); }, [fetchCached]);

  const handleSync = async () => {
    setSyncing(true);
    try {
      const res = await api.post('/api/portfolio/sync');
      setData(res.data);
    } catch (e) {
      console.error('Sync failed:', e);
    } finally {
      setSyncing(false);
    }
  };

  const toggleAnalysis = async (symbol: string) => {
    if (expandedSym === symbol) {
      setExpandedSym(null);
      return;
    }
    setExpandedSym(symbol);
    if (!analyses[symbol]) {
      setLoadingA(prev => ({ ...prev, [symbol]: true }));
      try {
        const res = await api.get(`/api/portfolio/analysis/${symbol}`);
        setAnalyses(prev => ({ ...prev, [symbol]: res.data }));
      } catch (e) {
        console.error(`Analysis failed for ${symbol}:`, e);
      } finally {
        setLoadingA(prev => ({ ...prev, [symbol]: false }));
      }
    }
  };

  if (loading) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%',
        color: 'rgba(0,229,255,0.4)', fontFamily: "'Courier New', monospace",
        letterSpacing: 4, fontSize: 12,
      }}>
        LOADING PORTFOLIO...
      </div>
    );
  }

  const holdings = data?.holdings ?? [];

  return (
    <div style={{ padding: '0 4px' }}>
      {/* ── Header ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 22 }}>
        <div>
          <h2 style={{
            margin: 0, color: '#00e5ff', fontSize: 19, letterSpacing: 4,
            textTransform: 'uppercase', fontFamily: "'Courier New', monospace",
          }}>
            Portfolio
          </h2>
          <p style={{ margin: '4px 0 0', color: 'rgba(160,196,224,0.45)', fontSize: 11, letterSpacing: 1.5 }}>
            All demat holdings via Angel One
            {data?.last_sync && ` · synced ${data.last_sync}`}
          </p>
        </div>
        <button
          onClick={handleSync}
          disabled={syncing}
          style={{
            padding: '8px 20px',
            background: syncing ? 'rgba(0,229,255,0.06)' : 'transparent',
            border: '1px solid rgba(0,229,255,0.4)',
            color: syncing ? 'rgba(0,229,255,0.4)' : '#00e5ff',
            fontSize: 11, letterSpacing: 3,
            fontFamily: "'Courier New', monospace",
            cursor: syncing ? 'not-allowed' : 'pointer',
            borderRadius: 4, transition: 'all 0.2s',
          }}
          onMouseEnter={e => { if (!syncing) (e.currentTarget as HTMLButtonElement).style.background = 'rgba(0,229,255,0.08)'; }}
          onMouseLeave={e => { if (!syncing) (e.currentTarget as HTMLButtonElement).style.background = 'transparent'; }}
        >
          {syncing ? '⟳ SYNCING…' : '⟳ SYNC BROKER'}
        </button>
      </div>

      {/* ── Summary cards ── */}
      {data && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 22 }}>
          {([
            { label: 'Total Invested',  value: M(INR(data.total_invested)),     color: '#00e5ff'  },
            { label: 'Market Value',    value: M(INR(data.total_market_value)),  color: '#a78bfa'  },
            {
              label: 'Total P&L',
              value: `${data.total_pnl >= 0 ? '+' : ''}${M(INR(data.total_pnl))}`,
              color: pnlCol(data.total_pnl),
            },
            {
              label: 'Overall Return',
              value: `${data.total_pnl_pct >= 0 ? '+' : ''}${data.total_pnl_pct.toFixed(2)}%`,
              color: pnlCol(data.total_pnl_pct),
            },
          ] as { label: string; value: string; color: string }[]).map(card => (
            <div key={card.label} style={{
              background: 'rgba(0,229,255,0.04)', border: '1px solid rgba(0,229,255,0.1)',
              borderRadius: 8, padding: '14px 16px', textAlign: 'center',
            }}>
              <div style={{
                color: 'rgba(160,196,224,0.45)', fontSize: 10, letterSpacing: 2,
                textTransform: 'uppercase', marginBottom: 6,
                fontFamily: "'Courier New', monospace",
              }}>{card.label}</div>
              <div style={{ color: card.color, fontSize: 15, fontWeight: 700, fontFamily: "'Courier New', monospace" }}>
                {card.value}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Holdings list ── */}
      {holdings.length === 0 ? (
        <div style={{
          textAlign: 'center', color: 'rgba(160,196,224,0.35)',
          padding: '60px 0', fontSize: 12, letterSpacing: 2,
          fontFamily: "'Courier New', monospace",
        }}>
          NO HOLDINGS FOUND — CLICK SYNC BROKER TO FETCH
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {holdings.map(h => {
            const isOpen   = expandedSym === h.symbol;
            const analysis = analyses[h.symbol];
            const loading_ = loadingA[h.symbol];

            return (
              <div key={h.symbol} style={{
                background: 'rgba(2,6,18,0.75)',
                border: `1px solid ${isOpen ? 'rgba(0,229,255,0.28)' : 'rgba(0,229,255,0.09)'}`,
                borderRadius: 10, overflow: 'hidden', transition: 'border-color 0.2s',
              }}>
                {/* Row */}
                <div
                  onClick={() => toggleAnalysis(h.symbol)}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '2fr 80px 110px 110px 110px 110px 90px',
                    alignItems: 'center', padding: '14px 18px', cursor: 'pointer', gap: 6,
                  }}
                >
                  {/* Name block */}
                  <div>
                    <div style={{ color: '#00e5ff', fontFamily: "'Courier New', monospace", fontWeight: 700, fontSize: 13, letterSpacing: 1 }}>
                      {h.symbol}
                    </div>
                    <div style={{ color: 'rgba(160,196,224,0.5)', fontSize: 10, marginTop: 2 }}>{h.name}</div>
                    <div style={{ color: 'rgba(160,196,224,0.28)', fontSize: 9, marginTop: 1 }}>
                      {h.instrument_type} · {h.exchange}
                    </div>
                  </div>

                  <Cell label="Qty"       value={String(h.qty)} />
                  <Cell label="Avg Price" value={`₹${h.avg_price.toFixed(2)}`} />
                  <Cell label="LTP"       value={`₹${h.current_price.toFixed(2)}`} />
                  <Cell
                    label="Invested"
                    value={M(h.invested_value >= 1000
                      ? `₹${(h.invested_value / 1000).toFixed(1)}K`
                      : `₹${h.invested_value.toFixed(0)}`)}
                  />

                  {/* P&L */}
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ color: 'rgba(160,196,224,0.4)', fontSize: 9, letterSpacing: 1, textTransform: 'uppercase' }}>P&L</div>
                    <div style={{ color: pnlCol(h.pnl), fontFamily: "'Courier New', monospace", fontSize: 13, fontWeight: 700, marginTop: 2 }}>
                      {h.pnl >= 0 ? '+' : ''}{M(`₹${Math.abs(h.pnl).toFixed(0)}`)}
                    </div>
                    <div style={{ color: pnlCol(h.pnl_pct), fontSize: 10, marginTop: 1 }}>
                      {h.pnl_pct >= 0 ? '+' : ''}{h.pnl_pct.toFixed(2)}%
                    </div>
                  </div>

                  {/* Expand button */}
                  <div style={{ textAlign: 'center' }}>
                    <span style={{
                      color: isOpen ? '#00e5ff' : 'rgba(0,229,255,0.5)',
                      fontSize: 10, border: '1px solid rgba(0,229,255,0.2)',
                      borderRadius: 4, padding: '4px 8px',
                      fontFamily: "'Courier New', monospace", letterSpacing: 1,
                      userSelect: 'none', whiteSpace: 'nowrap',
                    }}>
                      {isOpen ? '▲ HIDE' : '▼ ANALYSE'}
                    </span>
                  </div>
                </div>

                {/* Analysis drawer */}
                {isOpen && (
                  <div style={{
                    borderTop: '1px solid rgba(0,229,255,0.08)',
                    padding: '20px 20px 22px',
                    background: 'rgba(0,0,10,0.25)',
                  }}>
                    {loading_ ? (
                      <div style={{
                        textAlign: 'center', color: 'rgba(0,229,255,0.35)',
                        fontFamily: "'Courier New', monospace", letterSpacing: 3,
                        fontSize: 11, padding: '28px 0',
                      }}>
                        ⟳ ANALYSING {h.symbol}…
                        <div style={{ color: 'rgba(160,196,224,0.25)', fontSize: 9, marginTop: 6, letterSpacing: 1 }}>
                          Fetching price history · running AI deep-dive
                        </div>
                      </div>
                    ) : analysis ? (
                      <AnalysisPanel analysis={analysis} />
                    ) : (
                      <div style={{
                        textAlign: 'center', color: 'rgba(248,113,113,0.5)',
                        fontFamily: "'Courier New', monospace", fontSize: 11, padding: '20px 0',
                      }}>
                        Analysis failed — click ▼ ANALYSE to retry
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Cell({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ textAlign: 'right' }}>
      <div style={{ color: 'rgba(160,196,224,0.4)', fontSize: 9, letterSpacing: 1, textTransform: 'uppercase' }}>{label}</div>
      <div style={{ color: '#e2e8f0', fontFamily: "'Courier New', monospace", fontSize: 13, marginTop: 2 }}>{value}</div>
    </div>
  );
}
