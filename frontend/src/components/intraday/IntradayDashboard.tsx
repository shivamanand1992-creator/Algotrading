import React, { useEffect, useState } from 'react';
import { Card } from '../ui/Card';
import { api } from '../../api/client';

interface IntradaySignal {
  symbol: string;
  signal_type: string;
  confidence: number;
  entry_price: number;
  target: number;
  stop_loss: number;
  timestamp: string;
}

export function IntradayDashboard() {
  const [signals, setSignals] = useState<IntradaySignal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchIntradaySignals();
    const interval = setInterval(fetchIntradaySignals, 60000); // Refresh every minute
    return () => clearInterval(interval);
  }, []);

  const fetchIntradaySignals = async () => {
    try {
      const response = await api.get('/api/intraday/signals');
      setSignals(response.data.signals || []);
      setError(null);
    } catch (err: any) {
      console.error('Failed to fetch intraday signals:', err);
      setError(err.response?.data?.error || 'Failed to load intraday signals');
    } finally {
      setLoading(false);
    }
  };

  const getSignalColor = (type: string) => {
    return type === 'BUY' ? '#00e676' : '#ff5252';
  };

  const getConfidenceColor = (confidence: number) => {
    if (confidence >= 0.75) return '#00e676';
    if (confidence >= 0.60) return '#ffd600';
    return '#ff6e40';
  };

  if (loading) {
    return (
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '400px',
        color: 'rgba(0,229,255,0.4)',
        fontFamily: "'Courier New', monospace",
        fontSize: 12,
        letterSpacing: 2,
      }}>
        LOADING INTRADAY SIGNALS...
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 1600, margin: '0 auto' }}>
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <h1 style={{
          fontSize: 28,
          fontWeight: 900,
          color: '#00e5ff',
          fontFamily: "'Courier New', monospace",
          letterSpacing: '0.15em',
          textShadow: '0 0 20px rgba(0,229,255,0.4)',
          marginBottom: 8,
        }}>
          INTRADAY TRADING
        </h1>
        <p style={{
          color: 'rgba(160,196,224,0.5)',
          fontSize: 12,
          letterSpacing: '0.1em',
          fontFamily: 'monospace',
        }}>
          Real-time intraday trading signals and setups
        </p>
      </div>

      {error && (
        <Card
          title="Error"
          style={{ marginBottom: 20, borderLeft: '3px solid #ff5252' }}
        >
          <p style={{ color: '#ff5252', fontSize: 14 }}>{error}</p>
        </Card>
      )}

      {/* Signals Grid */}
      {signals.length === 0 ? (
        <Card title="No Active Signals">
          <p style={{
            color: 'rgba(160,196,224,0.5)',
            fontSize: 14,
            textAlign: 'center',
            padding: '40px 20px',
          }}>
            No intraday signals detected at this time. Check back during market hours.
          </p>
        </Card>
      ) : (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))',
          gap: 20,
        }}>
          {signals.map((signal, idx) => (
            <Card
              key={`${signal.symbol}-${idx}`}
              title={signal.symbol}
              style={{
                borderLeft: `3px solid ${getSignalColor(signal.signal_type)}`,
              }}
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {/* Signal Type */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 700,
                      letterSpacing: '0.1em',
                      color: 'rgba(160,196,224,0.5)',
                      fontFamily: 'monospace',
                    }}
                  >
                    SIGNAL
                  </span>
                  <span
                    style={{
                      fontSize: 14,
                      fontWeight: 900,
                      color: getSignalColor(signal.signal_type),
                      fontFamily: "'Courier New', monospace",
                      letterSpacing: '0.15em',
                      textShadow: `0 0 10px ${getSignalColor(signal.signal_type)}80`,
                    }}
                  >
                    {signal.signal_type}
                  </span>
                </div>

                {/* Confidence */}
                <div>
                  <div style={{
                    fontSize: 11,
                    fontWeight: 700,
                    letterSpacing: '0.1em',
                    color: 'rgba(160,196,224,0.5)',
                    fontFamily: 'monospace',
                    marginBottom: 6,
                  }}>
                    CONFIDENCE
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <div style={{
                      flex: 1,
                      height: 6,
                      background: 'rgba(255,255,255,0.05)',
                      borderRadius: 3,
                      overflow: 'hidden',
                    }}>
                      <div
                        style={{
                          height: '100%',
                          width: `${signal.confidence * 100}%`,
                          background: getConfidenceColor(signal.confidence),
                          borderRadius: 3,
                          transition: 'width 0.3s ease',
                        }}
                      />
                    </div>
                    <span
                      style={{
                        fontSize: 13,
                        fontWeight: 700,
                        color: getConfidenceColor(signal.confidence),
                        fontFamily: 'monospace',
                      }}
                    >
                      {Math.round(signal.confidence * 100)}%
                    </span>
                  </div>
                </div>

                {/* Price Levels */}
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 1fr 1fr',
                  gap: 10,
                  marginTop: 8,
                }}>
                  <div>
                    <div style={{
                      fontSize: 9,
                      color: 'rgba(160,196,224,0.4)',
                      letterSpacing: '0.1em',
                      fontFamily: 'monospace',
                      marginBottom: 4,
                    }}>
                      ENTRY
                    </div>
                    <div style={{
                      fontSize: 14,
                      fontWeight: 700,
                      color: '#00e5ff',
                      fontFamily: 'monospace',
                    }}>
                      ₹{signal.entry_price.toFixed(2)}
                    </div>
                  </div>
                  <div>
                    <div style={{
                      fontSize: 9,
                      color: 'rgba(160,196,224,0.4)',
                      letterSpacing: '0.1em',
                      fontFamily: 'monospace',
                      marginBottom: 4,
                    }}>
                      TARGET
                    </div>
                    <div style={{
                      fontSize: 14,
                      fontWeight: 700,
                      color: '#00e676',
                      fontFamily: 'monospace',
                    }}>
                      ₹{signal.target.toFixed(2)}
                    </div>
                  </div>
                  <div>
                    <div style={{
                      fontSize: 9,
                      color: 'rgba(160,196,224,0.4)',
                      letterSpacing: '0.1em',
                      fontFamily: 'monospace',
                      marginBottom: 4,
                    }}>
                      STOP LOSS
                    </div>
                    <div style={{
                      fontSize: 14,
                      fontWeight: 700,
                      color: '#ff5252',
                      fontFamily: 'monospace',
                    }}>
                      ₹{signal.stop_loss.toFixed(2)}
                    </div>
                  </div>
                </div>

                {/* Timestamp */}
                <div style={{
                  fontSize: 10,
                  color: 'rgba(160,196,224,0.3)',
                  letterSpacing: '0.05em',
                  fontFamily: 'monospace',
                  marginTop: 8,
                  paddingTop: 10,
                  borderTop: '1px solid rgba(0,229,255,0.08)',
                }}>
                  {new Date(signal.timestamp).toLocaleString()}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
