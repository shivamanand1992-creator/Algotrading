import sys
import time
import asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta, date as _date

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.requests import Request
from contextlib import asynccontextmanager
from starlette.middleware.base import BaseHTTPMiddleware
from loguru import logger

from backend.config import config
from backend.api.routes import (
    system,
    strategies,
    positions,
    trades,
    market_data,
    risk,
    stocks,
    niftybees,
)
from backend.api.routes import auth as auth_routes
from backend.api.routes import sector_analysis
from backend.api.routes import etf_holdings
from backend.api.routes import jarvis_voice
from backend.api.routes import portfolio as portfolio_routes
from backend.api.routes import conviction as conviction_routes
from backend.api.routes import support_resistance as sr_routes
from backend.api.routes import version as version_routes
from backend.api.routes import ml_intraday as ml_intraday_routes
from backend.api.routes import weekly_income as weekly_income_routes
from backend.api.routes import growsect_heatmap as growsect_routes
from backend.ml.paper_trading_engine import get_paper_engine
# from backend.api.routes import intraday_signals  # TEMPORARILY DISABLED - debugging startup crash
from backend.auth import verify_token
from backend.dependencies import cleanup_dependencies
from backend.websocket_manager import ws_manager

_IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# EOD auto square-off — runs at 15:30 IST every weekday
# ---------------------------------------------------------------------------

async def _eod_squareoff_loop() -> None:
    """Background task: square off all positions at 15:30 IST on trading days."""
    last_squareoff_date: _date | None = None

    while True:
        try:
            now_ist = datetime.now(_IST)
            today   = now_ist.date()

            is_weekday         = today.weekday() < 5          # Mon–Fri
            past_cutoff        = (now_ist.hour, now_ist.minute) >= (15, 30)
            not_done_today     = last_squareoff_date != today

            if is_weekday and past_cutoff and not_done_today:
                last_squareoff_date = today
                logger.warning("EOD 15:30 — auto square-off triggered.")

                # Stop all running strategies first
                try:
                    from backend.api.routes.strategies import get_strategy_service
                    svc = get_strategy_service()
                    for name in list(svc.running_strategies.keys()):
                        await svc.stop_strategy(name)
                        logger.info(f"EOD: strategy '{name}' stopped.")
                except Exception as exc:
                    logger.error(f"EOD strategy stop error: {exc}")

                # Square off all open positions
                try:
                    from backend.dependencies import get_order_manager
                    loop = asyncio.get_event_loop()
                    om = get_order_manager()
                    await loop.run_in_executor(
                        None, om.exit_all_positions, "EOD auto square-off 15:30"
                    )
                    logger.info("EOD: all positions squared off.")
                except Exception as exc:
                    logger.error(f"EOD square-off error: {exc}")

        except Exception as exc:
            logger.error(f"_eod_squareoff_loop unexpected error: {exc}")

        await asyncio.sleep(60)  # check every minute


# ---------------------------------------------------------------------------
# Swing autopilot — scan + auto-execute top 3 at 15:35 IST every weekday
# ---------------------------------------------------------------------------

async def _swing_autopilot_loop() -> None:
    """
    Daily 09:20 IST: scan Nifty50 (using prev-day EOD data) then immediately
    place buy orders — market has been open for 5 minutes so orders execute.
    """
    last_autopilot_date: _date | None = None

    while True:
        try:
            now_ist = datetime.now(_IST)
            today   = now_ist.date()

            is_weekday     = today.weekday() < 5
            past_cutoff    = (now_ist.hour, now_ist.minute) >= (9, 20)
            not_done_today = last_autopilot_date != today

            if is_weekday and past_cutoff and not_done_today:
                last_autopilot_date = today
                try:
                    from backend.api.routes.stocks import _get_svc
                    svc = _get_svc()
                    logger.info(
                        f"[SwingAutopilot] 09:20 IST check — "
                        f"autopilot={'ON' if svc._autopilot_enabled else 'OFF'}, "
                        f"open_positions={len(svc._swing_positions)}, "
                        f"mode={svc._autopilot_mode}"
                    )
                    if svc._autopilot_enabled:
                        result = await svc.run_autopilot()
                        logger.info(
                            f"[SwingAutopilot] Complete: {result.get('executed_count', 0)} trades from "
                            f"{result.get('signals_found', 0)} signals. "
                            f"regime_warning={result.get('regime_warning', '')}"
                        )
                    else:
                        logger.info("[SwingAutopilot] Disabled — set enabled=True via /api/stocks/autopilot to activate.")
                except Exception as exc:
                    logger.error(f"Swing autopilot error: {exc}")

        except Exception as exc:
            logger.error(f"_swing_autopilot_loop unexpected error: {exc}")

        await asyncio.sleep(60)


# ---------------------------------------------------------------------------
# Swing position monitor — runs at 15:20 IST (market still open — can exit)
# ---------------------------------------------------------------------------

async def _swing_monitor_loop() -> None:
    """Check intraday SL/target for open swing positions and exit before close."""
    last_monitor_date: _date | None = None

    while True:
        try:
            now_ist = datetime.now(_IST)
            today   = now_ist.date()

            is_weekday     = today.weekday() < 5
            past_cutoff    = (now_ist.hour, now_ist.minute) >= (15, 20)
            not_done_today = last_monitor_date != today

            if is_weekday and past_cutoff and not_done_today:
                last_monitor_date = today
                logger.info("15:20 IST — swing position monitor triggered (market still open).")
                try:
                    from backend.api.routes.stocks import _get_svc
                    svc = _get_svc()
                    await svc.monitor_positions()
                except Exception as exc:
                    logger.error(f"Swing monitor error: {exc}")

        except Exception as exc:
            logger.error(f"_swing_monitor_loop unexpected error: {exc}")

        await asyncio.sleep(60)


# ---------------------------------------------------------------------------
# Real-time intraday SL / target monitor — checks every 10s, 09:15–15:30 IST
# ---------------------------------------------------------------------------

