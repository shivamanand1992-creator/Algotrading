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
    "You are JARVIS, the AI assistant for Shivam's algorithmic trading system. "
    "Generate spoken briefings in a sophisticated, confident tone — like a "
    "British AI assistant. Use natural speech (no bullet points, no markdown, "
    "no asterisks). Address the user as 'sir' once. Keep it under 120 words "
    "unless the topic is 'full_briefing' (then up to 200 words). "
    "Speak naturally — numbers should be spoken: 23,530 becomes 'twenty-three "
    "thousand five hundred thirty'."
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
                    f"Good day, sir. Your NiftyBees position stands at "
                    f"{nb['total_qty']} units at an average of "
                    f"rupees {nb.get('avg_entry_price', 0):.0f}, currently "
                    f"{nb.get('pnl_pct', 0):+.2f} percent in your favour. "
                    f"The five percent target has "
                    f"{'been reached' if nb.get('pnl_pct', 0) >= 5 else 'not yet been reached'}. "
                    f"No other swing positions are open at this time."
                )
            return "Good day, sir. No active positions at the moment."

        return (
            f"Good day, sir. Nifty fifty is trading at {ltp:,.0f}, "
            f"{dir_w} {sign} {abs(change):.0f} points or "
            f"{abs(ch_pct):.2f} percent today. "
            f"The technical trend is {trend}. "
            f"Configure the Claude API key for detailed AI briefings."
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

    if ctx.get("global_cues"):
        lines.append("Global cues:")
        for c in ctx["global_cues"][:6]:
            if c.get("ltp") and c.get("change_pct") is not None:
                lines.append(f"  {c['name']}: {c['ltp']:,.2f} ({c['change_pct']:+.2f}%)")

    nb = ctx.get("niftybees")
    if nb and nb.get("total_qty"):
        lines.append(
            f"NiftyBees: {nb['total_qty']} units  avg ₹{nb.get('avg_entry_price', 0):.2f}  "
            f"CMP ₹{nb.get('current_price', 0):.2f}  P&L {nb.get('pnl_pct', 0):+.2f}% "
            f"(target {nb.get('target', 5)}%)"
        )

    if ctx.get("swing_positions"):
        open_pos = [p for p in ctx["swing_positions"] if p.get("status") == "open"]
        if open_pos:
            lines.append(f"Swing positions ({len(open_pos)} open):")
            for p in open_pos[:4]:
                lines.append(f"  {p['symbol']}: {p.get('pnl_pct', 0):+.2f}%")

    if ctx.get("news"):
        lines.append("Top news:")
        for item in ctx["news"][:5]:
            lines.append(f"  - {item.get('title', '')[:90]}")

    return "\n".join(lines) if lines else "No market data available."


# ── Singleton ─────────────────────────────────────────────────────────────

_svc: Optional[JarvisVoiceService] = None


def get_jarvis_voice_service() -> JarvisVoiceService:
    global _svc
    if _svc is None:
        _svc = JarvisVoiceService()
    return _svc
