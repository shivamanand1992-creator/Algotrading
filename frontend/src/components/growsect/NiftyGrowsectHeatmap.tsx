import React, { useState, useEffect } from 'react';
import { api } from '../../api/client';

interface Sector {
  avg_change_pct: number;
  gainers: number;
  losers: number;
  strength: string;
  stocks: string[];
}

interface Stock {
  symbol: string;
  price: number;
  change_pct: number;
  sector: string;
  rsi: number;
  trend: string;
  color: string;
}

interface Signal {
  symbol: string;
  sector: string;
  change_pct: number;
  price: number;
  rsi: number;
  confidence?: {
    score: number;
    factors: {
      rsi: string;
      macd: string;
      volume: string;
      trend_strength: string;
      ema_alignment: string;
    };
  };
  technical?: {
    support_resistance: { support: number; resistance: number; distance_to_support_pct: number; distance_to_resistance_pct: number };
    bollinger_bands: { upper: number; middle: number; lower: number; pct_b: number; status: string };
    momentum: { macd_line: number; macd_signal: number; macd_histogram: number; direction: string };
    trend_strength: { adx: number; strength: string };
    ema_alignment: { ema50: number; ema100: number; ema200: number; bullish: boolean; status: string };
    volume: { ratio: number; strength: string };
    rsi: { value: number; zone: string };
  };
}

