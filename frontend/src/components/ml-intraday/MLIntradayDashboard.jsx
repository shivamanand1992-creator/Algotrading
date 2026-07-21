import React, { useState, useEffect } from 'react';
import { api } from '../../api/client';
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
  const [niftyStatus, setNiftyStatus] = useState(null);
  const [niftyMsg, setNiftyMsg] = useState(null);
  const [capital, setCapital] = useState(100000);

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
      const response = await api.get('/api/ml-intraday/status');
      setSystemStatus(response.data);
    } catch (error) {
      console.error('Failed to fetch ML system status:', error);
    }
  };

  const fetchTopStocks = async () => {
    try {
      const response = await api.get('/api/ml-intraday/top-stocks');
      setTopStocks(response.data.stocks || []);
      setSignals(response.data.signals || []);
    } catch (error) {
      console.error('Failed to fetch top stocks:', error);
    }
    try {
      const pt = await api.get('/api/ml-intraday/paper-trades');
      setPaperTrades(pt.data);
    } catch (e) { /* noop */ }
  };

  const fetchNiftyStatus = async () => {
    try {
      const res = await api.get('/api/ml-intraday/nifty-status');
      setNiftyStatus(res.data);
    } catch (e) { /* noop */ }
  };

  useEffect(() => {
    fetchNiftyStatus();
    const interval = setInterval(fetchNiftyStatus, 15000);
    return () => clearInterval(interval);
  }, []);

  const niftyAction = async (endpoint, body, label) => {
    setNiftyMsg(`${label}...`);
    try {
      const res = await api.post(`/api/ml-intraday/${endpoint}`, body || {});
      setNiftyMsg(res.data.message || JSON.stringify(res.data));
      setTimeout(fetchNiftyStatus, 1500);
    } catch (error) {
      setNiftyMsg(`${label} failed: ${error.response?.data?.detail || error.message}`);
    }
  };

  const triggerAction = async (endpoint, label) => {
    setActionMsg(`${label}...`);
    try {
      const res = await api.post(`/api/ml-intraday/${endpoint}`);
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
      const response = await api.post('/api/ml-intraday/explain', {
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
        {/* NIFTY ML Auto-Trader — trained on 11 years of data */}
        <div className="ml-card" style={{ borderColor: 'rgba(0,230,118,0.25)' }}>
          <div className="card-header">
            <h2>🎯 NIFTY Auto-Trader</h2>
            {niftyStatus && (
              <span className={`status-badge ${niftyStatus.enabled ? 'active' : 'inactive'}`}
                style={{ padding: '0.4rem 1rem', borderRadius: 8, fontSize: '0.75rem', fontWeight: 700 }}>
                {niftyStatus.enabled ? `ACTIVE — ${niftyStatus.mode?.toUpperCase()}` : 'DISABLED'}
              </span>
            )}
          </div>

          {niftyStatus && (
            <div style={{ position: 'relative', zIndex: 1 }}>
              <div className="athena-stats-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '1rem', marginBottom: '1rem' }}>
                <div className="stat-item">
                  <span className="stat-label" style={{ fontSize: '0.7rem', color: 'var(--jarvis-text-secondary)', textTransform: 'uppercase' }}>Model</span>
                  <span style={{ fontFamily: 'monospace', color: niftyStatus.model_loaded ? '#00e676' : '#ff1744' }}>
                    {niftyStatus.model_loaded ? (niftyStatus.model_version || 'loaded') : 'NOT TRAINED'}
                  </span>
                </div>
                <div className="stat-item">
                  <span className="stat-label" style={{ fontSize: '0.7rem', color: 'var(--jarvis-text-secondary)', textTransform: 'uppercase' }}>Test Win Rate</span>
                  <span style={{ fontFamily: 'monospace', color: 'var(--jarvis-text-primary)' }}>
                    {niftyStatus.test_report ? `${(niftyStatus.test_report.win_rate * 100).toFixed(0)}% (${niftyStatus.test_report.trades} trades)` : '—'}
                  </span>
                </div>
                <div className="stat-item">
                  <span className="stat-label" style={{ fontSize: '0.7rem', color: 'var(--jarvis-text-secondary)', textTransform: 'uppercase' }}>Expectancy (after cost)</span>
                  <span style={{ fontFamily: 'monospace', fontWeight: 700, color: (niftyStatus.test_report?.expectancy_after_cost ?? 0) > 0 ? '#00e676' : '#ff1744' }}>
                    {niftyStatus.test_report ? `${niftyStatus.test_report.expectancy_after_cost > 0 ? '+' : ''}${niftyStatus.test_report.expectancy_after_cost}%/trade` : '—'}
                  </span>
                </div>
                <div className="stat-item">
                  <span className="stat-label" style={{ fontSize: '0.7rem', color: 'var(--jarvis-text-secondary)', textTransform: 'uppercase' }}>Live P(now)</span>
                  <span style={{ fontFamily: 'monospace', color: 'var(--jarvis-primary)' }}>
                    {niftyStatus.last_proba != null ? `${(niftyStatus.last_proba * 100).toFixed(1)}% @ ${niftyStatus.last_update}` : '—'}
                  </span>
                </div>
                <div className="stat-item">
                  <span className="stat-label" style={{ fontSize: '0.7rem', color: 'var(--jarvis-text-secondary)', textTransform: 'uppercase' }}>Session P&L</span>
                  <span style={{ fontFamily: 'monospace', fontWeight: 700, color: (niftyStatus.total_pnl_rs ?? 0) >= 0 ? '#00e676' : '#ff1744' }}>
                    ₹{niftyStatus.total_pnl_rs ?? 0} ({niftyStatus.trades_today ?? 0} trades)
                  </span>
                </div>
              </div>

              <p style={{ color: 'var(--jarvis-text-secondary)', fontSize: '0.8rem', marginBottom: '1rem' }}>
                Strategy: BUY NIFTYBEES when P ≥ {niftyStatus.threshold} | Target +0.8% / SL −0.4% |
                Entries 09:30–13:00 | Max hold 3.5h | Square-off 15:10
              </p>

              {niftyStatus.position && (
                <div style={{ padding: '0.75rem 1rem', background: 'rgba(0,230,118,0.08)', border: '1px solid rgba(0,230,118,0.3)', borderRadius: 8, marginBottom: '1rem', fontFamily: 'monospace', fontSize: '0.85rem' }}>
                  OPEN [{niftyStatus.position.mode?.toUpperCase()}]: NIFTYBEES ×{niftyStatus.position.qty} @ ₹{niftyStatus.position.entry_bees} |
                  NIFTY {niftyStatus.position.entry_nifty} → T {niftyStatus.position.target_nifty} / SL {niftyStatus.position.sl_nifty} |
                  P={niftyStatus.position.probability}%
                </div>
              )}

              <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', alignItems: 'center' }}>
                <button className="btn-explain" onClick={() => niftyAction('train-nifty', null, 'Training on 11yr data')}>
                  Train Model
                </button>
                <input
                  type="number" value={capital} step={10000} min={10000}
                  onChange={(e) => setCapital(Number(e.target.value))}
                  style={{ width: 110, padding: '0.45rem 0.6rem', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(0,229,255,0.25)', borderRadius: 6, color: 'var(--jarvis-text-primary)', fontFamily: 'monospace' }}
                />
                <button className="btn-explain" onClick={() => niftyAction('nifty-enable', { mode: 'paper', capital }, 'Enabling paper mode')}>
                  ▶ Paper Trade
                </button>
                <button
                  className="btn-explain"
                  style={{ background: 'linear-gradient(135deg, #ff1744, #f50057)', color: '#fff', opacity: niftyStatus.tradeable ? 1 : 0.4 }}
                  disabled={!niftyStatus.tradeable}
                  onClick={() => {
                    if (window.confirm(`⚠️ LIVE MODE: real orders on Angel One with ₹${capital.toLocaleString()} per trade. Confirm?`)) {
                      niftyAction('nifty-enable', { mode: 'live', capital }, 'Enabling LIVE mode');
                    }
                  }}>
                  🔴 GO LIVE
                </button>
                <button className="btn-close" style={{ fontSize: '0.75rem', padding: '0.5rem 1rem' }}
                  onClick={() => niftyAction('nifty-disable', null, 'Disabling')}>
                  ⏹ Stop
                </button>
              </div>
              {niftyMsg && <p style={{ marginTop: '0.75rem', color: 'var(--jarvis-text-secondary)', fontSize: '0.85rem' }}>{niftyMsg}</p>}

              {niftyStatus.trades_closed?.length > 0 && (
                <div className="signals-table-container" style={{ marginTop: '1rem' }}>
                  <table className="signals-table">
                    <thead>
                      <tr><th>Mode</th><th>Qty</th><th>Entry</th><th>Exit</th><th>P&L %</th><th>P&L ₹</th><th>Reason</th></tr>
                    </thead>
                    <tbody>
                      {niftyStatus.trades_closed.map((t, i) => (
                        <tr key={i}>
                          <td><span className="rr-badge">{t.mode}</span></td>
                          <td>{t.qty}</td>
                          <td className="price-cell">₹{t.entry_bees}</td>
                          <td className="price-cell">₹{t.exit_bees}</td>
                          <td className={t.pnl_pct >= 0 ? 'positive' : 'negative'}>{t.pnl_pct >= 0 ? '+' : ''}{t.pnl_pct}%</td>
                          <td className={t.pnl_rs >= 0 ? 'positive' : 'negative'}>₹{t.pnl_rs}</td>
                          <td className="time-cell">{t.exit_reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>

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