async def _swing_intraday_sl_loop() -> None:
    """
    Every 10 seconds during market hours, check open swing positions against
    their stop-loss and targets using live WebSocket ticks (with REST fallback).
    Creates one LiveFeed per trading day; tears it down after market close.
    """
    _live_feed = None
    _feed_attached = False
    last_reset_date = None

    while True:
        try:
            now_ist    = datetime.now(_IST)
            is_weekday = now_ist.weekday() < 5
            hm         = (now_ist.hour, now_ist.minute)
            in_hours   = (9, 15) <= hm <= (15, 30)

            if is_weekday and in_hours:
                from backend.api.routes.stocks import _get_svc
                from backend.dependencies import get_angel_client
                svc = _get_svc()

                # Reset daily "already triggered" guard at market open
                today = now_ist.date()
                if last_reset_date != today:
                    svc._sl_triggered.clear()
                    last_reset_date = today

                if svc._swing_positions:
                    angel_client = get_angel_client()

                    # Create & start live feed once per day
                    if _live_feed is None and angel_client is not None:
                        try:
                            from data.live_feed import LiveFeed
                            _live_feed    = LiveFeed(angel_client, symbols=[])
                            _live_feed.start()
                            _feed_attached = False
                            logger.info("[SLLoop] LiveFeed started — real-time SL monitoring active.")
                        except Exception as exc:
                            logger.warning(f"[SLLoop] LiveFeed creation failed: {exc}")

                    if _live_feed is not None:
                        if not _feed_attached:
                            await svc.attach_live_feed(_live_feed)
                            _feed_attached = True
                        else:
                            # Subscribe any positions opened since last cycle
                            await svc._subscribe_open_positions()

                        triggered = await svc.check_sl_realtime()
                        if triggered:
                            logger.info(f"[SLLoop] Intraday exits triggered: {triggered}")

            else:
                # Outside market hours — stop feed, free resources
                if _live_feed is not None:
                    try:
                        _live_feed.stop()
                        logger.info("[SLLoop] LiveFeed stopped (outside market hours).")
                    except Exception:
                        pass
                    _live_feed     = None
                    _feed_attached = False

        except Exception as exc:
            logger.error(f"_swing_intraday_sl_loop error: {exc}")

        await asyncio.sleep(10)


# ---------------------------------------------------------------------------
# Morning auto-retrain — runs at 08:30 IST every weekday
# ---------------------------------------------------------------------------

async def _morning_retrain_loop() -> None:
    """Background task: retrain ML models at 08:30 IST on trading days."""
    last_retrain_date: _date | None = None

    while True:
        try:
            now_ist = datetime.now(_IST)
            today   = now_ist.date()

            is_weekday     = today.weekday() < 5
            past_cutoff    = (now_ist.hour, now_ist.minute) >= (8, 30)
            not_done_today = last_retrain_date != today

            if is_weekday and past_cutoff and not_done_today:
                last_retrain_date = today
                logger.info("Morning 08:30 — scheduled model retrain starting.")

                try:
                    from backend.api.routes.system import _run_training
                    from backend.dependencies import get_angel_client
                    angel_client = get_angel_client()
                    if angel_client is None:
                        logger.warning("Morning retrain skipped — broker not connected.")
                    else:
                        asyncio.create_task(_run_training(angel_client, days=60))
                        logger.info("Morning retrain task launched (60 days, ~10–15 min).")
                except Exception as exc:
                    logger.error(f"Morning retrain error: {exc}")

        except Exception as exc:
            logger.error(f"_morning_retrain_loop unexpected error: {exc}")

        await asyncio.sleep(60)  # check every minute


# ---------------------------------------------------------------------------
# Morning broker reconnect — runs at 08:55 IST every weekday
# Ensures a fresh Angel One session 25 min before autopilot (09:20)
# and 20 min before market open (09:15).
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# NiftyBees ETF autopilot — every 60s during 09:15–15:30 IST on weekdays
# ---------------------------------------------------------------------------

async def _niftybees_monitor_loop() -> None:
    """Check Nifty dip and NiftyBees position gain every 60 seconds during market hours."""
    _last_heartbeat: _date | None = None
    _last_heartbeat_hm: tuple = (0, 0)

    while True:
        try:
            now_ist    = datetime.now(_IST)
            is_weekday = now_ist.weekday() < 5
            hm         = (now_ist.hour, now_ist.minute)
            in_hours   = (9, 15) <= hm <= (15, 30)

            if is_weekday and in_hours:
                from backend.services.niftybees_service import get_niftybees_service
                from backend.dependencies import get_angel_client
                svc    = get_niftybees_service(get_angel_client())
                result = await svc.run_monitor()
                action = result.get("action", "none")

                # Always log buy/sell actions + send Telegram
                if action in ("bought", "sold"):
                    logger.info(f"[NiftyBeesLoop] ACTION={action} | {result.get('details', '')}")
                    try:
                        from backend.services.telegram_service import send_trade_notification
                        pos = svc._position
                        if pos:
                            qty   = pos.get("total_qty", 0)
                            price = pos.get("current_price", pos.get("avg_entry_price", 0))
                            send_trade_notification(
                                action=action.upper(),
                                symbol="NIFTYBEES",
                                qty=qty,
                                price=price,
                                mode=svc._config.get("mode", "paper"),
                                reason=result.get("details", ""),
                            )
                    except Exception as tg_exc:
                        logger.warning(f"[NiftyBeesLoop] Telegram notify failed: {tg_exc}")
                # Heartbeat every 30 minutes so we can verify the loop is alive in Railway logs
                elif (now_ist.hour * 60 + now_ist.minute) % 30 == 0 and hm != _last_heartbeat_hm:
                    _last_heartbeat_hm = hm
                    pos = svc._position
                    logger.info(
                        f"[NiftyBeesLoop] heartbeat {hm[0]:02d}:{hm[1]:02d} IST — "
                        f"enabled={svc._config.get('enabled')}, "
                        f"action={action}, "
                        f"detail={result.get('details', '')}, "
                        f"position={'ACTIVE (' + str(pos.get('pnl_pct', 0)) + '%)' if pos and pos.get('active') else 'none'}"
                    )
            else:
                # Outside market hours — log once per day at first check
                today = now_ist.date()
                if _last_heartbeat != today and hm >= (15, 31):
                    _last_heartbeat = today
                    logger.info(f"[NiftyBeesLoop] Market closed for today. State preserved in DB.")

        except Exception as exc:
            logger.error(f"_niftybees_monitor_loop error: {exc}")

        await asyncio.sleep(60)


# ---------------------------------------------------------------------------
# Intraday Trending Alerts — runs at 09:30 IST every weekday
# ---------------------------------------------------------------------------

