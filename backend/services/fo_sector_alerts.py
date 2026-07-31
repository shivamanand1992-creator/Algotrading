"""
F&O Sector Trending Alerts Service
===================================

Daily 9:30 AM alert showing top F&O stocks from trending sectors
- Identifies trending sectors (sector % change > 0)
- Shows top 2-3 F&O stocks from each trending sector (ranked by % gain)
- Sends to multiple Telegram users

Config storage: backend/data/fo_sector_alerts_config.json
"""

import json
import os
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from dataclasses import dataclass
import urllib.request
import urllib.error

from loguru import logger

_IST = timezone(timedelta(hours=5, minutes=30))
_CONFIG_FILE = "/home/user/Algotrading/backend/data/fo_sector_alerts_config.json"

# F&O stocks mapped to sectors (India's major F&O eligible stocks)
DEFAULT_FO_STOCKS = {
    # Banking
    "RELIANCE": "Energy",
    "TCS": "IT",
    "HDFC": "Finance",
    "HDFC BANK": "Finance",
    "ICICI BANK": "Finance",
    "AXIS BANK": "Finance",
    "KOTAK BANK": "Finance",
    "INFY": "IT",
    "WIPRO": "IT",
    "TECHM": "IT",
    "PERSISTENT": "IT",
    # Auto
    "MARUTI": "Auto",
    "BAJAJ-AUTO": "Auto",
    "TATA MOTORS": "Auto",
    "EICHERMOT": "Auto",
    "M&M": "Auto",
    # Pharma
    "SUNPHARMA": "Pharma",
    "CIPLA": "Pharma",
    "DIVISLAB": "Pharma",
    "LUPIN": "Pharma",
    "DIVI'S LAB": "Pharma",
    # Consumer & Telecom
    "HUL": "Consumer",
    "ITC": "Consumer",
    "NESTLEIND": "Consumer",
    "BRITANNIA": "Consumer",
    "JIOTOWER": "Telecom",
    "AIRTEL": "Telecom",
    # Cement & Utilities
    "ULTRACEMCO": "Cement",
    "SHREECEM": "Cement",
    "ADANIPOWER": "Utilities",
    "NTPC": "Utilities",
    # Metals & Others
    "TATASTEEL": "Metals",
    "HINDALCO": "Metals",
    "ADANIGREEN": "Utilities",
    "LT": "Infrastructure",
    "BAJAJFINSV": "Finance",
}

# Sector groups for analysis
SECTOR_STOCKS = {
    "IT": ["TCS", "INFY", "WIPRO", "TECHM", "PERSISTENT"],
    "Finance": ["HDFC", "HDFC BANK", "ICICI BANK", "AXIS BANK", "KOTAK BANK", "BAJAJFINSV"],
    "Auto": ["MARUTI", "BAJAJ-AUTO", "TATA MOTORS", "EICHERMOT", "M&M"],
    "Pharma": ["SUNPHARMA", "CIPLA", "DIVISLAB", "LUPIN"],
    "Energy": ["RELIANCE"],
    "Consumer": ["HUL", "ITC", "NESTLEIND", "BRITANNIA"],
    "Telecom": ["JIOTOWER", "AIRTEL"],
    "Cement": ["ULTRACEMCO", "SHREECEM"],
    "Utilities": ["ADANIPOWER", "NTPC", "ADANIGREEN"],
    "Infrastructure": ["LT"],
    "Metals": ["TATASTEEL", "HINDALCO"],
}


@dataclass
class FoStock:
    """F&O stock data for sector filtering"""
    symbol: str
    sector: str
    price: float
    change_pct: float
    sector_change_pct: float
    timestamp: datetime


