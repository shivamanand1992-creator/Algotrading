import React, { useEffect, useState, useCallback } from 'react';
import { motion, type Variants } from 'framer-motion';
import { marketApi } from '../src/api/client';

// Animation variants
const staggerContainer: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.08 } },
};

const staggerItem: Variants = {
  hidden: { opacity: 0, y: 20 },
  show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: 'easeOut' } },
};

// Types
interface SupportResistance {
  level: number;
  type: 'support' | 'resistance';
  strength: 'weak' | 'moderate' | 'strong';
}

interface IndexLevels {
  symbol: string;
  ltp: number;
  change_pct: number;
  supports: SupportResistance[];
  resistances: SupportResistance[];
  pivot: number;
}

interface SetupAlert {
  id: string;
  timestamp: string;
  symbol: string;
  type: 'breakout' | 'breakdown' | 'reversal' | 'momentum';
  message: string;
  priority: 'low' | 'medium' | 'high';
}

interface MarketStatus {
  is_open: boolean;
  session: 'pre_market' | 'regular' | 'post_market' | 'closed';
  next_open?: string;
  next_close?: string;
}

interface FIIDIIFlow {
  date: string;
  fii_net: number;
  dii_net: number;
  fii_buy: number;
  fii_sell: number;
  dii_buy: number;
  dii_sell: number;
}

