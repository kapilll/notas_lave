"""End-to-end cross-phase integration tests.

These tests verify that data is consistent ACROSS all layers simultaneously:
  EventStore ↔ TradeLog ↔ Leaderboard ↔ WS events ↔ REST API

No single-layer test can catch cross-layer inconsistencies.
These are the most important tests in the suite.
"""

import os
import tempfile

import pytest

from notas_lave.api.app import Container, create_app
from notas_lave.api.ws_manager import ConnectionManager
from notas_lave.core.models import Direction, TradeSetup
from notas_lave.engine.event_bus import EventBus
from notas_lave.engine.lab import LabEngine
from notas_lave.engine.leaderboard import StrategyLeaderboard
from notas_lave.engine.pnl import PnLService
from notas_lave.execution.paper import PaperBroker
from notas_lave.journal.event_store import EventStore


def _make_engine(deposit=10_000.0):
    broker = PaperBroker(initial_balance=deposit)
    journal = EventStore(":memory:")
    bus = EventBus()
    pnl = PnLService(original_deposit=deposit)
    engine = LabEngine(broker=broker, journal=journal, bus=bus, pnl=pnl)
    engine.leaderboard = StrategyLeaderboard(persist_path=os.path.join(
        tempfile.mkdtemp(), "test_leaderboard.json"))
    return engine, broker, journal


def _make_app(engine, broker, journal, pnl):
    container = Container(broker=broker, journal=journal, bus=EventBus(), pnl=pnl,
                          lab_engine=engine)
    return create_app(container)


# ===================================================================
# 5A-1: Trade lifecycle — ALL layers agree on every number
# ===================================================================

@pytest.mark.asyncio
async def test_trade_lifecycle_all_numbers_match():
    """Open trade → close trade → verify all layers agree.

    Checks:
    1. TradeLog.pnl matches expected P&L formula
    2. Leaderboard strategy total matches journal count
    3. EventStore count matches TradeLog closed count
    4. WS trade.executed event carries same P&L as journal
    5. No orphaned EventStore entries without a close
    """
    engine, broker, journal = _make_engine(deposit=10_000.0)
    await broker.connect()

    # Subscribe to WS events to capture broadcasts
    ws_events = []

    class FakeWebSocket:
        async def accept(self): pass
        async def send_json(self, data): ws_events.append(data)
        async def close(self, code=None): pass

    from notas_lave.api.ws_manager import ws_manager
    fake_ws = FakeWebSocket()
    client_id = await ws_manager.connect(fake_ws)
    await ws_manager.subscribe(client_id, ["trade.executed"])
    ws_events.clear()

    # --- Open a trade ---
    setup = TradeSetup(
        symbol="BTCUSD", direction=Direction.LONG,
        entry_price=70_000.0, stop_loss=69_000.0,
        take_profit=72_000.0, position_size=0.01,
    )
    tid, _exec_err = await engine.execute_trade(setup, context={"proposing_strategy": "trend_momentum"})
    assert tid > 0

    # Verify open state
    open_trades = journal.get_open_trades()
    assert len(open_trades) == 1, "EventStore must show 1 open trade"

    # --- Close the trade at a profit ---
    exit_price = 71_000.0
    await engine.close_trade(tid, exit_price=exit_price, reason="tp_hit")

    # 1. EventStore has exactly 1 closed trade
    closed = journal.get_closed_trades()
    assert len(closed) == 1
    assert len(journal.get_open_trades()) == 0

    # 2. P&L formula: (exit - entry) * size * contract_size (BTCUSD contract_size=1)
    expected_pnl = (exit_price - 70_000.0) * 0.01 * 1.0  # = 10.0
    assert closed[0]["pnl"] == pytest.approx(expected_pnl, abs=0.01)

    # 3. Leaderboard shows exactly 1 trade for this strategy
    record = engine.leaderboard.get_strategy("trend_momentum")
    assert record is not None
    assert record["total_trades"] == 1
    assert record["wins"] == 1

    # 4. WS trade.executed event was broadcast with correct data
    close_events = [
        e for e in ws_events
        if e.get("topic") == "trade.executed" and e.get("data", {}).get("event") == "closed"
    ]
    assert len(close_events) == 1, "WS must broadcast trade.executed on close"
    ws_pnl = close_events[0]["data"]["pnl"]
    assert ws_pnl == pytest.approx(expected_pnl, abs=0.01), (
        f"WS P&L ({ws_pnl}) != journal P&L ({expected_pnl})"
    )

    # 5. No orphaned EventStore open entries
    assert len(journal.get_open_trades()) == 0

    await ws_manager.disconnect(client_id)


