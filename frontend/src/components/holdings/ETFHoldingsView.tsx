import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../../api/client';

interface ETFHolding {
  symbol: string;
  name: string;
  qty: number;
  avg_price: number;
  current_price: number;
  pnl: number;
  pnl_pct: number;
  target_price: number;
  target_hit: boolean;
  token: string;
  exchange: string;
}

interface HoldingsResponse {
  holdings: ETFHolding[];
  last_sync: string | null;
  sells?: string[];
  error?: string;
}

export function ETFHoldingsView() {
  const [holdings, setHoldings] = useState<ETFHolding[]>([]);
  const [lastSync, setLastSync] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchCached = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<HoldingsResponse>('/api/etf/holdings');
      setHoldings(res.data.holdings || []);
      setLastSync(res.data.last_sync || null);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Failed to load holdings');
    } finally {
      setLoading(false);
    }
  }, []);

  const syncNow = async () => {
    setSyncing(true);
    setError(null);
    try {
      const res = await api.post<HoldingsResponse>('/api/etf/sync');
      setHoldings(res.data.holdings || []);
      setLastSync(
        res.data.last_sync ||
        new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })
      );
      if (res.data.sells && res.data.sells.length > 0) {
        // Brief flash so user sees which ETFs were auto-sold
        alert(`Auto-sold at 5% target: ${res.data.sells.join(', ')}`);
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Sync failed');
    } finally {
      setSyncing(false);
    }
  };

  useEffect(() => {
    fetchCached();
  }, [fetchCached]);

  const totalInvested = holdings.reduce((s, h) => s + h.avg_price * h.qty, 0);
  const totalCurrent  = holdings.reduce((s, h) => s + h.current_price * h.qty, 0);
  const totalPnl      = totalCurrent - totalInvested;
  const totalPnlPct   = totalInvested > 0 ? (totalPnl / totalInvested) * 100 : 0;

  return (
    <div className="p-6 space-y-6">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-jarvis-primary tracking-wider">
            ETF Holdings
          </h1>
          <p className="text-xs text-jarvis-text-secondary mt-1">
            Synced from Angel One broker · 5% target auto-sell enabled
          </p>
        </div>
        <div className="flex items-center gap-3">
          {lastSync && (
            <span className="text-xs text-jarvis-text-secondary">
              Last sync: {lastSync}
            </span>
          )}
          <button
            onClick={syncNow}
            disabled={syncing}
            className="px-4 py-2 text-sm font-medium rounded border border-jarvis-primary/50
                       text-jarvis-primary hover:bg-jarvis-primary/10 transition-all
                       disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {syncing ? (
              <span className="flex items-center gap-2">
                <span className="animate-spin">⟳</span> Syncing…
              </span>
            ) : (
              '⟳ Sync Now'
            )}
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="glass-panel border border-red-500/40 rounded-lg p-4 text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Portfolio summary */}
      {holdings.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <SummaryCard label="Holdings" value={`${holdings.length} ETF${holdings.length !== 1 ? 's' : ''}`} />
          <SummaryCard label="Invested" value={`₹${totalInvested.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`} />
          <SummaryCard label="Current Value" value={`₹${totalCurrent.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`} />
          <SummaryCard
            label="Total P&L"
            value={`${totalPnl >= 0 ? '+' : ''}₹${totalPnl.toLocaleString('en-IN', { maximumFractionDigits: 0 })} (${totalPnlPct >= 0 ? '+' : ''}${totalPnlPct.toFixed(2)}%)`}
            highlight={totalPnl >= 0 ? 'green' : 'red'}
          />
        </div>
      )}

      {/* Holdings table */}
      {loading ? (
        <div className="glass-panel rounded-xl p-12 flex items-center justify-center">
          <div className="text-center text-jarvis-text-secondary">
            <div className="text-2xl mb-3 animate-pulse">📊</div>
            <div className="text-sm tracking-widest">LOADING HOLDINGS…</div>
          </div>
        </div>
      ) : holdings.length === 0 ? (
        <div className="glass-panel rounded-xl p-12 flex items-center justify-center">
          <div className="text-center text-jarvis-text-secondary">
            <div className="text-3xl mb-3 opacity-40">🗂️</div>
            <div className="text-sm">No ETF holdings found in your Angel One account.</div>
            <div className="text-xs mt-2 opacity-60">
              Click "Sync Now" to fetch the latest holdings from your broker.
            </div>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {holdings.map((h) => (
            <HoldingCard key={h.symbol} holding={h} />
          ))}
        </div>
      )}

      {/* Info footer */}
      <div className="glass-panel rounded-lg p-4 text-xs text-jarvis-text-secondary space-y-1">
        <div className="font-semibold text-jarvis-primary/70 mb-2">HOW IT WORKS</div>
        <div>• Holdings are synced from your Angel One demat account every 5 minutes during market hours.</div>
        <div>• When any ETF reaches a <span className="text-jarvis-primary">+5% gain</span> from your average buy price, JARVIS automatically places a SELL order for the full quantity.</div>
        <div>• If the auto-sell order fails, you will receive a Telegram alert to sell manually.</div>
        <div>• Only ETFs are tracked here (NIFTYBEES, BANKBEES, GOLDBEES, etc.). Regular stocks are shown in the Stocks section.</div>
      </div>
    </div>
  );
}


