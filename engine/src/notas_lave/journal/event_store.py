"""Append-only event store — the v2 trade journal.

RULES:
- Every operation is an INSERT. Never UPDATE, never DELETE.
- State is reconstructed by replaying events.
- Each trade has a lifecycle: signal -> opened -> closed -> graded
- All events are timestamped and immutable once written.

Implements ITradeJournal from core/ports.py.
"""

import json
import sqlite3
from datetime import datetime, timezone

from ..core.models import Signal, TradeSetup

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trade_events_trade_id
    ON trade_events(trade_id);
CREATE INDEX IF NOT EXISTS idx_trade_events_type
    ON trade_events(event_type);
"""

_TRADE_ID_SEQ = """
CREATE TABLE IF NOT EXISTS trade_id_seq (
    next_id INTEGER NOT NULL DEFAULT 1
);
"""


class EventStore:
    """Append-only trade event store backed by SQLite."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.executescript(_TRADE_ID_SEQ)
        # Initialize sequence if empty
        row = self._conn.execute("SELECT COUNT(*) FROM trade_id_seq").fetchone()
        if row[0] == 0:
            self._conn.execute("INSERT INTO trade_id_seq (next_id) VALUES (1)")
            self._conn.commit()

    def _next_trade_id(self) -> int:
        cur = self._conn.execute("SELECT next_id FROM trade_id_seq")
        trade_id = cur.fetchone()[0]
        self._conn.execute(
            "UPDATE trade_id_seq SET next_id = ?", (trade_id + 1,)
        )
        return trade_id

    def _append(self, trade_id: int, event_type: str, data: dict) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO trade_events (trade_id, event_type, timestamp, data) "
            "VALUES (?, ?, ?, ?)",
            (trade_id, event_type, now, json.dumps(data)),
        )
        self._conn.commit()

    def event_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM trade_events").fetchone()
        return row[0]

    # -- ITradeJournal implementation --

    def record_signal(self, signal: Signal) -> int:
        trade_id = self._next_trade_id()
        self._append(trade_id, "signal", {
            "strategy_name": signal.strategy_name,
            "direction": signal.direction.value if signal.direction else None,
            "score": signal.score,
            "entry_price": signal.entry_price,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "reason": signal.reason,
            "metadata": signal.metadata,
        })
        self._conn.commit()
        return trade_id

    def record_open(self, trade_id: int, setup: TradeSetup, context: dict | None = None) -> None:
        ctx = context or {}
        self._append(trade_id, "opened", {
            "symbol": setup.symbol,
            "direction": setup.direction.value,
            "entry_price": setup.entry_price,
            "stop_loss": setup.stop_loss,
            "take_profit": setup.take_profit,
            "position_size": setup.position_size,
            "confluence_score": setup.confluence_score,
            "proposing_strategy": ctx.get("proposing_strategy", ""),
            "timeframe": ctx.get("timeframe", ""),
            "strategy_score": ctx.get("strategy_score", 0),
            "competing_proposals": ctx.get("competing_proposals", 0),
        })

    def record_close(
        self, trade_id: int, exit_price: float, reason: str, pnl: float,
    ) -> None:
        self._append(trade_id, "closed", {
            "exit_price": exit_price,
            "exit_reason": reason,
            "pnl": pnl,
        })

    def record_grade(
        self, trade_id: int, grade: str, lesson: str,
    ) -> None:
        self._append(trade_id, "graded", {
            "grade": grade,
            "lesson": lesson,
        })

    def get_open_trades(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT trade_id, data FROM trade_events WHERE event_type = 'opened'"
        ).fetchall()

        closed_ids = {
            r[0] for r in self._conn.execute(
                "SELECT trade_id FROM trade_events WHERE event_type = 'closed'"
            ).fetchall()
        }

        result = []
        for row in rows:
            if row["trade_id"] not in closed_ids:
                data = json.loads(row["data"])
                data["trade_id"] = row["trade_id"]
                result.append(data)
        return result

    def get_closed_trades(self, limit: int = 50) -> list[dict]:
        # Get all opened events for closed trades (include timestamps)
        closed_rows = self._conn.execute(
            "SELECT trade_id, data, timestamp FROM trade_events "
            "WHERE event_type = 'closed' "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()

        if not closed_rows:
            return []

        trade_ids = [r["trade_id"] for r in closed_rows]

        # Get opened data for each (with timestamp)
        opened_map: dict[int, dict] = {}
        opened_ts: dict[int, str] = {}
        for tid in trade_ids:
            row = self._conn.execute(
                "SELECT data, timestamp FROM trade_events "
                "WHERE trade_id = ? AND event_type = 'opened'",
                (tid,),
            ).fetchone()
            if row:
                opened_map[tid] = json.loads(row["data"])
                opened_ts[tid] = row["timestamp"]

        # Get grade data for each
        grade_map: dict[int, dict] = {}
        for tid in trade_ids:
            row = self._conn.execute(
                "SELECT data FROM trade_events "
                "WHERE trade_id = ? AND event_type = 'graded'",
                (tid,),
            ).fetchone()
            if row:
                grade_map[tid] = json.loads(row["data"])

        # Get signal data for each (strategy, timeframe, regime)
        signal_map: dict[int, dict] = {}
        for tid in trade_ids:
            row = self._conn.execute(
                "SELECT data FROM trade_events "
                "WHERE trade_id = ? AND event_type = 'signal'",
                (tid,),
            ).fetchone()
            if row:
                signal_map[tid] = json.loads(row["data"])

        result = []
        for closed_row in closed_rows:
            tid = closed_row["trade_id"]
            closed_data = json.loads(closed_row["data"])
            opened_data = opened_map.get(tid, {})
            grade_data = grade_map.get(tid, {})
            signal_data = signal_map.get(tid, {})
            metadata = signal_data.get("metadata", {})

            # Strategy name: prefer opened event (new), fallback to signal (old)
            strategy = (
                opened_data.get("proposing_strategy")
                or signal_data.get("strategy_name")
                or metadata.get("proposing_strategy")
                or ""
            )
            # Timeframe: prefer opened event (new), fallback to signal metadata
            timeframe = (
                opened_data.get("timeframe")
                or metadata.get("timeframe")
                or ""
            )

            result.append({
                "trade_id": tid,
                "symbol": opened_data.get("symbol", ""),
                "direction": opened_data.get("direction", ""),
                "entry_price": opened_data.get("entry_price", 0),
                "exit_price": closed_data.get("exit_price", 0),
                "stop_loss": opened_data.get("stop_loss", 0),
                "take_profit": opened_data.get("take_profit", 0),
                "position_size": opened_data.get("position_size", 0),
                "confluence_score": opened_data.get("confluence_score", 0),
                "pnl": closed_data.get("pnl", 0),
                "exit_reason": closed_data.get("exit_reason", ""),
                # Timestamps
                "opened_at": opened_ts.get(tid, ""),
                "closed_at": closed_row["timestamp"],
                # Strategy context
                "proposing_strategy": strategy,
                "timeframe": timeframe,
                "strategy_score": opened_data.get("strategy_score", metadata.get("strategy_score", 0)),
                "competing_proposals": opened_data.get("competing_proposals", metadata.get("competing_proposals", 0)),
                # Grading
                "outcome_grade": grade_data.get("grade", ""),
                "lessons_learned": grade_data.get("lesson", ""),
                # Legacy learning context
                "regime": metadata.get("regime", ""),
            })

        return result
