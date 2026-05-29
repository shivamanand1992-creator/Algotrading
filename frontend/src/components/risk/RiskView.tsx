import React, { useEffect, useState } from 'react';
import { riskApi } from '../../api/client';
import { Card } from '../ui/Card';
import type { RiskLimits } from '../../types/api';

function LimitBar({ label, used, limit, unit = '' }: { label: string; used: number; limit: number; unit?: string }) {
  const pct = limit > 0 ? Math.min((used / limit) * 100, 100) : 0;
  const color = pct > 80 ? 'bg-red-500' : pct > 50 ? 'bg-yellow-400' : 'bg-green-400';

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-sm">
        <span className="text-jarvis-text-secondary">{label}</span>
        <span className="font-mono text-jarvis-text-primary">
          {unit}{used.toFixed(0)} / {unit}{limit.toFixed(0)} ({pct.toFixed(1)}%)
        </span>
      </div>
      <div className="w-full bg-jarvis-primary/10 rounded-full h-2">
        <div className={`${color} h-2 rounded-full transition-all duration-500`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function EditField({
  label, value, onChange, prefix = '', suffix = '', min = 1, step = 1,
}: {
  label: string; value: string; onChange: (v: string) => void;
  prefix?: string; suffix?: string; min?: number; step?: number;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs text-jarvis-text-secondary uppercase tracking-wider">{label}</label>
      <div className="flex items-center gap-1">
        {prefix && <span className="text-jarvis-text-secondary text-sm">{prefix}</span>}
        <input
          type="number"
          min={min}
          step={step}
          value={value}
          onChange={e => onChange(e.target.value)}
          style={{
            background: 'rgba(0,229,255,0.05)',
            border: '1px solid rgba(0,229,255,0.3)',
            color: '#ffffff',
            fontFamily: "'Courier New', monospace",
            fontSize: 14,
            padding: '6px 10px',
            width: '100%',
            outline: 'none',
          }}
          onFocus={e => { e.target.style.borderColor = 'rgba(0,229,255,0.7)'; }}
          onBlur={e => { e.target.style.borderColor = 'rgba(0,229,255,0.3)'; }}
        />
        {suffix && <span className="text-jarvis-text-secondary text-sm">{suffix}</span>}
      </div>
    </div>
  );
}

export function RiskView() {
  const [limits, setLimits] = useState<RiskLimits | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ text: string; ok: boolean } | null>(null);

  // Edit form state (strings for controlled inputs)
  const [editDailyLimit, setEditDailyLimit] = useState('');
  const [editMaxPos, setEditMaxPos] = useState('');
  const [editPerTrade, setEditPerTrade] = useState('');

  const fetchLimits = async () => {
    try {
      const res = await riskApi.getLimits();
      setLimits(res.data);
    } catch (err) {
      console.error('Failed to fetch risk data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLimits();
    const interval = setInterval(fetchLimits, 15000);
    return () => clearInterval(interval);
  }, []);

  const handleEditOpen = () => {
    if (!limits) return;
    setEditDailyLimit(String(limits.daily_loss_limit));
    setEditMaxPos(String(limits.max_positions));
    setEditPerTrade(String(limits.per_trade_risk_limit));
    setSaveMsg(null);
    setEditing(true);
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveMsg(null);
    try {
      await riskApi.updateLimits({
        daily_loss_limit: parseFloat(editDailyLimit),
        max_positions: parseInt(editMaxPos, 10),
        per_trade_risk_percent: parseFloat(editPerTrade),
      });
      setSaveMsg({ text: 'Limits updated successfully.', ok: true });
      setEditing(false);
      await fetchLimits();
    } catch {
      setSaveMsg({ text: 'Failed to save — check connection.', ok: false });
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-jarvis-primary animate-pulse text-xl">Loading risk metrics...</div>
      </div>
    );
  }

  const safe = !limits || limits.daily_loss_percentage < 50;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-jarvis-primary tracking-widest uppercase">F&amp;O Risk Management</h2>
          <p className="text-xs text-jarvis-text-secondary mt-1 tracking-wider">Daily loss limit and per-trade risk controls for Nifty options</p>
        </div>
        <div className="flex items-center gap-4">
          {saveMsg && (
            <span className={`text-xs font-mono tracking-wider ${saveMsg.ok ? 'text-green-400' : 'text-red-400'}`}>
              {saveMsg.text}
            </span>
          )}
          {!editing && (
            <button
              onClick={handleEditOpen}
              style={{
                padding: '7px 16px',
                background: 'transparent',
                border: '1px solid rgba(0,229,255,0.5)',
                color: 'rgba(0,229,255,0.9)',
                fontSize: 11,
                letterSpacing: 3,
                fontFamily: "'Courier New', monospace",
                cursor: 'pointer',
                transition: 'all 0.2s',
              }}
              onMouseEnter={e => { (e.target as HTMLButtonElement).style.background = 'rgba(0,229,255,0.1)'; }}
              onMouseLeave={e => { (e.target as HTMLButtonElement).style.background = 'transparent'; }}
            >
              EDIT LIMITS
            </button>
          )}
        </div>
      </div>

      {editing && (
        <Card title="Set Risk Limits">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
            <EditField
              label="Daily Loss Limit"
              value={editDailyLimit}
              onChange={setEditDailyLimit}
              prefix="₹"
              min={1000}
              step={500}
            />
            <EditField
              label="Max Open Positions"
              value={editMaxPos}
              onChange={setEditMaxPos}
              min={1}
              step={1}
            />
            <EditField
              label="Per-Trade Risk"
              value={editPerTrade}
              onChange={setEditPerTrade}
              suffix="%"
              min={0.1}
              step={0.1}
            />
          </div>
          <p className="text-xs text-jarvis-text-secondary mb-4">
            Daily Loss Limit: when total losses hit this amount today, the system auto-stops all strategies.
            Per-Trade Risk: max % of capital risked on a single trade.
          </p>
          <div className="flex gap-3">
            <button
              onClick={handleSave}
              disabled={saving}
              style={{
                padding: '8px 20px',
                background: 'rgba(0,229,255,0.15)',
                border: '1px solid rgba(0,229,255,0.6)',
                color: '#00e5ff',
                fontSize: 11,
                letterSpacing: 3,
                fontFamily: "'Courier New', monospace",
                cursor: saving ? 'not-allowed' : 'pointer',
                opacity: saving ? 0.6 : 1,
              }}
            >
              {saving ? 'SAVING...' : 'SAVE'}
            </button>
            <button
              onClick={() => setEditing(false)}
              style={{
                padding: '8px 20px',
                background: 'transparent',
                border: '1px solid rgba(255,255,255,0.2)',
                color: 'rgba(255,255,255,0.6)',
                fontSize: 11,
                letterSpacing: 3,
                fontFamily: "'Courier New', monospace",
                cursor: 'pointer',
              }}
            >
              CANCEL
            </button>
          </div>
        </Card>
      )}

      {limits && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Card className="text-center">
              <div className="text-xs text-jarvis-text-secondary uppercase tracking-wider mb-1">Daily Loss Used</div>
              <div className={`text-2xl font-mono font-bold ${limits.daily_loss_percentage > 80 ? 'text-red-400' : limits.daily_loss_percentage > 50 ? 'text-yellow-400' : 'text-green-400'}`}>
                {limits.daily_loss_percentage.toFixed(2)}%
              </div>
            </Card>
            <Card className="text-center">
              <div className="text-xs text-jarvis-text-secondary uppercase tracking-wider mb-1">Per-Trade Risk</div>
              <div className="text-2xl font-mono font-bold text-jarvis-accent">
                {limits.per_trade_risk_limit}%
              </div>
            </Card>
            <Card className="text-center">
              <div className="text-xs text-jarvis-text-secondary uppercase tracking-wider mb-1">Positions</div>
              <div className="text-2xl font-mono font-bold text-jarvis-primary">
                {limits.current_positions} / {limits.max_positions}
              </div>
            </Card>
          </div>

          <Card title="Limit Usage">
            <div className="space-y-4">
              <LimitBar
                label="Daily Loss Limit"
                used={limits.daily_loss_used}
                limit={limits.daily_loss_limit}
                unit="₹"
              />
              <LimitBar
                label="Position Slots"
                used={limits.current_positions}
                limit={limits.max_positions}
              />
            </div>
          </Card>

          <Card title="System Health">
            <div className={`text-center py-4 font-bold text-lg ${safe ? 'text-green-400' : 'text-yellow-400'}`}>
              {safe ? 'All systems within safe limits' : 'Approaching risk thresholds — monitor closely'}
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
