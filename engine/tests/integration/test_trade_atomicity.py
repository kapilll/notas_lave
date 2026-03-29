"""Trade atomicity tests — broker failures must not corrupt journal.

These verify that:
- Broker failure → journal has 0 open trades
- Close uses trade_id not symbol match (2 trades same symbol)
"""

import os
import tempfile

import pytest

from notas_lave.core.models import Direction, Signal, TradeSetup
from notas_lave.engine.event_bus import EventBus
from notas_lave.engine.leaderboard import StrategyLeaderboard
from notas_lave.engine.pnl import PnLService
from notas_lave.execution.paper import PaperBroker
from notas_lave.journal.event_store import EventStore


class FailingBroker(PaperBroker):
    """Broker that fails on place_order."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.fail_on_place = False

    async def place_order(self, setup):
        if self.fail_on_place:
            from notas_lave.core.models import OrderResult
            return OrderResult(success=False, error="Connection refused")
        return await super().place_order(setup)


def _make_engine(broker=None):
    from notas_lave.engine.lab import LabEngine
    broker = broker or PaperBroker(initial_balance=10000.0)
    journal = EventStore(":memory:")
    bus = EventBus()
    pnl = PnLService(original_deposit=10000.0)
    engine = LabEngine(broker=broker, journal=journal, bus=bus, pnl=pnl)
    engine.leaderboard = StrategyLeaderboard(persist_path=os.path.join(
        tempfile.mkdtemp(), "test_leaderboard.json"))
    return engine, broker, journal


@pytest.mark.asyncio
async def test_broker_failure_doesnt_corrupt_journal():
    """Broker.place_order fails → journal must have 0 open trades.

    execute_trade should NOT record to journal if broker rejects.
    """
    broker = FailingBroker(initial_balance=10000.0)
    engine, _, journal = _make_engine(broker=broker)
    await broker.connect()
    broker.fail_on_place = True

    setup = TradeSetup(
        symbol="BTCUSD", direction=Direction.LONG,
        entry_price=70000.0, stop_loss=69000.0,
        take_profit=72000.0, position_size=0.01,
    )
    trade_id = await engine.execute_trade(setup, context={"proposing_strategy": "test"})

    assert trade_id == 0, "Failed broker order should return trade_id=0"
    assert len(journal.get_open_trades()) == 0, (
        "Journal must NOT have open trades when broker rejected the order"
    )


@pytest.mark.asyncio
async def test_successful_trade_records_to_journal():
    """Broker success → journal must have exactly 1 open trade."""
    engine, broker, journal = _make_engine()
    await broker.connect()

    setup = TradeSetup(
        symbol="BTCUSD", direction=Direction.LONG,
        entry_price=70000.0, stop_loss=69000.0,
        take_profit=72000.0, position_size=0.01,
    )
    trade_id = await engine.execute_trade(setup, context={"proposing_strategy": "test"})

    assert trade_id > 0, "Successful trade should return positive trade_id"
    open_trades = journal.get_open_trades()
    assert len(open_trades) == 1
    assert open_trades[0]["symbol"] == "BTCUSD"


@pytest.mark.asyncio
async def test_close_uses_trade_id_not_symbol_match():
    """2 open trades same symbol → closes correct one by ID.

    This verifies the C2 fix: close_trade uses trade_id, not
    fuzzy symbol match that could close the wrong trade.
    """
    engine, broker, journal = _make_engine()
    await broker.connect()

    # Open two trades on same symbol
    setup1 = TradeSetup(
        symbol="BTCUSD", direction=Direction.LONG,
        entry_price=70000.0, stop_loss=69000.0,
        take_profit=72000.0, position_size=0.01,
    )
    setup2 = TradeSetup(
        symbol="BTCUSD", direction=Direction.LONG,
        entry_price=71000.0, stop_loss=70000.0,
        take_profit=73000.0, position_size=0.02,
    )

    tid1 = await engine.execute_trade(setup1, context={"proposing_strategy": "strategy_a"})
    tid2 = await engine.execute_trade(setup2, context={"proposing_strategy": "strategy_b"})

    assert tid1 != tid2, "Two trades should have different IDs"

    # Close the FIRST trade specifically
    await engine.close_trade(tid1, exit_price=71500.0, reason="tp_hit")

    open_trades = journal.get_open_trades()
    closed_trades = journal.get_closed_trades()

    assert len(closed_trades) == 1, "Exactly one trade should be closed"
    assert closed_trades[0]["trade_id"] == tid1, "Must close trade by ID, not symbol"

    # The second trade should still be open
    assert len(open_trades) == 1, "Second trade must remain open"
    assert open_trades[0]["trade_id"] == tid2


@pytest.mark.asyncio
async def test_double_close_is_idempotent():
    """Closing the same trade_id twice must not create duplicate close events."""
    engine, broker, journal = _make_engine()
    await broker.connect()

    setup = TradeSetup(
        symbol="ETHUSD", direction=Direction.SHORT,
        entry_price=2000.0, stop_loss=2100.0,
        take_profit=1900.0, position_size=1.0,
    )
    tid = await engine.execute_trade(setup, context={"proposing_strategy": "test"})

    # Close twice
    await engine.close_trade(tid, exit_price=1950.0, reason="tp_hit")
    await engine.close_trade(tid, exit_price=1950.0, reason="tp_hit")

    closed = journal.get_closed_trades()
    assert len(closed) == 1, "Double close must be idempotent"
