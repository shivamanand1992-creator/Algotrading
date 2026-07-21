#!/usr/bin/env python3
"""
Live Agent Testing Script
Tests Hermes and Athena agents end-to-end with realistic market conditions
"""

import asyncio
import sys
import os
from datetime import datetime, time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.hermes_agent import HermesAgent
from backend.services.hermes_intraday_service import HermesIntradayService
from backend.services.athena_options_agent import AthenaOptionsAgent
from backend.services.athena_options_service import AthenaOptionsService
from data.angel_client import AngelOneClient


def print_section(title: str):
    """Print section header"""
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}\n")


async def test_hermes_agent():
    """Test Hermes agent with realistic intraday scenario"""
    print_section("🤖 HERMES AGENT TEST")

    # Realistic market data for a potential breakout scenario
    test_data = {
        'symbol': 'RELIANCE',
        'price': 2850.50,
        'prev_high': 2845.00,  # Current price ABOVE prev high (breakout!)
        'prev_low': 2805.00,
        'day_open': 2820.00,
        'rsi': 62.5,  # Healthy RSI, not overbought
        'macd': 0.0025,  # Positive MACD
        'volume_current': 2500000,
        'volume_ma': 1800000,  # Strong volume (1.39x average)
        'account_balance': 100000,
        'daily_pnl': 0,
        'open_positions': 0,
        'trades_today': 0,
        'max_trades': 4
    }

    print("📊 Test Market Conditions (Breakout Setup):")
    print(f"   Symbol: {test_data['symbol']}")
    print(f"   Price: ₹{test_data['price']} (ABOVE prev high ₹{test_data['prev_high']})")
    print(f"   Volume: {test_data['volume_current']:,} ({test_data['volume_current']/test_data['volume_ma']:.2f}x avg)")
    print(f"   RSI: {test_data['rsi']:.1f} (healthy range)")
    print(f"   MACD: {test_data['macd']:.4f} (positive)")
    print()

    try:
        agent = HermesAgent()
        print(f"✅ Hermes Agent initialized with model: {agent.model}")
        print(f"   Timeout: {agent.timeout}s, Max tokens: {agent.max_tokens}")
        print()

        print("🔄 Calling Claude AI for analysis...")
        decision = await agent.analyze_market(test_data)

        print()
        print("📋 DECISION RECEIVED:")
        print(f"   Action: {decision['action']}")
        print(f"   Confidence: {decision['confidence']:.1%}")
        print(f"   Setup Type: {decision.get('setup_type', 'N/A')}")
        print(f"   Reasoning: {decision['reasoning']}")

        if decision.get('entry_price'):
            print()
            print("💰 Trade Details:")
            print(f"   Entry: ₹{decision['entry_price']:.2f}")
            print(f"   Stop Loss: ₹{decision['stop_loss']:.2f}")
            print(f"   Target: ₹{decision['target']:.2f}")
            print(f"   Quantity: {decision.get('quantity', 'N/A')}")

            # Calculate risk-reward
            risk = decision['entry_price'] - decision['stop_loss']
            reward = decision['target'] - decision['entry_price']
            rr_ratio = reward / risk if risk > 0 else 0
            print(f"   Risk/Reward: 1:{rr_ratio:.2f}")

        print()
        if decision['confidence'] >= 0.65:
            print("✅ PASS: Confidence meets threshold (≥65%)")
        else:
            print(f"❌ FAIL: Confidence {decision['confidence']:.1%} below threshold (65%)")
            print("   This is the problem! Agent is too conservative.")

        return decision

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None


async def test_hermes_service():
    """Test full Hermes intraday service"""
    print_section("⚙️  HERMES SERVICE TEST")

    try:
        print("🔧 Initializing Hermes Intraday Service...")
        service = HermesIntradayService()

        print(f"✅ Service initialized")
        print(f"   Enabled: {service.enabled}")
        print(f"   Mode: {service.mode}")
        print(f"   Symbol: {service.symbol}")
        print(f"   Min Confidence: {service.min_confidence:.0%}")
        print(f"   Quantity: {service.quantity}")
        print()

        # Check if market is open (won't actually trade if closed)
        now = datetime.now().time()
        market_open = time(9, 15)
        market_close = time(15, 30)
        is_market_hours = market_open <= now <= market_close

        print(f"⏰ Current time: {now.strftime('%H:%M:%S')}")
        print(f"   Market hours: 09:15 - 15:30")
        print(f"   Status: {'🟢 OPEN' if is_market_hours else '🔴 CLOSED'}")
        print()

        if not is_market_hours:
            print("⚠️  Market is closed - will test logic but won't place real orders")

        print("🔄 Running analysis cycle...")
        result = await service.run_analysis_cycle()

        print()
        print("📋 SERVICE RESULT:")
        print(f"   Action: {result.get('action', 'N/A')}")
        print(f"   Decision: {result.get('decision', {}).get('action', 'N/A')}")
        print(f"   Confidence: {result.get('decision', {}).get('confidence', 0):.1%}")
        print(f"   Reason: {result.get('reason', 'N/A')}")

        return result

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None