@pytest.mark.asyncio
async def test_multi_trade_lifecycle_pnl_accounting():
    """Multiple trades: sum of all P&Ls equals total leaderboard P&L."""
    engine, broker, journal = _make_engine()
    await broker.connect()

    trades = [
        ("BTCUSD", Direction.LONG, 70_000.0, 71_000.0, 0.01, "trend_momentum"),   # +10
        ("ETHUSD", Direction.SHORT, 2_000.0, 1_950.0, 1.0, "mean_reversion"),      # +50
        ("SOLUSD", Direction.LONG, 150.0, 145.0, 10.0, "breakout"),                # -50
    ]

    tids = []
    for sym, direction, entry, exit_p, size, strat in trades:
        setup = TradeSetup(
            symbol=sym, direction=direction,
            entry_price=entry, stop_loss=entry * 0.97,
            take_profit=entry * 1.03, position_size=size,
        )
        tid, _exec_err = await engine.execute_trade(setup, context={"proposing_strategy": strat})
        tids.append((tid, exit_p, strat))

    for tid, exit_p, strat in tids:
        reason = "tp_hit" if exit_p > 70_000.0 or strat == "mean_reversion" else "sl_hit"
        await engine.close_trade(tid, exit_price=exit_p, reason=reason)

    closed = journal.get_closed_trades()
    assert len(closed) == 3

    journal_total_pnl = sum(t["pnl"] for t in closed)

    # Leaderboard total P&L must equal journal sum
    leaderboard_total = sum(
        engine.leaderboard.get_strategy(s)["total_pnl"]
        for s in ["trend_momentum", "mean_reversion", "breakout"]
        if engine.leaderboard.get_strategy(s)
    )
    assert leaderboard_total == pytest.approx(journal_total_pnl, abs=0.01), (
        f"Leaderboard total P&L ({leaderboard_total}) != journal sum ({journal_total_pnl})"
    )


# ===================================================================
# 5A-2: Broker disconnect — state stays consistent
# ===================================================================

