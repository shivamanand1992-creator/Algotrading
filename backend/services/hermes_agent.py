"""
Hermes Agent - AI-powered intraday trading decision engine
Uses Claude AI to analyze market conditions and make trading decisions
"""

import os
import json
import logging
from typing import Dict, Optional
from anthropic import AsyncAnthropic
from datetime import datetime

logger = logging.getLogger(__name__)


class HermesAgent:
    """AI trading agent using Claude (Anthropic) for market analysis"""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Hermes Agent

        Args:
            api_key: Anthropic API key (from ANTHROPIC_API_KEY env var if not provided)
        """
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")

        if not self.api_key:
            raise ValueError(
                "[Hermes] CRITICAL: ANTHROPIC_API_KEY environment variable is required but not set! "
                "Add ANTHROPIC_API_KEY=sk-ant-... to your .env file or Railway environment variables."
            )

        self.client = AsyncAnthropic(api_key=self.api_key)
        self.model = "claude-haiku-4-5"  # Fast, affordable Claude Haiku 4.5
        self.timeout = 30.0
        self.max_tokens = 1024

        logger.info(f"[Hermes] Agent initialized with model={self.model}")

    async def analyze_market(self, market_data: Dict) -> Dict:
        """
        Analyze market conditions and return trading decision

        Args:
            market_data: Dict with price, indicators, account state

        Returns:
            Dict with action, confidence, entry/sl/target, reasoning
        """
        try:
            prompt = self._build_prompt(market_data)
            response_text = await self._call_llm(prompt)
            decision = self._parse_decision(response_text)

            logger.info(
                f"[Hermes] {market_data.get('symbol', 'UNKNOWN')}: "
                f"{decision['action']} (confidence={decision['confidence']:.2f}) - "
                f"{decision['reasoning'][:80]}"
            )

            return decision

        except Exception as e:
            logger.error(f"[Hermes] Analysis failed: {e}")
            return {
                "action": "HOLD",
                "confidence": 0.0,
                "reasoning": f"Error: {e}",
                "entry_price": None,
                "stop_loss": None,
                "target": None,
                "quantity": None,
            }

    def _build_prompt(self, data: Dict) -> str:
        """Build analysis prompt for LLM"""

        return f"""You are an expert intraday trading agent for Indian equities.

INSTRUMENT: {data.get('symbol', 'UNKNOWN')}
CURRENT MARKET STATE:
- Price: ₹{data.get('price', 0):.2f}
- Previous Day High: ₹{data.get('prev_high', 0):.2f}
- Previous Day Low: ₹{data.get('prev_low', 0):.2f}
- Day Open: ₹{data.get('day_open', 0):.2f}

TECHNICAL INDICATORS:
- RSI(14): {data.get('rsi', 0):.1f}
- MACD Histogram: {data.get('macd', 0):.4f}
- Current Volume: {data.get('volume_current', 0):,.0f}
- Average Volume: {data.get('volume_ma', 0):,.0f}
- Volume Ratio: {data.get('volume_current', 1) / max(data.get('volume_ma', 1), 1):.2f}x

ACCOUNT STATE:
- Available Balance: ₹{data.get('account_balance', 0):,.2f}
- Today's P&L: ₹{data.get('daily_pnl', 0):.2f}
- Open Positions: {data.get('open_positions', 0)}
- Trades Today: {data.get('trades_today', 0)}/{data.get('max_trades', 4)}

TRADING RULES:
1. Intraday only (MIS) - must exit by 3:15 PM
2. Valid setups: Breakout (price > prev_high) OR Bounce (price near prev_low)
3. Volume confirmation required (current > 1.3x average)
4. RSI range: 30-70 (avoid overbought/oversold)
5. Max {data.get('max_trades', 4)} trades per day
6. Max loss per trade: 0.6% of entry
7. Target: 0.9% profit minimum

DECISION FRAMEWORK:
- HOLD: No clear setup, wait for better opportunity
- BUY: Valid breakout/bounce + volume confirmation + indicators aligned
- CLOSE_POSITION: Stop loss hit OR target reached OR time-based exit (3:10 PM)
- WAIT: Setup forming but not yet confirmed

Analyze the current market state and respond with a JSON decision:

{{
    "action": "HOLD|BUY|CLOSE_POSITION|WAIT",
    "confidence": 0.0-1.0,
    "reasoning": "Brief 1-2 sentence explanation",
    "entry_price": null or entry price,
    "stop_loss": null or SL price,
    "target": null or target price,
    "setup_type": null or "breakout" or "bounce",
    "quantity": null or position size
}}

Be conservative. Only recommend BUY if confidence >= 0.7 and all conditions met."""

    async def _call_llm(self, prompt: str) -> str:
        """Call Anthropic Claude API using official SDK"""

        if not self.client:
            raise ValueError("No ANTHROPIC_API_KEY configured")

        try:
            message = await self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=0.3,  # Low temperature for consistent decisions
                messages=[{"role": "user", "content": prompt}],
            )

            # Extract text from response
            return message.content[0].text

        except Exception as e:
            logger.error(f"[Hermes] Anthropic API error: {e}")
            raise

    def _parse_decision(self, response_text: str) -> Dict:
        """Parse LLM JSON response"""

        try:
            # Extract JSON from response (LLM may add markdown formatting)
            start = response_text.find("{")
            end = response_text.rfind("}") + 1
            json_str = response_text[start:end]

            data = json.loads(json_str)

            return {
                "action": data.get("action", "HOLD").upper(),
                "confidence": float(data.get("confidence", 0.0)),
                "entry_price": float(data["entry_price"]) if data.get("entry_price") else None,
                "stop_loss": float(data["stop_loss"]) if data.get("stop_loss") else None,
                "target": float(data["target"]) if data.get("target") else None,
                "setup_type": data.get("setup_type"),
                "quantity": int(data["quantity"]) if data.get("quantity") else None,
                "reasoning": data.get("reasoning", "No explanation provided"),
            }

        except Exception as e:
            logger.error(f"[Hermes] Failed to parse LLM response: {e}\nResponse: {response_text[:200]}")
            return {
                "action": "HOLD",
                "confidence": 0.0,
                "reasoning": f"Parse error: {e}",
                "entry_price": None,
                "stop_loss": None,
                "target": None,
                "quantity": None,
            }
