"""
swing_trade_service.py
======================
Orchestrates Nifty50 swing trade screener scans, order execution (paper &
live), and daily position monitoring.

Paper mode  — positions tracked in-memory; mark-to-market via yfinance at EOD
Live mode   — places CNC delivery orders via Angel One; monitors for SL/target
"""

from __future__ import annotations

import asyncio
import math
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import pytz
from loguru import logger

sys.path.append(str(Path(__file__).parent.parent.parent))

from data.nifty50_universe import NIFTY50_UNIVERSE
from models.stock_screener import StockScreener, StockSignal

_IST = pytz.timezone("Asia/Kolkata")


class SwingTradeService:
    """
    Manages swing trade lifecycle:
      1. Scan — runs StockScreener on Nifty50 universe
      2. Execute — places paper-simulated or live CNC orders
      3. Monitor — daily price update + SL/target check
    """

    def __init__(self, config: dict, angel_client=None) -> None:
        self.config        = config
        self.angel_client  = angel_client
        self._screener     = StockScreener(config)
        self._last_signals: List[StockSignal] = []
        self._last_scan_time: Optional[datetime] = None
        self._swing_positions: Dict[str, dict] = {}   # symbol → position dict
        self._token_cache: Dict[str, str] = {}        # symbol → Angel One token

        stocks_cfg = config.get("stocks", {})
        self._max_positions      = int(stocks_cfg.get("max_swing_positions", 5))
        self._risk_pct           = float(stocks_cfg.get("risk_per_trade_pct", 2.0))
        self._auto_exec_min_conf = float(stocks_cfg.get("auto_execute_min_confidence", 0.70))
        # Default capital: use stocks.capital if set, else risk.total_capital, else 150000
        default_cap              = float(stocks_cfg.get("capital", config.get("risk", {}).get("total_capital", 150000)))
        self._total_capital      = default_cap

    # ------------------------------------------------------------------
    # Scan
    # ------------------------------------------------------------------

    async def run_scan(self) -> List[StockSignal]:
        """
        Fetch daily OHLCV for all 50 stocks and return ranked BUY signals.
        Runs the sync screener in a thread executor (~15 seconds).
        """
        loop = asyncio.get_event_loop()
        logger.info("[SwingService] Starting Nifty50 swing scan…")
        signals = await loop.run_in_executor(
            None, self._screener.scan_swing, NIFTY50_UNIVERSE
        )
        self._last_signals   = signals
        self._last_scan_time = datetime.now(_IST)
        logger.info(f"[SwingService] Scan complete. {len(signals)} BUY signals found.")
        return signals

    def get_last_signals(self) -> List[StockSignal]:
        return self._last_signals

    def get_last_scan_time(self) -> Optional[datetime]:
        return self._last_scan_time

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute_signal(self, symbol: str, mode: str, capital_override: Optional[float] = None) -> Optional[str]:
        """
        Place a swing trade order for *symbol* from the last scan results.

        Parameters
        ----------
        symbol : str   e.g. "RELIANCE"
        mode   : str   "paper" | "live"

        Returns
        -------
        str   — order_id / paper position key on success
        None  — if blocked (already held, no signal, too many positions)
        """
        if symbol in self._swing_positions:
            logger.info(f"[SwingService] {symbol} already in open positions — skipping.")
            return None

        if len(self._swing_positions) >= self._max_positions:
            logger.warning(f"[SwingService] Max positions ({self._max_positions}) reached.")
            return None

        sig = next((s for s in self._last_signals if s.symbol == symbol), None)
        if sig is None:
            logger.warning(f"[SwingService] No signal found for {symbol}.")
            return None

        capital = capital_override if capital_override and capital_override > 0 else self._total_capital
        qty = self._calculate_qty(sig.entry_price, sig.stop_loss, capital)
        if qty <= 0:
            logger.warning(f"[SwingService] {symbol}: calculated qty=0 — not enough capital.")
            return None

        if mode == "paper":
            return self._open_paper_position(sig, qty)
        else:
            return await self._place_live_order(sig, qty)

    async def auto_execute_top_signals(self, mode: str, max_signals: int = 3, capital_override: Optional[float] = None) -> List[str]:
        """Execute top N signals (confidence >= auto_execute_min_conf) automatically."""
        order_ids: List[str] = []
        eligible = [
            s for s in self._last_signals
            if s.confidence >= self._auto_exec_min_conf
            and s.symbol not in self._swing_positions
        ]
        for sig in eligible[:max_signals]:
            oid = await self.execute_signal(sig.symbol, mode, capital_override=capital_override)
            if oid:
                order_ids.append(oid)
        return order_ids

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------

    def get_positions(self) -> List[dict]:
        return list(self._swing_positions.values())

    def close_position(self, symbol: str, reason: str = "manual") -> bool:
        if symbol not in self._swing_positions:
            return False
        pos = self._swing_positions.pop(symbol)
        logger.info(f"[SwingService] Closed {symbol} position — reason: {reason}. PnL: ₹{pos.get('unrealized_pnl', 0):.2f}")
        return True

    async def monitor_positions(self) -> None:
        """
        Update mark-to-market prices for all open swing positions.
        Called once daily after market close (~16:00 IST).
        Checks SL and target1 breaches; auto-closes paper positions.
        """
        if not self._swing_positions:
            return

        import yfinance as yf

        symbols_to_close: List[str] = []

        for symbol, pos in self._swing_positions.items():
            try:
                ticker  = pos.get("yf_ticker", symbol + ".NS")
                df_day  = yf.download(ticker, period="2d", interval="1d",
                                      progress=False, auto_adjust=True)
                if df_day is None or df_day.empty:
                    continue

                if isinstance(df_day.columns, pd.MultiIndex):
                    df_day.columns = df_day.columns.get_level_values(0)
                df_day.columns = [c.lower() for c in df_day.columns]

                today_row  = df_day.iloc[-1]
                today_low  = float(today_row.get("low",   pos["entry_price"]))
                today_high = float(today_row.get("high",  pos["entry_price"]))
                today_close= float(today_row.get("close", pos["entry_price"]))

                pos["current_price"]  = today_close
                pos["unrealized_pnl"] = (today_close - pos["entry_price"]) * pos["qty"]
                pos["pnl_pct"]        = round(
                    (today_close - pos["entry_price"]) / pos["entry_price"] * 100, 2
                )
                pos["last_updated"]   = datetime.now(_IST).isoformat()

                # SL hit check (intraday low ≤ SL)
                if today_low <= pos["stop_loss"]:
                    pnl = (pos["stop_loss"] - pos["entry_price"]) * pos["qty"]
                    logger.warning(f"[SwingMonitor] {symbol} SL HIT — loss ₹{pnl:.2f}")
                    pos["status"]       = "closed_sl"
                    pos["exit_price"]   = pos["stop_loss"]
                    pos["realized_pnl"] = pnl
                    symbols_to_close.append(symbol)

                # Target1 hit check (intraday high ≥ target1)
                elif today_high >= pos["target1"]:
                    pnl = (pos["target1"] - pos["entry_price"]) * pos["qty"]
                    logger.info(f"[SwingMonitor] {symbol} TARGET1 HIT — profit ₹{pnl:.2f}")
                    pos["status"]       = "closed_target"
                    pos["exit_price"]   = pos["target1"]
                    pos["realized_pnl"] = pnl
                    symbols_to_close.append(symbol)

                else:
                    logger.debug(
                        f"[SwingMonitor] {symbol} | close={today_close:.2f} "
                        f"P&L={pos['pnl_pct']:.2f}% | "
                        f"SL={pos['stop_loss']:.2f} T1={pos['target1']:.2f}"
                    )

            except Exception as exc:
                logger.error(f"[SwingMonitor] {symbol} update failed: {exc}")

        # Place live exit orders for live positions that hit SL/target
        for symbol in symbols_to_close:
            pos = self._swing_positions.get(symbol)
            if pos and pos.get("mode") == "live" and self.angel_client:
                await self._place_exit_order(pos)
            # Remove closed positions from active dict
            if symbol in self._swing_positions and self._swing_positions[symbol].get("status") in ("closed_sl", "closed_target"):
                self._swing_positions.pop(symbol, None)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _calculate_qty(self, entry: float, sl: float, capital: Optional[float] = None) -> int:
        """Fixed-fraction sizing: risk 2% of capital per trade."""
        if entry <= 0 or sl <= 0 or entry <= sl:
            return 0
        risk_per_share = entry - sl
        cap            = capital if capital and capital > 0 else self._total_capital
        risk_capital   = (self._risk_pct / 100) * cap
        qty            = math.floor(risk_capital / risk_per_share)
        return max(qty, 1)

    def _open_paper_position(self, sig: StockSignal, qty: int) -> str:
        """Record a paper swing position in memory."""
        pos_id = f"PAPER-SWING-{sig.symbol}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        self._swing_positions[sig.symbol] = {
            "order_id":       pos_id,
            "symbol":         sig.symbol,
            "name":           sig.name,
            "sector":         sig.sector,
            "yf_ticker":      sig.yf_ticker,
            "entry_price":    sig.entry_price,
            "current_price":  sig.entry_price,
            "qty":            qty,
            "stop_loss":      sig.stop_loss,
            "target1":        sig.target1,
            "target2":        sig.target2,
            "entry_date":     datetime.now(_IST).strftime("%Y-%m-%d"),
            "unrealized_pnl": 0.0,
            "pnl_pct":        0.0,
            "status":         "open",
            "mode":           "paper",
            "confidence":     sig.confidence,
            "regime":         sig.regime,
        }
        logger.info(f"[SwingService] Paper position opened: {sig.symbol} qty={qty} entry=₹{sig.entry_price:.2f}")
        return pos_id

    async def _resolve_token(self, symbol: str) -> str:
        """Resolve Angel One instrument token for a stock symbol."""
        if symbol in self._token_cache:
            return self._token_cache[symbol]

        if self.angel_client is None:
            return "0"

        try:
            token = self.angel_client.search_scrip("NSE", symbol)
            if token:
                self._token_cache[symbol] = token
                logger.debug(f"[SwingService] Token resolved: {symbol} → {token}")
                return token
        except Exception as exc:
            logger.warning(f"[SwingService] Token lookup failed for {symbol}: {exc}")

        return "0"

    async def _place_live_order(self, sig: StockSignal, qty: int) -> Optional[str]:
        """Place a real CNC delivery order via Angel One."""
        if self.angel_client is None:
            logger.error("[SwingService] Angel One client not available for live order.")
            return None

        token = await self._resolve_token(sig.symbol)
        if not token or token == "0":
            logger.error(f"[SwingService] Could not resolve token for {sig.symbol} — skipping live order.")
            return None
        # NSE cash equity trading symbol uses the "-EQ" suffix in Angel One
        eq_symbol = f"{sig.symbol}-EQ"
        try:
            loop = asyncio.get_event_loop()
            order_id = await loop.run_in_executor(
                None,
                lambda: self.angel_client.place_order(
                    variety          = "NORMAL",
                    exchange         = "NSE",
                    symbol           = eq_symbol,
                    token            = token,
                    qty              = qty,
                    order_type       = "MARKET",
                    transaction_type = "BUY",
                    price            = 0.0,
                    trigger_price    = 0.0,
                    product          = "DELIVERY",
                )
            )
            if order_id:
                self._swing_positions[sig.symbol] = {
                    "order_id":       order_id,
                    "symbol":         sig.symbol,
                    "name":           sig.name,
                    "sector":         sig.sector,
                    "yf_ticker":      sig.yf_ticker,
                    "entry_price":    sig.entry_price,
                    "current_price":  sig.entry_price,
                    "qty":            qty,
                    "stop_loss":      sig.stop_loss,
                    "target1":        sig.target1,
                    "target2":        sig.target2,
                    "entry_date":     datetime.now(_IST).strftime("%Y-%m-%d"),
                    "unrealized_pnl": 0.0,
                    "pnl_pct":        0.0,
                    "status":         "open",
                    "mode":           "live",
                    "token":          token,
                    "confidence":     sig.confidence,
                    "regime":         sig.regime,
                }
                logger.info(f"[SwingService] Live CNC order placed: {sig.symbol} qty={qty} order_id={order_id}")
                return order_id
        except Exception as exc:
            logger.error(f"[SwingService] Live order failed for {sig.symbol}: {exc}")

        return None

    async def _place_exit_order(self, pos: dict) -> None:
        """Place a live CNC sell order to exit a position."""
        if self.angel_client is None:
            return
        symbol    = pos["symbol"]
        eq_symbol = f"{symbol}-EQ"
        token     = pos.get("token", await self._resolve_token(symbol))
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.angel_client.place_order(
                    variety          = "NORMAL",
                    exchange         = "NSE",
                    symbol           = eq_symbol,
                    token            = token,
                    qty              = pos["qty"],
                    order_type       = "MARKET",
                    transaction_type = "SELL",
                    price            = 0.0,
                    trigger_price    = 0.0,
                    product          = "DELIVERY",
                )
            )
            logger.info(f"[SwingService] Live exit order placed for {symbol}.")
        except Exception as exc:
            logger.error(f"[SwingService] Live exit order failed for {symbol}: {exc}")


# ---------------------------------------------------------------------------
# Module-level singleton (lazily created by the API route)
# ---------------------------------------------------------------------------
_swing_service_instance: Optional[SwingTradeService] = None


def get_swing_service(config: dict, angel_client=None) -> SwingTradeService:
    global _swing_service_instance
    if _swing_service_instance is None:
        _swing_service_instance = SwingTradeService(config, angel_client)
    return _swing_service_instance


