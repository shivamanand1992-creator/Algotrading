"""
Historical Data Importer
Downloads 5-min candles from Angel One and stores in SQLite for ML training.

Usage (on Railway or with .env credentials):
    python -m backend.ml.data_importer --days 30
"""

import argparse
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from loguru import logger

_IST = timezone(timedelta(hours=5, minutes=30))

# SQLite DB lives alongside trained models (Railway volume: /data)
DB_DIR = Path("/data") if Path("/data").exists() else Path(__file__).parent / "storage"
DB_PATH = DB_DIR / "ml_intraday.db"

# NSE F&O liquid stocks - top 50 by volume/liquidity
UNIVERSE = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS",
    "SBIN", "AXISBANK", "KOTAKBANK", "LT", "ITC",
    "BHARTIARTL", "HINDUNILVR", "BAJFINANCE", "MARUTI", "M&M",
    "TATAMOTORS", "TATASTEEL", "SUNPHARMA", "TITAN", "ULTRACEMCO",
    "WIPRO", "HCLTECH", "TECHM", "NTPC", "POWERGRID",
    "ONGC", "COALINDIA", "JSWSTEEL", "HINDALCO", "ADANIENT",
    "ADANIPORTS", "BAJAJFINSV", "ASIANPAINT", "NESTLEIND", "GRASIM",
    "CIPLA", "DRREDDY", "APOLLOHOSP", "DIVISLAB", "EICHERMOT",
    "HEROMOTOCO", "BAJAJ-AUTO", "BRITANNIA", "INDUSINDBK", "TATACONSUM",
    "SBILIFE", "HDFCLIFE", "BPCL", "UPL", "LTIM",
]


def get_db() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candles_5min (
            symbol TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume INTEGER NOT NULL,
            PRIMARY KEY (symbol, timestamp)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_candles_ts ON candles_5min(timestamp)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS index_candles_5min (
            symbol TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            PRIMARY KEY (symbol, timestamp)
        )
    """)
    return conn


def import_symbol(client, conn: sqlite3.Connection, symbol: str, days: int) -> int:
    """Import candles for one symbol. Returns row count inserted."""
    try:
        token = client.search_scrip("NSE", symbol)
        if not token:
            logger.warning(f"[Importer] Token not found for {symbol}, skipping")
            return 0
    except Exception as e:
        logger.warning(f"[Importer] Failed to search {symbol}: {e}")
        return 0

    now = datetime.now(_IST)
    total = 0

    # Angel One caps ~100 days of 5-min data per request; chunk by 10 days to be safe
    chunk_days = 10
    start = now - timedelta(days=days)
    while start < now:
        end = min(start + timedelta(days=chunk_days), now)
        try:
            df = client.get_historical_data(
                exchange="NSE",
                symbol_token=token,
                interval="FIVE_MINUTE",
                from_date=start.strftime("%Y-%m-%d %H:%M"),
                to_date=end.strftime("%Y-%m-%d %H:%M"),
            )
            if df is not None and len(df) > 0:
                df = df.copy()
                df["symbol"] = symbol
                df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.strftime("%Y-%m-%d %H:%M:%S")
                rows = df[["symbol", "timestamp", "open", "high", "low", "close", "volume"]].values.tolist()
                conn.executemany(
                    "INSERT OR REPLACE INTO candles_5min VALUES (?,?,?,?,?,?,?)", rows
                )
                conn.commit()
                total += len(rows)
                logger.debug(f"[Importer] {symbol} {start.date()}→{end.date()}: {len(rows)} candles")
        except Exception as e:
            logger.warning(f"[Importer] {symbol} chunk {start.date()}–{end.date()} failed: {e}")

        start = end
        time.sleep(1.2)  # Angel One: client enforces 1.0s min between requests, add 0.2s buffer

    logger.info(f"[Importer] {symbol}: {total} candles stored")
    return total


def import_index(client, conn: sqlite3.Connection, name: str, token: str, days: int) -> int:
    """Import index candles (NIFTY/BANKNIFTY) for market-context features."""
    now = datetime.now(_IST)
    total = 0
    start = now - timedelta(days=days)
    while start < now:
        end = min(start + timedelta(days=10), now)
        try:
            df = client.get_historical_data(
                exchange="NSE",
                symbol_token=token,
                interval="FIVE_MINUTE",
                from_date=start.strftime("%Y-%m-%d %H:%M"),
                to_date=end.strftime("%Y-%m-%d %H:%M"),
            )
            if df is not None and len(df) > 0:
                df = df.copy()
                df["symbol"] = name
                df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.strftime("%Y-%m-%d %H:%M:%S")
                rows = df[["symbol", "timestamp", "open", "high", "low", "close", "volume"]].values.tolist()
                conn.executemany(
                    "INSERT OR REPLACE INTO index_candles_5min VALUES (?,?,?,?,?,?,?)", rows
                )
                conn.commit()
                total += len(rows)
        except Exception as e:
            logger.warning(f"[Importer] {name} chunk failed: {e}")
        start = end
        time.sleep(1.2)
    logger.info(f"[Importer] {name}: {total} candles stored")
    return total


def run_import(days: int = 30, symbols: list = None, progress_callback=None) -> dict:
    """Main import entry point. Returns summary dict. Progress callback for UI updates."""
    from backend.dependencies import get_angel_client

    client = get_angel_client()
    conn = get_db()
    symbols = symbols or UNIVERSE
    total_symbols = len(symbols)

    logger.info(f"[Importer] Starting import: {total_symbols} symbols × {days} days")
    results = {}

    # Indices first (needed for market-context features)
    results["NIFTY50"] = import_index(client, conn, "NIFTY50", "26000", days)
    results["BANKNIFTY"] = import_index(client, conn, "BANKNIFTY", "99926000", days)

    for i, symbol in enumerate(symbols, 1):
        results[symbol] = import_symbol(client, conn, symbol, days)

        # Update progress callback for UI
        if progress_callback:
            progress_pct = int((i / total_symbols) * 100)
            progress_callback({
                "status": "importing",
                "message": f"Importing {symbol}... ({i}/{total_symbols})",
                "progress_pct": progress_pct,
                "stocks_done": i,
                "total_stocks": total_symbols,
            })
        logger.info(f"[Importer] Progress: {i}/{total_symbols} — {symbol}")

    conn.close()
    total = sum(results.values())
    logger.info(f"[Importer] DONE — {total} total candles across {len(results)} instruments")
    return {"total_candles": total, "per_symbol": results}


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--symbols", nargs="*", default=None)
    args = parser.parse_args()

    run_import(days=args.days, symbols=args.symbols)
