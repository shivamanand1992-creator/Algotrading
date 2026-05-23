"""
Order placement and management via Angel One SmartAPI.
Supports both live and paper trading modes.
"""

import time
import uuid
from datetime import datetime
from typing import Optional
import pytz
from loguru import logger

IST = pytz.timezone("Asia/Kolkata")


class OrderManager:
    """
    Handles order entry, exit, and reconciliation with Angel One.
    In paper_trading mode all orders are simulated with current LTP.
    """

    def __init__(self, client, risk_manager, config: dict, paper_trading: bool = False):
        self.client = client
        self.risk_manager = risk_manager
        self.config = config
        self.paper_trading = paper_trading
        self._order_book: dict = {}    # order_id → order details

        if paper_trading:
            logger.warning("OrderManager running in PAPER TRADING mode — no real orders placed")

    # ── Public API ─────────────────────────────────────────────────────────────

    def execute_signal(self, signal) -> Optional[str]:
        """
        Execute a TradeSignal or Signal by placing an order.
        Returns order_id on success, None on failure.
        """
        symbol = getattr(signal, "symbol", "")
        token = getattr(signal, "token", "")
        exchange = getattr(signal, "exchange", "NFO")
        qty = getattr(signal, "qty", self.config["trading"]["lot_size"])
        transaction_type = getattr(signal, "transaction_type", "BUY")
        order_type = getattr(signal, "order_type", "MARKET")
        price = getattr(signal, "price", 0.0)
        action = getattr(signal, "action", "")

        # Map action to transaction type if not set
        if not transaction_type and action:
            transaction_type = "SELL" if action.startswith("SELL") else "BUY"

        if self.paper_trading:
            return self._paper_trade(symbol, token, exchange, qty, transaction_type, price, signal)

        return self._live_order(symbol, token, exchange, qty, transaction_type, order_type, price)

    def exit_position(self, position, reason: str = "") -> Optional[str]:
        """Place exit order for a position (opposite side at market)."""
        exit_side = "SELL" if position.direction == "BUY" else "BUY"
        logger.info(f"Exiting {position.symbol} | Reason: {reason}")

        if self.paper_trading:
            return self._paper_exit(position, reason)

        return self._live_order(
            symbol=position.symbol,
            token=position.token,
            exchange="NFO",
            qty=position.qty,
            transaction_type=exit_side,
            order_type="MARKET",
            price=0,
        )

    def exit_all_positions(self, reason: str = ""):
        """Square off all open positions."""
        try:
            open_positions = self.client.get_positions()
        except Exception as e:
            logger.error(f"Could not fetch positions for square-off: {e}")
            return

        for pos in open_positions:
            if pos.get("netqty", 0) == 0:
                continue
            exit_side = "SELL" if int(pos.get("netqty", 0)) > 0 else "BUY"
            qty = abs(int(pos.get("netqty", 0)))
            try:
                if self.paper_trading:
                    logger.info(f"[PAPER] Square-off {pos.get('tradingsymbol', '')} qty={qty} reason={reason}")
                else:
                    self._live_order(
                        symbol=pos.get("tradingsymbol", ""),
                        token=pos.get("symboltoken", ""),
                        exchange=pos.get("exchange", "NFO"),
                        qty=qty,
                        transaction_type=exit_side,
                        order_type="MARKET",
                        price=0,
                    )
            except Exception as e:
                logger.error(f"Square-off failed for {pos.get('tradingsymbol', '')}: {e}")

    def get_order_status(self, order_id: str) -> dict:
        try:
            return self.client.get_order_status(order_id)
        except Exception as e:
            logger.warning(f"Order status check failed: {e}")
            return {}

    def sync_positions(self):
        """Reconcile internal order book with broker positions."""
        try:
            broker_positions = self.client.get_positions()
            logger.debug(f"Broker positions: {len(broker_positions)}")
        except Exception as e:
            logger.warning(f"Position sync failed: {e}")

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _live_order(
        self, symbol: str, token: str, exchange: str, qty: int,
        transaction_type: str, order_type: str, price: float
    ) -> Optional[str]:
        for attempt in range(3):
            try:
                order_id = self.client.place_order(
                    variety="NORMAL",
                    exchange=exchange,
                    symbol=symbol,
                    token=token,
                    qty=qty,
                    order_type=order_type,
                    transaction_type=transaction_type,
                    price=price if order_type == "LIMIT" else 0,
                    product="INTRADAY",
                )
                self._order_book[order_id] = {
                    "symbol": symbol, "token": token, "qty": qty,
                    "side": transaction_type, "timestamp": datetime.now(IST),
                }
                logger.info(f"Order placed: {order_id} | {transaction_type} {qty} {symbol}")
                return order_id
            except Exception as e:
                wait = 2 ** attempt
                logger.warning(f"Order attempt {attempt+1} failed: {e}. Retrying in {wait}s…")
                time.sleep(wait)
        logger.error(f"All order attempts failed for {symbol}")
        return None

    def _paper_trade(self, symbol: str, token: str, exchange: str, qty: int,
                     transaction_type: str, price: float, signal) -> str:
        order_id = f"PAPER-{uuid.uuid4().hex[:8].upper()}"
        fill_price = price if price > 0 else self._get_ltp_safe(token, exchange, symbol)
        self._order_book[order_id] = {
            "symbol": symbol, "token": token, "qty": qty,
            "side": transaction_type, "fill_price": fill_price,
            "timestamp": datetime.now(IST), "paper": True,
        }
        logger.info(f"[PAPER] {transaction_type} {qty} {symbol} @ ₹{fill_price:.2f} | OID: {order_id}")
        return order_id

    def _paper_exit(self, position, reason: str) -> str:
        order_id = f"PAPER-EXIT-{uuid.uuid4().hex[:8].upper()}"
        ltp = self._get_ltp_safe(position.token, "NFO", position.symbol)
        logger.info(f"[PAPER] EXIT {position.symbol} @ ₹{ltp:.2f} | Reason: {reason} | OID: {order_id}")
        return order_id

    def _get_ltp_safe(self, token: str, exchange: str, symbol: str) -> float:
        try:
            return self.client.get_ltp(exchange, symbol, token)
        except Exception:
            return 0.0
