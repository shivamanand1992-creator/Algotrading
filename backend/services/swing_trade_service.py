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
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import pytz
from loguru import logger
from sqlalchemy import Column, String, Integer, Float, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session

sys.path.append(str(Path(__file__).parent.parent.parent))

from data.nifty50_universe import NIFTY50_UNIVERSE
from models.stock_screener import StockScreener, StockSignal

_IST = pytz.timezone("Asia/Kolkata")

_STATE_FILE   = Path(__file__).parent.parent.parent / "logs" / "swing_state.json"
_LEDGER_FILE  = Path(__file__).parent.parent.parent / "logs" / "swing_orders_ledger.json"


# ---------------------------------------------------------------------------
# SQLAlchemy model — swing orders ledger (survives redeployments via Postgres)
# ---------------------------------------------------------------------------

class _LedgerBase(DeclarativeBase):
    pass


class _SwingLedgerRow(_LedgerBase):
    __tablename__ = "swing_orders_ledger"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    symbol      = Column(String(32),  nullable=False, index=True)
    order_id    = Column(String(64),  nullable=False)
    date        = Column(String(16),  nullable=False)   # YYYY-MM-DD
    qty         = Column(Integer,     nullable=False)
    entry_price = Column(Float,       nullable=False)
    mode        = Column(String(16),  nullable=False)


class _SwingStateRow(_LedgerBase):
    """Key-value store for swing service state — persists across Railway redeploys."""
    __tablename__ = "swing_service_state"
    key        = Column(String(64), primary_key=True)
    value_json = Column(Text,       nullable=False, default="{}")
    updated_at = Column(String(32), nullable=False, default="")


