import React, { useState, useEffect } from 'react';
import { api } from '../../api/client';
import './OptionTradingDashboard.css';

const StatusBadge = ({ status, mode }) => {
  const isActive = status === 'enabled';
  const isPaper = mode === 'paper';

  return (
    <div style={{
      display: 'inline-flex',
      gap: '0.5rem',
      alignItems: 'center',
    }}>
      <span style={{
        display: 'inline-block',
        width: 8,
        height: 8,
        borderRadius: '50%',
        background: isActive ? '#00e676' : '#666',
        animation: isActive ? 'pulse 2s infinite' : 'none',
      }} />
      <span style={{
        fontFamily: 'monospace',
        fontSize: '0.9rem',
        color: isActive ? '#00e676' : '#999',
      }}>
        {isActive ? '● ACTIVE' : '○ INACTIVE'} ({isPaper ? '📄 PAPER' : '🔴 LIVE'})
      </span>
    </div>
  );
};

const GreeksDisplay = ({ position }) => {
  if (!position) return null;

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(4, 1fr)',
      gap: '1rem',
      marginTop: '1rem',
      padding: '1rem',
      background: 'rgba(0, 229, 255, 0.05)',
      borderRadius: 8,
      border: '1px solid rgba(0, 229, 255, 0.1)',
    }}>
      <div>
        <div style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.5)', marginBottom: '0.25rem' }}>DELTA (Δ)</div>
        <div style={{ fontSize: '1.1rem', fontWeight: 'bold', color: '#00e5ff' }}>
          {position.delta?.toFixed(2) || '--'}
        </div>
        <div style={{ fontSize: '0.7rem', color: 'rgba(255,255,255,0.4)' }}>Directional</div>
      </div>

      <div>
        <div style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.5)', marginBottom: '0.25rem' }}>GAMMA (Γ)</div>
        <div style={{ fontSize: '1.1rem', fontWeight: 'bold', color: '#00e5ff' }}>
          {position.gamma?.toFixed(4) || '--'}
        </div>
        <div style={{ fontSize: '0.7rem', color: 'rgba(255,255,255,0.4)' }}>Acceleration</div>
      </div>

      <div>
        <div style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.5)', marginBottom: '0.25rem' }}>THETA (Θ)</div>
        <div style={{ fontSize: '1.1rem', fontWeight: 'bold', color: position.theta < 0 ? '#ff9100' : '#00e5ff' }}>
          {position.theta?.toFixed(3) || '--'}
        </div>
        <div style={{ fontSize: '0.7rem', color: 'rgba(255,255,255,0.4)' }}>Time Decay</div>
      </div>

      <div>
        <div style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.5)', marginBottom: '0.25rem' }}>VEGA (ν)</div>
        <div style={{ fontSize: '1.1rem', fontWeight: 'bold', color: '#00e5ff' }}>
          {position.vega?.toFixed(2) || '--'}
        </div>
        <div style={{ fontSize: '0.7rem', color: 'rgba(255,255,255,0.4)' }}>IV Sensitivity</div>
      </div>
    </div>
  );
};

