import React, { useState, useEffect } from 'react';
import { api } from '../../api/client';
import './AthenaDashboard.css';

interface AthenaStatus {
  enabled: boolean;
  mode: string;
  positions: number;
  trades_this_week: number;
  weekly_pnl: number;
  max_positions: number;
  min_confidence: number;
  min_pop: number;
}

interface Position {
  id?: number;
  strategy: string;
  symbol: string;
  entry_date: string;
  expiry_date?: string;
  strikes: {
    sell_strike?: number;
    buy_strike?: number;
    sell_strike_2?: number;
    buy_strike_2?: number;
  };
  premium_received: number;
  max_loss: number;
  current_value: number;
  realized_pnl: number;
  confidence: number;
  probability_of_profit: number;
  exit_date?: string;
  exit_reason?: string;
  status: string;
  mode: string;
  reasoning?: string;
}

interface AnalysisResult {
  action: string;
  strategy?: string;
  confidence?: number;
  details?: any;
  reason?: string;
}

const AthenaDashboard: React.FC = () => {
  const [status, setStatus] = useState<AthenaStatus | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);

  useEffect(() => {
    fetchStatus();
    fetchPositions();

    // Poll every 30 seconds
    const interval = setInterval(() => {
      fetchStatus();
      fetchPositions();
    }, 30000);

    return () => clearInterval(interval);
  }, []);

  const fetchStatus = async () => {
    try {
      const res = await api.get('/api/athena/status');
      setStatus(res.data);
    } catch (err) {
      console.error('[Athena] Failed to fetch status:', err);
    }
  };

  const fetchPositions = async () => {
    try {
      const res = await api.get('/api/athena/positions');
      // Ensure positions is always an array
      setPositions(Array.isArray(res.data) ? res.data : []);
    } catch (err) {
      console.error('[Athena] Failed to fetch positions:', err);
      setPositions([]); // Set empty array on error
    }
  };

  const handleEnable = async (mode: 'paper' | 'live') => {
    setLoading(true);
    try {
      await api.post('/api/athena/enable', { mode });
      await fetchStatus();
      alert(`Athena enabled in ${mode.toUpperCase()} mode`);
    } catch (err: any) {
      alert(`Failed to enable Athena: ${err.response?.data?.detail || err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleDisable = async () => {
    setLoading(true);
    try {
      await api.post('/api/athena/disable');
      await fetchStatus();
      alert('Athena disabled');
    } catch (err: any) {
      alert(`Failed to disable Athena: ${err.response?.data?.detail || err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleAnalyze = async () => {
    setAnalyzing(true);
    setAnalysisResult(null);
    try {
      const res = await api.post('/api/athena/analyze');
      setAnalysisResult(res.data);
      await fetchPositions();
    } catch (err: any) {
      alert(`Analysis failed: ${err.response?.data?.detail || err.message}`);
    } finally {
      setAnalyzing(false);
    }
  };

  const formatCurrency = (value: number) => {
    return `₹${value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  const formatPercent = (value: number) => {
    return `${(value * 100).toFixed(0)}%`;
  };

  const formatDate = (dateStr?: string) => {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleString('en-IN', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const getStrategyLabel = (strategy: string) => {
    const labels: Record<string, string> = {
      'BULL_PUT_SPREAD': 'Bull Put Spread',
      'BEAR_CALL_SPREAD': 'Bear Call Spread',
      'IRON_CONDOR': 'Iron Condor'
    };
    return labels[strategy] || strategy;
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'OPEN': return '#22c55e';
      case 'CLOSED': return '#64748b';
      case 'EXPIRED': return '#94a3b8';
      default: return '#6b7280';
    }
  };

  return (
    <div className="athena-dashboard">
      <div className="athena-header">
        <h1>🏛️ Athena Options Trading</h1>
        <p className="athena-subtitle">AI-Powered Weekly Options · Target 80% Success Rate</p>
      </div>

      {/* Status Card */}
      <div className="athena-card">
        <div className="athena-card-header">
          <h2>Status</h2>
          {status && (
            <span className={`status-badge ${status.enabled ? 'active' : 'inactive'}`}>
              {status.enabled ? `ACTIVE · ${status.mode.toUpperCase()}` : 'INACTIVE'}
            </span>
          )}
        </div>

        {status && (
          <div className="athena-stats-grid">
            <div className="stat-item">
              <span className="stat-label">Weekly P&L</span>
              <span className={`stat-value ${status.weekly_pnl >= 0 ? 'positive' : 'negative'}`}>
                {formatCurrency(status.weekly_pnl)}
              </span>
            </div>
            <div className="stat-item">
              <span className="stat-label">Trades This Week</span>
              <span className="stat-value">{status.trades_this_week} / {status.max_positions}</span>
            </div>
            <div className="stat-item">
              <span className="stat-label">Open Positions</span>
              <span className="stat-value">{status.positions}</span>
            </div>
            <div className="stat-item">
              <span className="stat-label">Min Confidence</span>
              <span className="stat-value">{formatPercent(status.min_confidence)}</span>
            </div>
          </div>
        )}

        <div className="athena-controls">
          <button
            className="btn btn-primary"
            onClick={() => handleEnable('paper')}
            disabled={loading || status?.enabled === true}
          >
            Enable Paper Trading
          </button>
          <button
            className="btn btn-live"
            onClick={() => handleEnable('live')}
            disabled={loading || status?.enabled === true}
          >
            Enable Live Trading
          </button>
          <button
            className="btn btn-secondary"
            onClick={handleDisable}
            disabled={loading || status?.enabled === false}
          >
            Disable
          </button>
          <button
            className="btn btn-analyze"
            onClick={handleAnalyze}
            disabled={analyzing}
          >
            {analyzing ? 'Analyzing...' : 'Run Analysis'}
          </button>
        </div>
      </div>

      {/* Analysis Result */}
      {analysisResult && (
        <div className={`athena-card analysis-result ${analysisResult.action.toLowerCase()}`}>
          <h2>Latest Analysis</h2>
          <div className="analysis-content">
            <div className="analysis-action">
              <span className="analysis-label">Action:</span>
              <span className="analysis-value">{analysisResult.action}</span>
            </div>
            {analysisResult.strategy && (
              <div className="analysis-strategy">
                <span className="analysis-label">Strategy:</span>
                <span className="analysis-value">{getStrategyLabel(analysisResult.strategy)}</span>
              </div>
            )}
            {analysisResult.confidence !== undefined && (
              <div className="analysis-confidence">
                <span className="analysis-label">Confidence:</span>
                <span className="analysis-value">{formatPercent(analysisResult.confidence)}</span>
              </div>
            )}
            {analysisResult.reason && (
              <div className="analysis-reason">
                <span className="analysis-label">Reason:</span>
                <span className="analysis-value">{analysisResult.reason}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Positions Table */}
      <div className="athena-card">
        <h2>Positions ({positions.length})</h2>

        {positions.length === 0 ? (
          <div className="empty-state">
            <p>No positions yet</p>
            <p className="empty-hint">Run an analysis to find high-probability setups</p>
          </div>
        ) : (
          <div className="positions-table-container">
            <table className="positions-table">
              <thead>
                <tr>
                  <th>Strategy</th>
                  <th>Entry</th>
                  <th>Strikes</th>
                  <th>Premium</th>
                  <th>Max Loss</th>
                  <th>P&L</th>
                  <th>Confidence</th>
                  <th>PoP</th>
                  <th>Status</th>
                  <th>Exit</th>
                </tr>
              </thead>
              <tbody>
                {(positions || []).map((pos, idx) => (
                  <tr key={pos.id || idx}>
                    <td>
                      <div className="position-strategy">
                        {getStrategyLabel(pos.strategy)}
                        <span className="mode-badge">{pos.mode}</span>
                      </div>
                    </td>
                    <td className="text-small">{formatDate(pos.entry_date)}</td>
                    <td className="strikes-cell">
                      <div className="strikes-info">
                        {pos.strikes?.sell_strike && <span>S: {pos.strikes.sell_strike}</span>}
                        {pos.strikes?.buy_strike && <span>B: {pos.strikes.buy_strike}</span>}
                        {pos.strikes?.sell_strike_2 && <span>S2: {pos.strikes.sell_strike_2}</span>}
                        {pos.strikes?.buy_strike_2 && <span>B2: {pos.strikes.buy_strike_2}</span>}
                      </div>
                    </td>
                    <td className="positive">{formatCurrency(pos.premium_received)}</td>
                    <td className="negative">{formatCurrency(pos.max_loss)}</td>
                    <td className={pos.realized_pnl >= 0 ? 'positive' : 'negative'}>
                      {formatCurrency(pos.realized_pnl)}
                    </td>
                    <td>{formatPercent(pos.confidence)}</td>
                    <td>{formatPercent(pos.probability_of_profit)}</td>
                    <td>
                      <span
                        className="status-dot"
                        style={{ backgroundColor: getStatusColor(pos.status) }}
                      >
                        {pos.status}
                      </span>
                    </td>
                    <td className="text-small">
                      {pos.exit_reason || '-'}
                      {pos.exit_date && <div>{formatDate(pos.exit_date)}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Info Card */}
      <div className="athena-card athena-info">
        <h3>How Athena Works</h3>
        <ul>
          <li><strong>Weekly Analysis:</strong> Scans Bank Nifty weekly options every day</li>
          <li><strong>High Probability:</strong> Only trades setups with 75%+ probability of profit</li>
          <li><strong>Credit Spreads:</strong> Bull Put / Bear Call spreads in trending markets</li>
          <li><strong>Iron Condors:</strong> Range-bound strategies when markets consolidate</li>
          <li><strong>Risk Management:</strong> Exit at 50% profit or 100% loss (max risk defined)</li>
          <li><strong>AI Powered:</strong> Claude Opus 4.8 with extended thinking for options analysis</li>
        </ul>
      </div>
    </div>
  );
};

export default AthenaDashboard;