async def _intraday_alerts_loop() -> None:
    """Background task: send intraday trending stocks alert at 09:30 IST on trading days."""
    last_alert_date: _date | None = None

    while True:
        try:
            now_ist = datetime.now(_IST)
            today   = now_ist.date()

            is_weekday     = today.weekday() < 5
            past_cutoff    = (now_ist.hour, now_ist.minute) >= (9, 30)
            not_done_today = last_alert_date != today

            if is_weekday and past_cutoff and not_done_today:
                last_alert_date = today
                logger.info("[IntradayAlerts] 09:30 IST — Sending intraday trending stocks alert…")
                try:
                    from backend.services.growsect_service import get_growsect_service
                    from backend.services import growsect_intraday_alerts
                    from backend.api.routes.market_data import get_market_service

                    service = get_growsect_service()
                    market_svc = get_market_service()

                    # Fetch fresh data
                    await service.update_stock_prices(market_svc)

                    # Get all stocks
                    all_stocks = service.get_stock_heatmap()
                    if not all_stocks:
                        logger.warning("[IntradayAlerts] No stock data available")
                        await asyncio.sleep(60)
                        continue

                    # Get sector data
                    heatmap = service.get_heatmap_data()
                    sector_changes = {
                        sector_name: data.get("avg_change_pct", 0)
                        for sector_name, data in heatmap.get("sectors", {}).items()
                    }

                    # Filter: stock % > 0 AND sector % > 0, then rank by stock %
                    intraday_movers = []
                    for stock in all_stocks:
                        stock_pct = stock.get("change_pct", 0)
                        sector = stock.get("sector", "")
                        sector_pct = sector_changes.get(sector, 0)

                        if stock_pct > 0 and sector_pct > 0:
                            intraday_movers.append(
                                growsect_intraday_alerts.IntradayStock(
                                    symbol=stock.get("symbol"),
                                    sector=sector,
                                    price=stock.get("price"),
                                    change_pct=round(stock_pct, 2),
                                    sector_change_pct=round(sector_pct, 2),
                                    timestamp=now_ist,
                                )
                            )

                    # Sort by stock % gain descending
                    intraday_movers.sort(key=lambda x: x.change_pct, reverse=True)

                    # Send alert
                    if intraday_movers:
                        title = f"📈 <b>GROWSECT15 INTRADAY MOVERS — {now_ist.strftime('%d %b %H:%M')}</b>"
                        await growsect_intraday_alerts.broadcast_alert(title, intraday_movers)
                        logger.info(f"[IntradayAlerts] Alert sent: {len(intraday_movers)} stocks trending with sector support")
                    else:
                        logger.info("[IntradayAlerts] No stocks with sector tailwind today")

                except Exception as e:
                    logger.error(f"[IntradayAlerts] Failed to send alert: {e}")

        except Exception as exc:
            logger.error(f"_intraday_alerts_loop error: {exc}")

        await asyncio.sleep(60)


async def _eod_telegram_report_loop() -> None:
    """Send EOD Telegram report at 16:00 IST every weekday."""
    _last_eod_date: _date | None = None

    while True:
        try:
            now_ist = datetime.now(_IST)
            today   = now_ist.date()
            hm      = (now_ist.hour, now_ist.minute)
            is_weekday     = today.weekday() < 5
            past_cutoff    = hm >= (16, 0)
            not_done_today = _last_eod_date != today

            if is_weekday and past_cutoff and not_done_today:
                _last_eod_date = today
                logger.info("[EODReport] Composing EOD Telegram report…")
                try:
                    from backend.services.telegram_service import send_eod_report, is_configured
                    from backend.services.niftybees_service import get_niftybees_service
                    from backend.api.routes.stocks import _get_svc as _get_swing_svc
                    from backend.dependencies import get_angel_client
                    from backend.api.routes.system import get_account_balance

                    if not is_configured():
                        logger.info("[EODReport] Telegram not configured — skipping.")
                    else:
                        angel = get_angel_client()
                        nb    = get_niftybees_service(angel)
                        swing_svc = _get_swing_svc()
                        swings = list(swing_svc._swing_positions.values())

                        # Fetch balance
                        balance = {}
                        if angel:
                            try:
                                loop = asyncio.get_event_loop()
                                raw  = await loop.run_in_executor(None, angel.get_funds)
                                avail_eod = float(raw.get("availablecash", raw.get("available_cash", 0)) or 0)
                                net_eod   = float(raw.get("net", 0) or 0)
                                # Only include balance when Angel One returns real data
                                if avail_eod > 0 or net_eod > 0:
                                    balance = {"available_cash": avail_eod, "net": net_eod}
                                else:
                                    logger.warning("[EODReport] Balance API returned empty data — omitting from report.")
                            except Exception as bal_exc:
                                logger.warning(f"[EODReport] Balance fetch failed: {bal_exc}")

                        ok = send_eod_report(nb, swings, balance)
                        if ok:
                            logger.info("[EODReport] Telegram EOD report sent.")
                        else:
                            logger.error("[EODReport] Telegram EOD report FAILED — check bot token / chat ID.")
                except Exception as exc:
                    logger.error(f"[EODReport] Error: {exc}")
        except Exception as exc:
            logger.error(f"_eod_telegram_report_loop unexpected error: {exc}")
        await asyncio.sleep(60)


async def _balance_check_loop() -> None:
    """Check Angel One balance every 2h during market hours; alert via Telegram if low."""
    _last_alert_date: _date | None = None
    _low_balance_min = 0  # set by first successful check

    while True:
        try:
            now_ist    = datetime.now(_IST)
            is_weekday = now_ist.weekday() < 5
            hm         = (now_ist.hour, now_ist.minute)
            in_hours   = (9, 0) <= hm <= (15, 30)
            on_the_hour = now_ist.minute < 2  # fire once per hour near :00

            if is_weekday and in_hours and on_the_hour:
                try:
                    from backend.dependencies import get_angel_client
                    from backend.services.niftybees_service import get_niftybees_service
                    from backend.services.telegram_service import send_low_balance_alert, is_configured

                    angel = get_angel_client()
                    if angel is None:
                        await asyncio.sleep(60)
                        continue

                    loop = asyncio.get_event_loop()
                    raw  = await loop.run_in_executor(None, angel.get_funds)

                    # Angel One returns a string (or None) when the session is degraded
                    if not isinstance(raw, dict):
                        logger.warning(
                            f"[BalanceCheck] get_funds returned non-dict "
                            f"({type(raw).__name__}) — triggering session reconnect."
                        )
                        try:
                            loop2 = asyncio.get_event_loop()
                            await loop2.run_in_executor(None, angel.connect)
                            logger.info("[BalanceCheck] Angel One session restored.")
                        except Exception as _rc_exc:
                            logger.error(f"[BalanceCheck] Reconnect failed: {_rc_exc}")
                        await asyncio.sleep(60)
                        continue

                    avail = float(raw.get("availablecash", raw.get("available_cash", 0)) or 0)
                    net   = float(raw.get("net", 0) or 0)

                    # Skip if Angel One returned empty data (common after market hours)
                    if avail == 0 and net == 0:
                        logger.debug("[BalanceCheck] rmsLimit returned empty data — skipping alert.")
                        await asyncio.sleep(60)
                        continue

                    nb  = get_niftybees_service(angel)
                    req = nb._config.get("capital_amount", 10000.0)

                    today = now_ist.date()
                    if avail < req * 1.1 and _last_alert_date != today and is_configured():
                        _last_alert_date = today
                        ok = send_low_balance_alert(available=avail, required=req)
                        if ok:
                            logger.warning(f"[BalanceCheck] Low balance alert sent: ₹{avail:,.0f} < ₹{req:,.0f}")
                        else:
                            logger.error(f"[BalanceCheck] Low balance alert FAILED to send (Telegram error).")
                    else:
                        logger.info(f"[BalanceCheck] Balance OK: ₹{avail:,.0f}")
                except Exception as exc:
                    logger.error(f"[BalanceCheck] Error: {exc}")
        except Exception as exc:
            logger.error(f"_balance_check_loop unexpected error: {exc}")
        await asyncio.sleep(60)