const PositionCard = ({ position }) => {
  if (!position) {
    return (
      <div style={{
        padding: '2rem',
        textAlign: 'center',
        color: 'rgba(255,255,255,0.5)',
        borderRadius: 8,
        background: 'rgba(0,0,0,0.2)',
        border: '1px solid rgba(255,255,255,0.1)',
      }}>
        No open position
      </div>
    );
  }

  return (
    <div style={{
      padding: '1.5rem',
      background: 'rgba(0, 229, 255, 0.08)',
      borderRadius: 8,
      border: '1px solid rgba(0, 229, 255, 0.2)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <div>
          <div style={{ fontSize: '0.85rem', color: 'rgba(255,255,255,0.6)' }}>CURRENT POSITION</div>
          <div style={{ fontSize: '1.3rem', fontWeight: 'bold', marginTop: '0.25rem' }}>
            {position.symbol}
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: '0.85rem', color: 'rgba(255,255,255,0.6)' }}>QTY</div>
          <div style={{ fontSize: '1.3rem', fontWeight: 'bold', color: '#00e5ff' }}>
            {position.quantity}
          </div>
        </div>
      </div>

      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(2, 1fr)',
        gap: '1rem',
        marginBottom: '1rem',
        padding: '1rem 0',
        borderTop: '1px solid rgba(0, 229, 255, 0.1)',
        borderBottom: '1px solid rgba(0, 229, 255, 0.1)',
      }}>
        <div>
          <div style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.5)' }}>Entry Premium</div>
          <div style={{ fontSize: '1.1rem', fontWeight: 'bold', color: '#00e5ff' }}>
            ₹{position.entry_premium?.toFixed(2) || '--'}
          </div>
        </div>
        <div>
          <div style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.5)' }}>Exp. Days</div>
          <div style={{ fontSize: '1.1rem', fontWeight: 'bold', color: '#00e5ff' }}>
            {position.days_to_expiry || '--'}
          </div>
        </div>
        <div>
          <div style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.5)' }}>Stop Loss</div>
          <div style={{ fontSize: '1.1rem', fontWeight: 'bold', color: '#ff6b6b' }}>
            ₹{position.stop_loss_premium?.toFixed(2) || '--'}
          </div>
        </div>
        <div>
          <div style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.5)' }}>Target</div>
          <div style={{ fontSize: '1.1rem', fontWeight: 'bold', color: '#00e676' }}>
            ₹{position.profit_target_premium?.toFixed(2) || '--'}
          </div>
        </div>
      </div>

      <GreeksDisplay position={position} />
    </div>
  );
};

