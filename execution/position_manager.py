"""
Position tracking, P&L calculation, and trade persistence.
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, List
import pytz
from loguru import logger
from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, Boolean
from sqlalchemy.orm import declarative_base, Session
from pathlib import Path

IST = pytz.timezone("Asia/Kolkata")
Base = declarative_base()


class TradeRecord(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String, unique=True, index=True)
    symbol = Column(String)
    token = Column(String)
    strike = Column(Integer)
    option_type = Column(String)
    expiry = Column(String)
    direction = Column(String)           # BUY or SELL
    entry_price = Column(Float)
    exit_price = Column(Float, nullable=True)
    qty = Column(Integer)
    realized_pnl = Column(Float, default=0.0)
    sl_price = Column(Float)
    target_price = Column(Float)
    entry_time = Column(DateTime)
    exit_time = Column(DateTime, nullable=True)
    strategy = Column(String)
    regime = Column(String)
    exit_reason = Column(String, nullable=True)
    is_open = Column(Boolean, default=True)
    trade_date = Column(String)          # YYYY-MM-DD


@dataclass
class PositionInfo:
    order_id: str
    symbol: str
    token: str
    strike: int
    option_type: str
    expiry: str
    direction: str                       # BUY or SELL
    entry_price: float
    current_price: float
    qty: int
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    sl_price: float = 0.0
    target_price: float = 0.0
    entry_time: datetime = field(default_factory=lambda: datetime.now(IST))
    exit_time: Optional[datetime] = None
    strategy: str = ""
    regime: str = ""
    exit_reason: str = ""


class PositionManager:
    def __init__(self, config: dict):
        self.config = config
        self._positions: dict[str, PositionInfo] = {}    # order_id → PositionInfo
        self._closed_trades: list[PositionInfo] = []
        self._trade_count_today: int = 0
        self._wins_today: int = 0
        self._losses_today: int = 0
        self._today = date.today().isoformat()

        db_url = config.get("database", {}).get("url", "sqlite:///logs/trades.db")
        Path("logs").mkdir(exist_ok=True)
        self._engine = create_engine(db_url, echo=False)
        Base.metadata.create_all(self._engine)
        logger.info(f"PositionManager initialised. DB: {db_url}")

    # ── Write API ─────────────────────────────────────────────────────────────

    def add_position(self, order_id: str, signal, fill_price: float, qty: int):
        """Register a new open position after order fill."""
        sl = getattr(signal, "sl_price", fill_price * 0.70)
        target = getattr(signal, "target_price", fill_price * 1.60)
        pos = PositionInfo(
            order_id=order_id,
            symbol=getattr(signal, "symbol", ""),
            token=getattr(signal, "token", ""),
            strike=getattr(signal, "strike", 0),
            option_type=getattr(signal, "option_type", ""),
            expiry=getattr(signal, "expiry", ""),
            direction=getattr(signal, "transaction_type", "BUY"),
            entry_price=fill_price,
            current_price=fill_price,
            qty=qty,
            sl_price=sl,
            target_price=target,
            strategy=getattr(signal, "strategy_name", ""),
            regime=getattr(signal, "regime", ""),
        )
        self._positions[order_id] = pos
        self._persist_open(pos)
        logger.info(f"Position added: {pos.symbol} | Entry ₹{fill_price:.2f} | Qty {qty}")

    def update_position_pnl(self, symbol_token: str, current_ltp: float):
        """Update unrealized P&L for a position identified by its token."""
        for pos in self._positions.values():
            if pos.token == symbol_token:
                multiplier = 1 if pos.direction == "BUY" else -1
                pos.current_price = current_ltp
                pos.unrealized_pnl = multiplier * (current_ltp - pos.entry_price) * pos.qty
                break

    def close_position(self, order_id: str, exit_price: float, reason: str = ""):
        """Move a position to closed and compute realized P&L."""
        if order_id not in self._positions:
            logger.warning(f"Tried to close unknown position: {order_id}")
            return

        pos = self._positions.pop(order_id)
        pos.exit_time = datetime.now(IST)
        pos.exit_reason = reason

        if exit_price > 0:
            multiplier = 1 if pos.direction == "BUY" else -1
            pos.realized_pnl = multiplier * (exit_price - pos.entry_price) * pos.qty
            pos.current_price = exit_price
        else:
            pos.realized_pnl = pos.unrealized_pnl

        pos.unrealized_pnl = 0.0
        self._closed_trades.append(pos)
        self._trade_count_today += 1
        if pos.realized_pnl > 0:
            self._wins_today += 1
        else:
            self._losses_today += 1

        self._persist_close(pos, exit_price)
        logger.info(f"Position closed: {pos.symbol} | P&L ₹{pos.realized_pnl:+,.0f} | Reason: {reason}")

    # ── Read API ──────────────────────────────────────────────────────────────

    def get_open_positions(self) -> List[PositionInfo]:
        return list(self._positions.values())

    def get_daily_pnl(self) -> float:
        realized = self.get_realized_pnl()
        unrealized = sum(p.unrealized_pnl for p in self._positions.values())
        return realized + unrealized

    def get_realized_pnl(self) -> float:
        return sum(t.realized_pnl for t in self._closed_trades if t.exit_time and
                   t.exit_time.astimezone(IST).date().isoformat() == self._today)

    def get_position_by_token(self, token: str) -> Optional[PositionInfo]:
        for pos in self._positions.values():
            if pos.token == token:
                return pos
        return None

    def get_position_report(self) -> str:
        """Rich-formatted summary string."""
        lines = [f"Open positions: {len(self._positions)}",
                 f"Daily P&L: ₹{self.get_daily_pnl():+,.0f}",
                 f"Realized: ₹{self.get_realized_pnl():+,.0f}",
                 f"Trades today: {self._trade_count_today} | W: {self._wins_today} | L: {self._losses_today}"]
        return "\n".join(lines)

    # ── Persistence ───────────────────────────────────────────────────────────

    def _persist_open(self, pos: PositionInfo):
        try:
            with Session(self._engine) as session:
                record = TradeRecord(
                    order_id=pos.order_id,
                    symbol=pos.symbol,
                    token=pos.token,
                    strike=pos.strike,
                    option_type=pos.option_type,
                    expiry=pos.expiry,
                    direction=pos.direction,
                    entry_price=pos.entry_price,
                    qty=pos.qty,
                    sl_price=pos.sl_price,
                    target_price=pos.target_price,
                    entry_time=pos.entry_time,
                    strategy=pos.strategy,
                    regime=pos.regime,
                    is_open=True,
                    trade_date=self._today,
                )
                session.merge(record)
                session.commit()
        except Exception as e:
            logger.warning(f"DB persist_open failed: {e}")

    def _persist_close(self, pos: PositionInfo, exit_price: float):
        try:
            with Session(self._engine) as session:
                rec = session.query(TradeRecord).filter_by(order_id=pos.order_id).first()
                if rec:
                    rec.exit_price = exit_price
                    rec.realized_pnl = pos.realized_pnl
                    rec.exit_time = pos.exit_time
                    rec.exit_reason = pos.exit_reason
                    rec.is_open = False
                    session.commit()
        except Exception as e:
            logger.warning(f"DB persist_close failed: {e}")
