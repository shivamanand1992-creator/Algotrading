"""
Athena Options Trading Agent - AI-Powered Options Strategy
Target: 80% success rate using high-probability setups

Strategy: Weekly Bank Nifty Credit Spreads + Iron Condors
- Sell premium in low volatility
- Strict trend/range filters
- Exit at 50% profit or 100% loss
- Max 3 positions per week
"""

import os
import json
from typing import Dict, Optional, List
from datetime import datetime, time
from anthropic import AsyncAnthropic
from loguru import logger


class AthenaOptionsAgent:
    """
    AI agent for high-probability options trading

    Strategy Focus:
    1. Weekly Bank Nifty options (most liquid)
    2. Credit spreads in trending markets
    3. Iron Condors in ranging markets
    4. Strict IV and trend filters
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")

        if not self.api_key:
            raise ValueError("[Athena] ANTHROPIC_API_KEY required")

        self.client = AsyncAnthropic(api_key=self.api_key)
        self.model = "claude-opus-4-8"  # Using Opus for complex options analysis
        self.timeout = 45.0
        self.max_tokens = 2048

        logger.info(f"[Athena] Options agent initialized with {self.model}")

    async def analyze_options_setup(self, market_data: Dict) -> Dict:
        """
        Analyze market for high-probability options setup

        Args:
            market_data: {
                'spot_price': float,
                'vix': float,  # India VIX
                'trend': str,  # 'uptrend', 'downtrend', 'ranging'
                'support': float,
                'resistance': float,
                'atr': float,
                'rsi': float,
                'iv_rank': float,  # 0-100
                'days_to_expiry': int,
                'open_interest': Dict,  # PCR, max pain, etc.
            }

        Returns:
            {
                'strategy': 'BULL_PUT_SPREAD' | 'BEAR_CALL_SPREAD' | 'IRON_CONDOR' | 'NONE',
                'confidence': 0.0-1.0,
                'strikes': {
                    'sell_strike': float,
                    'buy_strike': float,
                    'sell_strike_2': float,  # For Iron Condor
                    'buy_strike_2': float,
                },
                'premium': float,  # Expected credit
                'max_loss': float,
                'probability_of_profit': float,
                'reasoning': str,
                'risk_factors': List[str]
            }
        """
        try:
            prompt = self._build_options_prompt(market_data)
            response_text = await self._call_llm(prompt)
            decision = self._parse_decision(response_text)

            logger.info(
                f"[Athena] {market_data.get('symbol', 'BANKNIFTY')}: "
                f"{decision['strategy']} (confidence={decision['confidence']:.2f}, "
                f"PoP={decision.get('probability_of_profit', 0):.0%})"
            )

            return decision

        except Exception as e:
            logger.error(f"[Athena] Analysis failed: {e}")
            return {
                'strategy': 'NONE',
                'confidence': 0.0,
                'reasoning': f'Error: {e}',
                'strikes': {},
                'premium': 0,
                'max_loss': 0,
                'probability_of_profit': 0,
                'risk_factors': ['ERROR']
            }

    def _build_options_prompt(self, data: Dict) -> str:
        """Build analysis prompt for Claude"""

        spot = data.get('spot_price', 0)
        vix = data.get('vix', 15)
        trend = data.get('trend', 'ranging')
        support = data.get('support', spot * 0.97)
        resistance = data.get('resistance', spot * 1.03)
        iv_rank = data.get('iv_rank', 50)
        dte = data.get('days_to_expiry', 7)
        pcr = data.get('put_call_ratio', 1.0)

        return f"""You are an expert options trading strategist specializing in high-probability setups.

MARKET CONDITIONS - BANK NIFTY WEEKLY OPTIONS
================================================

SPOT & STRUCTURE:
- Current Price: ₹{spot:,.0f}
- Trend: {trend.upper()}
- Support: ₹{support:,.0f} ({((support - spot) / spot * 100):+.1f}%)
- Resistance: ₹{resistance:,.0f} ({((resistance - spot) / spot * 100):+.1f}%)
- ATR: ₹{data.get('atr', 0):.0f}

VOLATILITY:
- India VIX: {vix:.1f}
- IV Rank: {iv_rank:.0f}/100 {"(HIGH - good for selling)" if iv_rank > 50 else "(LOW - avoid selling)"}
- Put/Call Ratio: {pcr:.2f} {"(Bullish)" if pcr > 1.2 else "(Bearish)" if pcr < 0.8 else "(Neutral)"}

TIME:
- Days to Expiry: {dte} days {"(Weekly)" if dte <= 7 else "(Monthly)"}

TECHNICAL:
- RSI: {data.get('rsi', 50):.0f}
- MACD: {data.get('macd_hist', 0):.4f}

STRATEGY SELECTION RULES (for 80%+ success rate):
=================================================

