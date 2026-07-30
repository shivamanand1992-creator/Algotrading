"""
GROWSECT15 Intraday Trending Alerts Service
============================================

Daily 9:30 AM IST alert showing:
- GROWSECT15 stocks where BOTH stock AND sector are trending (positive % change)
- Ranked by % gain for intraday trading
- Sends to multiple Telegram users

Config storage: backend/data/growsect_alerts_config.json
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
_CONFIG_FILE = "/home/user/Algotrading/backend/data/growsect_alerts_config.json"

# Default GROWSECT15 stocks with sectors
DEFAULT_WATCHLIST = {
    "DIVISLAB": "Pharma",
    "HINDUNILVR": "FMCG",
    "INFY": "IT",
    "CIPLA": "Pharma",
    "TCS": "IT",
    "PERSISTENT": "IT",
    "TVSMOTOR": "Auto",
    "NESTLEIND": "FMCG",
    "TECHM": "IT",
    "APOLLOHOSP": "Healthcare",
    "MARUTI": "Auto",
    "SUNPHARMA": "Pharma",
    "TITAN": "Consumer",
    "EICHERMOT": "Auto",
    "M&M": "Auto",
}

# Default Telegram users
DEFAULT_TELEGRAM_IDS = [
    8274242401,   # Shivam
    1619146075,   # Gaurav
]

# Sector groups for heatmap calculations
SECTOR_GROUPS = {
    "Pharma": ["DIVISLAB", "CIPLA", "SUNPHARMA"],
    "IT": ["INFY", "TCS", "PERSISTENT", "TECHM"],
    "FMCG": ["HINDUNILVR", "NESTLEIND"],
    "Auto": ["TVSMOTOR", "MARUTI", "EICHERMOT", "M&M"],
    "Healthcare": ["APOLLOHOSP"],
    "Consumer": ["TITAN"],
}


@dataclass
class IntradayStock:
    """Stock data for intraday filtering"""
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
            logger.warning(f"[GrowSect Alerts] Failed to load config: {e}, using defaults")

    # Create default config
    config = {
        "watchlist": DEFAULT_WATCHLIST,
        "telegram_ids": DEFAULT_TELEGRAM_IDS,
        "created_at": datetime.now(_IST).isoformat(),
    }

    # Ensure directory exists
    os.makedirs(os.path.dirname(_CONFIG_FILE), exist_ok=True)

    try:
        with open(_CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        logger.info(f"[GrowSect Alerts] Created default config at {_CONFIG_FILE}")
    except Exception as e:
        logger.error(f"[GrowSect Alerts] Failed to save config: {e}")

    return config


def _save_config(config: Dict) -> bool:
    """Save config to file"""
    try:
        os.makedirs(os.path.dirname(_CONFIG_FILE), exist_ok=True)
        with open(_CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        logger.info("[GrowSect Alerts] Config saved")
        return True
    except Exception as e:
        logger.error(f"[GrowSect Alerts] Failed to save config: {e}")
        return False


def get_config() -> Dict:
    """Get current config"""
    return _load_config()


def update_watchlist(new_watchlist: Dict[str, str]) -> bool:
    """
    Update the GROWSECT15 watchlist

    Args:
        new_watchlist: Dict of {symbol: sector, ...}

    Returns:
        True if successful
    """
    if not isinstance(new_watchlist, dict) or len(new_watchlist) == 0:
        logger.error("[GrowSect Alerts] Invalid watchlist format")
        return False

    config = _load_config()
    config["watchlist"] = new_watchlist
    config["watchlist_updated_at"] = datetime.now(_IST).isoformat()

    success = _save_config(config)
    if success:
        logger.info(f"[GrowSect Alerts] Watchlist updated with {len(new_watchlist)} stocks")
    return success


def add_telegram_user(chat_id: int) -> bool:
    """Add a Telegram user ID to receive alerts"""
    if not isinstance(chat_id, int) or chat_id <= 0:
        logger.error("[GrowSect Alerts] Invalid chat ID")
        return False

    config = _load_config()
    if chat_id not in config.get("telegram_ids", []):
        config.setdefault("telegram_ids", []).append(chat_id)
        success = _save_config(config)
        if success:
            logger.info(f"[GrowSect Alerts] Added Telegram user {chat_id}")
        return success

    logger.info(f"[GrowSect Alerts] Chat ID {chat_id} already exists")
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
            logger.info(f"[GrowSect Alerts] Removed Telegram user {chat_id}")
        return success

    logger.info(f"[GrowSect Alerts] Chat ID {chat_id} not found")
    return False


def get_telegram_users() -> List[int]:
    """Get list of registered Telegram users"""
    config = _load_config()
    return config.get("telegram_ids", DEFAULT_TELEGRAM_IDS)


async def send_to_telegram(chat_id: int, text: str) -> bool:
    """Send message to a specific Telegram user"""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

    if not token:
        logger.debug("[GrowSect Alerts] Telegram bot token not configured")
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
                logger.info(f"[GrowSect Alerts] Message sent to {chat_id}")
                return True
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except:
            body = "(unreadable)"
        logger.error(f"[GrowSect Alerts] Send failed HTTP {exc.code}: {body}")
    except Exception as exc:
        logger.error(f"[GrowSect Alerts] Send failed: {exc}")

    return False


async def broadcast_alert(title: str, stocks_data: List[IntradayStock]) -> None:
    """
    Send intraday trending alert to all registered Telegram users

    Args:
        title: Alert title (e.g., "📈 GROWSECT15 INTRADAY MOVERS — 30 Jul 09:30")
        stocks_data: List of IntradayStock objects (already filtered & sorted by % gain)
    """
    if not stocks_data:
        logger.info("[GrowSect Alerts] No stocks to alert")
        return

    # Build message
    lines = [f"<b>{title}</b>", ""]
    lines.append("<b>Stocks to trade (both stock & sector trending):</b>")
    lines.append("")

    for stock in stocks_data:
        lines.append(
            f"<b>{stock.symbol}</b> | {stock.sector}\n"
            f"  Stock: <b>{stock.change_pct:+.2f}%</b> | Sector: <b>{stock.sector_change_pct:+.2f}%</b>"
        )

    lines.append("")
    lines.append("<i>Execute intraday trades on these with sector tailwind.</i>")

    message = "\n".join(lines)

    # Send to all registered users
    telegram_ids = get_telegram_users()
    if not telegram_ids:
        logger.warning("[GrowSect Alerts] No Telegram users configured")
        return

    logger.info(f"[GrowSect Alerts] Sending alert to {len(telegram_ids)} users")
    tasks = [send_to_telegram(chat_id, message) for chat_id in telegram_ids]
    results = await asyncio.gather(*tasks)

    success_count = sum(1 for r in results if r)
    logger.info(f"[GrowSect Alerts] Alert sent to {success_count}/{len(telegram_ids)} users")


# Initialize config on module load
_load_config()
