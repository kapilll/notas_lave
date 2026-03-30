"""Balance reconciliation invariants.

These verify that P&L, leaderboard, and risk state stay consistent
with broker truth after a sequence of trades.
"""

import os
import tempfile

import pytest

from notas_lave.core.models import Direction, TradeSetup
from notas_lave.engine.event_bus import EventBus
from notas_lave.engine.leaderboard import StrategyLeaderboard
from notas_lave.engine.pnl import PnLService
from notas_lave.execution.paper import PaperBroker
from notas_lave.journal.event_store import EventStore


def _make_engine():
    from notas_lave.engine.lab import LabEngine
    broker = PaperBroker(initial_balance=10000.0)
    journal = EventStore(":memory:")
    bus = EventBus()
    pnl = PnLService(original_deposit=10000.0)
    engine = LabEngine(broker=broker, journal=journal, bus=bus, pnl=pnl)
    # Use isolated leaderboard so tests don't share state via disk
    engine.leaderboard = StrategyLeaderboard(persist_path=os.path.join(
        tempfile.mkdtemp(), "test_leaderboard.json"))
    return engine, broker, journal


@pytest.mark.asyncio
async def test_pnl_sum_matches_after_trades():
    """Execute trades → sum(trade.pnl) must be internally consistent.

    This uses PaperBroker so we can't compare to broker balance directly
    (PaperBroker doesn't track P&L on positions). Instead we verify:
    sum(closed_trade_pnls) == total P&L tracked by journal.
    """
    engine, broker, journal = _make_engine()
    await broker.connect()

    trades = [
        ("BTCUSD", Direction.LONG, 70000.0, 71000.0, 0.01),   # win: +10
        ("ETHUSD", Direction.SHORT, 2000.0, 1950.0, 1.0),     # win: +50
        ("SOLUSD", Direction.LONG, 150.0, 145.0, 10.0),       # loss: -50
    ]

    for symbol, direction, entry, exit_p, size in trades:
        setup = TradeSetup(
            symbol=symbol, direction=direction,
            entry_price=entry, stop_loss=entry * 0.97,
            take_profit=entry * 1.03, position_size=size,
        )
        tid, _exec_err = await engine.execute_trade(setup, context={"proposing_strategy": "test"})
        assert tid > 0
        await engine.close_trade(tid, exit_price=exit_p,
                                 reason="tp_hit" if exit_p > entry else "sl_hit")

    closed = journal.get_closed_trades()
    assert len(closed) == 3

    total_pnl = sum(t["pnl"] for t in closed)
    # Expected: +10 + 50 + (-50) = +10
    assert total_pnl == pytest.approx(10.0, abs=0.01), (
        f"Sum of trade P&Ls should be $10, got ${total_pnl}"
    )


@pytest.mark.asyncio
async def test_leaderboard_total_matches_tradelog_count():
    """For each strategy: leaderboard.total_trades == actual journal count."""
    engine, broker, journal = _make_engine()
    await broker.connect()

    strategy_trades = {
        "trend_momentum": [
            ("BTCUSD", Direction.LONG, 70000.0, 71000.0, 0.01),
            ("BTCUSD", Direction.LONG, 72000.0, 73000.0, 0.01),
        ],
        "mean_reversion": [
            ("ETHUSD", Direction.SHORT, 2000.0, 1950.0, 1.0),
        ],
    }

    for strategy, trades in strategy_trades.items():
        for symbol, direction, entry, exit_p, size in trades:
            setup = TradeSetup(
                symbol=symbol, direction=direction,
                entry_price=entry, stop_loss=entry * 0.97,
                take_profit=entry * 1.03, position_size=size,
            )
            tid, _exec_err = await engine.execute_trade(setup, context={"proposing_strategy": strategy})
            await engine.close_trade(tid, exit_price=exit_p, reason="tp_hit")

    # Verify leaderboard counts match
    for strategy, trades in strategy_trades.items():
        record = engine.leaderboard.get_strategy(strategy)
        assert record is not None, f"Strategy {strategy} should exist in leaderboard"
        assert record["total_trades"] == len(trades), (
            f"{strategy}: leaderboard shows {record['total_trades']} trades, "
            f"but we executed {len(trades)}"
        )


@pytest.mark.asyncio
async def test_leaderboard_pnl_matches_journal_pnl():
    """Leaderboard total_pnl per strategy == sum of that strategy's journal P&Ls."""
    engine, broker, journal = _make_engine()
    await broker.connect()

    # Execute trades with known P&L
    setup = TradeSetup(
        symbol="BTCUSD", direction=Direction.LONG,
        entry_price=70000.0, stop_loss=69000.0,
        take_profit=72000.0, position_size=0.01,
    )

    # Win: (71000-70000)*0.01 = 10
    tid1, _exec_err = await engine.execute_trade(setup, context={"proposing_strategy": "arena_strat"})
    await engine.close_trade(tid1, exit_price=71000.0, reason="tp_hit")

    # Loss: (69000-70000)*0.01 = -10
    setup2 = TradeSetup(
        symbol="ETHUSD", direction=Direction.LONG,
        entry_price=2000.0, stop_loss=1900.0,
        take_profit=2200.0, position_size=1.0,
    )
    tid2, _exec_err = await engine.execute_trade(setup2, context={"proposing_strategy": "arena_strat"})
    await engine.close_trade(tid2, exit_price=1950.0, reason="sl_hit")

    record = engine.leaderboard.get_strategy("arena_strat")
    closed = journal.get_closed_trades()

    journal_pnl = sum(t["pnl"] for t in closed)
    assert record["total_pnl"] == pytest.approx(journal_pnl, abs=0.01), (
        f"Leaderboard P&L ({record['total_pnl']}) != journal P&L sum ({journal_pnl})"
    )


@pytest.mark.asyncio
async def test_no_open_trades_after_all_closed():
    """After closing all trades, journal must show 0 open trades."""
    engine, broker, journal = _make_engine()
    await broker.connect()

    tids = []
    for symbol, entry in [("BTCUSD", 70000.0), ("ETHUSD", 2000.0)]:
        setup = TradeSetup(
            symbol=symbol, direction=Direction.LONG,
            entry_price=entry, stop_loss=entry * 0.97,
            take_profit=entry * 1.03, position_size=0.01,
        )
        tid, _exec_err = await engine.execute_trade(setup, context={"proposing_strategy": "test"})
        tids.append((tid, entry))

    assert len(journal.get_open_trades()) == 2

    for tid, entry in tids:
        await engine.close_trade(tid, exit_price=entry * 1.01, reason="tp_hit")

    assert len(journal.get_open_trades()) == 0, "All trades closed but journal shows open trades"
    assert len(journal.get_closed_trades()) == 2
