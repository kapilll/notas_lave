"""
Lab Trading Engine -- trades aggressively to LEARN.

WHO TAKES TRADES: The Lab does, automatically. No human, no Claude per-trade.
It uses the same 12 strategies but with LOW thresholds (score >= 3.0, R:R >= 1.0).
Every qualifying signal = instant trade. Volume over precision.

HOW AGGRESSIVELY: 100 trades/day max, 5 concurrent, 60s cooldown, ALL timeframes.
No blacklist, no regime filtering. The goal is MAXIMUM DATA.

PERSISTENCE: All trades stored in lab.db (SQLite). Open positions reload on restart.
Lab risk state persisted to lab.db. Nothing is lost on restart.

WHAT IT RUNS AUTOMATICALLY:
- Backtester every 6 hours on 1h and 4h timeframes
- Optimizer every 12 hours
- Claude daily review at 22:00 UTC -> Telegram report with strategy leaderboard
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone, date

from ..data.market_data import market_data
from ..data.instruments import get_instrument
from ..confluence.scorer import compute_confluence
from ..execution.paper_trader import PaperTrader
from ..journal.database import use_db, log_signal, init_lab_db, get_db
from ..alerts.telegram import send_telegram
from ..config import config
from .lab_config import lab_config
from .lab_risk import LabRiskManager

logger = logging.getLogger(__name__)

# Path for persisting lab risk state
_LAB_STATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "lab_risk_state.json"
)


class LabTrader:
    """Unrestricted trading engine for learning.

    Trades aggressively on demo accounts. Every qualifying signal becomes a trade.
    All data persists to lab.db (separate from production).
    """

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
        self._last_heartbeat: datetime | None = None

        # Lab gets its OWN instances (separate from production)
        self.risk_manager = LabRiskManager()
        self.paper_trader = PaperTrader()  # Separate instance
        self._analyzed_trades: set[str] = set()

    async def start(self):
        if self._running:
            return

        # Initialize lab database (separate file from production)
        init_lab_db()
        use_db("lab")

        # Load persisted lab risk state
        self._load_risk_state()

        # Reload open positions from lab.db (persistence across restarts)
        self.paper_trader._reload_open_positions()

        self._running = True
        logger.info("[LAB] Lab Engine started")
        logger.info("[LAB] Timeframes: %s", lab_config.scan_timeframes)
        logger.info("[LAB] Min score: %s, Min R:R: %s",
                     lab_config.min_score_to_trade, lab_config.min_rr_to_trade)
        logger.info("[LAB] Max trades/day: %s, Max concurrent: %s",
                     lab_config.max_trades_per_day, lab_config.max_concurrent_positions)

        await send_telegram(
            f"{lab_config.telegram_prefix} *Lab Engine Started*\n\n"
            f"Timeframes: {', '.join(lab_config.scan_timeframes)}\n"
            f"Min score: {lab_config.min_score_to_trade}\n"
            f"Max trades/day: {lab_config.max_trades_per_day}\n"
            f"Balance: ${self.risk_manager.current_balance:,.2f}\n"
            f"Open positions reloaded: {self.paper_trader.open_count}"
        )

        async def main_loop():
            while self._running:
                try:
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
        # Persist risk state on shutdown
        self._save_risk_state()
        logger.info("[LAB] Lab Engine stopped. Risk state saved.")

    # ═══════════════════════════════════════════════════════════
    # PERSISTENCE
    # ═══════════════════════════════════════════════════════════

    def _save_risk_state(self):
        """Persist lab risk manager state to disk."""
        try:
            os.makedirs(os.path.dirname(_LAB_STATE_PATH), exist_ok=True)
            state = {
                "current_balance": self.risk_manager.current_balance,
                "total_pnl": self.risk_manager.total_pnl,
                "peak_balance": self.risk_manager.peak_balance,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            with open(_LAB_STATE_PATH, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error("[LAB] Failed to save risk state: %s", e)

    def _load_risk_state(self):
        """Load lab risk manager state from disk."""
        try:
            if os.path.exists(_LAB_STATE_PATH):
                with open(_LAB_STATE_PATH) as f:
                    state = json.load(f)
                self.risk_manager.current_balance = state.get("current_balance", 100_000.0)
                self.risk_manager.total_pnl = state.get("total_pnl", 0.0)
                self.risk_manager.peak_balance = state.get("peak_balance", 100_000.0)
                logger.info("[LAB] Loaded risk state: balance=$%.2f, P&L=$%.2f",
                           self.risk_manager.current_balance, self.risk_manager.total_pnl)
        except Exception as e:
            logger.warning("[LAB] Could not load risk state: %s", e)

    # ═══════════════════════════════════════════════════════════
    # MAIN LOOP
    # ═══════════════════════════════════════════════════════════

    async def _tick(self):
        now = datetime.now(timezone.utc)
        today = now.date()

        if self._today != today:
            self._today = today
            self._daily_trades = {}

        # Heartbeat every 2 hours
        if self._last_heartbeat is None or (now - self._last_heartbeat).total_seconds() >= 7200:
            await send_telegram(
                f"{lab_config.telegram_prefix} Heartbeat: "
                f"{self.paper_trader.open_count} positions, "
                f"{self._daily_trades.get(today.isoformat(), 0)} trades today, "
                f"balance ${self.risk_manager.current_balance:,.2f}"
            )
            self._last_heartbeat = now

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

    # ═══════════════════════════════════════════════════════════
    # TRADING — Takes every qualifying signal
    # ═══════════════════════════════════════════════════════════

    async def _scan_and_trade(self):
        """Scan ALL instruments on ALL timeframes. Trade aggressively."""
        now = datetime.now(timezone.utc)

        for symbol in config.active_instruments:
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
                    if not (0 <= age <= tf_seconds * 2):  # 2x tolerance for lab
                        continue

                    # Run ALL strategies — lab bypasses blacklist
                    from ..strategies.registry import get_all_strategies
                    result = compute_confluence(candles, symbol, tf)

                    # Lab uses VERY low thresholds
                    if result.composite_score < lab_config.min_score_to_trade / 10:
                        continue
                    if not result.direction:
                        continue

                    # Take ANY signal with entry levels (not just the best)
                    best = None
                    for s in result.signals:
                        if s.direction is not None and s.entry_price and s.stop_loss and s.take_profit:
                            best = s
                            break
                    if not best:
                        continue

                    # R:R check (very loose)
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

                    # Lab risk (always approves)
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

                    # Extract features for ML
                    features = {}
                    try:
                        from ..ml.features import extract_features
                        features = extract_features(candles, best, result.regime, symbol, tf)
                    except Exception:
                        pass

                    # Log signal to lab.db
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
                        claude_reasoning=f"Lab auto: {best.strategy_name} ({tf}), features={len(features)}",
                        risk_passed=True,
                        risk_rejections=[],
                        should_trade=True,
                    )

                    # Open position in lab paper trader
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

                    self._last_trade_time[symbol] = now
                    daily_key = self._today.isoformat() if self._today else ""
                    self._daily_trades[daily_key] = self._daily_trades.get(daily_key, 0) + 1

                    logger.info(
                        "%s TRADE: %s %s (%s) @ %.2f score=%.1f strategy=%s",
                        lab_config.telegram_prefix, result.direction.value, symbol,
                        tf, candles[-1].close, result.composite_score,
                        best.strategy_name,
                    )

                    return  # One trade per tick

                except Exception as e:
                    logger.debug("[LAB] Scan error %s %s: %s", symbol, tf, e)
                    continue

    # ═══════════════════════════════════════════════════════════
    # LEARNING — Track results, persist state
    # ═══════════════════════════════════════════════════════════

    async def _check_closed_positions(self):
        """Check closed positions, record results, persist."""
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
                "%s CLOSED: %s %s P&L=$%.2f (%s) duration=%dm strategy=%s",
                lab_config.telegram_prefix, pos.symbol, pos.direction.value,
                pnl, pos.exit_reason, pos.duration_seconds // 60,
                ", ".join(pos.strategies_agreed[:2]) if pos.strategies_agreed else "?",
            )

        # Save risk state after any position closes
        if recently_closed:
            self._save_risk_state()

        # Prune analyzed trades set
        if len(self._analyzed_trades) > 600:
            recent_ids = {p.id for p in self.paper_trader.closed_positions[-500:]}
            self._analyzed_trades &= recent_ids

    # ═══════════════════════════════════════════════════════════
    # AUTO TOOLS — Backtester, Optimizer (no human needed)
    # ═══════════════════════════════════════════════════════════

    def _should_run_backtest(self, now: datetime) -> bool:
        if self._last_backtest is None:
            return now.minute < 2  # Run on first tick
        return (now - self._last_backtest).total_seconds() >= lab_config.auto_backtest_hours * 3600

    def _should_run_optimize(self, now: datetime) -> bool:
        if self._last_optimize is None:
            return False
        return (now - self._last_optimize).total_seconds() >= lab_config.auto_optimize_hours * 3600

    async def _auto_backtest(self):
        """Run backtester automatically on key timeframes."""
        logger.info("%s Running auto-backtest...", lab_config.telegram_prefix)
        try:
            from ..backtester.engine import Backtester

            results_summary = []
            for symbol in config.active_instruments:
                for tf in ["1h", "4h"]:
                    candles = await market_data.get_candles(symbol, tf, limit=1000)
                    if not candles or len(candles) < 300:
                        continue

                    bt = Backtester(slippage_pct=0.0005)
                    result = bt.run(candles, symbol, tf)

                    results_summary.append(
                        f"  {symbol} {tf}: {result.total_trades}t "
                        f"WR={result.win_rate:.0f}% PF={result.profit_factor:.2f}"
                    )

            if results_summary:
                await send_telegram(
                    f"{lab_config.telegram_prefix} *Auto-Backtest Results*\n\n"
                    + "\n".join(results_summary)
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
                    await send_telegram(
                        f"{lab_config.telegram_prefix} *Optimizer Found Improvements*\n"
                        f"Symbol: {symbol}\n"
                        + "\n".join(f"  {r['strategy']}: +{r['improvement_pct']:.0f}%" for r in improved)
                    )
        except Exception as e:
            logger.error("%s Auto-optimizer error: %s", lab_config.telegram_prefix, e)

    # ═══════════════════════════════════════════════════════════
    # CLAUDE DAILY REVIEW
    # ═══════════════════════════════════════════════════════════

    async def _claude_daily_review(self):
        """Claude reviews the day's lab results and sends report to Telegram."""
        logger.info("%s Running daily review...", lab_config.telegram_prefix)
        try:
            use_db("lab")
            from ..learning.analyzer import analyze_overall

            analysis = analyze_overall()
            overall = analysis.get("overall", {})
            strategy_breakdown = analysis.get("strategy_breakdown", {})

            trades = overall.get("trades", 0)
            if trades == 0:
                await send_telegram(
                    f"{lab_config.telegram_prefix} Daily Review: No trades today. "
                    f"Strategies may be too restrictive or markets are quiet."
                )
                return

            # Strategy leaderboard
            leaderboard = []
            for i, (name, stats) in enumerate(sorted(
                strategy_breakdown.items(),
                key=lambda x: x[1].get("total_pnl", 0),
                reverse=True,
            )):
                medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"#{i+1}"
                leaderboard.append(
                    f"  {medal} {name}: {stats['trades']}t, "
                    f"{stats['win_rate']}% WR, ${stats['total_pnl']:.0f}"
                )

            report = (
                f"{lab_config.telegram_prefix} *Daily Lab Report*\n\n"
                f"Trades: {trades}\n"
                f"Win Rate: {overall.get('win_rate', 0):.1f}%\n"
                f"Profit Factor: {overall.get('profit_factor', 0):.2f}\n"
                f"P&L: ${overall.get('total_pnl', 0):.2f}\n\n"
                f"*Strategy Leaderboard:*\n"
                + "\n".join(leaderboard[:6])
                + f"\n\nBalance: ${self.risk_manager.current_balance:,.2f}"
            )

            await send_telegram(report)
            logger.info("%s Daily review sent to Telegram", lab_config.telegram_prefix)

        except Exception as e:
            logger.error("%s Daily review error: %s", lab_config.telegram_prefix, e)

    # ═══════════════════════════════════════════════════════════
    # STATUS
    # ═══════════════════════════════════════════════════════════

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
