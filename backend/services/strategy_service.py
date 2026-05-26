import sys
import asyncio
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
from loguru import logger

sys.path.append(str(Path(__file__).parent.parent.parent))

from strategies.trend_strategy import TrendFollowingStrategy
from strategies.premium_strategy import PremiumSellingStrategy
from strategies.scalping_strategy import ScalpingStrategy
from backend.api.models.responses import StrategyStatus, TradeSignalResponse

# How often (seconds) each strategy loop checks for signals
STRATEGY_INTERVAL = 300   # 5 minutes


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

        # Generate signal (sync call, run in executor)
        try:
            signal = await loop.run_in_executor(None, self.signal_generator.generate_signal, df)
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
