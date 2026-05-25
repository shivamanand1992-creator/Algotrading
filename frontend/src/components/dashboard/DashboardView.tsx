import React, { useEffect, useState } from 'react';
import { CircularWidget } from '../ui/CircularWidget';
import { Card } from '../ui/Card';
import { useWebSocket } from '../../hooks/useWebSocket';
import { positionsApi, marketApi, riskApi } from '../../api/client';
import { formatCurrency, formatPercent } from '../../utils/formatters';
import type { PortfolioSummary, MarketData, RiskLimits } from '../../types/api';

export function DashboardView() {
  const { connected, positions, marketData: wsMarketData } = useWebSocket();
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null);
  const [marketData, setMarketData] = useState<MarketData | null>(null);
  const [riskLimits, setRiskLimits] = useState<RiskLimits | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [portfolioRes, marketRes, riskRes] = await Promise.all([
          positionsApi.getPortfolio(),
          marketApi.getCurrent(),
          riskApi.getLimits(),
        ]);
        setPortfolio(portfolioRes.data);
        setMarketData(marketRes.data);
        setRiskLimits(riskRes.data);
      } catch (error) {
        console.error('Failed to fetch dashboard data:', error);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  // Update market data from WebSocket
  useEffect(() => {
    if (wsMarketData) {
      setMarketData(wsMarketData);
    }
  }, [wsMarketData]);

  return (
    <div className="space-y-6">
      {/* Connection Status */}
      <div className="flex items-center justify-between">
        <h2 className="text-3xl font-bold text-jarvis-primary glow-text">
          Command Center
        </h2>
        <div className="flex items-center space-x-2">
          <div
            className={`w-3 h-3 rounded-full ${
              connected ? 'bg-green-400' : 'bg-red-400'
            } pulse-glow`}
          />
          <span className="text-sm text-jarvis-text-secondary">
            {connected ? 'Live Connected' : 'Disconnected'}
          </span>
        </div>
      </div>

      {/* Top Metrics - Circular Widgets */}
      <div className="grid grid-cols-4 gap-8">
        <CircularWidget
          title="Total P&L"
          value={formatCurrency(portfolio?.total_pnl || 0)}
          progress={
            portfolio
              ? Math.min(
                  Math.abs(portfolio.total_pnl_percentage),
                  100
                )
              : 0
          }
          size="lg"
        />
        <CircularWidget
          title="Daily P&L"
          value={formatPercent(portfolio?.daily_pnl_percentage || 0)}
          progress={portfolio ? Math.abs(portfolio.daily_pnl_percentage) : 0}
          size="md"
        />
        <CircularWidget
          title="Capital Used"
          value={formatPercent(
            portfolio
              ? (portfolio.used_capital / portfolio.total_capital) * 100
              : 0
          )}
          progress={
            portfolio
              ? (portfolio.used_capital / portfolio.total_capital) * 100
              : 0
          }
          size="md"
        />
        <CircularWidget
          title="Positions"
          value={portfolio?.open_positions_count || 0}
          unit="active"
          progress={
            riskLimits
              ? (portfolio?.open_positions_count || 0) /
                riskLimits.max_positions *
                100
              : 0
          }
          size="md"
        />
      </div>

      {/* Market Overview & Portfolio Summary */}
      <div className="grid grid-cols-2 gap-6">
        {/* Market Overview */}
        <Card title="Market Overview">
          <div className="space-y-4">
            <div className="flex justify-between items-center p-4 bg-jarvis-bg-panel rounded-lg">
              <span className="text-jarvis-text-secondary">Nifty 50</span>
              <div className="text-right">
                <div className="text-2xl font-mono text-jarvis-primary">
                  {marketData?.ltp.toFixed(2) || '0.00'}
                </div>
                <div
                  className={`text-sm ${
                    (marketData?.change || 0) >= 0
                      ? 'text-green-400'
                      : 'text-red-400'
                  }`}
                >
                  {(marketData?.change ?? 0) >= 0 ? '+' : ''}
                  {(marketData?.change ?? 0).toFixed(2)} (
                  {formatPercent(marketData?.change_percentage || 0)})
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="p-3 bg-jarvis-bg-panel rounded-lg">
                <div className="text-xs text-jarvis-text-secondary">
                  IV Percentile
                </div>
                <div className="text-lg font-mono text-jarvis-accent mt-1">
                  {marketData?.iv_percentile.toFixed(1) || '0.0'}%
                </div>
              </div>
              <div className="p-3 bg-jarvis-bg-panel rounded-lg">
                <div className="text-xs text-jarvis-text-secondary">
                  PCR Ratio
                </div>
                <div className="text-lg font-mono text-jarvis-accent mt-1">
                  {marketData?.pcr.toFixed(2) || '0.00'}
                </div>
              </div>
            </div>
          </div>
        </Card>

        {/* Portfolio Summary */}
        <Card title="Portfolio Summary">
          <div className="space-y-3">
            <div className="flex justify-between p-3 bg-jarvis-bg-panel rounded-lg">
              <span className="text-jarvis-text-secondary">Total Capital</span>
              <span className="font-mono text-jarvis-primary">
                {formatCurrency(portfolio?.total_capital || 0)}
              </span>
            </div>
            <div className="flex justify-between p-3 bg-jarvis-bg-panel rounded-lg">
              <span className="text-jarvis-text-secondary">Used Capital</span>
              <span className="font-mono text-jarvis-accent">
                {formatCurrency(portfolio?.used_capital || 0)}
              </span>
            </div>
            <div className="flex justify-between p-3 bg-jarvis-bg-panel rounded-lg">
              <span className="text-jarvis-text-secondary">
                Available Capital
              </span>
              <span className="font-mono text-jarvis-secondary">
                {formatCurrency(portfolio?.available_capital || 0)}
              </span>
            </div>
            <div className="flex justify-between p-3 bg-jarvis-bg-panel rounded-lg">
              <span className="text-jarvis-text-secondary">Open Positions</span>
              <span className="font-mono text-jarvis-primary">
                {portfolio?.open_positions_count || 0}
              </span>
            </div>
          </div>
        </Card>
      </div>

      {/* Active Positions */}
      <Card title="Active Positions">
        {positions.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Type</th>
                  <th>Entry</th>
                  <th>Current</th>
                  <th>Qty</th>
                  <th>P&L</th>
                  <th>%</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((pos) => (
                  <tr key={pos.order_id}>
                    <td className="font-semibold">{pos.symbol}</td>
                    <td>
                      <span
                        className={`px-2 py-1 rounded text-xs ${
                          pos.direction === 'BUY'
                            ? 'bg-green-400/20 text-green-400'
                            : 'bg-red-400/20 text-red-400'
                        }`}
                      >
                        {pos.direction}
                      </span>
                    </td>
                    <td>{pos.entry_price.toFixed(2)}</td>
                    <td>{pos.current_price.toFixed(2)}</td>
                    <td>{pos.qty}</td>
                    <td
                      className={
                        pos.unrealized_pnl >= 0
                          ? 'text-green-400'
                          : 'text-red-400'
                      }
                    >
                      {formatCurrency(pos.unrealized_pnl)}
                    </td>
                    <td
                      className={
                        pos.pnl_percentage >= 0
                          ? 'text-green-400'
                          : 'text-red-400'
                      }
                    >
                      {formatPercent(pos.pnl_percentage)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-center py-12 text-jarvis-text-secondary">
            <div className="text-4xl mb-4">📊</div>
            <p>No active positions</p>
          </div>
        )}
      </Card>
    </div>
  );
}
