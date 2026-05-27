from datetime import datetime
from typing import Optional, List, Dict
from pydantic import BaseModel


class StrategyStatus(BaseModel):
    name: str
    display_name: str
    status: str  # "running" | "stopped"
    mode: Optional[str] = None  # "paper" | "live"
    uptime_seconds: Optional[int] = None
    signals_generated: int = 0
    active_positions: int = 0
    regime_suitability: Optional[str] = None


class TradeSignalResponse(BaseModel):
    action: str
    symbol: str
    strike: int
    option_type: str
    qty: int
    price: float
    sl_price: float
    target_price: float
    confidence: float
    strategy_name: str
    timestamp: datetime


class PositionResponse(BaseModel):
    order_id: str
    symbol: str
    strike: int
    entry_price: float
    current_price: float
    qty: int
    direction: str
    entry_time: datetime
    exit_time: Optional[datetime] = None
    strategy: str
    regime: str
    unrealized_pnl: float
    realized_pnl: float
    sl_price: float
    target_price: float
    pnl_percentage: float


class PortfolioSummary(BaseModel):
    total_capital: float
    used_capital: float
    available_capital: float
    total_pnl: float
    total_pnl_percentage: float
    open_positions_count: int
    daily_pnl: float
    daily_pnl_percentage: float


class TradeHistoryResponse(BaseModel):
    order_id: str
    symbol: str
    strike: int
    option_type: str
    entry_price: float
    exit_price: float
    qty: int
    realized_pnl: float
    pnl_percentage: float
    entry_time: datetime
    exit_time: datetime
    exit_reason: str
    strategy: str
    regime: str


class TradeStatistics(BaseModel):
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_profit: float
    avg_loss: float
    total_pnl: float
    sharpe_ratio: Optional[float] = None
    max_drawdown: float
    profit_factor: float


class MarketDataResponse(BaseModel):
    symbol: str
    ltp: float
    change: float
    change_percentage: float
    iv_percentile: float
    pcr: float
    timestamp: datetime


class OptionsChainItem(BaseModel):
    strike: int
    call_ltp: float
    call_iv: float
    call_oi: int
    call_delta: float
    call_gamma: float
    call_theta: float
    call_vega: float
    put_ltp: float
    put_iv: float
    put_oi: int
    put_delta: float
    put_gamma: float
    put_theta: float
    put_vega: float


class MarketRegimeResponse(BaseModel):
    current_regime: str
    confidence: float
    regime_probabilities: Dict[str, float]
    timestamp: datetime


class PredictionResponse(BaseModel):
    direction: int  # +1, 0, -1
    direction_label: str  # "UP", "FLAT", "DOWN"
    confidence: float
    direction_probabilities: Dict[str, float]
    timestamp: datetime


class RiskLimitsResponse(BaseModel):
    daily_loss_limit: float
    daily_loss_used: float
    daily_loss_percentage: float
    per_trade_risk_limit: float
    max_positions: int
    current_positions: int


class RiskMetricsResponse(BaseModel):
    var_95: float
    var_99: float
    max_drawdown: float
    position_concentration: float
    leverage: float


class RiskAlert(BaseModel):
    severity: str  # "low" | "medium" | "high"
    message: str
    timestamp: datetime


class SystemStatusResponse(BaseModel):
    status: str  # "healthy" | "degraded" | "down"
    broker_connected: bool
    websocket_connected: bool
    database_connected: bool
    uptime_seconds: int
    current_mode: str  # "paper" | "live" | "backtest"


class LogEntry(BaseModel):
    timestamp: datetime
    level: str
    message: str
    source: Optional[str] = None


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    timestamp: datetime


# ---------------------------------------------------------------------------
# Stock Screener / Swing Trade models
# ---------------------------------------------------------------------------

class StockSignalResponse(BaseModel):
    symbol: str
    name: str
    sector: str
    yf_ticker: str
    action: str           # "BUY" | "HOLD"
    close: float
    entry_price: float
    stop_loss: float
    target1: float
    target2: float
    sl_pct: float
    risk_reward: float
    confidence: float
    regime: str
    reasons: List[str]
    rsi: float
    adx: float
    atr: float
    volume_ratio: float
    macd_hist: float
    ema9: float
    ema21: float
    ema50: float
    rs_vs_nifty: float = 0.0
    scan_time: str


class SwingPositionResponse(BaseModel):
    order_id: str
    symbol: str
    name: str
    sector: str
    yf_ticker: str
    entry_price: float
    current_price: float
    qty: int
    stop_loss: float
    target1: float
    target2: float
    entry_date: str
    unrealized_pnl: float
    pnl_pct: float
    status: str           # "open" | "closed_sl" | "closed_target" | "closed_trail"
    mode: str             # "paper" | "live"
    confidence: float
    regime: str
    trailing_active: bool = False