const TradeHistoryTable = ({ trades }) => {
  if (!trades || trades.length === 0) {
    return <div style={{ padding: '1rem', textAlign: 'center', color: 'rgba(255,255,255,0.4)' }}>No trades yet</div>;
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{
        width: '100%',
        borderCollapse: 'collapse',
        fontSize: '0.85rem',
        fontFamily: 'monospace',
      }}>
        <thead>
          <tr style={{ borderBottom: '1px solid rgba(0, 229, 255, 0.2)' }}>
            <th style={{ padding: '0.75rem', textAlign: 'left', color: 'rgba(0, 229, 255, 0.8)' }}>Symbol</th>
            <th style={{ padding: '0.75rem', textAlign: 'left', color: 'rgba(0, 229, 255, 0.8)' }}>Entry</th>
            <th style={{ padding: '0.75rem', textAlign: 'left', color: 'rgba(0, 229, 255, 0.8)' }}>Exit</th>
            <th style={{ padding: '0.75rem', textAlign: 'left', color: 'rgba(0, 229, 255, 0.8)' }}>Qty</th>
            <th style={{ padding: '0.75rem', textAlign: 'right', color: 'rgba(0, 229, 255, 0.8)' }}>P&L %</th>
            <th style={{ padding: '0.75rem', textAlign: 'right', color: 'rgba(0, 229, 255, 0.8)' }}>P&L ₹</th>
            <th style={{ padding: '0.75rem', textAlign: 'left', color: 'rgba(0, 229, 255, 0.8)' }}>Reason</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade, idx) => (
            <tr key={idx} style={{ borderBottom: '1px solid rgba(0, 229, 255, 0.05)' }}>
              <td style={{ padding: '0.75rem', color: '#00e5ff' }}>{trade.symbol}</td>
              <td style={{ padding: '0.75rem', color: 'rgba(255,255,255,0.7)' }}>₹{trade.entry_premium?.toFixed(2)}</td>
              <td style={{ padding: '0.75rem', color: 'rgba(255,255,255,0.7)' }}>₹{trade.exit_premium?.toFixed(2)}</td>
              <td style={{ padding: '0.75rem', color: 'rgba(255,255,255,0.7)' }}>{trade.quantity}</td>
              <td style={{
                padding: '0.75rem',
                textAlign: 'right',
                color: trade.pnl_pct >= 0 ? '#00e676' : '#ff6b6b',
                fontWeight: 'bold',
              }}>
                {trade.pnl_pct >= 0 ? '+' : ''}{trade.pnl_pct?.toFixed(2)}%
              </td>
              <td style={{
                padding: '0.75rem',
                textAlign: 'right',
                color: trade.pnl_rupees >= 0 ? '#00e676' : '#ff6b6b',
                fontWeight: 'bold',
              }}>
                {trade.pnl_rupees >= 0 ? '+' : ''}₹{trade.pnl_rupees?.toFixed(0)}
              </td>
              <td style={{ padding: '0.75rem', color: 'rgba(255,255,255,0.5)', fontSize: '0.75rem' }}>
                {trade.exit_reason}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

const OptionTradingDashboard = () => {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState(null);
  const [capital, setCapital] = useState(100000);
  const [pollInterval, setPollInterval] = useState(5000);

  // Fetch status
  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, pollInterval);
    return () => clearInterval(interval);
  }, [pollInterval]);

  const fetchStatus = async () => {
    try {
      const response = await api.get('/api/ml-intraday/nifty-options-status');
      setStatus(response.data);
      setLoading(false);
    } catch (error) {
      console.error('Failed to fetch options status:', error);
    }
  };

  const handleEnable = async (mode) => {
    try {
      setLoading(true);
      const response = await api.post('/api/ml-intraday/nifty-options-enable', {
        mode,
        capital: parseInt(capital),
      });
      setMessage(`✓ Options trading enabled in ${mode} mode`);
      setStatus(response.data);
      setTimeout(() => setMessage(null), 3000);
    } catch (error) {
      setMessage(`✗ Failed to enable: ${error.response?.data?.detail || error.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleDisable = async () => {
    try {
      setLoading(true);
      const response = await api.post('/api/ml-intraday/nifty-options-disable');
      setMessage('✓ Options trading disabled');
      setStatus(response.data);
      setTimeout(() => setMessage(null), 3000);
    } catch (error) {
      setMessage(`✗ Failed to disable: ${error.response?.data?.detail || error.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleCycle = async () => {
    try {
      setLoading(true);
      const response = await api.post('/api/ml-intraday/nifty-options-cycle');
      setMessage('✓ Cycle executed');
      await new Promise(r => setTimeout(r, 1000));
      fetchStatus();
    } catch (error) {
      setMessage(`✗ Cycle failed: ${error.response?.data?.detail || error.message}`);
    } finally {
      setLoading(false);
    }
  };

  if (!status) {
    return <div style={{ padding: '2rem', color: 'rgba(255,255,255,0.5)' }}>Loading option trader status...</div>;
  }

  const stats = [
    { label: 'Model', value: status.model_loaded ? '✓ Loaded' : '✗ Not loaded', color: status.model_loaded ? '#00e676' : '#ff6b6b' },
    { label: 'Win Rate', value: status.win_rate ? `${(status.win_rate * 100).toFixed(0)}%` : 'N/A', color: '#00e5ff' },
    { label: 'Trades', value: status.trades_today || 0, color: '#00e5ff' },
    { label: 'Total P&L', value: `₹${status.total_pnl_rupees?.toFixed(0) || 0}`, color: status.total_pnl_rupees >= 0 ? '#00e676' : '#ff6b6b' },
  ];

  return (
    <div style={{ padding: '2rem', maxWidth: '1400px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ marginBottom: '2rem' }}>
        <h1 style={{ fontSize: '2rem', marginBottom: '0.5rem', color: '#00e5ff' }}>NIFTY OPTIONS TRADER</h1>
        <p style={{ color: 'rgba(255,255,255,0.6)', fontSize: '0.9rem' }}>
          Paper trading enabled by default. Switch to live once validated.
        </p>
      </div>

      {/* Message */}
      {message && (
        <div style={{
          padding: '1rem',
          marginBottom: '1rem',
          borderRadius: 8,
          background: message.includes('✓') ? 'rgba(0, 230, 118, 0.1)' : 'rgba(255, 107, 107, 0.1)',
          border: `1px solid ${message.includes('✓') ? 'rgba(0, 230, 118, 0.3)' : 'rgba(255, 107, 107, 0.3)'}`,
          color: message.includes('✓') ? '#00e676' : '#ff6b6b',
          fontFamily: 'monospace',
        }}>
          {message}
        </div>
      )}

      {/* Status Row */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))',
        gap: '1rem',
        marginBottom: '2rem',
      }}>
        {stats.map((stat, idx) => (
          <div key={idx} style={{
            padding: '1rem',
            background: 'rgba(0, 229, 255, 0.05)',
            borderRadius: 8,
            border: '1px solid rgba(0, 229, 255, 0.1)',
          }}>
            <div style={{ fontSize: '0.85rem', color: 'rgba(255,255,255,0.6)', marginBottom: '0.5rem' }}>
              {stat.label}
            </div>
            <div style={{ fontSize: '1.3rem', fontWeight: 'bold', color: stat.color }}>
              {stat.value}
            </div>
          </div>
        ))}
      </div>

      {/* Status & Controls */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: '2rem',
        marginBottom: '2rem',
      }}>
        {/* Left: Status */}
        <div>
          <h3 style={{ fontSize: '1.1rem', marginBottom: '1rem', color: '#00e5ff' }}>Status</h3>
          <div style={{
            padding: '1.5rem',
            background: 'rgba(0,0,0,0.2)',
            borderRadius: 8,
            border: '1px solid rgba(0, 229, 255, 0.1)',
          }}>
            <div style={{ marginBottom: '1rem' }}>
              <StatusBadge status={status.enabled ? 'enabled' : 'disabled'} mode={status.mode} />
            </div>
            {status.model_loaded && (
              <div style={{ fontSize: '0.85rem', color: 'rgba(255,255,255,0.7)', lineHeight: 1.6 }}>
                <div>Version: <span style={{ color: '#00e5ff' }}>{status.model_version}</span></div>
                <div>Threshold: <span style={{ color: '#00e5ff' }}>{(status.threshold * 100).toFixed(0)}%</span></div>
                <div>Tradeable: <span style={{ color: status.tradeable ? '#00e676' : '#ff6b6b' }}>
                  {status.tradeable ? '✓ Yes' : '✗ No'}
                </span></div>
              </div>
            )}
          </div>
        </div>

        {/* Right: Controls */}
        <div>
          <h3 style={{ fontSize: '1.1rem', marginBottom: '1rem', color: '#00e5ff' }}>Controls</h3>
          <div style={{
            padding: '1.5rem',
            background: 'rgba(0,0,0,0.2)',
            borderRadius: 8,
            border: '1px solid rgba(0, 229, 255, 0.1)',
          }}>
            <div style={{ marginBottom: '1rem' }}>
              <label style={{ fontSize: '0.85rem', color: 'rgba(255,255,255,0.6)', display: 'block', marginBottom: '0.5rem' }}>
                Capital per trade (₹)
              </label>
              <input
                type="number"
                value={capital}
                onChange={(e) => setCapital(e.target.value)}
                disabled={status.enabled}
                style={{
                  width: '100%',
                  padding: '0.5rem',
                  background: 'rgba(0, 229, 255, 0.1)',
                  border: '1px solid rgba(0, 229, 255, 0.3)',
                  borderRadius: 4,
                  color: '#00e5ff',
                  fontFamily: 'monospace',
                  opacity: status.enabled ? 0.6 : 1,
                  cursor: status.enabled ? 'not-allowed' : 'text',
                }}
              />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
              <button
                onClick={() => handleEnable('paper')}
                disabled={loading || status.enabled}
                style={{
                  padding: '0.75rem',
                  background: status.enabled ? 'rgba(0, 229, 255, 0.1)' : 'rgba(0, 229, 255, 0.2)',
                  border: '1px solid rgba(0, 229, 255, 0.4)',
                  borderRadius: 4,
                  color: '#00e5ff',
                  cursor: status.enabled ? 'not-allowed' : 'pointer',
                  fontWeight: 'bold',
                  opacity: status.enabled ? 0.5 : 1,
                  transition: 'all 0.2s',
                }}
                onMouseEnter={(e) => !status.enabled && (e.target.style.background = 'rgba(0, 229, 255, 0.3)')}
                onMouseLeave={(e) => !status.enabled && (e.target.style.background = 'rgba(0, 229, 255, 0.2)')}
              >
                📄 Paper Mode
              </button>

              <button
                onClick={() => handleEnable('live')}
                disabled={loading || status.enabled || !status.tradeable}
                style={{
                  padding: '0.75rem',
                  background: status.enabled ? 'rgba(0, 229, 255, 0.1)' : 'rgba(255, 107, 107, 0.2)',
                  border: `1px solid ${status.enabled ? 'rgba(0, 229, 255, 0.4)' : 'rgba(255, 107, 107, 0.4)'}`,
                  borderRadius: 4,
                  color: status.enabled ? '#00e5ff' : '#ff6b6b',
                  cursor: status.enabled || !status.tradeable ? 'not-allowed' : 'pointer',
                  fontWeight: 'bold',
                  opacity: status.enabled || !status.tradeable ? 0.5 : 1,
                  transition: 'all 0.2s',
                }}
                onMouseEnter={(e) => !status.enabled && status.tradeable && (e.target.style.background = 'rgba(255, 107, 107, 0.3)')}
                onMouseLeave={(e) => !status.enabled && status.tradeable && (e.target.style.background = 'rgba(255, 107, 107, 0.2)')}
              >
                🔴 Live Mode
              </button>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginTop: '0.75rem' }}>
              <button
                onClick={handleCycle}
                disabled={loading || !status.enabled}
                style={{
                  padding: '0.75rem',
                  background: 'rgba(0, 230, 118, 0.2)',
                  border: '1px solid rgba(0, 230, 118, 0.4)',
                  borderRadius: 4,
                  color: '#00e676',
                  cursor: !status.enabled ? 'not-allowed' : 'pointer',
                  fontWeight: 'bold',
                  opacity: !status.enabled ? 0.5 : 1,
                  transition: 'all 0.2s',
                }}
              >
                ▶ Run Cycle
              </button>

              <button
                onClick={handleDisable}
                disabled={loading || !status.enabled}
                style={{
                  padding: '0.75rem',
                  background: 'rgba(255, 107, 107, 0.2)',
                  border: '1px solid rgba(255, 107, 107, 0.4)',
                  borderRadius: 4,
                  color: '#ff6b6b',
                  cursor: !status.enabled ? 'not-allowed' : 'pointer',
                  fontWeight: 'bold',
                  opacity: !status.enabled ? 0.5 : 1,
                  transition: 'all 0.2s',
                }}
              >
                ⏹ Disable
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Current Position */}
      <div style={{ marginBottom: '2rem' }}>
        <h3 style={{ fontSize: '1.1rem', marginBottom: '1rem', color: '#00e5ff' }}>Current Position</h3>
        <PositionCard position={status.position} />
      </div>

      {/* Trade History */}
      <div>
        <h3 style={{ fontSize: '1.1rem', marginBottom: '1rem', color: '#00e5ff' }}>Trade History (Last 20)</h3>
        <div style={{
          background: 'rgba(0,0,0,0.2)',
          borderRadius: 8,
          border: '1px solid rgba(0, 229, 255, 0.1)',
          overflow: 'hidden',
        }}>
          <TradeHistoryTable trades={status.trades_closed} />
        </div>
      </div>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>
    </div>
  );
};

export default OptionTradingDashboard;
