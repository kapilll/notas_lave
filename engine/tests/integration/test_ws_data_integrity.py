"""WebSocket data integrity tests.

Verify that WS broadcasts carry the same data as REST endpoints,
and that trade events flow correctly end-to-end.
"""

import asyncio
import pytest

from fastapi.testclient import TestClient

from notas_lave.api.app import Container, create_app
from notas_lave.api.ws_manager import ConnectionManager
from notas_lave.core.models import Direction, TradeSetup
from notas_lave.engine.event_bus import EventBus
from notas_lave.engine.leaderboard import StrategyLeaderboard
from notas_lave.engine.pnl import PnLService
from notas_lave.execution.paper import PaperBroker
from notas_lave.journal.event_store import EventStore


def _make_app():
    broker = PaperBroker(initial_balance=10000.0)
    journal = EventStore(":memory:")
    bus = EventBus()
    pnl = PnLService(original_deposit=10000.0)
    container = Container(broker=broker, journal=journal, bus=bus, pnl=pnl)
    app = create_app(container)
    return app, broker, journal, container


def test_ws_broker_status_matches_rest_endpoint():
    """Subscribe to broker.status → data matches /api/system/health broker section."""
    app, broker, *_ = _make_app()
    with TestClient(app) as client:
        # Get REST data
        rest_response = client.get("/api/system/health")
        assert rest_response.status_code == 200
        rest_broker = rest_response.json()["components"]["broker"]

        # Get WS snapshot
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # welcome
            ws.send_json({"action": "subscribe", "topics": ["broker.status"]})
            snapshot = ws.receive_json()

            ws_data = snapshot["data"]
            assert ws_data["connected"] == (rest_broker["status"] == "connected")


def test_ws_risk_status_snapshot_has_required_fields():
    """risk.status snapshot must have balance, pnl, pnl_pct, drawdown_pct."""
    app, *_ = _make_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # welcome
            ws.send_json({"action": "subscribe", "topics": ["risk.status"]})
            snapshot = ws.receive_json()

            data = snapshot["data"]
            assert "balance" in data
            assert "pnl" in data
            assert "pnl_pct" in data
            assert "drawdown_pct" in data


def test_ws_trade_positions_snapshot_is_list():
    """trade.positions snapshot must be a list."""
    app, *_ = _make_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # welcome
            ws.send_json({"action": "subscribe", "topics": ["trade.positions"]})
            snapshot = ws.receive_json()

            assert isinstance(snapshot["data"], list)


def test_ws_arena_leaderboard_snapshot_is_list():
    """arena.leaderboard snapshot must be a list (possibly empty)."""
    app, *_ = _make_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # welcome
            ws.send_json({"action": "subscribe", "topics": ["arena.leaderboard"]})
            snapshot = ws.receive_json()

            assert isinstance(snapshot["data"], list)


def test_ws_message_has_timestamp():
    """Every WS message must have a 'ts' ISO timestamp field."""
    app, *_ = _make_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # welcome (no ts required on this one)
            ws.send_json({"action": "subscribe", "topics": ["broker.status"]})
            snapshot = ws.receive_json()

            assert "ts" in snapshot, "WS messages must include a timestamp"
            # Validate it's parseable ISO format
            from datetime import datetime
            datetime.fromisoformat(snapshot["ts"].replace("Z", "+00:00"))


# --- End-to-end broadcast tests ---

@pytest.mark.asyncio
async def test_broadcast_reaches_client_on_trade_executed():
    """Execute a trade → client subscribed to trade.executed receives it."""
    from notas_lave.engine.lab import LabEngine
    import os, tempfile

    broker = PaperBroker(initial_balance=10000.0)
    journal = EventStore(":memory:")
    bus = EventBus()
    pnl = PnLService(original_deposit=10000.0)
    engine = LabEngine(broker=broker, journal=journal, bus=bus, pnl=pnl)
    engine.leaderboard = StrategyLeaderboard(persist_path=os.path.join(
        tempfile.mkdtemp(), "test_leaderboard.json"))

    await broker.connect()

    received = []

    class FakeWebSocket:
        async def accept(self): pass
        async def send_json(self, data): received.append(data)
        async def close(self, code=None): pass

    # Subscribe directly to the module-level ws_manager
    from notas_lave.api.ws_manager import ws_manager
    ws = FakeWebSocket()
    client_id = await ws_manager.connect(ws)
    await ws_manager.subscribe(client_id, ["trade.executed"])
    received.clear()  # clear snapshots

    # Execute a trade
    setup = TradeSetup(
        symbol="BTCUSD", direction=Direction.LONG,
        entry_price=70000.0, stop_loss=69000.0,
        take_profit=72000.0, position_size=0.01,
    )
    tid = await engine.execute_trade(setup, context={"proposing_strategy": "test"})
    assert tid > 0

    # Should have received a trade.executed broadcast
    trade_msgs = [m for m in received if m.get("topic") == "trade.executed"]
    assert len(trade_msgs) >= 1
    assert trade_msgs[0]["data"]["event"] == "opened"
    assert trade_msgs[0]["data"]["symbol"] == "BTCUSD"

    await ws_manager.disconnect(client_id)