def _load_config() -> Dict:
    """Load config from file, or create with defaults"""
    if os.path.exists(_CONFIG_FILE):
        try:
            with open(_CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"[FO Alerts] Failed to load config: {e}, using defaults")

    # Create default config
    config = {
        "fo_stocks": DEFAULT_FO_STOCKS,
        "telegram_ids": [],  # No defaults for F&O
        "top_per_sector": 3,  # Top 3 stocks per trending sector
        "created_at": datetime.now(_IST).isoformat(),
    }

    # Ensure directory exists
    os.makedirs(os.path.dirname(_CONFIG_FILE), exist_ok=True)

    try:
        with open(_CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        logger.info(f"[FO Alerts] Created default config at {_CONFIG_FILE}")
    except Exception as e:
        logger.error(f"[FO Alerts] Failed to save config: {e}")

    return config


def _save_config(config: Dict) -> bool:
    """Save config to file"""
    try:
        os.makedirs(os.path.dirname(_CONFIG_FILE), exist_ok=True)
        with open(_CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        logger.info("[FO Alerts] Config saved")
        return True
    except Exception as e:
        logger.error(f"[FO Alerts] Failed to save config: {e}")
        return False


def get_config() -> Dict:
    """Get current config"""
    return _load_config()


def update_fo_stocks(new_stocks: Dict[str, str]) -> bool:
    """
    Update the F&O stocks watchlist

    Args:
        new_stocks: Dict of {symbol: sector, ...}

    Returns:
        True if successful
    """
    if not isinstance(new_stocks, dict) or len(new_stocks) == 0:
        logger.error("[FO Alerts] Invalid stocks format")
        return False

    config = _load_config()
    config["fo_stocks"] = new_stocks
    config["stocks_updated_at"] = datetime.now(_IST).isoformat()

    success = _save_config(config)
    if success:
        logger.info(f"[FO Alerts] F&O stocks updated with {len(new_stocks)} symbols")
    return success


def add_telegram_user(chat_id: int) -> bool:
    """Add a Telegram user ID to receive F&O alerts"""
    if not isinstance(chat_id, int) or chat_id <= 0:
        logger.error("[FO Alerts] Invalid chat ID")
        return False

    config = _load_config()
    if chat_id not in config.get("telegram_ids", []):
        config.setdefault("telegram_ids", []).append(chat_id)
        success = _save_config(config)
        if success:
            logger.info(f"[FO Alerts] Added Telegram user {chat_id}")
        return success

    logger.info(f"[FO Alerts] Chat ID {chat_id} already exists")
    return True


def remove_telegram_user(chat_id: int) -> bool:
    """Remove a Telegram user ID"""
    config = _load_config()
    telegram_ids = config.get("telegram_ids", [])

    if chat_id in telegram_ids:
        telegram_ids.remove(chat_id)
        config["telegram_ids"] = telegram_ids
        success = _save_config(config)
        if success:
            logger.info(f"[FO Alerts] Removed Telegram user {chat_id}")
        return success

    logger.info(f"[FO Alerts] Chat ID {chat_id} not found")
    return False


def get_telegram_users() -> List[int]:
    """Get list of registered Telegram users for F&O alerts"""
    config = _load_config()
    return config.get("telegram_ids", [])


async def send_to_telegram(chat_id: int, text: str) -> bool:
    """Send message to a specific Telegram user"""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

    if not token:
        logger.debug("[FO Alerts] Telegram bot token not configured")
        return False

    try:
        payload = json.dumps({
            "chat_id": chat_id,
            "text": text[:4096],  # Telegram limit
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }).encode()

        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
        )

        with urllib.request.urlopen(req, timeout=12) as resp:
            if resp.status == 200:
                logger.info(f"[FO Alerts] Message sent to {chat_id}")
                return True
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except:
            body = "(unreadable)"
        logger.error(f"[FO Alerts] Send failed HTTP {exc.code}: {body}")
    except Exception as exc:
        logger.error(f"[FO Alerts] Send failed: {exc}")

    return False


async def broadcast_alert(title: str, stocks_by_sector: Dict[str, List[FoStock]]) -> None:
    """
    Send F&O sector trending alert to all registered Telegram users

    Args:
        title: Alert title
        stocks_by_sector: Dict of {sector: [top stocks]}
    """
    if not stocks_by_sector:
        logger.info("[FO Alerts] No stocks to alert")
        return

    # Build message
    lines = [f"<b>{title}</b>", ""]
    lines.append("<b>Top F&O stocks by trending sector:</b>")
    lines.append("")

    for sector in sorted(stocks_by_sector.keys()):
        stocks = stocks_by_sector[sector]
        if not stocks:
            continue

        lines.append(f"<b>▸ {sector}</b> ({len(stocks)} stocks)")
        for i, stock in enumerate(stocks, 1):
            lines.append(
                f"  {i}. <b>{stock.symbol}</b> • {stock.change_pct:+.2f}% "
                f"(Sector {stock.sector_change_pct:+.2f}%)"
            )
        lines.append("")

    lines.append("<i>Execute F&O trades on these with sector momentum.</i>")

    message = "\n".join(lines)

    # Send to all registered users
    telegram_ids = get_telegram_users()
    if not telegram_ids:
        logger.warning("[FO Alerts] No Telegram users configured for F&O alerts")
        return

    logger.info(f"[FO Alerts] Sending alert to {len(telegram_ids)} users")
    tasks = [send_to_telegram(chat_id, message) for chat_id in telegram_ids]
    results = await asyncio.gather(*tasks)

    success_count = sum(1 for r in results if r)
    logger.info(f"[FO Alerts] Alert sent to {success_count}/{len(telegram_ids)} users")


# Initialize config on module load
_load_config()