async def _morning_news_loop() -> None:
    """Fetch market news at startup and again at 09:00 IST Mon–Fri."""
    _last_fetch_date: _date | None = None

    # Immediate startup fetch so news is ready the moment the server comes up
    await asyncio.sleep(5)  # let DB settle first
    try:
        from backend.api.routes.market_data import get_market_service, set_cached_news
        svc   = get_market_service()
        items = await svc.get_news_summary()
        if items:
            set_cached_news(items)
            logger.info(f"[NewsLoop] Startup fetch: {len(items)} headlines.")
    except Exception as exc:
        logger.warning(f"[NewsLoop] Startup fetch failed: {exc}")

    while True:
        try:
            now_ist = datetime.now(_IST)
            today   = now_ist.date()
            hm      = (now_ist.hour, now_ist.minute)
            is_weekday  = today.weekday() < 5
            past_cutoff = hm >= (9, 0)
            not_done_today = _last_fetch_date != today

            if is_weekday and past_cutoff and not_done_today:
                _last_fetch_date = today
                try:
                    from backend.api.routes.market_data import get_market_service, set_cached_news
                    svc   = get_market_service()
                    items = await svc.get_news_summary()
                    if items:
                        set_cached_news(items)
                        logger.info(f"[NewsLoop] Daily refresh: {len(items)} headlines for {today}.")
                    else:
                        logger.warning("[NewsLoop] No headlines returned from any RSS source.")
                except Exception as exc:
                    logger.error(f"[NewsLoop] error: {exc}")
        except Exception as exc:
            logger.error(f"_morning_news_loop unexpected error: {exc}")

        await asyncio.sleep(60)


async def _etf_holdings_monitor_loop() -> None:
    """
    Every 5 minutes during market hours (09:15–15:30 IST, weekdays):
    sync ETF holdings from broker, check 5% profit target, auto-sell if hit.
    """
    while True:
        try:
            now_ist    = datetime.now(_IST)
            is_weekday = now_ist.weekday() < 5
            hm         = (now_ist.hour, now_ist.minute)
            in_hours   = (9, 15) <= hm <= (15, 30)

            if is_weekday and in_hours and now_ist.minute % 5 == 0:
                try:
                    from backend.services.etf_holdings_service import get_etf_holdings_service
                    from backend.dependencies import get_angel_client
                    svc    = get_etf_holdings_service(get_angel_client())
                    result = await svc.sync_and_check()
                    sells  = result.get("sells", [])
                    if sells:
                        logger.info(f"[ETFHoldings] Auto-sold (5% target): {sells}")
                    else:
                        logger.debug(
                            f"[ETFHoldings] {len(result.get('holdings', []))} ETF(s) checked — no target hits."
                        )
                except Exception as exc:
                    logger.error(f"[ETFHoldings] monitor error: {exc}")
        except Exception as exc:
            logger.error(f"_etf_holdings_monitor_loop unexpected error: {exc}")

        await asyncio.sleep(60)


async def _session_refresh_loop() -> None:
    """
    Scheduled reconnects: midnight (clears overnight token expiry), then
    08:55/09:05 IST (before market open) and 12:30 IST (midday safety).
    Reconnects run every calendar day so the nightly token expiry is always
    cleaned up before the next morning.
    """
    # (hour, minute, weekday_only)
    _reconnect_slots = [
        (0,  1, False),   # just after midnight — reset overnight expiry
        (8, 55, True),    # pre-market
        (9,  5, True),    # 10 min after open
        (12, 30, True),   # midday safety
    ]
    _last_dates: dict = {}

    while True:
        try:
            now_ist = datetime.now(_IST)
            today   = now_ist.date()
            hm      = (now_ist.hour, now_ist.minute)

            for slot in _reconnect_slots:
                sh, sm, weekday_only = slot
                key = (sh, sm)
                already_done = _last_dates.get(key) == today
                if hm >= (sh, sm) and not already_done:
                    if weekday_only and now_ist.weekday() >= 5:
                        _last_dates[key] = today
                        continue
                    _last_dates[key] = today
                    try:
                        from backend.dependencies import get_angel_client
                        angel_client = get_angel_client()
                        if angel_client is None:
                            logger.warning(
                                f"[SessionRefresh] {sh:02d}:{sm:02d} skipped — no broker client."
                            )
                        else:
                            loop = asyncio.get_event_loop()
                            await loop.run_in_executor(None, angel_client.connect)
                            logger.info(
                                f"[SessionRefresh] {sh:02d}:{sm:02d} IST — Angel One reconnected."
                            )
                    except Exception as exc:
                        logger.error(f"[SessionRefresh] {sh:02d}:{sm:02d} error: {exc}")

        except Exception as exc:
            logger.error(f"_session_refresh_loop unexpected error: {exc}")

        await asyncio.sleep(60)


