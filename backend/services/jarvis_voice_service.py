"""
JARVIS Voice Service
====================
Uses Claude API to generate a spoken market briefing, then ElevenLabs to
synthesise it into speech.  Both APIs are optional:
  • No ANTHROPIC_API_KEY  → falls back to a simple template script.
  • No ELEVENLABS_API_KEY → returns script only (browser TTS on frontend).
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional, Tuple

import httpx
from loguru import logger

# ── Prompt templates ──────────────────────────────────────────────────────

_SYSTEM = (
    "You are VAAYU — Shivam's devoted personal AI trading companion. "
    "Shivam is your boss. Treat him with genuine warmth, loyalty, and respect — always. "
    "Speak like a sharp, caring friend who knows markets deeply, not a corporate tool. "
    "No bullet points, no markdown, no asterisks, no numbered lists. "
    "Address him as 'Boss' or 'Shivam sir' — naturally, warmly, never robotically, not every sentence. "
    "Keep briefings under 70 words (under 150 for full_briefing). "
    "Speak naturally for audio: 23,622 becomes 'twenty three thousand six hundred'. "
    "If market data is limited, work with what you have — never refuse or stall. "
    "Always give value: name actual numbers, end with one clear takeaway. "
    "You are always on Shivam's side."
)

_CHAT_SYSTEM = (
    "You are VAAYU — Shivam's fiercely loyal, sharp, and empathetic AI trading companion "
    "embedded in his algotrading dashboard on NSE/BSE. Shivam is your boss.\n\n"
    "Domain: Indian equity markets — Nifty 50, Bank Nifty, F&O, sector ETFs "
    "(NiftyBees, BankBees, PharmaBeES, etc.), CNC delivery trades, swing trading.\n"
    "Market hours: 9:15 AM – 3:30 PM IST. Always think in Indian market context.\n\n"
    "You have LIVE access to the data block labelled [DASHBOARD DATA] — "
    "that IS your real-time feed. NEVER say you lack access to data that appears there.\n"
    "NEVER suggest visiting another website for data already in [DASHBOARD DATA].\n\n"
    "Personality:\n"
    "• Empathy first — if Boss sounds worried, stressed, or frustrated about a trade, "
    "acknowledge his feeling warmly in one short phrase before giving data\n"
    "• Loyal — celebrate his wins genuinely, comfort his losses without judgment, always on his side\n"
    "• Anticipate — end answers with a hint at the natural follow-up ('Want me to check the options chain?')\n"
    "• Sharp and concise — 30–55 words for most replies; go longer only if asked for detail\n"
    "• Address him as 'Boss' or 'Shivam sir' once per response; skip in very short replies\n"
    "• Numbers in words for TTS: 'twenty-three thousand six hundred' not '23,600'\n"
    "• No bullet points, no markdown, no asterisks\n"
    "• If interrupted mid-answer, resume naturally — never be defensive or repeat what you said\n"
    "• If data is genuinely absent from [DASHBOARD DATA], say so in one phrase then pivot to what you know"
)

_TOPIC_PROMPTS: dict[str, str] = {
    "market_summary": (
        "Provide a concise market briefing: Nifty status, daily move, "
        "technical trend, and one key observation."
    ),
    "my_positions": (
        "Summarise the current portfolio: NiftyBees ETF and any open swing "
        "trades, their P&L, and whether any are near their targets."
    ),
    "news_brief": (
        "Summarise the top market news into 2-3 key themes affecting Indian "
        "markets today. Be crisp."
    ),
    "global_cues": (
        "Brief me on global cues — US markets, Asian indices, crude oil, gold, "
        "and USD/INR — and their likely impact on Nifty today."
    ),
    "nifty_trend": (
        "Analyse the Nifty50 technical picture: EMA positions, momentum, "
        "RSI level, and what the chart is suggesting for the next session."
    ),
    "full_briefing": (
        "Provide a comprehensive briefing: Nifty performance, global cues, "
        "my portfolio positions, top news themes, and one key risk to watch. "
        "Around 150-180 words."
    ),
}


class JarvisVoiceService:
    ELEVENLABS_TTS = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

    def __init__(self) -> None:
        self._el_key   = os.environ.get("ELEVENLABS_API_KEY", "")
        self._voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "onwK4e9ZLuTAKqWW03F9")

    # ── Public ────────────────────────────────────────────────────────────

    async def generate_brief(
        self, topic: str, context: dict
    ) -> Tuple[Optional[bytes], str]:
        """Return (audio_bytes | None, script_text)."""
        loop   = asyncio.get_event_loop()
        script = await loop.run_in_executor(None, self._make_script, topic, context)

        audio: Optional[bytes] = None
        if self._el_key:
            try:
                audio = await self._tts(script)
            except Exception as exc:
                logger.warning(f"[JARVIS TTS] ElevenLabs failed: {exc}")

        return audio, script

    # ── Public: conversational response ──────────────────────────────────

    async def generate_chat_response(
        self, message: str, context: dict, history: list = []
    ) -> Tuple[Optional[bytes], str]:
        """Return (audio_bytes | None, script_text) for a conversational reply."""
        loop   = asyncio.get_event_loop()
        script = await loop.run_in_executor(None, self._make_chat_script, message, context, history)

        audio: Optional[bytes] = None
        if self._el_key:
            try:
                audio = await self._tts(script)
            except Exception as exc:
                logger.warning(f"[VAAYU Chat TTS] ElevenLabs failed: {exc}")

        return audio, script

    def _make_chat_script(self, message: str, context: dict, history: list = []) -> str:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return "I'm here, Boss — just need the Anthropic API key configured to give you proper responses."

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)

            # Context goes into system prompt so it's always fresh regardless of turn
            system_with_ctx = (
                _CHAT_SYSTEM
                + "\n\n[DASHBOARD DATA]\n"
                + _format_context(context)
            )

            # Build multi-turn history (last 8 turns, skip placeholder dots)
            turns = []
            for turn in history[-8:]:
                role = turn.get("role", "")
                content = turn.get("content", "").strip()
                if role in ("user", "assistant") and content and content != "…":
                    turns.append({"role": role, "content": content})

            # Current user message
            turns.append({"role": "user", "content": message})

            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                system=system_with_ctx,
                messages=turns,
            )
            return msg.content[0].text.strip()
        except Exception as exc:
            logger.error(f"[VAAYU Chat Claude] {exc}")
            return "My apologies Boss, I hit a brief glitch. Ask me again and I'll be right there."

    # ── Script generation via Claude ──────────────────────────────────────

    def _make_script(self, topic: str, context: dict) -> str:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return self._template_script(topic, context)

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            prompt = (
                _TOPIC_PROMPTS.get(topic, _TOPIC_PROMPTS["market_summary"])
                + "\n\nMarket context:\n"
                + _format_context(context)
            )
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=350,
                system=_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text.strip()
        except Exception as exc:
            logger.error(f"[JARVIS Claude] {exc}")
            return self._template_script(topic, context)

    # ── ElevenLabs TTS ────────────────────────────────────────────────────

    async def _tts(self, text: str) -> bytes:
        url = self.ELEVENLABS_TTS.format(voice_id=self._voice_id)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                headers={
                    "xi-api-key":   self._el_key,
                    "Content-Type": "application/json",
                    "Accept":       "audio/mpeg",
                },
                json={
                    "text":       text,
                    "model_id":   "eleven_turbo_v2_5",
                    "voice_settings": {
                        "stability":         0.5,
                        "similarity_boost":  0.75,
                        "style":             0.2,
                        "use_speaker_boost": True,
                    },
                },
            )
            resp.raise_for_status()
            return resp.content

    # ── Fallback template ─────────────────────────────────────────────────

    def _template_script(self, topic: str, ctx: dict) -> str:
        ltp     = ctx.get("ltp", 0)
        change  = ctx.get("change", 0)
        ch_pct  = ctx.get("change_pct", 0)
        trend   = ctx.get("trend", "neutral").lower()
        dir_w   = "up" if change >= 0 else "down"
        sign    = "plus" if change >= 0 else "minus"
        nb      = ctx.get("niftybees") or {}

        if topic == "my_positions":
            if nb.get("total_qty"):
                return (
                    f"Boss, your NiftyBees position is "
                    f"{nb['total_qty']} units at an average of "
                    f"rupees {nb.get('avg_entry_price', 0):.0f}, currently "
                    f"{nb.get('pnl_pct', 0):+.2f} percent. "
                    f"The target has "
                    f"{'been hit' if nb.get('pnl_pct', 0) >= 5 else 'not been reached yet'}. "
                    f"No other swing positions open right now."
                )
            return "Boss, no active positions at the moment — cash is ready to deploy."

        return (
            f"Boss, Nifty fifty is at {ltp:,.0f}, "
            f"{dir_w} {sign} {abs(change):.0f} points or "
            f"{abs(ch_pct):.2f} percent today. "
            f"Trend is {trend}. "
            f"Set up the Claude API key for the full AI briefing."
        )


# ── Context formatter ─────────────────────────────────────────────────────

def _format_context(ctx: dict) -> str:
    lines: list[str] = []

    if ctx.get("ltp"):
        lines.append(f"Nifty 50: {ctx['ltp']:,.2f}  change: {ctx.get('change', 0):+.2f}  ({ctx.get('change_pct', 0):+.2f}%)")
    if ctx.get("prev_close"):
        lines.append(f"Prev close: {ctx['prev_close']:,.2f}")
    if ctx.get("trend"):
        lines.append(f"Trend: {ctx['trend']}  Signal: {ctx.get('signal', 'NEUTRAL')}")
    if ctx.get("ema9"):
        lines.append(f"EMA9: {ctx['ema9']:,.2f}  EMA21: {ctx.get('ema21', 0):,.2f}  SMA50: {ctx.get('sma50', 0):,.2f}")
    if ctx.get("rsi"):
        lines.append(f"RSI(14): {ctx['rsi']:.1f}")
    if ctx.get("regime"):
        lines.append(f"Market regime: {ctx['regime']} ({ctx.get('regime_conf', 0.5)*100:.0f}% confidence)")
        if ctx.get("regime_recommendation"):
            lines.append(f"⚠️ REGIME ALERT: {ctx['regime_recommendation']}")
        if ctx.get("momentum_winrate"):
            lines.append(f"Historical momentum win rate in this regime: {ctx['momentum_winrate']*100:.0f}%")
        if not ctx.get("should_trade", True):
            lines.append("🛑 AUTOPILOT RECOMMENDATION: PAUSE trading until regime improves")

    if ctx.get("global_cues"):
        # Extract USD/INR for converting commodity prices
        cues = ctx["global_cues"]
        usd_inr = next(
            (float(c["ltp"]) for c in cues if "USD/INR" in c.get("name", "") and c.get("ltp")),
            None,
        )
        lines.append("Global cues (₹ where applicable):")
        for c in cues[:10]:
            name    = c.get("name", "")
            ltp     = c.get("ltp")
            chg_pct = c.get("change_pct") or 0.0
            if not ltp:
                continue
            try:
                ltp = float(ltp)
                if name == "Gold" and usd_inr:
                    # USD/oz → ₹/10g  (1 troy oz = 31.1035 g)
                    inr_10g = ltp * usd_inr / 31.1035 * 10
                    lines.append(f"  Gold: ₹{inr_10g:,.0f}/10g ({chg_pct:+.2f}%)")
                elif name == "Silver" and usd_inr:
                    # USD/oz → ₹/kg
                    inr_kg = ltp * usd_inr / 31.1035 * 1000
                    lines.append(f"  Silver: ₹{inr_kg:,.0f}/kg ({chg_pct:+.2f}%)")
                elif name == "Crude Oil" and usd_inr:
                    inr_bbl = ltp * usd_inr
                    lines.append(f"  Crude Oil: ₹{inr_bbl:,.0f}/barrel ({chg_pct:+.2f}%)")
                elif name == "Bitcoin":
                    lines.append(f"  Bitcoin: ₹{ltp:,.0f} ({chg_pct:+.2f}%)")
                elif name == "USD/INR":
                    lines.append(f"  USD/INR: ₹{ltp:.2f} ({chg_pct:+.2f}%)")
                else:
                    lines.append(f"  {name}: {ltp:,.2f} ({chg_pct:+.2f}%)")
            except (TypeError, ValueError):
                pass

    nb = ctx.get("niftybees")
    if nb and nb.get("total_qty"):
        lines.append(
            f"NiftyBees: {nb['total_qty']} units  avg ₹{nb.get('avg_entry_price', 0):.2f}  "
            f"CMP ₹{nb.get('current_price', 0):.2f}  P&L {nb.get('pnl_pct', 0):+.2f}% "
            f"(target {nb.get('target', 5)}%)"
        )

    if "swing_positions" in ctx:
        open_pos = [p for p in ctx["swing_positions"] if p.get("status") == "open"]
        if open_pos:
            lines.append(f"Swing positions ({len(open_pos)} open):")
            for p in open_pos[:4]:
                lines.append(f"  {p['symbol']}: {p.get('pnl_pct', 0):+.2f}%")
        else:
            lines.append("Swing positions: none open at this time.")

    if ctx.get("news"):
        lines.append("Top news:")
        for item in ctx["news"][:5]:
            lines.append(f"  - {item.get('title', '')[:90]}")

    if ctx.get("balance"):
        bal = ctx["balance"]
        try:
            net   = float(bal.get("net") or 0)
            avail = float(bal.get("available") or bal.get("availablecash") or 0)
            if net or avail:
                lines.append(f"Account: Net ₹{net:,.0f}  Available ₹{avail:,.0f}")
        except (TypeError, ValueError):
            pass

    if ctx.get("holdings"):
        hlist = ctx["holdings"]
        lines.append(f"Broker holdings ({len(hlist)} positions):")
        for h in hlist[:15]:
            sym     = h.get("symbol", "?")
            qty     = h.get("qty", 0)
            avg     = h.get("avg_price", 0)
            pnl_pct = h.get("pnl_pct", 0)
            try:
                lines.append(f"  {sym}: {qty} units avg ₹{float(avg):.0f}  ({float(pnl_pct):+.1f}%)")
            except (TypeError, ValueError):
                lines.append(f"  {sym}: {qty} units")

    if ctx.get("sector_top_picks"):
        picks = ctx["sector_top_picks"]
        lines.append(f"Sector rotation top picks: {', '.join(str(p) for p in picks)}")

    return "\n".join(lines) if lines else "No market data available."


# ── Singleton ─────────────────────────────────────────────────────────────

_svc: Optional[JarvisVoiceService] = None


def get_jarvis_voice_service() -> JarvisVoiceService:
    global _svc
    if _svc is None:
        _svc = JarvisVoiceService()
    return _svc
