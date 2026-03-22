"""
Lab Trading Engine -- trades aggressively to LEARN.

Like AutonomousTrader but:
- Uses LabRiskManager (never blocks)
- Uses separate lab.db
- Lower score thresholds, more trades
- Tests ALL timeframes
- No blacklist filtering
- Runs backtester + optimizer automatically
- Claude reviews daily

The Lab's only purpose is generating learning data.
Every trade teaches something. Volume over precision.
"""

import asyncio
import logging
from datetime import datetime, timezone, date

from ..data.market_data import market_data
from ..data.instruments import get_instrument
from ..confluence.scorer import compute_confluence
from ..execution.paper_trader import PaperTrader
from ..journal.database import use_db, log_signal, init_lab_db
from ..alerts.telegram import send_telegram
from ..config import config
from .lab_config import lab_config
from .lab_risk import LabRiskManager

logger = logging.getLogger(__name__)


class LabTrader:
    """Unrestricted trading engine for learning."""

    _TF_SECONDS = {
        "1m": 60, "3m": 180, "5m": 300, "15m": 900,
        "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400,
    }

    def __init__(self):
        self._running = False
        self._task = None
        self._daily_trades: dict[str, int] = {}
        self._today: date | None = None
        self._last_trade_time: dict[str, datetime] = {}
        self._last_backtest: datetime | None = None
        self._last_optimize: datetime | None = None
        self._last_daily_review: date | None = None

        # Lab gets its OWN instances (separate from production)
        self.risk_manager = LabRiskManager()
        self.paper_trader = PaperTrader()  # Separate instance, not the singleton
        self._analyzed_trades: set[str] = set()

    async def start(self):
        if self._running:
            return

        # Initialize lab database
        init_lab_db()
        use_db("lab")

        self._running = True
        logger.info("[LAB] Lab Engine started")
        logger.info("[LAB] Timeframes: %s", lab_config.scan_timeframes)
        logger.info("[LAB] Min score: %s, Min R:R: %s",
                     lab_config.min_score_to_trade, lab_config.min_rr_to_trade)
        logger.info("[LAB] Max trades/day: %s", lab_config.max_trades_per_day)

        await send_telegram(
            f"{lab_config.telegram_prefix} *Lab Engine Started*\n\n"
            f"Timeframes: {', '.join(lab_config.scan_timeframes)}\n"
            f"Min score: {lab_config.min_score_to_trade}\n"
            f"Max trades/day: {lab_config.max_trades_per_day}\n"
            f"Blacklist: {'OFF' if not lab_config.use_blacklist else 'ON'}"
        )

        async def main_loop():
            while self._running:
                try:
                    # Switch to lab DB context for all operations
                    use_db("lab")
                    await self._tick()
                except Exception as e:
                    logger.error("[LAB] Tick error: %s", e)
                await asyncio.sleep(lab_config.scan_interval_seconds)

        self._task = asyncio.create_task(main_loop())

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("[LAB] Lab Engine stopped")

    async def _tick(self):
        now = datetime.now(timezone.utc)
        today = now.date()

        if self._today != today:
            self._today = today
            self._daily_trades = {}

        # Check and learn from closed positions
        await self._check_closed_positions()

        # Auto-run backtester
        if self._should_run_backtest(now):
            await self._auto_backtest()
            self._last_backtest = now

        # Auto-run optimizer
        if self._should_run_optimize(now):
            await self._auto_optimize()
            self._last_optimize = now

        # Daily Claude review
        if self._last_daily_review != today and now.hour >= lab_config.daily_review_hour:
            await self._claude_daily_review()
            self._last_daily_review = today

        # Check trade limits
        daily_key = today.isoformat()
        if self._daily_trades.get(daily_key, 0) >= lab_config.max_trades_per_day:
            return

        if self.paper_trader.open_count >= lab_config.max_concurrent_positions:
            return

        await self._scan_and_trade()

    async def _scan_and_trade(self):
        """Scan ALL instruments on ALL timeframes. Trade aggressively."""
        now = datetime.now(timezone.utc)

        for symbol in config.active_instruments:
            # Cooldown per symbol
            last = self._last_trade_time.get(symbol)
            if last and (now - last).total_seconds() < lab_config.cooldown_seconds:
                continue

            for tf in lab_config.scan_timeframes:
                try:
                    candles = await market_data.get_candles(symbol, tf, limit=250)
                    if not candles or len(candles) < 50:
                        continue

                    # Candle freshness check
                    tf_seconds = self._TF_SECONDS.get(tf, 300)
                    age = (now - candles[-1].timestamp).total_seconds()
                    if not (0 <= age <= tf_seconds):
                        continue

                    result = compute_confluence(candles, symbol, tf)

                    # Lab uses lower thresholds
                    if result.composite_score < lab_config.min_score_to_trade / 10:
                        continue
                    if not result.direction:
                        continue

                    best = max(
                        (s for s in result.signals if s.direction is not None),
                        key=lambda s: s.score, default=None,
                    )
                    if not best or not best.entry_price or not best.stop_loss or not best.take_profit:
                        continue

                    # R:R check (looser)
                    risk = abs(best.entry_price - best.stop_loss)
                    reward = abs(best.take_profit - best.entry_price)
                    if risk <= 0 or (reward / risk) < lab_config.min_rr_to_trade:
                        continue

                    # Position sizing
                    spec = get_instrument(symbol)
                    pos_size = spec.calculate_position_size(
                        best.entry_price, best.stop_loss,
                        self.risk_manager.current_balance,
                        lab_config.risk_per_trade_pct,
                    )
                    if pos_size <= 0:
                        continue

                    # Lab risk manager (always approves)
                    from ..data.models import TradeSetup
                    setup = TradeSetup(
                        symbol=symbol, timeframe=tf,
                        direction=result.direction,
                        entry_price=best.entry_price,
                        stop_loss=best.stop_loss,
                        take_profit=best.take_profit,
                        position_size=pos_size,
                        risk_reward_ratio=reward / risk,
                        confluence_score=result.composite_score,
                        regime=result.regime,
                    )
                    self.risk_manager.validate_trade(setup)

                    # Log signal
                    strategies_agreed = [
                        s.strategy_name for s in result.signals
                        if s.direction == result.direction
                    ]
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
                        claude_action="LAB_AUTO",
                        claude_confidence=int(result.composite_score),
                        claude_reasoning=f"Lab auto-trade: {best.strategy_name}",
                        risk_passed=True,
                        risk_rejections=[],
                        should_trade=True,
                    )

                    # Open position
                    position = self.paper_trader.open_position(
                        signal_log_id=signal_id,
                        symbol=symbol, timeframe=tf,
                        direction=result.direction,
                        regime=result.regime.value,
                        entry_price=candles[-1].close,
                        stop_loss=best.stop_loss,
                        take_profit=best.take_profit,
                        position_size=pos_size,
                        confluence_score=result.composite_score,
                        claude_confidence=int(result.composite_score),
                        strategies_agreed=strategies_agreed,
                    )

                    # Track
                    self._last_trade_time[symbol] = now
                    daily_key = self._today.isoformat() if self._today else ""
                    self._daily_trades[daily_key] = self._daily_trades.get(daily_key, 0) + 1

                    logger.info(
                        "%s TRADE: %s %s (%s) @ %s score=%s strategy=%s",
                        lab_config.telegram_prefix, result.direction.value, symbol,
                        tf, candles[-1].close, result.composite_score,
                        best.strategy_name,
                    )

                    return  # One trade per tick

                except Exception as e:
                    logger.debug("[LAB] Scan error %s %s: %s", symbol, tf, e)
                    continue

    async def _check_closed_positions(self):
        """Check for closed positions, record results, learn."""
        # Update prices for paper positions
        await self.paper_trader.update_positions()

        recently_closed = [
            p for p in self.paper_trader.closed_positions
            if p.id not in self._analyzed_trades
        ]

        for pos in recently_closed:
            self._analyzed_trades.add(pos.id)
            spec = get_instrument(pos.symbol)
            pnl = spec.calculate_pnl(
                pos.entry_price, pos.exit_price,
                pos.position_size, pos.direction.value,
            )
            self.risk_manager.record_trade_result(pnl)

            logger.info(
                "%s CLOSED: %s %s P&L=$%.2f (%s) duration=%dm",
                lab_config.telegram_prefix, pos.symbol, pos.direction.value,
                pnl, pos.exit_reason, pos.duration_seconds // 60,
            )

        # Prune analyzed trades set
        if len(self._analyzed_trades) > 600:
            recent_ids = {p.id for p in self.paper_trader.closed_positions[-500:]}
            self._analyzed_trades &= recent_ids

    def _should_run_backtest(self, now: datetime) -> bool:
        if self._last_backtest is None:
            return now.hour % lab_config.auto_backtest_hours == 0 and now.minute < 1
        return (now - self._last_backtest).total_seconds() >= lab_config.auto_backtest_hours * 3600

    def _should_run_optimize(self, now: datetime) -> bool:
        if self._last_optimize is None:
            return False  # Don't optimize on first tick
        return (now - self._last_optimize).total_seconds() >= lab_config.auto_optimize_hours * 3600

    async def _auto_backtest(self):
        """Run backtester automatically."""
        logger.info("%s Running auto-backtest...", lab_config.telegram_prefix)
        try:
            from ..backtester.engine import Backtester

            for symbol in config.active_instruments:
                for tf in ["1h", "4h"]:  # Test key timeframes
                    candles = await market_data.get_candles(symbol, tf, limit=1000)
                    if not candles or len(candles) < 300:
                        continue

                    bt = Backtester(slippage_pct=0.0005)
                    result = bt.run(candles, symbol, tf)

                    logger.info(
                        "%s Backtest %s %s: %dt WR=%.1f%% PF=%.2f P&L=$%.2f",
                        lab_config.telegram_prefix, symbol, tf,
                        result.total_trades, result.win_rate,
                        result.profit_factor, result.net_pnl,
                    )
        except Exception as e:
            logger.error("%s Auto-backtest error: %s", lab_config.telegram_prefix, e)

    async def _auto_optimize(self):
        """Run optimizer automatically."""
        logger.info("%s Running auto-optimizer...", lab_config.telegram_prefix)
        try:
            from ..learning.optimizer import optimize_all_strategies, save_results

            for symbol in config.active_instruments:
                candles = await market_data.get_candles(symbol, "1h", limit=1000)
                if not candles or len(candles) < 300:
                    continue

                results = optimize_all_strategies(candles, symbol, "1h")
                save_results(symbol, results)

                improved = [r for r in results if r.get("improvement_pct", 0) > 5]
                if improved:
                    logger.info(
                        "%s Optimizer found improvements for %s: %s",
                        lab_config.telegram_prefix, symbol,
                        [r["strategy"] for r in improved],
                    )
        except Exception as e:
            logger.error("%s Auto-optimizer error: %s", lab_config.telegram_prefix, e)

    async def _claude_daily_review(self):
        """Claude reviews the day's lab results and sends report."""
        logger.info("%s Running daily Claude review...", lab_config.telegram_prefix)
        try:
            use_db("lab")
            from ..learning.analyzer import analyze_overall

            analysis = analyze_overall()
            overall = analysis.get("overall", {})
            strategy_breakdown = analysis.get("strategy_breakdown", {})

            trades = overall.get("trades", 0)
            if trades == 0:
                await send_telegram(f"{lab_config.telegram_prefix} Daily Review: No trades today.")
                return

            # Build strategy leaderboard
            leaderboard = []
            for name, stats in sorted(
                strategy_breakdown.items(),
                key=lambda x: x[1].get("total_pnl", 0),
                reverse=True,
            ):
                leaderboard.append(
                    f"  {name}: {stats['trades']}t, "
                    f"{stats['win_rate']}% WR, ${stats['total_pnl']:.0f}"
                )

            report = (
                f"{lab_config.telegram_prefix} *Daily Lab Report*\n\n"
                f"Trades: {trades}\n"
                f"Win Rate: {overall.get('win_rate', 0):.1f}%\n"
                f"Profit Factor: {overall.get('profit_factor', 0):.2f}\n"
                f"P&L: ${overall.get('total_pnl', 0):.2f}\n\n"
                f"*Strategy Leaderboard:*\n"
                + "\n".join(leaderboard[:5])
                + f"\n\nBalance: ${self.risk_manager.current_balance:.2f}"
            )

            await send_telegram(report)
            logger.info("%s Daily review sent to Telegram", lab_config.telegram_prefix)

        except Exception as e:
            logger.error("%s Daily review error: %s", lab_config.telegram_prefix, e)

    def get_status(self) -> dict:
        return {
            "mode": "lab",
            "running": self._running,
            "config": lab_config.to_dict(),
            "risk": self.risk_manager.get_status(),
            "open_positions": self.paper_trader.open_count,
            "total_closed": len(self.paper_trader.closed_positions),
            "daily_trades": self._daily_trades,
        }
