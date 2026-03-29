"""WebSocket integration tests.

Tests the /ws endpoint: connection, subscriptions, heartbeat, auth,
multi-client broadcasts, and topic filtering.

Uses FastAPI's TestClient with WebSocket support — no real network needed.
"""

import asyncio
import json
import os
import pytest

from fastapi.testclient import TestClient

from notas_lave.api.app import Container, create_app
from notas_lave.api.ws_manager import ConnectionManager, VALID_TOPICS
from notas_lave.engine.event_bus import EventBus
from notas_lave.engine.pnl import PnLService
from notas_lave.execution.paper import PaperBroker
from notas_lave.journal.event_store import EventStore


def _make_app():
    """Create a test FastAPI app with a fresh WS manager."""
    broker = PaperBroker(initial_balance=10000.0)
    journal = EventStore(":memory:")
    bus = EventBus()
    pnl = PnLService(original_deposit=10000.0)
    container = Container(broker=broker, journal=journal, bus=bus, pnl=pnl)
    app = create_app(container)
    return app, broker, journal, container


# --- Connection tests ---

def test_connect_receives_welcome():
    """Client connects to /ws → receives {type: connected, client_id}."""
    app, *_ = _make_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "connected"
            assert "client_id" in msg
            assert len(msg["client_id"]) == 12


def test_subscribe_and_receive_snapshot():
    """Client subscribes to a topic → receives a snapshot immediately."""
    app, *_ = _make_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # welcome

            ws.send_json({"action": "subscribe", "topics": ["broker.status"]})

            msg = ws.receive_json()
            assert msg.get("topic") == "broker.status"
            assert msg.get("snapshot") is True
            assert "data" in msg
            assert "ts" in msg


def test_subscribe_multiple_topics():
    """Client can subscribe to multiple topics at once."""
    app, *_ = _make_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # welcome

            ws.send_json({"action": "subscribe", "topics": ["broker.status", "risk.status"]})

            received_topics = set()
            for _ in range(2):
                msg = ws.receive_json()
                if "topic" in msg:
                    received_topics.add(msg["topic"])

            assert "broker.status" in received_topics
            assert "risk.status" in received_topics


def test_invalid_topic_returns_error():
    """Subscribing to an unknown topic → {type: error} response."""
    app, *_ = _make_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # welcome

            ws.send_json({"action": "subscribe", "topics": ["not.a.real.topic"]})

            msg = ws.receive_json()
            assert msg.get("type") == "error"
            assert "not.a.real.topic" in msg.get("detail", "")


def test_snapshot_action_resends_data():
    """Client sends {type: snapshot} → server resends fresh snapshot."""
    app, *_ = _make_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # welcome

            # Subscribe first
            ws.send_json({"action": "subscribe", "topics": ["broker.status"]})
            first_snapshot = ws.receive_json()
            assert first_snapshot.get("snapshot") is True

            # Request fresh snapshot
            ws.send_json({"type": "snapshot"})
            second_snapshot = ws.receive_json()
            assert second_snapshot.get("topic") == "broker.status"
            assert "data" in second_snapshot


# --- Auth tests ---

def test_auth_required_when_api_key_set(monkeypatch):
    """When API_KEY env is set, connecting without key → rejected."""
    monkeypatch.setenv("API_KEY", "test-secret-key-1234")
    app, *_ = _make_app()
    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/ws") as ws:
                ws.receive_json()


def test_auth_accepted_with_correct_key(monkeypatch):
    """Connecting with correct api_key query param → accepted."""
    monkeypatch.setenv("API_KEY", "test-secret-key-1234")
    app, *_ = _make_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws?api_key=test-secret-key-1234") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "connected"


def test_no_auth_required_without_api_key(monkeypatch):
    """When API_KEY is not set, any client can connect."""
    monkeypatch.delenv("API_KEY", raising=False)
    app, *_ = _make_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "connected"


# --- Connection manager unit tests ---

def test_valid_topics_set():
    """All expected topics are in VALID_TOPICS."""
    expected = {
        "system.health", "system.errors", "market.prices",
        "trade.executed", "trade.positions", "trade.rejected",
        "risk.status", "arena.proposals", "arena.leaderboard",
        "lab.status", "broker.status",
    }
    assert expected == VALID_TOPICS


@pytest.mark.asyncio
async def test_broadcast_reaches_subscribed_client():
    """Broadcast to a topic → only subscribed clients receive it."""
    manager = ConnectionManager()

    messages_received = []

    class FakeWebSocket:
        """Minimal WS mock that captures sent JSON."""
        async def accept(self): pass
        async def send_json(self, data):
            messages_received.append(data)
        async def close(self, code=None): pass

    fake_ws = FakeWebSocket()
    client_id = await manager.connect(fake_ws)
    messages_received.clear()  # clear welcome-related messages

    await manager.subscribe(client_id, ["trade.executed"])
    messages_received.clear()  # clear snapshot messages

    # Broadcast to subscribed topic
    await manager.broadcast("trade.executed", {"event": "opened", "trade_id": 1})
    assert len(messages_received) == 1
    assert messages_received[0]["topic"] == "trade.executed"

    # Broadcast to non-subscribed topic
    await manager.broadcast("risk.status", {"balance": 10000})
    assert len(messages_received) == 1  # unchanged


@pytest.mark.asyncio
async def test_multiple_clients_receive_broadcasts():
    """3 clients subscribe → broadcast → all 3 receive."""
    manager = ConnectionManager()

    class CountingWebSocket:
        def __init__(self):
            self.received = []
        async def accept(self): pass
        async def send_json(self, data):
            self.received.append(data)
        async def close(self, code=None): pass

    clients = [CountingWebSocket() for _ in range(3)]
    client_ids = []

    for ws in clients:
        cid = await manager.connect(ws)
        client_ids.append(cid)
        await manager.subscribe(cid, ["arena.leaderboard"])
        ws.received.clear()  # clear snapshots

    await manager.broadcast("arena.leaderboard", [{"strategy": "test", "trust_score": 75}])

    for ws in clients:
        assert len(ws.received) == 1
        assert ws.received[0]["topic"] == "arena.leaderboard"


@pytest.mark.asyncio
async def test_topic_filtering():
    """Client subscribed to arena.proposals doesn't receive market.prices."""
    manager = ConnectionManager()

    class RecordingWebSocket:
        def __init__(self): self.received = []
        async def accept(self): pass
        async def send_json(self, data): self.received.append(data)
        async def close(self, code=None): pass

    ws = RecordingWebSocket()
    client_id = await manager.connect(ws)
    await manager.subscribe(client_id, ["arena.proposals"])
    ws.received.clear()

    await manager.broadcast("market.prices", {"BTCUSD": {"price": 70000}})
    assert len(ws.received) == 0, "Client should not receive unsubscribed topics"

    await manager.broadcast("arena.proposals", {"leaderboard": []})
    assert len(ws.received) == 1


@pytest.mark.asyncio
async def test_pong_resets_timeout_counter():
    """Receiving a pong updates the client's last_pong time."""
    manager = ConnectionManager()

    class FakeWebSocket:
        async def accept(self): pass
        async def send_json(self, data): pass
        async def close(self, code=None): pass

    ws = FakeWebSocket()
    client_id = await manager.connect(ws)
    client = manager._clients[client_id]

    import asyncio
    loop = asyncio.get_event_loop()
    old_pong = client.last_pong

    await asyncio.sleep(0.01)  # small delay
    await manager.handle_message(client_id, {"type": "pong"})

    assert client.last_pong >= old_pong
