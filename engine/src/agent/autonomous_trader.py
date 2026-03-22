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
import logging
from datetime import datetime, timezone, timedelta, date
from ..data.market_data import market_data

logger = logging.getLogger(__name__)
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
from ..learning.accuracy import log_prediction, resolve_pending_predictions


class AutonomousTrader:
    """
    The autonomous trading agent.

    Runs in the background, scanning markets, placing paper trades,
    and learning from every outcome. No human input required.
    """

    # Map timeframe strings to their duration in seconds for candle-alignment
    _TF_SECONDS: dict[str, int] = {
        "1m": 60, "3m": 180, "5m": 300, "15m": 900,
        "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400,
    }

    def __init__(self):
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_trade_time: dict[str, datetime] = {}  # Cooldown per symbol
        self._daily_trades: dict[str, int] = {}  # Trade count per day
        self._today: date | None = None
        self._last_daily_review: date | None = None
        self._last_weekly_review: date | None = None
        self._last_reconciliation: datetime | None = None  # AT-04: position reconciliation
        self._active_orders: dict[str, dict] = {}  # AT-08: position_id → {main, sl, tp} order IDs
        self._analyzed_trades: set[str] = set()  # AT-10: track analyzed positions by ID (no monkey-patching)
        self._broker = None  # AT-09: reusable broker instance
        self._last_heartbeat: datetime | None = None  # AT-16: health check heartbeat

    async def start(self):
        """Start the autonomous trading loop."""
        if self._running:
            return

        if agent_config.mode == AgentMode.ALERT_ONLY:
            logger.info("Mode is ALERT_ONLY — autonomous trading disabled")
            return

        self._running = True
        logger.info("Autonomous trader started")
        logger.info("Mode: %s", agent_config.mode.value)
        logger.info("Instruments: %s", config.active_instruments)
        logger.info("Timeframes: %s", agent_config.scan_timeframes)
        logger.info("Min score: %s", agent_config.min_score_to_trade)

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
                    logger.error("Tick error: %s", e)
                await asyncio.sleep(agent_config.scan_interval_seconds)

        self._task = asyncio.create_task(main_loop())

    def stop(self):
        """Stop the autonomous trader."""
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("Autonomous trader stopped")

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

        # --- AT-16: Heartbeat every 6 hours ---
        if (self._last_heartbeat is None or
                (now - self._last_heartbeat).total_seconds() >= 21600):
            daily_key = today.isoformat()
            await send_telegram(
                f"Notas Lave heartbeat: {paper_trader.open_count} positions, "
                f"{self._daily_trades.get(daily_key, 0)} trades today, "
                f"balance ${risk_manager.current_balance:.2f}"
            )
            self._last_heartbeat = now

        # --- AT-04: Reconcile local vs exchange positions every 5 minutes ---
        if config.broker != "paper":
            if (self._last_reconciliation is None or
                    (now - self._last_reconciliation).total_seconds() >= 300):
                await self._reconcile_positions()
                self._last_reconciliation = now

        # --- AT-F01: Detect exchange-side SL/TP fills ---
        # When using a real broker, the exchange handles SL/TP execution.
        # If an exchange-side fill happens, our local positions become stale.
        # This detects and resolves those by closing local positions that
        # the exchange already closed.
        if config.broker != "paper":
            await self._detect_exchange_fills()

        # --- Check for closed positions and LEARN from them ---
        await self._check_and_learn_from_closed_positions()

        # ML-18 FIX: Resolve pending predictions using actual candle data.
        # Predictions logged at trade open are never marked hit/miss without this.
        try:
            resolve_pending_predictions(market_data.get_candles)  # sync function
        except Exception as e:
            logger.debug("Prediction resolution error: %s", e)

        # --- News blackout check ---
        blocked, event = is_in_blackout(now, blackout_minutes=config.news_blackout_minutes)
        if blocked:
            return

        # --- Check open positions (update prices, check SL/TP) ---
        # AT-29 FIX: Only use paper_trader for SL/TP monitoring in paper mode.
        # When using a real broker, the exchange handles SL/TP execution.
        # paper_trader is still used for local position tracking, but its
        # update_positions() would conflict with exchange-managed SL/TP orders.
        if config.broker == "paper":
            await paper_trader.update_positions()

        # RC-03: Update risk manager with current unrealized P&L from open positions.
        # FundingPips monitors equity (balance + floating P&L), not just closed P&L.
        unrealized = sum(
            pos.unrealized_pnl for pos in paper_trader.positions.values()
            if hasattr(pos, 'unrealized_pnl')
        )
        risk_manager.update_unrealized_pnl(unrealized)

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

    async def _get_broker(self):
        """
        AT-09: Return the appropriate broker based on config.broker.

        Initializes the broker once and reuses it. Falls back to None
        for "paper" mode (uses paper_trader directly instead).
        """
        if config.broker == "paper":
            return None  # Use paper_trader directly

        if self._broker is not None:
            return self._broker

        from ..execution.binance_testnet import BinanceTestnetBroker
        from ..execution.coindcx import CoinDCXBroker
        from ..execution.mt5_broker import MT5Broker

        if config.broker == "binance_testnet":
            self._broker = BinanceTestnetBroker()
        elif config.broker == "coindcx":
            self._broker = CoinDCXBroker()
        elif config.broker == "mt5":
            self._broker = MT5Broker()

        if self._broker and not self._broker.is_connected:
            connected = await self._broker.connect()
            if not connected:
                logger.warning("Could not connect to %s broker", config.broker)
                self._broker = None

        return self._broker

    def _is_candle_fresh(self, candle_timestamp: datetime, timeframe: str) -> bool:
        """
        AT-01/AT-22: Check if the latest candle has closed recently.

        Returns True if the candle closed within the last candle-period,
        meaning we have a fresh, complete candle to analyze.
        A candle that hasn't closed yet should not trigger signals.
        """
        tf_seconds = self._TF_SECONDS.get(timeframe, 300)  # Default to 5m
        now = datetime.now(timezone.utc)
        age = (now - candle_timestamp).total_seconds()
        # The candle is "fresh" if it closed within the last candle-period
        # (e.g., for 5m candles, the candle timestamp should be within the last 300s)
        return 0 <= age <= tf_seconds

    async def _scan_and_trade(self):
        """Scan all instruments and auto paper trade qualifying signals."""
        now = datetime.now(timezone.utc)
        for symbol in config.active_instruments:
            # RC-07 FIX: Skip metals on Friday after 19:00 UTC — weekend gap risk.
            # Gold and Silver markets close over the weekend and can gap significantly
            # on Monday open, blowing past stop losses set on Friday.
            if symbol in ("XAUUSD", "XAGUSD") and now.weekday() == 4 and now.hour >= 19:
                continue

            # Cooldown: minimum 5 minutes between trades per symbol
            last = self._last_trade_time.get(symbol)
            if last and (datetime.now(timezone.utc) - last).total_seconds() < 300:
                continue

            for tf in agent_config.scan_timeframes:
                try:
                    candles = await market_data.get_candles(symbol, tf, limit=250)
                    if not candles or len(candles) < 50:
                        continue

                    # AT-01: Only scan on fresh (recently closed) candles
                    # Skip if the latest candle hasn't closed yet — avoids
                    # acting on incomplete data and redundant scans
                    if not self._is_candle_fresh(candles[-1].timestamp, tf):
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

                        # AT-20: Skip if spread eats >5% of SL distance
                        spec = get_instrument(symbol)
                        if risk > 0 and spec.spread_typical / risk > 0.05:
                            logger.info("Skipping %s: spread (%s) is %.1f%% of SL distance",
                                    symbol, spec.spread_typical, spec.spread_typical / risk * 100)
                            continue

                        # Calculate position size (spec already fetched for AT-20 spread check)
                        pos_size = spec.calculate_position_size(
                            best.entry_price, best.stop_loss,
                            risk_manager.current_balance,
                            agent_config.max_risk_per_trade_pct,
                        )

                        if pos_size <= 0:
                            continue

                        # TP-05: Conviction scaling — higher scores get full risk,
                        # lower scores get reduced risk. This prevents moderate-quality
                        # setups from risking the same as high-conviction setups.
                        if result.composite_score < 7.0:
                            pos_size = round(pos_size * 0.6, 6)  # 60% size for moderate setups
                            if pos_size <= 0:
                                continue

                        # RC-01 FIX: Pass EVERY trade through risk_manager.validate_trade().
                        # This was the #1 finding across ALL review panels — the risk
                        # gatekeeper existed but was NEVER called by the autonomous trader.
                        # Without this, daily drawdown, total drawdown, consistency rule,
                        # hedging detection, and news blackout checks are all bypassed.
                        from ..data.models import TradeSetup
                        setup = TradeSetup(
                            symbol=symbol,
                            timeframe=tf,
                            direction=result.direction,
                            entry_price=best.entry_price,
                            stop_loss=best.stop_loss,
                            take_profit=best.take_profit,
                            position_size=pos_size,
                            risk_reward_ratio=reward / risk if risk > 0 else 0,
                            confluence_score=result.composite_score,
                            regime=result.regime,
                        )

                        # Build open_positions map for hedging detection (RC-05)
                        open_positions_map = {
                            pos.symbol: pos.direction.value
                            for pos in paper_trader.positions.values()
                        }

                        risk_passed, risk_rejections = risk_manager.validate_trade(
                            setup, open_positions=open_positions_map
                        )

                        # Log the signal with actual risk validation result
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
                            risk_passed=risk_passed,
                            risk_rejections=risk_rejections,
                            should_trade=risk_passed,
                        )

                        if not risk_passed:
                            logger.warning("Trade REJECTED by risk manager: %s %s — %s",
                                           symbol, result.direction.value, risk_rejections)
                            continue

                        # Log this as a prediction for accuracy tracking
                        try:
                            log_prediction(
                                symbol=symbol,
                                timeframe=tf,
                                strategy_name=best.strategy_name,
                                predicted_direction=result.direction.value,
                                entry_price=best.entry_price,
                                stop_loss=best.stop_loss,
                                take_profit=best.take_profit,
                                confluence_score=result.composite_score,
                                regime=result.regime.value,
                            )
                        except Exception as e:
                            logger.debug("Non-critical error logging prediction: %s", e)

                        # AT-22: Re-fetch current price to avoid stale entries
                        # The strategy signal may have been computed on a candle
                        # that closed seconds ago; use the latest close as entry
                        current_price = candles[-1].close

                        # Execute trade via appropriate broker
                        strategies_agreed = [
                            s.strategy_name for s in result.signals
                            if s.direction == result.direction
                        ]

                        broker = await self._get_broker()

                        if broker is not None:
                            # AT-09: Use real broker (Binance Demo, CoinDCX, MT5)
                            from ..execution.base_broker import OrderSide, OrderType
                            side = OrderSide.BUY if result.direction.value == "LONG" else OrderSide.SELL
                            order = await broker.place_order(
                                symbol=symbol,
                                side=side,
                                quantity=pos_size,
                                order_type=OrderType.MARKET,
                                price=current_price,
                                stop_loss=best.stop_loss,
                                take_profit=best.take_profit,
                            )

                            from ..execution.base_broker import OrderStatus
                            if order.status != OrderStatus.FILLED:
                                logger.warning("Order REJECTED by %s: %s", config.broker, symbol)
                                continue

                            # Use the broker's fill price as the actual entry
                            actual_entry = order.filled_price if order.filled_price > 0 else current_price

                            # MM-08 FIX: Check if fill price deviates significantly from signal entry.
                            # If fill deviates by >20% of SL distance, the risk:reward is materially
                            # different from what the strategy intended. Log for monitoring.
                            fill_deviation = abs(actual_entry - best.entry_price)
                            if risk > 0 and fill_deviation / risk > 0.20:
                                logger.warning("MM-08: %s fill deviation %.4f is %.1f%% of SL distance "
                                               "(signal entry=%s, fill=%s)",
                                               symbol, fill_deviation, fill_deviation / risk * 100,
                                               best.entry_price, actual_entry)

                            # AT-08: Track SL/TP order IDs from the broker
                            # Also record in paper_trader for local position tracking
                            position = paper_trader.open_position(
                                signal_log_id=signal_id,
                                symbol=symbol, timeframe=tf,
                                direction=result.direction,
                                regime=result.regime.value,
                                entry_price=actual_entry,
                                stop_loss=best.stop_loss,
                                take_profit=best.take_profit,
                                position_size=pos_size,
                                confluence_score=result.composite_score,
                                claude_confidence=int(result.composite_score),
                                strategies_agreed=strategies_agreed,
                            )

                            # AT-08: Store order IDs for this position
                            self._active_orders[position.id] = {
                                "main_order_id": order.broker_order_id,
                                "sl_order_id": order.sl_order_id,
                                "tp_order_id": order.tp_order_id,
                            }
                        else:
                            # Paper mode: use paper_trader directly with fresh price
                            position = paper_trader.open_position(
                                signal_log_id=signal_id,
                                symbol=symbol, timeframe=tf,
                                direction=result.direction,
                                regime=result.regime.value,
                                entry_price=current_price,
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

                        actual_price = current_price if broker is None else (order.filled_price or current_price)
                        logger.info("AUTO TRADE: %s %s @ %s (score %s) [broker=%s]",
                                    result.direction.value, symbol, actual_price,
                                    result.composite_score, config.broker)

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
                    logger.error("Scan error %s %s: %s", symbol, tf, e)
                    continue

    async def _check_and_learn_from_closed_positions(self):
        """
        Check if any positions were closed, then run Claude analysis on each.

        This is the LEARNING part — every closed trade teaches the agent something.
        """
        if not agent_config.learn_after_every_trade:
            return

        # Check for newly closed positions (AT-10: use set instead of monkey-patching)
        recently_closed = [
            p for p in paper_trader.closed_positions
            if p.id not in self._analyzed_trades
        ]

        for pos in recently_closed:
            self._analyzed_trades.add(pos.id)

            # AT-F06: Prune _analyzed_trades to avoid unbounded memory growth.
            # closed_positions is capped at 500, so keep only IDs that still
            # exist in that list. Beyond 600 entries, stale IDs are just waste.
            if len(self._analyzed_trades) > 600:
                recent_ids = {p.id for p in paper_trader.closed_positions[-500:]}
                self._analyzed_trades &= recent_ids

            # Run Claude analysis on this trade
            try:
                lesson = await analyze_closed_trade(pos)
                if lesson:
                    logger.info("Learned from %s trade: %s...", pos.symbol, lesson[:80])

                    if agent_config.notify_on_trade_close:
                        spec = get_instrument(pos.symbol)
                        pnl = spec.calculate_pnl(
                            pos.entry_price, pos.exit_price,
                            pos.position_size, pos.direction.value,
                        )
                        # TP-08 FIX: Neutral framing — no WIN/LOSS labels.
                        # Emotional framing ("WIN!!!" / "LOSS") triggers human
                        # intervention (revenge trades, premature strategy changes).
                        # Report facts only; let the system handle adaptation.
                        closed_count = len(paper_trader.closed_positions)
                        recent_n = min(closed_count, 20)
                        if recent_n > 0:
                            recent_wins = sum(
                                1 for p in paper_trader.closed_positions[-recent_n:]
                                if getattr(p, 'pnl', 0) > 0
                            )
                            wr_line = f"System WR: {recent_wins / recent_n * 100:.0f}% over last {recent_n} trades"
                        else:
                            wr_line = ""
                        await send_telegram(
                            f"*Trade closed:* `{pos.symbol}` {pos.direction.value}, "
                            f"P&L: `${pnl:.2f}`, exit: `{pos.exit_reason}`\n"
                            f"Duration: `{pos.duration_seconds // 60}m`\n"
                            f"{wr_line}\n\n"
                            f"*Lesson:* {lesson[:200]}"
                        )
            except Exception as e:
                logger.error("Learning error: %s", e)

    async def _run_daily_review(self):
        """Run daily performance review. Weight/blacklist adjustments weekly only."""
        from ..learning.analyzer import analyze_overall

        analysis = analyze_overall()
        overall = analysis.get("overall", {})

        # ML-20 FIX: Only adjust blacklists and weights on Sundays.
        # Daily adjustments cause overfitting to recent noise — a strategy
        # that lost 3 trades on Monday might win 5 on Tuesday. Weekly
        # cadence gives enough sample size for meaningful adaptation.
        now = datetime.now(timezone.utc)
        if now.weekday() == 6:  # Sunday only
            from ..learning.recommendations import get_dynamic_blacklist

            # Auto-update blacklists if permitted — APPLY them, don't just print
            if agent_config.can_update_blacklists:
                new_blacklist = get_dynamic_blacklist()
                if new_blacklist:
                    from ..backtester.engine import update_blacklist
                    for symbol, strategies in new_blacklist.items():
                        update_blacklist(symbol, strategies)
                    logger.info("Weekly adjustment: APPLIED blacklists for %s", list(new_blacklist.keys()))

            # Auto-adjust confluence weights if permitted — APPLY them
            if agent_config.can_adjust_weights:
                from ..learning.recommendations import recommend_weight_adjustments
                new_weights = recommend_weight_adjustments()
                if new_weights:
                    from ..confluence.scorer import update_regime_weights
                    update_regime_weights(new_weights)
                    logger.info("Weekly adjustment: APPLIED weight adjustments for %s", list(new_weights.keys()))

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

        logger.info("Running weekly review...")
        result = await generate_review()
        logger.info("Weekly review complete: %s", result.get('status'))

        # ML-16: Load optimized parameters and inject into strategy registry.
        # The optimizer produces per-instrument strategy params from walk-forward
        # analysis. Clearing the strategy cache forces re-creation with new params
        # next time strategies are requested via the registry.
        try:
            from ..learning.optimizer import get_optimal_params
            from ..strategies.registry import clear_strategy_cache
            # Check if optimal params exist for any active instrument
            for symbol in config.active_instruments:
                params = get_optimal_params(symbol)
                if params:
                    logger.info("ML-16: Found optimal params for %s: %s", symbol, list(params.keys()))
            clear_strategy_cache()
        except Exception as e:
            logger.error("Optimizer loading error: %s", e)

    async def _reconcile_positions(self):
        """
        AT-04: Compare local paper_trader positions with exchange positions.

        Runs every 5 minutes when broker is not 'paper'. Detects mismatches
        between what we think is open locally and what the exchange reports.
        Detection and logging only — no auto-correction for safety.
        """
        try:
            # Reuse the shared broker instance (AT-09)
            broker = await self._get_broker()
            if not broker:
                return

            exchange_positions = await broker.get_positions()
            exchange_symbols = {p.symbol for p in exchange_positions}

            # CQ-13 FIX: Normalize local symbols to exchange format for comparison.
            # Local uses BTCUSD, exchange uses BTCUSDT — they never matched before,
            # causing reconciliation to ALWAYS report false mismatches.
            local_positions = list(paper_trader.positions.values())
            local_symbols_mapped = set()
            for pos in local_positions:
                try:
                    from ..execution.binance_testnet import _map_symbol
                    local_symbols_mapped.add(_map_symbol(pos.symbol))
                except (ValueError, ImportError):
                    local_symbols_mapped.add(pos.symbol)

            # Check for positions on exchange but not tracked locally
            orphaned = exchange_symbols - local_symbols_mapped
            if orphaned:
                logger.warning("RECONCILIATION MISMATCH: exchange has positions not tracked locally: %s", orphaned)
                # AT-26: Send Telegram alert on mismatch (not just stdout)
                await send_telegram(
                    f"RECONCILIATION ALERT: Exchange has orphaned positions: {orphaned}"
                )

            # Check for local positions not on exchange
            missing = local_symbols_mapped - exchange_symbols
            if missing:
                logger.warning("RECONCILIATION MISMATCH: local positions not found on exchange: %s", missing)
                await send_telegram(
                    f"RECONCILIATION ALERT: Local positions not on exchange: {missing}"
                )

            if not orphaned and not missing:
                logger.info("Reconciliation OK: %d positions in sync", len(local_symbols_mapped))

        except Exception as e:
            logger.error("Reconciliation error: %s", e)

    async def _detect_exchange_fills(self):
        """
        AT-F01: Detect exchange-side SL/TP fills and close local positions.

        When using a real broker, the exchange executes SL/TP orders server-side.
        The autonomous trader's update_positions() only runs in paper mode, so
        exchange-managed fills go undetected. This method compares local positions
        with the exchange and closes any local position whose symbol is no longer
        open on the exchange — meaning the exchange already closed it (SL/TP hit).

        This differs from _reconcile_positions() which only DETECTS mismatches.
        This method RESOLVES them by closing the stale local positions.
        """
        try:
            broker = await self._get_broker()
            if not broker:
                return

            exchange_positions = await broker.get_positions()
            exchange_symbols = {p.symbol for p in exchange_positions}

            # Check each local position against exchange state
            local_positions = list(paper_trader.positions.values())
            for pos in local_positions:
                # Normalize local symbol to exchange format for comparison
                try:
                    from ..execution.binance_testnet import _map_symbol
                    mapped_symbol = _map_symbol(pos.symbol)
                except (ValueError, ImportError):
                    mapped_symbol = pos.symbol

                if mapped_symbol not in exchange_symbols:
                    # Exchange no longer has this position — it was closed
                    # (SL/TP hit on the exchange side). Close it locally.
                    # Use the last known current_price as exit approximation.
                    # The position's current_price gets updated during reconciliation.
                    exit_price = pos.current_price if pos.current_price > 0 else pos.entry_price

                    logger.info("AT-F01: Exchange closed %s (pos %s) — SL/TP filled on exchange. "
                               "Closing locally at %s", pos.symbol, pos.id, exit_price)

                    paper_trader.close_position(
                        pos.id,
                        reason="exchange_closed",
                        exit_price=exit_price,
                    )

                    # Clean up tracked order IDs for this position
                    self._active_orders.pop(pos.id, None)

                    # Notify via Telegram
                    await send_telegram(
                        f"*Exchange SL/TP Fill Detected*\n\n"
                        f"Symbol: `{pos.symbol}`\n"
                        f"Direction: `{pos.direction.value}`\n"
                        f"Entry: `{pos.entry_price}`\n"
                        f"Exit (approx): `{exit_price}`\n"
                        f"Position closed locally to sync with exchange."
                    )

        except Exception as e:
            logger.error("AT-F01 exchange fill detection error: %s", e)

    def get_status(self) -> dict:
        """Get agent status for the dashboard."""
        return {
            "running": self._running,
            "mode": agent_config.mode.value,
            "config": agent_config.to_dict(),
            "daily_trades": self._daily_trades,
            "open_positions": paper_trader.open_count,
            "total_closed": len(paper_trader.closed_positions),
            "broker": config.broker,
            "broker_connected": self._broker.is_connected if self._broker else (config.broker == "paper"),
            "active_orders": self._active_orders,
        }


# Singleton
autonomous_trader = AutonomousTrader()
