# Database & Storage

> Last verified against code: 2026-03-28

## Overview

Two SQLite databases, two journal systems. This is a known architectural issue (ML-02).

```
notas_lave_lab_v2.db          notas_lave.db
(raw sqlite3)                 (SQLAlchemy ORM)
     |                              |
EventStore                    database.py
(Lab Engine writes here)      (Learning Engine reads here)
     |                              |
trade_events table            signal_logs, trade_logs,
trade_id_seq table            prediction_logs, ab_tests,
                              risk_state, token_usage
```

**Problem:** Lab trades go into EventStore. Learning engine queries TradeLog. They never see each other's data.

## EventStore (journal/event_store.py)

Append-only event log. Used by Lab Engine via `ITradeJournal` protocol.

**DB file:** `engine/notas_lave_lab_v2.db`

**Tables:**
```sql
CREATE TABLE trade_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,    -- 'signal', 'opened', 'closed', 'graded'
    timestamp TEXT NOT NULL,
    data TEXT NOT NULL           -- JSON blob
);

CREATE TABLE trade_id_seq (
    next_id INTEGER NOT NULL DEFAULT 1
);
```

**Event lifecycle:** `signal` → `opened` → `closed` → `graded`

**Rules:**
- Never UPDATE — only INSERT new events
- State reconstructed by replaying events per trade_id
- `get_open_trades()` = opened events without matching closed events

## SQLAlchemy Database (journal/database.py)

Full ORM with structured tables. Used by Learning Engine, API dashboard, accuracy tracker.

**DB file:** Configured via `config.db_url` (default: `sqlite+aiosqlite:///./notas_lave.db`)

**Tables:**

### signal_logs
Every signal evaluation, even non-trades.
```
id, timestamp, symbol, timeframe, regime, composite_score, direction,
agreeing_strategies, total_strategies, signals_json, claude_action,
claude_confidence, claude_reasoning, risk_passed, risk_rejections,
candle_timestamp, candle_close, should_trade
```

### trade_logs
Completed trades — core of learning engine.
```
id, signal_log_id (FK), opened_at, closed_at, symbol, timeframe,
direction, regime, entry_price, stop_loss, take_profit, exit_price,
position_size, pnl, pnl_pct, duration_seconds, max_favorable,
max_adverse, exit_reason, confluence_score, claude_confidence,
strategies_agreed (JSON), outcome_grade, lessons_learned
```

### prediction_logs
Signal accuracy tracking (like ML model evaluation).
```
id, timestamp, symbol, timeframe, strategy_name, predicted_direction,
entry_price, stop_loss, take_profit, confluence_score, regime,
actual_direction, outcome, price_after_n, max_favorable, max_adverse,
direction_correct, target_hit, resolved, resolved_at, candles_to_resolve
```

### ab_tests / ab_test_results
Shadow-mode parameter comparison.

### risk_state
Persisted risk manager state (survives restarts).
```
id, updated_at, starting_balance, current_balance, total_pnl, peak_balance
```

### token_usage
Claude API cost tracking.
```
id, timestamp, category, purpose, model, tokens_in, tokens_out,
estimated_cost_usd, metadata_json
```

### performance_snapshots
**DEPRECATED** — table exists but is never written to or read.

## Session Management

```python
# CQ-01: Session factory, not singleton
_engines: dict[str, object] = {}
_factories: dict[str, object] = {}

# CQ-24: ContextVar for per-task DB selection
_active_db_key: ContextVar[str] = ContextVar("_active_db_key", default="default")

# Usage:
db = get_db()           # Returns scoped session for current context
with get_session():     # Context manager with auto-commit/rollback
```

## JSON State Files

Stored in `engine/data/` (not git-tracked). Validated via Pydantic schemas in `journal/schemas.py`.

| File | Purpose | Schema |
|------|---------|--------|
| `learned_state.json` | Persisted regime weights | `LearnedState` |
| `learned_blacklists.json` | Dynamic strategy blacklists | `LearnedBlacklists` |
| `optimizer_results.json` | Walk-forward optimization results | `OptimizerResults` |
| `rate_limit_state.json` | TwelveData API call counter | `RateLimitState` |
| `adjustment_state.json` | Last weight/blacklist adjustment time | `AdjustmentState` |
| `lab_pace.txt` | Current Lab pace setting | Plain text |

## SQLite Configuration

- **WAL mode** enabled on all connections (better concurrent read/write)
- **Checkpoint** function exists (`checkpoint_wal()`) but is NOT scheduled
- **Backup** function exists (`backup_database()`) but is NOT scheduled
- **WAL + SHM files** (`notas_lave.db-wal`, `notas_lave.db-shm`) are expected in the working directory

## Rules

- **Never UPDATE the EventStore.** Append events only.
- **Always use `get_db()` or `get_session()`** — never create raw sessions.
- **JSON state files must use `safe_load_json` / `safe_save_json`** with Pydantic schemas.
- **Database files must be chmod 600** — the engine checks this on startup (SE-23).
- **Backups go to `engine/data/backups/`** — keep last 7 days.
- **Lab and Production use separate databases** — `use_db("lab")` / `use_db("default")`.
