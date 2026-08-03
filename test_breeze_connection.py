"""
Test ICICI Direct Breeze API Connection

Run this locally (NOT in production):
python test_breeze_connection.py
"""

import os
from datetime import datetime, timedelta

# You'll need to install breeze_connect
# pip install breeze_connect

def test_breeze_connection():
    """Test if Breeze API is working"""

    # Get credentials from environment variables (safer than hardcoding)
    api_key = os.getenv("BREEZE_API_KEY", "your_api_key_here")
    api_secret = os.getenv("BREEZE_API_SECRET", "your_api_secret_here")

    if api_key == "your_api_key_here":
        print("❌ ERROR: Set environment variables first:")
        print("   export BREEZE_API_KEY='your_key'")
        print("   export BREEZE_API_SECRET='your_secret'")
        return False

    try:
        from breeze_connect import BreezeConnect

        breeze = BreezeConnect(api_key=api_key, api_secret=api_secret)
        breeze.generate_session()

        print("✅ Breeze connection successful!")
        print(f"   Session: {breeze.session_key}")

        # Test 1: Get account info
        print("\n📊 Test 1: Fetching account info...")
        account_info = breeze.get_account_info()
        print(f"   Account: {account_info}")

        # Test 2: Get stock quote
        print("\n📈 Test 2: Fetching stock quote (RELIANCE)...")
        quote = breeze.get_quote(exchange_code="NSE", symbol="RELIANCE-EQ")
        print(f"   Price: {quote}")

        # Test 3: Get historical data (last 10 days)
        print("\n📉 Test 3: Fetching historical data (INFY, last 10 days)...")
        today = datetime.now().date()
        start_date = today - timedelta(days=10)

        historical = breeze.get_historical_data(
            exchange_code="NSE",
            symbol="INFY-EQ",
            interval="1d",
            from_date=start_date.strftime("%d-%b-%Y"),
            to_date=today.strftime("%d-%b-%Y")
        )
        print(f"   Data points: {len(historical)}")
        if historical:
            print(f"   Latest: {historical[0]}")

        # Test 4: Get option chain
        print("\n📊 Test 4: Fetching option chain (NIFTY50, next expiry)...")
        option_chain = breeze.get_option_chain(
            exchange_code="NFO",
            symbol="NIFTY50"
        )
        print(f"   Strikes available: {len(option_chain)}")
        if option_chain:
            print(f"   Sample: {option_chain[0]}")

        print("\n✅ ALL TESTS PASSED!")
        print("\nYou can now use Breeze for backtesting.")
        return True

    except ImportError:
        print("❌ breeze_connect not installed")
        print("   Run: pip install breeze_connect")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        print(f"   Check your API credentials")
        return False

if __name__ == "__main__":
    test_breeze_connection()
