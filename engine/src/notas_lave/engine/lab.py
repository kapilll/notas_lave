"""v2 Lab Engine — Multi-Timeframe Analysis, learns from every trade.

STRATEGY:
  Read the map on higher timeframes (4h, 1d) — find bias, levels, structure.
  Execute trades on lower timeframes (15m, 30m, 1h) — precise entries.
  HTF candles are passed to confluence scorer for trend bias filtering.

PACE CONTROL:
  Trading pace can be changed live via API. Presets:
  - "conservative": 1h only, score>=4.0, agree>=2
  - "balanced":      15m+1h, score>=3.5, agree>=1
  - "aggressive":    15m+30m+1h, score>=2.5, agree>=1
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

LAB_INSTRUMENTS = [
    "BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "BNBUSD", "DOGEUSD",
    "ADAUSD", "AVAXUSD", "LINKUSD", "DOTUSD", "LTCUSD", "NEARUSD",
    "SUIUSD", "ARBUSD", "PEPEUSD", "WIFUSD", "FTMUSD", "ATOMUSD",
]

# Context timeframes — for reading bias, NOT for taking trades
CONTEXT_TIMEFRAMES = ["4h", "1d"]

# Pace presets — entry timeframes + thresholds
PACE_PRESETS = {
    "conservative": {
        "entry_tfs": ["1h"],
        "min_score": 4.0,
        "min_agree": 2,
        "min_rr": 2.0,
        "max_concurrent": 3,
        "cooldown": 300,
        "scan_interval": 60,
    },
    "balanced": {
        "entry_tfs": ["15m", "1h"],
        "min_score": 3.5,
        "min_agree": 1,
        "min_rr": 1.5,
        "max_concurrent": 5,
        "cooldown": 120,
        "scan_interval": 45,
    },
    "aggressive": {
        "entry_tfs": ["15m", "30m", "1h"],
        "min_score": 2.5,
        "min_agree": 1,
        "min_rr": 1.2,
        "max_concurrent": 8,
        "cooldown": 60,
        "scan_interval": 30,
    },
}

RISK_PER_TRADE = 0.01


class LabEngine:
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

        # Pace — can be changed live via set_pace()
        self._pace = "balanced"
        self._settings = PACE_PRESETS["balanced"].copy()

        # Learning state
        self._strategy_stats: dict[str, dict] = defaultdict(lambda: {"wins": 0, "losses": 0})
        self._instrument_stats: dict[str, dict] = defaultdict(lambda: {"wins": 0, "losses": 0})
        self._total_trades = 0
        self._total_wins = 0

        # HTF bias cache — refreshed every tick
        self._htf_bias: dict[str, str] = {}  # symbol -> "LONG"/"SHORT"/None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def pace(self) -> str:
        return self._pace

    def set_pace(self, pace: str) -> bool:
        if pace not in PACE_PRESETS:
            return False
        self._pace = pace
        self._settings = PACE_PRESETS[pace].copy()
        logger.info("[LAB] Pace changed to %s: %s", pace, self._settings)
        return True

    async def start(self) -> None:
        if self._running:
            return
        if not self.broker.is_connected:
            if not await self.broker.connect():
                logger.error("[LAB] Could not connect to broker")
                return

        from ..strategies.base import BaseStrategy
        BaseStrategy.set_volume_check(False)

        self._running = True
        balance = await self.broker.get_balance()
        s = self._settings
        logger.info("[LAB] Started — %s pace, broker=%s, balance=%.2f %s",
                     self._pace, self.broker.name, balance.total, balance.currency)
        logger.info("[LAB] Entry TFs: %s | Context TFs: %s | score>=%.1f rr>=%.1f agree>=%d max=%d",
                     s["entry_tfs"], CONTEXT_TIMEFRAMES, s["min_score"],
                     s["min_rr"], s["min_agree"], s["max_concurrent"])
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
            await asyncio.sleep(self._settings["scan_interval"])

    async def _tick(self) -> None:
        from ..data.market_data import market_data
        from ..confluence.scorer import compute_confluence

        market_data.max_stale_minutes = 0
        s = self._settings
        open_count = len(self.journal.get_open_trades())
        scanned = 0
        trades_placed = 0

        for symbol in LAB_INSTRUMENTS:
            if open_count >= s["max_concurrent"]:
                break

            last = self._last_trade.get(symbol)
            if last and (datetime.now(timezone.utc) - last).total_seconds() < s["cooldown"]:
                continue

            # Skip instruments with terrible track record
            ist = self._instrument_stats[symbol]
            total = ist["wins"] + ist["losses"]
            if total >= 5 and ist["wins"] / total < 0.25:
                continue

            # Fetch HTF candles ONCE for context (bias, levels, structure)
            htf_candles = None
            for ctx_tf in CONTEXT_TIMEFRAMES:
                try:
                    htf = await market_data.get_candles(symbol, ctx_tf, limit=100)
                    if htf and len(htf) >= 20:
                        htf_candles = htf
                        break
                except Exception:
                    pass

            # Scan ENTRY timeframes (where we actually trade)
            for tf in s["entry_tfs"]:
                try:
                    candles = await market_data.get_candles(symbol, tf, limit=250)
                    if not candles or len(candles) < 50:
                        continue

                    # Pass HTF candles for bias filtering
                    result = compute_confluence(candles, symbol, tf, htf_candles=htf_candles)
                    scanned += 1

                    if result.direction is None:
                        continue
                    if result.composite_score < s["min_score"]:
                        continue
                    if result.agreeing_strategies < s["min_agree"]:
                        continue

                    best = max(
                        (sig for sig in result.signals if sig.direction == result.direction),
                        key=lambda sig: sig.score,
                        default=None,
                    )
                    if not best or not best.entry_price or not best.stop_loss or not best.take_profit:
                        continue

                    risk = abs(best.entry_price - best.stop_loss)
                    reward = abs(best.take_profit - best.entry_price)
                    if risk <= 0 or reward / risk < s["min_rr"]:
                        continue

                    # Position sizing — 1% risk
                    balance = await self.broker.get_balance()
                    pos_size = (balance.total * RISK_PER_TRADE) / risk if risk > 0 else 0.001
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

                    htf_dir = "with HTF" if htf_candles else "no HTF"
                    logger.info(
                        "[LAB] TRADE #%d: %s %s %s score=%.1f agree=%d rr=%.1f size=%.4f (%s)",
                        trade_id, result.direction.value, symbol, tf,
                        result.composite_score, result.agreeing_strategies,
                        reward / risk, pos_size, htf_dir,
                    )
                    break

                except Exception as e:
                    logger.debug("[LAB] %s/%s error: %s", symbol, tf, e)

        if trades_placed > 0 or scanned > 0:
            wr = (self._total_wins / self._total_trades * 100) if self._total_trades > 0 else 0
            logger.info(
                "[LAB] Tick [%s]: scanned=%d placed=%d open=%d | %d trades %.0f%% WR",
                self._pace, scanned, trades_placed, open_count, self._total_trades, wr,
            )

        await self._check_positions()

    async def _check_positions(self) -> None:
        from ..data.market_data import market_data

        open_trades = self.journal.get_open_trades()
        if not open_trades:
            return

        # Live prices from broker
        broker_positions = await self.broker.get_positions()
        broker_prices: dict[str, float] = {}
        for bp in broker_positions:
            key = bp.symbol.replace("USDT", "USD") if bp.symbol.endswith("USDT") else bp.symbol
            if bp.current_price > 0:
                broker_prices[key] = bp.current_price

        for trade in open_trades:
            symbol = trade.get("symbol", "")
            trade_id = trade.get("trade_id", 0)
            sl = trade.get("stop_loss", 0)
            tp = trade.get("take_profit", 0)
            direction = trade.get("direction", "LONG")

            try:
                price = broker_prices.get(symbol, 0)
                if price <= 0:
                    candles = await market_data.get_candles(symbol, "1m", limit=1)
                    price = candles[-1].close if candles else 0
                if price <= 0:
                    continue

                # Use candle high/low for wick detection
                candles = await market_data.get_candles(symbol, "1m", limit=1)
                high = candles[-1].high if candles else price
                low = candles[-1].low if candles else price

                hit = None
                exit_price = price
                if direction == "LONG":
                    if sl > 0 and low <= sl:
                        hit, exit_price = "sl_hit", sl
                    elif tp > 0 and high >= tp:
                        hit, exit_price = "tp_hit", tp
                elif direction == "SHORT":
                    if sl > 0 and high >= sl:
                        hit, exit_price = "sl_hit", sl
                    elif tp > 0 and low <= tp:
                        hit, exit_price = "tp_hit", tp

                if hit:
                    await self.close_trade(trade_id, exit_price=exit_price, reason=hit)

            except Exception as e:
                logger.warning("[LAB] Monitor %s error: %s", symbol, e)

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

    async def close_trade(self, trade_id: int, exit_price: float, reason: str) -> None:
        open_trades = self.journal.get_open_trades()
        trade_info = next(
            (t for t in open_trades if t.get("trade_id") == trade_id), None
        )

        symbol = trade_info.get("symbol", "") if trade_info else ""
        direction = trade_info.get("direction", "LONG") if trade_info else "LONG"
        entry_price = trade_info.get("entry_price", 0) if trade_info else 0
        position_size = trade_info.get("position_size", 0) if trade_info else 0

        pnl = ((exit_price - entry_price) if direction == "LONG"
               else (entry_price - exit_price)) * position_size

        grade = "A" if reason == "tp_hit" and pnl > 0 else "B" if pnl > 0 else "D" if reason == "sl_hit" else "C"

        self.journal.record_close(trade_id, exit_price, reason, pnl)
        self.journal.record_grade(trade_id, grade, reason)

        # Update learning
        self._total_trades += 1
        is_win = pnl > 0
        if is_win:
            self._total_wins += 1
            self._instrument_stats[symbol]["wins"] += 1
        else:
            self._instrument_stats[symbol]["losses"] += 1

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
            trade_id=str(trade_id), symbol=symbol, direction=direction,
            entry_price=entry_price, exit_price=exit_price,
            pnl=pnl, reason=reason, timestamp=now,
        ))

    def _log_learning_summary(self) -> None:
        if self._total_trades == 0:
            return
        wr = self._total_wins / self._total_trades * 100
        logger.info("[LAB] === SUMMARY: %d trades, %.0f%% WR ===", self._total_trades, wr)
        for sym in sorted(self._instrument_stats):
            s = self._instrument_stats[sym]
            t = s["wins"] + s["losses"]
            if t > 0:
                logger.info("[LAB]   %s: %dW/%dL (%.0f%%)", sym, s["wins"], s["losses"], s["wins"]/t*100)

    async def get_status(self) -> dict:
        balance = await self.broker.get_balance()
        open_trades = self.journal.get_open_trades()
        closed_trades = self.journal.get_closed_trades(limit=1000)
        wr = (self._total_wins / self._total_trades * 100) if self._total_trades > 0 else 0
        return {
            "running": self._running,
            "pace": self._pace,
            "entry_tfs": self._settings["entry_tfs"],
            "context_tfs": CONTEXT_TIMEFRAMES,
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
