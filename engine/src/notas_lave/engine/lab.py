"""v2 Lab Engine — Broker is source of truth, journal is history.

ARCHITECTURE:
  Broker = source of truth for LIVE state (positions, balance)
  Journal = source of truth for HISTORY (closed trades, grades)
  Never show a position the broker doesn't have.
  Only mark journal "open" AFTER broker confirms fill.

STRATEGY:
  Read the map on higher timeframes (4h, 1d) — bias, levels, structure.
  Execute trades on lower timeframes (15m, 30m, 1h) — precise entries.

PACE CONTROL:
  "conservative": 1h only, score>=4.0, rr>=3.0
  "balanced":      15m+1h, score>=3.5, rr>=2.0
  "aggressive":    15m+30m+1h, score>=2.5, rr>=2.0
"""

import asyncio
import logging
import os
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

CONTEXT_TIMEFRAMES = ["4h", "1d"]

PACE_PRESETS = {
    "conservative": {
        "entry_tfs": ["1h"],
        "min_score": 4.0, "min_agree": 2, "min_rr": 3.0,
        "max_concurrent": 3, "cooldown": 300, "scan_interval": 60,
    },
    "balanced": {
        "entry_tfs": ["15m", "1h"],
        "min_score": 3.5, "min_agree": 1, "min_rr": 2.0,
        "max_concurrent": 5, "cooldown": 120, "scan_interval": 45,
    },
    "aggressive": {
        "entry_tfs": ["15m", "30m", "1h"],
        "min_score": 2.5, "min_agree": 1, "min_rr": 2.0,
        "max_concurrent": 8, "cooldown": 60, "scan_interval": 30,
    },
}

RISK_PER_TRADE = 0.01