def _get_ledger_engine():
    """Return an SQLAlchemy engine using DATABASE_URL (Postgres on Railway, SQLite locally)."""
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        logs_dir = Path(__file__).parent.parent.parent / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        db_url = f"sqlite:///{logs_dir}/trades.db"
    # SQLAlchemy requires 'postgresql://' not 'postgres://'
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return create_engine(db_url, echo=False, future=True, pool_pre_ping=True)


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
        self._autopilot_enabled            = False
        self._autopilot_mode               = "paper"
        self._autopilot_capital_per_trade  = 1000.0   # ₹ to invest per trade
        self._autopilot_max_trades         = 3
        self._autopilot_optimizer_method   = "confidence_weighted"  # equal_weight | risk_parity | kelly | confidence_weighted
        self._autopilot_last_run: Optional[datetime] = None
        self._autopilot_last_result: dict              = {}

        self._orders_ledger: List[dict] = []   # all orders ever placed by this system
        self._load_state()
        self._load_ledger()

        # Real-time intraday SL monitoring via Angel One WebSocket
        self._live_feed = None
        self._realtime_ltps: Dict[str, float] = {}   # token → live LTP
        self._token_to_symbol: Dict[str, str] = {}   # token → symbol
        self._sl_triggered: set = set()              # symbols with exits already placed today
        self._feed_subscribed_tokens: set = set()    # tokens already sent to live feed

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        """Persist positions and autopilot config — DB primary (survives Railway redeploys), file secondary."""
        state = {
            "positions": self._swing_positions,
            "autopilot": {
                "enabled":           self._autopilot_enabled,
                "mode":              self._autopilot_mode,
                "capital_per_trade": self._autopilot_capital_per_trade,
                "max_trades":        self._autopilot_max_trades,
                "optimizer_method":  self._autopilot_optimizer_method,
                "last_run":          self._autopilot_last_run.isoformat() if self._autopilot_last_run else None,
                "last_result":       self._autopilot_last_result,
            },
        }
        state_json = json.dumps(state, default=str)

        # Primary: PostgreSQL — survives Railway container replacement
        try:
            engine = _get_ledger_engine()
            _LedgerBase.metadata.create_all(engine, checkfirst=True)
            with Session(engine) as s:
                s.merge(_SwingStateRow(
                    key        = "swing_state",
                    value_json = state_json,
                    updated_at = datetime.now(_IST).isoformat(),
                ))
                s.commit()
        except Exception as exc:
            logger.warning(f"[SwingService] DB state save failed: {exc}")

        # Secondary: file on disk (local dev / fallback)
        try:
            _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _STATE_FILE.write_text(state_json)
        except Exception as exc:
            logger.warning(f"[SwingService] File state save failed: {exc}")

    def _apply_state(self, state: dict) -> None:
        """Apply a loaded state dict to instance fields."""
        positions = state.get("positions", {})
        if isinstance(positions, dict):
            self._swing_positions = positions
            if positions:
                logger.info(
                    f"[SwingService] Restored {len(positions)} swing position(s): "
                    + ", ".join(positions.keys())
                )
        ap = state.get("autopilot", {})
        if ap.get("enabled") is not None:
            self._autopilot_enabled            = bool(ap["enabled"])
            self._autopilot_mode               = ap.get("mode", "paper")
            self._autopilot_capital_per_trade  = float(ap.get("capital_per_trade", 1000.0))
            self._autopilot_max_trades         = int(ap.get("max_trades", 3))
            self._autopilot_optimizer_method   = ap.get("optimizer_method", "confidence_weighted")
            if ap.get("last_run"):
                try:
                    self._autopilot_last_run = datetime.fromisoformat(ap["last_run"])
                except Exception:
                    pass
            if ap.get("last_result"):
                self._autopilot_last_result = ap["last_result"]
            if self._autopilot_enabled:
                logger.info(
                    f"[SwingService] Restored autopilot: enabled={self._autopilot_enabled}, "
                    f"mode={self._autopilot_mode}, ₹{self._autopilot_capital_per_trade:.0f} "
                    f"× {self._autopilot_max_trades} trades"
                )

    def _load_state(self) -> None:
        """Restore positions and autopilot config — DB first (Railway-safe), then file fallback."""
        # Primary: database (PostgreSQL on Railway, SQLite locally)
        try:
            engine = _get_ledger_engine()
            _LedgerBase.metadata.create_all(engine, checkfirst=True)
            db_json = None
            with Session(engine) as s:
                row = s.get(_SwingStateRow, "swing_state")
                if row is not None:
                    db_json = row.value_json   # capture inside session to avoid DetachedInstanceError
            if db_json:
                state = json.loads(db_json)
                self._apply_state(state)
                logger.info("[SwingService] State loaded from database.")
                return
        except Exception as exc:
            logger.warning(f"[SwingService] DB state load failed, trying file: {exc}")

        # Fallback: local file (ephemeral on Railway, useful for local dev)
        if not _STATE_FILE.exists():
            return
        try:
            state = json.loads(_STATE_FILE.read_text())
            self._apply_state(state)
            logger.info("[SwingService] State loaded from file (migrating to DB on next save).")
        except Exception as exc:
            logger.warning(f"[SwingService] Could not load saved state: {exc}")

    def _load_ledger(self) -> None:
        """
        Load orders ledger — tries database first (survives Railway redeploys),
        then falls back to the JSON file for local dev / first-run.
        """
        try:
            engine = _get_ledger_engine()
            _LedgerBase.metadata.create_all(engine, checkfirst=True)
            with Session(engine) as s:
                rows = s.query(_SwingLedgerRow).all()
            if rows:
                self._orders_ledger = [
                    {"symbol": r.symbol, "order_id": r.order_id, "date": r.date,
                     "qty": r.qty, "entry_price": r.entry_price, "mode": r.mode}
                    for r in rows
                ]
                logger.info(f"[SwingService] Ledger loaded from DB — {len(rows)} orders.")
                return
        except Exception as exc:
            logger.warning(f"[SwingService] DB ledger load failed, falling back to JSON: {exc}")

        # JSON fallback
        if not _LEDGER_FILE.exists():
            return
        try:
            self._orders_ledger = json.loads(_LEDGER_FILE.read_text())
            logger.info(f"[SwingService] Ledger loaded from JSON — {len(self._orders_ledger)} orders.")
            # Migrate JSON entries into DB so future restarts use DB
            self._migrate_json_ledger_to_db()
        except Exception as exc:
            logger.warning(f"[SwingService] Could not load orders ledger: {exc}")

    def _migrate_json_ledger_to_db(self) -> None:
        """One-time migration: write JSON ledger entries into the database."""
        try:
            engine = _get_ledger_engine()
            _LedgerBase.metadata.create_all(engine, checkfirst=True)
            with Session(engine) as s:
                existing = {r.order_id for r in s.query(_SwingLedgerRow).all()}
                for e in self._orders_ledger:
                    if e["order_id"] not in existing:
                        s.add(_SwingLedgerRow(
                            symbol=e["symbol"], order_id=e["order_id"], date=e["date"],
                            qty=int(e["qty"]), entry_price=float(e["entry_price"]), mode=e["mode"]
                        ))
                s.commit()
            logger.info(f"[SwingService] Migrated {len(self._orders_ledger)} JSON ledger entries to DB.")
        except Exception as exc:
            logger.warning(f"[SwingService] JSON→DB ledger migration failed: {exc}")

    def _append_to_ledger(self, symbol: str, order_id: str, qty: int,
                          entry_price: float, mode: str) -> None:
        """Append a new order entry to database AND JSON file."""
        entry = {
            "symbol":      symbol,
            "order_id":    order_id,
            "date":        datetime.now(_IST).strftime("%Y-%m-%d"),
            "qty":         qty,
            "entry_price": entry_price,
            "mode":        mode,
        }
        self._orders_ledger.append(entry)

        # Write to database (primary, survives redeploys)
        try:
            engine = _get_ledger_engine()
            with Session(engine) as s:
                s.add(_SwingLedgerRow(**entry))
                s.commit()
        except Exception as exc:
            logger.warning(f"[SwingService] DB ledger write failed: {exc}")

        # Write to JSON file (secondary, local dev backup)
        try:
            _LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
            _LEDGER_FILE.write_text(json.dumps(self._orders_ledger, indent=2, default=str))
        except Exception as exc:
            logger.warning(f"[SwingService] JSON ledger write failed: {exc}")

    def _ledger_symbols(self) -> set:
        """Return the set of all symbols ever ordered by the system."""
        return {e["symbol"] for e in self._orders_ledger}

    def _ledger_entry(self, symbol: str) -> Optional[dict]:
        """Return the most recent ledger entry for a symbol."""
        matches = [e for e in self._orders_ledger if e["symbol"] == symbol]
        return matches[-1] if matches else None

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

        # Regime gate — pause trading in unfavorable market conditions
        try:
            from backend.services.regime_service import detect_market_regime
            regime = await detect_market_regime()
            if not regime.get("should_trade", True):
                logger.warning(
                    f"[SwingAutopilot] PAUSED — {regime['regime']} regime "
                    f"(confidence {regime.get('confidence', 0):.0%}, "
                    f"momentum win rate {regime.get('momentum_winrate', 0):.0%})"
                )
                self._autopilot_last_run = datetime.now(_IST)
                self._autopilot_last_result = {
                    "run_time":       self._autopilot_last_run.isoformat(),
                    "signals_found":  0,
                    "executed_count": 0,
                    "executed":       [],
                    "skipped_reason": f"Regime gate: {regime['regime']} ({regime.get('confidence', 0):.0%} conf)",
                    "regime_warning": regime.get("recommendation", "Trading paused due to unfavorable regime"),
                    "regime": regime,
                    "nifty_bullish":  regime["regime"] == "trending_up",
                }
                return self._autopilot_last_result
        except Exception as exc:
            logger.error(f"[SwingAutopilot] Regime check failed: {exc} — proceeding with scan")

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

        # ── Portfolio optimization: allocate capital optimally across signals ──
        from backend.services.portfolio_optimizer import get_portfolio_optimizer

        eligible = [s for s in signals if s.symbol not in self._swing_positions]
        if not eligible:
            logger.info("[SwingAutopilot] No eligible signals after filtering.")
            self._autopilot_last_run = datetime.now(_IST)
            self._autopilot_last_result = {
                "run_time":       self._autopilot_last_run.isoformat(),
                "signals_found":  len(signals),
                "executed_count": 0,
                "executed":       [],
                "regime_warning": regime_info.get("warning", ""),
                "nifty_bullish":  regime_info.get("bullish", True),
            }
            return self._autopilot_last_result

        # Prepare signal dicts for optimizer
        signal_dicts = [
            {
                "symbol": s.symbol,
                "confidence": s.confidence,
                "entry_price": s.entry_price,
                "stop_loss": s.stop_loss,
                "target1": s.target1,
            }
            for s in eligible[:slots_free]
        ]

        # Use configured optimizer method
        optimizer = get_portfolio_optimizer(method=self._autopilot_optimizer_method)
        total_budget = self._autopilot_capital_per_trade * slots_free
        allocations = optimizer.optimize(signal_dicts, total_budget, max_positions=slots_free)

        # Execute positions with optimized capital allocation
        executed = []
        for sig in eligible[:slots_free]:
            if sig.symbol not in allocations:
                continue

            allocated_capital = allocations[sig.symbol]
            qty = self._calculate_qty_by_capital(sig.entry_price, allocated_capital)
            if qty <= 0:
                continue

            if self._autopilot_mode == "paper":
                oid = self._open_paper_position(sig, qty)
            else:
                oid = await self._place_live_order(sig, qty)

            if oid:
                invested = round(qty * sig.entry_price, 2)
                executed.append({
                    "symbol":         sig.symbol,
                    "order_id":       oid,
                    "qty":            qty,
                    "entry":          sig.entry_price,
                    "sl":             sig.stop_loss,
                    "target1":        sig.target1,
                    "target2":        sig.target2,
                    "invested":       invested,
                    "allocated":      round(allocated_capital, 2),
                    "confidence":     sig.confidence,
                })
                logger.info(
                    f"[SwingAutopilot] {sig.symbol}: allocated=₹{allocated_capital:.0f}, "
                    f"qty={qty}, entry=₹{sig.entry_price:.2f}, invested=₹{invested:.2f} "
                    f"(confidence={sig.confidence:.1%})"
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

    async def sync_from_broker(self) -> dict:
        """
        Reconcile local swing state with Angel One.

        Rules:
        - Already tracked position → update qty/price from holdings (always safe)
        - NOT tracked + bought via system TODAY (appears in today's completed DELIVERY orders)
          → import (recovery after server restart on same day)
        - NOT tracked + NOT in today's orders → skip (personal portfolio, not touched)
        """
        if self.angel_client is None:
            return {"error": "Broker not connected"}

        from data.nifty50_universe import NIFTY100_UNIVERSE
        universe_symbols = {s["symbol"]: s for s in NIFTY100_UNIVERSE}

        loop = asyncio.get_event_loop()

        # 1. Symbols the system has ever ordered (ledger is the source of truth)
        system_symbols = self._ledger_symbols()
        fresh_deploy   = len(system_symbols) == 0 and len(self._swing_positions) == 0
        logger.info(
            f"[SwingSync] Ledger: {len(system_symbols)} symbol(s) | fresh_deploy={fresh_deploy}"
        )

        # 2. Holdings → current qty / avg price from demat
        try:
            holdings = await loop.run_in_executor(None, self.angel_client.get_holdings)
        except Exception as exc:
            logger.error(f"[SwingSync] get_holdings failed: {exc}")
            return {"error": str(exc)}

        holdings_map: dict = {
            h.get("tradingsymbol", "").replace("-EQ", "").upper(): h
            for h in (holdings or [])
            if int(h.get("quantity", 0) or 0) > 0
        }

        imported, updated, skipped, orphaned = [], [], [], []

        # 3. Candidates = already tracked + anything in ledger that's still in demat
        # SAFETY: never import holdings that aren't in the ledger — that's personal portfolio
        if not system_symbols and not self._swing_positions:
            logger.warning(
                "[SwingSync] Ledger is empty and no tracked positions — "
                "nothing to sync. This usually means the database ledger hasn't "
                "recorded any orders yet, or this is the first ever run."
            )
            return {
                "imported":     [],
                "updated":      [],
                "orphaned":     [],
                "skipped":      list(holdings_map.keys()),
                "fresh_deploy": True,
                "message":      (
                    "Ledger is empty — cannot safely identify which holdings were bought by "
                    "this system. No positions imported (your personal portfolio is safe). "
                    "To recover: manually execute the stocks the system previously bought "
                    "using the signal table, or wait for the autopilot to re-enter them."
                ),
            }
        candidates = set(self._swing_positions.keys()) | (system_symbols & set(holdings_map.keys()))
        for symbol in candidates:
            if symbol not in universe_symbols:
                continue
            h = holdings_map.get(symbol)
            if h is None:
                continue

            qty    = int(h.get("quantity", 0) or 0)
            avg_px = float(h.get("averageprice", 0) or 0)
            ltp    = float(h.get("ltp", avg_px) or avg_px)
            if qty <= 0:
                continue

            stock_info = universe_symbols[symbol]

            # If Angel One's ltp == avg_px (common after market close), fetch closing price via yfinance
            if ltp == avg_px and stock_info.get("yf"):
                try:
                    import yfinance as yf
                    df_yf = await loop.run_in_executor(
                        None,
                        lambda t=stock_info["yf"]: yf.download(t, period="2d", interval="1d",
                                                                progress=False, auto_adjust=True)
                    )
                    if df_yf is not None and not df_yf.empty:
                        if hasattr(df_yf.columns, "get_level_values"):
                            df_yf.columns = df_yf.columns.get_level_values(0)
                        df_yf.columns = [c.lower() for c in df_yf.columns]
                        yf_close = float(df_yf["close"].iloc[-1])
                        if yf_close > 0:
                            ltp = yf_close
                            logger.debug(f"[SwingSync] {symbol}: used yfinance close ₹{ltp:.2f} (AO ltp=avg_px)")
                except Exception as _yf_exc:
                    logger.debug(f"[SwingSync] {symbol}: yfinance fallback failed: {_yf_exc}")

            if symbol in self._swing_positions:
                # Always refresh qty and live price for tracked positions
                existing = self._swing_positions[symbol]
                if existing["qty"] != qty:
                    logger.info(f"[SwingSync] {symbol}: qty {existing['qty']} → {qty}")
                    existing["qty"] = qty
                existing["current_price"]  = round(ltp, 2)
                existing["unrealized_pnl"] = round((ltp - existing["entry_price"]) * qty, 2)
                existing["pnl_pct"]        = round((ltp - existing["entry_price"]) / existing["entry_price"] * 100, 2) if existing["entry_price"] > 0 else 0.0
                # Anything found in broker demat is a real (live) position
                if existing.get("mode") != "live":
                    logger.info(f"[SwingSync] {symbol}: mode {existing['mode']}→live (confirmed in broker demat)")
                    existing["mode"] = "live"
                updated.append(symbol)
            else:
                # Recover from ledger — use original entry price from ledger if available
                ledger_entry = self._ledger_entry(symbol)
                entry_price  = float(ledger_entry["entry_price"]) if ledger_entry else avg_px
                sig = await self._fetch_signal_on_demand(symbol)
                sl  = sig.stop_loss if sig else round(entry_price * 0.97, 2)
                t1  = sig.target1   if sig else round(entry_price * 1.06, 2)
                t2  = sig.target2   if sig else round(entry_price * 1.09, 2)
                entry_date = ledger_entry["date"] if ledger_entry else datetime.now(_IST).strftime("%Y-%m-%d")
                order_id   = ledger_entry["order_id"] if ledger_entry else f"RECOVERED-{symbol}"
                # Resolve token now so refresh_position_prices can get live LTP immediately
                token = await self._resolve_token(symbol)
                self._swing_positions[symbol] = {
                    "order_id":       order_id,
                    "symbol":         symbol,
                    "name":           stock_info["name"],
                    "sector":         stock_info.get("sector", ""),
                    "yf_ticker":      stock_info["yf"],
                    "entry_price":    round(entry_price, 2),
                    "current_price":  round(ltp, 2),
                    "qty":            qty,
                    "stop_loss":      sl,
                    "target1":        t1,
                    "target2":        t2,
                    "entry_date":     entry_date,
                    "unrealized_pnl": round((ltp - entry_price) * qty, 2),
                    "pnl_pct":        round((ltp - entry_price) / entry_price * 100, 2) if entry_price > 0 else 0.0,
                    "status":         "open",
                    "mode":           "live",   # in broker demat = real position regardless of how it was placed
                    "token":          token if token != "0" else "",
                    "confidence":     0.5,
                    "regime":         "recovered",
                }
                logger.info(f"[SwingSync] Recovered {symbol} from broker: qty={qty} entry=₹{entry_price:.2f} cmp=₹{ltp:.2f}")
                imported.append(symbol)

        # 4. Report live positions not found in broker holdings
        for symbol, pos in self._swing_positions.items():
            if pos.get("mode") == "live" and symbol not in holdings_map:
                orphaned.append(symbol)
                logger.warning(f"[SwingSync] {symbol} tracked as live but not in holdings — sold externally?")

        # 5. Demat stocks that were skipped (not in ledger = personal portfolio)
        for symbol in holdings_map:
            if symbol in universe_symbols and symbol not in system_symbols and symbol not in self._swing_positions:
                skipped.append(symbol)

        if imported or updated:
            self._last_ltp_refresh = None  # force fresh LTP on next positions poll
            self._save_state()

        return {
            "imported":     imported,
            "updated":      updated,
            "orphaned":     orphaned,
            "skipped":      skipped,
            "fresh_deploy": fresh_deploy,
            "message":      "",
        }

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
                elif pos.get("yf_ticker"):
                    # yfinance fallback — used when market is closed or token unavailable
                    try:
                        import yfinance as yf
                        df_yf = await loop.run_in_executor(
                            None,
                            lambda t=pos["yf_ticker"]: yf.download(
                                t, period="2d", interval="1d", progress=False, auto_adjust=True
                            )
                        )
                        if df_yf is not None and not df_yf.empty:
                            if hasattr(df_yf.columns, "get_level_values"):
                                df_yf.columns = df_yf.columns.get_level_values(0)
                            df_yf.columns = [c.lower() for c in df_yf.columns]
                            yf_close = float(df_yf["close"].iloc[-1])
                            if yf_close > 0:
                                entry = pos["entry_price"]
                                qty   = pos["qty"]
                                pos["current_price"]  = round(yf_close, 2)
                                pos["unrealized_pnl"] = round((yf_close - entry) * qty, 2)
                                pos["pnl_pct"]        = round((yf_close - entry) / entry * 100, 2)
                                pos["last_updated"]   = now.isoformat()
                                logger.debug(f"[SwingService] {symbol} yfinance close=₹{yf_close:.2f} P&L={pos['pnl_pct']:+.2f}%")
                    except Exception as _yf_exc:
                        logger.debug(f"[SwingService] {symbol} yfinance fallback failed: {_yf_exc}")
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

    # ------------------------------------------------------------------
    # Real-time intraday SL monitoring
    # ------------------------------------------------------------------

    async def attach_live_feed(self, feed) -> None:
        """Wire up a LiveFeed instance for real-time tick updates."""
        self._live_feed = feed
        feed.subscribe(self._on_swing_tick)
        await self._subscribe_open_positions()
        logger.info("[SwingService] Live feed attached for intraday SL monitoring.")

    def _on_swing_tick(self, tick: dict) -> None:
        """Callback invoked by LiveFeed on every incoming tick (runs in WS thread)."""
        token = str(tick.get("token", ""))
        ltp   = float(tick.get("ltp", 0) or 0)
        if not (token and ltp > 0):
            return
        # Sanity-check: if the tick LTP is > 50× the known entry price for this
        # token, it's almost certainly a paise value that wasn't converted.
        symbol = self._token_to_symbol.get(token)
        if symbol:
            pos = self._swing_positions.get(symbol)
            if pos and pos.get("entry_price", 0) > 0:
                if ltp > pos["entry_price"] * 50:
                    ltp = ltp / 100.0
                    logger.warning(
                        f"[SwingTick] {symbol}: raw tick looked like paise "
                        f"({ltp * 100:.0f}) — auto-divided to ₹{ltp:.2f}"
                    )
        self._realtime_ltps[token] = ltp

    async def _subscribe_open_positions(self) -> None:
        """Subscribe open swing positions to the live feed — skips already-subscribed tokens."""
        if self._live_feed is None:
            return
        to_subscribe = []
        for symbol, pos in list(self._swing_positions.items()):
            token = pos.get("token") or await self._resolve_token(symbol)
            if token and token != "0":
                pos["token"] = token
                self._token_to_symbol[token] = symbol
                if token not in self._feed_subscribed_tokens:
                    to_subscribe.append({"exchange_type": 1, "token": token})
        if to_subscribe:
            self._live_feed.add_symbols(to_subscribe)
            for s in to_subscribe:
                self._feed_subscribed_tokens.add(s["token"])
            logger.info(f"[SwingService] Subscribed {len(to_subscribe)} new position token(s) to live feed.")

    async def check_sl_realtime(self) -> List[str]:
        """
        Check all open positions against SL / targets using live WebSocket LTP.
        Falls back to REST get_ltp() if WebSocket data is absent.
        Returns list of symbols where an exit was triggered.
        """
        triggered: List[str] = []

        for symbol, pos in list(self._swing_positions.items()):
            if symbol in self._sl_triggered:
                continue

            token = pos.get("token", "")
            ltp   = self._realtime_ltps.get(token, 0.0)

            # REST fallback when WebSocket hasn't delivered a tick yet
            if ltp <= 0 and self.angel_client and token:
                try:
                    loop  = asyncio.get_event_loop()
                    eq_sym = f"{symbol}-EQ"
                    ltp = await loop.run_in_executor(
                        None,
                        lambda s=eq_sym, t=token: self.angel_client.get_ltp("NSE", s, t)
                    ) or 0.0
                except Exception:
                    pass

            if ltp <= 0:
                continue

            # Update live P&L
            entry = pos["entry_price"]
            qty   = pos["qty"]
            pos["current_price"]  = round(ltp, 2)
            pos["unrealized_pnl"] = round((ltp - entry) * qty, 2)
            pos["pnl_pct"]        = round((ltp - entry) / entry * 100, 2) if entry > 0 else 0.0

            sl       = pos["stop_loss"]
            t1       = pos["target1"]
            t2       = pos["target2"]
            trailing = pos.get("trailing_active", False)

            def _exit(reason: str, exit_px: float) -> None:
                pnl = round((exit_px - entry) * qty, 2)
                logger.warning(
                    f"[RealtimeSL] {symbol} {reason} — "
                    f"LTP=₹{ltp:.2f} | exit≈₹{exit_px:.2f} | P&L=₹{pnl:.2f}"
                )
                pos["status"]       = "closed_target" if "TARGET" in reason else "closed_sl"
                pos["exit_price"]   = round(exit_px, 2)
                pos["realized_pnl"] = pnl
                self._sl_triggered.add(symbol)
                triggered.append(symbol)

            if ltp <= sl:
                _exit("TRAILING_SL HIT" if trailing else "SL HIT", ltp)
            elif ltp >= t2:
                _exit("TARGET2 HIT 🎯", t2)
            elif not trailing and ltp >= t1:
                pos["stop_loss"]       = entry   # trail SL to breakeven
                pos["trailing_active"] = True
                logger.info(
                    f"[RealtimeSL] {symbol} TARGET1 HIT ✓ — "
                    f"LTP=₹{ltp:.2f} ≥ T1=₹{t1:.2f} — trailing SL → ₹{entry:.2f} (breakeven)"
                )
                self._save_state()
                continue

            if symbol in self._sl_triggered:
                # Place live exit order if applicable
                if pos.get("mode") == "live" and self.angel_client:
                    await self._place_exit_order(pos)
                # Remove from active positions
                self._swing_positions.pop(symbol, None)
                # Unsubscribe token from live feed
                if self._live_feed and token:
                    try:
                        self._live_feed.unsubscribe([{"exchange_type": 1, "token": token}])
                    except Exception:
                        pass
                self._token_to_symbol.pop(token, None)
                self._feed_subscribed_tokens.discard(token)
                self._save_state()

        return triggered

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
        self._append_to_ledger(sig.symbol, pos_id, qty, sig.entry_price, "paper")
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
            # 'str' object has no attribute 'get' means Angel One session expired
            if "str" in str(exc) and "get" in str(exc):
                logger.error(
                    "[SwingService] Balance check suggests expired session (API returned string). "
                    "Attempting broker reconnect before placing order…"
                )
                try:
                    loop2 = asyncio.get_event_loop()
                    await loop2.run_in_executor(None, self.angel_client.connect)
                    logger.info("[SwingService] Broker reconnected.")
                except Exception as reconnect_exc:
                    logger.error(f"[SwingService] Reconnect failed: {reconnect_exc}")
                    return None
            else:
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
                self._append_to_ledger(sig.symbol, order_id, qty, sig.entry_price, "live")
                self._save_state()
                return order_id
        except Exception as exc:
            err_str = str(exc)
            # AG8001 = Angel One "Invalid Token" → session expired; reconnect and retry once
            if "AG8001" in err_str or "Invalid Token" in err_str:
                logger.warning(
                    f"[SwingService] AG8001 Invalid Token for {sig.symbol} — "
                    f"session expired. Reconnecting and retrying…"
                )
                try:
                    loop_rc = asyncio.get_event_loop()
                    await loop_rc.run_in_executor(None, self.angel_client.connect)
                    logger.info("[SwingService] Broker reconnected after AG8001.")
                    # Single retry after reconnect
                    order_id = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: self.angel_client.place_order(
                            variety="NORMAL", exchange="NSE", symbol=eq_symbol,
                            token=token, qty=qty, order_type="MARKET",
                            transaction_type="BUY", price=0.0,
                            trigger_price=0.0, product="DELIVERY",
                        )
                    )
                    if order_id:
                        self._swing_positions[sig.symbol] = {
                            "order_id": order_id, "symbol": sig.symbol,
                            "name": sig.name, "sector": sig.sector,
                            "yf_ticker": sig.yf_ticker, "entry_price": sig.entry_price,
                            "current_price": sig.entry_price, "qty": qty,
                            "stop_loss": sig.stop_loss, "target1": sig.target1,
                            "target2": sig.target2,
                            "entry_date": datetime.now(_IST).strftime("%Y-%m-%d"),
                            "unrealized_pnl": 0.0, "pnl_pct": 0.0,
                            "status": "open", "mode": "live", "token": token,
                            "confidence": sig.confidence, "regime": sig.regime,
                        }
                        logger.info(f"[SwingService] Live CNC order placed after reconnect: {sig.symbol} qty={qty} order_id={order_id}")
                        self._append_to_ledger(sig.symbol, order_id, qty, sig.entry_price, "live")
                        self._save_state()
                        return order_id
                except Exception as retry_exc:
                    logger.error(f"[SwingService] Order retry after reconnect failed for {sig.symbol}: {retry_exc}")
            else:
                logger.error(f"[SwingService] Live order failed for {sig.symbol}: {exc}")

        return None

    async def _place_exit_order(self, pos: dict) -> None:
        """Place a live CNC sell order to exit a position."""
        if self.angel_client is None:
            return
        symbol = pos["symbol"]

        # ── HARD SAFETY GUARD ──────────────────────────────────────────────
        # Never sell a stock the system didn't explicitly place a BUY order for.
        # This prevents accidentally selling personal portfolio holdings.
        if symbol not in self._ledger_symbols():
            logger.error(
                f"[SAFETY BLOCK] Refusing to sell {symbol} — "
                f"not found in system orders ledger. "
                f"This stock was NOT bought by this system. Sell cancelled."
            )
            return
        # ──────────────────────────────────────────────────────────────────
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


