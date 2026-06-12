"""
JARVIS Voice API
================
POST /api/jarvis/speak  — generate AI briefing + TTS audio
GET  /api/jarvis/topics — list available briefing topics
GET  /api/jarvis/config — check which services are configured
"""
from __future__ import annotations

import asyncio
import base64
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from loguru import logger

from backend.auth import verify_token
from backend.services.jarvis_voice_service import get_jarvis_voice_service

router = APIRouter(prefix="/api/jarvis", tags=["jarvis"])

TOPICS = [
    {"id": "market_summary", "label": "Market Summary",  "icon": "📊", "desc": "Nifty status, trend & technicals"},
    {"id": "my_positions",   "label": "My Positions",    "icon": "💼", "desc": "NiftyBees & swing trade P&L"},
    {"id": "news_brief",     "label": "News Brief",      "icon": "📰", "desc": "Top headlines summarised by AI"},
    {"id": "global_cues",    "label": "Global Cues",     "icon": "🌐", "desc": "US, Asia, commodities & forex"},
    {"id": "nifty_trend",    "label": "Nifty Trend",     "icon": "📈", "desc": "Technical analysis deep-dive"},
    {"id": "full_briefing",  "label": "Full Briefing",   "icon": "🎯", "desc": "Complete 90-second overview"},
]


class SpeakRequest(BaseModel):
    topic: str = "market_summary"


@router.get("/topics")
async def list_topics(_: str = Depends(verify_token)):
    return TOPICS


@router.get("/config")
async def get_config(_: str = Depends(verify_token)):
    import os
    return {
        "claude_configured":     bool(os.environ.get("ANTHROPIC_API_KEY")),
        "elevenlabs_configured": bool(os.environ.get("ELEVENLABS_API_KEY")),
        "voice_id":              os.environ.get("ELEVENLABS_VOICE_ID", "onwK4e9ZLuTAKqWW03F9"),
    }


@router.post("/speak")
async def jarvis_speak(
    body: SpeakRequest,
    _: str = Depends(verify_token),
):
    try:
        context = await _build_context(body.topic)
        svc     = get_jarvis_voice_service()
        audio_bytes, script = await svc.generate_brief(body.topic, context)

        return {
            "script": script,
            "audio":  base64.b64encode(audio_bytes).decode() if audio_bytes else None,
        }
    except Exception as exc:
        logger.error(f"[JARVIS Speak] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Context builder ───────────────────────────────────────────────────────

async def _build_context(topic: str) -> dict:
    ctx: dict = {}

    async def _safe(coro):
        try:
            return await coro
        except Exception:
            return None

    # Always: market LTP + change
    try:
        from backend.dependencies import get_market_service
        mkt = get_market_service()
        if mkt:
            md = await _safe(mkt.get_current_market_data())
            if md:
                ctx["ltp"]        = md.ltp
                ctx["change"]     = md.change
                ctx["change_pct"] = md.change_percentage
                ctx["prev_close"] = mkt._cached_prev_close
    except Exception:
        pass

    # Technicals
    if topic in ("market_summary", "nifty_trend", "full_briefing"):
        try:
            from backend.dependencies import get_market_service
            mkt = get_market_service()
            if mkt:
                tech = await _safe(mkt.get_nifty_technicals())
                if tech:
                    ctx.update({k: tech[k] for k in ("ema9", "ema21", "sma50", "trend", "signal") if k in tech})
                    ctx["rsi"] = tech.get("rsi14")
        except Exception:
            pass

    # Regime
    if topic in ("market_summary", "full_briefing"):
        try:
            from backend.dependencies import get_market_service
            mkt = get_market_service()
            if mkt:
                r = await _safe(mkt.get_market_regime())
                if r:
                    ctx["regime"]      = r.current_regime
                    ctx["regime_conf"] = r.confidence
        except Exception:
            pass

    # Global cues
    if topic in ("global_cues", "market_summary", "full_briefing"):
        try:
            from backend.dependencies import get_market_service
            mkt = get_market_service()
            if mkt:
                cues = await _safe(mkt.get_global_cues())
                if cues:
                    ctx["global_cues"] = cues
        except Exception:
            pass

    # News
    if topic in ("news_brief", "full_briefing"):
        try:
            from backend.dependencies import get_market_service
            mkt = get_market_service()
            if mkt:
                news = await _safe(mkt.get_news_summary(max_items=7))
                if news:
                    ctx["news"] = news
        except Exception:
            pass

    # NiftyBees position
    if topic in ("my_positions", "full_briefing"):
        try:
            from backend.services.niftybees_service import get_niftybees_service
            nb = get_niftybees_service()
            status = nb.get_status()
            pos    = (status or {}).get("position") or {}
            if pos.get("active"):
                ctx["niftybees"] = {
                    "total_qty":       pos.get("total_qty", 0),
                    "avg_entry_price": pos.get("avg_entry_price", 0),
                    "current_price":   pos.get("current_price", 0),
                    "pnl_pct":         pos.get("pnl_pct", 0),
                    "target":          (nb.get_status() or {}).get("config", {}).get("target_gain_pct", 5),
                }
        except Exception:
            pass

    # Swing positions
    if topic in ("my_positions", "full_briefing"):
        try:
            from backend.api.routes.stocks import _get_svc
            swing = _get_svc()
            if swing:
                all_pos = swing.get_open_positions_list()
                ctx["swing_positions"] = [
                    {"symbol": p.symbol, "pnl_pct": getattr(p, "pnl_pct", 0), "status": p.status}
                    for p in all_pos
                ]
        except Exception:
            pass

    return ctx
