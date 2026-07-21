"""
SQLAlchemy models for ML intraday trading
Stores candles, features, and ML predictions
"""

from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, BigInteger, Index
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()


class Candle5Min(Base):
    """5-minute OHLCV candles"""
    __tablename__ = 'candles_5min'

    symbol = Column(String(20), primary_key=True)
    timestamp = Column(DateTime, primary_key=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(BigInteger, nullable=False)

    # Indexes for fast queries
    __table_args__ = (
        Index('idx_symbol_timestamp', 'symbol', 'timestamp'),
        Index('idx_timestamp', 'timestamp'),
    )


class StockFeatures(Base):
    """Calculated features for ML model"""
    __tablename__ = 'stock_features'

    symbol = Column(String(20), primary_key=True)
    timestamp = Column(DateTime, primary_key=True)

    # Trend features
    ema5 = Column(Float)
    ema9 = Column(Float)
    ema20 = Column(Float)
    ema50 = Column(Float)
    ema200 = Column(Float)
    sma20 = Column(Float)
    sma50 = Column(Float)

    # Momentum features
    rsi = Column(Float)
    roc = Column(Float)  # Rate of change
    momentum = Column(Float)
    adx = Column(Float)
    atr = Column(Float)
    macd = Column(Float)
    macd_signal = Column(Float)
    macd_hist = Column(Float)
    stoch_k = Column(Float)
    stoch_d = Column(Float)

    # Volume features
    volume_ma = Column(Float)
    rel_volume = Column(Float)  # current_volume / volume_ma
    volume_spike = Column(Boolean)  # volume > 1.5x average
    obv = Column(Float)  # On-balance volume

    # Market features
    nifty_trend = Column(Integer)  # -1, 0, 1
    banknifty_trend = Column(Integer)
    india_vix = Column(Float)
    sector_strength = Column(Float)  # Sector relative to Nifty

    # Price action features
    prev_day_high = Column(Float)
    prev_day_low = Column(Float)
    prev_day_close = Column(Float)
    opening_range_high = Column(Float)  # First 15min high
    opening_range_low = Column(Float)   # First 15min low
    day_high = Column(Float)
    day_low = Column(Float)

    # Statistical features
    z_score = Column(Float)
    volatility = Column(Float)
    dist_from_vwap = Column(Float)
    dist_from_ema20 = Column(Float)
    upper_bb = Column(Float)  # Bollinger bands
    lower_bb = Column(Float)

    # Pattern features
    is_inside_bar = Column(Boolean)
    is_nr7 = Column(Boolean)  # Narrow range 7
    is_engulfing = Column(Boolean)
    gap_pct = Column(Float)  # Gap from previous close
    is_breakout = Column(Boolean)  # Above prev_day_high
    is_breakdown = Column(Boolean)  # Below prev_day_low

    # Time features
    hour = Column(Integer)
    minute = Column(Integer)
    time_since_open = Column(Integer)  # minutes since 9:15

    # Target label (for training)
    is_profitable_30min = Column(Boolean)  # Did trade make target in 30min?
    profit_30min = Column(Float)  # Actual % profit/loss
    exit_reason = Column(String(10))  # 'target', 'sl', 'time'

    # Indexes
    __table_args__ = (
        Index('idx_features_symbol_timestamp', 'symbol', 'timestamp'),
        Index('idx_features_timestamp', 'timestamp'),
        Index('idx_features_profitable', 'is_profitable_30min'),
    )


class MLPrediction(Base):
    """Real-time ML model predictions"""
    __tablename__ = 'ml_predictions'

    symbol = Column(String(20), primary_key=True)
    timestamp = Column(DateTime, primary_key=True)

    # ML scores
    trend_score = Column(Integer)  # 0-100
    momentum_score = Column(Integer)
    volume_score = Column(Integer)
    pattern_score = Column(Integer)
    market_score = Column(Integer)
    final_score = Column(Integer)  # Weighted average

    # Prediction
    probability = Column(Float)  # P(success) from model
    predicted_profit = Column(Float)  # Expected % profit
    confidence = Column(String(10))  # 'low', 'medium', 'high'

    # Signal details (if score >= 90 and probability >= 0.70)
    is_signal = Column(Boolean)
    entry_price = Column(Float)
    stop_loss = Column(Float)
    target = Column(Float)
    reward_risk = Column(Float)
    expected_hold_time = Column(Integer)  # minutes

    # Model metadata
    model_version = Column(String(20))
    created_at = Column(DateTime, default=datetime.utcnow)

    # Indexes
    __table_args__ = (
        Index('idx_predictions_symbol_timestamp', 'symbol', 'timestamp'),
        Index('idx_predictions_signal', 'is_signal', 'timestamp'),
        Index('idx_predictions_score', 'final_score'),
    )


class BacktestResult(Base):
    """Backtest performance metrics"""
    __tablename__ = 'backtest_results'

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_version = Column(String(20), nullable=False)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)

    # Performance metrics
    total_trades = Column(Integer)
    winning_trades = Column(Integer)
    losing_trades = Column(Integer)
    win_rate = Column(Float)

    avg_win = Column(Float)
    avg_loss = Column(Float)
    expectancy = Column(Float)  # (Win% × Avg Win) - (Loss% × Avg Loss)

    total_pnl = Column(Float)
    max_drawdown = Column(Float)
    sharpe_ratio = Column(Float)

    # Risk metrics
    max_consecutive_losses = Column(Integer)
    avg_hold_time = Column(Integer)  # minutes

    created_at = Column(DateTime, default=datetime.utcnow)

    # Indexes
    __table_args__ = (
        Index('idx_backtest_model_version', 'model_version'),
        Index('idx_backtest_dates', 'start_date', 'end_date'),
    )
