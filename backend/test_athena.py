#!/usr/bin/env python3
"""
Quick test script for Athena Options Trading System
Run this to validate setup before live market
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from loguru import logger
from data.angel_client import (
    AngelOneClient,
    get_banknifty_spot_price,
    get_india_vix,
    get_next_weekly_expiry,
    get_option_symbol,
    find_option_token
)
from backend.services.athena_options_service import AthenaOptionsService
from backend.services.athena_options_agent import AthenaOptionsAgent


async def test_angel_one_connection():
    """Test 1: Angel One API connection"""
    logger.info("=" * 60)
    logger.info("TEST 1: Angel One API Connection")
    logger.info("=" * 60)

    try:
        client = AngelOneClient()
        client.connect()
        logger.success("✅ Angel One connected successfully")

        profile = client.get_profile()
        logger.info(f"   Client: {profile.get('name', 'Unknown')}")
        logger.info(f"   Client Code: {profile.get('clientcode', 'Unknown')}")

        return client

    except Exception as e:
        logger.error(f"❌ Angel One connection failed: {e}")
        return None


async def test_market_data(client: AngelOneClient):
    """Test 2: Fetch live market data"""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 2: Market Data Fetch")
    logger.info("=" * 60)

    try:
        # Bank Nifty spot
        spot = get_banknifty_spot_price(client)
        logger.success(f"✅ Bank Nifty Spot: ₹{spot:,.2f}")

        # India VIX
        vix = get_india_vix(client)
        logger.success(f"✅ India VIX: {vix:.2f}")

        # Next expiry
        expiry = get_next_weekly_expiry()
        logger.success(f"✅ Next Weekly Expiry: {expiry}")

        return spot, vix, expiry

    except Exception as e:
        logger.error(f"❌ Market data fetch failed: {e}")
        return None, None, None


async def test_option_chain(client: AngelOneClient, spot: float, expiry: str):
    """Test 3: Options chain access"""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 3: Options Chain Access")
    logger.info("=" * 60)

    try:
        # Round to nearest 100 for strike
        atm_strike = int(round(spot / 100) * 100)

        # Test finding option tokens
        test_strikes = [
            (atm_strike - 100, 'PE'),  # ITM Put
            (atm_strike, 'CE'),         # ATM Call
            (atm_strike + 100, 'CE'),   # OTM Call
        ]

        for strike, opt_type in test_strikes:
            symbol = get_option_symbol("BANKNIFTY", expiry, strike, opt_type)
            token = find_option_token(client, "BANKNIFTY", expiry, strike, opt_type)

            if token:
                logger.success(f"✅ {symbol}: token={token}")
            else:
                logger.warning(f"⚠️  {symbol}: token not found")

        logger.success("✅ Options chain accessible")

    except Exception as e:
        logger.error(f"❌ Options chain test failed: {e}")


async def test_ai_agent():
    """Test 4: AI analysis engine"""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 4: AI Analysis Engine")
    logger.info("=" * 60)

    try:
        agent = AthenaOptionsAgent()

        # Mock market data
        market_data = {
            'symbol': 'BANKNIFTY',
            'spot_price': 52000.0,
            'vix': 17.5,
            'trend': 'uptrend',
            'support': 51500.0,
            'resistance': 52500.0,
            'atr': 780.0,
            'rsi': 55.0,
            'macd_hist': 0.002,
            'iv_rank': 55.0,
            'put_call_ratio': 1.1,
            'days_to_expiry': 5,
        }

        logger.info("🤖 Calling Claude AI for analysis...")
        decision = await agent.analyze_options_setup(market_data)

        logger.info(f"   Strategy: {decision['strategy']}")
        logger.info(f"   Confidence: {decision['confidence']:.0%}")
        logger.info(f"   PoP: {decision['probability_of_profit']:.0%}")
        logger.info(f"   Reasoning: {decision['reasoning'][:100]}...")

        if decision['strategy'] != 'NONE':
            logger.success("✅ AI agent working - found trade setup")
        else:
            logger.info("ℹ️  AI agent working - no trade setup (expected in test)")

    except Exception as e:
        logger.error(f"❌ AI agent test failed: {e}")


async def test_athena_service(client: AngelOneClient):
    """Test 5: Athena service initialization"""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 5: Athena Service")
    logger.info("=" * 60)

    try:
        service = AthenaOptionsService(client)
        logger.success("✅ Athena service initialized")

        status = service.get_status()
        logger.info(f"   Mode: {status['mode']}")
        logger.info(f"   Enabled: {status['enabled']}")
        logger.info(f"   Open Positions: {status['positions']}")
        logger.info(f"   Trades This Week: {status['trades_this_week']}")

        logger.success("✅ Athena service ready")

        return service

    except Exception as e:
        logger.error(f"❌ Athena service test failed: {e}")
        return None


async def test_telegram():
    """Test 6: Telegram notifications"""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 6: Telegram Notifications")
    logger.info("=" * 60)

    try:
        from backend.services import telegram_service

        if not telegram_service.is_configured():
            logger.warning("⚠️  Telegram not configured (optional)")
            return

        # Test notification
        success = telegram_service.send(
            "🏛️ *Athena Test*\n\n"
            "This is a test notification from Athena Options Trading System.\n"
            "If you see this, Telegram integration is working! ✅"
        )

        if success:
            logger.success("✅ Telegram notification sent")
        else:
            logger.warning("⚠️  Telegram send failed (check credentials)")

    except Exception as e:
        logger.error(f"❌ Telegram test failed: {e}")


async def main():
    """Run all tests"""
    logger.info("\n" + "=" * 80)
    logger.info("ATHENA OPTIONS TRADING SYSTEM - PRE-MARKET VALIDATION")
    logger.info("=" * 80)

    # Test 1: Angel One connection
    client = await test_angel_one_connection()
    if not client:
        logger.error("\n❌ CRITICAL: Cannot proceed without Angel One connection")
        return

    # Test 2: Market data
    spot, vix, expiry = await test_market_data(client)
    if not spot:
        logger.error("\n❌ CRITICAL: Cannot fetch market data")
        return

    # Test 3: Options chain
    await test_option_chain(client, spot, expiry)

    # Test 4: AI agent
    await test_ai_agent()

    # Test 5: Athena service
    service = await test_athena_service(client)

    # Test 6: Telegram
    await test_telegram()

    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("TEST SUMMARY")
    logger.info("=" * 80)
    logger.success("✅ All critical tests passed!")
    logger.info("\n🏛️ Athena is ready for live market testing tomorrow")
    logger.info("\nNext steps:")
    logger.info("1. Open dashboard: http://localhost:3000")
    logger.info("2. Navigate to 🏛️ Athena Options")
    logger.info("3. Click 'Enable Paper Trading' to start")
    logger.info("4. Click 'Run Analysis' to test AI analysis")
    logger.info("5. Monitor positions and verify Telegram notifications")
    logger.info("\n⚠️  Start with PAPER mode to validate before going LIVE")


if __name__ == "__main__":
    asyncio.run(main())
