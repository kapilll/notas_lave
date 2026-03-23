"""v2 Lab Engine — learns from every trade, gets smarter over time.

Philosophy: Trade with conviction, not spray-and-pray.
- Require at least 2 strategies to agree (confluence)
- Favor trades with good R:R (1.5+)
- Grade every closed trade (A-F)
- Track what works per strategy/instrument/timeframe
- Adapt: boost strategies that win, fade strategies that lose
"""

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone

from ..core.events import TradeClosed, TradeOpened
from ..core.models import Direction, Signal, TradeSetup
from ..core.ports import IBroker, ITradeJournal
from ..engine.event_bus import EventBus
from ..engine.pnl import PnLResult, PnLService

logger = logging.getLogger(__name__)

# Balanced settings — enough trades to learn, selective enough to be meaningful
LAB_INSTRUMENTS = [
    "BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "BNBUSD", "DOGEUSD",
    "ADAUSD", "AVAXUSD", "LINKUSD", "DOTUSD", "LTCUSD", "NEARUSD",
    "SUIUSD", "ARBUSD", "PEPEUSD", "WIFUSD", "FTMUSD", "ATOMUSD",
]
LAB_TIMEFRAMES = ["5m", "15m", "1h", "4h"]
MIN_SCORE = 3.5           # Higher bar since single-strategy allowed
MIN_RR = 1.5              # Only favorable risk/reward
MIN_AGREE = 1             # Single strong signal OK (score compensates)
MAX_CONCURRENT = 5        # Focus on fewer, better trades
SCAN_INTERVAL = 45        # Scan every 45s
COOLDOWN_SECONDS = 120    # 2 min cooldown per symbol (avoid overtrading)
RISK_PER_TRADE = 0.01     # 1% of balance risked per trade


