"""
Auto-Scanner — continuously monitors markets and sends alerts.

Runs in the background every 60 seconds:
1. Scans all instruments on all entry timeframes
2. If confluence score >= alert threshold, sends Telegram notification
3. Prevents spam by tracking recently alerted setups (cooldown per symbol/timeframe)

This is what makes the system a "co-pilot" — you don't watch the dashboard,
the system watches the market and taps you on the shoulder when something
worth looking at appears.
"""

import asyncio
from datetime import datetime, timezone, timedelta
from ..data.market_data import market_data
from ..confluence.scorer import compute_confluence
from ..config import config
from .telegram import send_telegram, format_signal_alert


class AlertScanner:
    """
    Background scanner that monitors markets and sends Telegram alerts.

    Features:
    - Scans all instruments on entry timeframes (1m, 5m, 15m, 30m, 1h)
    - Alert threshold configurable (default: score >= 5.0)
    - Cooldown prevents spam (same symbol+tf won't alert again for 15 min)
    - Tracks sent alerts to avoid duplicates
    """

    def __init__(
        self,
        alert_threshold: float = 5.0,  # Minimum confluence score to alert
        scan_interval: int = 60,        # Seconds between scans
        cooldown_minutes: int = 15,     # Minutes before re-alerting same setup
    ):
        self.alert_threshold = alert_threshold
        self.scan_interval = scan_interval
        self.cooldown = timedelta(minutes=cooldown_minutes)
        self._last_alert: dict[str, datetime] = {}  # "XAUUSD_5m" -> last alert time
        self._running = False
        self._task: asyncio.Task | None = None

    def _cooldown_key(self, symbol: str, tf: str) -> str:
        return f"{symbol}_{tf}"

    def _is_on_cooldown(self, symbol: str, tf: str) -> bool:
        key = self._cooldown_key(symbol, tf)
        last = self._last_alert.get(key)
        if not last:
            return False
        return datetime.now(timezone.utc) - last < self.cooldown

    def _record_alert(self, symbol: str, tf: str):
        self._last_alert[self._cooldown_key(symbol, tf)] = datetime.now(timezone.utc)

    async def scan_once(self) -> list[dict]:
        """
        Run one scan cycle across all instruments and timeframes.
        Returns list of alerts that were sent.
        """
        alerts_sent = []

        # Only scan meaningful timeframes (not 1m — too noisy for alerts)
        scan_timeframes = ["5m", "15m", "30m", "1h"]

        for symbol in config.instruments:
            for tf in scan_timeframes:
                if self._is_on_cooldown(symbol, tf):
                    continue

                try:
                    candles = await market_data.get_candles(symbol, tf, limit=250)
                    if not candles or len(candles) < 50:
                        continue

                    result = compute_confluence(candles, symbol, tf)

                    if result.composite_score >= self.alert_threshold and result.direction:
                        # Format and send alert
                        signal_data = [
                            {
                                "strategy": s.strategy_name,
                                "direction": s.direction.value if s.direction else None,
                                "score": s.score,
                                "reason": s.reason[:100],
                                "entry": s.entry_price,
                                "stop_loss": s.stop_loss,
                                "take_profit": s.take_profit,
                            }
                            for s in result.signals
                        ]

                        message = format_signal_alert(
                            symbol=symbol,
                            timeframe=tf,
                            direction=result.direction.value,
                            score=result.composite_score,
                            regime=result.regime.value,
                            agreeing=result.agreeing_strategies,
                            total=result.total_strategies,
                            signals=signal_data,
                            price=candles[-1].close,
                        )

                        sent = await send_telegram(message)
                        if sent:
                            self._record_alert(symbol, tf)
                            alerts_sent.append({
                                "symbol": symbol,
                                "timeframe": tf,
                                "score": result.composite_score,
                                "direction": result.direction.value,
                            })
                            print(f"[Alert] Sent: {symbol} {tf} {result.direction.value} (score {result.composite_score})")

                except Exception as e:
                    print(f"[Alert] Error scanning {symbol} {tf}: {e}")
                    continue

        return alerts_sent

    async def start(self):
        """Start the background scanner loop."""
        if self._running:
            return

        # Check if Telegram is configured
        if not config.telegram_bot_token or not config.telegram_chat_id:
            print("[Alert] Telegram not configured. Scanner disabled.")
            print("[Alert] Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env")
            return

        self._running = True
        print(f"[Alert] Scanner started. Threshold: {self.alert_threshold}, Interval: {self.scan_interval}s, Cooldown: {self.cooldown}")

        # Send startup message
        await send_telegram(
            "🚀 *Notas Lave Alert Scanner Started*\n\n"
            f"Monitoring: {', '.join(config.instruments)}\n"
            f"Timeframes: 5m, 15m, 30m, 1h\n"
            f"Alert threshold: {self.alert_threshold}/10\n"
            f"Scan interval: {self.scan_interval}s"
        )

        async def scan_loop():
            while self._running:
                try:
                    await self.scan_once()
                except Exception as e:
                    print(f"[Alert] Scan loop error: {e}")
                await asyncio.sleep(self.scan_interval)

        self._task = asyncio.create_task(scan_loop())

    def stop(self):
        """Stop the scanner."""
        self._running = False
        if self._task:
            self._task.cancel()
        print("[Alert] Scanner stopped.")

    def get_status(self) -> dict:
        """Get scanner status for the dashboard."""
        return {
            "running": self._running,
            "threshold": self.alert_threshold,
            "interval": self.scan_interval,
            "cooldown_minutes": self.cooldown.total_seconds() / 60,
            "active_cooldowns": {
                k: v.isoformat() for k, v in self._last_alert.items()
                if datetime.now(timezone.utc) - v < self.cooldown
            },
        }


# Singleton
alert_scanner = AlertScanner()