export function NiftyGrowsectHeatmap() {
  const [heatmapData, setHeatmapData] = useState<any>(null);
  const [stocks, setStocks] = useState<Stock[]>([]);
  const [signals, setSignals] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'heatmap' | 'stocks' | 'signals'>('heatmap');
  const [expandedSignal, setExpandedSignal] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        const [heatmapRes, stocksRes, signalsRes] = await Promise.all([
          api.get('/api/growsect/heatmap'),
          api.get('/api/growsect/stocks'),
          api.get('/api/growsect/signals'),
        ]);

        setHeatmapData(heatmapRes.data);
        setStocks(stocksRes.data.stocks || []);
        setSignals(signalsRes.data);
      } catch (error) {
        console.error('Failed to fetch GROWSECT data:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 60000); // Update every minute
    return () => clearInterval(interval);
  }, []);

  const getStrengthColor = (strength: string) => {
    switch (strength) {
      case 'VERY_STRONG': return '#00cc00';
      case 'STRONG': return '#90ee90';
      case 'NEUTRAL': return '#cccccc';
      case 'WEAK': return '#ffb3b3';
      case 'VERY_WEAK': return '#cc0000';
      default: return '#cccccc';
    }
  };

  if (loading) return <div style={{ padding: '20px', color: '#fff' }}>Loading...</div>;

  return (
    <div style={{
      padding: '20px',
      background: '#050d1a',
      color: '#00e5ff',
      fontFamily: "'Courier New', monospace",
      borderRadius: '8px',
      minHeight: '600px',
    }}>
      {/* Header */}
      <div style={{ marginBottom: '20px' }}>
        <h2 style={{ margin: '0 0 10px 0', fontSize: '24px', fontWeight: 700 }}>
          💰 NIFTY GROWSECT 15 — Real-time Heatmap
        </h2>
        <p style={{ margin: 0, fontSize: '12px', color: 'rgba(0,229,255,0.6)' }}>
          {heatmapData?.message || '15 High-growth stocks | Updates every 1 minute'}
        </p>
      </div>

      {/* Tab Navigation */}
      <div style={{ display: 'flex', gap: '10px', marginBottom: '20px', borderBottom: '1px solid rgba(0,229,255,0.2)', paddingBottom: '10px' }}>
        {['heatmap', 'stocks', 'signals'].map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab as any)}
            style={{
              padding: '8px 16px',
              background: activeTab === tab ? 'rgba(0,229,255,0.2)' : 'transparent',
              color: activeTab === tab ? '#00e5ff' : 'rgba(0,229,255,0.5)',
              border: `1px solid ${activeTab === tab ? '#00e5ff' : 'rgba(0,229,255,0.2)'}`,
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '12px',
              fontFamily: 'monospace',
              fontWeight: activeTab === tab ? 700 : 400,
              transition: 'all 0.2s',
            }}
          >
            {tab === 'heatmap' && '📊 Sectors'}
            {tab === 'stocks' && '📈 Stocks'}
            {tab === 'signals' && '🎯 Signals'}
          </button>
        ))}
      </div>

      {/* Heatmap Tab */}
      {activeTab === 'heatmap' && heatmapData && (
        <div>
          <div style={{ marginBottom: '20px' }}>
            <h3 style={{ margin: '0 0 15px 0', fontSize: '14px', color: '#00e5ff' }}>Sector Strength</h3>
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
              gap: '12px',
            }}>
              {Object.entries(heatmapData.sectors || {}).map(([sector, data]: [string, any]) => (
                <div
                  key={sector}
                  style={{
                    padding: '12px',
                    borderRadius: '8px',
                    background: `${getStrengthColor(data.strength)}20`,
                    border: `2px solid ${getStrengthColor(data.strength)}`,
                    textAlign: 'center',
                  }}
                >
                  <div style={{ fontWeight: 700, marginBottom: '5px' }}>{sector}</div>
                  <div style={{ fontSize: '14px', fontWeight: 700, color: getStrengthColor(data.strength) }}>
                    {data.avg_change_pct > 0 ? '+' : ''}{data.avg_change_pct.toFixed(2)}%
                  </div>
                  <div style={{ fontSize: '10px', color: 'rgba(0,229,255,0.6)', marginTop: '5px' }}>
                    🟢 {data.gainers} | 🔴 {data.losers}
                  </div>
                  <div style={{ fontSize: '10px', fontWeight: 700, marginTop: '5px', color: getStrengthColor(data.strength) }}>
                    {data.strength}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: '20px',
            marginTop: '20px',
          }}>
            <div style={{
              padding: '15px',
              background: 'rgba(0, 204, 0, 0.1)',
              border: '1px solid #00cc00',
              borderRadius: '8px',
            }}>
              <div style={{ fontWeight: 700, marginBottom: '10px' }}>🟢 Strongest Sector</div>
              <div style={{ fontSize: '16px', color: '#00cc00', fontWeight: 700 }}>
                {heatmapData.most_bullish}
              </div>
              <div style={{ fontSize: '12px', color: 'rgba(0,229,255,0.6)', marginTop: '5px' }}>
                Leading today's gains
              </div>
            </div>
            <div style={{
              padding: '15px',
              background: 'rgba(204, 0, 0, 0.1)',
              border: '1px solid #cc0000',
              borderRadius: '8px',
            }}>
              <div style={{ fontWeight: 700, marginBottom: '10px' }}>🔴 Weakest Sector</div>
              <div style={{ fontSize: '16px', color: '#cc0000', fontWeight: 700 }}>
                {heatmapData.most_bearish}
              </div>
              <div style={{ fontSize: '12px', color: 'rgba(0,229,255,0.6)', marginTop: '5px' }}>
                Lagging today
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Stocks Tab */}
      {activeTab === 'stocks' && stocks.length > 0 && (
        <div>
          <div style={{
            overflowX: 'auto',
            marginBottom: '20px',
          }}>
            <table style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontSize: '11px',
            }}>
              <thead>
                <tr style={{ borderBottom: '1px solid rgba(0,229,255,0.2)' }}>
                  <th style={{ padding: '10px', textAlign: 'left', color: '#00e5ff', fontWeight: 700 }}>Symbol</th>
                  <th style={{ padding: '10px', textAlign: 'right', color: '#00e5ff', fontWeight: 700 }}>Price</th>
                  <th style={{ padding: '10px', textAlign: 'right', color: '#00e5ff', fontWeight: 700 }}>Change %</th>
                  <th style={{ padding: '10px', textAlign: 'center', color: '#00e5ff', fontWeight: 700 }}>Sector</th>
                  <th style={{ padding: '10px', textAlign: 'right', color: '#00e5ff', fontWeight: 700 }}>RSI</th>
                  <th style={{ padding: '10px', textAlign: 'center', color: '#00e5ff', fontWeight: 700 }}>Trend</th>
                </tr>
              </thead>
              <tbody>
                {stocks.map((stock) => (
                  <tr
                    key={stock.symbol}
                    style={{
                      borderBottom: '1px solid rgba(0,229,255,0.1)',
                      background: `${stock.color}15`,
                    }}
                  >
                    <td style={{ padding: '10px', fontWeight: 700, color: stock.color }}>{stock.symbol}</td>
                    <td style={{ padding: '10px', textAlign: 'right', color: '#00e5ff' }}>₹{stock.price.toFixed(2)}</td>
                    <td style={{
                      padding: '10px',
                      textAlign: 'right',
                      color: stock.color,
                      fontWeight: 700,
                    }}>
                      {stock.change_pct > 0 ? '+' : ''}{stock.change_pct.toFixed(2)}%
                    </td>
                    <td style={{ padding: '10px', textAlign: 'center', fontSize: '10px', color: 'rgba(0,229,255,0.6)' }}>
                      {stock.sector}
                    </td>
                    <td style={{ padding: '10px', textAlign: 'right', color: 'rgba(0,229,255,0.7)' }}>
                      {stock.rsi.toFixed(1)}
                    </td>
                    <td style={{
                      padding: '10px',
                      textAlign: 'center',
                      background: stock.color,
                      color: '#000',
                      fontWeight: 700,
                      fontSize: '10px',
                      borderRadius: '4px',
                    }}>
                      {stock.trend}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Signals Tab */}
      {activeTab === 'signals' && signals && (
        <div>
          <div style={{ marginBottom: '20px' }}>
            <p style={{ fontSize: '12px', color: 'rgba(0,229,255,0.7)', fontStyle: 'italic', margin: '0 0 15px 0' }}>
              {signals.recommendation}
            </p>
          </div>

          {['strong_buy', 'buy', 'sell', 'strong_sell'].map((category) => (
            signals[category].length > 0 && (
              <div key={category} style={{ marginBottom: '20px' }}>
                <h4 style={{
                  margin: '0 0 10px 0',
                  fontSize: '12px',
                  color: category.includes('buy') ? '#00cc00' : '#cc0000',
                  fontWeight: 700,
                }}>
                  {category === 'strong_buy' && '🟢 STRONG BUY'}
                  {category === 'buy' && '🟢 BUY'}
                  {category === 'sell' && '🔴 SELL'}
                  {category === 'strong_sell' && '🔴 STRONG SELL'}
                  {' '}({signals[category].length})
                </h4>
                <div style={{ display: 'grid', gap: '12px' }}>
                  {signals[category].map((signal: Signal) => (
                    <div
                      key={signal.symbol}
                      style={{
                        padding: '12px',
                        background: category.includes('buy') ? 'rgba(0,204,0,0.1)' : 'rgba(204,0,0,0.1)',
                        border: `1px solid ${category.includes('buy') ? '#00cc00' : '#cc0000'}`,
                        borderRadius: '8px',
                        cursor: 'pointer',
                        transition: 'all 0.2s',
                      }}
                      onClick={() => setExpandedSignal(expandedSignal === signal.symbol ? null : signal.symbol)}
                      onMouseEnter={(e) => {
                        (e.currentTarget as HTMLElement).style.background = category.includes('buy') ? 'rgba(0,204,0,0.15)' : 'rgba(204,0,0,0.15)';
                      }}
                      onMouseLeave={(e) => {
                        (e.currentTarget as HTMLElement).style.background = category.includes('buy') ? 'rgba(0,204,0,0.1)' : 'rgba(204,0,0,0.1)';
                      }}
                    >
                      {/* Header */}
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div>
                          <div style={{ fontWeight: 700, marginBottom: '8px', color: category.includes('buy') ? '#00cc00' : '#cc0000' }}>
                            {signal.symbol}
                            {signal.confidence && (
                              <span style={{ marginLeft: '8px', fontSize: '10px', color: 'rgba(0,229,255,0.6)' }}>
                                Confidence: {signal.confidence.score}%
                              </span>
                            )}
                          </div>
                          <div style={{ fontSize: '11px', color: 'rgba(0,229,255,0.7)', marginBottom: '5px' }}>
                            {signal.sector} | Price: ₹{signal.price.toFixed(2)}
                          </div>
                          <div style={{ fontSize: '11px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                            <span>Change: {signal.change_pct > 0 ? '+' : ''}{signal.change_pct.toFixed(2)}%</span>
                            <span>RSI: {signal.rsi.toFixed(1)}</span>
                          </div>
                        </div>
                        <span style={{ fontSize: '16px', opacity: 0.6 }}>
                          {expandedSignal === signal.symbol ? '▼' : '▶'}
                        </span>
                      </div>

                      {/* Expanded Technical Analysis */}
                      {expandedSignal === signal.symbol && signal.technical && (
                        <div style={{ marginTop: '15px', paddingTop: '15px', borderTop: '1px solid rgba(0,229,255,0.2)' }}>
                          <div style={{ fontSize: '11px', lineHeight: 1.8 }}>
                            {/* Support/Resistance */}
                            <div style={{ marginBottom: '12px' }}>
                              <div style={{ fontWeight: 700, color: '#00e5ff', marginBottom: '5px' }}>📍 Support & Resistance</div>
                              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', color: 'rgba(0,229,255,0.8)' }}>
                                <span>Support: ₹{signal.technical.support_resistance.support.toFixed(2)}</span>
                                <span>Resistance: ₹{signal.technical.support_resistance.resistance.toFixed(2)}</span>
                                <span>From Support: +{signal.technical.support_resistance.distance_to_support_pct.toFixed(2)}%</span>
                                <span>To Resistance: +{signal.technical.support_resistance.distance_to_resistance_pct.toFixed(2)}%</span>
                              </div>
                            </div>

                            {/* Bollinger Bands */}
                            <div style={{ marginBottom: '12px' }}>
                              <div style={{ fontWeight: 700, color: '#00e5ff', marginBottom: '5px' }}>📊 Bollinger Bands</div>
                              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', color: 'rgba(0,229,255,0.8)' }}>
                                <span>Upper: ₹{signal.technical.bollinger_bands.upper.toFixed(2)}</span>
                                <span>Lower: ₹{signal.technical.bollinger_bands.lower.toFixed(2)}</span>
                                <span>Position: {signal.technical.bollinger_bands.pct_b.toFixed(0)}% ({signal.technical.bollinger_bands.status})</span>
                              </div>
                            </div>

                            {/* MACD */}
                            <div style={{ marginBottom: '12px' }}>
                              <div style={{ fontWeight: 700, color: '#00e5ff', marginBottom: '5px' }}>⚡ MACD Momentum</div>
                              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', color: 'rgba(0,229,255,0.8)' }}>
                                <span>Direction: {signal.technical.momentum.direction}</span>
                                <span>Histogram: {signal.technical.momentum.macd_histogram.toFixed(4)}</span>
                              </div>
                            </div>

                            {/* Trend Strength */}
                            <div style={{ marginBottom: '12px' }}>
                              <div style={{ fontWeight: 700, color: '#00e5ff', marginBottom: '5px' }}>📈 Trend Strength (ADX)</div>
                              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', color: 'rgba(0,229,255,0.8)' }}>
                                <span>ADX: {signal.technical.trend_strength.adx.toFixed(1)}</span>
                                <span>Status: {signal.technical.trend_strength.strength}</span>
                              </div>
                            </div>

                            {/* EMA Alignment */}
                            <div style={{ marginBottom: '12px' }}>
                              <div style={{ fontWeight: 700, color: '#00e5ff', marginBottom: '5px' }}>🔄 EMA Alignment</div>
                              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', color: 'rgba(0,229,255,0.8)' }}>
                                <span>EMA50: ₹{signal.technical.ema_alignment.ema50.toFixed(2)}</span>
                                <span>EMA100: ₹{signal.technical.ema_alignment.ema100.toFixed(2)}</span>
                                <span>EMA200: ₹{signal.technical.ema_alignment.ema200.toFixed(2)}</span>
                                <span>{signal.technical.ema_alignment.status}</span>
                              </div>
                            </div>

                            {/* Volume & RSI */}
                            <div>
                              <div style={{ fontWeight: 700, color: '#00e5ff', marginBottom: '5px' }}>📊 Volume & RSI</div>
                              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', color: 'rgba(0,229,255,0.8)' }}>
                                <span>Volume Ratio: {signal.technical.volume.ratio.toFixed(2)}x ({signal.technical.volume.strength})</span>
                                <span>RSI: {signal.technical.rsi.value.toFixed(1)} ({signal.technical.rsi.zone})</span>
                              </div>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )
          ))}
        </div>
      )}

      {/* Footer */}
      <div style={{
        marginTop: '20px',
        paddingTop: '15px',
        borderTop: '1px solid rgba(0,229,255,0.2)',
        fontSize: '10px',
        color: 'rgba(0,229,255,0.5)',
        textAlign: 'center',
      }}>
        Updates every 1 minute during market hours (9:15 AM - 3:30 PM IST)
      </div>
    </div>
  );
}
