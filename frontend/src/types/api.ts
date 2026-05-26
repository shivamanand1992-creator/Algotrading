export interface StrategyStatus {
  name: string;
  display_name: string;
  status: 'running' | 'stopped';
  mode: 'paper' | 'live' | null;
  uptime_seconds: number | null;
  signals_generated: number;
  active_positions: number;
  regime_suitability: string | null;
}

export interface Position {
  order_id: string;
  symbol: string;
  strike: number;
  entry_price: number;
  current_price: number;
  qty: number;
  direction: 'BUY' | 'SELL';
  entry_time: string;
  exit_time: string | null;
  strategy: string;
  regime: string;
  unrealized_pnl: number;
  realized_pnl: number;
  sl_price: number;
  target_price: number;
  pnl_percentage: number;
}

export interface PortfolioSummary {
  total_capital: number;
  used_capital: number;
  available_capital: number;
  total_pnl: number;
  total_pnl_percentage: number;
  open_positions_count: number;
  daily_pnl: number;
  daily_pnl_percentage: number;
}

export interface MarketData {
  symbol: string;
  ltp: number;
  change: number;
  change_percentage: number;
  open?: number;
  high?: number;
  low?: number;
  volume?: number;
  iv_percentile: number;
  pcr: number;
  timestamp: string;
}

export interface MarketRegime {
  current_regime: string;
  confidence: number;
  regime_probabilities: Record<string, number>;
  recommended_strategies?: string[];
  timestamp?: string;
}

export interface Prediction {
  direction: string;
  direction_label: string;
  confidence: number;
  predicted_move?: number;
  time_horizon?: string;
  model_agreement?: number;
  direction_probabilities?: Record<string, number>;
  timestamp?: string;
}

export interface RiskLimits {
  daily_loss_limit: number;
  daily_loss_used: number;
  daily_loss_percentage: number;
  per_trade_risk_limit: number;
  max_positions: number;
  current_positions: number;
}


export interface SystemStatus {
  status: 'healthy' | 'degraded' | 'down';
  broker_connected: boolean;
  websocket_connected: boolean;
  database_connected: boolean;
  uptime_seconds: number;
  current_mode: string;
}

export interface WebSocketMessage {
  type: 'position_update' | 'market_tick' | 'new_signal' | 'risk_alert' | 'connected' | 'ack';
  data?: any;
  message?: string;
  timestamp?: string;
}

export interface OHLCVCandle {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface TrainStatus {
  status: 'idle' | 'running' | 'complete' | 'failed';
  progress: string;
  error: string;
}
