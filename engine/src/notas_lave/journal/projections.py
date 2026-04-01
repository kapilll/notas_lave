"""Projections — read-only views rebuilt from events.

These functions derive analytics from the append-only event store.
If a projection has a bug, fix it and re-run — events are the truth.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .event_store import EventStore


def trade_summary(store: EventStore) -> dict:
    """Compute overall trading summary from events."""
    closed = store.get_closed_trades(limit=10000)
    open_trades = store.get_open_trades()

    wins = [t for t in closed if t.get("pnl", 0) > 0]
    losses = [t for t in closed if t.get("pnl", 0) <= 0]
    total_pnl = sum(t.get("pnl", 0) for t in closed)
    total = len(closed)

    return {
        "total_trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / total * 100, 1) if total > 0 else 0.0,
        "total_pnl": round(total_pnl, 2),
        "open_trades": len(open_trades),
    }


def strategy_performance(store: EventStore) -> dict[str, dict]:
    """Compute per-strategy performance from signal + close events."""
    conn = store._conn

    # Get signal data (strategy_name) joined with close data (pnl)
    signal_rows = conn.execute(
        "SELECT trade_id, data FROM trade_events WHERE event_type = 'signal'"
    ).fetchall()

    close_rows = conn.execute(
        "SELECT trade_id, data FROM trade_events WHERE event_type = 'closed'"
    ).fetchall()

    close_map = {r["trade_id"]: json.loads(r["data"]) for r in close_rows}

    stats: dict[str, dict] = {}
    for row in signal_rows:
        tid = row["trade_id"]
        if tid not in close_map:
            continue

        signal_data = json.loads(row["data"])
        close_data = close_map[tid]
        name = signal_data.get("strategy_name", "unknown")
        pnl = close_data.get("pnl", 0)

        if name not in stats:
            stats[name] = {"wins": 0, "losses": 0, "total_pnl": 0.0}

        if pnl > 0:
            stats[name]["wins"] += 1
        else:
            stats[name]["losses"] += 1
        stats[name]["total_pnl"] += pnl

    return stats