async def _session_health_watchdog_loop() -> None:
    """
    Continuously monitor Angel One session health.  Every 5 minutes, call
    get_funds() — if it returns a non-dict (the telltale sign of a degraded
    or expired session), immediately trigger a full re-login so every API
    call in the next cycle uses a live token.

    This is the permanent fix for the 'every morning broken session' problem:
    rather than waiting for the scheduled reconnect at 08:55 IST, this loop
    detects the broken session within 5 minutes and self-heals.
    """
    _last_reconnect: float = 0.0   # epoch seconds, throttle reconnects to 5 min

    while True:
        await asyncio.sleep(300)   # check every 5 minutes
        try:
            from backend.dependencies import get_angel_client
            angel_client = get_angel_client()
            if angel_client is None:
                continue

            loop = asyncio.get_event_loop()
            try:
                raw = await loop.run_in_executor(None, angel_client.get_funds)
            except Exception:
                raw = None

            session_ok = isinstance(raw, dict) and (
                raw.get("net") not in (None, "", "0", 0)
                or raw.get("availablecash") not in (None, "", "0", 0)
            )

            if not session_ok:
                now = time.time()
                if now - _last_reconnect < 300:
                    # Already reconnected in the last 5 min — don't spam
                    continue
                _last_reconnect = now
                logger.warning(
                    "[SessionWatchdog] Degraded session detected "
                    f"(get_funds returned {type(raw).__name__}: {str(raw)[:60]}). "
                    "Reconnecting…"
                )
                try:
                    await loop.run_in_executor(None, angel_client.connect)
                    logger.info("[SessionWatchdog] Angel One session restored.")
                except Exception as exc:
                    logger.error(f"[SessionWatchdog] Reconnect failed: {exc}")
            else:
                logger.debug(
                    f"[SessionWatchdog] Session healthy — "
                    f"net=₹{raw.get('net', 0)}, "
                    f"avail=₹{raw.get('availablecash', 0)}"
                )
        except Exception as exc:
            logger.error(f"_session_health_watchdog_loop unexpected error: {exc}")
_PUBLIC_API_PATHS = {
    "/api/auth/login",
    "/api/system/status",  # Railway health check
    "/api/system/telegram/test",  # safe to expose — only sends to the configured chat ID
    "/api/version",  # Deployment verification — public for troubleshooting
    "/health",
}

class _AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Pass through: static files, frontend routes, public API paths, WS
        if (
            not path.startswith("/api")
            or path in _PUBLIC_API_PATHS
            or path.startswith("/ws/")
        ):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)

        token = auth_header.split(" ", 1)[1]
        try:
            verify_token(token)
        except Exception:
            return JSONResponse({"detail": "Token invalid or expired"}, status_code=401)

        return await call_next(request)


async def _startup_init_services() -> None:
    """
    Eagerly create service singletons on startup so DB state is loaded BEFORE
    the background loops fire. Retries up to 3 times (2s gaps) in case the
    Railway PostgreSQL container is still warming up.
    """
    from backend.dependencies import get_angel_client
    angel = get_angel_client()

    # --- Swing / equity service ---
    for attempt in range(3):
        try:
            from backend.api.routes.stocks import _get_svc
            svc = _get_svc()
            logger.info(
                f"[Startup] SwingService ready: {len(svc._swing_positions)} open position(s), "
                f"autopilot={'ON' if svc._autopilot_enabled else 'OFF'} "
                f"(attempt {attempt+1})"
            )
            break
        except Exception as exc:
            logger.warning(f"[Startup] SwingService init attempt {attempt+1}/3 failed: {exc}")
            if attempt < 2:
                await asyncio.sleep(3)

    # --- NiftyBees service ---
    for attempt in range(3):
        try:
            from backend.services.niftybees_service import get_niftybees_service
            nb  = get_niftybees_service(angel)
            pos = nb._position
            logger.info(
                f"[Startup] NiftyBeesService ready: "
                f"enabled={nb._config.get('enabled')}, "
                f"position={'ACTIVE (' + str(pos.get('total_qty', 0)) + ' units, avg ₹' + str(pos.get('avg_entry_price', 0)) + ')' if pos and pos.get('active') else 'none'} "
                f"(attempt {attempt+1})"
            )
            break
        except Exception as exc:
            logger.warning(f"[Startup] NiftyBeesService init attempt {attempt+1}/3 failed: {exc}")
            if attempt < 2:
                await asyncio.sleep(3)


async def _sr_refresh_loop() -> None:
    """
    Daily Support/Resistance level refresh at 9:00 AM IST.
    Recalculates S/R levels for tracked symbols using last 3 days OHLC.
    """
    last_refresh_date: _date | None = None

    while True:
        try:
            now_ist = datetime.now(_IST)
            today   = now_ist.date()

            is_weekday     = today.weekday() < 5
            past_cutoff    = (now_ist.hour, now_ist.minute) >= (9, 0)
            not_done_today = last_refresh_date != today

            if is_weekday and past_cutoff and not_done_today:
                last_refresh_date = today
                logger.info("[SRRefresh] Daily 9:00 AM refresh starting…")

                try:
                    from backend.dependencies import get_sr_service
                    sr_service = get_sr_service()
                    # Refresh Nifty by default; add more symbols as needed
                    result = await sr_service.refresh_daily(["NIFTY"])
                    logger.info(
                        f"[SRRefresh] Complete — {result['refreshed']} symbol(s) updated "
                        f"at {result['timestamp']}"
                    )
                except Exception as exc:
                    logger.error(f"[SRRefresh] Daily refresh error: {exc}")

        except Exception as exc:
            logger.error(f"_sr_refresh_loop unexpected error: {exc}")

        await asyncio.sleep(60)  # check every minute


