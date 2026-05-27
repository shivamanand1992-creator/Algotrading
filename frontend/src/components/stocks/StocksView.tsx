import React, { useEffect, useState, useCallback } from 'react';
import { stocksApi } from '../../api/client';
import { Card } from '../ui/Card';
import type { StockSignal, SwingPosition } from '../../types/api';

// ── Sector colour chips ────────────────────────────────────────────────────
const SECTOR_COLORS: Record<string, string> = {
  IT:          '#00e5ff',
  Banking:     '#1de9b6',
  Finance:     '#00b0ff',
  Pharma:      '#69f0ae',
  Auto:        '#ffab40',
  Energy:      '#ff6e40',
  Consumer:    '#ea80fc',
  Metals:      '#8c9eff',
  Healthcare:  '#80d8ff',
  Telecom:     '#ccff90',
  Insurance:   '#ffd740',
  Industrials: '#ff80ab',
  Commodities: '#b9f6ca',
  Utilities:   '#a7ffeb',
  Materials:   '#ffe57f',
  Retail:      '#f8bbd0',
};

function SectorChip({ sector }: { sector: string }) {
  const color = SECTOR_COLORS[sector] ?? '#8aa5c0';
  return (
    <span
      className="text-xs font-semibold px-2 py-0.5 rounded-full"
      style={{ background: `${color}22`, color, border: `1px solid ${color}55` }}
    >
      {sector}
    </span>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const pct  = Math.round(value * 100);
  const col  = value >= 0.75 ? '#00e676' : value >= 0.60 ? '#ffd600' : '#ff6e40';
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-white/10 rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: col }} />
      </div>
      <span className="text-xs font-mono" style={{ color: col }}>{pct}%</span>
    </div>
  );
}

function PnLBadge({ value }: { value: number }) {
  const positive = value >= 0;
  return (
    <span
      className="text-xs font-bold px-2 py-0.5 rounded"
      style={{
        background: positive ? 'rgba(0,230,118,0.15)' : 'rgba(255,82,82,0.15)',
        color:      positive ? '#00e676' : '#ff5252',
      }}
    >
      {positive ? '+' : ''}{value.toFixed(2)}%
    </span>
  );
}

