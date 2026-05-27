import sys
import asyncio
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta, timezone
from loguru import logger

sys.path.append(str(Path(__file__).parent.parent.parent))

from strategies.trend_strategy import TrendFollowingStrategy
from strategies.premium_strategy import PremiumSellingStrategy
from strategies.scalping_strategy import ScalpingStrategy
from backend.api.models.responses import StrategyStatus, TradeSignalResponse

# How often (seconds) each strategy loop checks for signals
STRATEGY_INTERVAL = 300   # 5 minutes


def _enrich_features(df) -> "pd.DataFrame":
    """
    Enrich a raw OHLCV DataFrame with the same features used during training:
      1. Technical indicators (EMA, RSI, MACD, ATR, Bollinger, etc.)
      2. Time-of-day features (hour, minute, minutes_since_open, …)
      3. India VIX features (vix_close, vix_change_5, vix_is_high, vix_is_low)
    Called synchronously in a thread executor so it doesn't block the event loop.
    """
    import numpy as np
    import pandas as pd
    import yfinance as yf
    from features.technical_indicators import TechnicalFeatureEngine

    # 1. Technical indicators
    engine = TechnicalFeatureEngine()
    df = engine.compute_all(df)

    # 2. Ensure a datetime index for time features
    if "timestamp" in df.columns:
        df = df.set_index("timestamp")
    df.index = pd.to_datetime(df.index)
    # Strip timezone so arithmetic works cleanly
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    # 3. Time features
    df["hour"]               = df.index.hour
    df["minute"]             = df.index.minute
    df["minutes_since_open"] = (df.index.hour - 9) * 60 + df.index.minute - 15
    df["minutes_to_close"]   = (15 * 60 + 30) - (df.index.hour * 60 + df.index.minute)
    df["is_first_30min"]     = (df["minutes_since_open"] <= 30).astype(int)
    df["is_last_30min"]      = (df["minutes_to_close"]   <= 30).astype(int)
    df["day_of_week"]        = df.index.dayofweek
    df["is_expiry_day"]      = (df.index.dayofweek == 3).astype(int)  # Thursday

    # 4. India VIX features
    try:
        vix = yf.Ticker("^INDIAVIX").history(period="10d", interval="15m")
        if vix is not None and not vix.empty:
            vix.index = pd.to_datetime(vix.index)
            if vix.index.tz is not None:
                vix.index = vix.index.tz_convert(None)
            vix = vix[["Close"]].rename(columns={"Close": "vix_close"})
            df = df.merge(vix, left_index=True, right_index=True, how="left")
            df["vix_close"]    = df["vix_close"].ffill().bfill()
            df["vix_change_5"] = df["vix_close"].pct_change(5)
            df["vix_is_high"]  = (df["vix_close"] > 20).astype(int)
            df["vix_is_low"]   = (df["vix_close"] < 12).astype(int)
    except Exception:
        # VIX unavailable — fill with neutral defaults so model still runs
        df["vix_close"]    = 15.0
        df["vix_change_5"] = 0.0
        df["vix_is_high"]  = 0
        df["vix_is_low"]   = 0

    # 5. Daily context features — same multi-timeframe columns used during training.
    # The price predictor expects daily_ema_20/50/200, daily_rsi, daily_above_200ema,
    # daily_trend, daily_weekly_ret.  Fetch 2yr daily NSEI from Yahoo Finance and
    # forward-fill onto each intraday bar by date.
    _daily_cols = [
        "daily_ema_20", "daily_ema_50", "daily_ema_200",
        "daily_rsi", "daily_above_200ema", "daily_trend", "daily_weekly_ret",
    ]
    try:
        raw_daily = yf.Ticker("^NSEI").history(period="730d", interval="1d")
        if raw_daily is not None and not raw_daily.empty:
            raw_daily.index = pd.to_datetime(raw_daily.index)
            if raw_daily.index.tz is not None:
                raw_daily.index = raw_daily.index.tz_convert(None)
            raw_daily.index = raw_daily.index.normalize()
            c = raw_daily["Close"]
            raw_daily["daily_ema_20"]  = c.ewm(span=20,  adjust=False).mean()
            raw_daily["daily_ema_50"]  = c.ewm(span=50,  adjust=False).mean()
            raw_daily["daily_ema_200"] = c.ewm(span=200, adjust=False).mean()
            delta = c.diff()
            gain  = delta.clip(lower=0).rolling(14).mean()
            loss  = (-delta.clip(upper=0)).rolling(14).mean()
            raw_daily["daily_rsi"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
            raw_daily["daily_above_200ema"] = (c > raw_daily["daily_ema_200"]).astype(int)
            ema_diff = (raw_daily["daily_ema_20"] - raw_daily["daily_ema_50"]) / raw_daily["daily_ema_50"]
            raw_daily["daily_trend"] = np.where(ema_diff > 0.003, 1,
                                       np.where(ema_diff < -0.003, -1, 0)).astype(int)
            raw_daily["daily_weekly_ret"] = c.pct_change(5)
            daily_ctx = raw_daily[_daily_cols].ffill().bfill()
            # Align daily values onto intraday bars by matching midnight date
            bar_dates = df.index.normalize()
            aligned = daily_ctx.reindex(bar_dates, method="ffill")
            aligned.index = df.index
            df = df.join(aligned, how="left", rsuffix="_daily_tmp")
            for col in _daily_cols:
                if col + "_daily_tmp" in df.columns:
                    df.drop(columns=[col + "_daily_tmp"], inplace=True)
            df[_daily_cols] = df[_daily_cols].ffill().bfill()
    except Exception:
        pass  # fill defaults below

    # Ensure all daily columns exist with neutral fallbacks
    for col in _daily_cols:
        if col not in df.columns or df[col].isna().all():
            if col in ("daily_ema_20", "daily_ema_50", "daily_ema_200"):
                df[col] = df["close"] if "close" in df.columns else 0.0
            elif col == "daily_rsi":
                df[col] = 50.0
            else:
                df[col] = 0

    return df

_IST = timezone(timedelta(hours=5, minutes=30))


def _is_market_open() -> bool:
    """Returns True only during NSE trading hours (Mon–Fri 09:15–15:30 IST)."""
    now = datetime.now(_IST)
    if now.weekday() >= 5:          # Saturday=5, Sunday=6
        return False
    t = (now.hour, now.minute)
    return (9, 15) <= t <= (15, 30)


def _seconds_until_next_open() -> int:
    """Seconds from now until next NSE open (09:15 IST, next weekday)."""
    now = datetime.now(_IST)
    # Start from today's open
    candidate = now.replace(hour=9, minute=15, second=0, microsecond=0)
    # If today's open is in the past or it's already after open, move to next day
    if candidate <= now:
        candidate += timedelta(days=1)
    # Skip weekends
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return max(1, int((candidate - now).total_seconds()))


class StrategyService:
    def __init__(self, config, order_manager, signal_generator):
        self.config           = config
        self.order_manager    = order_manager
        self.signal_generator = signal_generator

        self.available_strategies = {
            'trend': {
                'class':        TrendFollowingStrategy,
                'display_name': 'Trend Following',
                'description':  'Trades directional moves using EMA, RSI, MACD',
            },
            'premium': {
                'class':        PremiumSellingStrategy,
                'display_name': 'Premium Selling',
                'description':  'Short strangles in ranging markets',
            },
            'scalping': {
                'class':        ScalpingStrategy,
                'display_name': 'Scalping',
                'description':  '1-2 minute scalping strategy',
            },
        }

        # name -> { instance, mode, start_time, signals_count, task }
        self.running_strategies: Dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    async def get_all_strategies(self) -> List[StrategyStatus]:
        result = []
        for name, info in self.available_strategies.items():
            status, mode, uptime, signals = "stopped", None, None, 0
            if name in self.running_strategies:
                run = self.running_strategies[name]
                status  = "running"
                mode    = run['mode']
                uptime  = int((datetime.now() - run['start_time']).total_seconds())
                signals = run.get('signals_count', 0)
            result.append(StrategyStatus(
                name=name,
                display_name=info['display_name'],
                status=status,
                mode=mode,
                uptime_seconds=uptime,
                signals_generated=signals,
                active_positions=0,
                regime_suitability=None,
            ))
        return result

    # ------------------------------------------------------------------
    # Start / stop
    # ------------------------------------------------------------------

    async def start_strategy(self, name: str, mode: str) -> bool:
        if name not in self.available_strategies:
            raise ValueError(f"Unknown strategy: {name}")
        if name in self.running_strategies:
            raise ValueError(f"Strategy {name} is already running")

        strategy_class    = self.available_strategies[name]['class']
        strategy_instance = strategy_class(self.config)

        run_info: dict = {
            'instance':      strategy_instance,
            'mode':          mode,
            'start_time':    datetime.now(),
            'signals_count': 0,
            'task':          None,
        }
        self.running_strategies[name] = run_info

        # Launch background signal loop
        task = asyncio.create_task(
            self._signal_loop(name, strategy_instance, mode),
            name=f"strategy-{name}",
        )
        run_info['task'] = task
        task.add_done_callback(lambda t: self._on_task_done(name, t))

        logger.info(f"Strategy '{name}' started in {mode} mode.")
        return True

    async def stop_strategy(self, name: str) -> bool:
        if name not in self.running_strategies:
            raise ValueError(f"Strategy {name} is not running")

        run = self.running_strategies.pop(name)
        task: Optional[asyncio.Task] = run.get('task')
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        logger.info(f"Strategy '{name}' stopped.")
        return True

    # ------------------------------------------------------------------
    # Signal loop (background task per strategy)
    # ------------------------------------------------------------------

    async def _signal_loop(self, name: str, strategy_instance, mode: str) -> None:
        """Runs continuously, generating signals every STRATEGY_INTERVAL seconds."""
        logger.info(f"[{name}] Signal loop started (mode={mode})")
        while name in self.running_strategies:
            # Market hours gate — sleep until next NSE open if market is closed
            if not _is_market_open():
                secs = _seconds_until_next_open()
                logger.info(
                    f"[{name}] Market closed — sleeping {secs / 3600:.1f}h until next open."
                )
                try:
                    # Wake at most every hour to recheck (handles DST / holiday edge cases)
                    await asyncio.sleep(min(secs, 3600))
                except asyncio.CancelledError:
                    break
                continue

            try:
                await self._run_strategy_cycle(name, strategy_instance, mode)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{name}] Signal loop error: {e}")

            # Wait for next cycle; check cancellation
            try:
                await asyncio.sleep(STRATEGY_INTERVAL)
            except asyncio.CancelledError:
                break

        logger.info(f"[{name}] Signal loop exited.")

    async def _run_strategy_cycle(self, name: str, strategy_instance, mode: str) -> None:
        """One cycle: fetch market data → generate signal → optionally execute."""
        import pandas as pd
        from datetime import timedelta
        loop = asyncio.get_event_loop()

        df = pd.DataFrame()

        # 1. Try Angel One
        if self.order_manager and hasattr(self.order_manager, 'angel_client') and self.order_manager.angel_client:
            try:
                client = self.order_manager.angel_client
                now    = datetime.now()
                f_date = (now - timedelta(days=3)).strftime("%Y-%m-%d %H:%M")
                t_date = now.strftime("%Y-%m-%d %H:%M")
                hist = await loop.run_in_executor(
                    None,
                    client.get_historical_data,
                    "NSE", "26000", "FIFTEEN_MINUTE", f_date, t_date,
                )
                if hist is not None and not hist.empty:
                    df = hist.copy()
            except Exception as e:
                logger.warning(f"[{name}] Angel One data fetch failed: {e}")

        # 2. Fallback to Yahoo Finance when Angel One returns nothing
        if df.empty:
            try:
                import yfinance as yf

                def _yf_fetch():
                    return yf.Ticker("^NSEI").history(period="5d", interval="15m")

                yf_df = await loop.run_in_executor(None, _yf_fetch)
                if yf_df is not None and not yf_df.empty:
                    yf_df = yf_df.rename(columns={
                        "Open": "open", "High": "high", "Low": "low",
                        "Close": "close", "Volume": "volume",
                    })
                    yf_df.index.name = "timestamp"
                    yf_df = yf_df.reset_index()
                    yf_df["timestamp"] = pd.to_datetime(yf_df["timestamp"]).dt.tz_localize(None)
                    df = yf_df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
                    logger.debug(f"[{name}] Using Yahoo Finance data ({len(df)} rows)")
            except Exception as e:
                logger.warning(f"[{name}] Yahoo Finance fallback failed: {e}")

        if df.empty:
            logger.debug(f"[{name}] No market data — skipping cycle.")
            return

        # Enrich raw OHLCV with technical features, time features, and VIX
        # (same pipeline used during model training — without this the price
        # predictor receives raw bars and returns 0% confidence on every signal)
        try:
            df = await loop.run_in_executor(None, _enrich_features, df)
            logger.debug(f"[{name}] Features computed: {len(df.columns)} cols, {len(df)} rows")
        except Exception as e:
            logger.warning(f"[{name}] Feature enrichment failed: {e}")
            return

        # Fetch signal generator fresh each cycle — picks up newly trained models
        # after reload_ml_models() is called post-training (avoids stale reference).
        try:
            from backend.dependencies import get_signal_generator
            signal_gen = get_signal_generator()
        except Exception as e:
            logger.warning(f"[{name}] Could not get signal generator: {e}")
            return

        # Generate signal (sync call, run in executor)
        try:
            signal = await loop.run_in_executor(None, signal_gen.generate_signal, df)
        except Exception as e:
            logger.warning(f"[{name}] Signal generation failed: {e}")
            return

        if name in self.running_strategies:
            self.running_strategies[name]['signals_count'] += 1

        logger.info(f"[{name}] Signal: action={getattr(signal, 'action', 'none')} confidence={getattr(signal, 'confidence', 0):.2f}")

        # Execute if not paper (paper mode skips real orders but still logs)
        if mode == 'live' and self.order_manager and signal and getattr(signal, 'action', 'none') != 'none':
            try:
                await loop.run_in_executor(None, self.order_manager.execute_signal, signal)
                logger.info(f"[{name}] Live order executed.")
            except Exception as e:
                logger.error(f"[{name}] Order execution failed: {e}")

    def _on_task_done(self, name: str, task: asyncio.Task) -> None:
        if task.cancelled():
            logger.info(f"[{name}] Task cancelled cleanly.")
        elif task.exception():
            logger.error(f"[{name}] Task ended with exception: {task.exception()}")
        # Clean up from running dict if still there
        self.running_strategies.pop(name, None)

    # ------------------------------------------------------------------
    # Config & signals
    # ------------------------------------------------------------------

    async def get_strategy_signals(self, name: str, limit: int = 20) -> List[TradeSignalResponse]:
        return []

    async def get_strategy_config(self, name: str) -> dict:
        if name not in self.available_strategies:
            raise ValueError(f"Unknown strategy: {name}")
        return self.config.get('strategies', {}).get(name, {})

    async def update_strategy_config(self, name: str, new_config: dict) -> bool:
        if name not in self.available_strategies:
            raise ValueError(f"Unknown strategy: {name}")
        return True
