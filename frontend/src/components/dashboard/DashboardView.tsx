import React, { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { CircularWidget } from '../ui/CircularWidget';
import { Card } from '../ui/Card';
import { useWebSocket } from '../../hooks/useWebSocket';
import { positionsApi, marketApi, riskApi } from '../../api/client';
import { formatCurrency, formatPercent } from '../../utils/formatters';
import type { PortfolioSummary, MarketData, RiskLimits } from '../../types/api';

const stagger = {
  container: { hidden: {}, show: { transition: { staggerChildren: 0.08 } } },
  item: {
    hidden: { opacity: 0, y: 24 },
    show:   { opacity: 1, y: 0, transition: { duration: 0.45, ease: 'easeOut' } },
  },
};

export function DashboardView() {
  const { connected, positions, marketData: wsMarketData } = useWebSocket();
  const [portfolio, setPortfolio]   = useState<PortfolioSummary | null>(null);
  const [marketData, setMarketData] = useState<MarketData | null>(null);
  const [riskLimits, setRiskLimits] = useState<RiskLimits | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [pRes, mRes, rRes] = await Promise.all([
          positionsApi.getPortfolio(),
          marketApi.getCurrent(),
          riskApi.getLimits(),
        ]);
        setPortfolio(pRes.data);
        setMarketData(mRes.data);
        setRiskLimits(rRes.data);
      } catch (e) {
        console.error('Dashboard fetch error:', e);
      }
    };
    fetchData();
    const iv = setInterval(fetchData, 5000);
    return () => clearInterval(iv);
  }, []);

  useEffect(() => {
    if (wsMarketData) setMarketData(wsMarketData);
  }, [wsMarketData]);

  const pnl        = portfolio?.total_pnl ?? 0;
  const pnlColor   = pnl >= 0 ? 'green' : 'red';
  const change     = marketData?.change ?? 0;
  const changePct  = marketData?.change_percentage ?? 0;

  return (
    <motion.div
      className="space-y-6"
      variants={stagger.container}
      initial="hidden"
      animate="show"
    >
      {/* Header row */}
      <motion.div variants={stagger.item} className="flex items-center justify-between">
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
      <motion.div variants={stagger.item}>
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

      {/* Market + Portfolio */}
      <motion.div variants={stagger.item} className="grid grid-cols-2 gap-6">
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
      <motion.div variants={stagger.item}>
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
    </motion.div>
  );
}
