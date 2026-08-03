#!/usr/bin/env python3
"""
ONE-COMMAND SETUP & BACKTEST
=============================

This script does EVERYTHING:
1. Gets your Breeze credentials
2. Tests connection
3. Downloads 2 years of real data
4. Runs backtests
5. Shows you the results

Just run:
    python setup_breeze_and_backtest.py
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from getpass import getpass

_IST = timezone(timedelta(hours=5, minutes=30))

# Color codes for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
END = '\033[0m'

def print_header(title):
    print(f"\n{BLUE}{'='*60}")
    print(f"{title.center(60)}")
    print(f"{'='*60}{END}\n")

def print_success(msg):
    print(f"{GREEN}✅ {msg}{END}")

def print_error(msg):
    print(f"{RED}❌ {msg}{END}")

def print_info(msg):
    print(f"{YELLOW}ℹ️  {msg}{END}")

def get_credentials():
    """Ask user for Breeze credentials"""
    print_header("Step 1: Breeze API Credentials")

    print("Enter your ICICI Direct Breeze API credentials:")
    print("(You can get these from: https://developer.icicidirect.com/)\n")

    api_key = input(f"{BLUE}API Key:{END} ").strip()
    api_secret = getpass(f"{BLUE}API Secret (won't show):{END} ").strip()

    if not api_key or not api_secret:
        print_error("Credentials cannot be empty!")
        return None, None

    return api_key, api_secret

def test_breeze_connection(api_key, api_secret):
    """Test if Breeze API works"""
    print_header("Step 2: Testing Breeze Connection")

    try:
        from breeze_connect import BreezeConnect

        print_info("Installing breeze_connect if needed...")
        os.system("pip install -q breeze_connect 2>/dev/null")

        print_info("Connecting to Breeze API...")
        breeze = BreezeConnect(api_key=api_key, api_secret=api_secret)
        breeze.generate_session()

        print_success("Connected to Breeze API!")

        # Test getting a quote
        print_info("Testing data access...")
        quote = breeze.get_quote(exchange_code="NSE", symbol="RELIANCE-EQ")
        if quote:
            print_success(f"RELIANCE quote: ₹{quote.get('ltp', 'N/A')}")

        return breeze

    except ImportError:
        print_error("breeze_connect library not found")
        print_info("Installing now...")
        os.system("pip install breeze_connect")
        return test_breeze_connection(api_key, api_secret)
    except Exception as e:
        print_error(f"Connection failed: {e}")
        print_info("Check your API credentials and try again")
        return None

def fetch_data(breeze):
    """Fetch 2 years of historical data"""
    print_header("Step 3: Downloading 2 Years of Real Data")

    if not breeze:
        print_error("No Breeze connection")
        return False

    try:
        # List of stocks to backtest
        stocks = [
            ("NIFTYBEES-EQ", "NiftyBees ETF"),
            ("INFY-EQ", "Infosys"),
            ("TCS-EQ", "Tata Consultancy"),
            ("RELIANCE-EQ", "Reliance"),
            ("HDFC-EQ", "HDFC"),
            ("MARUTI-EQ", "Maruti"),
        ]

        cache_dir = Path("/home/user/Algotrading/backend/data/breeze_cache")
        cache_dir.mkdir(parents=True, exist_ok=True)

        print_info(f"Fetching data for {len(stocks)} stocks...")
        print_info("This may take a few minutes...\n")

        to_date = datetime.now(_IST).date()
        from_date = to_date - timedelta(days=730)  # 2 years

        downloaded = []
        failed = []

        for symbol, name in stocks:
            try:
                print(f"  Fetching {name}...", end=" ", flush=True)

                data = breeze.get_historical_data(
                    exchange_code="NSE",
                    symbol=symbol,
                    interval="1d",
                    from_date=from_date.strftime("%d-%b-%Y"),
                    to_date=to_date.strftime("%d-%b-%Y")
                )

                if data:
                    # Save to cache
                    cache_file = cache_dir / f"{symbol}_1d_730d.json"
                    with open(cache_file, "w") as f:
                        json.dump(data, f)

                    print(f"{GREEN}✓ ({len(data)} bars){END}")
                    downloaded.append((symbol, len(data)))
                else:
                    print(f"{RED}✗ (no data){END}")
                    failed.append(symbol)

            except Exception as e:
                print(f"{RED}✗ (error: {str(e)[:30]}){END}")
                failed.append(symbol)

        print_success(f"Downloaded {len(downloaded)} stocks")
        if failed:
            print_info(f"Failed to download: {', '.join(failed)}")

        return True

    except Exception as e:
        print_error(f"Data fetch failed: {e}")
        return False

def run_backtests():
    """Run backtests on downloaded data"""
    print_header("Step 4: Running Backtests")

    try:
        print_info("Loading backtester...")

        from backtesting.backtester import Backtester
        from backend.data.breeze_data_fetcher import BreezeDataFetcher
        import pandas as pd

        # Load config
        with open("/home/user/Algotrading/config/config.yaml") as f:
            import yaml
            config = yaml.safe_load(f)

        print_info("Running backtests...\n")

        cache_dir = Path("/home/user/Algotrading/backend/data/breeze_cache")

        # Backtest each stock
        results = {}
        stocks_to_test = [
            ("NIFTYBEES-EQ", "NiftyBees DCA"),
            ("INFY-EQ", "INFY Swing"),
            ("TCS-EQ", "TCS Swing"),
        ]

        for symbol, strategy_name in stocks_to_test:
            try:
                cache_file = cache_dir / f"{symbol}_1d_730d.json"
                if not cache_file.exists():
                    print_info(f"Skipping {strategy_name} (no data)")
                    continue

                print(f"  Testing {strategy_name}...", end=" ", flush=True)

                # Load data
                with open(cache_file) as f:
                    data = json.load(f)

                # Convert to DataFrame
                df = pd.DataFrame(data)
                df['date'] = pd.to_datetime(df['date'])
                df.set_index('date', inplace=True)

                # Run backtest
                backtester = Backtester(config, signal_generator=None)
                result = backtester.run(df, start_date="2022-01-01", end_date=None)

                results[strategy_name] = {
                    "trades": result.total_trades,
                    "win_rate": result.win_rate,
                    "pnl": result.total_pnl,
                    "sharpe": result.sharpe_ratio,
                    "drawdown": result.max_drawdown,
                }

                print(f"{GREEN}✓{END}")

            except Exception as e:
                print(f"{RED}✗ ({str(e)[:20]}){END}")
                continue

        # Print results
        print("\n" + "="*60)
        print("BACKTEST RESULTS (REAL DATA)".center(60))
        print("="*60 + "\n")

        if results:
            for strategy, metrics in results.items():
                print(f"{BLUE}{strategy}{END}")
                print(f"  Trades: {metrics['trades']}")
                print(f"  Win Rate: {metrics['win_rate']:.1f}%")
                print(f"  Total P&L: ₹{metrics['pnl']:,.0f}")
                print(f"  Sharpe Ratio: {metrics['sharpe']:.2f}")
                print(f"  Max Drawdown: {metrics['drawdown']:.2f}%")
                print()
        else:
            print_error("No results (data not available)")

        return True

    except Exception as e:
        print_error(f"Backtest failed: {e}")
        print_info("This is okay - we still have your data cached")
        return False

def save_credentials(api_key, api_secret):
    """Optionally save credentials for future use"""
    print_header("Step 5: Save Credentials (Optional)")

    response = input(f"{BLUE}Save credentials for next time? (y/n):{END} ").strip().lower()

    if response == 'y':
        env_file = Path.home() / ".algotrading_credentials"
        with open(env_file, "w") as f:
            f.write(f"BREEZE_API_KEY={api_key}\n")
            f.write(f"BREEZE_API_SECRET={api_secret}\n")
        os.chmod(env_file, 0o600)  # Read/write only for owner
        print_success(f"Credentials saved to {env_file}")
        print_info("Next time, the script will load them automatically")
    else:
        print_info("Credentials not saved")

def main():
    """Main setup flow"""
    print_header("ALGOTRADING - BREEZE API SETUP")
    print("This script will:")
    print("  1. Test your Breeze API connection")
    print("  2. Download 2 years of real market data")
    print("  3. Run backtests on your strategies")
    print("  4. Show you the results\n")
    print("Let's go!\n")

    # Step 1: Get credentials
    api_key, api_secret = get_credentials()
    if not api_key:
        return

    # Step 2: Test connection
    breeze = test_breeze_connection(api_key, api_secret)
    if not breeze:
        return

    # Step 3: Fetch data
    if not fetch_data(breeze):
        print_error("Data fetch failed, but you can try again")
        return

    # Step 4: Run backtests
    run_backtests()

    # Step 5: Save credentials
    save_credentials(api_key, api_secret)

    # Final message
    print_header("SETUP COMPLETE!")
    print(f"{GREEN}Your real market data is ready for backtesting!{END}\n")
    print("Next steps:")
    print("  1. Review the backtest results above")
    print("  2. Check which strategies are profitable")
    print("  3. Paper trade for 2-4 weeks")
    print("  4. Then trade with real money (small amounts first)\n")
    print(f"Data cached in: /home/user/Algotrading/backend/data/breeze_cache/\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Interrupted by user{END}")
        sys.exit(0)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        sys.exit(1)
