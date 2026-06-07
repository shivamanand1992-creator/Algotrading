"""
Telegram notification service.

Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in Railway environment variables.
Get your bot token from @BotFather on Telegram.
Get your chat ID by messaging @userinfobot on Telegram.
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from loguru import logger

_IST = timezone(timedelta(hours=5, minutes=30))

_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID",   "").strip()


def is_configured() -> bool:
    return bool(_TOKEN and _CHAT_ID)


def send(text: str, parse_mode: str = "HTML") -> bool:
    """Send a Telegram message. Returns True on success."""
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
    text = (
        f"⚠️ *JARVIS — Low Balance Alert*\n\n"
        f"• Available Cash: ₹{available:,.0f}\n"
        f"• Min Required for next DCA: ₹{required:,.0f}\n\n"
        f"Please top up your Angel One account to continue automatic NiftyBees accumulation."
    )
    return send(text)


def send_trade_notification(action: str, symbol: str, qty: int, price: float,
                            mode: str, reason: str = "") -> bool:
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
