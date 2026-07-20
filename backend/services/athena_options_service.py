"""
Athena Options Service - Manages options positions and execution
Integrates with Angel One for options trading
"""

import asyncio
from datetime import datetime, timezone, timedelta, time
from typing import Dict, List, Optional
from loguru import logger
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import os

from backend.services.athena_options_agent import AthenaOptionsAgent
from backend.models.options_position import OptionsPosition, Base
from data.angel_client import AngelOneClient


_IST = timezone(timedelta(hours=5, minutes=30))


class AthenaOptionsService:
    """
    Service for managing AI-powered options trading

    Features:
    - Weekly Bank Nifty options analysis
    - Credit spread execution
    - Position monitoring
    - Auto exit at targets
    """

    def __init__(self, angel_client: AngelOneClient):
        self.angel = angel_client
        self.agent = AthenaOptionsAgent()

        # Database setup
        db_url = os.getenv("DATABASE_URL", "sqlite:///./backend/data/athena.db")
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        self._engine = create_engine(db_url, pool_pre_ping=True)
        self._init_db()

        # Configuration
        self.config = {
            'enabled': False,  # Manual enable required
            'symbol': 'BANKNIFTY',
            'max_positions': 3,  # Max 3 spreads per week
            'capital_per_trade': 50000,  # ₹50K per spread
            'profit_target_pct': 50,  # Exit at 50% of max profit
            'stop_loss_pct': 100,  # Exit at 100% loss (premium lost)
            'min_confidence': 0.80,
            'min_pop': 0.75,  # Minimum 75% probability of profit
            'mode': 'paper',  # 'paper' or 'live'
        }

        self.positions = []  # Active option spreads
        self.trades_this_week = 0
        self.weekly_pnl = 0.0

        logger.info("[Athena] Options service initialized")

    def _init_db(self):
        """Initialize database tables"""
        try:
            Base.metadata.create_all(self._engine, checkfirst=True)
            logger.info("[Athena] Database initialized")
        except Exception as e:
            logger.error(f"[Athena] Database init failed: {e}")

    async def run_analysis_cycle(self) -> Dict:
        """
        Run one analysis cycle for options setups

        Returns:
            {
                'action': 'ENTER' | 'EXIT' | 'HOLD',
                'strategy': str,
                'confidence': float,
                'details': Dict
            }
        """
        if not self.config['enabled']:
            return {'action': 'HOLD', 'reason': 'Athena disabled'}

        # Check position limits
        if len(self.positions) >= self.config['max_positions']:
            return {'action': 'HOLD', 'reason': 'Max positions reached'}

        if self.trades_this_week >= self.config['max_positions']:
            return {'action': 'HOLD', 'reason': 'Weekly trade limit reached'}

        # Fetch market data
        market_data = await self._fetch_market_data()

        if not market_data:
            return {'action': 'HOLD', 'reason': 'Market data unavailable'}

        # Get AI recommendation
        logger.info("[Athena] 🤖 Calling Claude AI for options analysis...")
        decision = await self.agent.analyze_options_setup(market_data)
        logger.info(
            f"[Athena] 📊 Decision: {decision['strategy']} "
            f"(confidence={decision['confidence']:.0%}, PoP={decision['probability_of_profit']:.0%})"
        )

        # Check if setup meets criteria
        if decision['strategy'] == 'NONE':
            return {
                'action': 'HOLD',
                'reason': decision['reasoning'],
                'decision': decision
            }

        if decision['confidence'] < self.config['min_confidence']:
            return {
                'action': 'HOLD',
                'reason': f"Low confidence ({decision['confidence']:.0%} < {self.config['min_confidence']:.0%})",
                'decision': decision
            }

        if decision['probability_of_profit'] < self.config['min_pop']:
            return {
                'action': 'HOLD',
                'reason': f"Low PoP ({decision['probability_of_profit']:.0%} < {self.config['min_pop']:.0%})",
                'decision': decision
            }

        # Save position to database
        try:
            position = self._save_position(decision)
            self.positions.append(position.to_dict())
            self.trades_this_week += 1

            # Send Telegram notification
            self._send_entry_notification(decision)

            # Execute trade (if in live mode)
            if self.config['mode'] == 'live':
                result = await self._execute_spread(decision)
                if not result['success']:
                    logger.error(f"[Athena] Live execution failed: {result['error']}")
                    # Position is already saved in paper mode - can attempt execution later

            logger.info(
                f"[Athena] {'🔴 LIVE' if self.config['mode'] == 'live' else '📝 PAPER'} ENTRY: "
                f"{decision['strategy']} - {decision['reasoning']}"
            )

            return {
                'action': 'ENTER',
                'strategy': decision['strategy'],
                'confidence': decision['confidence'],
                'mode': self.config['mode'],
                'details': decision
            }

        except Exception as e:
            logger.error(f"[Athena] Failed to process entry: {e}")
            return {
                'action': 'HOLD',
                'reason': f"Database error: {e}",
                'decision': decision
            }

    async def _fetch_market_data(self) -> Optional[Dict]:
        """
        Fetch comprehensive market data for options analysis

        Returns market conditions needed for strategy selection
        """
        try:
            # Get Bank Nifty spot price
            spot_data = await self._get_spot_price('BANKNIFTY')
            if not spot_data:
                return None

            spot = spot_data['ltp']

            # Get India VIX
            vix = await self._get_vix()

            # Calculate support/resistance (simplified - use proper levels in production)
            atr = spot_data.get('atr', spot * 0.015)  # Estimate 1.5% ATR
            support = spot - (1.5 * atr)
            resistance = spot + (1.5 * atr)

            # Determine trend (using EMA crossover)
            trend = await self._determine_trend()

            # Get IV rank and PCR (requires options chain - placeholder)
            iv_rank = 50  # TODO: Calculate from options chain
            pcr = 1.0  # TODO: Get actual Put/Call ratio

            # Days to weekly expiry (Thursday)
            today = datetime.now(_IST)
            days_to_thursday = (3 - today.weekday()) % 7  # Thursday = 3
            if days_to_thursday == 0 and today.time() > time(15, 30):
                days_to_thursday = 7
            dte = days_to_thursday if days_to_thursday > 0 else 7

            return {
                'symbol': 'BANKNIFTY',
                'spot_price': spot,
                'vix': vix,
                'trend': trend,
                'support': support,
                'resistance': resistance,
                'atr': atr,
                'rsi': spot_data.get('rsi', 50),
                'macd_hist': spot_data.get('macd', 0),
                'iv_rank': iv_rank,
                'put_call_ratio': pcr,
                'days_to_expiry': dte,
            }

        except Exception as e:
            logger.error(f"[Athena] Market data fetch failed: {e}")
            return None

    async def _get_spot_price(self, symbol: str) -> Optional[Dict]:
        """Get current spot price and indicators"""
        # TODO: Implement using Angel One API
        # Placeholder for now
        return {
            'ltp': 52000.0,
            'atr': 780.0,
            'rsi': 55.0,
            'macd': 0.002
        }

    async def _get_vix(self) -> float:
        """Get current India VIX value"""
        # TODO: Fetch from Angel One
        return 16.5

    async def _determine_trend(self) -> str:
        """Determine market trend (uptrend/downtrend/ranging)"""
        # TODO: Calculate from historical data
        # For now, return ranging as safest
        return 'ranging'

    async def _execute_spread(self, decision: Dict) -> Dict:
        """
        Execute option spread via Angel One

        Returns:
            {
                'success': bool,
                'position': Dict,  # If successful
                'error': str  # If failed
            }
        """
        try:
            # TODO: Implement actual options order execution
            # For now, return paper trade

            logger.info(
                f"[Athena] 🚀 Executing {decision['strategy']}: "
                f"Sell {decision['strikes']['sell_strike']}, "
                f"Buy {decision['strikes']['buy_strike']}"
            )

            return {
                'success': True,
                'position': {
                    'strategy': decision['strategy'],
                    'entry_date': datetime.now(_IST),
                    'strikes': decision['strikes'],
                    'premium_received': decision['premium'],
                    'max_loss': decision['max_loss'],
                    'status': 'OPEN'
                }
            }

        except Exception as e:
            logger.error(f"[Athena] Execution failed: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    async def monitor_positions(self) -> List[Dict]:
        """
        Monitor all open positions and exit if target/stop hit

        Returns list of position updates
        """
        if not self.positions:
            return []

        updates = []

        for pos in self.positions:
            # TODO: Check current P&L
            # Exit if 50% profit or 100% loss

            pass

        return updates

    def get_status(self) -> Dict:
        """Get current status of Athena"""
        return {
            'enabled': self.config['enabled'],
            'mode': self.config['mode'],
            'positions': len(self.positions),
            'trades_this_week': self.trades_this_week,
            'weekly_pnl': self.weekly_pnl,
            'max_positions': self.config['max_positions'],
            'min_confidence': self.config['min_confidence'],
            'min_pop': self.config['min_pop'],
        }

    def enable(self, mode: str = 'paper'):
        """Enable Athena trading"""
        self.config['enabled'] = True
        self.config['mode'] = mode
        logger.info(f"[Athena] Enabled in {mode.upper()} mode")

    def disable(self):
        """Disable Athena trading"""
        self.config['enabled'] = False
        logger.info("[Athena] Disabled")

    def _save_position(self, decision: Dict) -> OptionsPosition:
        """Save position to database"""
        try:
            position = OptionsPosition(
                strategy=decision['strategy'],
                symbol=self.config['symbol'],
                entry_date=datetime.now(_IST),
                expiry_date=None,  # TODO: Calculate from options data
                strikes=decision['strikes'],
                premium_received=decision['premium'],
                max_loss=decision['max_loss'],
                confidence=decision['confidence'],
                probability_of_profit=decision['probability_of_profit'],
                status='OPEN',
                mode=self.config['mode'],
                reasoning=decision.get('reasoning', ''),
                risk_factors=decision.get('risk_factors', []),
            )

            with Session(self._engine) as session:
                session.add(position)
                session.commit()
                session.refresh(position)

            logger.info(f"[Athena] Position saved: {position.id}")
            return position

        except Exception as e:
            logger.error(f"[Athena] Failed to save position: {e}")
            raise

    def _send_entry_notification(self, decision: Dict):
        """Send Telegram notification for trade entry"""
        try:
            from backend.services import telegram_service
            telegram_service.send_athena_entry(
                strategy=decision['strategy'],
                symbol=self.config['symbol'],
                strikes=decision['strikes'],
                premium=decision['premium'],
                max_loss=decision['max_loss'],
                confidence=decision['confidence'],
                pop=decision['probability_of_profit'],
                mode=self.config['mode'],
                reasoning=decision.get('reasoning', '')
            )
        except Exception as e:
            logger.warning(f"[Athena] Telegram notification failed: {e}")

    def _send_exit_notification(self, position: OptionsPosition):
        """Send Telegram notification for trade exit"""
        try:
            from backend.services import telegram_service
            telegram_service.send_athena_exit(
                strategy=position.strategy,
                symbol=position.symbol,
                exit_reason=position.exit_reason or 'UNKNOWN',
                premium=position.premium_received,
                realized_pnl=position.realized_pnl,
                mode=position.mode
            )
        except Exception as e:
            logger.warning(f"[Athena] Telegram notification failed: {e}")
