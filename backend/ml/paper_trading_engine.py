"""
PAPER TRADING ENGINE — Simulates trades for validation
========================================================

Tracks:
- Account balance & equity
- Active positions with real-time P&L
- Closed trades with performance metrics
- Weekly/monthly/YTD returns
- Win rate, profit factor, largest win/loss
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict, field
import uuid

from loguru import logger

_IST = timezone(timedelta(hours=5, minutes=30))

# ─────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PaperTrade:
    """Simulated trade execution"""
    trade_id: str
    strategy: str  # "call_spread", "intraday_call"
    symbol: str
    entry_price: float
    entry_time: str
    entry_datetime: datetime = field(default_factory=lambda: datetime.now(_IST))

    quantity: int = 1
    premium_paid: float = 0.0
    max_profit: float = 0.0
    max_loss: float = 0.0

    current_price: float = 0.0
    current_pnl: float = 0.0
    current_pnl_pct: float = 0.0

    exit_price: Optional[float] = None
    exit_time: Optional[str] = None
    exit_reason: str = "open"  # open, profit_target, stop_loss, time_exit, manual

    status: str = "open"  # open, closed
    confidence_score: float = 0.0

    def calculate_pnl(self, current_price: float) -> Tuple[float, float]:
        """Calculate current P&L"""
        if self.strategy == "call_spread":
            # For call spread: P&L = (current_price - entry_price) * width - premium_paid
            # Simplified: assume spread value changes linearly
            move = current_price - self.entry_price
            pnl = move * 100 * self.quantity - self.premium_paid * 100 * self.quantity
            pnl = min(pnl, self.max_profit)  # Cap at max profit
            pnl = max(pnl, -self.max_loss)   # Cap at max loss
        else:
            # For intraday call: P&L = (current_price - entry_price) * 100 - premium_paid
            move = current_price - self.entry_price
            pnl = move * 100 * self.quantity - self.premium_paid * 100 * self.quantity
            pnl = max(pnl, -self.premium_paid * 100 * self.quantity)  # Cap at premium

        pnl_pct = (pnl / (self.premium_paid * 100 * self.quantity)) * 100 if self.premium_paid > 0 else 0
        return pnl, pnl_pct


@dataclass
class PaperAccount:
    """Paper trading account state"""
    account_id: str
    initial_capital: float = 100000.0
    current_balance: float = 100000.0

    active_trades: List[PaperTrade] = field(default_factory=list)
    closed_trades: List[PaperTrade] = field(default_factory=list)

    total_pnl: float = 0.0
    week_pnl: float = 0.0
    month_pnl: float = 0.0

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0

    largest_win: float = 0.0
    largest_loss: float = 0.0

    start_date: datetime = field(default_factory=lambda: datetime.now(_IST))

    @property
    def win_rate(self) -> float:
        """Winning trade percentage"""
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100

    @property
    def profit_factor(self) -> float:
        """Average win / Average loss"""
        if self.losing_trades == 0:
            return 0.0
        avg_win = self.largest_win / max(self.winning_trades, 1) if self.winning_trades > 0 else 0
        avg_loss = abs(self.largest_loss) / max(self.losing_trades, 1)
        return avg_win / avg_loss if avg_loss > 0 else 0

    @property
    def equity(self) -> float:
        """Current equity (balance + open position P&L)"""
        open_pnl = sum(t.current_pnl for t in self.active_trades)
        return self.current_balance + open_pnl

    @property
    def return_pct(self) -> float:
        """Total return percentage"""
        if self.initial_capital == 0:
            return 0.0
        return ((self.equity - self.initial_capital) / self.initial_capital) * 100


# ─────────────────────────────────────────────────────────────────────────────
# PAPER TRADING ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class PaperTradingEngine:
    """Simulates trade execution and tracks performance"""

    def __init__(self, initial_capital: float = 100000.0):
        self.account = PaperAccount(
            account_id=f"paper_{datetime.now(_IST).strftime('%Y%m%d_%H%M%S')}",
            initial_capital=initial_capital,
            current_balance=initial_capital
        )
        logger.info(f"[PaperTrading] Account initialized: {self.account.account_id} | Capital: ₹{initial_capital:,.0f}")

    async def execute_trade(self, setup) -> PaperTrade:
        """Execute a trade setup (paper simulation)"""

        trade = PaperTrade(
            trade_id=f"trade_{uuid.uuid4().hex[:8]}",
            strategy=setup.strategy,
            symbol=setup.symbol,
            entry_price=setup.entry_price,
            entry_time=setup.entry_time,
            entry_datetime=datetime.now(_IST),
            quantity=1,
            premium_paid=setup.capital_required / 100,  # Per share
            max_profit=setup.max_profit,
            max_loss=setup.max_loss,
            current_price=setup.entry_price,
            confidence_score=setup.confidence_score,
        )

        # Add to active trades
        self.account.active_trades.append(trade)
        self.account.total_trades += 1

        logger.info(
            f"[PaperTrading] EXECUTED {setup.strategy.upper()} "
            f"| Entry: ₹{setup.entry_price:.2f} "
            f"| Risk: ₹{setup.max_loss:.0f} | Profit Target: ₹{setup.max_profit:.0f}"
        )

        return trade

    async def update_prices(self, current_price: float):
        """Update all active trades with current price"""
        for trade in self.account.active_trades:
            if trade.symbol == "NIFTY":
                trade.current_price = current_price
                pnl, pnl_pct = trade.calculate_pnl(current_price)
                trade.current_pnl = pnl
                trade.current_pnl_pct = pnl_pct

    async def check_exits(self, current_price: float) -> List[PaperTrade]:
        """Check if any trades hit profit target or stop loss"""
        closed_trades = []

        for trade in self.account.active_trades[:]:  # Copy to avoid modifying during iteration
            if trade.status == "closed":
                continue

            pnl, pnl_pct = trade.calculate_pnl(current_price)

            # Check profit target (50% of max profit)
            profit_target = trade.max_profit * 0.5
            if pnl >= profit_target:
                await self._close_trade(trade, current_price, "profit_target", pnl)
                closed_trades.append(trade)
                continue

            # Check stop loss (100% of max loss)
            if pnl <= -trade.max_loss:
                await self._close_trade(trade, current_price, "stop_loss", -trade.max_loss)
                closed_trades.append(trade)
                continue

            # Check time exit (weekly spreads after 4 days, intraday after 4 hours)
            time_diff = datetime.now(_IST) - trade.entry_datetime
            if trade.strategy == "call_spread" and time_diff > timedelta(days=4):
                await self._close_trade(trade, current_price, "time_exit", pnl)
                closed_trades.append(trade)
            elif trade.strategy == "intraday_call" and time_diff > timedelta(hours=4):
                await self._close_trade(trade, current_price, "time_exit", pnl)
                closed_trades.append(trade)

        return closed_trades

    async def _close_trade(self, trade: PaperTrade, exit_price: float, reason: str, pnl: float):
        """Close a trade and update account"""
        trade.status = "closed"
        trade.exit_price = exit_price
        trade.exit_time = datetime.now(_IST).strftime("%H:%M:%S")
        trade.exit_reason = reason
        trade.current_pnl = pnl

        # Update account
        self.account.active_trades.remove(trade)
        self.account.closed_trades.append(trade)
        self.account.current_balance += pnl
        self.account.total_pnl += pnl
        self.account.week_pnl += pnl

        # Update win/loss tracking
        if pnl > 0:
            self.account.winning_trades += 1
            self.account.largest_win = max(self.account.largest_win, pnl)
        else:
            self.account.losing_trades += 1
            self.account.largest_loss = min(self.account.largest_loss, pnl)

        logger.info(
            f"[PaperTrading] CLOSED {trade.strategy.upper()} "
            f"| Exit: ₹{exit_price:.2f} "
            f"| Reason: {reason} "
            f"| P&L: ₹{pnl:.0f} ({(pnl/trade.premium_paid/100)*100:.1f}%)"
        )

    async def get_status(self) -> Dict:
        """Get complete account status"""
        return {
            "account_id": self.account.account_id,
            "capital": self.account.initial_capital,
            "balance": self.account.current_balance,
            "equity": self.account.equity,
            "total_pnl": self.account.total_pnl,
            "return_pct": self.account.return_pct,
            "week_pnl": self.account.week_pnl,
            "month_pnl": self.account.month_pnl,
            "active_trades": len(self.account.active_trades),
            "total_trades": self.account.total_trades,
            "winning_trades": self.account.winning_trades,
            "losing_trades": self.account.losing_trades,
            "win_rate": self.account.win_rate,
            "profit_factor": self.account.profit_factor,
            "largest_win": self.account.largest_win,
            "largest_loss": self.account.largest_loss,
            "active": [
                {
                    "trade_id": t.trade_id,
                    "strategy": t.strategy,
                    "entry_price": t.entry_price,
                    "entry_time": t.entry_time,
                    "current_pnl": t.current_pnl,
                    "current_pnl_pct": t.current_pnl_pct,
                    "max_profit": t.max_profit,
                    "max_loss": t.max_loss,
                }
                for t in self.account.active_trades
            ],
            "closed": [
                {
                    "trade_id": t.trade_id,
                    "strategy": t.strategy,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "pnl": t.current_pnl,
                    "pnl_pct": t.current_pnl_pct,
                    "exit_reason": t.exit_reason,
                    "duration_min": int((datetime.now(_IST) - t.entry_datetime).total_seconds() / 60),
                }
                for t in self.account.closed_trades[-20:]  # Last 20
            ]
        }


# ─────────────────────────────────────────────────────────────────────────────
# SINGLETON
# ─────────────────────────────────────────────────────────────────────────────

_engine_instance = None

def get_paper_engine() -> PaperTradingEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = PaperTradingEngine(initial_capital=100000.0)
    return _engine_instance

def reset_paper_engine():
    """Reset engine (for live switch)"""
    global _engine_instance
    _engine_instance = None
