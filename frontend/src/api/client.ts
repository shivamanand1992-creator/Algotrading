import axios from 'axios';
import type {
  StrategyStatus,
  Position,
  PortfolioSummary,
  MarketData,
  MarketRegime,
  Prediction,
  RiskLimits,
  SystemStatus,
  OHLCVCandle,
  TrainStatus,
  StockSignal,
  SwingPosition,
  NiftyBeesConfig,
  NiftyBeesStatus,
  GlobalCue,
  NewsItem,
  NiftyTechnicals,
} from '../types/api';

// In production (Railway) frontend is served by the same server, so use relative URLs.
// In local dev, proxy to localhost:8000.
const API_BASE = process.env.REACT_APP_API_URL || '';

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 30000,  // Increased from 10s to 30s for scoring cycles with rate limiting
  headers: {
    'Content-Type': 'application/json',
  },
});

// Auto-logout on any 401 response (expired or invalid token)
api.interceptors.response.use(
  res => res,
  err => {
    if (err.response?.status === 401) {
      localStorage.removeItem('algo_auth_token');
      delete api.defaults.headers.common['Authorization'];
      // Reload to show login screen
      window.location.reload();
    }
    return Promise.reject(err);
  }
);

/** Returns a WebSocket URL with the current JWT appended as ?token= */
export function wsUrl(path: string): string {
  const token = localStorage.getItem('algo_auth_token') ?? '';
  const base = API_BASE
    ? API_BASE.replace(/^http/, 'ws')
    : `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`;
  return `${base}${path}?token=${token}`;
}

// System endpoints
export const systemApi = {
  getStatus:     () => api.get<SystemStatus>('/api/system/status'),
  setMode:       (mode: 'paper' | 'live' | 'backtest') => api.post('/api/system/mode', { mode }),
  squareOffAll:  () => api.post('/api/system/squareoff'),
  getBalance:    () => api.get<{ available_cash: number; net: number; used_margin: number; error?: string; source?: string }>('/api/system/balance'),
  syncAll:       () => api.post<{ success: boolean; message: string; swing: any; niftybees: any; errors: string[] }>('/api/system/sync', {}, { timeout: 30000 }),
  testTelegram:  () => api.post<{ sent: boolean; error: string | null }>('/api/system/telegram/test'),
};

// Strategy endpoints
export const strategiesApi = {
  getAll: () => api.get<StrategyStatus[]>('/api/strategies'),
  start: (name: string, mode: 'paper' | 'live') =>
    api.post(`/api/strategies/${name}/start`, { mode }),
  stop: (name: string) => api.post(`/api/strategies/${name}/stop`),
  getConfig: (name: string) => api.get(`/api/strategies/${name}/config`),
  updateConfig: (name: string, config: any) =>
    api.put(`/api/strategies/${name}/config`, { config }),
};

// Position endpoints
export const positionsApi = {
  getAll: () => api.get<Position[]>('/api/positions'),
  getOne: (orderId: string) => api.get<Position>(`/api/positions/${orderId}`),
  close: (orderId: string, reason?: string) =>
    api.post(`/api/positions/${orderId}/close`, { reason }),
  getPortfolio: () => api.get<PortfolioSummary>('/api/portfolio/summary'),
};

// Market data endpoints
export const marketApi = {
  getCurrent: () => api.get<MarketData>('/api/market/current'),
  getOptionsChain: () => api.get('/api/market/options_chain'),
  getRegime: () => api.get<MarketRegime>('/api/market/regime', { timeout: 35000 }),
  getPredictions: () => api.get<Prediction>('/api/market/predictions', { timeout: 35000 }),
  getOHLCV: (interval = 'FIFTEEN_MINUTE', days = 5) =>
    api.get<OHLCVCandle[]>(`/api/market/ohlcv?interval=${interval}&days=${days}`),
  getVIX: (interval = 'FIFTEEN_MINUTE', days = 5) =>
    api.get<{ timestamp: string; open: number; high: number; low: number; close: number }[]>(
      `/api/market/vix?interval=${interval}&days=${days}`
    ),
  getGlobalCues:  () => api.get<GlobalCue[]>('/api/market/global-cues', { timeout: 20000 }),
  getNews:        () => api.get<NewsItem[]>('/api/market/news', { timeout: 20000 }),
  getTechnicals:  () => api.get<NiftyTechnicals>('/api/market/technicals', { timeout: 30000 }),
};