@pytest.mark.asyncio
async def test_broadcast_on_trade_close():
    """Close a trade → client receives trade.executed (closed) + arena.leaderboard + risk.status."""
    from notas_lave.engine.lab import LabEngine
    import os, tempfile

    broker = PaperBroker(initial_balance=10000.0)
    journal = EventStore(":memory:")
    bus = EventBus()
    pnl = PnLService(original_deposit=10000.0)
    engine = LabEngine(broker=broker, journal=journal, bus=bus, pnl=pnl)
    engine.leaderboard = StrategyLeaderboard(persist_path=os.path.join(
        tempfile.mkdtemp(), "test_leaderboard.json"))

    await broker.connect()

    from notas_lave.api.ws_manager import ws_manager
    received = []

    class FakeWebSocket:
        async def accept(self): pass
        async def send_json(self, data): received.append(data)
        async def close(self, code=None): pass

    ws = FakeWebSocket()
    client_id = await ws_manager.connect(ws)
    await ws_manager.subscribe(client_id, [
        "trade.executed", "arena.leaderboard", "risk.status", "trade.positions"
    ])
    received.clear()

    # Execute and close a trade
    setup = TradeSetup(
        symbol="ETHUSD", direction=Direction.SHORT,
        entry_price=2000.0, stop_loss=2100.0,
        take_profit=1900.0, position_size=1.0,
    )
    tid = await engine.execute_trade(setup, context={"proposing_strategy": "test"})
    received.clear()  # clear open broadcasts

    await engine.close_trade(tid, exit_price=1950.0, reason="tp_hit")

    topics_received = {m.get("topic") for m in received if "topic" in m}
    assert "trade.executed" in topics_received
    assert "arena.leaderboard" in topics_received

    # Verify the close event content
    close_msgs = [m for m in received
                  if m.get("topic") == "trade.executed" and m["data"].get("event") == "closed"]
    assert len(close_msgs) == 1
    assert close_msgs[0]["data"]["pnl"] == pytest.approx(50.0, abs=0.01)  # (2000-1950)*1.0

    await ws_manager.disconnect(client_id)


@pytest.mark.asyncio
async def test_no_message_loss_under_rapid_trades():
    """Execute 5 trades → client receives exactly 5 trade.executed open events."""
    from notas_lave.engine.lab import LabEngine
    import os, tempfile

    broker = PaperBroker(initial_balance=100000.0)
    journal = EventStore(":memory:")
    bus = EventBus()
    pnl = PnLService(original_deposit=100000.0)
    engine = LabEngine(broker=broker, journal=journal, bus=bus, pnl=pnl)
    engine.leaderboard = StrategyLeaderboard(persist_path=os.path.join(
        tempfile.mkdtemp(), "test_leaderboard.json"))

    await broker.connect()

    from notas_lave.api.ws_manager import ws_manager
    received = []

    class FakeWebSocket:
        async def accept(self): pass
        async def send_json(self, data): received.append(data)
        async def close(self, code=None): pass

    ws = FakeWebSocket()
    client_id = await ws_manager.connect(ws)
    await ws_manager.subscribe(client_id, ["trade.executed"])
    received.clear()

    symbols = ["BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "ADAUSD"]
    for symbol in symbols:
        setup = TradeSetup(
            symbol=symbol, direction=Direction.LONG,
            entry_price=100.0, stop_loss=95.0,
            take_profit=110.0, position_size=0.1,
        )
        await engine.execute_trade(setup, context={"proposing_strategy": "test"})

    open_events = [m for m in received
                   if m.get("topic") == "trade.executed"
                   and m["data"].get("event") == "opened"]
    assert len(open_events) == 5, (
        f"Expected 5 trade.executed open events, got {len(open_events)}"
    )

    await ws_manager.disconnect(client_id)
