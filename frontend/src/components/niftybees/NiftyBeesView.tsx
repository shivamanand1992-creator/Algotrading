import React, { useEffect, useState, useCallback } from 'react';
import { niftyBeesApi } from '../../api/client';
import { Card } from '../ui/Card';
import type { NiftyBeesConfig, NiftyBeesPosition, NiftyBeesStatus } from '../../types/api';

// ---------------------------------------------------------------------------
// Helpers
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
  config: NiftyBeesConfig;
  saving: boolean;
  onSave: (cfg: Partial<NiftyBeesConfig>) => void;
  brokerConnected: boolean;
}

function ConfigForm({ config, saving, onSave, brokerConnected }: ConfigFormProps) {
  const [local, setLocal] = useState<NiftyBeesConfig>({ ...config });

  useEffect(() => { setLocal({ ...config }); }, [config]);

  const field = (key: keyof NiftyBeesConfig, label: string, type: 'number' | 'select', opts?: string[]) => (
    <div className="flex flex-col gap-1">
      <label className="text-[10px] uppercase tracking-widest text-jarvis-primary/60">{label}</label>
      {type === 'select' && opts ? (
        <select
          className="bg-black/40 border border-jarvis-primary/30 rounded px-2 py-1.5 text-sm text-white focus:outline-none focus:border-jarvis-primary"
          value={String(local[key])}
          onChange={e => setLocal(p => ({ ...p, [key]: e.target.value }))}
        >
          {opts.map(o => <option key={o} value={o}>{o}</option>)}
        </select>
      ) : (
        <input
          type="number"
          step="any"
          className="bg-black/40 border border-jarvis-primary/30 rounded px-2 py-1.5 text-sm text-white focus:outline-none focus:border-jarvis-primary w-full"
          value={local[key] as number}
          onChange={e => setLocal(p => ({ ...p, [key]: parseFloat(e.target.value) || 0 }))}
        />
      )}
    </div>
  );

  const handleSave = () => {
    if (local.mode === 'live' && !brokerConnected) {
      alert('Broker is not connected — switch to paper mode first.');
      return;
    }
    onSave({ ...local });
  };

  return (
    <div className="grid grid-cols-2 gap-4">
      {field('capital_amount',    'Capital per Buy (₹)', 'number')}
      {field('dip_threshold_pct', 'Nifty Dip Trigger (%)', 'number')}
      {field('target_gain_pct',   'Target Gain (%)', 'number')}
      {field('mode', 'Order Mode', 'select', ['paper', 'live'])}

      <div className="col-span-2 flex justify-end pt-2">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-5 py-2 rounded font-semibold text-sm transition-all"
          style={{
            background:  saving ? 'rgba(0,229,255,0.1)' : 'rgba(0,229,255,0.2)',
            border:      '1px solid rgba(0,229,255,0.5)',
            color:       '#00e5ff',
            cursor:      saving ? 'not-allowed' : 'pointer',
          }}
        >
          {saving ? 'Saving…' : 'Save Config'}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Active position card
// ---------------------------------------------------------------------------

function PositionCard({ pos, onClose }: { pos: NiftyBeesPosition; onClose: () => void }) {
  const pnlPos = pos.pnl_pct >= 0;
  return (
    <div
      className="rounded-xl p-4 border"
      style={{
        background:   'rgba(0,229,255,0.05)',
        borderColor:  pnlPos ? 'rgba(0,230,118,0.4)' : 'rgba(255,82,82,0.4)',
        boxShadow:    pnlPos ? '0 0 20px rgba(0,230,118,0.08)' : '0 0 20px rgba(255,82,82,0.08)',
      }}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <span className="text-lg font-bold text-white">NIFTYBEES ETF</span>
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
          <span className="text-xs bg-green-500/10 text-green-400 border border-green-400/30 px-2 py-0.5 rounded">
            HOLDING
          </span>
        </div>
        <PnLBadge value={pos.pnl_pct} />
      </div>

      <div className="grid grid-cols-3 gap-4 mb-3">
        <Stat label="Qty"         value={`${pos.qty} units`} />
        <Stat label="Entry Price" value={`₹${pos.entry_price.toFixed(2)}`} />
        <Stat label="Current"     value={`₹${(pos.current_price ?? pos.entry_price).toFixed(2)}`} />
        <Stat label="Invested"    value={`₹${pos.invested.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`} />
        <Stat label="Unrealized P&L" value={
          <span style={{ color: pos.unrealized_pnl >= 0 ? '#00e676' : '#ff5252' }}>
            {pos.unrealized_pnl >= 0 ? '+' : ''}₹{pos.unrealized_pnl.toFixed(2)}
          </span>
        } />
        <Stat label="Nifty at Entry" value={`₹${pos.nifty_at_entry.toFixed(0)}`} sub={`Dip: ${pos.nifty_dip_pct.toFixed(2)}%`} />
      </div>

      <div className="flex items-center justify-between text-xs text-jarvis-text-secondary">
        <span>Bought: {pos.entry_date}</span>
        <span>Last checked: {pos.last_checked ?? '—'}</span>
        <button
          onClick={onClose}
          className="text-red-400 hover:text-red-300 border border-red-400/30 hover:border-red-400/60 px-3 py-1 rounded transition-all"
        >
          Close Tracker
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// History table
// ---------------------------------------------------------------------------

function HistoryTable({ history }: { history: NiftyBeesPosition[] }) {
  if (!history.length) return (
    <p className="text-center text-jarvis-text-secondary text-sm py-6">No closed trades yet.</p>
  );
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-jarvis-primary/60 text-[10px] uppercase tracking-wider border-b border-jarvis-primary/10">
            <th className="text-left py-2 pr-3">Entry Date</th>
            <th className="text-right pr-3">Entry ₹</th>
            <th className="text-right pr-3">Exit ₹</th>
            <th className="text-right pr-3">Qty</th>
            <th className="text-right pr-3">P&L ₹</th>
            <th className="text-right pr-3">Gain %</th>
            <th className="text-left">Reason</th>
          </tr>
        </thead>
        <tbody>
          {[...history].reverse().map((h, i) => (
            <tr key={i} className="border-b border-white/5 hover:bg-jarvis-primary/5 transition-colors">
              <td className="py-2 pr-3 text-jarvis-text-secondary text-xs">{h.entry_date?.slice(0, 10)}</td>
              <td className="text-right pr-3 font-mono">₹{h.entry_price.toFixed(2)}</td>
              <td className="text-right pr-3 font-mono">₹{(h.exit_price ?? 0).toFixed(2)}</td>
              <td className="text-right pr-3">{h.qty}</td>
              <td className={`text-right pr-3 font-mono font-bold ${(h.realized_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {(h.realized_pnl ?? 0) >= 0 ? '+' : ''}₹{(h.realized_pnl ?? 0).toFixed(2)}
              </td>
              <td className="text-right pr-3">
                <PnLBadge value={h.gain_pct ?? 0} />
              </td>
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
  const [status, setStatus]   = useState<NiftyBeesStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving]   = useState(false);
  const [checking, setChecking] = useState(false);
  const [error, setError]     = useState('');
  const [lastCheck, setLastCheck] = useState<{ action: string; details: string } | null>(null);

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
    const timer = setInterval(fetchStatus, 60_000);
    return () => clearInterval(timer);
  }, [fetchStatus]);

  const handleToggle = async () => {
    if (!status) return;
    setSaving(true);
    try {
      await niftyBeesApi.updateConfig({ enabled: !status.config.enabled });
      await fetchStatus();
    } catch {
      setError('Failed to toggle autopilot.');
    } finally {
      setSaving(false);
    }
  };

  const handleSaveConfig = async (cfg: Partial<NiftyBeesConfig>) => {
    setSaving(true);
    try {
      await niftyBeesApi.updateConfig(cfg);
      await fetchStatus();
    } catch {
      setError('Failed to save config.');
    } finally {
      setSaving(false);
    }
  };

  const handleManualCheck = async () => {
    setChecking(true);
    setLastCheck(null);
    try {
      const res = await niftyBeesApi.triggerCheck();
      setLastCheck(res.data);
      await fetchStatus();
    } catch {
      setError('Manual check failed.');
    } finally {
      setChecking(false);
    }
  };

  const handleClosePosition = async () => {
    if (!window.confirm('Close / reset the tracked NiftyBees position? Use this if you sold manually.')) return;
    try {
      await niftyBeesApi.closePosition();
      await fetchStatus();
    } catch {
      setError('Failed to close position tracker.');
    }
  };

  const enabled = status?.config?.enabled ?? false;

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-jarvis-primary/40 text-sm tracking-widest">
        LOADING NIFTYBEES AUTOPILOT...
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-wide">NiftyBees ETF Autopilot</h1>
          <p className="text-sm text-jarvis-text-secondary mt-1">
            Auto-buy NIFTYBEES when Nifty dips · Auto-sell at 5% gain
          </p>
        </div>

        {/* Enable / disable toggle */}
        <div className="flex items-center gap-4">
          <button
            onClick={handleManualCheck}
            disabled={checking}
            className="text-sm px-4 py-2 rounded border transition-all"
            style={{
              border:  '1px solid rgba(0,229,255,0.3)',
              color:   checking ? 'rgba(0,229,255,0.4)' : '#00e5ff',
              background: 'rgba(0,229,255,0.05)',
            }}
          >
            {checking ? 'Checking…' : 'Check Now'}
          </button>

          <button
            onClick={handleToggle}
            disabled={saving}
            className="px-5 py-2 rounded-lg font-bold text-sm transition-all"
            style={{
              background:  enabled ? 'rgba(255,82,82,0.2)'    : 'rgba(0,229,255,0.2)',
              border:      enabled ? '1px solid rgba(255,82,82,0.5)' : '1px solid rgba(0,229,255,0.5)',
              color:       enabled ? '#ff5252' : '#00e5ff',
              boxShadow:   enabled ? '0 0 16px rgba(255,82,82,0.2)' : '0 0 16px rgba(0,229,255,0.2)',
            }}
          >
            {enabled ? '◼ Disable Autopilot' : '▶ Enable Autopilot'}
          </button>
        </div>
      </div>

      {error && (
        <div className="text-red-400 text-sm bg-red-400/10 border border-red-400/30 rounded px-4 py-2">
          {error}
        </div>
      )}

      {lastCheck && lastCheck.action !== 'none' && (
        <div
          className="text-sm rounded px-4 py-2 border"
          style={{
            background:  'rgba(0,229,255,0.06)',
            borderColor: 'rgba(0,229,255,0.25)',
            color:       '#a0c4e0',
          }}
        >
          <span className="text-jarvis-primary font-semibold">Last check: </span>
          {lastCheck.action.toUpperCase()} — {lastCheck.details}
        </div>
      )}

      {/* Status strip */}
      <Card>
        <div className="flex items-center gap-8 flex-wrap">
          <div className="flex items-center gap-2">
            <div
              className="w-2.5 h-2.5 rounded-full"
              style={{
                background: enabled ? '#00e676' : '#666',
                boxShadow:  enabled ? '0 0 8px #00e676' : 'none',
              }}
            />
            <span className="text-sm font-semibold" style={{ color: enabled ? '#00e676' : '#666' }}>
              {enabled ? 'AUTOPILOT ON' : 'AUTOPILOT OFF'}
            </span>
          </div>
          {status?.config && (
            <>
              <Stat label="Capital" value={`₹${status.config.capital_amount.toLocaleString('en-IN')}`} />
              <Stat label="Dip Trigger" value={`${status.config.dip_threshold_pct}%`} />
              <Stat label="Target Gain" value={`${status.config.target_gain_pct}%`} />
              <Stat label="Mode" value={
                <span style={{ color: status.config.mode === 'live' ? '#ff4081' : '#00e5ff' }}>
                  {status.config.mode.toUpperCase()}
                </span>
              } />
              <Stat
                label="Strategy"
                value="Buy Dip, Hold for Target"
                sub="No time limit — days to weeks"
              />
            </>
          )}
        </div>
      </Card>

      {/* Active position */}
      {status?.position?.active && (
        <section>
          <h2 className="text-sm font-semibold text-jarvis-primary/70 uppercase tracking-widest mb-3">
            Open Position
          </h2>
          <PositionCard pos={status.position} onClose={handleClosePosition} />
        </section>
      )}

      {!status?.position?.active && (
        <div
          className="rounded-xl border border-dashed border-jarvis-primary/20 p-8 text-center"
          style={{ background: 'rgba(0,229,255,0.02)' }}
        >
          <div className="text-3xl mb-2">📊</div>
          <p className="text-jarvis-text-secondary text-sm">
            No active position — autopilot will buy when Nifty drops ≥{' '}
            <strong className="text-jarvis-primary">{status?.config?.dip_threshold_pct ?? 1}%</strong>
          </p>
          <p className="text-xs text-jarvis-text-secondary/60 mt-1">
            Checks every 60 seconds during market hours (09:15–15:30 IST)
          </p>
        </div>
      )}

      {/* Config editor */}
      <Card>
        <h2 className="text-sm font-semibold text-jarvis-primary/70 uppercase tracking-widest mb-4">
          Configuration
        </h2>
        {status?.config && (
          <ConfigForm
            config={status.config}
            saving={saving}
            onSave={handleSaveConfig}
            brokerConnected={true}
          />
        )}
      </Card>

      {/* How it works */}
      <Card>
        <h2 className="text-sm font-semibold text-jarvis-primary/70 uppercase tracking-widest mb-3">
          How It Works
        </h2>
        <ol className="space-y-2 text-sm text-jarvis-text-secondary">
          <li className="flex gap-3">
            <span className="text-jarvis-primary font-bold shrink-0">1.</span>
            Every morning at 09:15 IST, the system wakes up and begins monitoring.
          </li>
          <li className="flex gap-3">
            <span className="text-jarvis-primary font-bold shrink-0">2.</span>
            It fetches the previous day's Nifty50 closing price and the live intraday price.
          </li>
          <li className="flex gap-3">
            <span className="text-jarvis-primary font-bold shrink-0">3.</span>
            If Nifty drops ≥ <strong className="text-white">{status?.config?.dip_threshold_pct ?? 1}%</strong> from
            yesterday's close, it buys NIFTYBEES ETF for ₹{status?.config?.capital_amount?.toLocaleString('en-IN') ?? '10,000'}.
          </li>
          <li className="flex gap-3">
            <span className="text-jarvis-primary font-bold shrink-0">4.</span>
            The position is tracked across days — no forced exit. It sells automatically when
            the gain reaches <strong className="text-white">{status?.config?.target_gain_pct ?? 5}%</strong> (could be 2 days, 10 days, or a month).
          </li>
          <li className="flex gap-3">
            <span className="text-jarvis-primary font-bold shrink-0">5.</span>
            Only one position at a time. Once sold, the system waits for the next dip.
          </li>
        </ol>
      </Card>

      {/* Trade history */}
      {status?.history && status.history.length > 0 && (
        <Card>
          <h2 className="text-sm font-semibold text-jarvis-primary/70 uppercase tracking-widest mb-4">
            Closed Trades
          </h2>
          <HistoryTable history={status.history} />
        </Card>
      )}
    </div>
  );
}