async def _startup_telegram_ping() -> None:
    """Send a Telegram message on every startup so you know the bot is working."""
    await asyncio.sleep(10)  # let all services initialise first
    try:
        from backend.services.telegram_service import send, is_configured
        if not is_configured():
            logger.info("[StartupPing] Telegram not configured — skipping ping.")
            return
        from datetime import datetime, timezone, timedelta
        _IST = timezone(timedelta(hours=5, minutes=30))
        now  = datetime.now(_IST).strftime("%d %b %Y %H:%M IST")
        ok = send(f"✅ <b>JARVIS is online</b>\nStarted at {now}\n\nTelegram notifications are working.")
        if ok:
            logger.info("[StartupPing] Telegram startup ping sent.")
        else:
            logger.error("[StartupPing] Telegram startup ping FAILED — check bot token / chat ID in Railway vars.")
    except Exception as exc:
        logger.error(f"[StartupPing] Unexpected error: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting FastAPI backend...")

    # Give Railway DB a moment to be ready on cold-start, then init singletons
    await asyncio.sleep(2)
    await _startup_init_services()

    from backend.api.routes.positions import get_position_service
    from backend.api.routes.market_data import get_market_service
    from backend.api.routes.strategies import get_strategy_service
    # DISABLED: periodic updates break WebSocket connection for Hermes
    # asyncio.create_task(
    #     ws_manager.start_periodic_updates(get_position_service(), get_market_service())
    # )
    asyncio.create_task(_session_refresh_loop())
    asyncio.create_task(_session_health_watchdog_loop())
    # DISABLED: All competing strategies (free API quota for Weekly 5% Income only)
    # asyncio.create_task(_swing_autopilot_loop())  # DISABLED
    # asyncio.create_task(_swing_monitor_loop())  # DISABLED
    # asyncio.create_task(_swing_intraday_sl_loop())  # DISABLED
    # asyncio.create_task(_niftybees_monitor_loop())  # DISABLED
    # asyncio.create_task(_etf_holdings_monitor_loop())  # DISABLED
    # asyncio.create_task(_ml_intraday_loop())  # DISABLED
    # asyncio.create_task(_nifty_ml_loop())  # DISABLED
    # asyncio.create_task(_nifty_options_trader_loop())  # DISABLED
    # asyncio.create_task(_eod_squareoff_loop())  # DISABLED
    # asyncio.create_task(_morning_retrain_loop())  # DISABLED
    # asyncio.create_task(_sr_refresh_loop())  # DISABLED
    asyncio.create_task(_paper_trading_loop())  # ONLY: Weekly 5% Income paper trading (continuous)
    asyncio.create_task(_intraday_alerts_loop())  # Daily 09:30: GROWSECT15 intraday movers
    asyncio.create_task(_eod_telegram_report_loop())  # Keep: Daily reporting
    asyncio.create_task(_balance_check_loop())  # Keep: Account health
    asyncio.create_task(_morning_news_loop())  # Keep: Market news
    asyncio.create_task(_startup_telegram_ping())
    # Restore strategies that were running before any restart/redeploy
    await get_strategy_service().restore_running_strategies()
    yield
    print("Shutting down FastAPI backend...")
    cleanup_dependencies()


app = FastAPI(
    title="Algotrading API",
    description="JARVIS-style algorithmic trading platform API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,   # disable /docs in production
    redoc_url=None,
)

# CORS must be added before AuthMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(_AuthMiddleware)

# Include API routers
app.include_router(auth_routes.router)   # /api/auth/* — public login endpoint
app.include_router(system.router)
app.include_router(strategies.router)
app.include_router(positions.router)
app.include_router(trades.router)
app.include_router(market_data.router)
app.include_router(risk.router)
app.include_router(stocks.router)
app.include_router(niftybees.router)
app.include_router(sector_analysis.router)
app.include_router(etf_holdings.router)
app.include_router(jarvis_voice.router)
app.include_router(portfolio_routes.router)
app.include_router(conviction_routes.router)
app.include_router(sr_routes.router)
# app.include_router(hermes_routes.router)  # ARCHIVED: Hermes AI agent
# app.include_router(athena_routes.router)  # ARCHIVED: Athena Options agent
app.include_router(ml_intraday_routes.router)
app.include_router(weekly_income_routes.router)
app.include_router(growsect_routes.router)
app.include_router(version_routes.router)
# app.include_router(claude_usage.router)  # REMOVED: Claude API usage tracking
# app.include_router(intraday_signals.router)  # TEMPORARILY DISABLED - debugging startup crash


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.websocket("/ws/hermes")
async def hermes_websocket_endpoint(websocket: WebSocket):
    """Dedicated WebSocket endpoint for Hermes activity updates"""
    await websocket.accept()
    ws_manager.active_connections.append(websocket)
    print(f"[Hermes WS] Client connected. Total: {len(ws_manager.active_connections)}")

    try:
        # Send initial connection confirmation
        await websocket.send_json({
            "type": "connected",
            "message": "Connected to Hermes activity feed",
            "timestamp": datetime.now(_IST).isoformat()
        })

        # Keep connection alive
        while True:
            # Wait for client messages (ping/pong) to keep connection alive
            try:
                await websocket.receive_text()
            except:
                break
    except Exception as e:
        print(f"[Hermes WS] Connection error: {e}")
    finally:
        if websocket in ws_manager.active_connections:
            ws_manager.active_connections.remove(websocket)
        print(f"[Hermes WS] Client disconnected. Total: {len(ws_manager.active_connections)}")


@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket, token: str = ""):
    # Validate token passed as query param: /ws/live?token=<jwt>
    try:
        verify_token(token)
    except Exception:
        await websocket.accept()
        await websocket.close(code=4001)  # 4001 = unauthorised
        return
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_json({"type": "ack", "data": data})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