class LabEngine:
    """Lab engine that learns from every trade.

    Tracks per-strategy and per-instrument performance.
    Grades trades on close. Adjusts over time.
    """

    def __init__(
        self,
        broker: IBroker,
        journal: ITradeJournal,
        bus: EventBus,
        pnl: PnLService,
    ) -> None:
        self.broker = broker
        self.journal = journal
        self.bus = bus
        self.pnl = pnl
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_trade: dict[str, datetime] = {}

        # Learning state — tracks what works
        self._strategy_wins: dict[str, int] = defaultdict(int)
        self._strategy_losses: dict[str, int] = defaultdict(int)
        self._instrument_wins: dict[str, int] = defaultdict(int)
        self._instrument_losses: dict[str, int] = defaultdict(int)
        self._total_trades = 0
        self._total_wins = 0

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return

        if not self.broker.is_connected:
            connected = await self.broker.connect()
            if not connected:
                logger.error("[LAB] Could not connect to broker")
                return

        # Disable volume checks for lab
        from ..strategies.base import BaseStrategy
        BaseStrategy.set_volume_check(False)

        self._running = True
        balance = await self.broker.get_balance()
        logger.info("[LAB] Started — broker=%s balance=%.2f %s",
                     self.broker.name, balance.total, balance.currency)
        logger.info("[LAB] Mode: LEARN — score>=%.1f rr>=%.1f agree>=%d max=%d interval=%ds",
                     MIN_SCORE, MIN_RR, MIN_AGREE, MAX_CONCURRENT, SCAN_INTERVAL)

        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
        self._log_learning_summary()
        logger.info("[LAB] Stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.error("[LAB] Tick error: %s", e)
            await asyncio.sleep(SCAN_INTERVAL)

    async def _tick(self) -> None:
        from ..data.market_data import market_data
        from ..confluence.scorer import compute_confluence

        market_data.max_stale_minutes = 0
        open_count = len(self.journal.get_open_trades())
        scanned = 0
        trades_placed = 0

        for symbol in LAB_INSTRUMENTS:
            if open_count >= MAX_CONCURRENT:
                break

            # Skip symbols that are on cooldown
            last = self._last_trade.get(symbol)
            if last and (datetime.now(timezone.utc) - last).total_seconds() < COOLDOWN_SECONDS:
                continue

            # Skip instruments with terrible track record (>5 trades, <30% WR)
            sym_total = self._instrument_wins[symbol] + self._instrument_losses[symbol]
            if sym_total >= 5:
                sym_wr = self._instrument_wins[symbol] / sym_total
                if sym_wr < 0.30:
                    continue  # This instrument isn't working for us — skip it

            for tf in LAB_TIMEFRAMES:
                try:
                    candles = await market_data.get_candles(symbol, tf, limit=250)
                    if not candles or len(candles) < 50:
                        continue

                    result = compute_confluence(candles, symbol, tf)
                    scanned += 1

                    # Filters — trade with conviction
                    if result.direction is None:
                        continue
                    if result.composite_score < MIN_SCORE:
                        continue
                    if result.agreeing_strategies < MIN_AGREE:
                        continue

                    # Get best signal with levels
                    best = max(
                        (s for s in result.signals if s.direction == result.direction),
                        key=lambda s: s.score,
                        default=None,
                    )
                    if not best or not best.entry_price or not best.stop_loss or not best.take_profit:
                        continue

                    # R:R check
                    risk = abs(best.entry_price - best.stop_loss)
                    reward = abs(best.take_profit - best.entry_price)
                    if risk <= 0 or reward / risk < MIN_RR:
                        continue

                    # Position sizing — 1% risk
                    balance = await self.broker.get_balance()
                    risk_amount = balance.total * RISK_PER_TRADE
                    pos_size = risk_amount / risk if risk > 0 else 0.001
                    pos_size = max(0.001, min(pos_size, balance.total / best.entry_price * 0.05))
                    pos_size = round(pos_size, 6)

                    setup = TradeSetup(
                        symbol=symbol,
                        direction=result.direction,
                        entry_price=best.entry_price,
                        stop_loss=best.stop_loss,
                        take_profit=best.take_profit,
                        position_size=pos_size,
                        confluence_score=result.composite_score,
                    )

                    trade_id = await self.execute_trade(setup)
                    self._last_trade[symbol] = datetime.now(timezone.utc)
                    open_count += 1
                    trades_placed += 1

                    logger.info(
                        "[LAB] TRADE #%d: %s %s %s score=%.1f agree=%d/%d rr=%.1f size=%.4f",
                        trade_id, result.direction.value, symbol, tf,
                        result.composite_score, result.agreeing_strategies,
                        result.total_strategies, reward / risk, pos_size,
                    )
                    break

                except Exception as e:
                    logger.debug("[LAB] %s/%s error: %s", symbol, tf, e)

        if trades_placed > 0 or scanned > 0:
            wr = (self._total_wins / self._total_trades * 100) if self._total_trades > 0 else 0
            logger.info(
                "[LAB] Tick: scanned=%d placed=%d open=%d | lifetime: %d trades, %.0f%% WR",
                scanned, trades_placed, open_count, self._total_trades, wr,
            )

        await self._check_positions()

    async def _check_positions(self) -> None:
        from ..data.market_data import market_data

        for trade in self.journal.get_open_trades():
            symbol = trade.get("symbol", "")
            trade_id = trade.get("trade_id", 0)
            sl = trade.get("stop_loss", 0)
            tp = trade.get("take_profit", 0)
            direction = trade.get("direction", "LONG")

            try:
                candles = await market_data.get_candles(symbol, "1m", limit=3)
                if not candles:
                    continue

                price = candles[-1].close
                hit = None

                if direction == "LONG":
                    if sl > 0 and price <= sl:
                        hit = "sl_hit"
                    elif tp > 0 and price >= tp:
                        hit = "tp_hit"
                elif direction == "SHORT":
                    if sl > 0 and price >= sl:
                        hit = "sl_hit"
                    elif tp > 0 and price <= tp:
                        hit = "tp_hit"

                if hit:
                    await self.close_trade(trade_id, exit_price=price, reason=hit)

            except Exception as e:
                logger.debug("[LAB] Monitor %s error: %s", symbol, e)

    async def execute_trade(self, setup: TradeSetup) -> int:
        signal = Signal(
            strategy_name="lab_confluence",
            direction=setup.direction,
            score=setup.confluence_score,
        )
        trade_id = self.journal.record_signal(signal)
        self.journal.record_open(trade_id, setup)

        result = await self.broker.place_order(setup)
        if not result.success:
            logger.warning("[LAB] Broker rejected trade %d: %s", trade_id, result.error)

        now = datetime.now(timezone.utc)
        await self.bus.publish(TradeOpened(
            trade_id=str(trade_id),
            symbol=setup.symbol,
            direction=setup.direction.value,
            entry_price=setup.entry_price,
            position_size=setup.position_size,
            stop_loss=setup.stop_loss,
            take_profit=setup.take_profit,
            timestamp=now,
        ))
        return trade_id

    async def close_trade(
        self, trade_id: int, exit_price: float, reason: str,
    ) -> None:
        open_trades = self.journal.get_open_trades()
        trade_info = next(
            (t for t in open_trades if t.get("trade_id") == trade_id), None
        )

        symbol = trade_info.get("symbol", "") if trade_info else ""
        direction = trade_info.get("direction", "LONG") if trade_info else "LONG"
        entry_price = trade_info.get("entry_price", 0) if trade_info else 0
        position_size = trade_info.get("position_size", 0) if trade_info else 0

        if direction == "LONG":
            pnl = (exit_price - entry_price) * position_size
        else:
            pnl = (entry_price - exit_price) * position_size

        # Grade the trade
        is_win = pnl > 0
        grade = self._grade_trade(reason, pnl, entry_price, exit_price)

        self.journal.record_close(trade_id, exit_price, reason, pnl)
        self.journal.record_grade(trade_id, grade, reason)

        # Update learning state
        self._total_trades += 1
        if is_win:
            self._total_wins += 1
            self._instrument_wins[symbol] += 1
        else:
            self._instrument_losses[symbol] += 1

        if symbol:
            await self.broker.close_position(symbol)

        wr = self._total_wins / self._total_trades * 100
        logger.info(
            "[LAB] CLOSED #%d: %s %s %s pnl=%.4f grade=%s | WR=%.0f%% (%d/%d)",
            trade_id, direction, symbol, reason, pnl, grade,
            wr, self._total_wins, self._total_trades,
        )

        now = datetime.now(timezone.utc)
        await self.bus.publish(TradeClosed(
            trade_id=str(trade_id),
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl=pnl,
            reason=reason,
            timestamp=now,
        ))

    def _grade_trade(self, reason: str, pnl: float, entry: float, exit_price: float) -> str:
        """Grade A-F based on execution quality."""
        if reason == "tp_hit" and pnl > 0:
            return "A"  # Hit target — perfect execution
        if pnl > 0:
            return "B"  # Profitable but didn't hit target
        if reason == "sl_hit":
            return "D"  # Hit stop loss — setup was wrong
        return "C"  # Breakeven or small loss

    def _log_learning_summary(self) -> None:
        if self._total_trades == 0:
            return
        wr = self._total_wins / self._total_trades * 100
        logger.info("[LAB] === LEARNING SUMMARY ===")
        logger.info("[LAB] Total: %d trades, %.0f%% win rate", self._total_trades, wr)

        # Per-instrument breakdown
        all_syms = set(self._instrument_wins.keys()) | set(self._instrument_losses.keys())
        for sym in sorted(all_syms):
            w = self._instrument_wins[sym]
            l = self._instrument_losses[sym]
            total = w + l
            if total > 0:
                logger.info("[LAB]   %s: %dW/%dL (%.0f%%)", sym, w, l, w / total * 100)

    async def get_status(self) -> dict:
        balance = await self.broker.get_balance()
        open_trades = self.journal.get_open_trades()
        closed_trades = self.journal.get_closed_trades(limit=1000)
        wr = (self._total_wins / self._total_trades * 100) if self._total_trades > 0 else 0
        return {
            "running": self._running,
            "balance": balance.total,
            "open_trades": len(open_trades),
            "closed_trades": len(closed_trades),
            "broker": self.broker.name,
            "broker_connected": self.broker.is_connected,
            "win_rate": round(wr, 1),
            "total_trades": self._total_trades,
        }

    def get_pnl(self, current_balance: float) -> PnLResult:
        return self.pnl.calculate(current_balance)
