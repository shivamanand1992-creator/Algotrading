"""
VAAYU Voice API
===============
POST /api/jarvis/speak  — generate AI briefing + TTS audio
POST /api/jarvis/chat   — conversational follow-up question
GET  /api/jarvis/topics — list available briefing topics
GET  /api/jarvis/config — check which services are configured
"""
from __future__ import annotations

import asyncio
import base64
import time
from typing import List, Optional

# Module-level cache for broker holdings — refreshed every 5 minutes
_holdings_cache: list = []
_holdings_cache_time: float = 0.0
_HOLDINGS_TTL = 300.0

import os
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from loguru import logger

from backend.auth import get_current_user
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


class ConversationTurn(BaseModel):
    role: str     # "user" or "assistant"
    content: str

class ChatRequest(BaseModel):
    message: str
    context_topic: str = "full_briefing"
    history: List[ConversationTurn] = []


@router.post("/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
    _: str = Depends(get_current_user),
):
    """Transcribe voice recording via OpenAI Whisper — used on iOS where SpeechRecognition is unavailable."""
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY not configured")

    audio_bytes = await audio.read()
    content_type = audio.content_type or "audio/webm"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            files={"file": ("recording.webm", audio_bytes, content_type)},
            data={"model": "whisper-1", "language": "en"},
        )

    if resp.status_code != 200:
        logger.warning(f"Whisper API error {resp.status_code}: {resp.text}")
        raise HTTPException(status_code=502, detail="Transcription failed")

    transcript = resp.json().get("text", "").strip()
    return {"transcript": transcript}


@router.get("/topics")
async def list_topics(_: str = Depends(get_current_user)):
    return TOPICS


@router.get("/config")
async def get_config(_: str = Depends(get_current_user)):
    import os
    return {
        "claude_configured":     bool(os.environ.get("ANTHROPIC_API_KEY")),
        "elevenlabs_configured": bool(os.environ.get("ELEVENLABS_API_KEY")),
        "voice_id":              os.environ.get("ELEVENLABS_VOICE_ID", "onwK4e9ZLuTAKqWW03F9"),
    }


@router.post("/speak")
async def jarvis_speak(
    body: SpeakRequest,
    _: str = Depends(get_current_user),
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
        logger.error(f"[VAAYU Speak] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/chat")
async def jarvis_chat(
    body: ChatRequest,
    _: str = Depends(get_current_user),
):
    try:
        context = await _build_context(body.context_topic)
        svc     = get_jarvis_voice_service()
        history = [{"role": t.role, "content": t.content} for t in body.history]
        audio_bytes, script = await svc.generate_chat_response(body.message, context, history)
        return {
            "script": script,
            "audio":  base64.b64encode(audio_bytes).decode() if audio_bytes else None,
        }
    except Exception as exc:
        logger.error(f"[VAAYU Chat] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Context builder ───────────────────────────────────────────────────────

async def _build_context(topic: str) -> dict:
    ctx: dict = {}

    async def _safe(coro):
        try:
            return await coro
        except Exception:
            return None

    # Always: market LTP + change — use cached values when live data returns 0
    try:
        from backend.dependencies import get_market_service
        mkt = get_market_service()
        if mkt:
            md      = await _safe(mkt.get_current_market_data())
            # md.ltp may be 0 when market is closed — fall back to cached LTP
            ltp_val = (md.ltp if md and md.ltp > 0 else 0) or getattr(mkt, '_cached_ltp', 0)
            prev    = getattr(mkt, '_cached_prev_close', 0) or 0.0

            if ltp_val > 0:
                ctx["ltp"]       = ltp_val
                ctx["prev_close"] = prev if prev > 0 else None
                if prev > 0:
                    ctx["change"]     = round(ltp_val - prev, 2)
                    ctx["change_pct"] = round((ltp_val - prev) / prev * 100, 2)
                elif md:
                    ctx["change"]     = md.change
                    ctx["change_pct"] = md.change_percentage
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

    # Regime — NEW: use Vibe-Trading regime detection for accuracy boost
    if topic in ("market_summary", "full_briefing"):
        try:
            from backend.services.regime_service import detect_market_regime
            regime = await _safe(detect_market_regime())
            if regime:
                ctx["regime"] = regime.get("regime")
                ctx["regime_conf"] = regime.get("confidence")
                ctx["regime_recommendation"] = regime.get("recommendation")
                ctx["should_trade"] = regime.get("should_trade", True)
                ctx["momentum_winrate"] = regime.get("momentum_winrate", 0.55)
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

    # News — use in-memory cache (populated by _morning_news_loop on startup)
    # so chat requests are instant instead of re-fetching 6 RSS feeds each time
    if topic in ("news_brief", "full_briefing"):
        try:
            from backend.api.routes.market_data import _cached_news
            if _cached_news:
                ctx["news"] = _cached_news[:8]
            else:
                # Cache empty (e.g. first request before loop ran) — fetch once
                from backend.dependencies import get_market_service
                mkt = get_market_service()
                if mkt:
                    news = await _safe(mkt.get_news_summary(max_items=8))
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

    # Swing positions — always set key so formatter can say "none open" explicitly
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
            else:
                ctx["swing_positions"] = []
        except Exception:
            ctx["swing_positions"] = []

    # Account balance
    try:
        from backend.dependencies import get_angel_client
        ac = get_angel_client()
        if ac:
            funds = await _safe(asyncio.get_event_loop().run_in_executor(None, ac.get_funds))
            if funds and isinstance(funds, dict):
                ctx["balance"] = {
                    "net": funds.get("net", 0),
                    "available": funds.get("availablecash", funds.get("available", 0)),
                }
    except Exception:
        pass

    # Sector rotation top picks (cached — instant)
    try:
        from backend.services.sector_analysis_service import get_cached_analysis
        _cached_analysis = get_cached_analysis()
        if _cached_analysis:
            top = _cached_analysis.get("top_picks", [])
            ctx["sector_top_picks"] = top[:3] if top else []
    except Exception:
        pass

    # All broker holdings — cached 5 min to avoid hammering Angel One
    global _holdings_cache, _holdings_cache_time
    try:
        now = time.time()
        if _holdings_cache and (now - _holdings_cache_time) < _HOLDINGS_TTL:
            ctx["holdings"] = _holdings_cache
        else:
            # Try ETF service cached list first (always fast, no broker call)
            from backend.services.etf_holdings_service import get_etf_holdings_service
            etf_svc = get_etf_holdings_service()
            etf_cached = etf_svc.get_cached()

            # Fetch all raw holdings from broker (equities + ETFs)
            from backend.dependencies import get_angel_client
            ac = get_angel_client()
            all_holdings: list = []
            if ac:
                raw = await _safe(asyncio.get_event_loop().run_in_executor(None, ac.get_holdings))
                if raw and isinstance(raw, list):
                    for r in raw:
                        qty = int(r.get("quantity") or 0)
                        if qty <= 0:
                            continue
                        sym = (r.get("tradingsymbol") or "").replace("-EQ", "").upper()
                        avg = float(r.get("averageprice") or 0)
                        ltp = float(r.get("ltp") or r.get("close") or avg)
                        pnl_pct = ((ltp - avg) / avg * 100) if avg > 0 else 0.0
                        all_holdings.append({
                            "symbol":    sym,
                            "qty":       qty,
                            "avg_price": avg,
                            "pnl_pct":   round(pnl_pct, 2),
                        })

            final = all_holdings if all_holdings else etf_cached
            if final:
                _holdings_cache      = final
                _holdings_cache_time = now
                ctx["holdings"]      = final
    except Exception:
        pass

    return ctx
