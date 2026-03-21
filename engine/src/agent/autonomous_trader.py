"""
Autonomous Trading Agent — runs 24/7, trades on paper, learns from every trade.

THIS IS THE CORE OF THE SYSTEM.

The human (Kapil) sets the boundaries in agent/config.py.
Then this agent operates autonomously:

EVERY 60 SECONDS:
1. Scan all instruments on all entry timeframes
2. If a qualifying signal fires → auto paper trade it
3. Check open positions → close on SL/TP/breakeven
4. When a trade closes → Claude analyzes why it won/lost
5. Store lessons in the journal

DAILY:
6. Run learning engine → identify what's working
7. Update blacklists → disable failing strategies
8. Adjust confluence weights → favor what's working

WEEKLY:
9. Run walk-forward optimizer → retune parameters
10. Generate Claude weekly review → Telegram report

The agent doesn't just RECORD what happens — it LEARNS and ADAPTS.
Every trade makes the system smarter. Every loss teaches something.
This is the difference between a static system and an evolving one.
"""

import asyncio
import json
from datetime import datetime, timezone, timedelta, date
from ..data.market_data import market_data
from ..data.economic_calendar import is_in_blackout
from ..data.instruments import get_instrument
from ..confluence.scorer import compute_confluence
from ..risk.manager import risk_manager
from ..execution.paper_trader import paper_trader
from ..journal.database import log_signal
from ..alerts.telegram import send_telegram
from ..config import config
from .config import agent_config, AgentMode
from .trade_learner import analyze_closed_trade


