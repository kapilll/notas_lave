"""v2 Lab Engine — slim, DI-based, event-driven.

All dependencies injected via constructor. No globals, no use_db().
The engine orchestrates: signal -> trade -> monitor -> close -> grade.

This replaces the 2172-line lab_trader.py with a focused core.
Business logic lives here. I/O lives in adapters.
"""

import logging
from datetime import datetime, timezone

from ..core.events import TradeClosed, TradeOpened
from ..core.models import Signal, TradeSetup
from ..core.ports import IBroker, ITradeJournal
from ..engine.event_bus import EventBus
from ..engine.pnl import PnLResult, PnLService

logger = logging.getLogger(__name__)


class LabEngine:
    """Lab trading engine with dependency injection.

    Usage:
        engine = LabEngine(broker=..., journal=..., bus=..., pnl=...)
        trade_id = await engine.execute_trade(setup)
        await engine.close_trade(trade_id, exit_price=..., reason=...)
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

    @property
    def is_running(self) -> bool:
        return self._running

    async def execute_trade(self, setup: TradeSetup) -> int:
        """Execute a trade: journal it, place on broker, publish event."""
        signal = Signal(
            strategy_name="lab",
            direction=setup.direction,
            score=setup.confluence_score,
        )
        trade_id = self.journal.record_signal(signal)
        self.journal.record_open(trade_id, setup)

        result = await self.broker.place_order(setup)
        if not result.success:
            logger.warning("Broker rejected trade %d: %s", trade_id, result.error)

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
        # Get trade info for the event
        open_trades = self.journal.get_open_trades()
        trade_info = next(
            (t for t in open_trades if t.get("trade_id") == trade_id), None
        )

        symbol = trade_info.get("symbol", "") if trade_info else ""
        direction = trade_info.get("direction", "LONG") if trade_info else "LONG"
        entry_price = trade_info.get("entry_price", 0) if trade_info else 0
        position_size = trade_info.get("position_size", 0) if trade_info else 0

        # Calculate P&L
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
        """Get current engine status."""
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
        """Calculate P&L from current balance."""
        return self.pnl.calculate(current_balance)
