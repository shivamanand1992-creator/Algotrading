import React, { useState, useEffect } from 'react';
import './OptionsStrategyAdvisor.css';
import { api } from '../../api/client';

export default function OptionsStrategyAdvisor() {
  const [analysis, setAnalysis] = useState(null);
  const [selectedStrategy, setSelectedStrategy] = useState(null);
  const [spreadDetails, setSpreadDetails] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [refreshInterval, setRefreshInterval] = useState(300000); // 5 min default
  const [lastUpdate, setLastUpdate] = useState(null);

  // Fetch strategy analysis
  const fetchStrategyAnalysis = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.get('/api/ml-intraday/options-strategy-analysis');
      setAnalysis(response.data);
      setLastUpdate(new Date().toLocaleTimeString('en-IN'));
      setSelectedStrategy(response.data.primary_strategy.name);
      setSpreadDetails(null);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to fetch strategy analysis');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  // Fetch spread details
  const fetchSpreadDetails = async (spreadName) => {
    try {
      const response = await api.get(`/api/ml-intraday/options-spread-details/${encodeURIComponent(spreadName)}`);
      setSpreadDetails(response.data);
    } catch (err) {
      console.error('Failed to fetch spread details:', err);
    }
  };

  // Auto-refresh
  useEffect(() => {
    fetchStrategyAnalysis();
    const interval = setInterval(fetchStrategyAnalysis, refreshInterval);
    return () => clearInterval(interval);
  }, [refreshInterval]);

  // Fetch spread details when strategy changes
  useEffect(() => {
    if (selectedStrategy && analysis) {
      fetchSpreadDetails(selectedStrategy);
    }
  }, [selectedStrategy, analysis]);

  if (error) {
    return (
      <div className="strategy-advisor-container">
        <div className="error-message">
          <h3>⚠️ Error</h3>
          <p>{error}</p>
          <button onClick={fetchStrategyAnalysis} className="btn btn-retry">Retry</button>
        </div>
      </div>
    );
  }

  if (!analysis && loading) {
    return (
      <div className="strategy-advisor-container">
        <div className="loading">Loading strategy analysis...</div>
      </div>
    );
  }

  if (!analysis) {
    return (
      <div className="strategy-advisor-container">
        <button onClick={fetchStrategyAnalysis} className="btn btn-primary">
          Load Strategy Analysis
        </button>
      </div>
    );
  }

  const { market_analysis, primary_strategy, alternative_strategies, rationale, risk_factors, profit_targets, stop_loss_level } = analysis;

  return (
    <div className="strategy-advisor-container">
      <div className="advisor-header">
        <h1>📊 Options Strategy Advisor</h1>
        <p>Monthly Income Strategy Engine</p>
        <div className="header-controls">
          <button onClick={fetchStrategyAnalysis} className="btn btn-refresh" disabled={loading}>
            {loading ? '⟳ Refreshing...' : '⟳ Refresh Now'}
          </button>
          <select
            value={refreshInterval}
            onChange={(e) => setRefreshInterval(parseInt(e.target.value))}
            className="refresh-interval-select"
          >
            <option value={60000}>1 min</option>
            <option value={300000}>5 min</option>
            <option value={600000}>10 min</option>
            <option value={900000}>15 min</option>
          </select>
          {lastUpdate && <span className="last-update">Last update: {lastUpdate}</span>}
        </div>
      </div>

      {/* Market Analysis Section */}
      <section className="market-analysis-section">
        <h2>📈 Market Analysis</h2>
        <div className="market-grid">
          <div className="market-card">
            <div className="card-label">NIFTY Price</div>
            <div className="card-value">{market_analysis.nifty_price.toFixed(0)}</div>
            <div className={`card-change ${market_analysis.daily_change_pct >= 0 ? 'positive' : 'negative'}`}>
              {market_analysis.daily_change_pct >= 0 ? '▲' : '▼'} {Math.abs(market_analysis.daily_change_pct).toFixed(2)}%
            </div>
          </div>

          <div className="market-card">
            <div className="card-label">Trend</div>
            <div className={`card-value trend-${market_analysis.trend.toLowerCase()}`}>
              {market_analysis.trend}
            </div>
          </div>

          <div className="market-card">
            <div className="card-label">IV Percentile</div>
            <div className="card-value">{market_analysis.volatility.toFixed(0)}</div>
            <div className="card-meta">
              {market_analysis.volatility < 30 ? 'Low' : market_analysis.volatility > 70 ? 'High' : 'Normal'}
            </div>
          </div>

          <div className="market-card">
            <div className="card-label">RSI (14)</div>
            <div className={`card-value rsi-${market_analysis.rsi < 30 ? 'oversold' : market_analysis.rsi > 70 ? 'overbought' : 'normal'}`}>
              {market_analysis.rsi.toFixed(0)}
            </div>
          </div>

          <div className="market-card">
            <div className="card-label">Support</div>
            <div className="card-value">{market_analysis.support_level.toFixed(0)}</div>
            <div className="card-meta">{market_analysis.distance_to_support.toFixed(1)}% away</div>
          </div>

          <div className="market-card">
            <div className="card-label">Resistance</div>
            <div className="card-value">{market_analysis.resistance_level.toFixed(0)}</div>
            <div className="card-meta">{market_analysis.distance_to_resistance.toFixed(1)}% away</div>
          </div>

          <div className="market-card">
            <div className="card-label">MACD</div>
            <div className={`card-value macd-${market_analysis.macd_signal.toLowerCase()}`}>
              {market_analysis.macd_signal}
            </div>
          </div>

          <div className="market-card">
            <div className="card-label">Volume</div>
            <div className="card-value">{market_analysis.volume_ratio.toFixed(2)}x</div>
            <div className="card-meta">vs 20-day avg</div>
          </div>
        </div>
      </section>

      {/* Strategy Recommendation Section */}
      <section className="strategy-section">
        <h2>🎯 Recommended Strategy</h2>

        <div className="strategy-rationale">
          <p><strong>📌 Rationale:</strong> {rationale}</p>
        </div>

        <div className="strategy-cards">
          <div className="primary-strategy-card strategy-card">
            <div className="strategy-header">
              <h3>{primary_strategy.name}</h3>
              <span className="badge badge-primary">PRIMARY PICK</span>
            </div>
            <p className="description">{primary_strategy.description}</p>

            <div className="strategy-metrics">
              <div className="metric">
                <span className="metric-label">Max Profit</span>
                <span className="metric-value profit">+₹{primary_strategy.max_profit.toFixed(0)}</span>
              </div>
              <div className="metric">
                <span className="metric-label">Max Loss</span>
                <span className="metric-value loss">-₹{primary_strategy.max_loss.toFixed(0)}</span>
              </div>
              <div className="metric">
                <span className="metric-label">Risk/Reward</span>
                <span className="metric-value">{primary_strategy.reward_risk_ratio.toFixed(2)}:1</span>
              </div>
              <div className="metric">
                <span className="metric-label">Win Probability</span>
                <span className="metric-value">{primary_strategy.probability_profit.toFixed(0)}%</span>
              </div>
              <div className="metric">
                <span className="metric-label">Capital Required</span>
                <span className="metric-value">₹{primary_strategy.capital_required.toFixed(0)}</span>
              </div>
            </div>

            <div className="strategy-legs">
              <h4>📋 Position Legs</h4>
              {primary_strategy.legs.map((leg, idx) => (
                <div key={idx} className="leg">
                  <span className={`leg-action ${leg.position.toLowerCase()}`}>{leg.position}</span>
                  <span className="leg-contract">{leg.qty}x {leg.type} {leg.strike}</span>
                </div>
              ))}
            </div>

            <div className="breakevens">
              <h4>💰 Breakeven Points</h4>
              <div className="be-values">
                {primary_strategy.breakeven_points.map((be, idx) => (
                  <div key={idx} className="be-point">₹{be.toFixed(0)}</div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Alternative Strategies */}
        {alternative_strategies.length > 0 && (
          <div className="alternative-strategies">
            <h3>📚 Alternative Strategies</h3>
            <div className="alternative-cards">
              {alternative_strategies.map((strat, idx) => (
                <div
                  key={idx}
                  className={`strategy-card alternative ${selectedStrategy === strat.name ? 'selected' : ''}`}
                  onClick={() => {
                    setSelectedStrategy(strat.name);
                  }}
                >
                  <h4>{strat.name}</h4>
                  <div className="alt-metrics">
                    <div>Max Profit: +₹{strat.max_profit.toFixed(0)}</div>
                    <div>Max Loss: -₹{strat.max_loss.toFixed(0)}</div>
                    <div>R:R: {strat.reward_risk_ratio.toFixed(2)}:1</div>
                    <div>Win: {strat.probability_profit.toFixed(0)}%</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      {/* Entry/Exit Section */}
      <section className="entry-exit-section">
        <h2>🚀 Entry & Exit Plan</h2>
        <div className="entry-exit-grid">
          <div className="entry-exit-card">
            <h3>📍 Entry</h3>
            <div className="entry-details">
              <p><strong>Time:</strong> {analysis.ideal_entry_time}</p>
              <p><strong>Price:</strong> Market order near midpoint or limit at current price</p>
              <p><strong>Expiry:</strong> {analysis.expiry_days} days (Weekly/Monthly)</p>
            </div>
          </div>

          <div className="entry-exit-card">
            <h3>🎯 Profit Targets</h3>
            <div className="targets">
              {Object.entries(profit_targets).map(([level, amount]) => (
                <div key={level} className="target">
                  <span>{level} of max profit:</span>
                  <span className="amount">₹{Math.abs(amount).toFixed(0)}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="entry-exit-card">
            <h3>🛑 Stop Loss</h3>
            <div className="stop-loss">
              <p><strong>SL Level:</strong> ₹{stop_loss_level.toFixed(0)}</p>
              <p><strong>Logic:</strong> Exit if loss exceeds 30% of capital or at EOD</p>
            </div>
          </div>
        </div>
      </section>

      {/* Risk Factors */}
      <section className="risk-section">
        <h2>⚠️ Risk Factors</h2>
        <div className="risk-list">
          {risk_factors.map((risk, idx) => (
            <div key={idx} className="risk-item">
              <span className="risk-icon">⚠️</span>
              <span>{risk}</span>
            </div>
          ))}
        </div>
      </section>

      {/* Spread Details (when spread is selected) */}
      {spreadDetails && (
        <section className="spread-details-section">
          <h2>📊 {spreadDetails.spread.name} - Detailed Analysis</h2>

          <div className="payoff-container">
            <h3>P&L Across Price Levels</h3>
            <div className="payoff-graph">
              <div className="payoff-info">
                <p>Max Profit: <span className="profit">+₹{spreadDetails.payoff_data.max_profit.toFixed(0)}</span></p>
                <p>Max Loss: <span className="loss">-₹{spreadDetails.payoff_data.max_loss.toFixed(0)}</span></p>
                <p>Breakevens: <span>{spreadDetails.payoff_data.breakeven_points.map(b => `₹${b.toFixed(0)}`).join(', ')}</span></p>
              </div>
              {/* Simple ASCII representation */}
              <pre className="payoff-ascii">
                {renderPayoffGraph(spreadDetails.payoff_data.price_levels, spreadDetails.payoff_data.pnl)}
              </pre>
            </div>
          </div>

          <div className="greeks-container">
            <h3>Greeks at Current Price</h3>
            <div className="greeks-grid">
              <div className="greek-card">
                <div className="greek-label">Delta (Δ)</div>
                <div className="greek-value">{spreadDetails.current_greeks.delta.toFixed(2)}</div>
                <div className="greek-desc">Directional exposure</div>
              </div>
              <div className="greek-card">
                <div className="greek-label">Gamma (Γ)</div>
                <div className="greek-value">{spreadDetails.current_greeks.gamma.toFixed(3)}</div>
                <div className="greek-desc">Delta sensitivity</div>
              </div>
              <div className="greek-card">
                <div className="greek-label">Theta (Θ)</div>
                <div className="greek-value">{spreadDetails.current_greeks.theta.toFixed(2)}</div>
                <div className="greek-desc">Daily decay ₹</div>
              </div>
              <div className="greek-card">
                <div className="greek-label">Vega (ν)</div>
                <div className="greek-value">{spreadDetails.current_greeks.vega.toFixed(2)}</div>
                <div className="greek-desc">IV sensitivity</div>
              </div>
            </div>
          </div>

          <div className="position-sizing-container">
            <h3>Position Sizing & Risk</h3>
            <div className="sizing-grid">
              {Object.entries(spreadDetails.position_sizing).map(([key, value]) => (
                <div key={key} className="sizing-item">
                  <span className="sizing-label">{formatLabel(key)}</span>
                  <span className={`sizing-value ${key.includes('loss') ? 'loss' : key.includes('profit') ? 'profit' : ''}`}>
                    {typeof value === 'number' ? (key.includes('ratio') ? value.toFixed(2) : `₹${value.toFixed(0)}`) : value}
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div className="entry-exit-guide">
            <h3>📋 Entry/Exit Guide</h3>
            <div className="guide-grid">
              {Object.entries(spreadDetails.entry_exit_guide).map(([key, value]) => (
                <div key={key} className="guide-item">
                  <div className="guide-label">{formatLabel(key)}</div>
                  {typeof value === 'object' ? (
                    <div className="guide-values">
                      {Object.entries(value).map(([k, v]) => (
                        <div key={k} className="guide-sub">
                          <span>{k}:</span> <span className="value">{v}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="guide-value">{value}</div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}

// Helper function to render payoff graph
function renderPayoffGraph(prices, pnl) {
  if (prices.length === 0) return 'No data';

  const min_pnl = Math.min(...pnl);
  const max_pnl = Math.max(...pnl);
  const range = max_pnl - min_pnl || 1;

  // Sample every 5th point for ASCII graph
  const step = Math.max(1, Math.floor(prices.length / 50));
  const lines = [];

  // Find zero line
  const zero_normalized = -min_pnl / range;

  for (let i = 0; i < prices.length; i += step) {
    const price = prices[i];
    const value = pnl[i];
    const normalized = (value - min_pnl) / range;

    // Create a simple bar
    const barLength = Math.round(normalized * 40);
    const bar = '*'.repeat(Math.max(0, barLength));

    lines.push(`${price.toFixed(0).padStart(6)} | ${bar}`);
  }

  return lines.join('\n');
}

// Helper function to format label
function formatLabel(str) {
  return str
    .replace(/_/g, ' ')
    .replace(/([A-Z])/g, ' $1')
    .replace(/^\s+/, '')
    .split(' ')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}