# Serve React frontend — mount AFTER all API routes
_frontend_build = Path(__file__).parent.parent / "frontend" / "build"
if _frontend_build.exists():
    app.mount("/static", StaticFiles(directory=str(_frontend_build / "static")), name="static")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        return FileResponse(
            str(_frontend_build / "index.html"),
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
else:
    @app.get("/")
    async def root():
        return {"message": "Algotrading API v1.0.0 — frontend not built yet"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=int(__import__("os").getenv("PORT", 8000)), log_level="info")


# ---------------------------------------------------------------------------
# Hermes AI Agent - Intraday Trading Loop
# ---------------------------------------------------------------------------

async def _hermes_intraday_loop() -> None:
    """Background task: Hermes AI agent intraday trading every 30s"""
    from backend.services.hermes_intraday_service import HermesIntradayService
    from backend.dependencies import get_angel_client

    await asyncio.sleep(15)  # Wait for startup

    angel = get_angel_client()
    hermes_svc = HermesIntradayService(config.trading_config, angel)

    logger.info("[HermesLoop] Starting Hermes intraday trading loop")

    while True:
        try:
            if hermes_svc.enabled and hermes_svc.is_trading_hours():
                # Broadcast analyzing status
                await ws_manager.broadcast({
                    "type": "hermes_activity",
                    "action": "Market Analysis",
                    "details": f"Analyzing {hermes_svc.instrument} for trading opportunities",
                    "status": "analyzing"
                })

                result = await hermes_svc.run_analysis_cycle()
                logger.debug(f"[HermesLoop] Cycle: {result.get('status')}")

                # Broadcast result
                if result.get("status") == "success" and result.get("decision"):
                    decision = result["decision"]
                    execution = result.get("execution", {})

                    if decision["action"] in ["BUY", "CLOSE_POSITION"]:
                        await ws_manager.broadcast({
                            "type": "hermes_activity",
                            "action": f"{decision['action']} Signal",
                            "details": decision.get("reasoning", "No reason provided"),
                            "status": "executing" if execution.get("action") != "ignored" else "waiting",
                            "confidence": decision.get("confidence", 0),
                            "decision": decision
                        })
                    elif decision.get("confidence", 0) < hermes_svc.min_confidence:
                        await ws_manager.broadcast({
                            "type": "hermes_activity",
                            "action": "Low Confidence",
                            "details": f"Setup confidence {decision.get('confidence', 0):.0%} below threshold {hermes_svc.min_confidence:.0%}",
                            "status": "waiting",
                            "confidence": decision.get("confidence", 0)
                        })
                    elif result.get("position"):
                        await ws_manager.broadcast({
                            "type": "hermes_activity",
                            "action": "Position Monitoring",
                            "details": f"Monitoring {hermes_svc.instrument} position",
                            "status": "monitoring"
                        })
                    else:
                        await ws_manager.broadcast({
                            "type": "hermes_activity",
                            "action": decision["action"],
                            "details": decision.get("reasoning", "Waiting for setup"),
                            "status": "waiting",
                            "confidence": decision.get("confidence", 0)
                        })

            elif hermes_svc.enabled and hermes_svc.is_market_closed():
                await hermes_svc.force_exit_all()
                logger.info("[HermesLoop] Market closed - positions exited")
                await ws_manager.broadcast({
                    "type": "hermes_activity",
                    "action": "Market Closed",
                    "details": "Force-exiting all positions - market closed",
                    "status": "executing"
                })

            interval = config.trading_config.get("hermes", {}).get("check_interval_seconds", 30)
            await asyncio.sleep(interval)

        except Exception as e:
            logger.error(f"[HermesLoop] Error: {e}")
            await ws_manager.broadcast({
                "type": "hermes_activity",
                "action": "Error",
                "details": str(e),
                "status": "error"
            })
            await asyncio.sleep(60)


async def _nifty_ml_loop() -> None:
    """Background task: NIFTY ML auto-trader every 5 minutes during market hours"""
    from backend.ml.nifty_trader import NiftyMLTrader

    await asyncio.sleep(25)  # Wait for startup + angel connection

    trader = NiftyMLTrader.get_instance()
    logger.info("[NiftyMLLoop] Starting NIFTY ML trader loop (5-min cycle)")

    while True:
        try:
            now = datetime.now(_IST)
            in_hours = now.weekday() < 5 and "09:30" <= now.strftime("%H:%M") <= "15:30"

            if trader.enabled and trader.booster is not None and in_hours:
                result = await trader.run_cycle()
                logger.debug(f"[NiftyMLLoop] Cycle: {result.get('status')} proba={result.get('proba')}")

                await ws_manager.broadcast({
                    "type": "nifty_ml_update",
                    "status": result.get("status"),
                    "proba": result.get("proba"),
                    "position": trader.position,
                    "last_update": trader.last_update,
                })
                await asyncio.sleep(300)  # 5 minutes
            elif trader.enabled and trader.position and now.strftime("%H:%M") > "15:30":
                await trader.force_exit()
                await asyncio.sleep(300)
            else:
                await asyncio.sleep(60)

        except Exception as e:
            logger.error(f"[NiftyMLLoop] Error: {e}")
            await asyncio.sleep(300)


async def _nifty_options_trader_loop() -> None:
    """Background task: NIFTY options auto-trader every 30s during market hours"""
    from backend.ml.nifty_options_trader import NiftyOptionsTrader

    await asyncio.sleep(30)  # Wait for startup + angel connection

    trader = NiftyOptionsTrader.get_instance()
    logger.info("[NiftyOptionsLoop] Starting NIFTY options trader loop (30-sec cycle)")

    while True:
        try:
            now = datetime.now(_IST)
            is_weekday = now.weekday() < 5
            hm_str = now.strftime("%H:%M")
            in_hours = "09:15" <= hm_str <= "15:30"

            if trader.enabled and is_weekday and in_hours:
                result = await trader.run_cycle()
                if result.get("status") != "waiting":
                    logger.info(
                        f"[NiftyOptionsLoop] Cycle complete: status={result.get('status')} | "
                        f"action={result.get('action')}"
                    )
                    # Broadcast update to connected clients
                    try:
                        await ws_manager.broadcast({
                            "type": "nifty_options_update",
                            "status": result.get("status"),
                            "action": result.get("action"),
                            "last_update": now.isoformat(),
                        })
                    except Exception:
                        pass
                await asyncio.sleep(30)  # 30 seconds
            else:
                await asyncio.sleep(60)  # Check again in 1 min when closed/disabled

        except Exception as e:
            logger.error(f"[NiftyOptionsLoop] Error: {e}")
            await asyncio.sleep(60)


async def _paper_trading_loop() -> None:
    """Background task: Weekly 5% Income paper trading (9:15 AM - 3:30 PM IST non-stop)"""
    from backend.ml.weekly_income_trader import get_trader
    from backend.api.routes.market_data import get_market_service

    await asyncio.sleep(30)  # Wait for startup

    trader = get_trader()
    engine = get_paper_engine()
    logger.info("[PaperTrading] 🟢 Continuous paper trading enabled (9:15 AM - 3:30 PM IST, weekdays only)")
    logger.info("[PaperTrading] Account: ₹100,000 | Strategy: Weekly 5% Income | Target: 65%+ win rate")

    scan_counter = 0
    last_hour_logged = None

    while True:
        try:
            now = datetime.now(_IST)
            is_weekday = now.weekday() < 5  # Mon-Fri
            hm_str = now.strftime("%H:%M")
            in_hours = "09:15" <= hm_str <= "15:30"  # 9:15 AM - 3:30 PM IST

            # Log market open/close status once per hour
            current_hour = now.hour
            if current_hour != last_hour_logged:
                last_hour_logged = current_hour
                if is_weekday:
                    if in_hours:
                        if "11:30" <= hm_str <= "14:59":
                            logger.info(f"[PaperTrading] 🔸 LUNCH BREAK ({hm_str}) - Market closed, monitoring for reopening")
                        else:
                            logger.info(f"[PaperTrading] 🟢 ACTIVE ({hm_str} IST) - Scanning for opportunities")
                    else:
                        logger.info(f"[PaperTrading] 🔴 CLOSED ({hm_str} IST) - Outside trading hours")
                else:
                    logger.info(f"[PaperTrading] 🔴 CLOSED (Weekend) - No trading on weekends")

            if is_weekday and in_hours:
                # Scan every 5 minutes for new opportunities
                scan_counter += 1

                if scan_counter >= 5:  # Scan every 5 mins
                    scan_counter = 0
                    try:
                        market_svc = get_market_service()
                        current_data = await market_svc.get_current_market_data()
                        nifty_price = float(current_data.ltp)

                        # Fetch technicals
                        technicals = await market_svc.get_nifty_technicals()

                        # Fetch cycle
                        from backend.services.sector_analysis_service import run_sector_analysis
                        cycle = run_sector_analysis().get("cycle", {})

                        market_data = {
                            "ltp": nifty_price,
                            "rsi": technicals.get("rsi14", 50),
                            "macd_histogram": technicals.get("macd_hist", 0),
                            "volume_ratio": technicals.get("vol_ratio", 1.0),
                            "atr": technicals.get("atr14", 100),
                            "sma50": technicals.get("sma50", nifty_price),
                            "support": technicals.get("support_level", nifty_price - 200),
                            "resistance": technicals.get("resistance_level", nifty_price + 200),
                            "iv_percentile": technicals.get("iv_percentile", 50),
                        }

                        # Update prices in engine
                        await engine.update_prices(nifty_price)

                        # Update GROWSECT 15 heatmap data (every 60 seconds during market hours)
                        try:
                            from backend.services.growsect_service import get_growsect_service
                            growsect_svc = get_growsect_service()
                            await growsect_svc.update_stock_prices(market_svc)
                        except Exception as e:
                            logger.debug(f"[GROWSECT] Heatmap update error: {e}")

                        # Check for exits
                        closed = await engine.check_exits(nifty_price)
                        if closed:
                            logger.info(f"[PaperTrading] Closed {len(closed)} trades at ₹{nifty_price:.2f}")

                        # Scan for new opportunities
                        setups = await trader.scan_for_opportunities(market_data, cycle)
                        if setups:
                            logger.info(f"[PaperTrading] ✓ Found {len(setups)} high-confidence setup(s) | Executing...")
                        else:
                            logger.debug(f"[PaperTrading] Scan complete: 0 setups found (waiting for setup conditions)")

                        # Auto-execute if capital available
                        for setup in setups:
                            # Check if we have enough capital
                            if engine.account.equity >= setup.capital_required * 1.2:  # 20% buffer
                                trade = await engine.execute_trade(setup)
                                logger.info(
                                    f"[PaperTrading] ✅ EXECUTED: {setup.strategy.upper()} @ ₹{setup.entry_price:.2f} | "
                                    f"Confidence: {setup.confidence_score:.0f}% | Max P&L: ₹{setup.max_profit:,.0f} | "
                                    f"Risk: ₹{setup.max_loss:,.0f}"
                                )

                                # Try to send Telegram notification
                                try:
                                    from backend.services.telegram_service import send, is_configured
                                    if is_configured():
                                        await asyncio.to_thread(
                                            send,
                                            f"📈 **Paper Trade Executed**\n\n"
                                            f"Strategy: {setup.strategy.upper()}\n"
                                            f"Entry: ₹{setup.entry_price:.2f}\n"
                                            f"Confidence: {setup.confidence_score:.0f}%\n"
                                            f"Max Profit: ₹{setup.max_profit:,.0f}\n"
                                            f"Max Loss: ₹{setup.max_loss:,.0f}\n"
                                            f"Account Equity: ₹{engine.account.equity:,.0f}"
                                        )
                                except Exception as e:
                                    logger.debug(f"[PaperTrading] Telegram notification failed: {e}")

                                # Broadcast to connected clients
                                try:
                                    await ws_manager.broadcast({
                                        "type": "paper_trading_update",
                                        "event": "trade_executed",
                                        "trade_id": trade.trade_id,
                                        "strategy": setup.strategy,
                                        "confidence": setup.confidence_score,
                                        "nifty_price": nifty_price,
                                        "account_equity": engine.account.equity,
                                    })
                                except Exception:
                                    pass

                        # Log account status every scan cycle (every 5 minutes)
                        status = await engine.get_status()
                        logger.info(
                            f"[PaperTrading] 📊 {hm_str} IST | Equity: ₹{status['equity']:,.0f} | "
                            f"P&L: ₹{status['total_pnl']:,.0f} ({status['return_pct']:.2f}%) | "
                            f"Trades: {status['total_trades']} | Win Rate: {status['win_rate']:.0f}% | "
                            f"Active: {status['active_trades']}"
                        )

                    except Exception as e:
                        logger.error(f"[PaperTrading] Scan error: {e}")

                await asyncio.sleep(60)  # Check every minute
            else:
                await asyncio.sleep(120)  # Market closed, check less frequently

        except Exception as e:
            logger.error(f"[PaperTrading] Loop error: {e}")
            await asyncio.sleep(120)


async def _ml_intraday_loop() -> None:
    """Background task: ML scoring engine every 5 minutes during market hours"""
    from backend.ml.scoring_service import MLScoringService

    await asyncio.sleep(30)  # Wait for startup + angel connection

    svc = MLScoringService.get_instance()
    logger.info("[MLLoop] Starting ML intraday scoring loop (5-min cycle)")

    while True:
        try:
            now = datetime.now(_IST)
            in_hours = now.weekday() < 5 and "09:15" <= now.strftime("%H:%M") <= "15:30"

            if svc.model is not None and in_hours:
                await svc.update_live_candles()
                result = await svc.run_cycle()

                if result.get("status") == "ok" and svc.active_signals:
                    await ws_manager.broadcast({
                        "type": "ml_intraday_signals",
                        "signals": svc.active_signals,
                        "last_update": svc.last_update,
                    })
                    # Telegram alert for high-confidence signals
                    try:
                        from backend.services import telegram_service
                        for sig in svc.active_signals:
                            telegram_service.send(
                                f"🎯 <b>ML SIGNAL: BUY {sig['symbol']}</b>\n"
                                f"Score: {sig['score']} | P: {sig['probability']}%\n"
                                f"Entry ₹{sig['entry']} | SL ₹{sig['stop_loss']} | "
                                f"Target ₹{sig['target']} | R:R 1:{sig['reward_risk']}\n"
                                f"Mode: PAPER"
                            )
                    except Exception:
                        pass

                await asyncio.sleep(300)  # 5 minutes
            else:
                await asyncio.sleep(120)  # Check again in 2 min when closed/no model

        except Exception as e:
            logger.error(f"[MLLoop] Error: {e}")
            await asyncio.sleep(300)
