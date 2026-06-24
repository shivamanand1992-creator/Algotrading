import React, { useEffect, useState, useCallback } from 'react';
import { niftyBeesApi } from '../../api/client';
import { Card } from '../ui/Card';
import type { NiftyBeesConfig, NiftyBeesBuyEntry, NiftyBeesPosition, NiftyBeesStatus } from '../../types/api';
import { useBalanceVisibility, maskAmount } from '../../context/BalanceVisibilityContext';

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function PnLBadge({ value }: { value: number }) {
  const pos = value >= 0;
  return (
    <span
      className="text-xs font-bold px-2 py-0.5 rounded"
      style={{
        background: pos ? 'rgba(0,230,118,0.15)' : 'rgba(255,82,82,0.15)',
        color:      pos ? '#00e676' : '#ff5252',
      }}
    >
      {pos ? '+' : ''}{value.toFixed(2)}%
    </span>
  );
}

function Stat({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] text-jarvis-primary/50 uppercase tracking-widest mb-1">{label}</span>
      <span className="text-sm font-mono text-white">{value}</span>
      {sub && <span className="text-[10px] text-jarvis-text-secondary mt-0.5">{sub}</span>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Config panel
// ---------------------------------------------------------------------------

interface ConfigFormProps {
  config:  NiftyBeesConfig;
  saving:  boolean;
  onSave:  (cfg: Partial<NiftyBeesConfig>) => void;
}

function ConfigForm({ config, saving, onSave }: ConfigFormProps) {
  const [local, setLocal] = useState<NiftyBeesConfig>({ ...config });
  useEffect(() => { setLocal({ ...config }); }, [config]);

  const numField = (key: keyof NiftyBeesConfig, label: string, step = 'any') => (
    <div className="flex flex-col gap-1">
      <label className="text-[10px] uppercase tracking-widest text-jarvis-primary/60">{label}</label>
      <input
        type="number" step={step}
        className="bg-black/40 border border-jarvis-primary/30 rounded px-2 py-1.5 text-sm text-white focus:outline-none focus:border-jarvis-primary w-full"
        value={local[key] as number}
        onChange={e => setLocal(p => ({ ...p, [key]: parseFloat(e.target.value) || 0 }))}
      />
    </div>
  );

  return (
    <div className="grid grid-cols-2 gap-4">
      {numField('capital_amount',    'Capital per Buy Chunk (₹)')}
      {numField('dip_threshold_pct', 'Nifty Dip Trigger (%)')}
      {numField('target_gain_pct',   'Avg Gain to Sell All (%)')}

      <div className="flex flex-col gap-1">
        <label className="text-[10px] uppercase tracking-widest text-jarvis-primary/60">Order Mode</label>
        <select
          className="bg-black/40 border border-jarvis-primary/30 rounded px-2 py-1.5 text-sm text-white focus:outline-none focus:border-jarvis-primary"
          value={local.mode}
          onChange={e => setLocal(p => ({ ...p, mode: e.target.value as 'paper' | 'live' }))}
        >
          <option value="paper">paper</option>
          <option value="live">live</option>
        </select>
      </div>

      <div className="col-span-2 flex justify-end pt-2">
        <button
          onClick={() => onSave({ ...local })}
          disabled={saving}
          className="px-5 py-2 rounded font-semibold text-sm transition-all"
          style={{
            background: saving ? 'rgba(0,229,255,0.1)' : 'rgba(0,229,255,0.2)',
            border: '1px solid rgba(0,229,255,0.5)',
            color: '#00e5ff',
            cursor: saving ? 'not-allowed' : 'pointer',
          }}
        >
          {saving ? 'Saving…' : 'Save Config'}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Active DCA position card
// ---------------------------------------------------------------------------

function BuysTable({ buys }: { buys: NiftyBeesBuyEntry[] }) {
  const { balVisible } = useBalanceVisibility();
  const M = (v: string) => maskAmount(v, balVisible);
  if (!buys?.length) return null;
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-jarvis-primary/40 uppercase tracking-widest border-b border-white/5">
            <th className="text-left py-1.5 pr-3">#</th>
            <th className="text-left py-1.5 pr-3">Date</th>
            <th className="text-right pr-3">Qty</th>
            <th className="text-right pr-3">Buy Price</th>
            <th className="text-right pr-3">Invested</th>
            <th className="text-right pr-3">Nifty Dip</th>
          </tr>
        </thead>
        <tbody>
          {buys.map((b, i) => (
            <tr key={i} className="border-b border-white/5 hover:bg-white/5">
              <td className="py-1.5 pr-3 text-jarvis-primary/50">{i + 1}</td>
              <td className="pr-3 text-jarvis-text-secondary">{b.date?.slice(0, 10)}</td>
              <td className="text-right pr-3 font-mono text-white">{b.qty}</td>
              <td className="text-right pr-3 font-mono text-white">₹{b.price.toFixed(2)}</td>
              <td className="text-right pr-3 font-mono text-jarvis-text-secondary">{M(`₹${b.invested.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`)}</td>
              <td className="text-right pr-3">
                <span className="text-orange-400">▼{b.nifty_dip_pct.toFixed(2)}%</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PositionCard({ pos, onClose }: { pos: NiftyBeesPosition; onClose: () => void }) {
  const { balVisible } = useBalanceVisibility();
  const M = (v: string) => maskAmount(v, balVisible);
  const pnlPos = pos.pnl_pct >= 0;
  const numBuys = pos.buys?.length ?? 0;

  return (
    <div
      className="rounded-xl p-4 border"
      style={{
        background:  'rgba(0,229,255,0.04)',
        borderColor: pnlPos ? 'rgba(0,230,118,0.4)' : 'rgba(255,82,82,0.4)',
        boxShadow:   pnlPos ? '0 0 20px rgba(0,230,118,0.07)' : '0 0 20px rgba(255,82,82,0.07)',
      }}
    >
      {/* Header row */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <span className="text-lg font-bold text-white">NIFTYBEES ETF</span>
          <span className="text-xs bg-green-500/10 text-green-400 border border-green-400/30 px-2 py-0.5 rounded">
            {numBuys} BUY{numBuys !== 1 ? 'S' : ''} — DCA ACTIVE
          </span>
          <span
            className="text-xs px-2 py-0.5 rounded font-semibold"
            style={{
              background: pos.mode === 'live' ? 'rgba(255,64,129,0.15)' : 'rgba(0,229,255,0.12)',
              color:      pos.mode === 'live' ? '#ff4081' : '#00e5ff',
              border:     pos.mode === 'live' ? '1px solid rgba(255,64,129,0.3)' : '1px solid rgba(0,229,255,0.3)',
            }}
          >
            {pos.mode.toUpperCase()}
          </span>
        </div>
        <PnLBadge value={pos.pnl_pct} />
      </div>

      {/* Key metrics */}
      <div className="grid grid-cols-4 gap-4 mb-2">
        <Stat label="Total Units"    value={`${pos.total_qty}`} />
        <Stat label="Avg Entry"      value={`₹${pos.avg_entry_price.toFixed(2)}`} />
        <Stat label="Current Price"  value={`₹${(pos.current_price ?? pos.avg_entry_price).toFixed(2)}`} />
        <Stat
          label="Unrealized P&L"
          value={
            <span style={{ color: pos.unrealized_pnl >= 0 ? '#00e676' : '#ff5252' }}>
              {pos.unrealized_pnl >= 0 ? '+' : ''}{M(`₹${pos.unrealized_pnl.toFixed(2)}`)}
            </span>
          }
        />
        <Stat
          label="Total Invested"
          value={M(`₹${pos.total_invested.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`)}
        />
        <Stat
          label="Target @ 5%"
          value={`₹${(pos.avg_entry_price * (1 + (pos.avg_entry_price > 0 ? 0.05 : 0))).toFixed(2)}`}
          sub="avg × 1.05"
        />
        <Stat label="Last Buy"   value={pos.last_buy_date ?? '—'} />
        <Stat label="Checked"    value={pos.last_checked?.slice(11, 16) ?? '—'} sub={pos.last_checked?.slice(0, 10)} />
      </div>

      {/* Progress bar: avg gain toward target */}
      {(() => {
        const target = 5;
        const pct    = Math.min(100, Math.max(0, (pos.pnl_pct / target) * 100));
        const col    = pct >= 100 ? '#00e676' : pct >= 60 ? '#ffd600' : '#00e5ff';
        return (
          <div className="my-3">
            <div className="flex justify-between text-[10px] text-jarvis-text-secondary mb-1">
              <span>Progress to target ({pos.pnl_pct.toFixed(2)}% of {target}%)</span>
              <span style={{ color: col }}>{pct.toFixed(0)}%</span>
            </div>
            <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-1000"
                style={{ width: `${pct}%`, background: col, boxShadow: `0 0 6px ${col}` }}
              />
            </div>
          </div>
        );
      })()}

      {/* Individual buys table */}
      <BuysTable buys={pos.buys} />

      <div className="flex justify-end mt-3">
        <button
          onClick={onClose}
          className="text-red-400 hover:text-red-300 border border-red-400/30 hover:border-red-400/60 px-3 py-1 rounded text-xs transition-all"
        >
          Reset Tracker
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Closed trade history
// ---------------------------------------------------------------------------

function HistoryTable({ history }: { history: NiftyBeesPosition[] }) {
  const { balVisible } = useBalanceVisibility();
  const M = (v: string) => maskAmount(v, balVisible);
  if (!history.length) return (
    <p className="text-center text-jarvis-text-secondary text-sm py-6">No closed trades yet.</p>
  );
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-jarvis-primary/60 text-[10px] uppercase tracking-wider border-b border-jarvis-primary/10">
            <th className="text-left py-2 pr-3">Exit Date</th>
            <th className="text-right pr-3">Buys</th>
            <th className="text-right pr-3">Units</th>
            <th className="text-right pr-3">Avg Entry</th>
            <th className="text-right pr-3">Exit ₹</th>
            <th className="text-right pr-3">P&L ₹</th>
            <th className="text-right pr-3">Gain %</th>
            <th className="text-left">Reason</th>
          </tr>
        </thead>
        <tbody>
          {[...history].reverse().map((h, i) => (
            <tr key={i} className="border-b border-white/5 hover:bg-jarvis-primary/5 transition-colors">
              <td className="py-2 pr-3 text-jarvis-text-secondary text-xs">{h.exit_date?.slice(0, 10) ?? '—'}</td>
              <td className="text-right pr-3">{h.buys?.length ?? 1}</td>
              <td className="text-right pr-3 font-mono">{h.total_qty}</td>
              <td className="text-right pr-3 font-mono">₹{h.avg_entry_price.toFixed(2)}</td>
              <td className="text-right pr-3 font-mono">₹{(h.exit_price ?? 0).toFixed(2)}</td>
              <td className={`text-right pr-3 font-mono font-bold ${(h.realized_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {(h.realized_pnl ?? 0) >= 0 ? '+' : ''}{M(`₹${(h.realized_pnl ?? 0).toFixed(2)}`)}
              </td>
              <td className="text-right pr-3"><PnLBadge value={h.gain_pct ?? 0} /></td>
              <td className="text-xs text-jarvis-text-secondary capitalize">{h.close_reason?.replace(/_/g, ' ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main view
// ---------------------------------------------------------------------------

export function NiftyBeesView() {
  const [status,   setStatus]   = useState<NiftyBeesStatus | null>(null);
  const [loading,  setLoading]  = useState(true);
  const [saving,   setSaving]   = useState(false);
  const [checking, setChecking] = useState(false);
  const [error,    setError]    = useState('');
  const [lastAction, setLastAction] = useState<{ action: string; details: string } | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await niftyBeesApi.getStatus();
      setStatus(res.data);
      setError('');
    } catch {
      setError('Failed to load NiftyBees status.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const t = setInterval(fetchStatus, 60_000);
    return () => clearInterval(t);
  }, [fetchStatus]);

  const handleToggle = async () => {
    if (!status) return;
    setSaving(true);
    try {
      await niftyBeesApi.updateConfig({ enabled: !status.config.enabled });
      await fetchStatus();
    } catch { setError('Failed to toggle autopilot.'); }
    finally  { setSaving(false); }
  };

  const handleSaveConfig = async (cfg: Partial<NiftyBeesConfig>) => {
    setSaving(true);
    try {
      await niftyBeesApi.updateConfig(cfg);
      await fetchStatus();
    } catch { setError('Failed to save config.'); }
    finally  { setSaving(false); }
  };

  const handleManualCheck = async () => {
    setChecking(true);
    setLastAction(null);
    try {
      const res = await niftyBeesApi.triggerCheck();
      setLastAction(res.data);
      await fetchStatus();
    } catch { setError('Manual check failed.'); }
    finally  { setChecking(false); }
  };

  const handleClosePosition = async () => {
    if (!window.confirm('Reset the tracked NiftyBees position? Use this if you sold manually in Angel One.')) return;
    try {
      await niftyBeesApi.closePosition();
      await fetchStatus();
    } catch { setError('Failed to reset position tracker.'); }
  };

  const enabled  = status?.config?.enabled ?? false;
  const position = status?.position;
  const numBuys  = position?.buys?.length ?? 0;

  if (loading) return (
    <div className="flex items-center justify-center h-64 text-jarvis-primary/40 text-sm tracking-widest">
      LOADING NIFTYBEES AUTOPILOT...
    </div>
  );

  return (
    <div className="p-6 space-y-6">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-wide">NiftyBees ETF Autopilot</h1>
          <p className="text-sm text-jarvis-text-secondary mt-1">
            DCA buy on each Nifty dip · Sell all when avg gain ≥ target
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={handleManualCheck} disabled={checking}
            className="text-sm px-4 py-2 rounded border transition-all"
            style={{ border: '1px solid rgba(0,229,255,0.3)', color: checking ? 'rgba(0,229,255,0.4)' : '#00e5ff', background: 'rgba(0,229,255,0.05)' }}
          >
            {checking ? 'Checking…' : 'Check Now'}
          </button>
          <button
            onClick={handleToggle} disabled={saving}
            className="px-5 py-2 rounded-lg font-bold text-sm transition-all"
            style={{
              background: enabled ? 'rgba(255,82,82,0.2)'    : 'rgba(0,229,255,0.2)',
              border:     enabled ? '1px solid rgba(255,82,82,0.5)' : '1px solid rgba(0,229,255,0.5)',
              color:      enabled ? '#ff5252' : '#00e5ff',
              boxShadow:  enabled ? '0 0 16px rgba(255,82,82,0.2)' : '0 0 16px rgba(0,229,255,0.2)',
            }}
          >
            {enabled ? '◼ Disable Autopilot' : '▶ Enable Autopilot'}
          </button>
        </div>
      </div>

      {error && (
        <div className="text-red-400 text-sm bg-red-400/10 border border-red-400/30 rounded px-4 py-2">{error}</div>
      )}

      {lastAction && !['none', 'watching'].includes(lastAction.action) && (
        <div className="text-sm rounded px-4 py-2 border" style={{ background: 'rgba(0,229,255,0.06)', borderColor: 'rgba(0,229,255,0.25)', color: '#a0c4e0' }}>
          <span className="text-jarvis-primary font-semibold">Last check: </span>
          {lastAction.action.toUpperCase()} — {lastAction.details}
        </div>
      )}

      {/* Status strip */}
      <Card>
        <div className="flex items-center gap-8 flex-wrap">
          <div className="flex items-center gap-2">
            <div className="w-2.5 h-2.5 rounded-full" style={{ background: enabled ? '#00e676' : '#555', boxShadow: enabled ? '0 0 8px #00e676' : 'none' }} />
            <span className="text-sm font-semibold" style={{ color: enabled ? '#00e676' : '#666' }}>
              {enabled ? 'AUTOPILOT ON' : 'AUTOPILOT OFF'}
            </span>
          </div>
          {status?.config && (
            <>
              <Stat label="Per-Chunk Capital" value={`₹${status.config.capital_amount.toLocaleString('en-IN')}`} />
              <Stat label="Dip Trigger"       value={`≥${status.config.dip_threshold_pct}%`} sub="from prev close" />
              <Stat label="Sell Trigger"      value={`≥${status.config.target_gain_pct}%`}   sub="avg entry gain" />
              <Stat label="Mode"              value={<span style={{ color: status.config.mode === 'live' ? '#ff4081' : '#00e5ff' }}>{status.config.mode.toUpperCase()}</span>} />
              {position?.active && (
                <Stat label="Buys Accumulated" value={`${numBuys} day${numBuys !== 1 ? 's' : ''}`} sub={`avg ₹${position.avg_entry_price.toFixed(2)}`} />
              )}
            </>
          )}
        </div>
      </Card>

      {/* Active DCA position */}
      {position?.active ? (
        <section>
          <h2 className="text-sm font-semibold text-jarvis-primary/70 uppercase tracking-widest mb-3">Open Position</h2>
          <PositionCard pos={position} onClose={handleClosePosition} />
        </section>
      ) : (
        <div className="rounded-xl border border-dashed border-jarvis-primary/20 p-8 text-center" style={{ background: 'rgba(0,229,255,0.02)' }}>
          <div className="text-3xl mb-2">🐝</div>
          <p className="text-jarvis-text-secondary text-sm">
            No active position — system will buy when Nifty dips ≥{' '}
            <strong className="text-jarvis-primary">{status?.config?.dip_threshold_pct ?? 1}%</strong>
          </p>
          <p className="text-xs text-jarvis-text-secondary/60 mt-1">Checks every 60 s during 09:15–15:30 IST · One buy chunk per calendar day</p>
        </div>
      )}

      {/* Config editor */}
      <Card>
        <h2 className="text-sm font-semibold text-jarvis-primary/70 uppercase tracking-widest mb-4">Configuration</h2>
        {status?.config && <ConfigForm config={status.config} saving={saving} onSave={handleSaveConfig} />}
      </Card>

      {/* How it works */}
      <Card>
        <h2 className="text-sm font-semibold text-jarvis-primary/70 uppercase tracking-widest mb-3">Strategy Logic</h2>
        <ol className="space-y-2 text-sm text-jarvis-text-secondary">
          <li className="flex gap-3">
            <span className="text-jarvis-primary font-bold shrink-0">1.</span>
            Each day Nifty drops ≥ <strong className="text-white">{status?.config?.dip_threshold_pct ?? 1}%</strong> from the previous close, the system buys ₹{status?.config?.capital_amount?.toLocaleString('en-IN') ?? '10,000'} of NIFTYBEES ETF (CNC delivery). Only one buy per calendar day.
          </li>
          <li className="flex gap-3">
            <span className="text-jarvis-primary font-bold shrink-0">2.</span>
            If tomorrow Nifty dips again, another chunk is added. The blended average entry price updates after every buy.
          </li>
          <li className="flex gap-3">
            <span className="text-jarvis-primary font-bold shrink-0">3.</span>
            The system checks live NIFTYBEES LTP every 60 seconds. When the current price is ≥ <strong className="text-white">{status?.config?.target_gain_pct ?? 5}%</strong> above the average entry, it sells <em>all accumulated units</em> in one DELIVERY order.
          </li>
          <li className="flex gap-3">
            <span className="text-jarvis-primary font-bold shrink-0">4.</span>
            No fixed time limit — the position can span 2 days, 10 days, or a month. After a full exit, the cycle restarts on the next dip.
          </li>
        </ol>
      </Card>

      {/* History */}
      {!!status?.history?.length && (
        <Card>
          <h2 className="text-sm font-semibold text-jarvis-primary/70 uppercase tracking-widest mb-4">Closed Trades</h2>
          <HistoryTable history={status.history} />
        </Card>
      )}
    </div>
  );
}
