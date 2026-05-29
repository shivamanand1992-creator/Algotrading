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
import json
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

_STATE_FILE = Path(__file__).parent.parent.parent / "logs" / "swing_state.json"


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
        self._last_ltp_refresh: Optional[datetime] = None  # throttle live LTP calls

        stocks_cfg = config.get("stocks", {})
        self._max_positions      = int(stocks_cfg.get("max_swing_positions", 5))
        self._risk_pct           = float(stocks_cfg.get("risk_per_trade_pct", 2.0))
        self._auto_exec_min_conf = float(stocks_cfg.get("auto_execute_min_confidence", 0.70))
        # Default capital: use stocks.capital if set, else risk.total_capital, else 150000
        default_cap              = float(stocks_cfg.get("capital", config.get("risk", {}).get("total_capital", 150000)))
        self._total_capital      = default_cap

        # Autopilot settings (controlled via API / UI)
        self._autopilot_enabled           = False
        self._autopilot_mode              = "paper"
        self._autopilot_capital_per_trade = 1000.0   # ₹ to invest per trade
        self._autopilot_max_trades        = 3
        self._autopilot_last_run: Optional[datetime] = None
        self._autopilot_last_result: dict             = {}

        self._load_state()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        """Persist positions and autopilot config to disk so restarts don't lose them."""
        try:
            _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            state = {
                "positions": self._swing_positions,
                "autopilot": {
                    "enabled":           self._autopilot_enabled,
                    "mode":              self._autopilot_mode,
                    "capital_per_trade": self._autopilot_capital_per_trade,
                    "max_trades":        self._autopilot_max_trades,
                },
            }
            _STATE_FILE.write_text(json.dumps(state, indent=2, default=str))
        except Exception as exc:
            logger.warning(f"[SwingService] Could not save state: {exc}")

    def _load_state(self) -> None:
        """Restore positions and autopilot config from disk on startup."""
        if not _STATE_FILE.exists():
            return
        try:
            state = json.loads(_STATE_FILE.read_text())
            positions = state.get("positions", {})
            if isinstance(positions, dict):
                self._swing_positions = positions
                if positions:
                    logger.info(
                        f"[SwingService] Restored {len(positions)} swing position(s) from disk: "
                        + ", ".join(positions.keys())
                    )
            ap = state.get("autopilot", {})
            if ap.get("enabled") is not None:
                self._autopilot_enabled           = bool(ap["enabled"])
                self._autopilot_mode              = ap.get("mode", "paper")
                self._autopilot_capital_per_trade = float(ap.get("capital_per_trade", 1000.0))
                self._autopilot_max_trades        = int(ap.get("max_trades", 3))
                if self._autopilot_enabled:
                    logger.info(
                        f"[SwingService] Restored autopilot: enabled={self._autopilot_enabled}, "
                        f"mode={self._autopilot_mode}, ₹{self._autopilot_capital_per_trade:.0f} "
                        f"× {self._autopilot_max_trades} trades"
                    )
        except Exception as exc:
            logger.warning(f"[SwingService] Could not load saved state: {exc}")

    # ------------------------------------------------------------------
    # Scan
    # ------------------------------------------------------------------

    async def run_scan(self, universe: str = "nifty50", filters: Optional[dict] = None) -> tuple:
        """
        Fetch daily OHLCV and return (signals, regime_info).
        universe: "nifty50" | "nifty100"
        filters:  {"regime_filter": bool, "rs_filter": bool}
        Runs the sync screener in a thread executor (~15s for 50 stocks, ~30s for 100).
        """
        from data.nifty50_universe import NIFTY50_UNIVERSE, NIFTY100_UNIVERSE
        stock_list = NIFTY100_UNIVERSE if universe == "nifty100" else NIFTY50_UNIVERSE
        n = len(stock_list)
        loop = asyncio.get_event_loop()
        logger.info(f"[SwingService] Starting swing scan — universe={universe} ({n} stocks)…")
        signals, regime_info = await loop.run_in_executor(
            None, self._screener.scan_swing, stock_list, filters or {}
        )
        self._last_signals   = signals
        self._last_scan_time = datetime.now(_IST)
        logger.info(f"[SwingService] Scan complete. {len(signals)} BUY signals found.")
        return signals, regime_info

    def get_last_signals(self) -> List[StockSignal]:
        return self._last_signals

    def get_last_scan_time(self) -> Optional[datetime]:
        return self._last_scan_time

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute_signal(
        self,
        symbol: str,
        mode: str,
        capital_override: Optional[float] = None,
        position_value: Optional[float] = None,
    ) -> Optional[str]:
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
            logger.info(f"[SwingService] {symbol} not in last scan — fetching on-demand signal…")
            sig = await self._fetch_signal_on_demand(symbol)
            if sig is None:
                return None

        if position_value and position_value > 0:
            qty = self._calculate_qty_by_capital(sig.entry_price, position_value)
        else:
            capital = capital_override if capital_override and capital_override > 0 else self._total_capital
            qty = self._calculate_qty(sig.entry_price, sig.stop_loss, capital)
        if qty <= 0:
            logger.warning(f"[SwingService] {symbol}: calculated qty=0 — not enough capital.")
            return None

        if mode == "paper":
            return self._open_paper_position(sig, qty)
        else:
            return await self._place_live_order(sig, qty)

    async def auto_execute_top_signals(
        self,
        mode: str,
        max_signals: int = 3,
        capital_override: Optional[float] = None,
        position_value: Optional[float] = None,
    ) -> List[str]:
        """Execute top N signals (confidence >= auto_execute_min_conf) automatically."""
        order_ids: List[str] = []
        eligible = [
            s for s in self._last_signals
            if s.confidence >= self._auto_exec_min_conf
            and s.symbol not in self._swing_positions
        ]
        for sig in eligible[:max_signals]:
            oid = await self.execute_signal(
                sig.symbol, mode,
                capital_override=capital_override,
                position_value=position_value,
            )
            if oid:
                order_ids.append(oid)
        return order_ids

    # ------------------------------------------------------------------
    # Autopilot
    # ------------------------------------------------------------------

    def get_autopilot_config(self) -> dict:
        return {
            "enabled":           self._autopilot_enabled,
            "mode":              self._autopilot_mode,
            "capital_per_trade": self._autopilot_capital_per_trade,
            "max_trades":        self._autopilot_max_trades,
            "last_run":          self._autopilot_last_run.isoformat() if self._autopilot_last_run else None,
            "last_result":       self._autopilot_last_result,
        }

    def set_autopilot(
        self,
        enabled: bool,
        mode: str,
        capital_per_trade: float,
        max_trades: int = 3,
    ) -> None:
        self._autopilot_enabled           = enabled
        self._autopilot_mode              = mode if mode in ("paper", "live") else "paper"
        self._autopilot_capital_per_trade = max(100.0, float(capital_per_trade))
        self._autopilot_max_trades        = max(1, min(int(max_trades), 10))
        logger.info(
            f"[SwingAutopilot] Config: enabled={enabled}, mode={self._autopilot_mode}, "
            f"₹{self._autopilot_capital_per_trade:.0f} × {self._autopilot_max_trades} trades"
        )
        self._save_state()

    async def run_autopilot(self) -> dict:
        """
        Scan + auto-execute top N signals with fixed per-trade capital.
        Called daily at 09:20 IST by the scheduler (or manually via API).
        """
        if not self._autopilot_enabled:
            return {"skipped": True, "reason": "autopilot disabled"}

        logger.info(
            f"[SwingAutopilot] Starting — mode={self._autopilot_mode}, "
            f"₹{self._autopilot_capital_per_trade:.0f} × {self._autopilot_max_trades} trades"
        )

        # Check how many slots are free before scanning
        current_count = len(self._swing_positions)
        slots_free = self._autopilot_max_trades - current_count
        if slots_free <= 0:
            logger.info(
                f"[SwingAutopilot] Already holding {current_count}/{self._autopilot_max_trades} "
                f"positions — no new trades today."
            )
            self._autopilot_last_run = datetime.now(_IST)
            self._autopilot_last_result = {
                "run_time":       self._autopilot_last_run.isoformat(),
                "signals_found":  0,
                "executed_count": 0,
                "executed":       [],
                "skipped_reason": f"Max positions reached ({current_count}/{self._autopilot_max_trades})",
                "regime_warning": "",
                "nifty_bullish":  True,
            }
            return self._autopilot_last_result

        signals, regime_info = await self.run_scan(
            universe="nifty50",
            filters={"regime_filter": True, "rs_filter": True},
        )

        executed = []
        eligible = [s for s in signals if s.symbol not in self._swing_positions]
        for sig in eligible[:slots_free]:  # only fill empty slots, not always max_trades
            qty = self._calculate_qty_by_capital(sig.entry_price, self._autopilot_capital_per_trade)
            if qty <= 0:
                continue
            if self._autopilot_mode == "paper":
                oid = self._open_paper_position(sig, qty)
            else:
                oid = await self._place_live_order(sig, qty)
            if oid:
                invested = round(qty * sig.entry_price, 2)
                executed.append({
                    "symbol":     sig.symbol,
                    "order_id":   oid,
                    "qty":        qty,
                    "entry":      sig.entry_price,
                    "sl":         sig.stop_loss,
                    "target1":    sig.target1,
                    "target2":    sig.target2,
                    "invested":   invested,
                    "confidence": sig.confidence,
                })
                logger.info(
                    f"[SwingAutopilot] {sig.symbol}: qty={qty}, "
                    f"entry=₹{sig.entry_price:.2f}, invested=₹{invested:.2f}"
                )

        self._autopilot_last_run = datetime.now(_IST)
        self._autopilot_last_result = {
            "run_time":       self._autopilot_last_run.isoformat(),
            "signals_found":  len(signals),
            "executed_count": len(executed),
            "executed":       executed,
            "regime_warning": regime_info.get("warning", ""),
            "nifty_bullish":  regime_info.get("bullish", True),
        }
        logger.info(
            f"[SwingAutopilot] Complete — "
            f"{len(executed)}/{self._autopilot_max_trades} trades executed, "
            f"{len(signals)} signals found."
        )
        return self._autopilot_last_result

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------

    def get_positions(self) -> List[dict]:
        return list(self._swing_positions.values())

    async def refresh_position_prices(self) -> None:
        """
        Fetch live LTP for every open swing position and update current_price / P&L.
        Throttled: at most one round of LTP calls per 30 seconds to avoid hammering
        the Angel One API on every frontend poll.
        Paper positions use the same token lookup but live prices too — the screener
        entry price was at market close; intraday moves still matter for P&L display.
        """
        if not self._swing_positions:
            return

        now = datetime.now(_IST)
        if (
            self._last_ltp_refresh is not None
            and (now - self._last_ltp_refresh).total_seconds() < 30
        ):
            return  # skip — refreshed recently
        self._last_ltp_refresh = now

        loop = asyncio.get_event_loop()
        for symbol, pos in list(self._swing_positions.items()):
            try:
                token = await self._resolve_token(symbol)
                if not token or token == "0":
                    continue
                eq_sym = f"{symbol}-EQ"
                ltp = await loop.run_in_executor(
                    None,
                    lambda s=eq_sym, t=token: self.angel_client.get_ltp("NSE", s, t)
                )
                if ltp and ltp > 0:
                    entry = pos["entry_price"]
                    qty   = pos["qty"]
                    pos["current_price"]  = round(ltp, 2)
                    pos["unrealized_pnl"] = round((ltp - entry) * qty, 2)
                    pos["pnl_pct"]        = round((ltp - entry) / entry * 100, 2)
                    pos["last_updated"]   = now.isoformat()
                    logger.debug(
                        f"[SwingService] {symbol} LTP=₹{ltp:.2f} "
                        f"P&L={pos['pnl_pct']:+.2f}% (₹{pos['unrealized_pnl']:+.2f})"
                    )
            except Exception as exc:
                logger.debug(f"[SwingService] LTP refresh skipped for {symbol}: {exc}")
        self._save_state()

    def close_position(self, symbol: str, reason: str = "manual") -> bool:
        if symbol not in self._swing_positions:
            return False
        pos = self._swing_positions.pop(symbol)
        logger.info(f"[SwingService] Closed {symbol} position — reason: {reason}. PnL: ₹{pos.get('unrealized_pnl', 0):.2f}")
        self._save_state()
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
                ticker = pos.get("yf_ticker", symbol + ".NS")

                # Use 5-min intraday bars to get accurate today's high/low
                # (called at 15:20 IST while market is still open)
                df_intra = yf.download(ticker, period="1d", interval="5m",
                                       progress=False, auto_adjust=True)

                if df_intra is not None and not df_intra.empty:
                    if isinstance(df_intra.columns, pd.MultiIndex):
                        df_intra.columns = df_intra.columns.get_level_values(0)
                    df_intra.columns = [c.lower() for c in df_intra.columns]
                    today_high  = float(df_intra["high"].max())
                    today_low   = float(df_intra["low"].min())
                    today_close = float(df_intra["close"].iloc[-1])
                else:
                    # Fallback to daily candle if intraday unavailable
                    df_day = yf.download(ticker, period="2d", interval="1d",
                                         progress=False, auto_adjust=True)
                    if df_day is None or df_day.empty:
                        continue
                    if isinstance(df_day.columns, pd.MultiIndex):
                        df_day.columns = df_day.columns.get_level_values(0)
                    df_day.columns = [c.lower() for c in df_day.columns]
                    row = df_day.iloc[-1]
                    today_high  = float(row.get("high",  pos["entry_price"]))
                    today_low   = float(row.get("low",   pos["entry_price"]))
                    today_close = float(row.get("close", pos["entry_price"]))

                pos["current_price"]  = today_close
                pos["unrealized_pnl"] = (today_close - pos["entry_price"]) * pos["qty"]
                pos["pnl_pct"]        = round(
                    (today_close - pos["entry_price"]) / pos["entry_price"] * 100, 2
                )
                pos["last_updated"]   = datetime.now(_IST).isoformat()

                trailing = pos.get("trailing_active", False)

                # SL hit check (intraday low ≤ SL)
                if today_low <= pos["stop_loss"]:
                    exit_px = pos["stop_loss"]
                    pnl     = (exit_px - pos["entry_price"]) * pos["qty"]
                    if trailing:
                        logger.info(
                            f"[SwingMonitor] {symbol} TRAILING SL HIT @ ₹{exit_px:.2f} "
                            f"— locked profit ₹{pnl:.2f}"
                        )
                        pos["status"] = "closed_trail"
                    else:
                        logger.warning(f"[SwingMonitor] {symbol} SL HIT — loss ₹{pnl:.2f}")
                        pos["status"] = "closed_sl"
                    pos["exit_price"]   = exit_px
                    pos["realized_pnl"] = pnl
                    symbols_to_close.append(symbol)

                # Target1 hit: activate trailing stop at breakeven, ride to Target2
                elif not trailing and today_high >= pos["target1"]:
                    new_sl = pos["entry_price"]   # trail SL to breakeven
                    pos["stop_loss"]       = new_sl
                    pos["trailing_active"] = True
                    logger.info(
                        f"[SwingMonitor] {symbol} TARGET1 HIT ✓ — "
                        f"trailing SL moved to breakeven ₹{new_sl:.2f}, "
                        f"riding toward T2=₹{pos['target2']:.2f}"
                    )

                # Target2 hit: close with full profit
                elif today_high >= pos["target2"]:
                    pnl = (pos["target2"] - pos["entry_price"]) * pos["qty"]
                    logger.info(f"[SwingMonitor] {symbol} TARGET2 HIT 🎯 — profit ₹{pnl:.2f}")
                    pos["status"]       = "closed_target"
                    pos["exit_price"]   = pos["target2"]
                    pos["realized_pnl"] = pnl
                    symbols_to_close.append(symbol)

                else:
                    t_tag = " [trailing]" if trailing else ""
                    logger.debug(
                        f"[SwingMonitor] {symbol}{t_tag} | close={today_close:.2f} "
                        f"P&L={pos['pnl_pct']:.2f}% | "
                        f"SL={pos['stop_loss']:.2f} T2={pos['target2']:.2f}"
                    )

            except Exception as exc:
                logger.error(f"[SwingMonitor] {symbol} update failed: {exc}")

        # Place live exit orders for live positions that hit SL/target
        for symbol in symbols_to_close:
            pos = self._swing_positions.get(symbol)
            if pos and pos.get("mode") == "live" and self.angel_client:
                await self._place_exit_order(pos)
            # Remove closed positions from active dict
            if symbol in self._swing_positions and self._swing_positions[symbol].get("status") in ("closed_sl", "closed_target", "closed_trail"):
                self._swing_positions.pop(symbol, None)
        if symbols_to_close:
            self._save_state()

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

    def _calculate_qty_by_capital(self, entry: float, capital_per_trade: float) -> int:
        """Position-value sizing: invest capital_per_trade in one stock."""
        if entry <= 0 or capital_per_trade <= 0:
            return 0
        return max(1, math.floor(capital_per_trade / entry))

    async def _fetch_signal_on_demand(self, symbol: str) -> Optional[StockSignal]:
        """
        Build a minimal StockSignal for *symbol* by fetching live yfinance data.
        Used when the user executes a stock that was not in the last scan results
        (e.g. after a server restart or without running a scan first).
        Entry = last daily close; SL = entry − 1.5×ATR14; T1/T2 from 1:2/1:3 R:R.
        """
        from data.nifty50_universe import NIFTY100_UNIVERSE
        import yfinance as yf

        sym_upper = symbol.upper()
        stock_info = next((s for s in NIFTY100_UNIVERSE if s["symbol"] == sym_upper), None)
        if stock_info is None:
            logger.warning(
                f"[SwingService] {sym_upper} not found in Nifty100 universe — "
                f"cannot build on-demand signal."
            )
            return None

        yf_ticker = stock_info["yf"]
        try:
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(
                None,
                lambda: yf.download(yf_ticker, period="90d", interval="1d",
                                    progress=False, auto_adjust=True)
            )
            if df is None or df.empty or len(df) < 15:
                logger.warning(f"[SwingService] Insufficient yfinance data for {sym_upper}.")
                return None

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.columns = [c.lower() for c in df.columns]

            # ATR14: true range rolling mean
            pc = df["close"].shift(1)
            tr = pd.concat([
                df["high"] - df["low"],
                (df["high"] - pc).abs(),
                (df["low"]  - pc).abs(),
            ], axis=1).max(axis=1)
            atr14 = float(tr.rolling(14).mean().iloc[-1])

            entry  = round(float(df["close"].iloc[-1]), 2)
            sl     = round(entry - 1.5 * atr14, 2)
            risk   = entry - sl
            t1     = round(entry + 2.0 * risk, 2)
            t2     = round(entry + 3.0 * risk, 2)
            sl_pct = round((risk / entry) * 100, 2) if entry > 0 else 0.0

            logger.info(
                f"[SwingService] On-demand signal for {sym_upper}: "
                f"entry=₹{entry:.2f} SL=₹{sl:.2f} T1=₹{t1:.2f} T2=₹{t2:.2f}"
            )
            return StockSignal(
                symbol       = sym_upper,
                name         = stock_info["name"],
                sector       = stock_info.get("sector", ""),
                yf_ticker    = yf_ticker,
                action       = "BUY",
                close        = entry,
                entry_price  = entry,
                stop_loss    = sl,
                target1      = t1,
                target2      = t2,
                sl_pct       = sl_pct,
                confidence   = 0.5,
                regime       = "ranging",
                reasons      = ["manual execution — on-demand"],
                rsi          = 0.0,
                adx          = 0.0,
                atr          = atr14,
                volume_ratio = 0.0,
            )
        except Exception as exc:
            logger.error(f"[SwingService] On-demand signal fetch failed for {sym_upper}: {exc}")
            return None

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
        self._save_state()
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

        # NSE cash equity session: 09:15–15:30 IST
        now_ist = datetime.now(_IST).time()
        market_open  = datetime.strptime("09:15", "%H:%M").time()
        market_close = datetime.strptime("15:30", "%H:%M").time()
        if not (market_open <= now_ist <= market_close):
            logger.warning(
                f"[SwingService] Market is closed ({now_ist.strftime('%H:%M')} IST). "
                f"Live CNC order for {sig.symbol} skipped. Try during 09:15–15:30."
            )
            return None

        token = await self._resolve_token(sig.symbol)
        if not token or token == "0":
            logger.error(f"[SwingService] Could not resolve token for {sig.symbol} — skipping live order.")
            return None

        # Pre-flight balance check — abort early if clearly insufficient
        order_amount = round(qty * sig.entry_price, 2)
        try:
            loop2 = asyncio.get_event_loop()
            funds = await loop2.run_in_executor(None, self.angel_client.get_funds)
            avail = float(
                funds.get("availablecash")
                or funds.get("net")
                or funds.get("availablebalance")
                or 0
            )
            if avail > 0 and order_amount > avail:
                logger.error(
                    f"[SwingService] Insufficient funds for {sig.symbol}: "
                    f"need ₹{order_amount:.2f} but only ₹{avail:.2f} available. "
                    f"Reduce capital or quantity."
                )
                return None
            logger.info(
                f"[SwingService] Balance OK: ₹{avail:.2f} available, "
                f"order ₹{order_amount:.2f} ({qty}×{sig.symbol})"
            )
        except Exception as exc:
            logger.warning(f"[SwingService] Balance check failed (proceeding anyway): {exc}")

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
                self._save_state()
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


