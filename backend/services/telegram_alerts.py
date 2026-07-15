"""
Telegram Alert Service for Trading Setups
==========================================
Handles all Telegram notifications for both intraday and swing trading alerts.

Features:
- Intraday setup alerts (Opening Breakout, Retest, Consolidation Break)
- Swing trade alerts (entry, exit, stop loss updates)
- End-of-day portfolio summaries
- Low balance warnings
- Trade execution confirmations

Environment Variables:
- TELEGRAM_BOT_TOKEN: Bot token from @BotFather
- TELEGRAM_CHAT_ID: Your chat ID from @userinfobot
"""

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from loguru import logger

_IST = timezone(timedelta(hours=5, minutes=30))

_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID",   "").strip()


def is_configured() -> bool:
    """Check if Telegram credentials are configured."""
    return bool(_TOKEN and _CHAT_ID)


def send(text: str, parse_mode: str = "HTML") -> bool:
    """
    Send a Telegram message. Returns True on success.

    Args:
        text: Message text (max 4096 chars)
        parse_mode: Telegram parse mode (HTML or Markdown)

    Returns:
        bool: True if message was sent successfully
    """
    if not is_configured():
        logger.debug("[Telegram] Not configured — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")
        return False

    # Convert legacy Markdown bold (*text*) to HTML (<b>text</b>) since we use HTML mode
    # HTML is more robust — no escaping issues with special chars like . ! ( ) -
    if parse_mode == "HTML":
        import re
        text = re.sub(r'\*([^*]+)\*', r'<b>\1</b>', text)
        text = re.sub(r'_([^_]+)_', r'<i>\1</i>', text)

    try:
        payload = json.dumps({
            "chat_id":    _CHAT_ID,
            "text":       text[:4096],   # Telegram limit
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }).encode()

        req = urllib.request.Request(
            f"https://api.telegram.org/bot{_TOKEN}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
        )

        with urllib.request.urlopen(req, timeout=12) as resp:
            ok = resp.status == 200

        if ok:
            logger.info("[Telegram] Message sent.")
        return ok

    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = "(unreadable)"
        logger.error(f"[Telegram] Send failed HTTP {exc.code}: {body}")
        return False
    except Exception as exc:
        logger.error(f"[Telegram] Send failed: {exc}")
        return False


# ---------------------------------------------------------------------------
# Intraday Setup Alerts
# ---------------------------------------------------------------------------

