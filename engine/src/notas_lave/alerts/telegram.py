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

