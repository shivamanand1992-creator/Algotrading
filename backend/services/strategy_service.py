import sys
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
import asyncio

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from strategies.trend_strategy import TrendFollowingStrategy
from strategies.premium_strategy import PremiumSellingStrategy
from strategies.scalping_strategy import ScalpingStrategy
from backend.api.models.responses import StrategyStatus, TradeSignalResponse


class StrategyService:
    def __init__(self, config, order_manager, signal_generator):
        self.config = config
        self.order_manager = order_manager
        self.signal_generator = signal_generator

        # Available strategies
        self.available_strategies = {
            'trend': {
                'class': TrendFollowingStrategy,
                'display_name': 'Trend Following',
                'description': 'Trades directional moves using EMA, RSI, MACD'
            },
            'premium': {
                'class': PremiumSellingStrategy,
                'display_name': 'Premium Selling',
                'description': 'Short strangles in ranging markets'
            },
            'scalping': {
                'class': ScalpingStrategy,
                'display_name': 'Scalping',
                'description': '1-2 minute scalping strategy'
            }
        }

        # Running strategy instances
        self.running_strategies: Dict[str, dict] = {}

    async def get_all_strategies(self) -> List[StrategyStatus]:
        """Get status of all available strategies"""
        strategies = []

        for name, info in self.available_strategies.items():
            status = "stopped"
            mode = None
            uptime_seconds = None
            signals_count = 0
            active_positions = 0

            if name in self.running_strategies:
                status = "running"
                run_info = self.running_strategies[name]
                mode = run_info['mode']
                start_time = run_info['start_time']
                uptime_seconds = int((datetime.now() - start_time).total_seconds())
                signals_count = run_info.get('signals_count', 0)
                # TODO: Get active positions count from position manager

            strategies.append(StrategyStatus(
                name=name,
                display_name=info['display_name'],
                status=status,
                mode=mode,
                uptime_seconds=uptime_seconds,
                signals_generated=signals_count,
                active_positions=active_positions,
                regime_suitability=None  # TODO: Calculate based on current regime
            ))

        return strategies

    async def start_strategy(self, name: str, mode: str) -> bool:
        """Start a strategy"""
        if name not in self.available_strategies:
            raise ValueError(f"Unknown strategy: {name}")

        if name in self.running_strategies:
            raise ValueError(f"Strategy {name} is already running")

        # Initialize strategy instance
        strategy_class = self.available_strategies[name]['class']
        strategy_instance = strategy_class(self.config, self.order_manager)

        # Store running strategy info
        self.running_strategies[name] = {
            'instance': strategy_instance,
            'mode': mode,
            'start_time': datetime.now(),
            'signals_count': 0,
            'task': None  # Will be set if we run in background
        }

        # TODO: Start background task to generate signals periodically
        # For now, just mark as running
        return True

    async def stop_strategy(self, name: str) -> bool:
        """Stop a running strategy"""
        if name not in self.running_strategies:
            raise ValueError(f"Strategy {name} is not running")

        # TODO: Stop background task if running
        # TODO: Close open positions if configured

        del self.running_strategies[name]
        return True

    async def get_strategy_signals(self, name: str, limit: int = 20) -> List[TradeSignalResponse]:
        """Get recent signals from a strategy"""
        # TODO: Implement signal history tracking
        # For now, return empty list
        return []

    async def get_strategy_config(self, name: str) -> dict:
        """Get strategy configuration"""
        if name not in self.available_strategies:
            raise ValueError(f"Unknown strategy: {name}")

        # Return config from config.yaml
        strategy_config = self.config.get('strategies', {}).get(name, {})
        return strategy_config

    async def update_strategy_config(self, name: str, new_config: dict) -> bool:
        """Update strategy configuration"""
        if name not in self.available_strategies:
            raise ValueError(f"Unknown strategy: {name}")

        # TODO: Update config in memory and optionally persist to file
        # For now, just validate and return success
        return True
