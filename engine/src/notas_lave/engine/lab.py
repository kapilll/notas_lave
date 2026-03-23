"""v2 Lab Engine — scans markets, evaluates signals, executes trades.

All dependencies injected via constructor. No globals, no use_db().
The engine runs a scan loop: fetch candles -> run strategies ->
compute confluence -> execute qualifying trades -> monitor positions.
"""

import asyncio
import logging
from datetime import datetime, timezone

from ..core.events import TradeClosed, TradeOpened
from ..core.models import Direction, Signal, TradeSetup
from ..core.ports import IBroker, ITradeJournal
from ..engine.event_bus import EventBus
from ..engine.pnl import PnLResult, PnLService

logger = logging.getLogger(__name__)

# Lab settings
LAB_INSTRUMENTS = [
    "BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "BNBUSD", "DOGEUSD",
    "ADAUSD", "AVAXUSD", "LINKUSD", "DOTUSD", "LTCUSD", "NEARUSD",
    "SUIUSD", "ARBUSD", "PEPEUSD", "WIFUSD", "FTMUSD", "ATOMUSD",
]
LAB_TIMEFRAMES = ["15m", "1h", "4h"]
MIN_SCORE = 3.0
MIN_RR = 1.5
MAX_CONCURRENT = 5
SCAN_INTERVAL = 60  # seconds


class LabEngine:
    """Lab trading engine with dependency injection.

    Usage:
        engine = LabEngine(broker=..., journal=..., bus=..., pnl=...)
        await engine.start()  # runs scan loop
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

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Start the scan loop."""
        if self._running:
            return

        if not self.broker.is_connected:
            connected = await self.broker.connect()
            if not connected:
                logger.error("[LAB] Could not connect to broker")
                return

        self._running = True
        balance = await self.broker.get_balance()
        logger.info("[LAB] Started — broker=%s balance=%.2f %s",
                     self.broker.name, balance.total, balance.currency)

        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("[LAB] Stopped")

    async def _loop(self) -> None:
        """Main scan loop."""
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.error("[LAB] Tick error: %s", e)
            await asyncio.sleep(SCAN_INTERVAL)

    async def _tick(self) -> None:
        """One scan cycle: fetch data, evaluate, trade."""
        from ..data.market_data import market_data
        from ..confluence.scorer import compute_confluence

        # Lab mode: disable staleness check — we want maximum data
        market_data.max_stale_minutes = 0

        open_count = len(self.journal.get_open_trades())
        scanned = 0
        signals_found = 0

        for symbol in LAB_INSTRUMENTS:
            if open_count >= MAX_CONCURRENT:
                break

            # Cooldown: 60s between trades per symbol
            last = self._last_trade.get(symbol)
            if last and (datetime.now(timezone.utc) - last).total_seconds() < 60:
                continue

            for tf in LAB_TIMEFRAMES:
                try:
                    candles = await market_data.get_candles(symbol, tf, limit=250)
                    if not candles or len(candles) < 50:
                        continue

                    result = compute_confluence(candles, symbol, tf)
                    scanned += 1

                    if (result.direction is None
                            or result.composite_score < MIN_SCORE
                            or result.agreeing_strategies < 2):
                        continue

                    signals_found += 1

                    # Find entry/SL/TP from strongest signal
                    best = max(
                        (s for s in result.signals if s.direction == result.direction),
                        key=lambda s: s.score,
                        default=None,
                    )
                    if not best or not best.entry_price or not best.stop_loss or not best.take_profit:
                        continue

                    # Risk/reward check
                    risk = abs(best.entry_price - best.stop_loss)
                    reward = abs(best.take_profit - best.entry_price)
                    if risk <= 0 or reward / risk < MIN_RR:
                        continue

                    setup = TradeSetup(
                        symbol=symbol,
                        direction=result.direction,
                        entry_price=best.entry_price,
                        stop_loss=best.stop_loss,
                        take_profit=best.take_profit,
                        position_size=0.001,  # Minimal size for lab
                        confluence_score=result.composite_score,
                    )

                    trade_id = await self.execute_trade(setup)
                    self._last_trade[symbol] = datetime.now(timezone.utc)
                    open_count += 1

                    logger.info(
                        "[LAB] TRADE: %s %s %s score=%.1f entry=%.2f sl=%.2f tp=%.2f",
                        result.direction.value, symbol, tf,
                        result.composite_score, best.entry_price,
                        best.stop_loss, best.take_profit,
                    )
                    break  # One trade per symbol per tick

                except Exception as e:
                    logger.debug("[LAB] %s/%s error: %s", symbol, tf, e)

        logger.info("[LAB] Tick: scanned=%d signals=%d open=%d", scanned, signals_found, open_count)

        # Monitor open positions
        await self._check_positions()

    async def _check_positions(self) -> None:
        """Check open positions against broker for SL/TP hits."""
        from ..data.market_data import market_data

        open_trades = self.journal.get_open_trades()
        positions = await self.broker.get_positions()
        position_symbols = {p.symbol for p in positions}

        for trade in open_trades:
            symbol = trade.get("symbol", "")
            trade_id = trade.get("trade_id", 0)
            entry = trade.get("entry_price", 0)
            sl = trade.get("stop_loss", 0)
            tp = trade.get("take_profit", 0)
            direction = trade.get("direction", "LONG")

            try:
                candles = await market_data.get_candles(symbol, "1m", limit=3)
                if not candles:
                    continue

                price = candles[-1].close

                # Check SL/TP
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
                    logger.info("[LAB] CLOSED: %s %s %s @ %.2f (%s)",
                                direction, symbol, hit, price,
                                "WIN" if hit == "tp_hit" else "LOSS")

            except Exception as e:
                logger.debug("[LAB] Monitor %s error: %s", symbol, e)

    async def execute_trade(self, setup: TradeSetup) -> int:
        """Execute a trade: journal it, place on broker, publish event."""
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
        """Close a trade: journal it, close on broker, publish event."""
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

        self.journal.record_close(trade_id, exit_price, reason, pnl)

        if symbol:
            await self.broker.close_position(symbol)

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

    async def get_status(self) -> dict:
        balance = await self.broker.get_balance()
        open_trades = self.journal.get_open_trades()
        closed_trades = self.journal.get_closed_trades(limit=1000)
        return {
            "running": self._running,
            "balance": balance.total,
            "open_trades": len(open_trades),
            "closed_trades": len(closed_trades),
            "broker": self.broker.name,
            "broker_connected": self.broker.is_connected,
        }

    def get_pnl(self, current_balance: float) -> PnLResult:
        return self.pnl.calculate(current_balance)
