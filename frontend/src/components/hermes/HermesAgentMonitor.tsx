import React, { useEffect, useState, useRef } from 'react';
import { Card } from '../ui/Card';
import { api } from '../../api/client';

interface AgentActivity {
  timestamp: string;
  action: string;
  details: string;
  status: 'analyzing' | 'executing' | 'monitoring' | 'waiting' | 'success' | 'error';
  confidence?: number;
  decision?: any;
}

interface HermesMetrics {
  enabled: boolean;
  instrument: string;
  position: any | null;
  trades_today: number;
  daily_pnl: number;
  last_analysis: string | null;
  capital_per_trade: number;
  max_trades_per_day: number;
  min_confidence: number;
  current_price?: number;
  market_status?: string;
}

const ACTIVITY_STORAGE_KEY = 'hermes_activity_log';
const MAX_STORED_ACTIVITIES = 100;

export function HermesAgentMonitor() {
  const [metrics, setMetrics] = useState<HermesMetrics | null>(null);

  // Load activity log from localStorage on mount
  const [activityLog, setActivityLog] = useState<AgentActivity[]>(() => {
    try {
      const stored = localStorage.getItem(ACTIVITY_STORAGE_KEY);
      return stored ? JSON.parse(stored) : [];
    } catch (e) {
      console.error('[Hermes] Failed to load activity log from localStorage:', e);
      return [];
    }
  });

  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [pulseActive, setPulseActive] = useState(false);
  const activityEndRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // Save activity log to localStorage whenever it changes
  useEffect(() => {
    try {
      localStorage.setItem(ACTIVITY_STORAGE_KEY, JSON.stringify(activityLog.slice(-MAX_STORED_ACTIVITIES)));
    } catch (e) {
      console.error('[Hermes] Failed to save activity log to localStorage:', e);
    }
  }, [activityLog]);

  useEffect(() => {
    fetchMetrics();
    connectWebSocket();

    const interval = setInterval(() => {
      fetchMetrics();
    }, 5000); // Refresh every 5 seconds

    return () => {
      clearInterval(interval);
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  useEffect(() => {
    // Auto-scroll to latest activity
    activityEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [activityLog]);

  const connectWebSocket = () => {
    // Connect to dedicated Hermes WebSocket endpoint
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const ws = new WebSocket(`${protocol}//${host}/ws/hermes`);

    ws.onopen = () => {
      console.log('[Hermes] WebSocket connected');
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      console.log('[Hermes] WebSocket message:', data.type, data);

      // Filter for Hermes-related updates
      if (data.type === 'hermes_activity') {
        console.log('[Hermes] 🎯 Activity received:', data.action, data.details);
        addActivity({
          timestamp: new Date().toISOString(),
          action: data.action,
          details: data.details,
          status: data.status,
          confidence: data.confidence,
          decision: data.decision,
        });

        if (data.status === 'analyzing') {
          setIsAnalyzing(true);
          setPulseActive(true);
          setTimeout(() => setIsAnalyzing(false), 3000);
        }
      }
    };

    ws.onerror = (error) => {
      console.error('[Hermes] WebSocket error:', error);
    };

    ws.onclose = () => {
      console.log('[Hermes] WebSocket disconnected, reconnecting in 3s...');
      setTimeout(connectWebSocket, 3000);
    };

    wsRef.current = ws;
  };

  const fetchMetrics = async () => {
    try {
      const response = await api.get('/api/hermes/status');
      setMetrics(response.data);
    } catch (err) {
      console.error('Failed to fetch Hermes metrics:', err);
    }
  };

  const addActivity = (activity: AgentActivity) => {
    setActivityLog((prev) => [...prev.slice(-49), activity]); // Keep last 50
  };

  const getStatusColor = (status: AgentActivity['status']) => {
    switch (status) {
      case 'analyzing': return '#00e5ff';
      case 'executing': return '#ff9100';
      case 'monitoring': return '#00e676';
      case 'success': return '#00e676';
      case 'error': return '#ff5252';
      default: return '#8aa5c0';
    }
  };

  const getStatusIcon = (status: AgentActivity['status']) => {
    switch (status) {
      case 'analyzing': return '🧠';
      case 'executing': return '⚡';
      case 'monitoring': return '👁️';
      case 'success': return '✅';
      case 'error': return '❌';
      default: return '⏸️';
    }
  };

  const timeSinceLastAnalysis = () => {
    if (!metrics?.last_analysis) return 'Never';
    const diff = Date.now() - new Date(metrics.last_analysis).getTime();
    const seconds = Math.floor(diff / 1000);
    if (seconds < 60) return `${seconds}s ago`;
    return `${Math.floor(seconds / 60)}m ago`;
  };

  if (!metrics) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="text-6xl mb-4">🤖</div>
          <div className="text-jarvis-primary font-mono text-xl animate-pulse">
            INITIALIZING HERMES AGENT...
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-[1600px] mx-auto px-4 py-6 space-y-6">
      {/* Header with Pulse Animation */}
      <div className="relative">
        <div className="flex items-center gap-4 mb-2">
          <div className="relative">
            <div className="text-5xl">🤖</div>
            {pulseActive && (
              <div className="absolute inset-0 animate-ping">
                <div
                  className="w-full h-full rounded-full"
                  style={{
                    background: 'radial-gradient(circle, rgba(0,229,255,0.6) 0%, transparent 70%)',
                  }}
                />
              </div>
            )}
          </div>
          <div>
            <h1 className="text-4xl font-black text-jarvis-primary font-mono tracking-wider">
              HERMES AGENT MONITOR
            </h1>
            <p className="text-sm text-jarvis-text-secondary font-mono mt-1">
              Real-time AI trading agent activity visualization
            </p>
          </div>
        </div>

        {/* Status Bar */}
        <div className="flex items-center gap-6 mt-4 flex-wrap">
          <div className="flex items-center gap-2">
            <div
              className="w-3 h-3 rounded-full animate-pulse"
              style={{ background: metrics.enabled ? '#00e676' : '#ff5252' }}
            />
            <span className="text-sm font-bold font-mono" style={{ color: metrics.enabled ? '#00e676' : '#ff5252' }}>
              {metrics.enabled ? 'AGENT ACTIVE' : 'AGENT DISABLED'}
            </span>
          </div>

          {isAnalyzing && (
            <div className="flex items-center gap-2 animate-pulse">
              <div className="w-2 h-2 rounded-full bg-[#00e5ff]" />
              <span className="text-xs font-mono text-[#00e5ff]">
                ANALYZING MARKET...
              </span>
            </div>
          )}

          <div className="text-xs font-mono text-jarvis-text-secondary">
            Last scan: {timeSinceLastAnalysis()}
          </div>

          <div className="text-xs font-mono text-jarvis-text-secondary">
            Market: <span className="text-jarvis-primary">{metrics.market_status || 'OPEN'}</span>
          </div>
        </div>
      </div>

      {/* Main Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column - Metrics */}
        <div className="space-y-6">
          {/* Key Metrics */}
          <Card title="⚡ AGENT STATUS" className="border-l-4 border-jarvis-primary">
            <div className="space-y-4">
              {/* Instrument */}
              <div
                className="p-3 rounded-lg"
                style={{ background: 'rgba(0,229,255,0.05)', border: '1px solid rgba(0,229,255,0.2)' }}
              >
                <div className="text-xs text-jarvis-text-secondary mb-1">TRACKING</div>
                <div className="text-2xl font-black text-jarvis-primary font-mono">
                  {metrics.instrument}
                </div>
                {metrics.current_price && (
                  <div className="text-sm text-green-400 font-mono mt-1">
                    ₹{metrics.current_price.toFixed(2)}
                  </div>
                )}
              </div>

              {/* Daily P&L */}
              <div
                className="p-3 rounded-lg"
                style={{
                  background: metrics.daily_pnl >= 0 ? 'rgba(0,230,118,0.05)' : 'rgba(255,82,82,0.05)',
                  border: `1px solid ${metrics.daily_pnl >= 0 ? 'rgba(0,230,118,0.2)' : 'rgba(255,82,82,0.2)'}`,
                }}
              >
                <div className="text-xs text-jarvis-text-secondary mb-1">TODAY'S P&L</div>
                <div
                  className="text-3xl font-black font-mono"
                  style={{ color: metrics.daily_pnl >= 0 ? '#00e676' : '#ff5252' }}
                >
                  {metrics.daily_pnl >= 0 ? '+' : ''}₹{metrics.daily_pnl.toFixed(2)}
                </div>
              </div>

              {/* Trades Progress */}
              <div>
                <div className="flex justify-between text-xs mb-2">
                  <span className="text-jarvis-text-secondary">TRADES TODAY</span>
                  <span className="font-mono text-jarvis-primary">
                    {metrics.trades_today} / {metrics.max_trades_per_day}
                  </span>
                </div>
                <div className="h-2 rounded-full bg-white/5 overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{
                      width: `${(metrics.trades_today / metrics.max_trades_per_day) * 100}%`,
                      background: 'linear-gradient(90deg, #00e5ff, #00e676)',
                    }}
                  />
                </div>
              </div>

              {/* Confidence Threshold */}
              <div>
                <div className="flex justify-between text-xs mb-2">
                  <span className="text-jarvis-text-secondary">MIN CONFIDENCE</span>
                  <span className="font-mono text-jarvis-primary">
                    {Math.round(metrics.min_confidence * 100)}%
                  </span>
                </div>
                <div className="h-2 rounded-full bg-white/5 overflow-hidden">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${metrics.min_confidence * 100}%`,
                      background: '#00e676',
                    }}
                  />
                </div>
              </div>

              {/* Capital Per Trade */}
              <div className="pt-3 border-t border-white/10">
                <div className="text-xs text-jarvis-text-secondary mb-1">CAPITAL/TRADE</div>
                <div className="text-xl font-bold font-mono text-jarvis-primary">
                  ₹{metrics.capital_per_trade.toLocaleString()}
                </div>
              </div>
            </div>
          </Card>

          {/* Current Position */}
          {metrics.position ? (
            <Card title="📍 ACTIVE POSITION" className="border-l-4 border-green-500">
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <div className="text-xs text-jarvis-text-secondary mb-1">ENTRY</div>
                    <div className="text-lg font-bold text-green-400 font-mono">
                      ₹{metrics.position.entry_price.toFixed(2)}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-jarvis-text-secondary mb-1">QTY</div>
                    <div className="text-lg font-bold font-mono">{metrics.position.qty}</div>
                  </div>
                  <div>
                    <div className="text-xs text-jarvis-text-secondary mb-1">STOP LOSS</div>
                    <div className="text-sm font-bold text-red-400 font-mono">
                      ₹{metrics.position.stop_loss.toFixed(2)}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-jarvis-text-secondary mb-1">TARGET</div>
                    <div className="text-sm font-bold text-green-300 font-mono">
                      ₹{metrics.position.target.toFixed(2)}
                    </div>
                  </div>
                </div>

                <div className="pt-3 border-t border-white/10">
                  <div className="text-xs text-jarvis-text-secondary mb-1">SETUP TYPE</div>
                  <div className="text-sm font-mono">{metrics.position.setup_type}</div>
                </div>

                <div className="pt-3 border-t border-white/10 text-xs text-jarvis-text-secondary">
                  Entry: {new Date(metrics.position.entry_time).toLocaleTimeString()}
                </div>
              </div>
            </Card>
          ) : (
            <Card title="📍 POSITION" className="border-l-4 border-white/20">
              <div className="text-center py-8 text-jarvis-text-secondary">
                <div className="text-4xl mb-3">🎯</div>
                <div className="text-sm font-mono">NO ACTIVE POSITION</div>
                <div className="text-xs mt-2 opacity-60">
                  Scanning for high-confidence setups...
                </div>
              </div>
            </Card>
          )}
        </div>

        {/* Right Column - Activity Monitor */}
        <div className="lg:col-span-2">
          <Card
            title="📊 AGENT ACTIVITY LOG"
            className="h-[800px] flex flex-col border-l-4 border-[#00e5ff]"
          >
            <div className="flex-1 overflow-y-auto space-y-2 pr-2">
              {activityLog.length === 0 ? (
                <div className="flex items-center justify-center h-full">
                  <div className="text-center text-jarvis-text-secondary">
                    <div className="text-5xl mb-4">🔍</div>
                    <div className="text-sm font-mono">Waiting for agent activity...</div>
                    <div className="text-xs mt-2 opacity-60">
                      Connect WebSocket to see real-time updates
                    </div>
                  </div>
                </div>
              ) : (
                activityLog.map((activity, idx) => (
                  <div
                    key={idx}
                    className="p-3 rounded-lg transition-all hover:scale-[1.01] animate-slideIn"
                    style={{
                      background: 'rgba(255,255,255,0.02)',
                      border: `1px solid ${getStatusColor(activity.status)}40`,
                      borderLeft: `4px solid ${getStatusColor(activity.status)}`,
                    }}
                  >
                    <div className="flex items-start gap-3">
                      <div className="text-2xl">{getStatusIcon(activity.status)}</div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-2 mb-1">
                          <div
                            className="text-sm font-bold font-mono"
                            style={{ color: getStatusColor(activity.status) }}
                          >
                            {activity.action}
                          </div>
                          <div className="text-xs text-jarvis-text-secondary font-mono">
                            {new Date(activity.timestamp).toLocaleTimeString()}
                          </div>
                        </div>
                        <div className="text-xs text-jarvis-text-secondary mb-2">
                          {activity.details}
                        </div>

                        {activity.confidence !== undefined && (
                          <div className="flex items-center gap-2">
                            <div className="text-xs text-jarvis-text-secondary">Confidence:</div>
                            <div className="flex-1 h-1.5 rounded-full bg-white/10">
                              <div
                                className="h-full rounded-full transition-all"
                                style={{
                                  width: `${activity.confidence * 100}%`,
                                  background:
                                    activity.confidence >= 0.7
                                      ? '#00e676'
                                      : activity.confidence >= 0.5
                                      ? '#ff9100'
                                      : '#ff5252',
                                }}
                              />
                            </div>
                            <div
                              className="text-xs font-bold font-mono"
                              style={{
                                color:
                                  activity.confidence >= 0.7
                                    ? '#00e676'
                                    : activity.confidence >= 0.5
                                    ? '#ff9100'
                                    : '#ff5252',
                              }}
                            >
                              {Math.round(activity.confidence * 100)}%
                            </div>
                          </div>
                        )}

                        {activity.decision && (
                          <div className="mt-2 p-2 rounded bg-black/20 text-xs font-mono">
                            <div className="text-jarvis-text-secondary">
                              Decision: <span className="text-jarvis-primary">{activity.decision.action}</span>
                            </div>
                            {activity.decision.reasoning && (
                              <div className="text-jarvis-text-secondary mt-1 opacity-80">
                                {activity.decision.reasoning}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ))
              )}
              <div ref={activityEndRef} />
            </div>
          </Card>
        </div>
      </div>

      <style>{`
        @keyframes slideIn {
          from {
            opacity: 0;
            transform: translateX(-20px);
          }
          to {
            opacity: 1;
            transform: translateX(0);
          }
        }
        .animate-slideIn {
          animation: slideIn 0.3s ease-out;
        }
      `}</style>
    </div>
  );
}
