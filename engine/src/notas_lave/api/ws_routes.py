"""WebSocket route — /ws endpoint with auth, subscriptions, heartbeat.

Auth: If API_KEY env var is set, clients must pass ?api_key=<key>
in the WebSocket URL. Example: ws://localhost:8000/ws?api_key=secret

Connection lifecycle:
  1. Client connects to /ws (with ?api_key if auth enabled)
  2. Server accepts, sends {"type": "connected", "client_id": "..."}
  3. Client sends {"action": "subscribe", "topics": ["trade.executed", ...]}
  4. Server sends snapshot for each topic immediately
  5. Server sends {"type": "ping"} every 15s
  6. Client must reply {"type": "pong"} within 45s
  7. On disconnect: client removed
"""

import logging
import os

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from .ws_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(
    ws: WebSocket,
    api_key: str | None = Query(default=None),
):
    """Main WebSocket endpoint for real-time dashboard data."""
    # Auth check — only if API_KEY env var is set
    required_key = os.environ.get("API_KEY", "")
    if required_key and api_key != required_key:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning("[WS] Rejected unauthenticated connection")
        return

    # Register snapshot providers on first use
    _ensure_snapshots_registered()

    client_id = await ws_manager.connect(ws)
    try:
        # Welcome message
        await ws.send_json({"type": "connected", "client_id": client_id})

        # Message loop
        while True:
            try:
                message = await ws.receive_json()
                await ws_manager.handle_message(client_id, message)
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.warning("[WS] Client %s message error: %s", client_id, e)
                break
    finally:
        await ws_manager.disconnect(client_id)


def _ensure_snapshots_registered():
    """Register snapshot providers if not already done.

    These are lazy to avoid circular imports at module level.
    Each snapshot provider fetches current state for a topic.
    """
    from .app import get_container

    if "system.health" in ws_manager._snapshot_providers:
        return  # already registered

    async def snapshot_system_health():
        from datetime import datetime, timezone
        from ..data.market_data import market_data
        try:
            c = get_container()
            md_failures = dict(market_data._consecutive_failures)
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "broker_connected": c.broker.is_connected,
                "lab_running": c.lab_engine is not None and c.lab_engine.is_running,
                "market_data_status": "degraded" if sum(md_failures.values()) > 0 else "ok",
            }
        except Exception:
            return {}

    async def snapshot_market_prices():
        from ..data.market_data import market_data
        from ..data.instruments import INSTRUMENTS
        results = {}
        for symbol in list(INSTRUMENTS.keys())[:18]:
            try:
                candles = await market_data.get_candles(symbol, "1m", limit=1)
                if candles:
                    results[symbol] = {"price": candles[-1].close,
                                       "ts": candles[-1].timestamp.isoformat()}
            except Exception:
                pass
        return results

    async def snapshot_trade_positions():
        try:
            c = get_container()
            positions = await c.broker.get_positions()
            return [
                {"symbol": p.symbol, "direction": p.direction.value,
                 "quantity": p.quantity, "entry_price": p.entry_price,
                 "current_price": p.current_price, "pnl": round(p.unrealized_pnl, 4)}
                for p in positions
            ]
        except Exception:
            return []

    async def snapshot_risk_status():
        try:
            c = get_container()
            balance = await c.broker.get_balance()
            result = c.pnl.calculate(balance.total)
            return {
                "balance": balance.total,
                "pnl": round(result.pnl, 4),
                "pnl_pct": round(result.pnl_pct, 2),
                "drawdown_pct": round(result.drawdown_from_peak_pct, 2),
            }
        except Exception:
            return {}

    async def snapshot_arena_proposals():
        try:
            c = get_container()
            if c.lab_engine:
                return c.lab_engine.get_arena_status()
        except Exception:
            pass
        return {}

    async def snapshot_arena_leaderboard():
        try:
            c = get_container()
            if c.lab_engine:
                return c.lab_engine.leaderboard.get_leaderboard()
        except Exception:
            pass
        return []

    async def snapshot_lab_status():
        try:
            c = get_container()
            if c.lab_engine:
                return await c.lab_engine.get_status()
        except Exception:
            pass
        return {}

    async def snapshot_broker_status():
        try:
            c = get_container()
            return {"connected": c.broker.is_connected, "name": c.broker.name}
        except Exception:
            return {}

    ws_manager.register_snapshot("system.health", snapshot_system_health)
    ws_manager.register_snapshot("market.prices", snapshot_market_prices)
    ws_manager.register_snapshot("trade.positions", snapshot_trade_positions)
    ws_manager.register_snapshot("risk.status", snapshot_risk_status)
    ws_manager.register_snapshot("arena.proposals", snapshot_arena_proposals)
    ws_manager.register_snapshot("arena.leaderboard", snapshot_arena_leaderboard)
    ws_manager.register_snapshot("lab.status", snapshot_lab_status)
    ws_manager.register_snapshot("broker.status", snapshot_broker_status)