// Level Card Component
function LevelCard({ data }: { data: IndexLevels }) {
  const isUp = data.change_pct >= 0;
  const nearestSupport = data.supports[0];
  const nearestResistance = data.resistances[0];

  const getStrengthColor = (strength: string) => {
    switch (strength) {
      case 'strong':
        return '#4ade80';
      case 'moderate':
        return '#fbbf24';
      case 'weak':
        return '#94a3b8';
      default:
        return '#64748b';
    }
  };

  return (
    <div
      className="rounded-2xl p-5 relative overflow-hidden"
      style={{
        background: 'linear-gradient(135deg, rgba(0,8,24,0.97) 0%, rgba(0,20,40,0.97) 100%)',
        border: `1px solid ${isUp ? 'rgba(74,222,128,0.15)' : 'rgba(248,113,113,0.15)'}`,
      }}
    >
      <div className="scan-line" />

      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-bold text-jarvis-primary uppercase tracking-wider">
            {data.symbol}
          </h3>
          <div className="flex items-center gap-3 mt-1">
            <span className="text-2xl font-mono font-black text-jarvis-text-primary tabular-nums">
              {data.ltp.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
            </span>
            <span
              className={`text-sm font-mono font-bold ${
                isUp ? 'text-green-400' : 'text-red-400'
              }`}
            >
              {isUp ? '+' : ''}{data.change_pct.toFixed(2)}%
            </span>
          </div>
        </div>
        <div className="text-right">
          <div className="text-[9px] text-jarvis-text-secondary uppercase tracking-wider mb-1">
            Pivot
          </div>
          <div className="text-lg font-mono font-bold text-purple-400 tabular-nums">
            {data.pivot.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
          </div>
        </div>
      </div>

      {/* Support & Resistance Grid */}
      <div className="grid grid-cols-2 gap-4">
        {/* Resistances */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="text-[9px] font-bold text-red-400 uppercase tracking-wider">
              ▲ Resistance
            </span>
            <div className="flex-1 h-px bg-red-400/20" />
          </div>
          <div className="space-y-1.5">
            {data.resistances.slice(0, 3).map((r, i) => (
              <div
                key={i}
                className="flex items-center justify-between px-3 py-2 rounded-lg"
                style={{
                  background: 'rgba(248,113,113,0.04)',
                  border: '1px solid rgba(248,113,113,0.15)',
                }}
              >
                <div className="flex items-center gap-2">
                  <div
                    className="w-2 h-2 rounded-full"
                    style={{ backgroundColor: getStrengthColor(r.strength) }}
                  />
                  <span className="text-xs font-mono font-bold text-jarvis-text-primary tabular-nums">
                    {r.level.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                  </span>
                </div>
                <span className="text-[9px] font-bold uppercase tracking-wider text-jarvis-text-secondary">
                  {r.strength}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Supports */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="text-[9px] font-bold text-green-400 uppercase tracking-wider">
              ▼ Support
            </span>
            <div className="flex-1 h-px bg-green-400/20" />
          </div>
          <div className="space-y-1.5">
            {data.supports.slice(0, 3).map((s, i) => (
              <div
                key={i}
                className="flex items-center justify-between px-3 py-2 rounded-lg"
                style={{
                  background: 'rgba(74,222,128,0.04)',
                  border: '1px solid rgba(74,222,128,0.15)',
                }}
              >
                <div className="flex items-center gap-2">
                  <div
                    className="w-2 h-2 rounded-full"
                    style={{ backgroundColor: getStrengthColor(s.strength) }}
                  />
                  <span className="text-xs font-mono font-bold text-jarvis-text-primary tabular-nums">
                    {s.level.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                  </span>
                </div>
                <span className="text-[9px] font-bold uppercase tracking-wider text-jarvis-text-secondary">
                  {s.strength}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Distance indicators */}
      <div className="grid grid-cols-2 gap-3 mt-4 pt-3 border-t border-white/5">
        <div className="text-center">
          <div className="text-[9px] text-jarvis-text-secondary uppercase mb-1">
            To Resistance
          </div>
          <div className="text-sm font-mono font-bold text-red-400">
            {nearestResistance
              ? `+${((nearestResistance.level - data.ltp) / data.ltp * 100).toFixed(2)}%`
              : '—'}
          </div>
        </div>
        <div className="text-center">
          <div className="text-[9px] text-jarvis-text-secondary uppercase mb-1">
            To Support
          </div>
          <div className="text-sm font-mono font-bold text-green-400">
            {nearestSupport
              ? `-${((data.ltp - nearestSupport.level) / data.ltp * 100).toFixed(2)}%`
              : '—'}
          </div>
        </div>
      </div>
    </div>
  );
}

// Setup Alert Component
function SetupAlertItem({ alert }: { alert: SetupAlert }) {
  const getPriorityColor = () => {
    switch (alert.priority) {
      case 'high':
        return { bg: 'rgba(255,23,68,0.08)', border: 'rgba(255,23,68,0.3)', text: '#ff1744' };
      case 'medium':
        return { bg: 'rgba(251,191,36,0.08)', border: 'rgba(251,191,36,0.3)', text: '#fbbf24' };
      case 'low':
        return { bg: 'rgba(0,229,255,0.05)', border: 'rgba(0,229,255,0.15)', text: '#00e5ff' };
    }
  };

  const getTypeIcon = () => {
    switch (alert.type) {
      case 'breakout':
        return '📈';
      case 'breakdown':
        return '📉';
      case 'reversal':
        return '🔄';
      case 'momentum':
        return '⚡';
    }
  };

  const colors = getPriorityColor();

  return (
    <div
      className="rounded-lg p-3 flex items-start gap-3"
      style={{ background: colors.bg, border: `1px solid ${colors.border}` }}
    >
      <span className="text-xl">{getTypeIcon()}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-xs font-bold text-jarvis-primary">{alert.symbol}</span>
          <span
            className="text-[9px] font-bold px-1.5 py-0.5 rounded uppercase"
            style={{ backgroundColor: colors.bg, color: colors.text }}
          >
            {alert.type}
          </span>
          <span className="text-[9px] text-jarvis-text-secondary font-mono ml-auto">
            {new Date(alert.timestamp).toLocaleTimeString('en-IN', {
              hour: '2-digit',
              minute: '2-digit',
            })}
          </span>
        </div>
        <p className="text-xs text-jarvis-text-secondary leading-relaxed">{alert.message}</p>
      </div>
    </div>
  );
}

// Market Status Indicator Component
function MarketStatusIndicator({ status }: { status: MarketStatus }) {
  const getSessionColor = () => {
    switch (status.session) {
      case 'regular':
        return { bg: 'rgba(74,222,128,0.15)', border: 'rgba(74,222,128,0.4)', text: '#4ade80' };
      case 'pre_market':
        return { bg: 'rgba(251,191,36,0.15)', border: 'rgba(251,191,36,0.4)', text: '#fbbf24' };
      case 'post_market':
        return { bg: 'rgba(139,92,246,0.15)', border: 'rgba(139,92,246,0.4)', text: '#a78bfa' };
      case 'closed':
        return { bg: 'rgba(248,113,113,0.15)', border: 'rgba(248,113,113,0.4)', text: '#f87171' };
    }
  };

  const colors = getSessionColor();

  return (
    <div
      className="rounded-xl p-4 flex items-center justify-between"
      style={{
        background: colors.bg,
        border: `1px solid ${colors.border}`,
      }}
    >
      <div className="flex items-center gap-3">
        <motion.div
          className="w-3 h-3 rounded-full"
          style={{ backgroundColor: colors.text }}
          animate={
            status.session === 'regular'
              ? { scale: [1, 1.3, 1], opacity: [1, 0.6, 1] }
              : {}
          }
          transition={{ duration: 1.5, repeat: Infinity }}
        />
        <div>
          <div className="text-[10px] font-bold uppercase tracking-wider text-jarvis-text-secondary mb-0.5">
            Market Status
          </div>
          <div className="text-sm font-bold uppercase tracking-wide" style={{ color: colors.text }}>
            {status.session.replace('_', ' ')}
          </div>
        </div>
      </div>
      {(status.next_open || status.next_close) && (
        <div className="text-right">
          <div className="text-[9px] text-jarvis-text-secondary uppercase mb-0.5">
            {status.session === 'closed' ? 'Opens' : 'Closes'}
          </div>
          <div className="text-xs font-mono font-bold text-jarvis-primary">
            {status.session === 'closed' ? status.next_open : status.next_close}
          </div>
        </div>
      )}
    </div>
  );
}

// FII/DII Flow Component
function FIIDIIFlowCard({ data }: { data: FIIDIIFlow }) {
  const fiiNet = data.fii_net;
  const diiNet = data.dii_net;
  const totalNet = fiiNet + diiNet;

  const formatAmount = (amount: number) => {
    const abs = Math.abs(amount);
    if (abs >= 1000) {
      return `₹${(abs / 1000).toFixed(2)}K Cr`;
    }
    return `₹${abs.toFixed(2)} Cr`;
  };

  return (
    <div
      className="rounded-2xl p-5"
      style={{
        background: 'linear-gradient(135deg, rgba(0,8,24,0.97) 0%, rgba(0,20,40,0.97) 100%)',
        border: '1px solid rgba(0,229,255,0.12)',
      }}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <span className="text-base">💹</span>
          <span className="text-xs font-bold tracking-[0.2em] text-jarvis-primary uppercase">
            FII/DII Flow
          </span>
        </div>
        <span className="text-[9px] text-jarvis-text-secondary font-mono">
          {new Date(data.date).toLocaleDateString('en-IN')}
        </span>
      </div>

      {/* Net Flow Summary */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        <div
          className="rounded-lg p-3 text-center"
          style={{
            background: fiiNet >= 0 ? 'rgba(74,222,128,0.08)' : 'rgba(248,113,113,0.08)',
            border: `1px solid ${fiiNet >= 0 ? 'rgba(74,222,128,0.2)' : 'rgba(248,113,113,0.2)'}`,
          }}
        >
          <div className="text-[9px] text-jarvis-text-secondary uppercase mb-1">FII Net</div>
          <div
            className={`text-base font-mono font-bold tabular-nums ${
              fiiNet >= 0 ? 'text-green-400' : 'text-red-400'
            }`}
          >
            {fiiNet >= 0 ? '+' : ''}{formatAmount(fiiNet)}
          </div>
        </div>

        <div
          className="rounded-lg p-3 text-center"
          style={{
            background: diiNet >= 0 ? 'rgba(74,222,128,0.08)' : 'rgba(248,113,113,0.08)',
            border: `1px solid ${diiNet >= 0 ? 'rgba(74,222,128,0.2)' : 'rgba(248,113,113,0.2)'}`,
          }}
        >
          <div className="text-[9px] text-jarvis-text-secondary uppercase mb-1">DII Net</div>
          <div
            className={`text-base font-mono font-bold tabular-nums ${
              diiNet >= 0 ? 'text-green-400' : 'text-red-400'
            }`}
          >
            {diiNet >= 0 ? '+' : ''}{formatAmount(diiNet)}
          </div>
        </div>

        <div
          className="rounded-lg p-3 text-center"
          style={{
            background: totalNet >= 0 ? 'rgba(74,222,128,0.08)' : 'rgba(248,113,113,0.08)',
            border: `1px solid ${totalNet >= 0 ? 'rgba(74,222,128,0.2)' : 'rgba(248,113,113,0.2)'}`,
          }}
        >
          <div className="text-[9px] text-jarvis-text-secondary uppercase mb-1">Total Net</div>
          <div
            className={`text-base font-mono font-bold tabular-nums ${
              totalNet >= 0 ? 'text-green-400' : 'text-red-400'
            }`}
          >
            {totalNet >= 0 ? '+' : ''}{formatAmount(totalNet)}
          </div>
        </div>
      </div>

      {/* Buy/Sell Breakdown */}
      <div className="grid grid-cols-2 gap-4">
        {/* FII */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="text-[9px] font-bold text-jarvis-accent uppercase tracking-wider">
              FII Activity
            </span>
            <div className="flex-1 h-px bg-jarvis-accent/20" />
          </div>
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-xs">
              <span className="text-jarvis-text-secondary">Buy</span>
              <span className="font-mono font-bold text-green-400">
                {formatAmount(data.fii_buy)}
              </span>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-jarvis-text-secondary">Sell</span>
              <span className="font-mono font-bold text-red-400">
                {formatAmount(data.fii_sell)}
              </span>
            </div>
          </div>
        </div>

        {/* DII */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="text-[9px] font-bold text-jarvis-secondary uppercase tracking-wider">
              DII Activity
            </span>
            <div className="flex-1 h-px bg-jarvis-secondary/20" />
          </div>
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-xs">
              <span className="text-jarvis-text-secondary">Buy</span>
              <span className="font-mono font-bold text-green-400">
                {formatAmount(data.dii_buy)}
              </span>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-jarvis-text-secondary">Sell</span>
              <span className="font-mono font-bold text-red-400">
                {formatAmount(data.dii_sell)}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Interpretation */}
      <div
        className="mt-4 p-3 rounded-lg"
        style={{
          background: 'rgba(0,229,255,0.04)',
          border: '1px solid rgba(0,229,255,0.1)',
        }}
      >
        <div className="text-[9px] text-jarvis-primary uppercase tracking-wider mb-1">
          Interpretation
        </div>
        <p className="text-xs text-jarvis-text-secondary leading-relaxed">
          {fiiNet >= 0 && diiNet >= 0
            ? '🟢 Both FII & DII are buyers - Strong bullish sentiment'
            : fiiNet < 0 && diiNet < 0
            ? '🔴 Both FII & DII are sellers - Strong bearish pressure'
            : fiiNet >= 0 && diiNet < 0
            ? '🟡 FII buying, DII selling - Mixed sentiment, foreign inflow'
            : '🟡 DII buying, FII selling - Domestic support, foreign outflow'}
        </p>
      </div>
    </div>
  );
}

// Main Component
export function IntradayDashboard() {
  // Mock data states (replace with actual API calls)
  const [niftyLevels, setNiftyLevels] = useState<IndexLevels>({
    symbol: 'NIFTY 50',
    ltp: 24350.5,
    change_pct: 0.45,
    pivot: 24300,
    resistances: [
      { level: 24400, type: 'resistance', strength: 'strong' },
      { level: 24500, type: 'resistance', strength: 'moderate' },
      { level: 24600, type: 'resistance', strength: 'weak' },
    ],
    supports: [
      { level: 24250, type: 'support', strength: 'strong' },
      { level: 24150, type: 'support', strength: 'moderate' },
      { level: 24050, type: 'support', strength: 'weak' },
    ],
  });

  const [bankNiftyLevels, setBankNiftyLevels] = useState<IndexLevels>({
    symbol: 'BANK NIFTY',
    ltp: 52850.75,
    change_pct: -0.32,
    pivot: 52900,
    resistances: [
      { level: 53000, type: 'resistance', strength: 'strong' },
      { level: 53200, type: 'resistance', strength: 'moderate' },
      { level: 53400, type: 'resistance', strength: 'weak' },
    ],
    supports: [
      { level: 52700, type: 'support', strength: 'strong' },
      { level: 52500, type: 'support', strength: 'moderate' },
      { level: 52300, type: 'support', strength: 'weak' },
    ],
  });

  const [setupAlerts, setSetupAlerts] = useState<SetupAlert[]>([
    {
      id: '1',
      timestamp: new Date().toISOString(),
      symbol: 'RELIANCE',
      type: 'breakout',
      message: 'Breaking above 2850 resistance with strong volume',
      priority: 'high',
    },
    {
      id: '2',
      timestamp: new Date(Date.now() - 300000).toISOString(),
      symbol: 'HDFC Bank',
      type: 'momentum',
      message: 'RSI crossing 60, positive momentum building',
      priority: 'medium',
    },
    {
      id: '3',
      timestamp: new Date(Date.now() - 600000).toISOString(),
      symbol: 'TCS',
      type: 'reversal',
      message: 'Bullish divergence on 15-min chart',
      priority: 'low',
    },
  ]);

  const [marketStatus, setMarketStatus] = useState<MarketStatus>({
    is_open: true,
    session: 'regular',
    next_close: '15:30',
  });

  const [fiiDiiFlow, setFiiDiiFlow] = useState<FIIDIIFlow>({
    date: new Date().toISOString(),
    fii_net: 2456.78,
    dii_net: -1234.56,
    fii_buy: 12345.67,
    fii_sell: 9888.89,
    dii_buy: 8765.43,
    dii_sell: 9999.99,
  });

  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());

  // Fetch market data periodically
  useEffect(() => {
    const fetchData = async () => {
      try {
        // Here you would call your actual API endpoints
        // const marketData = await marketApi.getCurrent();
        // Update states with real data
        setLastUpdated(new Date());
      } catch (error) {
        console.error('Failed to fetch intraday data:', error);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 30000); // Update every 30s

    return () => clearInterval(interval);
  }, []);

  return (
    <motion.div
      className="space-y-5 p-6"
      variants={staggerContainer}
      initial="hidden"
      animate="show"
    >
      {/* Page Header */}
      <motion.div variants={staggerItem} className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-black text-jarvis-primary uppercase tracking-wider mb-1">
            Intraday Command Center
          </h1>
          <p className="text-xs text-jarvis-text-secondary">
            Real-time levels, setups, and market flows
          </p>
        </div>
        <div className="text-right">
          <div className="text-[9px] text-jarvis-text-secondary uppercase mb-1">Last Updated</div>
          <div className="text-xs font-mono text-jarvis-primary">
            {lastUpdated.toLocaleTimeString('en-IN', {
              hour: '2-digit',
              minute: '2-digit',
              second: '2-digit',
              hour12: false,
            })}
          </div>
        </div>
      </motion.div>

      {/* Market Status */}
      <motion.div variants={staggerItem}>
        <MarketStatusIndicator status={marketStatus} />
      </motion.div>

      {/* Index Levels - Nifty & Bank Nifty */}
      <motion.div variants={staggerItem}>
        <div className="flex items-center gap-2 mb-3">
          <span className="text-[10px] font-bold tracking-[0.25em] text-jarvis-primary/50 uppercase">
            Key Index Levels
          </span>
          <div className="flex-1 h-px bg-jarvis-primary/10" />
        </div>
        <div className="grid grid-cols-2 gap-5">
          <LevelCard data={niftyLevels} />
          <LevelCard data={bankNiftyLevels} />
        </div>
      </motion.div>

      {/* Live Setup Alerts & FII/DII Flow */}
      <motion.div variants={staggerItem}>
        <div className="grid grid-cols-2 gap-5">
          {/* Setup Alerts */}
          <div>
            <div className="flex items-center gap-2 mb-3">
              <span className="text-[10px] font-bold tracking-[0.25em] text-jarvis-primary/50 uppercase">
                Live Setup Alerts
              </span>
              <div className="flex-1 h-px bg-jarvis-primary/10" />
              <span
                className="text-[9px] font-bold px-2 py-0.5 rounded-full"
                style={{
                  background: 'rgba(0,229,255,0.1)',
                  color: '#00e5ff',
                }}
              >
                {setupAlerts.length} Active
              </span>
            </div>
            <div
              className="rounded-2xl p-4 space-y-3"
              style={{
                background: 'rgba(0,8,24,0.97)',
                border: '1px solid rgba(0,229,255,0.1)',
                minHeight: '400px',
                maxHeight: '600px',
                overflowY: 'auto',
              }}
            >
              {setupAlerts.length > 0 ? (
                setupAlerts.map((alert) => (
                  <SetupAlertItem key={alert.id} alert={alert} />
                ))
              ) : (
                <div className="flex flex-col items-center justify-center py-12">
                  <div className="text-4xl mb-3">📊</div>
                  <p className="text-xs text-jarvis-text-secondary/70 text-center">
                    No active setups at the moment
                    <br />
                    <span className="text-jarvis-text-secondary/40">
                      Alerts will appear when opportunities are detected
                    </span>
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* FII/DII Flow */}
          <div>
            <div className="flex items-center gap-2 mb-3">
              <span className="text-[10px] font-bold tracking-[0.25em] text-jarvis-primary/50 uppercase">
                Institutional Flow
              </span>
              <div className="flex-1 h-px bg-jarvis-primary/10" />
            </div>
            <FIIDIIFlowCard data={fiiDiiFlow} />
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
}
