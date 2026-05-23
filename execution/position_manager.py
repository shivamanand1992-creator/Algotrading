"""
Position Tracking and P&L Engine for Nifty50 Intraday Options Trading System.

Maintains an in-memory position book, computes real-time unrealized and
realized P&L, and persists every trade to SQLite via SQLAlchemy ORM.

The rich-formatted position report is consumed by the monitoring dashboard.

Database schema
---------------
Table: trades
    Every entry/exit is written to SQLite at logs/trades.db so the session
    can be reconstructed after a crash and for end-of-day reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

import pytz
from loguru import logger
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session

IST = pytz.timezone("Asia/Kolkata")


# ---------------------------------------------------------------------------
# SQLAlchemy ORM model
# ---------------------------------------------------------------------------

class _Base(DeclarativeBase):
    pass


class TradeRecord(_Base):
    """
    Persistent trade record — one row per open position, updated on close.
    """
    __tablename__ = "trades"

    id           = Column(Integer,  primary_key=True, autoincrement=True)
    order_id     = Column(String,   unique=True, index=True, nullable=False)
    symbol       = Column(String,   nullable=False)
    token        = Column(String,   default="")
    strike       = Column(Integer,  default=0)
    option_type  = Column(String,   default="")    # CE | PE
    expiry       = Column(String,   default="")
    direction    = Column(String,   default="BUY") # BUY | SELL (transaction_type)
    entry_price  = Column(Float,    default=0.0)
    exit_price   = Column(Float,    nullable=True)
    qty          = Column(Integer,  default=0)
    lots         = Column(Integer,  default=1)
    realized_pnl = Column(Float,    default=0.0)
    unrealized_pnl = Column(Float,  default=0.0)
    sl_price     = Column(Float,    default=0.0)
    target_price = Column(Float,    default=0.0)
    entry_time   = Column(DateTime, nullable=False)
    exit_time    = Column(DateTime, nullable=True)
    strategy     = Column(String,   default="")
    regime       = Column(String,   default="")
    exit_reason  = Column(Text,     nullable=True)
    is_open      = Column(Boolean,  default=True)
    trade_date   = Column(String,   default="")    # YYYY-MM-DD
    is_paper     = Column(Boolean,  default=False)


# ---------------------------------------------------------------------------
# In-memory position dataclass
# ---------------------------------------------------------------------------

@dataclass
class PositionInfo:
    """
    Runtime position record held in the in-memory book.

    Fields mirror the TradeRecord columns plus transient runtime state
    (unrealized_pnl is computed tick-by-tick and periodically flushed to DB).
    """
    order_id:       str
    symbol:         str
    token:          str
    strike:         int
    option_type:    str            # CE | PE
    expiry:         str
    direction:      str            # BUY | SELL (transaction_type)
    entry_price:    float
    current_price:  float
    qty:            int
    lots:           int            = 1
    unrealized_pnl: float          = 0.0
    realized_pnl:   float          = 0.0
    sl_price:       float          = 0.0
    target_price:   float          = 0.0
    entry_time:     datetime       = field(default_factory=lambda: datetime.now(IST))
    exit_time:      Optional[datetime] = None
    exit_price:     float          = 0.0
    strategy:       str            = ""
    regime:         str            = ""
    exit_reason:    str            = ""
    is_paper:       bool           = False


# ---------------------------------------------------------------------------
# Position Manager
# ---------------------------------------------------------------------------

class PositionManager:
    """
    Tracks open positions and cumulative P&L; persists every trade to SQLite.

    Parameters
    ----------
    config : dict
        Full application config.  Reads:
            database.url  — SQLAlchemy connection string
                            (default "sqlite:///logs/trades.db")
    """

    def __init__(self, config: dict) -> None:
        self.config = config

        # In-memory books
        self._positions:    dict[str, PositionInfo] = {}   # order_id → PositionInfo
        self._closed_trades: list[PositionInfo]     = []

        # Daily statistics (reset at midnight / on __init__)
        self._today:             str = date.today().isoformat()
        self._trade_count_today: int = 0
        self._wins_today:        int = 0
        self._losses_today:      int = 0

        # Database
        db_url  = config.get("database", {}).get("url", "sqlite:///logs/trades.db")
        db_path = Path(db_url.replace("sqlite:///", ""))
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self._engine = create_engine(db_url, echo=False, future=True)
        _Base.metadata.create_all(self._engine)

        logger.info(
            f"[PositionManager] Initialised — DB={db_url}, today={self._today}"
        )

        # Restore any open positions from the DB (crash recovery)
        self._restore_open_positions()

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------

    def add_position(
        self,
        order_id:   str,
        signal,
        fill_price: float,
        qty:        int,
        lots:       int = 1,
        is_paper:   bool = False,
    ) -> PositionInfo:
        """
        Register a newly filled position in the in-memory book and persist it.

        Parameters
        ----------
        order_id   : unique order ID from the broker (or PAPER-…).
        signal     : TradeSignal used to enter the trade.
        fill_price : actual fill / simulated LTP.
        qty        : total shares (lots × lot_size).
        lots       : number of lots.
        is_paper   : True if this is a paper trade.

        Returns
        -------
        PositionInfo  the newly created position.
        """
        sl_price     = float(getattr(signal, "sl_price",     fill_price * 0.70))
        target_price = float(getattr(signal, "target_price", fill_price * 1.60))

        pos = PositionInfo(
            order_id     = order_id,
            symbol       = str(getattr(signal, "symbol",           "")),
            token        = str(getattr(signal, "token",             "")),
            strike       = int(getattr(signal, "strike",            0)),
            option_type  = str(getattr(signal, "option_type",       "")),
            expiry       = str(getattr(signal, "expiry",            "")),
            direction    = str(getattr(signal, "transaction_type",  "BUY")),
            entry_price  = fill_price,
            current_price= fill_price,
            qty          = qty,
            lots         = lots,
            sl_price     = sl_price,
            target_price = target_price,
            strategy     = str(getattr(signal, "strategy_name",     "")),
            regime       = str(getattr(signal, "regime",            "")),
            is_paper     = is_paper,
        )
        self._positions[order_id] = pos
        self._persist_open(pos)

        logger.info(
            f"[PositionManager] Position added: order_id={order_id} "
            f"symbol={pos.symbol} fill=₹{fill_price:.2f} qty={qty} "
            f"SL=₹{sl_price:.2f} target=₹{target_price:.2f}"
        )
        return pos

    def update_position_pnl(self, symbol_token: str, current_ltp: float) -> None:
        """
        Recompute unrealized P&L for all positions whose token matches.

        Called every market tick.

        Parameters
        ----------
        symbol_token : Angel One instrument token (string).
        current_ltp  : latest traded price of the instrument.
        """
        for pos in self._positions.values():
            if pos.token == symbol_token:
                pos.current_price  = current_ltp
                multiplier         = 1 if pos.direction == "BUY" else -1
                pos.unrealized_pnl = multiplier * (current_ltp - pos.entry_price) * pos.qty

    def update_position_pnl_by_order_id(
        self, order_id: str, current_ltp: float
    ) -> None:
        """Update a single position's unrealized P&L by order_id."""
        pos = self._positions.get(order_id)
        if pos is None:
            return
        pos.current_price  = current_ltp
        multiplier         = 1 if pos.direction == "BUY" else -1
        pos.unrealized_pnl = multiplier * (current_ltp - pos.entry_price) * pos.qty

    def update_sl(self, order_id: str, new_sl: float) -> None:
        """Update the stop-loss price of an open position (trailing SL)."""
        pos = self._positions.get(order_id)
        if pos:
            old_sl       = pos.sl_price
            pos.sl_price = new_sl
            logger.debug(
                f"[PositionManager] Trailing SL updated for {pos.symbol}: "
                f"₹{old_sl:.2f} → ₹{new_sl:.2f}"
            )

    def close_position(
        self,
        order_id:   str,
        exit_price: float,
        reason:     str = "",
    ) -> Optional[PositionInfo]:
        """
        Mark a position as closed, compute realized P&L, and persist the exit.

        Parameters
        ----------
        order_id   : order_id of the position to close.
        exit_price : actual exit fill price.
        reason     : human-readable exit reason.

        Returns
        -------
        PositionInfo  the closed position, or None if not found.
        """
        if order_id not in self._positions:
            logger.warning(
                f"[PositionManager] close_position: order_id {order_id} not found"
            )
            return None

        pos              = self._positions.pop(order_id)
        pos.exit_time    = datetime.now(IST)
        pos.exit_reason  = reason
        pos.exit_price   = exit_price if exit_price > 0 else pos.current_price

        multiplier       = 1 if pos.direction == "BUY" else -1
        pos.realized_pnl = multiplier * (pos.exit_price - pos.entry_price) * pos.qty
        pos.unrealized_pnl = 0.0

        self._closed_trades.append(pos)

        # Update daily stats
        self._trade_count_today += 1
        if pos.realized_pnl > 0:
            self._wins_today += 1
        else:
            self._losses_today += 1

        self._persist_close(pos)

        logger.info(
            f"[PositionManager] Position closed: order_id={order_id} "
            f"symbol={pos.symbol} exit=₹{pos.exit_price:.2f} "
            f"P&L=₹{pos.realized_pnl:+,.2f} reason='{reason}'"
        )
        return pos

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def get_open_positions(self) -> List[PositionInfo]:
        """Return all currently open positions."""
        return list(self._positions.values())

    def get_open_positions_as_dicts(self) -> list[dict]:
        """Return open positions as plain dicts (for RiskManager / OrderManager)."""
        return [self._pos_to_dict(p) for p in self._positions.values()]

    def get_closed_trades(self) -> List[PositionInfo]:
        """Return all trades closed in the current session."""
        return list(self._closed_trades)

    def get_daily_pnl(self) -> float:
        """
        Return today's total P&L = realized (closed today) + unrealized (open).
        """
        return round(self.get_realized_pnl() + self.get_unrealized_pnl(), 2)

    def get_realized_pnl(self) -> float:
        """Return only the realized P&L from trades closed today."""
        today = date.today().isoformat()
        return round(
            sum(
                t.realized_pnl
                for t in self._closed_trades
                if t.exit_time
                and t.exit_time.astimezone(IST).date().isoformat() == today
            ),
            2,
        )

    def get_unrealized_pnl(self) -> float:
        """Return the sum of unrealized P&L across all open positions."""
        return round(sum(p.unrealized_pnl for p in self._positions.values()), 2)

    def get_position_by_order_id(self, order_id: str) -> Optional[PositionInfo]:
        """Return the PositionInfo for a given order_id, or None."""
        return self._positions.get(order_id)

    def get_position_by_token(self, token: str) -> Optional[PositionInfo]:
        """Return the first open position whose token matches."""
        for pos in self._positions.values():
            if pos.token == token:
                return pos
        return None

    def get_position_by_symbol(self, symbol: str) -> Optional[PositionInfo]:
        """Return the first open position whose symbol matches."""
        for pos in self._positions.values():
            if pos.symbol == symbol:
                return pos
        return None

    def get_position_report(self) -> str:
        """
        Return a rich-formatted multi-line string summarising current positions.

        Designed to be rendered directly in the monitoring dashboard or logged.
        """
        now_ist  = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        daily    = self.get_daily_pnl()
        realized = self.get_realized_pnl()
        unreal   = self.get_unrealized_pnl()
        open_cnt = len(self._positions)
        win_rate = (
            f"{self._wins_today}/{self._trade_count_today}"
            if self._trade_count_today > 0
            else "0/0"
        )

        header = (
            f"{'─'*60}\n"
            f"  POSITION REPORT  [{now_ist}]\n"
            f"{'─'*60}\n"
            f"  Open Positions  : {open_cnt}\n"
            f"  Daily P&L       : ₹{daily:+,.2f}\n"
            f"  Realized P&L    : ₹{realized:+,.2f}\n"
            f"  Unrealized P&L  : ₹{unreal:+,.2f}\n"
            f"  Wins / Trades   : {win_rate}  "
            f"(L={self._losses_today})\n"
            f"{'─'*60}"
        )

        if not self._positions:
            return header + "\n  No open positions.\n" + "─" * 60

        rows = [
            f"{'─'*60}",
            f"  {'SYMBOL':<26} {'DIR':4} {'QTY':>5} "
            f"{'ENTRY':>8} {'LTP':>8} {'UNREAL P&L':>12} {'SL':>8}",
            f"{'─'*60}",
        ]
        for pos in self._positions.values():
            pnl_str = f"₹{pos.unrealized_pnl:+,.0f}"
            rows.append(
                f"  {pos.symbol:<26} {pos.direction:<4} {pos.qty:>5} "
                f"₹{pos.entry_price:>7.2f} ₹{pos.current_price:>7.2f} "
                f"{pnl_str:>12} ₹{pos.sl_price:>7.2f}"
            )
        rows.append("─" * 60)

        return header + "\n" + "\n".join(rows)

    # ------------------------------------------------------------------
    # Database persistence
    # ------------------------------------------------------------------

    def _persist_open(self, pos: PositionInfo) -> None:
        """Write a new open position to SQLite."""
        try:
            with Session(self._engine) as session:
                record = TradeRecord(
                    order_id     = pos.order_id,
                    symbol       = pos.symbol,
                    token        = pos.token,
                    strike       = pos.strike,
                    option_type  = pos.option_type,
                    expiry       = pos.expiry,
                    direction    = pos.direction,
                    entry_price  = pos.entry_price,
                    qty          = pos.qty,
                    lots         = pos.lots,
                    sl_price     = pos.sl_price,
                    target_price = pos.target_price,
                    entry_time   = pos.entry_time,
                    strategy     = pos.strategy,
                    regime       = pos.regime,
                    is_open      = True,
                    trade_date   = self._today,
                    is_paper     = pos.is_paper,
                )
                session.merge(record)
                session.commit()
            logger.debug(f"[PositionManager] Persisted open: {pos.order_id}")
        except Exception as exc:
            logger.warning(f"[PositionManager] _persist_open failed: {exc}")

    def _persist_close(self, pos: PositionInfo) -> None:
        """Update the SQLite record when a position is closed."""
        try:
            with Session(self._engine) as session:
                rec = (
                    session.query(TradeRecord)
                    .filter_by(order_id=pos.order_id)
                    .first()
                )
                if rec:
                    rec.exit_price   = pos.exit_price
                    rec.realized_pnl = pos.realized_pnl
                    rec.exit_time    = pos.exit_time
                    rec.exit_reason  = pos.exit_reason
                    rec.is_open      = False
                else:
                    # Position was opened externally (e.g. before crash recovery)
                    session.add(TradeRecord(
                        order_id     = pos.order_id,
                        symbol       = pos.symbol,
                        token        = pos.token,
                        strike       = pos.strike,
                        option_type  = pos.option_type,
                        expiry       = pos.expiry,
                        direction    = pos.direction,
                        entry_price  = pos.entry_price,
                        exit_price   = pos.exit_price,
                        qty          = pos.qty,
                        lots         = pos.lots,
                        realized_pnl = pos.realized_pnl,
                        sl_price     = pos.sl_price,
                        target_price = pos.target_price,
                        entry_time   = pos.entry_time,
                        exit_time    = pos.exit_time,
                        strategy     = pos.strategy,
                        regime       = pos.regime,
                        exit_reason  = pos.exit_reason,
                        is_open      = False,
                        trade_date   = self._today,
                        is_paper     = pos.is_paper,
                    ))
                session.commit()
            logger.debug(f"[PositionManager] Persisted close: {pos.order_id}")
        except Exception as exc:
            logger.warning(f"[PositionManager] _persist_close failed: {exc}")

    def flush_unrealized_to_db(self) -> None:
        """
        Periodically flush current unrealized P&L values to SQLite.
        Called by the monitoring loop (e.g. every 5 minutes).
        """
        try:
            with Session(self._engine) as session:
                for pos in self._positions.values():
                    rec = (
                        session.query(TradeRecord)
                        .filter_by(order_id=pos.order_id)
                        .first()
                    )
                    if rec:
                        rec.unrealized_pnl = pos.unrealized_pnl
                session.commit()
            logger.debug("[PositionManager] Unrealized P&L flushed to DB.")
        except Exception as exc:
            logger.warning(f"[PositionManager] flush_unrealized_to_db failed: {exc}")

    def _restore_open_positions(self) -> None:
        """
        On start-up, reload open positions from the DB into the in-memory book.
        This allows the system to resume tracking after a restart.
        """
        try:
            with Session(self._engine) as session:
                open_records = (
                    session.query(TradeRecord)
                    .filter_by(is_open=True, trade_date=self._today)
                    .all()
                )
                for rec in open_records:
                    entry_time = rec.entry_time
                    if entry_time and entry_time.tzinfo is None:
                        entry_time = IST.localize(entry_time)

                    pos = PositionInfo(
                        order_id     = rec.order_id,
                        symbol       = rec.symbol,
                        token        = rec.token or "",
                        strike       = rec.strike or 0,
                        option_type  = rec.option_type or "",
                        expiry       = rec.expiry or "",
                        direction    = rec.direction or "BUY",
                        entry_price  = rec.entry_price or 0.0,
                        current_price= rec.entry_price or 0.0,
                        qty          = rec.qty or 0,
                        lots         = rec.lots or 1,
                        sl_price     = rec.sl_price or 0.0,
                        target_price = rec.target_price or 0.0,
                        strategy     = rec.strategy or "",
                        regime       = rec.regime or "",
                        entry_time   = entry_time or datetime.now(IST),
                        is_paper     = rec.is_paper or False,
                    )
                    self._positions[rec.order_id] = pos

                if open_records:
                    logger.info(
                        f"[PositionManager] Restored {len(open_records)} open "
                        f"position(s) from DB (crash recovery)."
                    )
        except Exception as exc:
            logger.warning(
                f"[PositionManager] _restore_open_positions failed: {exc}"
            )

    # ------------------------------------------------------------------
    # Historical query helpers
    # ------------------------------------------------------------------

    def get_trades_for_date(self, trade_date: str) -> list[dict]:
        """
        Return all trade records for a given date string (YYYY-MM-DD).

        Parameters
        ----------
        trade_date : str  e.g. "2024-05-15"

        Returns
        -------
        list[dict]  each dict has all TradeRecord columns.
        """
        try:
            with Session(self._engine) as session:
                records = (
                    session.query(TradeRecord)
                    .filter_by(trade_date=trade_date)
                    .order_by(TradeRecord.entry_time)
                    .all()
                )
                return [self._record_to_dict(r) for r in records]
        except Exception as exc:
            logger.warning(
                f"[PositionManager] get_trades_for_date({trade_date}) failed: {exc}"
            )
            return []

    def get_pnl_for_date(self, trade_date: str) -> float:
        """Return total realized P&L for a given date."""
        trades = self.get_trades_for_date(trade_date)
        return round(sum(t.get("realized_pnl", 0.0) for t in trades if not t.get("is_open")), 2)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _pos_to_dict(self, pos: PositionInfo) -> dict:
        return {
            "order_id":      pos.order_id,
            "symbol":        pos.symbol,
            "token":         pos.token,
            "strike":        pos.strike,
            "option_type":   pos.option_type,
            "expiry":        pos.expiry,
            "direction":     pos.direction,
            "entry_price":   pos.entry_price,
            "current_price": pos.current_price,
            "qty":           pos.qty,
            "lots":          pos.lots,
            "unrealized_pnl":pos.unrealized_pnl,
            "realized_pnl":  pos.realized_pnl,
            "sl_price":      pos.sl_price,
            "target_price":  pos.target_price,
            "entry_time":    pos.entry_time,
            "exit_time":     pos.exit_time,
            "strategy":      pos.strategy,
            "regime":        pos.regime,
            "exit_reason":   pos.exit_reason,
            "is_paper":      pos.is_paper,
        }

    @staticmethod
    def _record_to_dict(rec: TradeRecord) -> dict:
        return {
            "id":            rec.id,
            "order_id":      rec.order_id,
            "symbol":        rec.symbol,
            "token":         rec.token,
            "strike":        rec.strike,
            "option_type":   rec.option_type,
            "expiry":        rec.expiry,
            "direction":     rec.direction,
            "entry_price":   rec.entry_price,
            "exit_price":    rec.exit_price,
            "qty":           rec.qty,
            "lots":          rec.lots,
            "realized_pnl":  rec.realized_pnl,
            "unrealized_pnl":rec.unrealized_pnl,
            "sl_price":      rec.sl_price,
            "target_price":  rec.target_price,
            "entry_time":    rec.entry_time,
            "exit_time":     rec.exit_time,
            "strategy":      rec.strategy,
            "regime":        rec.regime,
            "exit_reason":   rec.exit_reason,
            "is_open":       rec.is_open,
            "trade_date":    rec.trade_date,
            "is_paper":      rec.is_paper,
        }
