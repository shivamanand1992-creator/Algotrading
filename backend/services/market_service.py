import sys
from pathlib import Path
from typing import List, Optional
from datetime import datetime
import pandas as pd

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from backend.api.models.responses import (
    MarketDataResponse,
    OptionsChainItem,
    MarketRegimeResponse,
    PredictionResponse
)


class MarketService:
    def __init__(self, angel_client, options_analyzer, signal_generator, config):
        self.angel_client = angel_client
        self.options_analyzer = options_analyzer
        self.signal_generator = signal_generator
        self.config = config

    async def get_current_market_data(self) -> MarketDataResponse:
        """Get current market data for Nifty50"""
        try:
            # TODO: Get real-time data from Angel client
            # For now, return mock data
            return MarketDataResponse(
                symbol="NIFTY50",
                ltp=18500.0,
                change=125.5,
                change_percentage=0.68,
                iv_percentile=45.0,
                pcr=1.05,
                timestamp=datetime.now()
            )
        except Exception as e:
            # Return default data if API fails
            return MarketDataResponse(
                symbol="NIFTY50",
                ltp=18500.0,
                change=0.0,
                change_percentage=0.0,
                iv_percentile=50.0,
                pcr=1.0,
                timestamp=datetime.now()
            )

    async def get_options_chain(self) -> List[OptionsChainItem]:
        """Get options chain with Greeks"""
        try:
            # TODO: Implement real options chain fetch
            # For now, return mock data for a few strikes
            atm_strike = 18500
            strikes = range(atm_strike - 300, atm_strike + 350, 50)

            chain = []
            for strike in strikes:
                chain.append(OptionsChainItem(
                    strike=strike,
                    call_ltp=150.0,
                    call_iv=18.5,
                    call_oi=50000,
                    call_delta=0.5,
                    call_gamma=0.001,
                    call_theta=-10.0,
                    call_vega=25.0,
                    put_ltp=140.0,
                    put_iv=19.0,
                    put_oi=48000,
                    put_delta=-0.5,
                    put_gamma=0.001,
                    put_theta=-10.0,
                    put_vega=25.0
                ))

            return chain
        except Exception as e:
            return []

    async def get_market_regime(self) -> MarketRegimeResponse:
        """Get current market regime classification"""
        try:
            # Use signal generator to get regime
            # TODO: Get real-time market data first
            signal = await self._generate_signal()

            return MarketRegimeResponse(
                current_regime=signal.regime,
                confidence=max(signal.regime_probs.values()),
                regime_probabilities=signal.regime_probs,
                timestamp=datetime.now()
            )
        except Exception as e:
            # Return default regime
            return MarketRegimeResponse(
                current_regime="ranging",
                confidence=0.5,
                regime_probabilities={
                    "trending_up": 0.2,
                    "trending_down": 0.2,
                    "ranging": 0.5,
                    "high_volatility": 0.1
                },
                timestamp=datetime.now()
            )

    async def get_predictions(self) -> PredictionResponse:
        """Get ML model predictions"""
        try:
            signal = await self._generate_signal()

            direction_labels = {1: "UP", 0: "FLAT", -1: "DOWN"}

            return PredictionResponse(
                direction=signal.direction,
                direction_label=direction_labels.get(signal.direction, "UNKNOWN"),
                confidence=signal.confidence,
                direction_probabilities=signal.direction_probs,
                timestamp=datetime.now()
            )
        except Exception as e:
            # Return default prediction
            return PredictionResponse(
                direction=0,
                direction_label="FLAT",
                confidence=0.5,
                direction_probabilities={"UP": 0.3, "FLAT": 0.4, "DOWN": 0.3},
                timestamp=datetime.now()
            )

    async def _generate_signal(self):
        """Generate signal using ML models"""
        # TODO: Get real market data
        # For now, create mock dataframe
        df = pd.DataFrame({
            'close': [18500],
            'open': [18450],
            'high': [18550],
            'low': [18400],
            'volume': [1000000]
        })

        return self.signal_generator.generate(df)