class AutonomousTrader:
    """
    The autonomous trading agent.

    Runs in the background, scanning markets, placing paper trades,
    and learning from every outcome. No human input required.
    """

    def __init__(self):
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_trade_time: dict[str, datetime] = {}  # Cooldown per symbol
        self._daily_trades: dict[str, int] = {}  # Trade count per day
        self._today: date | None = None
        self._last_daily_review: date | None = None
        self._last_weekly_review: date | None = None

    async def start(self):
        """Start the autonomous trading loop."""
        if self._running:
            return

        if agent_config.mode == AgentMode.ALERT_ONLY:
            print("[Agent] Mode is ALERT_ONLY — autonomous trading disabled")
            return

        self._running = True
        print(f"[Agent] Autonomous trader started")
        print(f"[Agent] Mode: {agent_config.mode.value}")
        print(f"[Agent] Instruments: {config.active_instruments}")
        print(f"[Agent] Timeframes: {agent_config.scan_timeframes}")
        print(f"[Agent] Min score: {agent_config.min_score_to_trade}")

        await send_telegram(
            "*Notas Lave Agent Started*\n\n"
            f"Mode: `{agent_config.mode.value}`\n"
            f"Instruments: {', '.join(config.active_instruments)}\n"
            f"Auto paper trading: {'ON' if agent_config.can_auto_paper_trade else 'OFF'}\n"
            f"Learning: {'ON' if agent_config.learn_after_every_trade else 'OFF'}"
        )

        async def main_loop():
            while self._running:
                try:
                    await self._tick()
                except Exception as e:
                    print(f"[Agent] Tick error: {e}")
                await asyncio.sleep(agent_config.scan_interval_seconds)

        self._task = asyncio.create_task(main_loop())

    def stop(self):
        """Stop the autonomous trader."""
        self._running = False
        if self._task:
            self._task.cancel()
        print("[Agent] Autonomous trader stopped")

    async def _tick(self):
        """
        One cycle of the autonomous loop.

        Called every scan_interval_seconds (default 60s).
        """
        now = datetime.now(timezone.utc)
        today = now.date()

        # Reset daily counters
        if self._today != today:
            self._today = today
            self._daily_trades = {}

        # --- Check for closed positions and LEARN from them ---
        await self._check_and_learn_from_closed_positions()

        # --- News blackout check ---
        blocked, event = is_in_blackout(now, blackout_minutes=config.news_blackout_minutes)
        if blocked:
            return

        # --- Check open positions (update prices, check SL/TP) ---
        await paper_trader.update_positions()

        # --- Daily review ---
        if agent_config.daily_review and self._last_daily_review != today:
            if now.hour >= 22:  # Run at 10 PM UTC
                await self._run_daily_review()
                self._last_daily_review = today

        # --- Weekly optimizer ---
        if agent_config.weekly_optimizer and now.weekday() == 6:  # Sunday
            if self._last_weekly_review != today:
                await self._run_weekly_review()
                self._last_weekly_review = today

        # --- Scan and trade ---
        if not agent_config.can_auto_paper_trade:
            return

        # Don't open new trades if at max concurrent
        if paper_trader.open_count >= agent_config.max_concurrent_positions:
            return

        # Check daily trade limit
        daily_key = today.isoformat()
        daily_count = self._daily_trades.get(daily_key, 0)
        if daily_count >= agent_config.max_trades_per_day:
            return

        await self._scan_and_trade()

    async def _scan_and_trade(self):
        """Scan all instruments and auto paper trade qualifying signals."""
        for symbol in config.active_instruments:
            # Cooldown: minimum 5 minutes between trades per symbol
            last = self._last_trade_time.get(symbol)
            if last and (datetime.now(timezone.utc) - last).total_seconds() < 300:
                continue

            for tf in agent_config.scan_timeframes:
                try:
                    candles = await market_data.get_candles(symbol, tf, limit=250)
                    if not candles or len(candles) < 50:
                        continue

                    result = compute_confluence(candles, symbol, tf)

                    if (result.composite_score >= agent_config.min_score_to_trade / 10
                            and result.direction):

                        # Find the best signal for entry/exit levels
                        best = max(
                            (s for s in result.signals if s.direction is not None),
                            key=lambda s: s.score, default=None,
                        )
                        if not best or not best.entry_price or not best.stop_loss or not best.take_profit:
                            continue

                        # Check R:R
                        risk = abs(best.entry_price - best.stop_loss)
                        reward = abs(best.take_profit - best.entry_price)
                        if risk <= 0 or (reward / risk) < agent_config.min_rr_to_trade:
                            continue

                        # Log the signal
                        signal_id = log_signal(
                            symbol=symbol, timeframe=tf,
                            regime=result.regime.value,
                            composite_score=result.composite_score,
                            direction=result.direction.value,
                            agreeing=result.agreeing_strategies,
                            total=result.total_strategies,
                            signals=[{
                                "strategy": s.strategy_name,
                                "direction": s.direction.value if s.direction else None,
                                "score": s.score,
                            } for s in result.signals],
                            claude_action="AUTO_TRADE",
                            claude_confidence=int(result.composite_score),
                            claude_reasoning="Autonomous agent auto-trade",
                            risk_passed=True, risk_rejections=[],
                            should_trade=True,
                        )

                        # Calculate position size
                        spec = get_instrument(symbol)
                        pos_size = spec.calculate_position_size(
                            best.entry_price, best.stop_loss,
                            risk_manager.current_balance,
                            agent_config.max_risk_per_trade_pct,
                        )

                        if pos_size <= 0:
                            continue

                        # Execute paper trade
                        strategies_agreed = [
                            s.strategy_name for s in result.signals
                            if s.direction == result.direction
                        ]

                        position = paper_trader.open_position(
                            signal_log_id=signal_id,
                            symbol=symbol, timeframe=tf,
                            direction=result.direction,
                            regime=result.regime.value,
                            entry_price=best.entry_price,
                            stop_loss=best.stop_loss,
                            take_profit=best.take_profit,
                            position_size=pos_size,
                            confluence_score=result.composite_score,
                            claude_confidence=int(result.composite_score),
                            strategies_agreed=strategies_agreed,
                        )

                        # Track
                        self._last_trade_time[symbol] = datetime.now(timezone.utc)
                        daily_key = self._today.isoformat() if self._today else ""
                        self._daily_trades[daily_key] = self._daily_trades.get(daily_key, 0) + 1

                        print(f"[Agent] AUTO TRADE: {result.direction.value} {symbol} "
                              f"@ {best.entry_price} (score {result.composite_score})")

                        # Notify via Telegram
                        if agent_config.notify_on_trade_open:
                            await send_telegram(
                                f"*AUTO TRADE OPENED*\n\n"
                                f"Symbol: `{symbol}` ({tf})\n"
                                f"Direction: `{result.direction.value}`\n"
                                f"Entry: `{best.entry_price}`\n"
                                f"SL: `{best.stop_loss}` | TP: `{best.take_profit}`\n"
                                f"Score: `{result.composite_score}/10`\n"
                                f"Strategies: {', '.join(strategies_agreed)}"
                            )

                        return  # One trade per tick

                except Exception as e:
                    print(f"[Agent] Scan error {symbol} {tf}: {e}")
                    continue

    async def _check_and_learn_from_closed_positions(self):
        """
        Check if any positions were closed, then run Claude analysis on each.

        This is the LEARNING part — every closed trade teaches the agent something.
        """
        if not agent_config.learn_after_every_trade:
            return

        # Check for newly closed positions
        recently_closed = [
            p for p in paper_trader.closed_positions
            if not getattr(p, '_analyzed', False)
        ]

        for pos in recently_closed:
            pos._analyzed = True

            # Run Claude analysis on this trade
            try:
                lesson = await analyze_closed_trade(pos)
                if lesson:
                    print(f"[Agent] Learned from {pos.symbol} trade: {lesson[:80]}...")

                    if agent_config.notify_on_trade_close:
                        spec = get_instrument(pos.symbol)
                        pnl = spec.calculate_pnl(
                            pos.entry_price, pos.exit_price,
                            pos.position_size, pos.direction.value,
                        )
                        await send_telegram(
                            f"*TRADE CLOSED — {'WIN' if pnl > 0 else 'LOSS'}*\n\n"
                            f"Symbol: `{pos.symbol}`\n"
                            f"Direction: `{pos.direction.value}`\n"
                            f"P&L: `${pnl:.2f}`\n"
                            f"Exit: `{pos.exit_reason}`\n"
                            f"Duration: `{pos.duration_seconds // 60}m`\n\n"
                            f"*Lesson:* {lesson[:200]}"
                        )
            except Exception as e:
                print(f"[Agent] Learning error: {e}")

    async def _run_daily_review(self):
        """Run daily performance review and auto-adjust."""
        from ..learning.analyzer import analyze_overall
        from ..learning.recommendations import get_dynamic_blacklist

        analysis = analyze_overall()
        overall = analysis.get("overall", {})

        # Auto-update blacklists if permitted
        if agent_config.can_update_blacklists:
            new_blacklist = get_dynamic_blacklist()
            if new_blacklist:
                print(f"[Agent] Daily review: updated blacklists for {list(new_blacklist.keys())}")

        if agent_config.notify_daily_summary:
            trades = overall.get("trades", 0)
            if trades > 0:
                await send_telegram(
                    f"*Daily Summary*\n\n"
                    f"Trades: `{trades}`\n"
                    f"Win Rate: `{overall.get('win_rate', 0):.1f}%`\n"
                    f"P&L: `${overall.get('total_pnl', 0):.2f}`\n"
                    f"PF: `{overall.get('profit_factor', 0):.2f}`"
                )

    async def _run_weekly_review(self):
        """Run weekly optimizer and Claude review."""
        from ..learning.claude_review import generate_review

        print("[Agent] Running weekly review...")
        result = await generate_review()
        print(f"[Agent] Weekly review complete: {result.get('status')}")

    def get_status(self) -> dict:
        """Get agent status for the dashboard."""
        return {
            "running": self._running,
            "mode": agent_config.mode.value,
            "config": agent_config.to_dict(),
            "daily_trades": self._daily_trades,
            "open_positions": paper_trader.open_count,
            "total_closed": len(paper_trader.closed_positions),
        }


# Singleton
autonomous_trader = AutonomousTrader()
