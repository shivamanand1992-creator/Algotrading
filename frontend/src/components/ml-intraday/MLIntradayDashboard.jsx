import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './MLIntradayDashboard.css';

const MLIntradayDashboard = () => {
  const [signals, setSignals] = useState([]);
  const [topStocks, setTopStocks] = useState([]);
  const [systemStatus, setSystemStatus] = useState(null);
  const [selectedSignal, setSelectedSignal] = useState(null);
  const [explanation, setExplanation] = useState(null);
  const [loading, setLoading] = useState(false);
  const [paperTrades, setPaperTrades] = useState(null);
  const [actionMsg, setActionMsg] = useState(null);

  // Fetch system status
  useEffect(() => {
    fetchSystemStatus();
    const interval = setInterval(fetchSystemStatus, 10000); // Every 10s
    return () => clearInterval(interval);
  }, []);

  // Fetch top scored stocks
  useEffect(() => {
    fetchTopStocks();
    const interval = setInterval(fetchTopStocks, 30000); // Every 30s
    return () => clearInterval(interval);
  }, []);

  const fetchSystemStatus = async () => {
    try {
      const response = await axios.get('/api/ml-intraday/status');
      setSystemStatus(response.data);
    } catch (error) {
      console.error('Failed to fetch ML system status:', error);
    }
  };

  const fetchTopStocks = async () => {
    try {
      const response = await axios.get('/api/ml-intraday/top-stocks');
      setTopStocks(response.data.stocks || []);
      setSignals(response.data.signals || []);
    } catch (error) {
      console.error('Failed to fetch top stocks:', error);
    }
    try {
      const pt = await axios.get('/api/ml-intraday/paper-trades');
      setPaperTrades(pt.data);
    } catch (e) { /* noop */ }
  };

  const triggerAction = async (endpoint, label) => {
    setActionMsg(`${label}...`);
    try {
      const res = await axios.post(`/api/ml-intraday/${endpoint}`);
      setActionMsg(res.data.message || res.data.status || `${label} done`);
      setTimeout(fetchSystemStatus, 2000);
    } catch (error) {
      setActionMsg(`${label} failed: ${error.response?.data?.detail || error.message}`);
    }
  };

  const getExplanation = async (signal) => {
    setLoading(true);
    setSelectedSignal(signal);
    try {
      const response = await axios.post('/api/ml-intraday/explain', {
        symbol: signal.symbol,
        score: signal.score,
        features: signal.features
      });
      setExplanation(response.data.explanation);
    } catch (error) {
      console.error('Failed to get explanation:', error);
      setExplanation('Failed to generate explanation');
    } finally {
      setLoading(false);
    }
  };

  const getScoreColor = (score) => {
    if (score >= 90) return 'score-excellent';
    if (score >= 80) return 'score-good';
    if (score >= 70) return 'score-moderate';
    return 'score-weak';
  };

  const getFeatureColor = (value) => {
    if (value >= 90) return 'feature-excellent';
    if (value >= 80) return 'feature-good';
    if (value >= 70) return 'feature-moderate';
    return 'feature-weak';
  };

  return (
    <div className="ml-intraday-dashboard">
      {/* Header */}
      <div className="ml-header">
        <div>
          <h1>ML Intraday Trading</h1>
          <p className="ml-subtitle">AI-Powered Stock Scoring & Signal Generation</p>
        </div>
        {systemStatus && (
          <div className="system-status">
            <div className="status-item">
              <span className="status-label">Model Status</span>
              <span className={`status-value ${systemStatus.model_loaded ? 'status-active' : 'status-inactive'}`}>
                {systemStatus.model_loaded ? '✓ Loaded' : '✗ Not Loaded'}
              </span>
            </div>
            <div className="status-item">
              <span className="status-label">Last Update</span>
              <span className="status-value">{systemStatus.last_update || 'Never'}</span>
            </div>
            <div className="status-item">
              <span className="status-label">Stocks Tracked</span>
              <span className="status-value">{systemStatus.stocks_tracked || 0}</span>
            </div>
          </div>
        )}
      </div>

      <div className="ml-content">
        {/* Setup Controls */}
        <div className="ml-card">
          <div className="card-header">
            <h2>System Controls</h2>
            {systemStatus?.tradeable === false && systemStatus?.model_loaded && (
              <span className="status-value" style={{ color: '#ff9100' }}>
                ⚠ Model expectancy not positive — PAPER ONLY
              </span>
            )}
          </div>
          <div className="ml-controls" style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', position: 'relative', zIndex: 1 }}>
            <button className="btn-explain" onClick={() => triggerAction('import-data?days=30', 'Importing 30 days of data')}>
              1. Import Data
            </button>
            <button className="btn-explain" onClick={() => triggerAction('train', 'Training model')}>
              2. Train Model
            </button>
            <button className="btn-explain" onClick={() => triggerAction('run-cycle', 'Running scoring cycle')}>
              3. Run Cycle Now
            </button>
          </div>
          {actionMsg && (
            <p style={{ marginTop: '1rem', color: 'var(--jarvis-text-secondary)', position: 'relative', zIndex: 1 }}>
              {actionMsg}
            </p>
          )}
          {systemStatus?.test_expectancy != null && (
            <p style={{ marginTop: '0.5rem', color: 'var(--jarvis-text-primary)', position: 'relative', zIndex: 1 }}>
              Out-of-sample expectancy: <strong style={{ color: systemStatus.test_expectancy > 0 ? '#00e676' : '#ff1744' }}>
                {systemStatus.test_expectancy > 0 ? '+' : ''}{systemStatus.test_expectancy}% per trade
              </strong>
            </p>
          )}
        </div>

        {/* Paper Trading P&L */}
        {paperTrades && (paperTrades.open_positions?.length > 0 || paperTrades.closed_trades?.length > 0) && (
          <div className="ml-card">
            <div className="card-header">
              <h2>Paper Trading</h2>
              <span className={paperTrades.total_pnl_pct >= 0 ? 'positive' : 'negative'} style={{ fontWeight: 700, fontFamily: 'monospace' }}>
                {paperTrades.total_pnl_pct >= 0 ? '+' : ''}{paperTrades.total_pnl_pct}%
              </span>
            </div>
            <div className="signals-table-container">
              <table className="signals-table">
                <thead>
                  <tr><th>Symbol</th><th>Entry</th><th>SL</th><th>Target</th><th>Exit</th><th>P&L</th><th>Status</th></tr>
                </thead>
                <tbody>
                  {paperTrades.open_positions.map((p, i) => (
                    <tr key={`o${i}`}>
                      <td className="symbol-cell">{p.symbol}</td>
                      <td className="price-cell">₹{p.entry}</td>
                      <td className="price-cell negative">₹{p.stop_loss}</td>
                      <td className="price-cell positive">₹{p.target}</td>
                      <td>—</td>
                      <td>—</td>
                      <td><span className="rr-badge">OPEN</span></td>
                    </tr>
                  ))}
                  {paperTrades.closed_trades.map((t, i) => (
                    <tr key={`c${i}`}>
                      <td className="symbol-cell">{t.symbol}</td>
                      <td className="price-cell">₹{t.entry}</td>
                      <td className="price-cell negative">₹{t.stop_loss}</td>
                      <td className="price-cell positive">₹{t.target}</td>
                      <td className="price-cell">₹{t.exit}</td>
                      <td className={t.pnl_pct >= 0 ? 'positive' : 'negative'}>
                        {t.pnl_pct >= 0 ? '+' : ''}{t.pnl_pct}%
                      </td>
                      <td className="time-cell">{t.exit_reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Top Stocks Panel */}
        <div className="ml-card">
          <div className="card-header">
            <h2>Live Stock Scores</h2>
            <span className="refresh-indicator">Auto-refresh: 30s</span>
          </div>

          {topStocks.length === 0 ? (
            <div className="empty-state">
              <p>🔄 Calculating stock scores...</p>
              <p className="empty-hint">ML models analyzing NSE stocks in real-time</p>
            </div>
          ) : (
            <div className="stocks-grid">
              {topStocks.map((stock, idx) => (
                <div
                  key={stock.symbol}
                  className={`stock-card ${getScoreColor(stock.score)}`}
                  onClick={() => stock.score >= 90 && getExplanation(stock)}
                  style={{ cursor: stock.score >= 90 ? 'pointer' : 'default' }}
                >
                  <div className="stock-header">
                    <div>
                      <div className="stock-symbol">{stock.symbol}</div>
                      <div className="stock-price">₹{stock.price?.toFixed(2) || '0.00'}</div>
                    </div>
                    <div className="stock-score-container">
                      <div className={`stock-score ${getScoreColor(stock.score)}`}>
                        {stock.score}
                      </div>
                      <div className="score-label">Score</div>
                    </div>
                  </div>

                  <div className="feature-breakdown">
                    <div className="feature-row">
                      <span className="feature-name">Trend</span>
                      <div className="feature-bar-container">
                        <div
                          className={`feature-bar ${getFeatureColor(stock.features?.trend || 0)}`}
                          style={{ width: `${stock.features?.trend || 0}%` }}
                        />
                      </div>
                      <span className="feature-value">{stock.features?.trend || 0}</span>
                    </div>
                    <div className="feature-row">
                      <span className="feature-name">Momentum</span>
                      <div className="feature-bar-container">
                        <div
                          className={`feature-bar ${getFeatureColor(stock.features?.momentum || 0)}`}
                          style={{ width: `${stock.features?.momentum || 0}%` }}
                        />
                      </div>
                      <span className="feature-value">{stock.features?.momentum || 0}</span>
                    </div>
                    <div className="feature-row">
                      <span className="feature-name">Volume</span>
                      <div className="feature-bar-container">
                        <div
                          className={`feature-bar ${getFeatureColor(stock.features?.volume || 0)}`}
                          style={{ width: `${stock.features?.volume || 0}%` }}
                        />
                      </div>
                      <span className="feature-value">{stock.features?.volume || 0}</span>
                    </div>
                    <div className="feature-row">
                      <span className="feature-name">Pattern</span>
                      <div className="feature-bar-container">
                        <div
                          className={`feature-bar ${getFeatureColor(stock.features?.pattern || 0)}`}
                          style={{ width: `${stock.features?.pattern || 0}%` }}
                        />
                      </div>
                      <span className="feature-value">{stock.features?.pattern || 0}</span>
                    </div>
                  </div>

                  {stock.score >= 90 && (
                    <div className="signal-badge">
                      🎯 HIGH CONFIDENCE SIGNAL
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Active Signals Panel */}
        <div className="ml-card">
          <div className="card-header">
            <h2>Active Signals</h2>
            <span className="signal-count">{signals.length} signals</span>
          </div>

          {signals.length === 0 ? (
            <div className="empty-state">
              <p>⏳ No high-confidence signals right now</p>
              <p className="empty-hint">Signals appear when Score ≥ 90 and P(Success) ≥ 70%</p>
            </div>
          ) : (
            <div className="signals-table-container">
              <table className="signals-table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Score</th>
                    <th>Probability</th>
                    <th>Entry</th>
                    <th>Stop Loss</th>
                    <th>Target</th>
                    <th>R:R</th>
                    <th>Hold Time</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {signals.map((signal, idx) => (
                    <tr key={idx}>
                      <td className="symbol-cell">{signal.symbol}</td>
                      <td>
                        <span className={`score-badge ${getScoreColor(signal.score)}`}>
                          {signal.score}
                        </span>
                      </td>
                      <td>
                        <span className="probability">{signal.probability}%</span>
                      </td>
                      <td className="price-cell">₹{signal.entry?.toFixed(2)}</td>
                      <td className="price-cell negative">₹{signal.stop_loss?.toFixed(2)}</td>
                      <td className="price-cell positive">₹{signal.target?.toFixed(2)}</td>
                      <td>
                        <span className="rr-badge">1:{signal.reward_risk?.toFixed(1)}</span>
                      </td>
                      <td className="time-cell">{signal.hold_time} min</td>
                      <td>
                        <button
                          className="btn-explain"
                          onClick={() => getExplanation(signal)}
                        >
                          Why?
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Explanation Panel */}
        {selectedSignal && (
          <div className="ml-card explanation-card">
            <div className="card-header">
              <h2>Signal Explanation: {selectedSignal.symbol}</h2>
              <button
                className="btn-close"
                onClick={() => {
                  setSelectedSignal(null);
                  setExplanation(null);
                }}
              >
                ✕
              </button>
            </div>

            {loading ? (
              <div className="loading-state">
                <div className="spinner"></div>
                <p>Generating explanation with Claude AI...</p>
              </div>
            ) : explanation ? (
              <div className="explanation-content">
                <pre>{explanation}</pre>
              </div>
            ) : null}
          </div>
        )}

        {/* Strategy Info */}
        <div className="ml-card info-card">
          <h3>How This Works</h3>
          <ul>
            <li><strong>ML Scoring:</strong> XGBoost/LightGBM models analyze 120+ features (trend, momentum, volume, patterns) to score every stock 0-100</li>
            <li><strong>Signal Generation:</strong> Only stocks with Score ≥ 90 and Probability of Success ≥ 70% generate signals</li>
            <li><strong>Expectancy-Optimized:</strong> System optimizes for Expected Profit = (Win% × Avg Win) - (Loss% × Avg Loss), not just accuracy</li>
            <li><strong>Risk Management:</strong> Every signal includes Entry, Stop Loss, Target with minimum 1.5:1 Reward:Risk ratio</li>
            <li><strong>AI Explanation:</strong> Claude explains WHY a stock scored high (not used for prediction, only explanation)</li>
            <li><strong>Walk-Forward Validated:</strong> All models trained on historical data with proper out-of-sample testing</li>
          </ul>
        </div>
      </div>
    </div>
  );
};

export default MLIntradayDashboard;