class LabEngine:
    def __init__(self, broker: IBroker, journal: ITradeJournal,
                 bus: EventBus, pnl: PnLService) -> None:
        self.broker = broker
        self.journal = journal
        self.bus = bus
        self.pnl = pnl
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_trade: dict[str, datetime] = {}

        # Load persisted pace or default to balanced
        self._pace_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            "data", "lab_pace.txt",
        )
        saved = self._load_pace()
        self._pace = saved if saved in PACE_PRESETS else "balanced"
        self._settings = PACE_PRESETS[self._pace].copy()

        # Learning state
        self._instrument_stats: dict[str, dict] = defaultdict(lambda: {"wins": 0, "losses": 0})
        self._total_trades = 0
        self._total_wins = 0

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
        self._save_pace(pace)
        logger.info("[LAB] Pace -> %s: entry=%s score>=%.1f rr>=%.1f",
                     pace, self._settings["entry_tfs"],
                     self._settings["min_score"], self._settings["min_rr"])
        return True

    def _load_pace(self) -> str | None:
        try:
            with open(self._pace_file) as f:
                return f.read().strip()
        except Exception:
            return None

    def _save_pace(self, pace: str) -> None:
        try:
            os.makedirs(os.path.dirname(self._pace_file), exist_ok=True)
            with open(self._pace_file, "w") as f:
                f.write(pace)
        except Exception:
            pass

    async def start(self) -> None:
        if self._running:
            return
        if not self.broker.is_connected:
            if not await self.broker.connect():
                logger.error("[LAB] Could not connect to broker")
                return

        from ..strategies.base import BaseStrategy
        BaseStrategy.set_volume_check(False)

        # Reconcile journal with broker on startup
        await self._reconcile()

        self._running = True
        balance = await self.broker.get_balance()
        s = self._settings
        logger.info("[LAB] Started — %s pace, broker=%s, balance=%.2f",
                     self._pace, self.broker.name, balance.total)
        logger.info("[LAB] Entry: %s | Context: %s | score>=%.1f rr>=%.1f max=%d",
                     s["entry_tfs"], CONTEXT_TIMEFRAMES,
                     s["min_score"], s["min_rr"], s["max_concurrent"])
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

    async def _reconcile(self) -> None:
        """Reconcile journal with broker — close journal entries that don't exist on broker."""
        broker_positions = await self.broker.get_positions()
        broker_syms = set()
        for bp in broker_positions:
            key = bp.symbol.replace("USDT", "USD") if bp.symbol.endswith("USDT") else bp.symbol
            broker_syms.add(key)

        journal_open = self.journal.get_open_trades()
        closed = 0
        for trade in journal_open:
            sym = trade.get("symbol", "")
            if sym not in broker_syms:
                self.journal.record_close(
                    trade.get("trade_id", 0),
                    exit_price=trade.get("entry_price", 0),
                    reason="reconcile",
                    pnl=0,
                )
                closed += 1

        # Also close duplicates (keep latest per symbol)
        remaining = self.journal.get_open_trades()
        seen: set[str] = set()
        for trade in sorted(remaining, key=lambda t: t.get("trade_id", 0), reverse=True):
            sym = trade.get("symbol", "")
            if sym in seen:
                self.journal.record_close(
                    trade.get("trade_id", 0),
                    exit_price=trade.get("entry_price", 0),
                    reason="reconcile_dup",
                    pnl=0,
                )
                closed += 1
            else:
                seen.add(sym)

        if closed > 0:
            logger.info("[LAB] Reconciled: closed %d stale/duplicate journal entries", closed)

    async def get_live_positions(self) -> list[dict]:
        """Get positions from BROKER (source of truth), enriched with journal data."""
        broker_positions = await self.broker.get_positions()
        journal_open = self.journal.get_open_trades()

        # Build journal lookup by symbol
        journal_by_sym: dict[str, dict] = {}
        for t in journal_open:
            journal_by_sym[t.get("symbol", "")] = t

        result = []
        for bp in broker_positions:
            sym = bp.symbol.replace("USDT", "USD") if bp.symbol.endswith("USDT") else bp.symbol
            journal_data = journal_by_sym.get(sym, {})

            result.append({
                "symbol": sym,
                "direction": bp.direction.value,
                "quantity": bp.quantity,
                "entry_price": bp.entry_price,
                "current_price": bp.current_price,
                "unrealized_pnl": round(bp.unrealized_pnl, 4),
                "pnl": round(bp.unrealized_pnl, 4),
                "leverage": bp.leverage,
                # Journal enrichment
                "stop_loss": journal_data.get("stop_loss", 0),
                "take_profit": journal_data.get("take_profit", 0),
                "confluence_score": journal_data.get("confluence_score", 0),
                "trade_id": journal_data.get("trade_id", 0),
            })

        return result

    async def _tick(self) -> None:
        from ..data.market_data import market_data
        from ..confluence.scorer import compute_confluence

        market_data.max_stale_minutes = 0
        s = self._settings

        # Reconcile every tick — broker is truth
        await self._reconcile()

        # Count from BROKER, not journal
        broker_positions = await self.broker.get_positions()
        open_count = len(broker_positions)
        open_syms = set()
        for bp in broker_positions:
            key = bp.symbol.replace("USDT", "USD") if bp.symbol.endswith("USDT") else bp.symbol
            open_syms.add(key)

        scanned = 0
        trades_placed = 0

        for symbol in LAB_INSTRUMENTS:
            if open_count >= s["max_concurrent"]:
                break
            if symbol in open_syms:
                continue  # Already have a position

            last = self._last_trade.get(symbol)
            if last and (datetime.now(timezone.utc) - last).total_seconds() < s["cooldown"]:
                continue

            # Skip instruments with terrible track record
            ist = self._instrument_stats[symbol]
            total = ist["wins"] + ist["losses"]
            if total >= 5 and ist["wins"] / total < 0.25:
                continue

            # Fetch HTF candles for context
            htf_candles = None
            for ctx_tf in CONTEXT_TIMEFRAMES:
                try:
                    htf = await market_data.get_candles(symbol, ctx_tf, limit=100)
                    if htf and len(htf) >= 20:
                        htf_candles = htf
                        break
                except Exception:
                    pass

            for tf in s["entry_tfs"]:
                try:
                    candles = await market_data.get_candles(symbol, tf, limit=250)
                    if not candles or len(candles) < 50:
                        continue

                    result = compute_confluence(candles, symbol, tf, htf_candles=htf_candles)
                    scanned += 1

                    if (result.direction is None
                            or result.composite_score < s["min_score"]
                            or result.agreeing_strategies < s["min_agree"]):
                        continue

                    best = max(
                        (sig for sig in result.signals if sig.direction == result.direction),
                        key=lambda sig: sig.score, default=None,
                    )
                    if not best or not best.entry_price or not best.stop_loss or not best.take_profit:
                        continue

                    risk = abs(best.entry_price - best.stop_loss)
                    reward = abs(best.take_profit - best.entry_price)
                    if risk <= 0 or reward / risk < s["min_rr"]:
                        continue

                    balance = await self.broker.get_balance()
                    pos_size = (balance.total * RISK_PER_TRADE) / risk if risk > 0 else 0.001
                    pos_size = max(0.001, min(pos_size, balance.total / best.entry_price * 0.05))
                    pos_size = round(pos_size, 6)

                    setup = TradeSetup(
                        symbol=symbol, direction=result.direction,
                        entry_price=best.entry_price, stop_loss=best.stop_loss,
                        take_profit=best.take_profit, position_size=pos_size,
                        confluence_score=result.composite_score,
                    )

                    trade_id = await self.execute_trade(setup)
                    if trade_id > 0:
                        self._last_trade[symbol] = datetime.now(timezone.utc)
                        open_count += 1
                        open_syms.add(symbol)
                        trades_placed += 1
                        logger.info(
                            "[LAB] TRADE #%d: %s %s %s score=%.1f rr=%.1f size=%.4f",
                            trade_id, result.direction.value, symbol, tf,
                            result.composite_score, reward / risk, pos_size,
                        )
                    break

                except Exception as e:
                    logger.debug("[LAB] %s/%s error: %s", symbol, tf, e)

        if trades_placed > 0 or scanned > 0:
            wr = (self._total_wins / self._total_trades * 100) if self._total_trades > 0 else 0
            logger.info("[LAB] Tick [%s]: scanned=%d placed=%d open=%d | %d trades %.0f%% WR",
                         self._pace, scanned, trades_placed, open_count, self._total_trades, wr)

        await self._check_positions()

    async def _check_positions(self) -> None:
        """Monitor SL/TP using broker positions (source of truth)."""
        from ..data.market_data import market_data

        broker_positions = await self.broker.get_positions()
        journal_open = self.journal.get_open_trades()

        # Build journal lookup
        journal_by_sym: dict[str, dict] = {}
        for t in journal_open:
            journal_by_sym[t.get("symbol", "")] = t

        for bp in broker_positions:
            sym = bp.symbol.replace("USDT", "USD") if bp.symbol.endswith("USDT") else bp.symbol
            journal = journal_by_sym.get(sym, {})
            sl = journal.get("stop_loss", 0)
            tp = journal.get("take_profit", 0)
            trade_id = journal.get("trade_id", 0)
            direction = bp.direction.value

            if not sl and not tp:
                continue

            price = bp.current_price
            if price <= 0:
                try:
                    candles = await market_data.get_candles(sym, "1m", limit=1)
                    price = candles[-1].close if candles else 0
                except Exception:
                    continue
            if price <= 0:
                continue

            # Use candle high/low for wick detection
            try:
                candles = await market_data.get_candles(sym, "1m", limit=1)
                high = candles[-1].high if candles else price
                low = candles[-1].low if candles else price
            except Exception:
                high = low = price

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

            if hit and trade_id > 0:
                await self.close_trade(trade_id, exit_price=exit_price, reason=hit)

    async def execute_trade(self, setup: TradeSetup) -> int:
        """Execute: place on broker FIRST, only journal if confirmed."""
        # Place on broker FIRST
        result = await self.broker.place_order(setup)
        if not result.success:
            logger.warning("[LAB] Broker rejected %s %s: %s",
                           setup.direction.value, setup.symbol, result.error)
            return 0  # Don't journal rejected trades

        # Broker confirmed — NOW record in journal
        signal = Signal(strategy_name="lab_confluence",
                        direction=setup.direction, score=setup.confluence_score)
        trade_id = self.journal.record_signal(signal)
        self.journal.record_open(trade_id, setup)

        now = datetime.now(timezone.utc)
        await self.bus.publish(TradeOpened(
            trade_id=str(trade_id), symbol=setup.symbol,
            direction=setup.direction.value,
            entry_price=result.filled_price or setup.entry_price,
            position_size=result.filled_quantity or setup.position_size,
            stop_loss=setup.stop_loss, take_profit=setup.take_profit,
            timestamp=now,
        ))
        return trade_id

    async def close_trade(self, trade_id: int, exit_price: float, reason: str) -> None:
        open_trades = self.journal.get_open_trades()
        trade_info = next(
            (t for t in open_trades if t.get("trade_id") == trade_id), None)
        if not trade_info:
            return

        symbol = trade_info.get("symbol", "")
        direction = trade_info.get("direction", "LONG")
        entry_price = trade_info.get("entry_price", 0)
        position_size = trade_info.get("position_size", 0)

        pnl = ((exit_price - entry_price) if direction == "LONG"
               else (entry_price - exit_price)) * position_size

        grade = ("A" if reason == "tp_hit" and pnl > 0
                 else "B" if pnl > 0
                 else "D" if reason == "sl_hit"
                 else "C")

        # Close on broker FIRST
        if symbol:
            await self.broker.close_position(symbol)

        # Then journal
        self.journal.record_close(trade_id, exit_price, reason, pnl)
        self.journal.record_grade(trade_id, grade, reason)

        self._total_trades += 1
        if pnl > 0:
            self._total_wins += 1
            self._instrument_stats[symbol]["wins"] += 1
        else:
            self._instrument_stats[symbol]["losses"] += 1

        wr = self._total_wins / self._total_trades * 100
        logger.info("[LAB] CLOSED #%d: %s %s %s pnl=%.4f grade=%s | WR=%.0f%%",
                     trade_id, direction, symbol, reason, pnl, grade, wr)

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
        broker_positions = await self.broker.get_positions()
        closed_trades = self.journal.get_closed_trades(limit=1000)
        wr = (self._total_wins / self._total_trades * 100) if self._total_trades > 0 else 0
        return {
            "running": self._running, "pace": self._pace,
            "entry_tfs": self._settings["entry_tfs"],
            "context_tfs": CONTEXT_TIMEFRAMES,
            "balance": balance.total,
            "open_trades": len(broker_positions),
            "closed_trades": len(closed_trades),
            "broker": self.broker.name,
            "broker_connected": self.broker.is_connected,
            "win_rate": round(wr, 1),
            "total_trades": self._total_trades,
        }

    def get_pnl(self, current_balance: float) -> PnLResult:
        return self.pnl.calculate(current_balance)
