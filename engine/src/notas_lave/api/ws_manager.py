"""WebSocket connection manager — topic-based pub/sub for live dashboard data.

PROTOCOL:
  Client → Server: {"action": "subscribe", "topics": ["market.prices", "arena.proposals"]}
  Client → Server: {"type": "pong"}
  Server → Client: {"topic": "market.prices", "data": {...}, "ts": "ISO"}
  Server → Client: {"type": "ping"}

TOPICS:
  system.health    — Health + version + component status (every 30s)
  system.errors    — On error: {component, error, timestamp}
  market.prices    — All instrument prices + staleness age
  trade.executed   — Trade open/close: full trade record
  trade.positions  — Current open positions from broker
  trade.rejected   — Broker rejection: {symbol, reason, proposal}
  risk.status      — P&L, drawdown, capacity
  arena.proposals  — Active proposals with scores (per tick)
  arena.leaderboard — Trust scores, strategy stats (on trade result)
  lab.status       — Engine running/stopped, pace, errors
  broker.status    — Connected/disconnected + last success

HEARTBEAT:
  Server pings every 15s.
  Client must pong within 45s or gets disconnected.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 15        # ping every 15s
HEARTBEAT_TIMEOUT = 45         # disconnect if no pong in 45s
VALID_TOPICS = {
    "system.health", "system.errors",
    "market.prices",
    "trade.executed", "trade.positions", "trade.rejected",
    "risk.status",
    "arena.proposals", "arena.leaderboard",
    "lab.status",
    "broker.status",
}


@dataclass
class _Client:
    """Tracks one connected WebSocket client."""
    ws: WebSocket
    client_id: str
    topics: set[str] = field(default_factory=set)
    last_pong: float = field(default_factory=lambda: asyncio.get_event_loop().time())
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class ConnectionManager:
    """Manages all WebSocket connections with topic-based subscriptions.

    Usage:
        manager = ConnectionManager()

        # In WS endpoint:
        await manager.connect(websocket)

        # From lab engine or routes:
        await manager.broadcast("trade.executed", {"trade_id": 42, ...})
    """

    def __init__(self) -> None:
        self._clients: dict[str, _Client] = {}
        self._snapshot_providers: dict[str, Callable[[], Coroutine]] = {}
        self._heartbeat_task: asyncio.Task | None = None

    def register_snapshot(self, topic: str, fn: Callable[[], Coroutine]) -> None:
        """Register an async snapshot provider for a topic.

        Called on subscribe to give the client full state immediately.
        """
        self._snapshot_providers[topic] = fn

    async def connect(self, ws: WebSocket) -> str:
        """Accept a new WebSocket connection. Returns client_id."""
        await ws.accept()
        client_id = uuid.uuid4().hex[:12]
        loop = asyncio.get_event_loop()
        self._clients[client_id] = _Client(ws=ws, client_id=client_id,
                                            last_pong=loop.time())
        logger.info("[WS] Client %s connected (%d total)", client_id, len(self._clients))

        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        return client_id

    async def disconnect(self, client_id: str) -> None:
        """Remove a client."""
        self._clients.pop(client_id, None)
        logger.info("[WS] Client %s disconnected (%d remaining)", client_id, len(self._clients))

    async def subscribe(self, client_id: str, topics: list[str]) -> None:
        """Subscribe a client to topics and send snapshots."""
        client = self._clients.get(client_id)
        if not client:
            return

        valid = [t for t in topics if t in VALID_TOPICS]
        invalid = [t for t in topics if t not in VALID_TOPICS]
        if invalid:
            await self._send(client, {"type": "error", "detail": f"Unknown topics: {invalid}"})

        client.topics.update(valid)
        logger.info("[WS] Client %s subscribed to %s", client_id, valid)

        # Send snapshot for each subscribed topic
        for topic in valid:
            provider = self._snapshot_providers.get(topic)
            if provider:
                try:
                    data = await provider()
                    await self._send(client, {
                        "topic": topic,
                        "data": data,
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "snapshot": True,
                    })
                except Exception as e:
                    logger.warning("[WS] Snapshot failed for %s: %s", topic, e)

    async def broadcast(self, topic: str, data: Any) -> None:
        """Broadcast to all clients subscribed to this topic."""
        if not self._clients:
            return

        message = {
            "topic": topic,
            "data": data,
            "ts": datetime.now(timezone.utc).isoformat(),
        }

        # Snapshot of keys to avoid mutation during iteration
        client_ids = list(self._clients.keys())
        for client_id in client_ids:
            client = self._clients.get(client_id)
            if client and topic in client.topics:
                try:
                    await self._send(client, message)
                except Exception:
                    await self.disconnect(client_id)

    async def handle_message(self, client_id: str, message: dict) -> None:
        """Process an incoming message from a client."""
        msg_type = message.get("type") or message.get("action")

        if msg_type == "pong":
            client = self._clients.get(client_id)
            if client:
                client.last_pong = asyncio.get_event_loop().time()

        elif msg_type == "subscribe":
            topics = message.get("topics", [])
            await self.subscribe(client_id, topics)

        elif msg_type == "snapshot":
            # Client requests fresh snapshot for all their topics
            client = self._clients.get(client_id)
            if client:
                await self.subscribe(client_id, list(client.topics))

        else:
            logger.debug("[WS] Unknown message from %s: %s", client_id, msg_type)

    async def _send(self, client: _Client, data: dict) -> None:
        """Send JSON to a single client, serializing safely."""
        async with client._lock:
            await client.ws.send_json(data)

    async def _heartbeat_loop(self) -> None:
        """Ping all clients every 15s. Disconnect those that don't pong in 45s."""
        while self._clients:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            loop = asyncio.get_event_loop()
            now = loop.time()

            stale = [
                cid for cid, c in list(self._clients.items())
                if now - c.last_pong > HEARTBEAT_TIMEOUT
            ]
            for client_id in stale:
                client = self._clients.get(client_id)
                if client:
                    logger.warning("[WS] Client %s timed out (no pong in %ds)",
                                   client_id, HEARTBEAT_TIMEOUT)
                    try:
                        await client.ws.close(code=1001)
                    except Exception:
                        pass
                    await self.disconnect(client_id)

            # Ping survivors
            for client_id, client in list(self._clients.items()):
                try:
                    await self._send(client, {"type": "ping"})
                except Exception:
                    await self.disconnect(client_id)

    @property
    def client_count(self) -> int:
        return len(self._clients)


# Module-level singleton — used by lab.py and routes
ws_manager = ConnectionManager()
