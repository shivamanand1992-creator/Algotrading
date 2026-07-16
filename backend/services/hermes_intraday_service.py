"""
Hermes Intraday Trading Service
Fully automated AI-powered intraday trading using Hermes Agent

Monitors market every 30 seconds during trading hours (9:15 AM - 3:15 PM)
Makes autonomous decisions to enter/exit positions
Sends Telegram alerts for all actions
"""

import asyncio
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional
import pytz
import pandas as pd
from loguru import logger
from pathlib import Path
import json

from backend.services.hermes_agent import HermesAgent


_IST = pytz.timezone("Asia/Kolkata")
_STATE_FILE = Path(__file__).parent.parent.parent / "logs" / "hermes_intraday_state.json"


class HermesIntradayService:
    """Fully automated intraday trading powered by Hermes Agent"""

    def __init__(self, config: dict, angel_client=None):
        """
        Initialize Hermes Intraday Service

        Args:
            config: Trading configuration
            angel_client: Angel One broker connection
        """
        self.config = config
        self.angel_client = angel_client

        # Hermes Agent
        self.agent = HermesAgent()

        # Configuration
        hermes_cfg = config.get("hermes", {})
        self.enabled = hermes_cfg.get("enabled", False)
        self.instrument = hermes_cfg.get("instrument", "NIFTYBEES")
        self.max_trades_per_day = hermes_cfg.get("max_trades_per_day", 4)
        self.capital_per_trade = hermes_cfg.get("capital_per_trade", 10000.0)
        self.min_confidence = hermes_cfg.get("min_confidence", 0.7)

        # State
        self.position: Optional[Dict] = None  # Current open position
        self.trades_today: List[Dict] = []
        self.daily_pnl: float = 0.0
        self.last_analysis_time: Optional[datetime] = None

        # Trading hours
        self.market_open = time(9, 15)   # 9:15 AM
        self.market_close = time(15, 10)  # 3:10 PM (exit by 3:15 PM)

        self._load_state()
        logger.info(f"[Hermes] Initialized - enabled={self.enabled}, instrument={self.instrument}")

    def _load_state(self):
        """Load state from disk"""
        if not _STATE_FILE.exists():
            return

        try:
            data = json.loads(_STATE_FILE.read_text())
            today = datetime.now(_IST).strftime("%Y-%m-%d")

            # Only restore if same trading day
            if data.get("date") == today:
                self.position = data.get("position")
                self.trades_today = data.get("trades_today", [])
                self.daily_pnl = data.get("daily_pnl", 0.0)
                logger.info(f"[Hermes] State loaded: {len(self.trades_today)} trades, P&L=₹{self.daily_pnl:.2f}")
        except Exception as e:
            logger.warning(f"[Hermes] Failed to load state: {e}")

    def _save_state(self):
        """Save state to disk"""
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "date": datetime.now(_IST).strftime("%Y-%m-%d"),
            "position": self.position,
            "trades_today": self.trades_today,
            "daily_pnl": self.daily_pnl,
            "last_analysis": self.last_analysis_time.isoformat() if self.last_analysis_time else None,
        }
        _STATE_FILE.write_text(json.dumps(state, indent=2, default=str))

    def is_trading_hours(self) -> bool:
        """Check if within trading window"""
        now = datetime.now(_IST).time()
        return self.market_open <= now <= self.market_close

    def is_market_closed(self) -> bool:
        """Check if market is closed"""
        now = datetime.now(_IST).time()
        return now > self.market_close

    async def run_analysis_cycle(self) -> Dict:
        """
        Single analysis cycle - called every 30 seconds

        Returns:
            Dict with cycle results
        """
        if not self.enabled:
            return {"status": "disabled"}

        if not self.is_trading_hours():
            return {"status": "outside_trading_hours"}

        try:
            # Fetch current market data
            market_data = await self._fetch_market_data()

            # PRIORITY: Monitor existing position for SL/Target hits
            if self.position:
                ltp = market_data["price"]
                position_result = await self._monitor_position(ltp)
                if position_result.get("action") == "exit":
                    self.last_analysis_time = datetime.now(_IST)
                    self._save_state()
                    return {
                        "status": "success",
                        "decision": {"action": "MONITORING_POSITION"},
                        "execution": position_result,
                        "position": None,
                        "daily_pnl": self.daily_pnl,
                    }

            # Get Hermes decision
            decision = await self.agent.analyze_market(market_data)

            # Execute decision if high confidence
            if decision["confidence"] >= self.min_confidence:
                result = await self._execute_decision(decision, market_data)
            else:
                result = {"action": "ignored", "reason": f"Low confidence ({decision['confidence']:.2f})"}

            self.last_analysis_time = datetime.now(_IST)
            self._save_state()

            return {
                "status": "success",
                "decision": decision,
                "execution": result,
                "position": self.position,
                "daily_pnl": self.daily_pnl,
            }

        except Exception as e:
            logger.error(f"[Hermes] Analysis cycle failed: {e}")
            return {"status": "error", "error": str(e)}

    async def _monitor_position(self, ltp: float) -> Dict:
        """
        Monitor open position for target/SL hits

        Args:
            ltp: Last traded price

        Returns:
            Dict with action taken
        """
        if not self.position:
            return {"action": "no_position"}

        entry = self.position["entry_price"]
        sl = self.position["stop_loss"]
        target = self.position["target"]

        # Check if target hit
        if ltp >= target:
            logger.info(f"[Hermes] TARGET HIT: LTP ₹{ltp:.2f} >= Target ₹{target:.2f}")
            market_data = {"price": ltp}
            return await self._exit_position(market_data, reason="target_hit")

        # Check if stop loss hit (backup - broker SL should trigger first)
        if ltp <= sl:
            logger.warning(f"[Hermes] STOP LOSS HIT: LTP ₹{ltp:.2f} <= SL ₹{sl:.2f}")
            market_data = {"price": ltp}
            return await self._exit_position(market_data, reason="stop_loss_hit")

        # Position still open
        pnl = (ltp - entry) * self.position["qty"]
        return {"action": "monitoring", "unrealized_pnl": pnl}

    async def _fetch_market_data(self) -> Dict:
        """Fetch real-time market data for analysis"""

        # Get current quote
        if self.angel_client:
            try:
                # Resolve token
                token = self.angel_client.search_scrip("NSE", self.instrument)
                if not token:
                    raise ValueError(f"Token not found for {self.instrument}")

                # Get LTP + OHLC
                quote = self.angel_client.get_quote("NSE", self.instrument, token)

                # Get recent candles for indicators (last 20 candles of 5min)
                from_date = (datetime.now(_IST) - pd.Timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
                to_date = datetime.now(_IST).strftime("%Y-%m-%d %H:%M")

                df = self.angel_client.get_historical_data(
                    exchange="NSE",
                    symbol_token=token,
                    interval="FIVE_MINUTE",
                    from_date=from_date,
                    to_date=to_date,
                )

                # Calculate indicators
                rsi = self._calculate_rsi(df) if len(df) >= 14 else 50.0
                macd = self._calculate_macd(df) if len(df) >= 26 else 0.0
                volume_ma = df["volume"].tail(10).mean() if len(df) >= 10 else df["volume"].mean()

                return {
                    "symbol": self.instrument,
                    "price": quote["ltp"],
                    "prev_high": quote["high"],
                    "prev_low": quote["low"],
                    "day_open": quote["open"],
                    "rsi": rsi,
                    "macd": macd,
                    "volume_current": df["volume"].iloc[-1] if len(df) > 0 else 0,
                    "volume_ma": volume_ma,
                    "account_balance": self._get_account_balance(),
                    "daily_pnl": self.daily_pnl,
                    "open_positions": 1 if self.position else 0,
                    "trades_today": len(self.trades_today),
                    "max_trades": self.max_trades_per_day,
                }

            except Exception as e:
                logger.error(f"[Hermes] Failed to fetch live data: {e}")

        # Fallback: demo data
        logger.warning("[Hermes] Using demo market data (broker not connected)")
        return {
            "symbol": self.instrument,
            "price": 100.0,
            "prev_high": 101.5,
            "prev_low": 98.5,
            "day_open": 99.0,
            "rsi": 55.0,
            "macd": 0.05,
            "volume_current": 100000,
            "volume_ma": 80000,
            "account_balance": 50000,
            "daily_pnl": self.daily_pnl,
            "open_positions": 1 if self.position else 0,
            "trades_today": len(self.trades_today),
            "max_trades": self.max_trades_per_day,
        }

    async def _execute_decision(self, decision: Dict, market_data: Dict) -> Dict:
        """Execute Hermes trading decision"""

        action = decision["action"]

        # BUY: Enter new position
        if action == "BUY" and not self.position:
            if len(self.trades_today) >= self.max_trades_per_day:
                logger.info(f"[Hermes] Max trades reached ({self.max_trades_per_day})")
                return {"action": "skipped", "reason": "max_trades_reached"}

            return await self._enter_position(decision, market_data)

        # CLOSE_POSITION: Exit current position
        elif action == "CLOSE_POSITION" and self.position:
            return await self._exit_position(market_data, reason="agent_decision")

        # HOLD / WAIT: No action
        else:
            return {"action": "no_action", "reason": f"Current state doesn't match {action}"}

    async def _enter_position(self, decision: Dict, market_data: Dict) -> Dict:
        """Enter a new intraday position"""

        entry_price = decision.get("entry_price") or market_data["price"]
        stop_loss = decision.get("stop_loss") or entry_price * 0.994  # 0.6% SL
        target = decision.get("target") or entry_price * 1.009  # 0.9% target

        # Calculate quantity based on capital
        qty = int(self.capital_per_trade / entry_price)
        if qty == 0:
            return {"action": "skipped", "reason": "qty_zero"}

        # Place order (MIS intraday)
        if self.angel_client:
            try:
                token = self.angel_client.search_scrip("NSE", self.instrument)

                # 1. Place BUY order (entry)
                entry_order_id = self.angel_client.place_order(
                    variety="NORMAL",
                    exchange="NSE",
                    symbol=f"{self.instrument}-EQ",
                    token=token,
                    qty=qty,
                    order_type="MARKET",
                    transaction_type="BUY",
                    product="INTRADAY",  # MIS
                )

                logger.info(f"[Hermes] Entry order placed: {entry_order_id}")
                await asyncio.sleep(2)  # Wait for order execution

                # 2. Place STOP-LOSS order (protection)
                try:
                    sl_order_id = self.angel_client.place_order(
                        variety="STOPLOSS",
                        exchange="NSE",
                        symbol=f"{self.instrument}-EQ",
                        token=token,
                        qty=qty,
                        order_type="STOPLOSS_LIMIT",
                        transaction_type="SELL",
                        product="INTRADAY",
                        price=stop_loss,  # Limit price
                        trigger_price=stop_loss,  # Trigger price
                    )
                    logger.success(f"[Hermes] SL order placed @ ₹{stop_loss:.2f}: {sl_order_id}")
                except Exception as sl_err:
                    logger.error(f"[Hermes] SL order failed (position unprotected!): {sl_err}")
                    sl_order_id = None

                self.position = {
                    "order_id": entry_order_id,
                    "sl_order_id": sl_order_id,
                    "symbol": self.instrument,
                    "entry_price": entry_price,
                    "entry_time": datetime.now(_IST).isoformat(),
                    "qty": qty,
                    "stop_loss": stop_loss,
                    "target": target,
                    "setup_type": decision.get("setup_type", "unknown"),
                    "mode": "live",
                }

                logger.success(f"[Hermes] ENTRY: {self.instrument} {qty}qty @ ₹{entry_price:.2f} | SL @ ₹{stop_loss:.2f}")
                await self._send_telegram_alert(
                    f"🟢 HERMES ENTRY\n"
                    f"Stock: {self.instrument}\n"
                    f"Qty: {qty}\n"
                    f"Entry: ₹{entry_price:.2f}\n"
                    f"SL: ₹{stop_loss:.2f} {'✅' if sl_order_id else '⚠️ FAILED'}\n"
                    f"Target: ₹{target:.2f}\n"
                    f"Setup: {decision.get('setup_type', 'N/A')}\n"
                    f"Confidence: {decision['confidence']:.0%}"
                )

                self._save_state()
                return {"action": "entry", "order_id": entry_order_id, "sl_order_id": sl_order_id, "qty": qty}

            except Exception as e:
                logger.error(f"[Hermes] Order placement failed: {e}")
                return {"action": "failed", "error": str(e)}
        else:
            # Paper mode
            self.position = {
                "order_id": f"PAPER_{datetime.now(_IST).strftime('%H%M%S')}",
                "symbol": self.instrument,
                "entry_price": entry_price,
                "entry_time": datetime.now(_IST).isoformat(),
                "qty": qty,
                "stop_loss": stop_loss,
                "target": target,
                "setup_type": decision.get("setup_type", "unknown"),
                "mode": "paper",
            }
            logger.info(f"[Hermes] PAPER ENTRY: {self.instrument} {qty}qty @ ₹{entry_price:.2f}")
            self._save_state()
            return {"action": "paper_entry", "qty": qty}

    async def _exit_position(self, market_data: Dict, reason: str = "manual") -> Dict:
        """Exit current position"""

        if not self.position:
            return {"action": "no_position"}

        exit_price = market_data["price"]
        qty = self.position["qty"]
        pnl = (exit_price - self.position["entry_price"]) * qty

        # Place exit order
        if self.angel_client and self.position["mode"] == "live":
            try:
                token = self.angel_client.search_scrip("NSE", self.instrument)

                # 1. Cancel SL order if it exists (to avoid double exit)
                sl_order_id = self.position.get("sl_order_id")
                if sl_order_id:
                    try:
                        self.angel_client.cancel_order(variety="STOPLOSS", order_id=sl_order_id)
                        logger.info(f"[Hermes] Cancelled SL order: {sl_order_id}")
                    except Exception as cancel_err:
                        logger.warning(f"[Hermes] SL cancel failed (may already be executed): {cancel_err}")

                # 2. Place MARKET SELL order
                order_id = self.angel_client.place_order(
                    variety="NORMAL",
                    exchange="NSE",
                    symbol=f"{self.instrument}-EQ",
                    token=token,
                    qty=qty,
                    order_type="MARKET",
                    transaction_type="SELL",
                    product="INTRADAY",
                )

                logger.success(f"[Hermes] EXIT: {self.instrument} @ ₹{exit_price:.2f} | P&L=₹{pnl:.2f}")

            except Exception as e:
                logger.error(f"[Hermes] Exit order failed: {e}")
                return {"action": "exit_failed", "error": str(e)}
        else:
            logger.info(f"[Hermes] PAPER EXIT: {self.instrument} @ ₹{exit_price:.2f} | P&L=₹{pnl:.2f}")

        # Record trade
        trade = {
            **self.position,
            "exit_price": exit_price,
            "exit_time": datetime.now(_IST).isoformat(),
            "pnl": pnl,
            "pnl_pct": (pnl / (self.position["entry_price"] * qty)) * 100,
            "exit_reason": reason,
        }
        self.trades_today.append(trade)
        self.daily_pnl += pnl

        # Send alert
        await self._send_telegram_alert(
            f"{'🔴' if pnl < 0 else '🟢'} HERMES EXIT\n"
            f"Stock: {self.instrument}\n"
            f"Entry: ₹{self.position['entry_price']:.2f}\n"
            f"Exit: ₹{exit_price:.2f}\n"
            f"P&L: ₹{pnl:.2f} ({trade['pnl_pct']:.2f}%)\n"
            f"Reason: {reason}\n"
            f"Today's P&L: ₹{self.daily_pnl:.2f}"
        )

        self.position = None
        self._save_state()

        return {"action": "exit", "pnl": pnl, "trade": trade}

    async def force_exit_all(self):
        """Force exit all positions at market close"""
        if self.position:
            market_data = await self._fetch_market_data()
            await self._exit_position(market_data, reason="market_close")

    def get_status(self) -> Dict:
        """Get current Hermes service status"""
        return {
            "enabled": self.enabled,
            "instrument": self.instrument,
            "position": self.position,
            "trades_today": len(self.trades_today),
            "daily_pnl": self.daily_pnl,
            "last_analysis": self.last_analysis_time.isoformat() if self.last_analysis_time else None,
            "capital_per_trade": self.capital_per_trade,
            "max_trades_per_day": self.max_trades_per_day,
            "min_confidence": self.min_confidence,
        }

    def _calculate_rsi(self, df) -> float:
        """Calculate RSI(14)"""
        import pandas as pd
        delta = df["close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1] if len(rsi) > 0 else 50.0

    def _calculate_macd(self, df) -> float:
        """Calculate MACD histogram"""
        import pandas as pd
        ema12 = df["close"].ewm(span=12).mean()
        ema26 = df["close"].ewm(span=26).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9).mean()
        histogram = macd_line - signal_line
        return histogram.iloc[-1] if len(histogram) > 0 else 0.0

    def _get_account_balance(self) -> float:
        """Get available account balance"""
        if self.angel_client:
            try:
                funds = self.angel_client.get_funds()
                return float(funds.get("availablecash", 50000))
            except:
                pass
        return 50000.0

    async def _send_telegram_alert(self, message: str):
        """Send Telegram alert"""
        try:
            from backend.services.telegram_service import send_message
            await send_message(message)
        except Exception as e:
            logger.warning(f"[Hermes] Telegram alert failed: {e}")