// ── Sub-components ────────────────────────────────────────────────────────────

function SummaryCard({
  label, value, highlight,
}: {
  label: string;
  value: string;
  highlight?: 'green' | 'red';
}) {
  const color =
    highlight === 'green' ? 'text-emerald-400' :
    highlight === 'red'   ? 'text-red-400' :
    'text-white';
  return (
    <div className="glass-panel rounded-lg p-4">
      <div className="text-xs text-jarvis-text-secondary mb-1">{label}</div>
      <div className={`text-lg font-bold ${color}`}>{value}</div>
    </div>
  );
}


function HoldingCard({ holding: h }: { holding: ETFHolding }) {
  const pnlColor  = h.pnl_pct >= 0 ? 'text-emerald-400' : 'text-red-400';
  const barColor  = h.pnl_pct >= _TARGET ? 'bg-emerald-400' : 'bg-jarvis-primary';
  const barWidth  = Math.min(100, Math.max(0, (h.pnl_pct / _TARGET) * 100));

  return (
    <div
      className={`glass-panel rounded-xl p-5 border transition-all ${
        h.target_hit
          ? 'border-emerald-400/60 shadow-[0_0_12px_rgba(52,211,153,0.2)]'
          : 'border-jarvis-primary/20 hover:border-jarvis-primary/40'
      }`}
    >
      <div className="flex items-start justify-between gap-4">

        {/* Left: symbol + name */}
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-bold text-white text-sm">{h.symbol}</span>
            <span className="text-xs text-jarvis-text-secondary">{h.name}</span>
            {h.target_hit && (
              <span className="text-xs bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 px-2 py-0.5 rounded-full font-bold">
                TARGET HIT ✓
              </span>
            )}
          </div>
          <div className="text-xs text-jarvis-text-secondary mt-1">
            {h.qty} units · avg ₹{h.avg_price.toFixed(2)}
          </div>
        </div>

        {/* Right: price + P&L */}
        <div className="text-right shrink-0">
          <div className="text-white font-bold">₹{h.current_price.toFixed(2)}</div>
          <div className={`text-sm font-semibold ${pnlColor}`}>
            {h.pnl_pct >= 0 ? '+' : ''}{h.pnl_pct.toFixed(2)}%
          </div>
          <div className={`text-xs ${pnlColor}`}>
            {h.pnl >= 0 ? '+' : ''}₹{h.pnl.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
          </div>
        </div>
      </div>

      {/* Progress bar toward 5% target */}
      <div className="mt-4">
        <div className="flex justify-between text-xs text-jarvis-text-secondary mb-1">
          <span>Progress to 5% target</span>
          <span>Target: ₹{h.target_price.toFixed(2)}</span>
        </div>
        <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${barColor}`}
            style={{ width: `${barWidth}%` }}
          />
        </div>
        <div className="flex justify-between text-xs mt-1">
          <span className="text-jarvis-text-secondary">0%</span>
          <span className={h.target_hit ? 'text-emerald-400' : 'text-jarvis-text-secondary'}>5%</span>
        </div>
      </div>
    </div>
  );
}

const _TARGET = 5.0;