// ── Confirmation modal ─────────────────────────────────────────────────────
interface ConfirmModalProps {
  title: string;
  body: string;
  onConfirm: () => void;
  onCancel: () => void;
}
function ConfirmModal({ title, body, onConfirm, onCancel }: ConfirmModalProps) {
  return (
    <div className="fixed inset-0 flex items-center justify-center" style={{ zIndex: 99999 }}>
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onCancel} />
      <div className="glass-panel neon-border p-8 max-w-md w-full mx-4 relative" style={{ zIndex: 100000 }}>
        <h3 className="text-lg font-bold text-jarvis-primary uppercase tracking-widest mb-3">{title}</h3>
        <p className="text-jarvis-text-secondary text-sm mb-6">{body}</p>
        <div className="flex gap-3">
          <button onClick={onCancel} className="flex-1 jarvis-button-outline text-center">Cancel</button>
          <button
            onClick={onConfirm}
            className="flex-1 py-2.5 rounded-lg font-bold uppercase tracking-wider text-sm"
            style={{ background: 'rgba(0,229,255,0.15)', border: '1px solid rgba(0,229,255,0.5)', color: '#00e5ff' }}
          >
            Confirm
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────
export function StocksView() {
  const [signals,   setSignals]   = useState<StockSignal[]>([]);
  const [positions, setPositions] = useState<SwingPosition[]>([]);
  const [scanning,  setScanning]  = useState(false);
  const [scanTime,  setScanTime]  = useState<string | null>(null);
  const [error,     setError]     = useState<string | null>(null);
  const [execMode,  setExecMode]  = useState<'paper' | 'live'>('paper');
  const [executing, setExecuting] = useState<string | null>(null);   // symbol being executed
  const [confirm,   setConfirm]   = useState<{ symbol: string; auto?: boolean } | null>(null);
  const [toast,     setToast]     = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 4000);
  };

  const fetchPositions = useCallback(async () => {
    try {
      const res = await stocksApi.getPositions();
      setPositions(Array.isArray(res.data) ? res.data : []);
    } catch { /* silent */ }
  }, []);

  // Load cached signals and positions on mount
  useEffect(() => {
    const init = async () => {
      try {
        const [sigRes, posRes] = await Promise.all([
          stocksApi.getSignals(),
          stocksApi.getPositions(),
        ]);
        const sigs = Array.isArray(sigRes.data) ? sigRes.data : [];
        setSignals(sigs);
        if (sigs.length > 0) setScanTime(sigs[0].scan_time);
        setPositions(Array.isArray(posRes.data) ? posRes.data : []);
      } catch { /* backend may not have scanned yet — that's fine */ }
    };
    init();
    const iv = setInterval(fetchPositions, 30000);
    return () => clearInterval(iv);
  }, [fetchPositions]);

  const handleScan = async () => {
    setScanning(true);
    setError(null);
    try {
      const res = await stocksApi.scan();
      const sigs = Array.isArray(res.data) ? res.data : [];
      setSignals(sigs);
      if (sigs.length > 0) setScanTime(sigs[0].scan_time);
      else setScanTime(new Date().toISOString());
      showToast(`Scan complete — ${sigs.length} BUY signal${sigs.length !== 1 ? 's' : ''} found`);
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? 'Scan failed — check network');
    } finally {
      setScanning(false);
    }
  };

  const handleExecute = async (symbol: string) => {
    setConfirm({ symbol });
  };

  const handleAutoExecute = () => {
    setConfirm({ symbol: '', auto: true });
  };

  const confirmExecute = async () => {
    if (!confirm) return;
    const isAuto = confirm.auto;
    setConfirm(null);
    setExecuting(isAuto ? '__auto__' : confirm.symbol);
    try {
      if (isAuto) {
        const res = await stocksApi.autoExecute(execMode, 3);
        const count = res.data.count ?? 0;
        showToast(`Auto-executed ${count} ${execMode} order${count !== 1 ? 's' : ''}`);
      } else {
        await stocksApi.execute(confirm.symbol, execMode);
        showToast(`${execMode === 'paper' ? 'Paper' : 'Live'} order placed for ${confirm.symbol}`);
      }
      await fetchPositions();
    } catch (err: any) {
      showToast(`Execution failed: ${err?.response?.data?.detail ?? err?.message}`);
    } finally {
      setExecuting(null);
    }
  };

  const handleClosePosition = async (symbol: string) => {
    if (!window.confirm(`Close ${symbol} swing position?`)) return;
    try {
      await stocksApi.closePosition(symbol);
      showToast(`${symbol} position closed`);
      await fetchPositions();
    } catch { showToast('Failed to close position'); }
  };

  const formatPrice = (v: number) => `₹${v.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const formatScanTime = (iso: string) => {
    try { return new Date(iso).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }); }
    catch { return iso; }
  };

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="p-6 space-y-6">
      {/* Toast */}
      {toast && (
        <div
          className="fixed top-6 right-6 glass-panel px-5 py-3 text-sm font-semibold text-jarvis-primary neon-border z-50"
          style={{ zIndex: 99998 }}
        >
          {toast}
        </div>
      )}

      {/* Confirm modal */}
      {confirm && (
        <ConfirmModal
          title={confirm.auto ? 'Auto-Execute Top 3 Signals' : `Execute ${confirm.symbol}`}
          body={
            confirm.auto
              ? `Place ${execMode} delivery orders for the top 3 signals with confidence ≥ 70%. Only BUY orders, no short-selling.`
              : `Place a ${execMode} delivery BUY order for ${confirm.symbol}. The position will be tracked in the Swing Positions table.`
          }
          onConfirm={confirmExecute}
          onCancel={() => setConfirm(null)}
        />
      )}

      {/* ── Header ── */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h2 className="text-xl font-black text-jarvis-primary glow-text uppercase tracking-widest">
            Stock Screener — Swing Trade
          </h2>
          <p className="text-xs text-jarvis-text-secondary mt-1">
            Nifty50 daily scan · Entry / SL / Target for 2–10 day delivery trades
          </p>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          {/* Mode toggle */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-jarvis-text-secondary">Mode:</span>
            {(['paper', 'live'] as const).map(m => (
              <button
                key={m}
                onClick={() => setExecMode(m)}
                className="px-3 py-1.5 text-xs font-bold uppercase rounded-lg transition-all"
                style={{
                  background: execMode === m ? (m === 'live' ? 'rgba(255,23,68,0.2)' : 'rgba(0,229,255,0.15)') : 'transparent',
                  border:     execMode === m ? (m === 'live' ? '1px solid rgba(255,23,68,0.6)' : '1px solid rgba(0,229,255,0.5)') : '1px solid rgba(255,255,255,0.1)',
                  color:      execMode === m ? (m === 'live' ? '#ff1744' : '#00e5ff') : '#8aa5c0',
                }}
              >
                {m}
              </button>
            ))}
          </div>

          {/* Auto-execute */}
          {signals.length > 0 && (
            <button
              onClick={handleAutoExecute}
              disabled={!!executing}
              className="px-4 py-2 text-xs font-bold uppercase rounded-lg transition-all"
              style={{ background: 'rgba(0,230,118,0.15)', border: '1px solid rgba(0,230,118,0.4)', color: '#00e676' }}
            >
              ⚡ Auto Execute Top 3
            </button>
          )}

          {/* Scan button */}
          <button
            onClick={handleScan}
            disabled={scanning}
            className="px-5 py-2 text-xs font-bold uppercase rounded-lg transition-all jarvis-button"
          >
            {scanning ? (
              <span className="flex items-center gap-2">
                <span className="inline-block w-3 h-3 border-2 border-jarvis-primary border-t-transparent rounded-full animate-spin" />
                Scanning…
              </span>
            ) : '🔍 Run Scan'}
          </button>
        </div>
      </div>

      {scanTime && (
        <p className="text-xs text-jarvis-text-secondary">
          Last scan: {formatScanTime(scanTime)} · {signals.length} BUY signal{signals.length !== 1 ? 's' : ''}
        </p>
      )}

      {error && (
        <div className="glass-panel p-4 border border-red-500/40 text-red-400 text-sm">{error}</div>
      )}

      {/* ── Open Swing Positions ── */}
      {positions.length > 0 && (
        <Card title={`Open Swing Positions (${positions.length})`}>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-jarvis-text-secondary border-b border-white/10">
                  <th className="pb-2 text-left">Stock</th>
                  <th className="pb-2 text-right">Entry</th>
                  <th className="pb-2 text-right">CMP</th>
                  <th className="pb-2 text-right">P&L</th>
                  <th className="pb-2 text-right">SL</th>
                  <th className="pb-2 text-right">Target</th>
                  <th className="pb-2 text-center">Mode</th>
                  <th className="pb-2 text-center">Action</th>
                </tr>
              </thead>
              <tbody>
                {positions.map(pos => (
                  <tr key={pos.symbol} className="border-b border-white/5 hover:bg-white/5">
                    <td className="py-2.5">
                      <div className="font-bold text-jarvis-primary">{pos.symbol}</div>
                      <SectorChip sector={pos.sector} />
                    </td>
                    <td className="py-2.5 text-right font-mono">{formatPrice(pos.entry_price)}</td>
                    <td className="py-2.5 text-right font-mono">{formatPrice(pos.current_price)}</td>
                    <td className="py-2.5 text-right"><PnLBadge value={pos.pnl_pct} /></td>
                    <td className="py-2.5 text-right font-mono text-red-400">{formatPrice(pos.stop_loss)}</td>
                    <td className="py-2.5 text-right font-mono text-green-400">{formatPrice(pos.target1)}</td>
                    <td className="py-2.5 text-center">
                      <span className="text-xs px-1.5 py-0.5 rounded" style={{
                        background: pos.mode === 'live' ? 'rgba(255,23,68,0.15)' : 'rgba(0,229,255,0.1)',
                        color:      pos.mode === 'live' ? '#ff1744' : '#00e5ff',
                      }}>
                        {pos.mode.toUpperCase()}
                      </span>
                    </td>
                    <td className="py-2.5 text-center">
                      <button
                        onClick={() => handleClosePosition(pos.symbol)}
                        className="text-xs px-2 py-1 rounded border border-white/20 text-jarvis-text-secondary hover:border-red-400 hover:text-red-400 transition-all"
                      >
                        Close
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* ── Signal cards ── */}
      {scanning ? (
        <div className="flex flex-col items-center justify-center py-16 gap-4">
          <div className="w-10 h-10 border-4 border-jarvis-primary border-t-transparent rounded-full animate-spin" />
          <div className="text-jarvis-primary font-semibold uppercase tracking-widest text-sm">
            Scanning 50 Nifty50 stocks…
          </div>
          <div className="text-jarvis-text-secondary text-xs">Fetching daily OHLCV + computing indicators (~15s)</div>
        </div>
      ) : signals.length === 0 ? (
        <Card title="Swing Signals">
          <div className="text-center py-12 text-jarvis-text-secondary">
            <div className="text-4xl mb-4">🔍</div>
            <div className="font-semibold">No signals yet</div>
            <div className="text-xs mt-2">Click "Run Scan" to scan Nifty50 for swing trade setups</div>
          </div>
        </Card>
      ) : (
        <Card title={`Swing Trade Signals — ${signals.length} found`}>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-jarvis-text-secondary border-b border-white/10 text-right">
                  <th className="pb-3 text-left">Stock</th>
                  <th className="pb-3">CMP</th>
                  <th className="pb-3">Entry</th>
                  <th className="pb-3 text-red-400">Stop Loss</th>
                  <th className="pb-3 text-green-400">Target 1</th>
                  <th className="pb-3 text-green-300">Target 2</th>
                  <th className="pb-3">SL%</th>
                  <th className="pb-3 text-left pl-4">Confidence</th>
                  <th className="pb-3 text-center">RSI</th>
                  <th className="pb-3 text-center">ADX</th>
                  <th className="pb-3 text-center">Vol×</th>
                  <th className="pb-3 text-center">Action</th>
                </tr>
              </thead>
              <tbody>
                {signals.map(sig => {
                  const alreadyHeld = positions.some(p => p.symbol === sig.symbol);
                  const isExec      = executing === sig.symbol;
                  return (
                    <tr key={sig.symbol} className="border-b border-white/5 hover:bg-white/5 group">
                      {/* Stock info */}
                      <td className="py-3">
                        <div className="font-bold text-jarvis-primary">{sig.symbol}</div>
                        <div className="text-jarvis-text-secondary mt-0.5">{sig.name.split(' ').slice(0,2).join(' ')}</div>
                        <SectorChip sector={sig.sector} />
                      </td>

                      {/* Prices */}
                      <td className="py-3 text-right font-mono">{formatPrice(sig.close)}</td>
                      <td className="py-3 text-right font-mono text-jarvis-primary">{formatPrice(sig.entry_price)}</td>
                      <td className="py-3 text-right font-mono text-red-400">{formatPrice(sig.stop_loss)}</td>
                      <td className="py-3 text-right font-mono text-green-400">{formatPrice(sig.target1)}</td>
                      <td className="py-3 text-right font-mono text-green-300">{formatPrice(sig.target2)}</td>
                      <td className="py-3 text-right text-orange-400">-{sig.sl_pct}%</td>

                      {/* Confidence bar */}
                      <td className="py-3 pl-4 min-w-[120px]">
                        <ConfidenceBar value={sig.confidence} />
                        {/* Regime badge */}
                        <div className="mt-1">
                          <span className="text-xs px-1.5 py-0.5 rounded"
                            style={{
                              background: sig.regime === 'uptrend' ? 'rgba(0,230,118,0.1)' : 'rgba(255,214,0,0.1)',
                              color:      sig.regime === 'uptrend' ? '#00e676' : '#ffd600',
                            }}
                          >
                            {sig.regime}
                          </span>
                        </div>
                      </td>

                      {/* Indicators */}
                      <td className="py-3 text-center">
                        <span style={{ color: sig.rsi >= 50 && sig.rsi <= 70 ? '#00e676' : '#8aa5c0' }}>
                          {sig.rsi.toFixed(0)}
                        </span>
                      </td>
                      <td className="py-3 text-center">
                        <span style={{ color: sig.adx > 25 ? '#00e676' : sig.adx > 20 ? '#ffd600' : '#8aa5c0' }}>
                          {sig.adx.toFixed(0)}
                        </span>
                      </td>
                      <td className="py-3 text-center">
                        <span style={{ color: sig.volume_ratio >= 1.5 ? '#00e676' : sig.volume_ratio >= 1.2 ? '#ffd600' : '#8aa5c0' }}>
                          {sig.volume_ratio.toFixed(1)}×
                        </span>
                      </td>

                      {/* Execute */}
                      <td className="py-3 text-center">
                        {alreadyHeld ? (
                          <span className="text-xs text-green-400 font-semibold">Held</span>
                        ) : (
                          <button
                            onClick={() => handleExecute(sig.symbol)}
                            disabled={isExec || !!executing}
                            className="px-3 py-1.5 text-xs font-bold uppercase rounded-lg transition-all"
                            style={{
                              background: 'rgba(0,229,255,0.15)',
                              border: '1px solid rgba(0,229,255,0.4)',
                              color: '#00e5ff',
                              opacity: executing ? 0.5 : 1,
                            }}
                          >
                            {isExec ? '…' : 'Execute'}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Reasons tooltip info */}
          <div className="mt-4 pt-4 border-t border-white/10">
            <p className="text-xs text-jarvis-text-secondary">
              <span className="text-jarvis-primary font-semibold">Signal logic:</span>{' '}
              EMA alignment · ADX trend strength · RSI momentum zone (50–70) · MACD histogram · Volume confirmation · Candlestick patterns.
              SL = 1.5 × ATR14 below entry · Target = 2× risk (1:2 R:R).
            </p>
          </div>
        </Card>
      )}
    </div>
  );
}
