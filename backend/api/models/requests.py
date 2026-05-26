from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class StartStrategyRequest(BaseModel):
    mode: str = Field(..., pattern="^(paper|live)$")


class UpdateStrategyConfigRequest(BaseModel):
    config: Dict[str, Any]


class ClosePositionRequest(BaseModel):
    reason: Optional[str] = "manual_close"


class TradeFilterRequest(BaseModel):
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    strategy: Optional[str] = None
    symbol: Optional[str] = None
    min_pnl: Optional[float] = None
    max_pnl: Optional[float] = None


class SystemModeRequest(BaseModel):
    mode: str = Field(..., pattern="^(paper|live|backtest)$")


class UpdateRiskLimitsRequest(BaseModel):
    daily_loss_limit: Optional[float] = None      # absolute ₹ amount
    max_positions: Optional[int] = None
    per_trade_risk_percent: Optional[float] = None
