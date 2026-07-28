import React, { useState, useCallback, useEffect } from 'react';
import { api } from '../../api/client';

interface TradeSetup {
  id: string;
  strategy: string;
  symbol: string;
  entry_price: number;
  entry_time: string;
  long_leg: any;
  short_leg: any;
  max_profit: number;
  max_loss: number;
  breakeven: number;
  risk_reward_ratio: number;
  probability_win: number;
  capital_required: number;
  confidence_score: number;
  rationale: string[];
}

interface OpportunitiesResponse {
  market_analysis: {
    nifty_price: number;
    confidence: string;
    bias: string;
    signals: string[];
  };
  setups: TradeSetup[];
  weekly_target: {
    target_return: string;
    expected_pnl: string;
    setups_generated: number;
    average_confidence: string;
  };
}

interface TraderStatus {
  capital: number;
  active_setups: number;
  completed_trades: number;
  weekly_pnl: number;
  weekly_return_pct: number;
  ytd_return_pct?: number;
  win_rate?: number;
  profit_factor?: number;
  active_trades?: any[];
}

export function WeeklyIncomeTrader() {
  const [opportunities, setOpportunities] = useState<OpportunitiesResponse | null>(null);
  const [status, setStatus] = useState<TraderStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [selectedSetup, setSelectedSetup] = useState<TradeSetup | null>(null);

  const fetchOpportunities = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await api.get<OpportunitiesResponse>('/api/weekly-income/opportunities');
      setOpportunities(resp.data);
    } catch (err: any) {
      setError(err.response?.data?.detail ?? err.message ?? 'Failed to fetch opportunities');
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchStatus = useCallback(async () => {
    try {
      const resp = await api.get<TraderStatus>('/api/weekly-income/status');
      setStatus(resp.data);
    } catch (err) {
      // Silent fail for status
    }
  }, []);

  const executeSetup = async (setupId: string) => {
    try {
      await api.post(`/api/weekly-income/execute?setup_id=${setupId}`);
      alert('Trade executed successfully (paper trading)');
      await fetchStatus();
    } catch (err: any) {
      alert(`Execution failed: ${err.message}`);
    }
  };

  useEffect(() => {
    fetchOpportunities();
    fetchStatus();

    if (autoRefresh) {
      const interval = setInterval(() => {
        fetchOpportunities();
        fetchStatus();
      }, 60000); // Refresh every minute
      return () => clearInterval(interval);
    }
  }, [autoRefresh]);

  return (
    <div className="p-6 space-y-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-3xl font-bold text-white">💰 Weekly 5% Income Trader</h1>
          <p className="text-sm text-jarvis-text-secondary mt-1">
            Intelligent automated system targeting 5% weekly returns (defined-risk options buying only)
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setAutoRefresh(!autoRefresh)}
            className={`px-4 py-2 text-xs rounded-lg border transition-all ${
              autoRefresh
                ? 'bg-green-500/20 border-green-500 text-green-400'
                : 'bg-white/5 border-white/10 text-jarvis-text-secondary'
            }`}
          >
            {autoRefresh ? '✓ Auto-refresh ON' : 'Auto-refresh OFF'}
          </button>
          <button
            onClick={fetchOpportunities}
            disabled={loading}
            className="px-6 py-2.5 rounded-lg font-semibold text-sm bg-jarvis-primary/20 border border-jarvis-primary text-jarvis-primary hover:bg-jarvis-primary/30 transition-all disabled:opacity-50 flex items-center gap-2"
          >
            {loading ? (
              <>
                <span className="animate-spin">◌</span>
                Scanning…
              </>
            ) : (
              <>
                <span>🔍</span>
                Scan for Opportunities
              </>
            )}
          </button>
        </div>
      </div>

      {/* Performance Summary */}
      {status && (
        <div className="glass-panel rounded-xl p-6 border border-jarvis-primary/30">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {[
              { label: 'Weekly P&L', value: `₹${status.weekly_pnl.toLocaleString()}`, color: status.weekly_pnl >= 0 ? 'text-green-400' : 'text-red-400' },
              { label: 'Weekly Return', value: `${status.weekly_return_pct.toFixed(2)}%`, color: 'text-cyan-400' },
              { label: 'Active Trades', value: status.active_setups, color: 'text-yellow-400' },
              { label: 'Win Rate', value: status.win_rate ? `${status.win_rate.toFixed(1)}%` : 'N/A', color: 'text-blue-400' },
            ].map((item) => (
              <div key={item.label} className="bg-jarvis-primary/5 rounded-lg p-4 text-center">
                <div className="text-xs text-jarvis-text-secondary uppercase tracking-wider mb-1">{item.label}</div>
                <div className={`text-lg font-bold ${item.color}`}>{item.value}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="glass-panel rounded-xl p-4 border border-red-500/40 text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Opportunities */}
      {opportunities && (
        <>
          {/* Market Analysis */}
          <div className="glass-panel rounded-xl p-6 border border-jarvis-primary/30">
            <h2 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
              <span>📊</span> Market Analysis
            </h2>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <div className="text-xs text-jarvis-text-secondary uppercase tracking-wider mb-1">NIFTY Price</div>
                <div className="text-2xl font-bold text-white">₹{opportunities.market_analysis.nifty_price.toLocaleString('en-IN')}</div>
              </div>
              <div>
                <div className="text-xs text-jarvis-text-secondary uppercase tracking-wider mb-1">Cycle Confidence</div>
                <div className={`text-xl font-bold ${
                  opportunities.market_analysis.confidence === 'HIGH' ? 'text-green-400' : 'text-yellow-400'
                }`}>
                  {opportunities.market_analysis.confidence}
                </div>
              </div>
              <div className="col-span-2">
                <div className="text-xs text-jarvis-text-secondary uppercase tracking-wider mb-2">Market Signals</div>
                <div className="space-y-1">
                  {opportunities.market_analysis.signals.map((signal, i) => (
                    <div key={i} className="text-xs text-jarvis-text-secondary flex items-start gap-2">
                      <span className="text-cyan-400 mt-0.5">›</span>
                      <span>{signal}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Trade Setups */}
          <div>
            <h2 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
              <span>🎯</span> High-Probability Setups ({opportunities.setups.length})
            </h2>
            <div className="space-y-4">
              {opportunities.setups.length === 0 ? (
                <div className="glass-panel rounded-xl p-8 text-center border border-jarvis-primary/20">
                  <div className="text-sm text-jarvis-text-secondary">
                    No high-confidence setups available right now. Check back soon.
                  </div>
                </div>
              ) : (
                opportunities.setups.map((setup, idx) => (
                  <div
                    key={setup.id}
                    className="glass-panel rounded-xl border border-cyan-500/30 overflow-hidden cursor-pointer hover:border-cyan-500/60 transition-all"
                    onClick={() => setSelectedSetup(selectedSetup?.id === setup.id ? null : setup)}
                  >
                    {/* Header */}
                    <div className="p-4 bg-gradient-to-r from-cyan-500/10 to-transparent">
                      <div className="flex items-start justify-between gap-4 flex-wrap">
                        <div>
                          <div className="flex items-center gap-2 mb-2">
                            <span className="text-xs font-bold bg-cyan-500/20 text-cyan-300 px-2 py-1 rounded">
                              {setup.strategy.replace('_', ' ').toUpperCase()}
                            </span>
                            <span className="text-xs font-bold bg-green-500/20 text-green-300 px-2 py-1 rounded">
                              {setup.probability_win.toFixed(0)}% WIN RATE
                            </span>
                          </div>
                          <div className="text-sm text-jarvis-text-secondary">
                            {setup.symbol} @ ₹{setup.entry_price.toLocaleString('en-IN')}
                          </div>
                        </div>

                        <div className="text-right">
                          <div className="text-xs text-jarvis-text-secondary mb-1">Confidence</div>
                          <div className="text-2xl font-bold text-cyan-400">{setup.confidence_score.toFixed(0)}%</div>
                        </div>
                      </div>
                    </div>

                    {/* Quick Stats */}
                    <div className="px-4 py-3 bg-white/5 grid grid-cols-4 gap-2">
                      {[
                        { label: 'Max Profit', value: `₹${setup.max_profit.toLocaleString('en-IN')}`, color: 'text-green-400' },
                        { label: 'Max Loss', value: `₹${setup.max_loss.toLocaleString('en-IN')}`, color: 'text-red-400' },
                        { label: 'R:R Ratio', value: `${setup.risk_reward_ratio.toFixed(2)}:1`, color: 'text-blue-400' },
                        { label: 'Capital', value: `₹${setup.capital_required.toLocaleString('en-IN')}`, color: 'text-yellow-400' },
                      ].map((stat) => (
                        <div key={stat.label} className="text-center">
                          <div className="text-[10px] text-jarvis-text-secondary uppercase mb-0.5">{stat.label}</div>
                          <div className={`text-xs font-bold ${stat.color}`}>{stat.value}</div>
                        </div>
                      ))}
                    </div>

                    {/* Expanded Detail */}
                    {selectedSetup?.id === setup.id && (
                      <div className="px-4 py-4 border-t border-white/10 space-y-4">
                        {/* Options Legs */}
                        <div>
                          <div className="text-xs text-jarvis-text-secondary uppercase tracking-wider mb-2">Options Legs</div>
                          <div className="space-y-2">
                            <div className="bg-green-500/10 rounded-lg p-3 border border-green-500/30">
                              <div className="text-sm font-bold text-green-400">BUY {setup.long_leg.option_type}</div>
                              <div className="text-xs text-jarvis-text-secondary mt-1">
                                Strike: ₹{setup.long_leg.strike} | Premium: ₹{setup.long_leg.premium.toFixed(0)} | Delta: {setup.long_leg.delta.toFixed(2)}
                              </div>
                            </div>
                            {setup.short_leg && (
                              <div className="bg-red-500/10 rounded-lg p-3 border border-red-500/30">
                                <div className="text-sm font-bold text-red-400">SELL {setup.short_leg.option_type}</div>
                                <div className="text-xs text-jarvis-text-secondary mt-1">
                                  Strike: ₹{setup.short_leg.strike} | Premium: ₹{setup.short_leg.premium.toFixed(0)} | Delta: {setup.short_leg.delta.toFixed(2)}
                                </div>
                              </div>
                            )}
                          </div>
                        </div>

                        {/* Key Levels */}
                        <div>
                          <div className="text-xs text-jarvis-text-secondary uppercase tracking-wider mb-2">Key Levels</div>
                          <div className="grid grid-cols-3 gap-2">
                            {[
                              { label: 'Entry', value: setup.entry_price },
                              { label: 'Breakeven', value: setup.breakeven },
                            ].map((level) => (
                              <div key={level.label} className="bg-white/5 rounded-lg p-2 text-center">
                                <div className="text-[10px] text-jarvis-text-secondary">{level.label}</div>
                                <div className="text-xs font-bold text-white">₹{level.value.toLocaleString('en-IN')}</div>
                              </div>
                            ))}
                          </div>
                        </div>

                        {/* Rationale */}
                        <div>
                          <div className="text-xs text-jarvis-text-secondary uppercase tracking-wider mb-2">Why This Setup</div>
                          <ul className="space-y-1">
                            {setup.rationale.map((reason, i) => (
                              <li key={i} className="text-xs text-jarvis-text-secondary flex items-start gap-2">
                                <span className="text-cyan-400 mt-0.5 shrink-0">✓</span>
                                <span>{reason}</span>
                              </li>
                            ))}
                          </ul>
                        </div>

                        {/* Execute Button */}
                        <button
                          onClick={() => executeSetup(setup.id)}
                          className="w-full mt-4 px-4 py-2.5 rounded-lg font-semibold text-sm bg-green-500/20 border border-green-500 text-green-400 hover:bg-green-500/30 transition-all"
                        >
                          Execute Setup (Paper Trading)
                        </button>
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Weekly Target */}
          <div className="glass-panel rounded-xl p-6 border border-jarvis-primary/30">
            <h3 className="text-sm font-bold text-white mb-4 uppercase tracking-wider">Weekly Target</h3>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              {[
                { label: 'Target Return', value: opportunities.weekly_target.target_return },
                { label: 'Expected P&L', value: opportunities.weekly_target.expected_pnl },
                { label: 'Setups Generated', value: opportunities.weekly_target.setups_generated },
                { label: 'Avg Confidence', value: opportunities.weekly_target.average_confidence },
              ].map((item) => (
                <div key={item.label} className="bg-white/5 rounded-lg p-3 text-center">
                  <div className="text-[10px] text-jarvis-text-secondary uppercase mb-1">{item.label}</div>
                  <div className="text-sm font-bold text-white">{item.value}</div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      {/* Empty State */}
      {!opportunities && !loading && (
        <div className="glass-panel rounded-xl p-10 text-center border border-jarvis-primary/20">
          <div className="text-4xl mb-3">🎯</div>
          <div className="text-white font-semibold mb-2">Ready to find opportunities?</div>
          <div className="text-sm text-jarvis-text-secondary max-w-sm mx-auto">
            Click "Scan for Opportunities" to analyze the market and generate high-probability trade setups for the week.
          </div>
        </div>
      )}
    </div>
  );
}