async def test_athena_agent():
    """Test Athena options agent"""
    print_section("🏛️  ATHENA AGENT TEST")

    test_data = {
        'spot_price': 48500.00,  # Bank Nifty
        'iv': 16.5,
        'regime': 'ranging',
        'trend': 0.02,
        'balance': 100000
    }

    print("📊 Test Market Conditions:")
    print(f"   Bank Nifty Spot: ₹{test_data['spot_price']:,.2f}")
    print(f"   India VIX: {test_data['iv']}")
    print(f"   Regime: {test_data['regime']}")
    print(f"   Balance: ₹{test_data['balance']:,.2f}")
    print()

    try:
        agent = AthenaOptionsAgent()
        print(f"✅ Athena Agent initialized with model: {agent.model}")
        print(f"   Max tokens: {agent.max_tokens}")
        print()

        print("🔄 Calling Claude AI for options analysis...")
        decision = await agent.analyze_options_setup(test_data)

        print()
        print("📋 DECISION RECEIVED:")
        print(f"   Strategy: {decision['strategy']}")
        print(f"   Confidence: {decision['confidence']:.1%}")
        print(f"   PoP: {decision['probability_of_profit']:.1%}")
        print(f"   Reasoning: {decision['reasoning'][:100]}...")

        if decision['strikes']:
            print()
            print("💰 Strike Details:")
            print(f"   {decision['strikes']}")
            print(f"   Premium: ₹{decision['premium']:,.2f}")
            print(f"   Max Loss: ₹{decision['max_loss']:,.2f}")

        print()
        if decision['confidence'] >= 0.70:
            print("✅ PASS: Confidence meets threshold (≥70%)")
        else:
            print(f"⚠️  Confidence {decision['confidence']:.1%} below threshold (70%)")

        return decision

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None


async def main():
    """Run all tests"""
    print()
    print("╔═══════════════════════════════════════════════════════════════════════════════╗")
    print("║                     ALGOTRADING AI AGENTS - LIVE TEST                         ║")
    print("║                         Testing Hermes & Athena                               ║")
    print("╚═══════════════════════════════════════════════════════════════════════════════╝")

    # Check API key
    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        print("\n❌ CRITICAL: ANTHROPIC_API_KEY not set in environment!")
        print("   Set it in Railway environment variables or .env file")
        return

    print(f"\n✅ ANTHROPIC_API_KEY: {'*' * 20}{api_key[-8:] if len(api_key) > 8 else '***'}")

    # Run tests
    results = {}

    results['hermes_agent'] = await test_hermes_agent()
    await asyncio.sleep(2)

    results['hermes_service'] = await test_hermes_service()
    await asyncio.sleep(2)

    results['athena_agent'] = await test_athena_agent()

    # Summary
    print_section("📊 TEST SUMMARY")

    hermes_agent_ok = results['hermes_agent'] and results['hermes_agent']['confidence'] >= 0.65
    hermes_service_ok = results['hermes_service'] is not None
    athena_ok = results['athena_agent'] is not None

    print(f"Hermes Agent:   {'✅ PASS' if hermes_agent_ok else '❌ FAIL'}")
    print(f"Hermes Service: {'✅ PASS' if hermes_service_ok else '❌ FAIL'}")
    print(f"Athena Agent:   {'✅ PASS' if athena_ok else '❌ FAIL'}")
    print()

    if hermes_agent_ok and hermes_service_ok and athena_ok:
        print("🎉 ALL TESTS PASSED!")
    else:
        print("⚠️  SOME TESTS FAILED - Check output above for details")

    print()


if __name__ == "__main__":
    asyncio.run(main())