// Risk endpoints
export const riskApi = {
  getLimits: () => api.get<RiskLimits>('/api/risk/limits'),
  updateLimits: (body: { daily_loss_limit?: number; max_positions?: number; per_trade_risk_percent?: number }) =>
    api.put('/api/risk/limits', body),
  getMetrics: () => api.get('/api/risk/metrics'),
  getAlerts: () => api.get('/api/risk/alerts'),
};

// Trades endpoints
export const tradesApi = {
  getHistory: (params?: any) => api.get('/api/trades', { params }),
  getStatistics: () => api.get('/api/trades/statistics'),
  export: (format: 'csv' | 'json' = 'csv') =>
    api.get('/api/trades/export', { params: { format } }),
};

// Training endpoints
export const trainingApi = {
  getStatus: () => api.get<TrainStatus>('/api/system/train/status'),
  start: (days = 60) => api.post(`/api/system/train?days=${days}`),
};

// Stock screener / swing trade endpoints
export const stocksApi = {
  getWatchlist: (universe = 'nifty50') => api.get<{ symbol: string; name: string; sector: string }[]>(`/api/stocks/watchlist?universe=${universe}`),
  getSignals:   () => api.get<StockSignal[]>('/api/stocks/signals'),
  scan: (params: { universe?: string; regime_filter?: boolean; rs_filter?: boolean } = {}) => {
    const q = new URLSearchParams({ universe: params.universe || 'nifty50' });
    if (params.regime_filter !== undefined) q.set('regime_filter', String(params.regime_filter));
    if (params.rs_filter     !== undefined) q.set('rs_filter',     String(params.rs_filter));
    return api.get<{ signals: StockSignal[]; regime_warning: string; nifty_bullish: boolean; nifty_20d_return: number; universe_size: number }>(
      `/api/stocks/scan?${q.toString()}`, { timeout: 90000 }
    );
  },
  getPositions: () => api.get<SwingPosition[]>('/api/stocks/positions'),
  execute:      (symbol: string, mode: 'paper' | 'live', capital?: number) =>
    api.post(`/api/stocks/signals/${symbol}/execute`, { mode, capital }),
  autoExecute:  (mode: 'paper' | 'live', max_signals = 3, capital?: number) =>
    api.post('/api/stocks/auto-execute', { mode, max_signals, capital }),
  closePosition:    (symbol: string) => api.delete(`/api/stocks/positions/${symbol}`),
  closeAllPositions: () => api.delete(`/api/stocks/positions`),
  getAutopilot: () => api.get<{
    enabled: boolean; mode: string; capital_per_trade: number; max_trades: number;
    last_run: string | null; last_result: Record<string, any>;
  }>('/api/stocks/autopilot'),
  setAutopilot: (cfg: { enabled: boolean; mode: string; capital_per_trade: number; max_trades: number }) =>
    api.post('/api/stocks/autopilot', cfg),
  runAutopilotNow: () => api.post('/api/stocks/autopilot/run-now', {}, { timeout: 120000 }),
  syncFromBroker: () => api.post<{
    imported: string[]; updated: string[]; orphaned: string[];
    total_broker_holdings: number; message: string;
  }>('/api/stocks/sync-from-broker', {}),
};

// JARVIS Voice / Briefing endpoints
export const jarvisApi = {
  getTopics: () => api.get<{ id: string; label: string; icon: string; desc: string }[]>('/api/jarvis/topics'),
  getConfig: () => api.get<{ claude_configured: boolean; elevenlabs_configured: boolean; voice_id: string }>('/api/jarvis/config'),
  speak:     (topic: string) => api.post<{ script: string; audio: string | null }>('/api/jarvis/speak', { topic }, { timeout: 45000 }),
};

// NiftyBees ETF autopilot endpoints
export const niftyBeesApi = {
  getStatus:    () => api.get<NiftyBeesStatus>('/api/niftybees/status'),
  updateConfig: (cfg: Partial<NiftyBeesConfig>) => api.post('/api/niftybees/config', cfg),
  triggerCheck: () => api.post<{ action: string; details: string }>('/api/niftybees/check'),
  closePosition: () => api.delete('/api/niftybees/position'),
};
