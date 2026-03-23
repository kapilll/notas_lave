"""
Telegram Alerts — get notified when high-confluence setups fire.

HOW IT WORKS:
1. Auto-scanner runs every 60 seconds on all instruments across entry timeframes
2. When a setup scores above threshold (confluence >= 5), it sends you a Telegram message
3. The message includes: symbol, direction, score, which strategies agree, entry/SL/TP levels
4. You look at it on your phone, check your charting platform, and decide

SETUP:
1. Create a bot: Talk to @BotFather on Telegram, send /newbot
2. Get your chat ID: Visit https://api.telegram.org/bot<TOKEN>/getUpdates
3. Add to engine/.env:
   TELEGRAM_BOT_TOKEN=your_token
   TELEGRAM_CHAT_ID=your_chat_id

WHY TELEGRAM:
- Free, instant, works on phone
- You get alerts even when not at your computer
- Perfect for "co-pilot mode" — system finds setups, you decide
"""

import logging
import time

import httpx
from datetime import datetime, timezone
from ..config import config

logger = logging.getLogger(__name__)

# B-01: Cooldown tracking for error alerts — {component: last_alert_timestamp}
_error_alert_cooldowns: dict[str, float] = {}
_ERROR_COOLDOWN_SECONDS = 300  # 5 minutes

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

# OPS-13: Reuse a single httpx client instead of creating one per message.
_telegram_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Lazily create and return the shared Telegram HTTP client."""
    global _telegram_client
    if _telegram_client is None or _telegram_client.is_closed:
        _telegram_client = httpx.AsyncClient(
            timeout=10.0,
            event_hooks={"request": [], "response": []},  # SEC-14: Suppress URL logging (token in URL)
        )
    return _telegram_client


async def cleanup_telegram_client() -> None:
    """Close the shared httpx client. Call on application shutdown."""
    global _telegram_client
    if _telegram_client is not None and not _telegram_client.is_closed:
        await _telegram_client.aclose()
        _telegram_client = None


async def send_telegram(message: str) -> bool:
    """Send a message via Telegram bot. Returns True if successful."""
    if not config.telegram_bot_token or not config.telegram_chat_id:
        return False

    url = TELEGRAM_API.format(token=config.telegram_bot_token)

    try:
        client = _get_client()
        resp = await client.post(url, json={
            "chat_id": config.telegram_chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        })
        return resp.status_code == 200
    except Exception as e:
        logger.error("Send failed: %s", e)
        return False


async def send_error_alert(component: str, error_msg: str) -> bool:
    """B-01: Send an error alert via Telegram with per-component cooldown.

    Throttles alerts to max 1 per 5 minutes per component to avoid spam.
    """
    now = time.monotonic()
    last = _error_alert_cooldowns.get(component, 0)
    if now - last < _ERROR_COOLDOWN_SECONDS:
        logger.debug("Error alert for %s suppressed (cooldown)", component)
        return False

    _error_alert_cooldowns[component] = now
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    message = (
        f"[ERROR] {component}\n"
        f"Component crashed at {timestamp}\n"
        f"Error: {error_msg}\n\n"
        f"(Alerts throttled: max 1 per 5 min per component)"
    )
    return await send_telegram(message)


def format_signal_alert(
    symbol: str,
    timeframe: str,
    direction: str,
    score: float,
    regime: str,
    agreeing: int,
    total: int,
    signals: list[dict],
    price: float,
) -> str:
    """Format a trading signal into a readable Telegram message."""

    emoji = "🟢" if direction == "LONG" else "🔴" if direction == "SHORT" else "⚪"
    regime_emoji = {"TRENDING": "📈", "RANGING": "↔️", "VOLATILE": "⚡", "QUIET": "😴"}.get(regime, "❓")

    lines = [
        f"{emoji} *{symbol}* | {direction} | Score: {score}/10",
        f"⏱ {timeframe} | {regime_emoji} {regime} | {agreeing}/{total} agree",
        f"💰 Price: ${price:,.2f}",
        "",
    ]

    # Show active strategies
    active = [s for s in signals if s.get("direction")]
    if active:
        lines.append("*Strategies:*")
        for s in active:
            name = s.get("strategy", "").replace("_", " ").title()
            score_val = s.get("score", 0)
            reason = s.get("reason", "")[:80]
            lines.append(f"  • {name} ({score_val:.0f}) — {reason}")

        # Show entry/SL/TP from best signal
        best = max(active, key=lambda x: x.get("score", 0))
        if best.get("entry"):
            lines.append("")
            lines.append(f"📍 Entry: {best['entry']:.2f}")
            if best.get("stop_loss"):
                lines.append(f"🛑 SL: {best['stop_loss']:.2f}")
            if best.get("take_profit"):
                lines.append(f"🎯 TP: {best['take_profit']:.2f}")

    lines.append("")
    lines.append(f"🕐 {datetime.now(timezone.utc).strftime('%H:%M UTC')}")
    lines.append("_Open dashboard to evaluate & trade_")

    return "\n".join(lines)


def format_trade_opened(
    symbol: str, direction: str, entry: float, sl: float, tp: float,
    size: float, risk: float, confidence: int,
) -> str:
    """Format a trade opened notification."""
    emoji = "🟢" if direction == "LONG" else "🔴"
    return (
        f"{emoji} *TRADE OPENED*\n\n"
        f"*{symbol}* {direction}\n"
        f"📍 Entry: ${entry:,.2f}\n"
        f"🛑 SL: ${sl:,.2f}\n"
        f"🎯 TP: ${tp:,.2f}\n"
        f"📊 Size: {size} lots | Risk: ${risk:,.2f}\n"
        f"🤖 Claude confidence: {confidence}/10"
    )


def format_trade_closed(
    symbol: str, direction: str, entry: float, exit_price: float,
    pnl: float, exit_reason: str, duration_mins: float,
) -> str:
    """Format a trade closed notification."""
    emoji = "✅" if pnl >= 0 else "❌"
    reason_map = {
        "tp_hit": "Take Profit Hit ✅",
        "sl_hit": "Stop Loss Hit ❌",
        "manual": "Manual Close",
        "breakeven": "Breakeven",
        "timeout": "Timeout",
    }
    return (
        f"{emoji} *TRADE CLOSED*\n\n"
        f"*{symbol}* {direction}\n"
        f"📍 Entry: ${entry:,.2f} → Exit: ${exit_price:,.2f}\n"
        f"💰 P&L: *{'+'if pnl>=0 else ''}{pnl:,.2f}*\n"
        f"📋 Reason: {reason_map.get(exit_reason, exit_reason)}\n"
        f"⏱ Duration: {duration_mins:.0f} min"
    )