**1. BULL PUT SPREAD** (Sell Put, Buy lower Put)
   When:
   - Uptrend OR ranging with bullish bias
   - VIX > 15 (good premium)
   - RSI not overbought (<70)
   - Support clearly defined
   - Probability of Profit > 75%

   Setup:
   - Sell Put at 1 standard deviation below spot (≈1 ATR)
   - Buy Put at 2-3% below sell strike
   - Target: 50% of max profit
   - Stop: 100% of premium received (close spread)

**2. BEAR CALL SPREAD** (Sell Call, Buy higher Call)
   When:
   - Downtrend OR ranging with bearish bias
   - VIX > 15
   - RSI not oversold (>30)
   - Resistance clearly defined
   - Probability of Profit > 75%

   Setup:
   - Sell Call at 1 standard deviation above spot
   - Buy Call at 2-3% above sell strike
   - Target: 50% of max profit
   - Stop: 100% of premium received

**3. IRON CONDOR** (Sell OTM Put + Call, Buy further OTM)
   When:
   - RANGING market (NOT trending)
   - VIX > 18 (high premium)
   - Clear support & resistance
   - Expected range-bound for next 3-5 days
   - Probability of Profit > 70%

   Setup:
   - Sell Put at support - 100 points
   - Buy Put 200 points lower
   - Sell Call at resistance + 100 points
   - Buy Call 200 points higher
   - Target: 40% of max profit (exit early)

**4. NONE** - Skip Trade
   When:
   - VIX < 14 (low premium, not worth risk)
   - Trend unclear or choppy
   - Major event risk (RBI, Fed, Budget)
   - Probability of Profit < 70%
   - Days to expiry < 3 (too risky)

RESPONSE FORMAT (JSON only):
============================

{{
    "strategy": "BULL_PUT_SPREAD" | "BEAR_CALL_SPREAD" | "IRON_CONDOR" | "NONE",
    "confidence": 0.0-1.0,
    "strikes": {{
        "sell_strike": 52000,
        "buy_strike": 51500,
        "sell_strike_2": null,  // Only for Iron Condor
        "buy_strike_2": null
    }},
    "premium": 150,  // Expected credit per lot
    "max_loss": 350,  // Max loss per lot
    "probability_of_profit": 0.78,  // 78%
    "reasoning": "Clear uptrend with strong support at 51800. VIX at 17 offers good premium. Bull put spread 1 ATR below with 78% PoP.",
    "risk_factors": ["Event risk on Friday", "Resistance at 53000"]
}}

CRITICAL RULES:
- Only recommend if confidence >= 0.80 AND probability_of_profit >= 0.75
- Use round numbers for strikes (e.g., 52000, not 52050)
- Premium should be 30-40% of spread width (good risk/reward)
- If VIX < 15, strategy should be NONE (premium too low)
- If trend is unclear, prefer IRON_CONDOR or NONE
- NEVER recommend naked options (always spreads)

Analyze and respond with JSON only (no markdown):"""

    async def _call_llm(self, prompt: str) -> str:
        """Call Claude API for options analysis"""

        try:
            message = await self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=0.2,  # Low temp for consistent analysis
                thinking={
                    "type": "adaptive",  # Extended thinking for complex options math
                    "budget_tokens": 5000
                },
                messages=[{"role": "user", "content": prompt}],
            )

            # Track usage
            try:
                from backend.services import claude_usage_service
                usage = message.usage
                claude_usage_service.track_usage(
                    model=self.model,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens
                )
            except Exception as track_err:
                logger.warning(f"[Athena] Failed to track usage: {track_err}")

            # Extract text from response
            return message.content[0].text

        except Exception as e:
            logger.error(f"[Athena] Claude API error: {e}")
            raise

    def _parse_decision(self, response_text: str) -> Dict:
        """Parse Claude's JSON response"""

        try:
            # Extract JSON
            start = response_text.find("{")
            end = response_text.rfind("}") + 1
            json_str = response_text[start:end]

            data = json.loads(json_str)

            return {
                "strategy": data.get("strategy", "NONE").upper(),
                "confidence": float(data.get("confidence", 0.0)),
                "strikes": data.get("strikes", {}),
                "premium": float(data.get("premium", 0)),
                "max_loss": float(data.get("max_loss", 0)),
                "probability_of_profit": float(data.get("probability_of_profit", 0.0)),
                "reasoning": data.get("reasoning", ""),
                "risk_factors": data.get("risk_factors", [])
            }

        except Exception as e:
            logger.error(f"[Athena] Parse error: {e}\nResponse: {response_text[:300]}")
            return {
                "strategy": "NONE",
                "confidence": 0.0,
                "strikes": {},
                "premium": 0,
                "max_loss": 0,
                "probability_of_profit": 0.0,
                "reasoning": f"Parse error: {e}",
                "risk_factors": ["PARSE_ERROR"]
            }
