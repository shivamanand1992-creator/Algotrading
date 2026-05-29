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
  const pct = Math.round(value * 100);
  const col = value >= 0.75 ? '#00e676' : value >= 0.60 ? '#ffd600' : '#ff6e40';
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

function FilterToggle({ label, value, onChange }: { label: string; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      onClick={() => onChange(!value)}
      className="flex items-center gap-2 px-3 py-1.5 text-xs font-bold uppercase rounded-lg transition-all"
      style={{
        background: value ? 'rgba(0,229,255,0.12)' : 'rgba(255,255,255,0.04)',
        border:     value ? '1px solid rgba(0,229,255,0.5)' : '1px solid rgba(255,255,255,0.15)',
        color:      value ? '#00e5ff' : '#8aa5c0',
      }}
    >
      <span
        className="inline-block w-2 h-2 rounded-full transition-all"
        style={{ background: value ? '#00e5ff' : '#444', boxShadow: value ? '0 0 6px #00e5ff' : 'none' }}
      />
      {label}
    </button>
  );
}

// ── Main component ─────────────────────────────────────────────────────────
export function StocksView() {
  const [signals,      setSignals]      = useState<StockSignal[]>([]);
  const [positions,    setPositions]    = useState<SwingPosition[]>([]);
  const [scanning,     setScanning]     = useState(false);
  const [scanTime,     setScanTime]     = useState<string | null>(null);
  const [error,        setError]        = useState<string | null>(null);
  const [executing,    setExecuting]    = useState<string | null>(null);
  const [confirmSym,   setConfirmSym]   = useState<string | null>(null);  // symbol or '__top__'
  const [toast,        setToast]        = useState<string | null>(null);

  // ── Unified settings (shared by manual execute AND autopilot) ──
  const [execMode, setExecMode] = useState<'paper' | 'live'>(() =>
    (localStorage.getItem('swing_exec_mode') as 'paper' | 'live') || 'paper'
  );
  const [capital, setCapital]     = useState<number>(() => {
    const s = localStorage.getItem('swing_capital');
    return s ? Math.max(500, parseInt(s, 10)) : 1000;
  });
  const [capitalInput, setCapitalInput] = useState<string>(() =>
    localStorage.getItem('swing_capital') ?? '1000'
  );
  const [maxTrades, setMaxTrades] = useState<number>(() => {
    const s = localStorage.getItem('swing_max_trades');
    return s ? parseInt(s, 10) : 3;
  });

  // ── Scan filters ──
  const [universe,      setUniverse]      = useState<'nifty50' | 'nifty100'>('nifty50');
  const [regimeFilter,  setRegimeFilter]  = useState(true);
  const [rsFilter,      setRsFilter]      = useState(true);
  const [regimeWarning, setRegimeWarning] = useState('');
  const [niftyBullish,  setNiftyBullish]  = useState<boolean | null>(null);
  const [niftyReturn,   setNiftyReturn]   = useState(0);

  // ── Autopilot ──
  const [autopilotEnabled,    setAutopilotEnabled]    = useState(false);
  const [autopilotLastRun,    setAutopilotLastRun]    = useState<string | null>(null);
  const [autopilotLastResult, setAutopilotLastResult] = useState<Record<string, any>>({});
  const [autopilotSaving,     setAutopilotSaving]     = useState(false);
  const [autopilotRunning,    setAutopilotRunning]    = useState(false);

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

  useEffect(() => {
    const init = async () => {
      try {
        const [sigRes, posRes, apRes] = await Promise.all([
          stocksApi.getSignals(),
          stocksApi.getPositions(),
          stocksApi.getAutopilot(),
        ]);
        const sigs = Array.isArray(sigRes.data) ? sigRes.data : [];
        setSignals(sigs);
        if (sigs.length > 0) setScanTime(sigs[0].scan_time);
        setPositions(Array.isArray(posRes.data) ? posRes.data : []);

        // Restore autopilot state; pull settings back as source of truth
        const ap = apRes.data;
        setAutopilotEnabled(ap.enabled ?? false);
        setAutopilotLastRun(ap.last_run ?? null);
        setAutopilotLastResult(ap.last_result ?? {});
        // Sync server-persisted settings back into local unified state
        if (ap.mode)              { setExecMode(ap.mode as 'paper' | 'live'); localStorage.setItem('swing_exec_mode', ap.mode); }
        if (ap.capital_per_trade) { setCapital(ap.capital_per_trade); setCapitalInput(String(ap.capital_per_trade)); localStorage.setItem('swing_capital', String(ap.capital_per_trade)); }
        if (ap.max_trades)        { setMaxTrades(ap.max_trades); localStorage.setItem('swing_max_trades', String(ap.max_trades)); }
      } catch { /* first load — fine */ }
    };
    init();
    const iv = setInterval(fetchPositions, 30000);
    return () => clearInterval(iv);
  }, [fetchPositions]);

  // Save unified settings to server whenever they change
  const syncAutopilot = useCallback(async (overrides?: Partial<{ enabled: boolean; mode: string; capital: number; max_trades: number }>) => {
    setAutopilotSaving(true);
    try {
      const res = await stocksApi.setAutopilot({
        enabled:           overrides?.enabled    ?? autopilotEnabled,
        mode:              overrides?.mode        ?? execMode,
        capital_per_trade: overrides?.capital     ?? capital,
        max_trades:        overrides?.max_trades  ?? maxTrades,
      });
      const cfg = (res.data as any).config ?? {};
      if (overrides?.enabled !== undefined) {
        setAutopilotEnabled(cfg.enabled ?? overrides.enabled);
        showToast(cfg.enabled ? '🤖 Autopilot ON — scans daily at 09:20 IST' : 'Autopilot disabled');
      }
    } catch { showToast('Failed to save settings'); }
    finally { setAutopilotSaving(false); }
  }, [autopilotEnabled, execMode, capital, maxTrades]);

  const handleModeChange = (m: 'paper' | 'live') => {
    setExecMode(m);
    localStorage.setItem('swing_exec_mode', m);
    syncAutopilot({ mode: m });
  };

  const handleCapitalChange = (val: string) => {
    setCapitalInput(val);
    const n = parseInt(val.replace(/,/g, ''), 10);
    if (!isNaN(n) && n >= 500) {
      setCapital(n);
      localStorage.setItem('swing_capital', String(n));
    }
  };

  const handleMaxTradesChange = (n: number) => {
    setMaxTrades(n);
    localStorage.setItem('swing_max_trades', String(n));
    syncAutopilot({ max_trades: n });
  };

  const handleAutopilotToggle = () => {
    const next = !autopilotEnabled;
    setAutopilotEnabled(next);
    syncAutopilot({ enabled: next });
  };

  const handleRunNow = async () => {
    if (!autopilotEnabled) { showToast('Enable autopilot first'); return; }
    setAutopilotRunning(true);
    try {
      const res = await stocksApi.runAutopilotNow();
      const result = res.data as any;
      setAutopilotLastResult(result);
      setAutopilotLastRun(new Date().toISOString());
      const n = result.executed_count ?? result.executed?.length ?? 0;
      showToast(`Autopilot ran: ${n} trade${n !== 1 ? 's' : ''} executed (${result.signals_found ?? 0} signals found)`);
      await fetchPositions();
    } catch (err: any) {
      showToast(`Autopilot failed: ${err?.response?.data?.detail ?? err?.message}`);
    } finally { setAutopilotRunning(false); }
  };

  const handleScan = async () => {
    setScanning(true);
    setError(null);
    setRegimeWarning('');
    try {
      const res = await stocksApi.scan({ universe, regime_filter: regimeFilter, rs_filter: rsFilter });
      const data = res.data as any;
      const sigs = Array.isArray(data.signals) ? data.signals : (Array.isArray(data) ? data : []);
      setSignals(sigs);
      setRegimeWarning(data.regime_warning ?? '');
      setNiftyBullish(data.nifty_bullish ?? null);
      setNiftyReturn(data.nifty_20d_return ?? 0);
      if (sigs.length > 0) setScanTime(sigs[0].scan_time);
      else setScanTime(new Date().toISOString());
      showToast(`Scan complete — ${sigs.length} BUY signal${sigs.length !== 1 ? 's' : ''} found`);
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? 'Scan failed — check network');
    } finally {
      setScanning(false);
    }
  };

  const confirmExecute = async () => {
    if (!confirmSym) return;
    const isTop = confirmSym === '__top__';
    setConfirmSym(null);
    setExecuting(isTop ? '__top__' : confirmSym);
    try {
      if (isTop) {
        const res = await stocksApi.autoExecute(execMode, maxTrades, capital);
        const count = res.data.count ?? 0;
        showToast(`Executed ${count} ${execMode} order${count !== 1 ? 's' : ''}`);
      } else {
        await stocksApi.execute(confirmSym, execMode, capital);
        showToast(`${execMode === 'paper' ? 'Paper' : 'Live'} order placed for ${confirmSym}`);
      }
      await fetchPositions();
    } catch (err: any) {
      showToast(`Execution failed: ${err?.response?.data?.detail ?? err?.message}`);
    } finally { setExecuting(null); }
  };

  const handleClosePosition = async (symbol: string) => {
    if (!window.confirm(`Close ${symbol} swing position?`)) return;
    try {
      await stocksApi.closePosition(symbol);
      showToast(`${symbol} position closed`);
      await fetchPositions();
    } catch { showToast('Failed to close position'); }
  };

  const handleCloseAll = async () => {
    if (!window.confirm('Remove ALL swing positions from the tracker?\n\nThis only clears the system state — make sure you have already closed them in Angel One.')) return;
    try {
      const res = await stocksApi.closeAllPositions();
      showToast((res.data as any).message ?? 'All positions cleared');
      await fetchPositions();
    } catch { showToast('Failed to clear positions'); }
  };

  const handleSyncFromBroker = async () => {
    try {
      showToast('Syncing holdings from Angel One…');
      const res = await stocksApi.syncFromBroker();
      showToast(res.data?.message || 'Sync complete');
      await fetchPositions();
    } catch { showToast('Sync failed — check broker connection'); }
  };

  const formatPrice   = (v: number) => `₹${v.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const formatScanTime = (iso: string) => {
    try { return new Date(iso).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }); }
    catch { return iso; }
  };

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="p-6 space-y-5">

      {/* Toast */}
      {toast && (
        <div
          className="fixed top-6 right-6 glass-panel px-5 py-3 text-sm font-semibold text-jarvis-primary neon-border"
          style={{ zIndex: 99998 }}
        >
          {toast}
        </div>
      )}

      {/* Confirm modal */}
      {confirmSym && (
        <div className="fixed inset-0 flex items-center justify-center" style={{ zIndex: 99999 }}>
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setConfirmSym(null)} />
          <div className="glass-panel neon-border p-8 max-w-md w-full mx-4 relative" style={{ zIndex: 100000 }}>
            <h3 className="text-lg font-bold text-jarvis-primary uppercase tracking-widest mb-3">
              {confirmSym === '__top__' ? `Execute Top ${maxTrades} Signals` : `Execute ${confirmSym}`}
            </h3>
            <p className="text-jarvis-text-secondary text-sm mb-6">
              {confirmSym === '__top__'
                ? `Place ${execMode.toUpperCase()} delivery BUY orders for the top ${maxTrades} highest-confidence signals. ₹${capital.toLocaleString('en-IN')} per trade.`
                : `Place a ${execMode.toUpperCase()} delivery BUY order for ${confirmSym}. ₹${capital.toLocaleString('en-IN')} invested.`}
            </p>
            <div className="flex gap-3">
              <button onClick={() => setConfirmSym(null)} className="flex-1 jarvis-button-outline text-center">Cancel</button>
              <button
                onClick={confirmExecute}
                className="flex-1 py-2.5 rounded-lg font-bold uppercase tracking-wider text-sm"
                style={{ background: execMode === 'live' ? 'rgba(255,23,68,0.2)' : 'rgba(0,229,255,0.15)', border: `1px solid ${execMode === 'live' ? 'rgba(255,23,68,0.6)' : 'rgba(0,229,255,0.5)'}`, color: execMode === 'live' ? '#ff1744' : '#00e5ff' }}
              >
                Confirm {execMode.toUpperCase()}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Header: title + unified settings + scan ── */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h2 className="text-xl font-black text-jarvis-primary glow-text uppercase tracking-widest">Equity Swing</h2>
          <p className="text-xs text-jarvis-text-secondary mt-1">CNC delivery trades · 2–10 day holds · Entry / Stop-Loss / Target</p>
        </div>

        <div className="flex items-center gap-3 flex-wrap">

          {/* ₹ per trade */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-jarvis-text-secondary">₹ / trade:</span>
            <div className="flex items-center glass-panel rounded-lg px-3 py-1.5 gap-1" style={{ border: '1px solid rgba(0,229,255,0.25)' }}>
              <span className="text-xs text-jarvis-text-secondary">₹</span>
              <input
                type="text"
                value={capitalInput}
                onChange={e => handleCapitalChange(e.target.value)}
                onBlur={() => syncAutopilot({ capital })}
                className="bg-transparent text-xs font-mono text-jarvis-primary outline-none w-20 text-right"
                placeholder="1000"
              />
            </div>
          </div>

          {/* Max positions */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-jarvis-text-secondary">Max:</span>
            {[1, 2, 3, 5].map(n => (
              <button
                key={n}
                onClick={() => handleMaxTradesChange(n)}
                className="w-7 h-7 text-xs font-bold rounded-lg transition-all"
                style={{
                  background: maxTrades === n ? 'rgba(0,229,255,0.2)' : 'rgba(255,255,255,0.05)',
                  border:     maxTrades === n ? '1px solid rgba(0,229,255,0.6)' : '1px solid rgba(255,255,255,0.1)',
                  color:      maxTrades === n ? '#00e5ff' : '#8aa5c0',
                }}
              >
                {n}
              </button>
            ))}
          </div>

          {/* Mode */}
          {(['paper', 'live'] as const).map(m => (
            <button
              key={m}
              onClick={() => handleModeChange(m)}
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

          {/* Scan */}
          <button
            onClick={handleScan}
            disabled={scanning}
            className="px-5 py-2 text-xs font-bold uppercase rounded-lg transition-all jarvis-button"
          >
            {scanning
              ? <span className="flex items-center gap-2"><span className="inline-block w-3 h-3 border-2 border-jarvis-primary border-t-transparent rounded-full animate-spin" />Scanning…</span>
              : '🔍 Run Scan'}
          </button>
        </div>
      </div>

      {/* ── Filters ── */}
      <div className="glass-panel p-3 rounded-xl" style={{ border: '1px solid rgba(0,229,255,0.15)' }}>
        <div className="flex items-center gap-4 flex-wrap">
          <span className="text-xs font-bold uppercase tracking-widest text-jarvis-text-secondary">Filters:</span>
          <div className="flex items-center gap-2">
            <span className="text-xs text-jarvis-text-secondary">Universe:</span>
            {([['nifty50', 'Nifty 50'], ['nifty100', 'Nifty 100']] as const).map(([val, label]) => (
              <button
                key={val}
                onClick={() => setUniverse(val)}
                className="px-3 py-1.5 text-xs font-bold rounded-lg transition-all"
                style={{
                  background: universe === val ? 'rgba(0,229,255,0.15)' : 'rgba(255,255,255,0.04)',
                  border:     universe === val ? '1px solid rgba(0,229,255,0.5)' : '1px solid rgba(255,255,255,0.12)',
                  color:      universe === val ? '#00e5ff' : '#8aa5c0',
                }}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="w-px h-4 bg-white/15 hidden sm:block" />
          <FilterToggle label="Nifty Regime" value={regimeFilter} onChange={setRegimeFilter} />
          <span className="text-xs text-jarvis-text-secondary hidden sm:inline">(warns if Nifty below 200-EMA)</span>
          <FilterToggle label="Rel. Strength" value={rsFilter} onChange={setRsFilter} />
          <span className="text-xs text-jarvis-text-secondary hidden sm:inline">(scores stocks vs Nifty 20d return)</span>
          {niftyBullish !== null && (
            <div className="ml-auto flex items-center gap-2">
              <span className="text-xs text-jarvis-text-secondary">Nifty 20d:</span>
              <span className="text-xs font-mono font-bold px-2 py-0.5 rounded" style={{ background: niftyBullish ? 'rgba(0,230,118,0.12)' : 'rgba(255,82,82,0.12)', color: niftyBullish ? '#00e676' : '#ff5252' }}>
                {niftyReturn >= 0 ? '+' : ''}{niftyReturn.toFixed(1)}%
              </span>
              <span className="text-xs font-bold px-2 py-0.5 rounded" style={{ background: niftyBullish ? 'rgba(0,230,118,0.12)' : 'rgba(255,214,0,0.12)', color: niftyBullish ? '#00e676' : '#ffd600', border: `1px solid ${niftyBullish ? 'rgba(0,230,118,0.3)' : 'rgba(255,214,0,0.3)'}` }}>
                {niftyBullish ? '▲ Above 200-EMA' : '▼ Below 200-EMA'}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* ── Autopilot (minimal — inherits settings from above) ── */}
      <div
        className="glass-panel px-4 py-3 rounded-xl flex items-center gap-4 flex-wrap"
        style={{
          border:     autopilotEnabled ? '1px solid rgba(0,230,118,0.4)' : '1px solid rgba(255,255,255,0.1)',
          background: autopilotEnabled ? 'rgba(0,230,118,0.03)' : undefined,
        }}
      >
        {/* Toggle */}
        <span className="text-sm font-black uppercase tracking-widest" style={{ color: autopilotEnabled ? '#00e676' : '#8aa5c0' }}>
          🤖 Autopilot
        </span>
        <button
          onClick={handleAutopilotToggle}
          disabled={autopilotSaving}
          className="relative inline-flex h-6 w-11 items-center rounded-full transition-all"
          style={{
            background: autopilotEnabled ? 'rgba(0,230,118,0.6)' : 'rgba(255,255,255,0.1)',
            border:     autopilotEnabled ? '1px solid rgba(0,230,118,0.8)' : '1px solid rgba(255,255,255,0.2)',
          }}
        >
          <span
            className="inline-block h-4 w-4 rounded-full transition-transform"
            style={{
              background: autopilotEnabled ? '#00e676' : '#8aa5c0',
              transform:  autopilotEnabled ? 'translateX(22px)' : 'translateX(3px)',
              boxShadow:  autopilotEnabled ? '0 0 8px #00e676' : 'none',
            }}
          />
        </button>

        {/* Description — shows current settings */}
        <span className="text-xs text-jarvis-text-secondary">
          {autopilotEnabled
            ? <>Scans daily at 09:20 IST · <span className="text-jarvis-primary font-mono">₹{capital.toLocaleString('en-IN')}</span> × <span className="text-jarvis-primary font-mono">{maxTrades}</span> stocks · <span style={{ color: execMode === 'live' ? '#ff1744' : '#00e5ff' }} className="font-bold">{execMode.toUpperCase()}</span></>
            : 'Off — enable to scan and buy automatically at 09:20 IST each day'}
        </span>

        {/* Last run summary */}
        {autopilotLastRun && autopilotLastResult.executed_count !== undefined && (
          <span className="text-xs text-jarvis-text-secondary">
            · Last run <span className="text-jarvis-primary font-mono">{formatScanTime(autopilotLastRun)}</span>
            {' '}→ <span style={{ color: '#00e676' }} className="font-bold">{autopilotLastResult.executed_count}</span> traded
          </span>
        )}

        {/* Run Now */}
        <button
          onClick={handleRunNow}
          disabled={autopilotRunning || !autopilotEnabled}
          className="ml-auto px-4 py-1.5 text-xs font-bold uppercase rounded-lg transition-all"
          style={{
            background: autopilotEnabled ? 'rgba(0,230,118,0.15)' : 'rgba(255,255,255,0.05)',
            border:     autopilotEnabled ? '1px solid rgba(0,230,118,0.5)' : '1px solid rgba(255,255,255,0.1)',
            color:      autopilotEnabled ? '#00e676' : '#8aa5c0',
            opacity:    autopilotRunning ? 0.6 : 1,
            cursor:     !autopilotEnabled ? 'not-allowed' : 'pointer',
          }}
        >
          {autopilotRunning
            ? <span className="flex items-center gap-1.5"><span className="w-3 h-3 border-2 rounded-full animate-spin" style={{ borderColor: '#00e676', borderTopColor: 'transparent' }} />Running…</span>
            : '▶ Run Now'}
        </button>
      </div>

      {/* ── Regime Warning ── */}
      {regimeWarning && (
        <div className="glass-panel p-4 rounded-xl text-sm font-semibold" style={{ border: '1px solid rgba(255,214,0,0.4)', background: 'rgba(255,214,0,0.06)', color: '#ffd600' }}>
          {regimeWarning}
          <span className="block text-xs font-normal mt-1 text-jarvis-text-secondary">
            Signals still shown — only the strongest setups with high RS scores are advisable in a downtrend.
          </span>
        </div>
      )}

      {error && <div className="glass-panel p-4 border border-red-500/40 text-red-400 text-sm">{error}</div>}

      {/* ── Open Swing Positions ── */}
      {positions.length > 0 && (
        <Card
          title={`Open Positions (${positions.length})`}
          headerAction={
            <div className="flex items-center gap-2">
              <button
                onClick={handleSyncFromBroker}
                className="text-xs px-3 py-1 border border-jarvis-primary/40 text-jarvis-primary rounded hover:bg-jarvis-primary/10 transition-colors"
                title="Import missing positions from Angel One demat holdings"
              >
                ⟳ Sync from Broker
              </button>
              <button
                onClick={handleCloseAll}
                className="text-xs px-3 py-1 border border-red-500/40 text-red-400 rounded hover:bg-red-500/10 transition-colors"
                title="Clear all positions from tracker (use after manually closing in Angel One)"
              >
                ✕ Close All
              </button>
            </div>
          }
        >
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-jarvis-text-secondary border-b border-white/10">
                  <th className="pb-2 text-left">Stock</th>
                  <th className="pb-2 text-right">Entry</th>
                  <th className="pb-2 text-right">CMP</th>
                  <th className="pb-2 text-right">P&L</th>
                  <th className="pb-2 text-right">Stop Loss</th>
                  <th className="pb-2 text-right">Target</th>
                  <th className="pb-2 text-center">Trail</th>
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
                    <td className="py-2.5 text-right font-mono text-green-400">
                      {pos.trailing_active
                        ? <span title="Riding to T2">{formatPrice(pos.target2)} <span style={{ color: '#ffd600', fontSize: 10 }}>T2</span></span>
                        : formatPrice(pos.target1)
                      }
                    </td>
                    <td className="py-2.5 text-center">
                      {pos.trailing_active
                        ? <span title="T1 hit — trailing stop at breakeven" style={{ color: '#ffd600', fontSize: 16 }}>🔒</span>
                        : <span style={{ color: '#8aa5c0' }}>—</span>
                      }
                    </td>
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

      {/* ── Scan results / empty state ── */}
      {scanning ? (
        <div className="flex flex-col items-center justify-center py-16 gap-4">
          <div className="w-10 h-10 border-4 border-jarvis-primary border-t-transparent rounded-full animate-spin" />
          <div className="text-jarvis-primary font-semibold uppercase tracking-widest text-sm">
            Scanning {universe === 'nifty100' ? '~100 Nifty100' : '50 Nifty50'} stocks…
          </div>
          <div className="text-jarvis-text-secondary text-xs">
            Fetching daily OHLCV + computing indicators (~{universe === 'nifty100' ? '30' : '15'}s)
          </div>
        </div>
      ) : signals.length === 0 ? (
        <Card title="Swing Signals">
          <div className="text-center py-12 text-jarvis-text-secondary">
            <div className="text-4xl mb-4">🔍</div>
            <div className="font-semibold">No signals yet</div>
            <div className="text-xs mt-2 mb-6">Click "Run Scan" to scan {universe === 'nifty100' ? 'Nifty100' : 'Nifty50'} for swing trade setups</div>
            {positions.length === 0 && (
              <button
                onClick={handleSyncFromBroker}
                className="text-xs px-4 py-2 border border-jarvis-primary/40 text-jarvis-primary rounded hover:bg-jarvis-primary/10 transition-colors"
              >
                ⟳ Sync Positions from Broker
              </button>
            )}
          </div>
        </Card>
      ) : (
        <Card
          title={`${signals.length} BUY Signal${signals.length !== 1 ? 's' : ''} · ${scanTime ? formatScanTime(scanTime) : ''}`}
          headerAction={
            <button
              onClick={() => setConfirmSym('__top__')}
              disabled={!!executing}
              className="px-4 py-1.5 text-xs font-bold uppercase rounded-lg transition-all"
              style={{ background: 'rgba(0,230,118,0.15)', border: '1px solid rgba(0,230,118,0.4)', color: '#00e676', opacity: executing ? 0.5 : 1 }}
            >
              ⚡ Execute Top {maxTrades}
            </button>
          }
        >
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
                  <th className="pb-3 text-green-400">T1%</th>
                  <th className="pb-3 text-left pl-4">Confidence</th>
                  <th className="pb-3 text-center">RSI</th>
                  <th className="pb-3 text-center">ADX</th>
                  <th className="pb-3 text-center">Vol×</th>
                  <th className="pb-3 text-center" title="20-day return vs Nifty50">RS</th>
                  <th className="pb-3 text-center">Action</th>
                </tr>
              </thead>
              <tbody>
                {signals.map(sig => {
                  const alreadyHeld = positions.some(p => p.symbol === sig.symbol);
                  const isExec      = executing === sig.symbol;
                  return (
                    <tr key={sig.symbol} className="border-b border-white/5 hover:bg-white/5">
                      <td className="py-3">
                        <div className="font-bold text-jarvis-primary">{sig.symbol}</div>
                        <div className="text-jarvis-text-secondary mt-0.5">{sig.name.split(' ').slice(0, 2).join(' ')}</div>
                        <SectorChip sector={sig.sector} />
                      </td>
                      <td className="py-3 text-right font-mono">{formatPrice(sig.close)}</td>
                      <td className="py-3 text-right font-mono text-jarvis-primary">{formatPrice(sig.entry_price)}</td>
                      <td className="py-3 text-right font-mono text-red-400">{formatPrice(sig.stop_loss)}</td>
                      <td className="py-3 text-right font-mono text-green-400">{formatPrice(sig.target1)}</td>
                      <td className="py-3 text-right font-mono text-green-300">{formatPrice(sig.target2)}</td>
                      <td className="py-3 text-right text-orange-400">-{sig.sl_pct}%</td>
                      <td className="py-3 text-right text-green-400 font-mono">
                        +{((sig.target1 - sig.entry_price) / sig.entry_price * 100).toFixed(1)}%
                      </td>
                      <td className="py-3 pl-4 min-w-[120px]">
                        <ConfidenceBar value={sig.confidence} />
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
                      <td className="py-3 text-center">
                        <span style={{ color: sig.rsi >= 50 && sig.rsi <= 70 ? '#00e676' : '#8aa5c0' }}>{sig.rsi.toFixed(0)}</span>
                      </td>
                      <td className="py-3 text-center">
                        <span style={{ color: sig.adx > 25 ? '#00e676' : sig.adx > 20 ? '#ffd600' : '#8aa5c0' }}>{sig.adx.toFixed(0)}</span>
                      </td>
                      <td className="py-3 text-center">
                        <span style={{ color: sig.volume_ratio >= 1.5 ? '#00e676' : sig.volume_ratio >= 1.2 ? '#ffd600' : '#8aa5c0' }}>{sig.volume_ratio.toFixed(1)}×</span>
                      </td>
                      <td className="py-3 text-center font-mono">
                        <span style={{ color: (sig.rs_vs_nifty ?? 0) >= 3 ? '#00e676' : (sig.rs_vs_nifty ?? 0) >= 1 ? '#69f0ae' : (sig.rs_vs_nifty ?? 0) < -2 ? '#ff5252' : '#8aa5c0' }}>
                          {(sig.rs_vs_nifty ?? 0) >= 0 ? '+' : ''}{(sig.rs_vs_nifty ?? 0).toFixed(1)}%
                        </span>
                      </td>
                      <td className="py-3 text-center">
                        {alreadyHeld ? (
                          <span className="text-xs text-green-400 font-semibold">Held</span>
                        ) : (
                          <button
                            onClick={() => setConfirmSym(sig.symbol)}
                            disabled={isExec || !!executing}
                            className="px-3 py-1.5 text-xs font-bold uppercase rounded-lg transition-all"
                            style={{ background: 'rgba(0,229,255,0.15)', border: '1px solid rgba(0,229,255,0.4)', color: '#00e5ff', opacity: executing ? 0.5 : 1 }}
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