def send_intraday_setup_alert(
    symbol: str,
    setup_type: str,
    direction: str,
    entry_price: float,
    stop_loss: float,
    targets: List[float],
    confidence: float,
    volume_ratio: float,
    metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Send intraday trading setup alert.

    Format: 🚨 BANK NIFTY - OPENING BREAKOUT | Entry: 43960 | SL: 43945 | Target: 43982

    Args:
        symbol: Trading symbol (e.g., "NIFTY", "BANKNIFTY")
        setup_type: Type of setup (opening_breakout, retest, consolidation_break)
        direction: Trade direction (long/short)
        entry_price: Entry price
        stop_loss: Stop loss price
        targets: List of target prices [T1, T2, T3]
        confidence: Setup confidence score (0.0-1.0)
        volume_ratio: Current volume vs average
        metadata: Additional setup-specific data

    Returns:
        bool: True if alert was sent successfully
    """
    if not is_configured():
        return False

    # Map setup type to readable name
    setup_names = {
        "opening_breakout": "OPENING BREAKOUT",
        "retest": "RETEST SETUP",
        "consolidation_break": "CONSOLIDATION BREAK"
    }
    setup_name = setup_names.get(setup_type, setup_type.upper().replace("_", " "))

    # Direction emoji
    dir_emoji = "🟢" if direction.lower() == "long" else "🔴"
    dir_label = "LONG" if direction.lower() == "long" else "SHORT"

    # Calculate risk:reward
    risk = abs(entry_price - stop_loss)
    reward = abs(targets[0] - entry_price) if targets else 0.0
    rr_ratio = reward / risk if risk > 0 else 0.0

    # Format symbol nicely
    symbol_display = symbol.replace("NIFTY", "NIFTY ").replace("BANKNIFTY", "BANK NIFTY")

    # Build compact alert message (primary line)
    primary_line = (
        f"🚨 *{symbol_display} - {setup_name}*\n"
        f"{dir_emoji} *{dir_label}* | Entry: *{entry_price:.2f}* | "
        f"SL: *{stop_loss:.2f}* | Target: *{targets[0]:.2f}*"
    )

    # Additional details
    details = [
        f"\n📊 *Setup Details:*",
        f"• Risk: {risk:.2f} pts | Reward: {reward:.2f} pts | R:R = *1:{rr_ratio:.1f}*",
        f"• Confidence: {confidence * 100:.0f}% | Volume: {volume_ratio:.1f}x avg",
    ]

    # Add all targets if multiple
    if len(targets) > 1:
        targets_str = " | ".join([f"T{i+1}: {t:.2f}" for i, t in enumerate(targets)])
        details.append(f"• Targets: {targets_str}")

    # Add metadata if available
    if metadata:
        if "opening_range" in metadata:
            or_data = metadata["opening_range"]
            details.append(
                f"• Opening Range: {or_data.get('low', 0):.2f} - {or_data.get('high', 0):.2f}"
            )
        if "consolidation_range" in metadata:
            cons_data = metadata["consolidation_range"]
            details.append(
                f"• Consolidation: {cons_data.get('low', 0):.2f} - {cons_data.get('high', 0):.2f}"
            )
        if "support_level" in metadata or "resistance_level" in metadata:
            sr_level = metadata.get("support_level") or metadata.get("resistance_level")
            level_type = "Support" if "support_level" in metadata else "Resistance"
            details.append(f"• {level_type}: {sr_level:.2f}")

    # Timestamp
    now_ist = datetime.now(_IST).strftime("%I:%M %p")
    details.append(f"\n⏰ {now_ist} IST")

    # Combine message
    message = primary_line + "\n".join(details)

    return send(message)


def send_setup_triggered_alert(
    symbol: str,
    setup_type: str,
    direction: str,
    entry_price: float,
    current_price: float
) -> bool:
    """
    Send alert when setup entry is triggered.

    Args:
        symbol: Trading symbol
        setup_type: Type of setup
        direction: Trade direction
        entry_price: Original entry price
        current_price: Current trigger price

    Returns:
        bool: True if alert was sent successfully
    """
    if not is_configured():
        return False

    setup_names = {
        "opening_breakout": "OPENING BREAKOUT",
        "retest": "RETEST SETUP",
        "consolidation_break": "CONSOLIDATION BREAK"
    }
    setup_name = setup_names.get(setup_type, setup_type.upper().replace("_", " "))

    dir_emoji = "🟢" if direction.lower() == "long" else "🔴"
    symbol_display = symbol.replace("NIFTY", "NIFTY ").replace("BANKNIFTY", "BANK NIFTY")

    message = (
        f"✅ *SETUP TRIGGERED!*\n\n"
        f"{dir_emoji} *{symbol_display} - {setup_name}*\n"
        f"• Entry: {entry_price:.2f}\n"
        f"• Current: {current_price:.2f}\n\n"
        f"🎯 Trade is now active!"
    )

    return send(message)


def send_setup_expired_alert(
    symbol: str,
    setup_type: str,
    reason: str = "Time expired"
) -> bool:
    """
    Send alert when setup expires without triggering.

    Args:
        symbol: Trading symbol
        setup_type: Type of setup
        reason: Reason for expiry

    Returns:
        bool: True if alert was sent successfully
    """
    if not is_configured():
        return False

    setup_names = {
        "opening_breakout": "OPENING BREAKOUT",
        "retest": "RETEST SETUP",
        "consolidation_break": "CONSOLIDATION BREAK"
    }
    setup_name = setup_names.get(setup_type, setup_type.upper().replace("_", " "))
    symbol_display = symbol.replace("NIFTY", "NIFTY ").replace("BANKNIFTY", "BANK NIFTY")

    message = (
        f"⏱️ *Setup Expired*\n\n"
        f"*{symbol_display} - {setup_name}*\n"
        f"• Reason: {reason}\n"
        f"• No entry triggered"
    )

    return send(message)


# ---------------------------------------------------------------------------
# Swing Trade Alerts
# ---------------------------------------------------------------------------

def send_swing_trade_alert(
    action: str,
    symbol: str,
    qty: int,
    price: float,
    stop_loss: Optional[float] = None,
    target: Optional[float] = None,
    conviction_score: Optional[float] = None,
    reason: str = ""
) -> bool:
    """
    Send swing trade entry/exit alert.

    Args:
        action: "ENTRY" or "EXIT"
        symbol: Stock symbol
        qty: Quantity
        price: Entry/exit price
        stop_loss: Stop loss level
        target: Target price
        conviction_score: Conviction score (0-100)
        reason: Trade reason/strategy

    Returns:
        bool: True if alert was sent successfully
    """
    if not is_configured():
        return False

    emoji = "📈" if action.upper() == "ENTRY" else "💰"

    lines = [
        f"{emoji} *SWING TRADE {action.upper()}*\n",
        f"• Symbol: *{symbol}*",
        f"• Qty: {qty} @ ₹{price:.2f}",
        f"• Value: ₹{qty * price:,.0f}",
    ]

    if stop_loss:
        risk_pct = abs((price - stop_loss) / price * 100)
        lines.append(f"• Stop Loss: ₹{stop_loss:.2f} (Risk: {risk_pct:.1f}%)")

    if target:
        reward_pct = abs((target - price) / price * 100)
        lines.append(f"• Target: ₹{target:.2f} (Reward: {reward_pct:.1f}%)")

        if stop_loss:
            rr = abs(target - price) / abs(price - stop_loss)
            lines.append(f"• Risk:Reward = 1:{rr:.1f}")

    if conviction_score:
        lines.append(f"• Conviction: {conviction_score:.0f}/100")

    if reason:
        lines.append(f"• Reason: {reason}")

    return send("\n".join(lines))


# ---------------------------------------------------------------------------
# Legacy Functions (for backward compatibility)
# ---------------------------------------------------------------------------

def send_eod_report(nb_service, swing_positions: list, balance: dict) -> bool:
    """Compose and send End-of-Day summary."""
    now_ist = datetime.now(_IST).strftime("%d %b %Y")
    lines   = [f"🤖 *JARVIS EOD Report — {now_ist}*\n"]

    # ── NiftyBees ──────────────────────────────────────────────────────
    pos = nb_service._position if nb_service else None
    if pos and pos.get("active"):
        pnl_pct = pos.get("pnl_pct", 0.0)
        pnl_abs = pos.get("unrealized_pnl", 0.0)
        invested  = pos.get("total_invested", 0.0)
        cur_price = pos.get("current_price", 0.0)
        cur_val   = pos.get("total_qty", 0) * cur_price
        emoji     = "🟢" if pnl_abs >= 0 else "🔴"
        lines += [
            "*🐝 NiftyBees ETF*",
            f"• Units: {pos.get('total_qty', 0)} | Avg buy: ₹{pos.get('avg_entry_price', 0):.2f} | CMP: ₹{cur_price:.2f}",
            f"• Invested: ₹{invested:,.0f} | Current: ₹{cur_val:,.0f}",
            f"• Unrealised P&L: {emoji} ₹{pnl_abs:,.0f} ({pnl_pct:+.2f}%)",
            f"• DCA buys: {len(pos.get('buys', []))}"
            f" | Mode: {'🔴 LIVE' if pos.get('mode') == 'live' else '📝 Paper'}",
        ]
    else:
        lines.append("*🐝 NiftyBees ETF*\n• No active position")

    lines.append("")

    # ── Swing Positions ────────────────────────────────────────────────
    open_swings = [p for p in swing_positions if p.get("status") == "open"]
    if open_swings:
        total_invested_sw = sum(p.get("entry_price", 0) * p.get("qty", 0) for p in open_swings)
        total_pnl_sw      = sum(p.get("unrealized_pnl", 0) for p in open_swings)
        emoji_tot         = "🟢" if total_pnl_sw >= 0 else "🔴"
        lines.append("*📈 Equity Swing Positions*")
        for p in open_swings:
            pct   = p.get("pnl_pct", 0.0)
            pnl   = p.get("unrealized_pnl", 0.0)
            emoji = "🟢" if pnl >= 0 else "🔴"
            cap   = p.get("entry_price", 0) * p.get("qty", 0)
            lines.append(
                f"• {p['symbol']} × {p.get('qty', 0)} | ₹{p.get('entry_price', 0):.0f} → "
                f"₹{p.get('current_price', 0):.0f} {emoji} {pct:+.2f}% | Deployed: ₹{cap:,.0f}"
            )
        lines.append(f"• Total Deployed: ₹{total_invested_sw:,.0f} | P&L: {emoji_tot} ₹{total_pnl_sw:,.0f}")
    else:
        lines.append("*📈 Equity Swing*\n• No open positions")

    lines.append("")

    # ── Balance ────────────────────────────────────────────────────────
    if balance:
        avail = balance.get("available_cash", 0.0)
        net   = balance.get("net", 0.0)
        lines += [
            "*💰 Angel One Balance*",
            f"• Available Cash: ₹{avail:,.0f}",
            f"• Net Portfolio: ₹{net:,.0f}",
        ]
        # Next trade estimate
        nb_cfg = nb_service._config if nb_service else {}
        chunk  = nb_cfg.get("capital_amount", 10000)
        lines.append(f"\n*📅 Tomorrow's DCA Estimate*")
        lines.append(f"• NiftyBees chunk size: ~₹{chunk:,.0f}")
        if avail < chunk * 1.2:
            lines.append(f"⚠️ *Balance low — top up needed before market open!*")
        else:
            lines.append(f"✅ Sufficient funds for {int(avail // chunk)} more DCA chunk(s)")

    lines.append("\n_Good night! JARVIS signing off._ 🌙")
    return send("\n".join(lines))


def send_low_balance_alert(available: float, required: float) -> bool:
    """Send low balance alert for DCA trades."""
    text = (
        f"⚠️ *JARVIS — Low Balance Alert*\n\n"
        f"• Available Cash: ₹{available:,.0f}\n"
        f"• Min Required for next DCA: ₹{required:,.0f}\n\n"
        f"Please top up your Angel One account to continue automatic NiftyBees accumulation."
    )
    return send(text)


def send_trade_notification(action: str, symbol: str, qty: int, price: float,
                            mode: str, reason: str = "") -> bool:
    """Send trade execution notification (DCA/NiftyBees)."""
    emoji = "🛒" if action == "BUY" else "💰"
    mode_label = "📝 PAPER" if mode == "paper" else "🔴 LIVE"
    lines = [
        f"{emoji} *JARVIS {action}* — {mode_label}",
        f"• Symbol: *{symbol}*",
        f"• Qty: {qty} @ ₹{price:.2f}",
        f"• Value: ₹{qty * price:,.0f}",
    ]
    if reason:
        lines.append(f"• Reason: {reason}")
    return send("\n".join(lines))
