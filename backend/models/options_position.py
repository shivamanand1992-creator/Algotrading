"""
Database model for Athena options positions
"""

from sqlalchemy import Column, Integer, String, Float, DateTime, JSON, Enum
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import enum

Base = declarative_base()


class StrategyType(str, enum.Enum):
    """Options strategy types"""
    BULL_PUT_SPREAD = "BULL_PUT_SPREAD"
    BEAR_CALL_SPREAD = "BEAR_CALL_SPREAD"
    IRON_CONDOR = "IRON_CONDOR"


class PositionStatus(str, enum.Enum):
    """Position status"""
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"


class OptionsPosition(Base):
    """
    Track Athena options positions
    """
    __tablename__ = "options_positions"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Strategy details
    strategy = Column(String(50), nullable=False)  # BULL_PUT_SPREAD, etc.
    symbol = Column(String(20), nullable=False, default="BANKNIFTY")

    # Entry
    entry_date = Column(DateTime, nullable=False)
    expiry_date = Column(DateTime, nullable=False)

    # Strikes (JSON for flexibility)
    strikes = Column(JSON, nullable=False)  # {sell_strike, buy_strike, sell_strike_2, buy_strike_2}

    # P&L
    premium_received = Column(Float, nullable=False)  # Credit received
    max_loss = Column(Float, nullable=False)  # Max potential loss
    current_value = Column(Float, default=0.0)  # Current spread value
    realized_pnl = Column(Float, default=0.0)  # Realized P&L on exit

    # Probabilities
    confidence = Column(Float, nullable=False)  # AI confidence score
    probability_of_profit = Column(Float, nullable=False)  # Expected PoP

    # Exit
    exit_date = Column(DateTime, nullable=True)
    exit_reason = Column(String(50), nullable=True)  # TARGET, STOP_LOSS, EXPIRY, MANUAL

    # Status
    status = Column(String(20), nullable=False, default="OPEN")
    mode = Column(String(10), nullable=False, default="paper")  # paper or live

    # AI decision context
    reasoning = Column(String(500), nullable=True)
    risk_factors = Column(JSON, nullable=True)  # List of risk factors

    # Market conditions at entry
    spot_at_entry = Column(Float, nullable=True)
    vix_at_entry = Column(Float, nullable=True)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """Convert to dictionary"""
        return {
            "id": self.id,
            "strategy": self.strategy,
            "symbol": self.symbol,
            "entry_date": self.entry_date.isoformat() if self.entry_date else None,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "strikes": self.strikes,
            "premium_received": self.premium_received,
            "max_loss": self.max_loss,
            "current_value": self.current_value,
            "realized_pnl": self.realized_pnl,
            "confidence": self.confidence,
            "probability_of_profit": self.probability_of_profit,
            "exit_date": self.exit_date.isoformat() if self.exit_date else None,
            "exit_reason": self.exit_reason,
            "status": self.status,
            "mode": self.mode,
            "reasoning": self.reasoning,
            "risk_factors": self.risk_factors,
            "spot_at_entry": self.spot_at_entry,
            "vix_at_entry": self.vix_at_entry,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
