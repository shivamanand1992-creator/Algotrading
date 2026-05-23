"""
Alert system: Telegram and email notifications for trade events.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional
import requests
from loguru import logger
import pytz

IST = pytz.timezone("Asia/Kolkata")


class TelegramAlerter:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.enabled = bool(bot_token and chat_id)

    def send(self, message: str) -> bool:
        if not self.enabled:
            return False
        try:
            resp = requests.post(
                f"{self.base_url}/sendMessage",
                json={"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"},
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.warning(f"Telegram alert failed: {e}")
            return False


class EmailAlerter:
    def __init__(self, smtp_host: str, smtp_port: int, sender: str, password: str, recipient: str):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.sender = sender
        self.password = password
        self.recipient = recipient
        self.enabled = bool(sender and password and recipient)

    def send(self, subject: str, body: str) -> bool:
        if not self.enabled:
            return False
        try:
            msg = MIMEMultipart()
            msg["From"] = self.sender
            msg["To"] = self.recipient
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "html"))
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender, self.password)
                server.send_message(msg)
            return True
        except Exception as e:
            logger.warning(f"Email alert failed: {e}")
            return False


class AlertManager:
    def __init__(self, config: dict):
        notif = config.get("notifications", {})
        tg = notif.get("telegram", {})
        em = notif.get("email", {})

        self.telegram = TelegramAlerter(
            bot_token=tg.get("bot_token", ""),
            chat_id=tg.get("chat_id", ""),
        ) if tg.get("enabled") else None

        self.email = EmailAlerter(
            smtp_host=em.get("smtp_host", "smtp.gmail.com"),
            smtp_port=em.get("smtp_port", 587),
            sender=em.get("sender", ""),
            password=em.get("password", ""),
            recipient=em.get("recipient", ""),
        ) if em.get("enabled") else None

        self.alert_on = set(notif.get("alert_on", []))

    def _now(self) -> str:
        return datetime.now(IST).strftime("%d %b %Y %H:%M:%S")

    def _dispatch(self, event: str, message: str, subject: str = ""):
        if event not in self.alert_on:
            return
        logger.info(f"ALERT [{event}]: {message}")
        if self.telegram:
            self.telegram.send(message)
        if self.email and subject:
            self.email.send(subject, message)

    def trade_entry(self, symbol: str, action: str, qty: int, price: float, strike: int, expiry: str, strategy: str):
        msg = (
            f"🟢 <b>TRADE ENTRY</b>\n"
            f"📅 {self._now()}\n"
            f"📌 {action} | {symbol} {strike} {expiry}\n"
            f"📦 Qty: {qty} | Entry: ₹{price:.2f}\n"
            f"🎯 Strategy: {strategy}"
        )
        self._dispatch("trade_entry", msg, f"Trade Entry: {action} {symbol}")

    def trade_exit(self, symbol: str, pnl: float, reason: str, entry_price: float, exit_price: float):
        icon = "🟩" if pnl >= 0 else "🟥"
        msg = (
            f"{icon} <b>TRADE EXIT</b>\n"
            f"📅 {self._now()}\n"
            f"📌 {symbol}\n"
            f"💰 P&L: ₹{pnl:+,.0f}\n"
            f"📊 Entry: ₹{entry_price:.2f} → Exit: ₹{exit_price:.2f}\n"
            f"📝 Reason: {reason}"
        )
        self._dispatch("trade_exit", msg, f"Trade Exit: {symbol} P&L ₹{pnl:+,.0f}")

    def sl_hit(self, symbol: str, sl_price: float, pnl: float):
        msg = (
            f"🛑 <b>STOP LOSS HIT</b>\n"
            f"📅 {self._now()}\n"
            f"📌 {symbol}\n"
            f"🔴 SL: ₹{sl_price:.2f} | Loss: ₹{pnl:,.0f}"
        )
        self._dispatch("sl_hit", msg, f"SL Hit: {symbol}")

    def target_hit(self, symbol: str, target_price: float, pnl: float):
        msg = (
            f"🎯 <b>TARGET HIT</b>\n"
            f"📅 {self._now()}\n"
            f"📌 {symbol}\n"
            f"🟢 Target: ₹{target_price:.2f} | Profit: ₹{pnl:,.0f}"
        )
        self._dispatch("target_hit", msg, f"Target Hit: {symbol}")

    def daily_loss_limit(self, daily_pnl: float, limit: float):
        msg = (
            f"⛔ <b>DAILY LOSS LIMIT HIT</b>\n"
            f"📅 {self._now()}\n"
            f"💸 Daily P&L: ₹{daily_pnl:,.0f}\n"
            f"🔒 Limit: ₹{limit:,.0f}\n"
            f"⚠️ All positions squared off. Trading halted for today."
        )
        self._dispatch("daily_loss_limit", msg, "ALERT: Daily Loss Limit Hit!")

    def system_error(self, error: str):
        msg = (
            f"🚨 <b>SYSTEM ERROR</b>\n"
            f"📅 {self._now()}\n"
            f"❌ {error}"
        )
        self._dispatch("system_error", msg, "SYSTEM ERROR: Trading System")

    def daily_summary(self, stats: dict):
        pnl = stats.get("daily_pnl", 0)
        trades = stats.get("trades", 0)
        wins = stats.get("wins", 0)
        losses = stats.get("losses", 0)
        win_rate = wins / trades * 100 if trades > 0 else 0
        icon = "📈" if pnl >= 0 else "📉"
        msg = (
            f"{icon} <b>DAILY TRADING SUMMARY</b>\n"
            f"📅 {self._now()}\n"
            f"💰 Net P&L: ₹{pnl:+,.0f}\n"
            f"📊 Trades: {trades} | Wins: {wins} | Losses: {losses}\n"
            f"🎯 Win Rate: {win_rate:.1f}%"
        )
        if self.telegram:
            self.telegram.send(msg)
        if self.email:
            self.email.send("Daily Trading Summary", msg)
