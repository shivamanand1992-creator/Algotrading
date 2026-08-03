"""
Risk Management Engine for Nifty50 Intraday Options Trading System.

Centralises all risk checks so that no order is placed without passing:
    • Daily loss limit gate
    • Daily profit target gate (halt new entries once target is reached)
    • Max simultaneous positions gate
    • Time gate (no_new_trades_after)
    • Per-trade capital allocation

Also manages trailing stop-losses and produces a live risk report.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Optional

import pytz
from loguru import logger

from strategies.base_strategy import TradeSignal

IST = pytz.timezone("Asia/Kolkata")


class RiskManager:
    """
    Risk management engine.

    Parameters
    ----------
    config : dict
        Full application configuration (loaded from config/config.yaml).

    Key config paths consumed
    -------------------------
    risk.total_capital
    risk.daily_loss_limit_pct
    risk.daily_profit_target_pct
    risk.per_trade_risk_pct
    risk.option_buy_sl_pct
    risk.option_buy_target_pct
    risk.option_sell_sl_pct
    risk.trailing_sl_trigger_pct
    risk.trailing_sl_pct
    trading.max_simultaneous_positions
    trading.no_new_trades_after
    trading.lot_size
    """

    def __init__(self, config: dict) -> None:
        self.config      = config
        risk_cfg         = config.get("risk", {})
        trading_cfg      = config.get("trading", {})

        # Capital
        self.total_capital: float = float(risk_cfg.get("total_capital", 500_000))

        # Daily limits
        self.daily_loss_limit: float = (
            self.total_capital
            * float(risk_cfg.get("daily_loss_limit_pct", 0.04))
        )
        self.daily_profit_target: float = (
            self.total_capital
            * float(risk_cfg.get("daily_profit_target_pct", 0.02))
        )

        # Per-trade risk
        self.per_trade_risk_pct: float = float(
            risk_cfg.get("per_trade_risk_pct", 0.01)
        )
        self.per_trade_risk_amount: float = self.total_capital * self.per_trade_risk_pct

        # Option SL/target percentages
        self.option_buy_sl_pct:     float = float(risk_cfg.get("option_buy_sl_pct",     0.30))
        self.option_buy_target_pct: float = float(risk_cfg.get("option_buy_target_pct", 0.60))
        self.option_sell_sl_pct:    float = float(risk_cfg.get("option_sell_sl_pct",    0.50))

        # Trailing SL
        self.trailing_sl_trigger_pct: float = float(
            risk_cfg.get("trailing_sl_trigger_pct", 0.20)
        )
        self.trailing_sl_pct: float = float(risk_cfg.get("trailing_sl_pct", 0.10))

        # Position limits
        self.max_positions: int = int(
            trading_cfg.get("max_simultaneous_positions", 3)
        )

        # No-new-trades cut-off time (IST)
        no_new_str: str = trading_cfg.get("no_new_trades_after", "15:00")
        _h, _m = map(int, no_new_str.split(":"))
        self.no_new_trades_after: time = time(_h, _m)

        # Square-off time
        sq_str: str = trading_cfg.get("square_off_time", "15:20")
        _sqh, _sqm = map(int, sq_str.split(":"))
        self.square_off_time: time = time(_sqh, _sqm)

        # Lot size
        self.lot_size: int = int(trading_cfg.get("lot_size", 50))

        # Runtime tracking — updated externally by PositionManager / OrderManager
        self._peak_daily_pnl: float = 0.0   # tracks high-water mark for trailing SL

        logger.info(
            f"[RiskManager] Initialised — capital=₹{self.total_capital:,.0f}, "
            f"daily_loss_limit=₹{self.daily_loss_limit:,.0f}, "
            f"daily_profit_target=₹{self.daily_profit_target:,.0f}, "
            f"per_trade_risk=₹{self.per_trade_risk_amount:,.0f}, "
            f"max_positions={self.max_positions}, "
            f"no_new_trades_after={self.no_new_trades_after.strftime('%H:%M')}"
        )

    # ------------------------------------------------------------------
    # Gate: can we place a new trade?
    # ------------------------------------------------------------------

    def can_place_trade(
        self,
        positions: list[dict],
        daily_pnl: float,
        signal: TradeSignal,
    ) -> tuple[bool, str]:
        """
        Run all pre-trade risk checks.

        Parameters
        ----------
        positions  : current open position list (each entry is a dict from
                     PositionManager.get_open_positions()).
        daily_pnl  : today's realised + unrealised P&L in rupees.
        signal     : the TradeSignal about to be executed.

        Returns
        -------
        (can_trade: bool, reason: str)
            reason is empty string when can_trade is True.
        """
        # ---- 1. Daily loss limit ----
        if daily_pnl <= -abs(self.daily_loss_limit):
            msg = (
                f"Daily loss limit hit: P&L=₹{daily_pnl:,.2f} ≤ "
                f"-₹{self.daily_loss_limit:,.2f}"
            )
            logger.warning(f"[RiskManager] BLOCK — {msg}")
            return False, msg

        # ---- 2. Daily profit target — halt new entries once booked ----
        if daily_pnl >= self.daily_profit_target:
            msg = (
                f"Daily profit target reached: P&L=₹{daily_pnl:,.2f} ≥ "
                f"₹{self.daily_profit_target:,.2f}. No new entries."
            )
            logger.info(f"[RiskManager] BLOCK — {msg}")
            return False, msg

        # ---- 3. Max simultaneous positions ----
        open_count = len(positions)
        if open_count >= self.max_positions:
            msg = (
                f"Max positions reached: {open_count}/{self.max_positions} open"
            )
            logger.warning(f"[RiskManager] BLOCK — {msg}")
            return False, msg

        # ---- 4. Time gate ----
        now_ist  = datetime.now(IST).time().replace(second=0, microsecond=0)
        if now_ist >= self.no_new_trades_after:
            msg = (
                f"Past no-new-trades cut-off "
                f"({now_ist.strftime('%H:%M')} ≥ "
                f"{self.no_new_trades_after.strftime('%H:%M')})"
            )
            logger.info(f"[RiskManager] BLOCK — {msg}")
            return False, msg

        # ---- 5. Signal sanity ----
        if signal.action == "NO_TRADE":
            return False, "Signal action is NO_TRADE"

        if signal.qty <= 0:
            return False, f"Invalid signal qty: {signal.qty}"

        logger.debug(
            f"[RiskManager] Trade approved: {signal.action} {signal.symbol} "
            f"qty={signal.qty} | open_positions={open_count}, "
            f"daily_pnl=₹{daily_pnl:,.2f}"
        )
        return True, ""

    # ------------------------------------------------------------------
    # Position sizing
    # ------------------------------------------------------------------

    def calculate_position_size(
        self,
        signal: TradeSignal,
        available_capital: float,
        current_pnl: float,
    ) -> int:
        """
        Compute the number of lots to trade.

        Method: fixed-fraction risk sizing.
            risk_amount = min(per_trade_risk_amount, available_capital * per_trade_risk_pct)
            max_loss_per_lot = entry_premium * sl_pct * lot_size
            lots = floor(risk_amount / max_loss_per_lot)
            Capped at max_lots_per_trade from config.

        Parameters
        ----------
        signal            : TradeSignal to be executed.
        available_capital : current available margin / funds in rupees.
        current_pnl       : today's running P&L (used to reduce sizing when
                            already in drawdown).

        Returns
        -------
        int  number of lots (≥ 1).
        """
        max_lots = int(self.config.get("trading", {}).get("max_lots_per_trade", 2))

        # CRITICAL FIX: No magic fallback. If price is missing, we cannot size the position.
        if signal.price <= 0:
            logger.error(
                f"[RiskManager] Cannot size position for {signal.symbol} — "
                f"signal.price is missing or zero. Trade refused. "
                f"(Previously would have used ₹50.0 fallback — this is now an error.)"
            )
            return 0  # Signal refusal by returning 0 lots

        premium = signal.price

        # Determine SL percentage based on direction
        if signal.transaction_type == "SELL":
            sl_pct = self.option_sell_sl_pct
        else:
            sl_pct = self.option_buy_sl_pct

        max_loss_per_lot = premium * sl_pct * self.lot_size
        if max_loss_per_lot <= 0:
            logger.warning(
                "[RiskManager] Cannot calculate position size — "
                "max_loss_per_lot is zero; defaulting to 1 lot"
            )
            return 1

        # Scale down risk amount if already in drawdown
        drawdown_adj = 1.0
        if current_pnl < 0:
            drawdown_fraction = abs(current_pnl) / self.daily_loss_limit
            drawdown_adj = max(1.0 - drawdown_fraction, 0.25)  # floor at 25 %

        effective_risk = self.per_trade_risk_amount * drawdown_adj
        # Also cap by available capital (can't risk more than we have)
        effective_risk = min(effective_risk, available_capital * self.per_trade_risk_pct)

        raw_lots = int(effective_risk / max_loss_per_lot)
        lots     = max(1, min(raw_lots, max_lots))

        logger.debug(
            f"[RiskManager] Position size: premium={premium:.2f}, "
            f"sl_pct={sl_pct:.2f}, max_loss/lot=₹{max_loss_per_lot:.2f}, "
            f"effective_risk=₹{effective_risk:.2f}, raw_lots={raw_lots}, "
            f"final_lots={lots}"
        )
        return lots

    # ------------------------------------------------------------------
    # SL / Target calculation
    # ------------------------------------------------------------------

    def calculate_sl_and_target(
        self,
        signal: TradeSignal,
        premium: float,
        spot_price: float,
    ) -> tuple[float, float]:
        """
        Compute stop-loss and target prices for an options position.

        For bought options (long premium):
            sl     = premium × (1 − sl_pct)
            target = premium × (1 + target_pct)

        For sold options (short premium / credit):
            sl     = premium × (1 + sl_pct)   [premium expands → loss]
            target = premium × (1 − target_pct) [premium decays → profit]

        Parameters
        ----------
        signal      : TradeSignal (uses transaction_type to determine direction).
        premium     : actual fill / LTP of the option in rupees.
        spot_price  : underlying spot price (reserved for future extensions
                      such as delta-based SL).

        Returns
        -------
        (sl_price, target_price)
        """
        if premium <= 0:
            logger.warning(
                "[RiskManager] premium ≤ 0 in calculate_sl_and_target; "
                "returning signal's built-in sl/target"
            )
            return signal.sl_price, signal.target_price

        if signal.transaction_type == "SELL":
            sl_price     = round(premium * (1.0 + self.option_sell_sl_pct),    2)
            target_price = round(premium * (1.0 - self.option_buy_target_pct), 2)
            target_price = max(target_price, 0.05)   # floor at 5 paisa
        else:
            sl_price     = round(premium * (1.0 - self.option_buy_sl_pct),     2)
            target_price = round(premium * (1.0 + self.option_buy_target_pct), 2)
            sl_price     = max(sl_price, 0.05)

        logger.debug(
            f"[RiskManager] SL/Target for {signal.symbol}: "
            f"premium={premium:.2f}, sl={sl_price:.2f}, target={target_price:.2f}"
        )
        return sl_price, target_price

    # ------------------------------------------------------------------
    # EOD / risk-breach square-off
    # ------------------------------------------------------------------

    def should_square_off_all(
        self,
        current_time: Optional[datetime],
        daily_pnl: float,
    ) -> bool:
        """
        Determine whether all open positions must be squared off immediately.

        Triggers:
        1. Current IST time ≥ square_off_time (15:20).
        2. Daily loss limit has been hit.
        3. Daily profit target has been hit (lock in profits).

        Parameters
        ----------
        current_time : datetime (timezone-aware or naive).  If None, uses now().
        daily_pnl    : today's combined realised + unrealised P&L in rupees.

        Returns
        -------
        bool
        """
        if current_time is None:
            current_time = datetime.now(IST)
        elif current_time.tzinfo is None:
            current_time = IST.localize(current_time)

        now_time = current_time.time().replace(second=0, microsecond=0)

        # ---- Time trigger ----
        if now_time >= self.square_off_time:
            logger.info(
                f"[RiskManager] Square-off triggered: time "
                f"{now_time.strftime('%H:%M')} ≥ {self.square_off_time.strftime('%H:%M')}"
            )
            return True

        # ---- Loss limit ----
        if daily_pnl <= -abs(self.daily_loss_limit):
            logger.warning(
                f"[RiskManager] Square-off triggered: daily loss "
                f"₹{daily_pnl:,.2f} ≤ -₹{self.daily_loss_limit:,.2f}"
            )
            return True

        # ---- Profit target ----
        if daily_pnl >= self.daily_profit_target:
            logger.info(
                f"[RiskManager] Square-off triggered: daily profit "
                f"₹{daily_pnl:,.2f} ≥ ₹{self.daily_profit_target:,.2f}"
            )
            return True

        return False

    # ------------------------------------------------------------------
    # Trailing stop-loss
    # ------------------------------------------------------------------

    def update_trailing_sl(
        self,
        position: dict,
        current_price: float,
    ) -> dict:
        """
        Adjust the stop-loss upward if the position is profitable enough.

        Logic (for bought options):
            • Activate trailing when current_price ≥ entry × (1 + trigger_pct)
            • New SL = max(existing SL, current_price × (1 - trail_pct))

        For sold options:
            • Activate when current_price ≤ entry × (1 - trigger_pct) [price fell = profit]
            • New SL = min(existing SL, current_price × (1 + trail_pct))

        Parameters
        ----------
        position      : dict from PositionManager (modified in-place and returned).
        current_price : current LTP of the option.

        Returns
        -------
        dict  position dict with potentially updated 'sl_price'.
        """
        entry_price: float = float(position.get("entry_price", 0.0))
        current_sl:  float = float(position.get("sl_price",    0.0))
        direction:   str   = position.get("direction",  "CE")
        tx_type:     str   = position.get("transaction_type", "BUY")
        symbol:      str   = position.get("symbol", "")

        if entry_price <= 0 or current_price <= 0:
            return position

        if tx_type == "SELL":
            # Sold option — profit = entry_price - current_price
            profit_pct = (entry_price - current_price) / entry_price
            if profit_pct >= self.trailing_sl_trigger_pct:
                new_sl = round(current_price * (1.0 + self.trailing_sl_pct), 2)
                # For SELL, SL moves DOWN as price falls (tighter ceiling)
                if current_sl == 0 or new_sl < current_sl:
                    position["sl_price"] = new_sl
                    logger.debug(
                        f"[RiskManager] Trailing SL updated (SELL) for {symbol}: "
                        f"{current_sl:.2f} → {new_sl:.2f}"
                    )
        else:
            # Bought option — profit = current_price - entry_price
            profit_pct = (current_price - entry_price) / entry_price
            if profit_pct >= self.trailing_sl_trigger_pct:
                new_sl = round(current_price * (1.0 - self.trailing_sl_pct), 2)
                # SL moves UP as price rises
                if current_sl == 0 or new_sl > current_sl:
                    position["sl_price"] = new_sl
                    logger.debug(
                        f"[RiskManager] Trailing SL updated (BUY) for {symbol}: "
                        f"{current_sl:.2f} → {new_sl:.2f}"
                    )

        return position

    # ------------------------------------------------------------------
    # Risk report
    # ------------------------------------------------------------------

    def get_risk_report(
        self,
        positions: Optional[list[dict]] = None,
        daily_pnl: float = 0.0,
        realized_pnl: float = 0.0,
    ) -> dict:
        """
        Build a snapshot of current risk metrics.

        Parameters
        ----------
        positions    : current open positions list (from PositionManager).
        daily_pnl    : combined realised + unrealised P&L today.
        realized_pnl : only realised (closed) P&L today.

        Returns
        -------
        dict with keys:
            total_capital, daily_loss_limit, daily_profit_target,
            daily_pnl, realized_pnl, unrealized_pnl,
            daily_pnl_pct, loss_limit_used_pct, profit_target_pct,
            open_positions, max_positions, positions_used_pct,
            can_trade, no_new_trades_after, square_off_time,
            per_trade_risk, per_trade_risk_pct,
            trailing_sl_trigger_pct, trailing_sl_pct
        """
        positions       = positions or []
        open_count      = len(positions)
        unrealized_pnl  = daily_pnl - realized_pnl

        daily_pnl_pct       = daily_pnl / self.total_capital * 100.0
        loss_limit_used_pct = (
            abs(daily_pnl) / self.daily_loss_limit * 100.0
            if daily_pnl < 0
            else 0.0
        )
        profit_target_pct = (
            daily_pnl / self.daily_profit_target * 100.0
            if daily_pnl > 0
            else 0.0
        )
        positions_used_pct = open_count / self.max_positions * 100.0

        now_ist = datetime.now(IST)
        now_time = now_ist.time().replace(second=0, microsecond=0)
        can_trade = (
            daily_pnl > -abs(self.daily_loss_limit)
            and daily_pnl < self.daily_profit_target
            and open_count < self.max_positions
            and now_time < self.no_new_trades_after
        )

        report = {
            "timestamp":             now_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
            "total_capital":         self.total_capital,
            "daily_loss_limit":      -abs(self.daily_loss_limit),
            "daily_profit_target":   self.daily_profit_target,
            "daily_pnl":             round(daily_pnl, 2),
            "realized_pnl":          round(realized_pnl, 2),
            "unrealized_pnl":        round(unrealized_pnl, 2),
            "daily_pnl_pct":         round(daily_pnl_pct, 3),
            "loss_limit_used_pct":   round(loss_limit_used_pct, 2),
            "profit_target_pct":     round(profit_target_pct, 2),
            "open_positions":        open_count,
            "max_positions":         self.max_positions,
            "positions_used_pct":    round(positions_used_pct, 2),
            "can_trade":             can_trade,
            "no_new_trades_after":   self.no_new_trades_after.strftime("%H:%M"),
            "square_off_time":       self.square_off_time.strftime("%H:%M"),
            "per_trade_risk":        round(self.per_trade_risk_amount, 2),
            "per_trade_risk_pct":    self.per_trade_risk_pct * 100.0,
            "trailing_sl_trigger":   self.trailing_sl_trigger_pct * 100.0,
            "trailing_sl_pct":       self.trailing_sl_pct * 100.0,
        }

        logger.debug(f"[RiskManager] Risk report: {report}")
        return report
