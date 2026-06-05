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

export interface StockSignal {
  symbol: string;
  name: string;
  sector: string;
  yf_ticker: string;
  action: 'BUY' | 'HOLD';
  close: number;
  entry_price: number;
  stop_loss: number;
  target1: number;
  target2: number;
  sl_pct: number;
  risk_reward: number;
  confidence: number;
  regime: string;
  reasons: string[];
  rsi: number;
  adx: number;
  atr: number;
  volume_ratio: number;
  macd_hist: number;
  ema9: number;
  ema21: number;
  ema50: number;
  rs_vs_nifty: number;
  scan_time: string;
}

// NiftyBees ETF autopilot types
export interface NiftyBeesConfig {
  enabled:           boolean;
  mode:              'paper' | 'live';
  capital_amount:    number;
  dip_threshold_pct: number;
  target_gain_pct:   number;
}

export interface NiftyBeesBuyEntry {
  date:          string;
  qty:           number;
  price:         number;
  nifty_at_buy:  number;
  nifty_dip_pct: number;
  order_id:      string;
  invested:      number;
}

export interface NiftyBeesPosition {
  active:          boolean;
  buys:            NiftyBeesBuyEntry[];
  total_qty:       number;
  total_invested:  number;
  avg_entry_price: number;
  mode:            'paper' | 'live';
  last_buy_date:   string;
  current_price:   number;
  unrealized_pnl:  number;
  pnl_pct:         number;
  last_checked:    string;
  // on closed trades
  exit_price?:     number;
  exit_date?:      string;
  gain_pct?:       number;
  realized_pnl?:   number;
  close_reason?:   string;
}

export interface NiftyBeesStatus {
  config:   NiftyBeesConfig;
  position: NiftyBeesPosition | null;
  history:  NiftyBeesPosition[];
}

export interface GlobalCue {
  symbol: string;
  name: string;
  type: 'index' | 'commodity' | 'forex';
  ltp: number | null;
  change: number | null;
  change_pct: number | null;
}

export interface NewsItem {
  title: string;
  link: string;
  published: string;
  source?: string;
  category?: 'indian' | 'global';
}

export interface NiftyTechCandle {
  date: string;
  close: number;
  ema9: number | null;
  ema21: number | null;
  bb_up: number | null;
  bb_lo: number | null;
}

export interface NiftyTechnicals {
  last_close:    number;
  ema9:          number;
  ema21:         number;
  sma50:         number;
  rsi14:         number;
  macd_hist:     number;
  atr14:         number;
  bb_upper:      number;
  bb_lower:      number;
  bb_position:   number;
  vol_ratio:     number;
  momentum_5d:   number;
  momentum_10d:  number;
  momentum_20d:  number;
  trend:         string;
  signal:        string;
  score:         number;
  nb_action:     string;
  nb_reason:     string;
  candles:       NiftyTechCandle[];
}

export interface SwingPosition {
  order_id: string;
  symbol: string;
  name: string;
  sector: string;
  yf_ticker: string;
  entry_price: number;
  current_price: number;
  qty: number;
  stop_loss: number;
  target1: number;
  target2: number;
  entry_date: string;
  unrealized_pnl: number;
  pnl_pct: number;
  status: 'open' | 'closed_sl' | 'closed_target' | 'closed_trail';
  mode: 'paper' | 'live';
  confidence: number;
  regime: string;
  trailing_active?: boolean;
}
