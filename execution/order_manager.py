"""
Order Manager for Nifty50 Intraday Options Trading System.

Bridges strategy signals and the Angel One SmartAPI.  Supports a
paper-trading mode that simulates fills without touching live markets.

Responsibilities
----------------
• execute_signal()     — place entry orders from a TradeSignal
• exit_position()      — place exit order for one open position
• exit_all_positions() — square off everything (EOD / risk breach)
• get_open_positions() — internal book view of open positions
• sync_positions()     — reconcile internal book with broker state
• _place_order()       — raw order routing (live or paper)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pytz
from loguru import logger

from strategies.base_strategy import TradeSignal

IST = pytz.timezone("Asia/Kolkata")


# ---------------------------------------------------------------------------
# Internal position record
# ---------------------------------------------------------------------------

@dataclass
class PositionInfo:
    """Lightweight order-book entry maintained by OrderManager."""
    order_id:         str
    symbol:           str
    token:            str
    exchange:         str
    entry_price:      float
    current_price:    float
    qty:              int
    lots:             int
    direction:        str            # option_type: "CE" or "PE"
    transaction_type: str            # "BUY" or "SELL"
    sl_price:         float
    target_price:     float
    entry_time:       datetime
    exit_time:        Optional[datetime]
    strategy:         str
    regime:           str
    status:           str            # "OPEN" | "CLOSED" | "PENDING"
    action:           str            # original signal action string
    exit_price:       float = 0.0
    exit_reason:      str   = ""
    unrealized_pnl:   float = 0.0
    realized_pnl:     float = 0.0
    is_paper:         bool  = False
    # Multi-leg support (straddle / strangle)
    leg2_order_id:    str   = ""
    leg2_symbol:      str   = ""
    leg2_token:       str   = ""
    leg2_entry_price: float = 0.0
    leg2_exit_price:  float = 0.0


# ---------------------------------------------------------------------------
# Order Manager
# ---------------------------------------------------------------------------

class OrderManager:
    """
    Manages order lifecycle for the options trading system.

    Parameters
    ----------
    client        : AngelOneClient — authenticated broker client.
    risk_manager  : RiskManager   — pre-trade risk gate.
    config        : dict          — full app config.
    paper_trading : bool          — if True, simulate fills without live orders.
    """

    def __init__(
        self,
        client,
        risk_manager,
        config: dict,
        paper_trading: bool = False,
    ) -> None:
        self.client        = client
        self.risk_manager  = risk_manager
        self.config        = config
        self.paper_trading = paper_trading

        trading_cfg        = config.get("trading", {})
        self.lot_size: int = int(trading_cfg.get("lot_size", 50))

        # Internal position book:  {order_id: PositionInfo}
        self._positions: dict[str, PositionInfo] = {}

        mode = "PAPER TRADING" if paper_trading else "LIVE TRADING"
        logger.info(f"[OrderManager] Initialised — mode={mode}")
        if paper_trading:
            logger.warning(
                "[OrderManager] Paper-trading mode active — no real orders will be placed."
            )

    # ------------------------------------------------------------------
    # Execute a new trade signal
    # ------------------------------------------------------------------

    def execute_signal(
        self,
        signal: TradeSignal,
        available_capital: float = 0.0,
        daily_pnl: float = 0.0,
        regime: str = "unknown",
    ) -> Optional[str]:
        """
        Translate a TradeSignal into one or two broker orders.

        For SELL_STRADDLE / SELL_STRANGLE signals the method places two
        legs (CE + PE sell) atomically.  The PE leg metadata must be
        attached to the signal as dynamic attributes by the strategy:
            signal.pe_symbol, signal.pe_token, signal.pe_premium.

        Parameters
        ----------
        signal            : TradeSignal from any strategy.
        available_capital : current available margin in rupees.
        daily_pnl         : today's running P&L for drawdown-adjusted sizing.
        regime            : market regime label recorded in the position book.

        Returns
        -------
        str   order_id of the primary leg on success.
        None  if the risk gate blocked the trade or an error occurred.
        """
        if signal.action in ("NO_TRADE", "EXIT"):
            logger.debug(
                f"[OrderManager] Skipping non-actionable signal: {signal.action}"
            )
            return None

        # ---- Hard rule: never open a short (written) options position ----
        # CRITICAL: This block prevents naked option sales. Removing it requires atomic leg placement
        # with full rollback logic for leg-2 failures. See order_manager.py:284-287 for the current gap.
        # DO NOT REMOVE without implementing automatic leg-1 exit if leg-2 fails to fill.
        _is_sell_entry = (
            signal.action in ("SELL_STRADDLE", "SELL_STRANGLE")
            or (
                getattr(signal, "transaction_type", "BUY") == "SELL"
                and getattr(signal, "exchange", "") in ("NFO", "BFO")
            )
        )
        if _is_sell_entry:
            logger.warning(
                f"[OrderManager] Trade blocked — option selling is strictly disabled. "
                f"Signal: {signal.action} ({getattr(signal, 'transaction_type', '?')} "
                f"{signal.symbol})"
            )
            return None

        # ---- Risk gate ----
        open_positions = self.get_open_positions()
        can_trade, block_reason = self.risk_manager.can_place_trade(
            open_positions, daily_pnl, signal
        )
        if not can_trade:
            logger.warning(
                f"[OrderManager] Trade blocked by RiskManager: {block_reason}"
            )
            return None

        # ---- Position sizing ----
        lots = self.risk_manager.calculate_position_size(
            signal, available_capital, daily_pnl
        )
        if lots <= 0:
            logger.warning(
                f"[OrderManager] RiskManager refused to size position for {signal.symbol}. "
                f"Trade rejected."
            )
            return None
        qty = lots * self.lot_size

        # ---- Determine fill price ----
        fill_price = self._get_fill_price(
            symbol     = signal.symbol,
            token      = signal.token,
            exchange   = signal.exchange,
            order_type = signal.order_type,
            limit_price= signal.price,
        )

        if fill_price is None:
            logger.warning(
                f"[OrderManager] Cannot determine fill price for {signal.symbol}. "
                f"Trade refused."
            )
            return None

        # ---- Live-only: verify actual cash balance before placing order ----
        if not self.paper_trading:
            required_cash = fill_price * qty
            available_cash = self._get_available_cash()
            if available_cash < required_cash:
                logger.warning(
                    f"[OrderManager] Insufficient funds: need ₹{required_cash:,.0f} "
                    f"to buy {qty}x {signal.symbol} @ ₹{fill_price:.2f}, "
                    f"but only ₹{available_cash:,.0f} cash available. Trade skipped."
                )
                return None
            logger.debug(
                f"[OrderManager] Fund check passed: ₹{available_cash:,.0f} available, "
                f"₹{required_cash:,.0f} required."
            )

        # ---- SL / target from RiskManager ----
        sl_price, target_price = self.risk_manager.calculate_sl_and_target(
            signal      = signal,
            premium     = fill_price,
            spot_price  = 0.0,
        )

        # ---- Place primary order ----
        order_id = self._place_order(
            symbol           = signal.symbol,
            token            = signal.token,
            exchange         = signal.exchange,
            qty              = qty,
            transaction_type = signal.transaction_type,
            order_type       = signal.order_type,
            price            = fill_price if signal.order_type == "LIMIT" else 0.0,
        )
        if order_id is None:
            return None

        # ---- Record primary leg ----
        now_ist = datetime.now(IST)
        pos = PositionInfo(
            order_id         = order_id,
            symbol           = signal.symbol,
            token            = signal.token,
            exchange         = signal.exchange,
            entry_price      = fill_price,
            current_price    = fill_price,
            qty              = qty,
            lots             = lots,
            direction        = signal.option_type,
            transaction_type = signal.transaction_type,
            sl_price         = sl_price,
            target_price     = target_price,
            entry_time       = now_ist,
            exit_time        = None,
            strategy         = signal.strategy_name,
            regime           = regime,
            status           = "OPEN",
            action           = signal.action,
            is_paper         = self.paper_trading,
        )
        self._positions[order_id] = pos

        logger.info(
            f"[OrderManager] Position opened: order_id={order_id} "
            f"symbol={signal.symbol} qty={qty} fill=₹{fill_price:.2f} "
            f"SL=₹{sl_price:.2f} target=₹{target_price:.2f}"
        )

        # ---- Handle multi-leg signals (SELL_STRADDLE / SELL_STRANGLE) ----
        if signal.action in ("SELL_STRADDLE", "SELL_STRANGLE"):
            pe_symbol  = getattr(signal, "pe_symbol",  "")
            pe_token   = getattr(signal, "pe_token",   "0")
            pe_premium = getattr(signal, "pe_premium", fill_price)

            if pe_symbol:
                leg2_fill = (
                    pe_premium if self.paper_trading
                    else self._get_fill_price(
                        symbol     = pe_symbol,
                        token      = pe_token,
                        exchange   = "NFO",
                        order_type = "MARKET",
                        limit_price= 0.0,
                    )
                )
                leg2_order_id = self._place_order(
                    symbol           = pe_symbol,
                    token            = pe_token,
                    exchange         = "NFO",
                    qty              = qty,
                    transaction_type = "SELL",
                    order_type       = "MARKET",
                    price            = 0.0,
                )
                if leg2_order_id:
                    pos.leg2_order_id    = leg2_order_id
                    pos.leg2_symbol      = pe_symbol
                    pos.leg2_token       = pe_token
                    pos.leg2_entry_price = leg2_fill
                    logger.info(
                        f"[OrderManager] Leg-2 placed: order_id={leg2_order_id} "
                        f"symbol={pe_symbol} fill=₹{leg2_fill:.2f}"
                    )
                else:
                    # CRITICAL: Leg-2 failed to fill. Immediately exit leg-1 to avoid naked short.
                    logger.error(
                        f"[OrderManager] LEG-2 FAILURE — {pe_symbol} failed to fill. "
                        f"Exiting leg-1 ({signal.symbol}) immediately to prevent naked option position."
                    )
                    self.exit_position(
                        {"order_id": order_id, "symbol": signal.symbol, "token": signal.token,
                         "exchange": signal.exchange, "qty": qty, "transaction_type": signal.transaction_type},
                        reason="Emergency exit — leg-2 fill failure"
                    )
                    # Mark the position as having failed leg-2, so the loop doesn't try to manage it
                    if order_id in self._positions:
                        pos.status = "CLOSED"
                        pos.exit_reason = "Leg-2 failed; emergency close"
                    return None

        return order_id

    # ------------------------------------------------------------------
    # Exit a single position
    # ------------------------------------------------------------------

    def exit_position(
        self,
        position: dict,
        reason: str = "Manual exit",
    ) -> Optional[str]:
        """
        Square off a single open position.

        Parameters
        ----------
        position : dict with keys: order_id, symbol, token, exchange,
                   qty, transaction_type, and optionally leg2_* keys.
        reason   : human-readable exit reason recorded in the book.

        Returns
        -------
        str   exit order_id on success, None on failure.
        """
        order_id      = str(position.get("order_id",         ""))
        symbol        = str(position.get("symbol",           ""))
        token         = str(position.get("token",            ""))
        exchange      = str(position.get("exchange",         "NFO"))
        qty           = int(position.get("qty",              0))
        tx_type       = str(position.get("transaction_type", "BUY"))
        leg2_order_id = str(position.get("leg2_order_id",    ""))
        leg2_symbol   = str(position.get("leg2_symbol",      ""))
        leg2_token    = str(position.get("leg2_token",       ""))

        if qty <= 0 or not symbol:
            logger.error(
                f"[OrderManager] exit_position: invalid position data — {position}"
            )
            return None

        # Reverse transaction type for closing
        exit_tx = "SELL" if tx_type == "BUY" else "BUY"

        # Current LTP for recording exit price
        exit_price = self._get_fill_price(
            symbol=symbol, token=token, exchange=exchange,
            order_type="MARKET", limit_price=0.0,
        )

        # Place exit order
        exit_order_id = self._place_order(
            symbol           = symbol,
            token            = token,
            exchange         = exchange,
            qty              = qty,
            transaction_type = exit_tx,
            order_type       = "MARKET",
            price            = 0.0,
        )

        if exit_order_id and order_id in self._positions:
            pos = self._positions[order_id]
            pos.status      = "CLOSED"
            pos.exit_time   = datetime.now(IST)
            pos.exit_price  = exit_price
            pos.exit_reason = reason
            if pos.transaction_type == "BUY":
                pos.realized_pnl = (exit_price - pos.entry_price) * qty
            else:
                pos.realized_pnl = (pos.entry_price - exit_price) * qty
            pos.unrealized_pnl = 0.0
            logger.info(
                f"[OrderManager] Position closed: order_id={order_id} "
                f"exit_order={exit_order_id} exit_price=₹{exit_price:.2f} "
                f"P&L=₹{pos.realized_pnl:.2f} reason='{reason}'"
            )

        # Exit leg-2 if present (straddle / strangle)
        if leg2_symbol and leg2_order_id:
            leg2_exit_price = self._get_fill_price(
                symbol=leg2_symbol, token=leg2_token, exchange="NFO",
                order_type="MARKET", limit_price=0.0,
            )
            leg2_exit_id = self._place_order(
                symbol           = leg2_symbol,
                token            = leg2_token,
                exchange         = "NFO",
                qty              = qty,
                transaction_type = "BUY",     # leg-2 was always SELL
                order_type       = "MARKET",
                price            = 0.0,
            )
            if leg2_exit_id and order_id in self._positions:
                self._positions[order_id].leg2_exit_price = leg2_exit_price
                logger.info(
                    f"[OrderManager] Leg-2 closed: exit_order={leg2_exit_id} "
                    f"symbol={leg2_symbol} exit_price=₹{leg2_exit_price:.2f}"
                )

        return exit_order_id

    # ------------------------------------------------------------------
    # Exit all open positions
    # ------------------------------------------------------------------

    def exit_all_positions(self, reason: str = "Square-off all") -> list[str]:
        """
        Square off every open position tracked in the internal book.

        Parameters
        ----------
        reason : reason string recorded against each exit.

        Returns
        -------
        list[str]  list of exit order IDs placed successfully.
        """
        open_positions = self.get_open_positions()
        if not open_positions:
            logger.info("[OrderManager] exit_all_positions: no open positions to exit.")
            return []

        logger.warning(
            f"[OrderManager] Squaring off {len(open_positions)} position(s) "
            f"— reason: {reason}"
        )
        exit_ids: list[str] = []
        for pos_dict in open_positions:
            eid = self.exit_position(pos_dict, reason=reason)
            if eid:
                exit_ids.append(eid)
            time.sleep(0.25)   # avoid broker rate-limit

        logger.info(f"[OrderManager] Bulk exit complete. Orders placed: {exit_ids}")
        return exit_ids

    # ------------------------------------------------------------------
    # Position queries
    # ------------------------------------------------------------------

    def get_open_positions(self) -> list[dict]:
        """
        Return all currently open positions as a list of plain dicts.

        The internal book is the source of truth; call sync_positions()
        periodically to reconcile with the broker.
        """
        return [
            self._position_to_dict(pos)
            for pos in self._positions.values()
            if pos.status == "OPEN"
        ]

    def get_all_positions(self) -> list[dict]:
        """Return every position (open + closed) from the internal book."""
        return [self._position_to_dict(p) for p in self._positions.values()]

    def get_position_by_order_id(self, order_id: str) -> Optional[PositionInfo]:
        """Return the raw PositionInfo dataclass for a given order_id."""
        return self._positions.get(order_id)

    def sync_positions(self) -> None:
        """
        Reconcile the internal position book with the broker's live positions.

        • Internal OPEN positions absent from the broker are marked CLOSED
          (externally squared off or filled OTM at expiry).
        • Broker positions not found internally are logged as warnings.

        In paper-trading mode this is a no-op.
        """
        if self.paper_trading:
            logger.debug("[OrderManager] sync_positions: skipped in paper mode.")
            return

        try:
            broker_positions = self.client.get_positions()
        except Exception as exc:
            logger.error(f"[OrderManager] sync_positions: broker API error — {exc}")
            return

        # Build a set of symbols with non-zero net qty at the broker
        broker_symbols: dict[str, dict] = {
            str(p.get("tradingsymbol", "")): p
            for p in broker_positions
            if int(p.get("netqty", 0)) != 0
        }

        # Internal symbols that are currently open
        for order_id, pos in list(self._positions.items()):
            if pos.status != "OPEN":
                continue
            if pos.symbol not in broker_symbols:
                logger.warning(
                    f"[OrderManager] sync: {pos.symbol} absent from broker — "
                    "marking CLOSED (externally squared off)"
                )
                pos.status      = "CLOSED"
                pos.exit_time   = datetime.now(IST)
                pos.exit_reason = "External square-off detected via sync"

        # Log broker positions not in the internal book
        internal_open_symbols = {
            pos.symbol
            for pos in self._positions.values()
            if pos.status == "OPEN"
        }
        for sym in broker_symbols:
            if sym not in internal_open_symbols:
                logger.warning(
                    f"[OrderManager] sync: untracked broker position "
                    f"symbol={sym} qty={broker_symbols[sym].get('netqty')}"
                )

        logger.info(
            f"[OrderManager] sync_positions complete — "
            f"{len(broker_symbols)} broker pos, "
            f"{len(self.get_open_positions())} internal open pos"
        )

    # ------------------------------------------------------------------
    # Price update helper (called by PositionManager tick loop)
    # ------------------------------------------------------------------

    def update_position_price(self, order_id: str, current_ltp: float) -> None:
        """Update current_price and unrealized_pnl for an open position."""
        pos = self._positions.get(order_id)
        if pos is None or pos.status != "OPEN":
            return
        pos.current_price  = current_ltp
        multiplier         = 1 if pos.transaction_type == "BUY" else -1
        pos.unrealized_pnl = multiplier * (current_ltp - pos.entry_price) * pos.qty

    # ------------------------------------------------------------------
    # Raw order placement
    # ------------------------------------------------------------------

    def _get_available_cash(self) -> float:
        """Fetch actual deposited cash balance from Angel One (never margin).

        Returns 0.0 on any error so the caller can safely block the trade.
        """
        if not self.client:
            return 0.0
        try:
            funds = self.client.get_funds()
            # 'availablecash' = deposited cash credited to the account.
            # 'net' = net free balance after all utilisations.
            # We take the lower of the two to be conservative.
            cash   = float(funds.get("availablecash") or 0)
            net    = float(funds.get("net")           or 0)
            result = min(cash, net) if (cash > 0 and net > 0) else max(cash, net)
            logger.debug(f"[OrderManager] Fund balance — availablecash=₹{cash:,.0f}, net=₹{net:,.0f}")
            return result
        except Exception as exc:
            logger.warning(
                f"[OrderManager] Could not fetch fund balance: {exc}. "
                "Blocking trade as a safety measure."
            )
            return 0.0

    def _place_order(
        self,
        symbol:           str,
        token:            str,
        exchange:         str,
        qty:              int,
        transaction_type: str,
        order_type:       str,
        price:            float = 0.0,
        trigger_price:    float = 0.0,
        product:          str   = "INTRADAY",
        variety:          str   = "NORMAL",
    ) -> Optional[str]:
        """
        Route an order to the broker (live) or the paper simulator.

        Returns
        -------
        str   order_id on success, None on failure.
        """
        if self.paper_trading:
            return self._simulate_order(
                symbol           = symbol,
                token            = token,
                exchange         = exchange,
                qty              = qty,
                transaction_type = transaction_type,
                order_type       = order_type,
                price            = price,
            )

        # ---- Live order with 3-attempt retry ----
        for attempt in range(1, 4):
            try:
                order_id = self.client.place_order(
                    variety          = variety,
                    exchange         = exchange,
                    symbol           = symbol,
                    token            = token,
                    qty              = qty,
                    order_type       = order_type,
                    transaction_type = transaction_type,
                    price            = price if order_type == "LIMIT" else 0.0,
                    trigger_price    = trigger_price,
                    product          = product,
                )
                logger.info(
                    f"[OrderManager] Live order placed: {transaction_type} {qty}x "
                    f"{symbol} @ ₹{price:.2f} [{order_type}] → order_id={order_id}"
                )
                return order_id
            except Exception as exc:
                wait = 2 ** (attempt - 1)
                logger.warning(
                    f"[OrderManager] Order attempt {attempt}/3 failed for "
                    f"{symbol}: {exc}. Retrying in {wait}s…"
                )
                time.sleep(wait)

        logger.error(f"[OrderManager] All order attempts failed for {symbol}")
        return None

    def _simulate_order(
        self,
        symbol:           str,
        token:            str,
        exchange:         str,
        qty:              int,
        transaction_type: str,
        order_type:       str,
        price:            float,
    ) -> Optional[str]:
        """Simulate a paper-trading fill and return a synthetic order_id.

        CRITICAL FIX: No longer invents prices. If price unavailable, refuses the trade
        instead of using a magic ₹50 fallback.
        """
        order_id = f"PAPER-{uuid.uuid4().hex[:10].upper()}"
        fill = price if price > 0 else self._get_ltp_safe(token, exchange, symbol)

        if fill <= 0:
            logger.error(
                f"[OrderManager][PAPER] Cannot simulate fill for {symbol} — "
                f"no price provided and LTP unavailable. Trade refused (was silently "
                f"using ₹50.0 fallback — this is now an error). Check broker connectivity."
            )
            return None

        logger.info(
            f"[OrderManager][PAPER] Simulated {transaction_type} {qty}x "
            f"{symbol} @ ₹{fill:.2f} [{order_type}] → {order_id}"
        )
        return order_id

    # ------------------------------------------------------------------
    # Fill price helpers
    # ------------------------------------------------------------------

    def _get_fill_price(
        self,
        symbol:      str,
        token:       str,
        exchange:    str,
        order_type:  str,
        limit_price: float,
    ) -> Optional[float]:
        """
        Determine the expected fill price for an order.

        LIMIT  → limit_price (required for LIMIT orders).
        MARKET → live LTP from broker (or limit_price as fallback).

        CRITICAL FIX: Returns None if price is unavailable instead of inventing ₹50.
        Caller must handle None (refuse the trade).
        """
        if order_type == "LIMIT":
            if limit_price > 0:
                return limit_price
            # LIMIT order requires a limit price
            logger.error(
                f"[OrderManager] LIMIT order for {symbol} has no limit_price. "
                f"Cannot execute."
            )
            return None

        if self.paper_trading and limit_price > 0:
            return limit_price

        ltp = self._get_ltp_safe(token, exchange, symbol)
        if ltp > 0:
            return ltp

        if limit_price > 0:
            return limit_price

        # All sources exhausted. Return None to signal trade refusal.
        logger.error(
            f"[OrderManager] Could not get fill price for {symbol} — "
            f"no limit price, no LTP available. Trade refused."
        )
        return None

    def _get_ltp_safe(self, token: str, exchange: str, symbol: str) -> float:
        """Fetch LTP without raising; returns 0.0 on error."""
        try:
            ltp = self.client.get_ltp(exchange=exchange, symbol=symbol, token=token)
            return float(ltp) if ltp else 0.0
        except Exception as exc:
            logger.debug(f"[OrderManager] LTP fetch suppressed for {symbol}: {exc}")
            return 0.0

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def _position_to_dict(self, pos: PositionInfo) -> dict:
        """Convert a PositionInfo dataclass to a plain serialisable dict."""
        return {
            "order_id":         pos.order_id,
            "symbol":           pos.symbol,
            "token":            pos.token,
            "exchange":         pos.exchange,
            "entry_price":      pos.entry_price,
            "current_price":    pos.current_price,
            "qty":              pos.qty,
            "lots":             pos.lots,
            "direction":        pos.direction,
            "transaction_type": pos.transaction_type,
            "sl_price":         pos.sl_price,
            "target_price":     pos.target_price,
            "entry_time":       pos.entry_time,
            "exit_time":        pos.exit_time,
            "strategy":         pos.strategy,
            "regime":           pos.regime,
            "status":           pos.status,
            "action":           pos.action,
            "exit_price":       pos.exit_price,
            "exit_reason":      pos.exit_reason,
            "unrealized_pnl":   pos.unrealized_pnl,
            "realized_pnl":     pos.realized_pnl,
            "is_paper":         pos.is_paper,
            "leg2_order_id":    pos.leg2_order_id,
            "leg2_symbol":      pos.leg2_symbol,
            "leg2_token":       pos.leg2_token,
            "leg2_entry_price": pos.leg2_entry_price,
            "leg2_exit_price":  pos.leg2_exit_price,
        }
