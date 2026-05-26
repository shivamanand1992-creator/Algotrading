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
} from '../types/api';

// In production (Railway) frontend is served by the same server, so use relative URLs.
// In local dev, proxy to localhost:8000.
const API_BASE = process.env.REACT_APP_API_URL || '';

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// System endpoints
export const systemApi = {
  getStatus: () => api.get<SystemStatus>('/api/system/status'),
  setMode: (mode: 'paper' | 'live' | 'backtest') =>
    api.post('/api/system/mode', { mode }),
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
  getRegime: () => api.get<MarketRegime>('/api/market/regime'),
  getPredictions: () => api.get<Prediction>('/api/market/predictions'),
  getOHLCV: (interval = 'FIFTEEN_MINUTE', days = 5) =>
    api.get<OHLCVCandle[]>(`/api/market/ohlcv?interval=${interval}&days=${days}`),
};

// Risk endpoints
export const riskApi = {
  getLimits: () => api.get<RiskLimits>('/api/risk/limits'),
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