class DisconnectableBroker(PaperBroker):
    """PaperBroker that can be force-disconnected."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.reject_orders = False

    async def place_order(self, setup):
        if self.reject_orders:
            from notas_lave.core.models import OrderResult
            return OrderResult(success=False, error="Broker disconnected")
        return await super().place_order(setup)

    async def disconnect(self):
        await super().disconnect()
        self.reject_orders = True

    async def connect(self):
        result = await super().connect()
        self.reject_orders = False
        return result


@pytest.mark.asyncio
async def test_broker_disconnect_no_trades_attempted():
    """When broker is disconnected, no trades must reach the journal."""
    broker = DisconnectableBroker(initial_balance=10_000.0)
    journal = EventStore(":memory:")
    bus = EventBus()
    pnl = PnLService(original_deposit=10_000.0)
    engine = LabEngine(broker=broker, journal=journal, bus=bus, pnl=pnl)
    engine.leaderboard = StrategyLeaderboard(persist_path=os.path.join(
        tempfile.mkdtemp(), "test_leaderboard.json"))

    await broker.connect()
    await broker.disconnect()  # Simulate disconnect — orders now rejected
    assert not broker.is_connected

    setup = TradeSetup(
        symbol="BTCUSD", direction=Direction.LONG,
        entry_price=70_000.0, stop_loss=69_000.0,
        take_profit=72_000.0, position_size=0.01,
    )
    tid, _exec_err = await engine.execute_trade(setup, context={"proposing_strategy": "test"})

    assert tid == 0, "No trade should be opened when broker is disconnected"
    assert len(journal.get_open_trades()) == 0, "Journal must be clean after broker failure"


@pytest.mark.asyncio
async def test_broker_reconnect_positions_reconciled():
    """After reconnect, existing positions are reconciled correctly."""
    broker = DisconnectableBroker(initial_balance=10_000.0)
    journal = EventStore(":memory:")
    bus = EventBus()
    pnl = PnLService(original_deposit=10_000.0)
    engine = LabEngine(broker=broker, journal=journal, bus=bus, pnl=pnl)
    engine.leaderboard = StrategyLeaderboard(persist_path=os.path.join(
        tempfile.mkdtemp(), "test_leaderboard.json"))

    await broker.connect()

    # Open a trade while connected
    setup = TradeSetup(
        symbol="ETHUSD", direction=Direction.LONG,
        entry_price=2_000.0, stop_loss=1_900.0,
        take_profit=2_200.0, position_size=1.0,
    )
    tid, _exec_err = await engine.execute_trade(setup, context={"proposing_strategy": "test"})
    assert tid > 0
    assert len(journal.get_open_trades()) == 1

    # Simulate position closed on exchange while we were "disconnected"
    # (clear broker positions directly to simulate)
    broker._positions.clear()
    engine._last_known_prices["ETHUSD"] = 2_100.0

    # Reconnect
    await broker.connect()

    # Reconcile — needs 2 misses
    await engine._reconcile()  # miss 1/2
    assert len(journal.get_closed_trades()) == 0

    await engine._reconcile()  # miss 2/2 — close it
    closed = journal.get_closed_trades()
    assert len(closed) == 1
    assert closed[0]["exit_reason"] == "exchange_close"
    # P&L: (2100 - 2000) * 1.0 = 100.0
    assert closed[0]["pnl"] == pytest.approx(100.0, abs=0.01)


# ===================================================================
# 5A-3: Engine restart — state preservation
# ===================================================================

@pytest.mark.asyncio
async def test_engine_restart_journal_survives():
    """Open trades survive engine restart (new LabEngine instance, same journal)."""
    # Shared journal (simulates persistent DB)
    journal = EventStore(":memory:")
    broker1 = PaperBroker(initial_balance=10_000.0)
    await broker1.connect()

    # Engine 1: open a trade
    engine1 = LabEngine(broker=broker1, journal=journal, bus=EventBus(),
                        pnl=PnLService(original_deposit=10_000.0))
    engine1.leaderboard = StrategyLeaderboard(persist_path=os.path.join(
        tempfile.mkdtemp(), "lb1.json"))

    setup = TradeSetup(
        symbol="BTCUSD", direction=Direction.LONG,
        entry_price=70_000.0, stop_loss=69_000.0,
        take_profit=72_000.0, position_size=0.01,
    )
    tid, _exec_err = await engine1.execute_trade(setup, context={"proposing_strategy": "test"})
    assert tid > 0

    # "Restart": create new engine with same journal and same broker
    broker2 = broker1  # Same broker — still has the position
    engine2 = LabEngine(broker=broker2, journal=journal, bus=EventBus(),
                        pnl=PnLService(original_deposit=10_000.0))
    engine2.leaderboard = StrategyLeaderboard(persist_path=os.path.join(
        tempfile.mkdtemp(), "lb2.json"))

    # Journal must still show the open trade after "restart"
    open_trades = journal.get_open_trades()
    assert len(open_trades) == 1, "Open trade must survive engine restart"
    assert open_trades[0]["symbol"] == "BTCUSD"

    # Engine 2 can close the trade from Engine 1
    await engine2.close_trade(tid, exit_price=71_000.0, reason="tp_hit")
    assert len(journal.get_closed_trades()) == 1
    assert len(journal.get_open_trades()) == 0


@pytest.mark.asyncio
async def test_leaderboard_seeded_from_prior_results():
    """Trust scores persist via leaderboard file and are loaded by new engine."""
    lb_path = os.path.join(tempfile.mkdtemp(), "leaderboard.json")

    engine1, broker1, journal1 = _make_engine()
    engine1.leaderboard = StrategyLeaderboard(persist_path=lb_path)
    await broker1.connect()

    # Record some wins for a strategy
    engine1.leaderboard.record_win("test_strategy", 100.0)
    engine1.leaderboard.record_win("test_strategy", 50.0)
    initial_trust = engine1.leaderboard.get_strategy("test_strategy")["trust_score"]

    # "Restart": new engine, same leaderboard path
    engine2, _, _ = _make_engine()
    engine2.leaderboard = StrategyLeaderboard(persist_path=lb_path)

    loaded = engine2.leaderboard.get_strategy("test_strategy")
    assert loaded is not None, "Strategy must be loaded from persisted leaderboard"
    assert loaded["trust_score"] == pytest.approx(initial_trust, abs=0.01), (
        "Trust score must survive engine restart"
    )
    assert loaded["total_trades"] == 2


# ===================================================================
# 5A-4: API consistency — REST matches WS snapshot data
# ===================================================================

def test_rest_api_broker_status_consistent():
    """GET /api/broker/status and GET /api/system/health broker section agree."""
    from fastapi.testclient import TestClient

    broker = PaperBroker(initial_balance=10_000.0)
    journal = EventStore(":memory:")
    bus = EventBus()
    pnl = PnLService(original_deposit=10_000.0)
    container = Container(broker=broker, journal=journal, bus=bus, pnl=pnl)
    app = create_app(container)

    with TestClient(app) as client:
        broker_resp = client.get("/api/broker/status")
        health_resp = client.get("/api/system/health")

        assert broker_resp.status_code == 200
        assert health_resp.status_code == 200

        broker_data = broker_resp.json()
        health_broker = health_resp.json()["components"]["broker"]

        # Both must agree on connection status
        broker_connected = broker_data.get("connected", broker_data.get("broker_connected"))
        health_connected = health_broker["status"] == "connected"
        assert broker_connected == health_connected, (
            f"/api/broker/status says connected={broker_connected} "
            f"but /api/system/health says {health_broker['status']}"
        )


def test_lab_positions_matches_broker_positions():
    """GET /api/lab/positions must match broker source of truth."""
    from fastapi.testclient import TestClient

    broker = PaperBroker(initial_balance=10_000.0)
    journal = EventStore(":memory:")
    bus = EventBus()
    pnl = PnLService(original_deposit=10_000.0)
    container = Container(broker=broker, journal=journal, bus=bus, pnl=pnl)
    app = create_app(container)

    with TestClient(app) as client:
        lab_resp = client.get("/api/lab/positions")
        assert lab_resp.status_code == 200
        # No positions initially
        positions = lab_resp.json()["positions"]
        assert isinstance(positions, list)
        assert len(positions) == 0
