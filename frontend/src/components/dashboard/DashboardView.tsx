import React, { useEffect, useState, useRef } from 'react';
import { motion, type Variants } from 'framer-motion';
import { AreaChart, Area, ResponsiveContainer } from 'recharts';
import { CircularWidget } from '../ui/CircularWidget';
import { Card } from '../ui/Card';
import { useWebSocket } from '../../hooks/useWebSocket';
import { positionsApi, marketApi, riskApi, trainingApi, stocksApi } from '../../api/client';
import { formatCurrency, formatPercent } from '../../utils/formatters';
import type { PortfolioSummary, MarketData, RiskLimits, TrainStatus, SwingPosition } from '../../types/api';

const staggerContainer: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.08 } },
};

const staggerItem: Variants = {
  hidden: { opacity: 0, y: 24 },
  show:   { opacity: 1, y: 0, transition: { duration: 0.45, ease: 'easeOut' } },
};

const SPARKLINE_MAX = 80;

export function DashboardView() {
  const { connected, positions, marketData: wsMarketData } = useWebSocket();
  const [portfolio, setPortfolio]   = useState<PortfolioSummary | null>(null);
  const [marketData, setMarketData] = useState<MarketData | null>(null);
  const [riskLimits, setRiskLimits] = useState<RiskLimits | null>(null);
  const [sparkline, setSparkline]   = useState<{ v: number }[]>([]);
  const [trainStatus, setTrainStatus] = useState<TrainStatus | null>(null);
  const [swingPositions, setSwingPositions] = useState<SwingPosition[]>([]);
  const [trainStarting, setTrainStarting] = useState(false);
  const trainPollerRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [pRes, mRes, rRes, swRes] = await Promise.all([
          positionsApi.getPortfolio(),
          marketApi.getCurrent(),
          riskApi.getLimits(),
          stocksApi.getPositions(),
        ]);
        setPortfolio(pRes.data);
        setMarketData(mRes.data);
        setRiskLimits(rRes.data);
        setSwingPositions(Array.isArray(swRes.data) ? swRes.data : []);
      } catch (e) {
        console.error('Dashboard fetch error:', e);
      }
    };
    fetchData();
    const iv = setInterval(fetchData, 5000);
    return () => clearInterval(iv);
  }, []);

  // Poll training status
  useEffect(() => {
    const poll = async () => {
      try {
        const res = await trainingApi.getStatus();
        setTrainStatus(res.data);
      } catch {}
    };
    poll();
    trainPollerRef.current = setInterval(poll, 5000);
    return () => { if (trainPollerRef.current) clearInterval(trainPollerRef.current); };
  }, []);

  // Build sparkline from WS ticks
  useEffect(() => {
    if (wsMarketData) {
      setMarketData(wsMarketData);
      setSparkline(prev => {
        const next = [...prev, { v: wsMarketData.ltp }];
        return next.length > SPARKLINE_MAX ? next.slice(-SPARKLINE_MAX) : next;
      });
    }
  }, [wsMarketData]);

  const handleTrainNow = async () => {
    setTrainStarting(true);
    try { await trainingApi.start(60); } catch {}
    setTrainStarting(false);
  };

  const pnl        = portfolio?.total_pnl ?? 0;
  const pnlColor   = pnl >= 0 ? 'green' : 'red';
  const change     = marketData?.change ?? 0;
  const changePct  = marketData?.change_percentage ?? 0;

  return (
    <motion.div
      className="space-y-6"
      variants={staggerContainer}
      initial="hidden"
      animate="show"
    >
      {/* Header row */}
      <motion.div variants={staggerItem} className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-black text-jarvis-primary glow-text tracking-widest neon-flicker">
            COMMAND CENTER
          </h2>
          <p className="text-xs text-jarvis-text-secondary mt-1 tracking-wider">
            Real-time trading intelligence dashboard
          </p>
        </div>
        <motion.div
          className="flex items-center gap-2 px-4 py-2 rounded-full border border-jarvis-primary/20 bg-jarvis-primary/5"
          animate={connected ? { borderColor: ['rgba(0,229,255,0.2)', 'rgba(0,229,255,0.5)', 'rgba(0,229,255,0.2)'] } : {}}
          transition={{ duration: 2, repeat: Infinity }}
        >
          <motion.div
            className={`w-2.5 h-2.5 rounded-full ${connected ? 'bg-green-400' : 'bg-red-500'}`}
            animate={connected ? { scale: [1, 1.3, 1], opacity: [1, 0.6, 1] } : {}}
            transition={{ duration: 1.5, repeat: Infinity }}
          />
          <span className="text-xs font-mono text-jarvis-text-secondary uppercase tracking-widest">
            {connected ? 'Live Stream' : 'Disconnected'}
          </span>
        </motion.div>
      </motion.div>

      {/* Circular KPI widgets */}
      <motion.div variants={staggerItem}>
        <motion.div
          className="glass-panel py-10 px-6 neon-border"
          style={{ perspective: 1000 }}
        >
          <div className="scan-line" />
          <div className="grid grid-cols-4 gap-8 items-center">
            <CircularWidget
              title="Total P&L"
              value={formatCurrency(pnl)}
              progress={Math.min(Math.abs(portfolio?.total_pnl_percentage ?? 0), 100)}
              size="lg"
              color={pnlColor as any}
            />
            <CircularWidget
              title="Daily P&L"
              value={formatPercent(portfolio?.daily_pnl_percentage ?? 0)}
              progress={Math.abs(portfolio?.daily_pnl_percentage ?? 0)}
              size="md"
              color={(portfolio?.daily_pnl_percentage ?? 0) >= 0 ? 'green' : 'red'}
            />
            <CircularWidget
              title="Capital Used"
              value={formatPercent(
                portfolio ? (portfolio.used_capital / portfolio.total_capital) * 100 : 0
              )}
              progress={portfolio ? (portfolio.used_capital / portfolio.total_capital) * 100 : 0}
              size="md"
              color="primary"
            />
            <CircularWidget
              title="Positions"
              value={portfolio?.open_positions_count ?? 0}
              unit="active"
              progress={
                riskLimits
                  ? ((portfolio?.open_positions_count ?? 0) / riskLimits.max_positions) * 100
                  : 0
              }
              size="md"
              color="yellow"
            />
          </div>
        </motion.div>
      </motion.div>

      {/* Sparkline + Training */}
      <motion.div variants={staggerItem} className="grid grid-cols-2 gap-6">
        {/* Nifty Sparkline */}
        <div className="rounded-xl p-4" style={{ background: 'rgba(0,15,35,0.7)', border: '1px solid rgba(0,229,255,0.15)' }}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-bold text-jarvis-text-secondary uppercase tracking-widest">NIFTY Live</span>
            <span className="text-xs font-mono text-jarvis-primary">
              {marketData?.ltp ? marketData.ltp.toLocaleString('en-IN', { maximumFractionDigits: 2 }) : '—'}
            </span>
          </div>
          {sparkline.length > 2 ? (
            <ResponsiveContainer width="100%" height={80}>
              <AreaChart data={sparkline} margin={{ top: 2, right: 2, left: 2, bottom: 2 }}>
                <defs>
                  <linearGradient id="sparkGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#00e5ff" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#00e5ff" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <Area type="monotone" dataKey="v" stroke="#00e5ff" strokeWidth={1.5}
                  fill="url(#sparkGrad)" dot={false} isAnimationActive={false} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-20 flex items-center justify-center text-xs text-jarvis-text-secondary/60">
              Waiting for live ticks…
            </div>
          )}
        </div>

        {/* Model Training Widget */}
        <div className="rounded-xl p-4" style={{ background: 'rgba(0,15,35,0.7)', border: '1px solid rgba(0,229,255,0.15)' }}>
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-bold text-jarvis-text-secondary uppercase tracking-widest">Model Training</span>
            {trainStatus?.status === 'complete' && (
              <span className="text-xs text-green-400 font-bold">● Ready</span>
            )}
            {trainStatus?.status === 'failed' && (
              <span className="text-xs text-red-400 font-bold">● Failed</span>
            )}
            {trainStatus?.status === 'running' && (
              <motion.span className="text-xs text-yellow-400 font-bold"
                animate={{ opacity: [1, 0.4, 1] }} transition={{ duration: 1.2, repeat: Infinity }}>
                ● Training…
              </motion.span>
            )}
          </div>

          {trainStatus?.status === 'running' && (
            <div className="space-y-2">
              <div className="text-xs text-jarvis-text-secondary truncate">{trainStatus.progress}</div>
              {['Step 1', 'Step 2', 'Step 3', 'Step 4', 'Step 5'].map((s, i) => {
                const stepNum = parseInt(trainStatus.progress?.match(/Step (\d)/)?.[1] ?? '0');
                return (
                  <div key={s} className="flex items-center gap-2">
                    <div className={`w-2 h-2 rounded-full flex-shrink-0 ${i < stepNum ? 'bg-green-400' : i === stepNum - 1 ? 'bg-yellow-400' : 'bg-jarvis-primary/20'}`} />
                    <div className="text-xs text-jarvis-text-secondary">{s}/5</div>
                    <div className="flex-1 bg-jarvis-primary/10 rounded-full h-1">
                      <div className="bg-jarvis-primary h-1 rounded-full transition-all duration-500"
                        style={{ width: `${i < stepNum ? 100 : i === stepNum - 1 ? 60 : 0}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {trainStatus?.status === 'idle' && (
            <div className="space-y-2">
              <p className="text-xs text-yellow-400/80">⚠ Models not trained. Strategies will generate no signals until trained.</p>
              <button
                onClick={handleTrainNow}
                disabled={trainStarting}
                className="w-full py-2 rounded-lg text-xs font-bold uppercase tracking-widest transition-all"
                style={{ background: 'rgba(0,229,255,0.1)', border: '1px solid rgba(0,229,255,0.4)', color: '#00e5ff' }}
              >
                {trainStarting ? 'Starting…' : 'Train Now (60 days)'}
              </button>
            </div>
          )}

          {trainStatus?.status === 'complete' && (
            <div className="space-y-1">
              <p className="text-xs text-green-400">✓ {trainStatus.progress}</p>
              <button
                onClick={handleTrainNow}
                disabled={trainStarting}
                className="text-xs text-jarvis-text-secondary hover:text-jarvis-primary transition-colors"
              >
                Retrain →
              </button>
            </div>
          )}

          {trainStatus?.status === 'failed' && (
            <div className="space-y-2">
              <p className="text-xs text-red-400 break-words">{trainStatus.error || 'Training failed'}</p>
              <button
                onClick={handleTrainNow}
                disabled={trainStarting}
                className="text-xs text-jarvis-text-secondary hover:text-jarvis-primary transition-colors"
              >
                Retry →
              </button>
            </div>
          )}
        </div>
      </motion.div>

      {/* Market + Portfolio */}
      <motion.div variants={staggerItem} className="grid grid-cols-2 gap-6">
        {/* Market Overview */}
        <Card title="Market Overview" scanLine>
          <div className="space-y-4">
            {/* Nifty price */}
            <motion.div
              className="flex justify-between items-center p-4 rounded-xl"
              style={{
                background: 'rgba(0,229,255,0.04)',
                border: '1px solid rgba(0,229,255,0.1)',
              }}
              whileHover={{ borderColor: 'rgba(0,229,255,0.3)', background: 'rgba(0,229,255,0.07)' }}
            >
              <div>
                <div className="text-xs text-jarvis-text-secondary uppercase tracking-widest mb-1">NIFTY 50</div>
                <div className="text-3xl font-black font-mono text-jarvis-primary glow-text tabular-nums">
                  {marketData?.ltp.toLocaleString('en-IN', { maximumFractionDigits: 2 }) ?? '—'}
                </div>
              </div>
              <div className="text-right">
                <motion.div
                  className={`text-2xl font-mono font-bold tabular-nums ${change >= 0 ? 'text-green-400' : 'text-red-400'}`}
                  key={change}
                  initial={{ scale: 1.15 }}
                  animate={{ scale: 1 }}
                  transition={{ duration: 0.3 }}
                >
                  {change >= 0 ? '+' : ''}{change.toFixed(2)}
                </motion.div>
                <div className={`text-sm font-mono ${changePct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {changePct >= 0 ? '+' : ''}{changePct.toFixed(2)}%
                </div>
              </div>
            </motion.div>

            <div className="grid grid-cols-2 gap-3">
              {[
                { label: 'IV Percentile', value: `${marketData?.iv_percentile.toFixed(1) ?? '—'}%` },
                { label: 'PCR Ratio',     value: marketData?.pcr.toFixed(2) ?? '—' },
              ].map(item => (
                <motion.div
                  key={item.label}
                  className="p-3 rounded-lg"
                  style={{ background: 'rgba(0,229,255,0.04)', border: '1px solid rgba(0,229,255,0.08)' }}
                  whileHover={{ borderColor: 'rgba(0,229,255,0.25)' }}
                >
                  <div className="text-xs text-jarvis-text-secondary uppercase tracking-widest">{item.label}</div>
                  <div className="text-xl font-mono font-bold text-jarvis-accent mt-1">{item.value}</div>
                </motion.div>
              ))}
            </div>
          </div>
        </Card>

        {/* Portfolio Summary */}
        <Card title="Portfolio Summary">
          <div className="space-y-2">
            {[
              { label: 'Total Capital',     value: formatCurrency(portfolio?.total_capital ?? 0),     color: 'text-jarvis-primary' },
              { label: 'Used Capital',      value: formatCurrency(portfolio?.used_capital ?? 0),      color: 'text-yellow-400' },
              { label: 'Available Capital', value: formatCurrency(portfolio?.available_capital ?? 0), color: 'text-jarvis-secondary' },
              { label: 'Daily P&L',         value: formatCurrency(portfolio?.daily_pnl ?? 0),         color: (portfolio?.daily_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400' },
            ].map((item, i) => (
              <motion.div
                key={item.label}
                className="flex justify-between items-center p-3 rounded-lg"
                style={{ background: 'rgba(0,229,255,0.03)', border: '1px solid rgba(0,229,255,0.06)' }}
                whileHover={{ borderColor: 'rgba(0,229,255,0.2)', background: 'rgba(0,229,255,0.06)' }}
                initial={{ opacity: 0, x: -12 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.07 + 0.2 }}
              >
                <span className="text-sm text-jarvis-text-secondary">{item.label}</span>
                <span className={`font-mono font-bold text-sm ${item.color}`}>{item.value}</span>
              </motion.div>
            ))}
          </div>
        </Card>
      </motion.div>

      {/* Active Positions */}
      <motion.div variants={staggerItem}>
        <Card title={`Active Positions ${positions.length > 0 ? `(${positions.length})` : ''}`} scanLine>
          {positions.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Dir</th>
                    <th>Entry</th>
                    <th>LTP</th>
                    <th>Qty</th>
                    <th>P&L</th>
                    <th>%</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((pos, i) => (
                    <motion.tr
                      key={pos.order_id}
                      initial={{ opacity: 0, x: -8 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: i * 0.06 }}
                    >
                      <td className="font-semibold text-jarvis-primary">{pos.symbol}</td>
                      <td>
                        <span className={`px-2 py-0.5 rounded text-xs font-bold ${
                          pos.direction === 'BUY'
                            ? 'bg-green-400/15 text-green-400'
                            : 'bg-red-400/15 text-red-400'
                        }`}>
                          {pos.direction}
                        </span>
                      </td>
                      <td>{pos.entry_price.toFixed(2)}</td>
                      <td>{pos.current_price.toFixed(2)}</td>
                      <td>{pos.qty}</td>
                      <td className={pos.unrealized_pnl >= 0 ? 'value-positive' : 'value-negative'}>
                        {formatCurrency(pos.unrealized_pnl)}
                      </td>
                      <td className={pos.pnl_percentage >= 0 ? 'value-positive' : 'value-negative'}>
                        {formatPercent(pos.pnl_percentage)}
                      </td>
                    </motion.tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <motion.div
              className="text-center py-14"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.3 }}
            >
              <motion.div
                className="text-5xl mb-4"
                animate={{ y: [0, -8, 0] }}
                transition={{ duration: 3, repeat: Infinity, ease: 'easeInOut' }}
              >
                📊
              </motion.div>
              <p className="text-jarvis-text-secondary text-sm uppercase tracking-widest">
                No active positions
              </p>
              <p className="text-jarvis-text-secondary/50 text-xs mt-1">
                Start a strategy to begin trading
              </p>
            </motion.div>
          )}
        </Card>
      </motion.div>

      {/* Swing Positions */}
      {swingPositions.length > 0 && (() => {
        const swingPnl = swingPositions.reduce((s, p) => s + (p.unrealized_pnl ?? 0), 0);
        const swingPnlPct = swingPositions.reduce((s, p) => s + (p.pnl_pct ?? 0), 0) / swingPositions.length;
        return (
          <motion.div variants={staggerItem}>
            <Card title={`Swing Positions (${swingPositions.length})`} scanLine>
              {/* Overall swing P&L row */}
              <div className="flex items-center justify-between mb-4 px-2 py-2 rounded-lg" style={{ background: 'rgba(0,229,255,0.04)', border: '1px solid rgba(0,229,255,0.1)' }}>
                <span className="text-xs text-jarvis-text-secondary uppercase tracking-widest">Swing P&L (unrealised)</span>
                <div className="flex items-center gap-3">
                  <span className={`text-sm font-mono font-bold ${swingPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {formatCurrency(swingPnl)}
                  </span>
                  <span className={`text-xs font-mono px-2 py-0.5 rounded ${swingPnl >= 0 ? 'bg-green-400/10 text-green-400' : 'bg-red-400/10 text-red-400'}`}>
                    {swingPnlPct >= 0 ? '+' : ''}{swingPnlPct.toFixed(2)}%
                  </span>
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-jarvis-text-secondary border-b border-white/10">
                      <th className="pb-2 text-left">Stock</th>
                      <th className="pb-2 text-right">Entry</th>
                      <th className="pb-2 text-right">CMP</th>
                      <th className="pb-2 text-right">P&L%</th>
                      <th className="pb-2 text-right">SL</th>
                      <th className="pb-2 text-right">Target</th>
                      <th className="pb-2 text-center">Mode</th>
                    </tr>
                  </thead>
                  <tbody>
                    {swingPositions.map(pos => (
                      <tr key={pos.symbol} className="border-b border-white/5 hover:bg-white/5">
                        <td className="py-2 font-bold text-jarvis-primary">{pos.symbol}</td>
                        <td className="py-2 text-right font-mono">₹{pos.entry_price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                        <td className="py-2 text-right font-mono">₹{pos.current_price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                        <td className="py-2 text-right">
                          <span className={`px-1.5 py-0.5 rounded text-xs font-bold ${(pos.pnl_pct ?? 0) >= 0 ? 'bg-green-400/10 text-green-400' : 'bg-red-400/10 text-red-400'}`}>
                            {(pos.pnl_pct ?? 0) >= 0 ? '+' : ''}{(pos.pnl_pct ?? 0).toFixed(2)}%
                          </span>
                        </td>
                        <td className="py-2 text-right font-mono text-red-400">₹{pos.stop_loss.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                        <td className="py-2 text-right font-mono text-green-400">₹{pos.target1.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                        <td className="py-2 text-center">
                          <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: pos.mode === 'live' ? 'rgba(255,23,68,0.15)' : 'rgba(0,229,255,0.1)', color: pos.mode === 'live' ? '#ff1744' : '#00e5ff' }}>
                            {pos.mode.toUpperCase()}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </motion.div>
        );
      })()}
    </motion.div>
  );
}
