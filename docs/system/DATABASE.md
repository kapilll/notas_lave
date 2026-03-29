# Database & Storage

> Last verified against code: v2.0.0 (2026-03-29)

## Overview

Two SQLite databases, bridged by Lab Engine. TradeLog is the single source of truth for structured trade data; EventStore is the append-only audit log.

```
EventStore (notas_lave_lab_v2.db)   TradeLog (notas_lave.db)
    raw sqlite3                          SQLAlchemy ORM
    ITradeJournal                        database.py
         │                                   │
    trade_events                    signal_logs, trade_logs,
    trade_id_seq                    prediction_logs, risk_state
         │                                   │
    Lab Engine writes               Lab Engine ALSO writes (dual-write)
    Broker truth → journal          Learning Engine reads from here
```

## EventStore (`journal/event_store.py`)

Append-only event log. The audit trail — never modified, only appended.

**DB file:** `engine/notas_lave_lab_v2.db` (in-memory `:memory:` in tests)

**Tables:**
```sql
CREATE TABLE trade_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,    -- 'signal', 'opened', 'closed', 'graded'
    timestamp TEXT NOT NULL,
    data TEXT NOT NULL           -- JSON blob
);
CREATE TABLE trade_id_seq (next_id INTEGER NOT NULL DEFAULT 1);
```

**Event lifecycle:** `signal` → `opened` → `closed` → `graded`

**Rules:**
- Never UPDATE — only INSERT new events
- State reconstructed by replaying events per trade_id
- `get_open_trades()` = opened events without matching closed events

## SQLAlchemy Database (`journal/database.py`)

Structured ORM tables. Single source of truth for learning, API, and analysis.

**DB file:** Configured via `config.db_url` (default: `sqlite:///./notas_lave.db`)

### TradeLog (primary table)

```python
class TradeLog(Base):
    __tablename__ = "trade_logs"

    id               # Primary key — maps to EventStore trade_id
    signal_log_id    # FK to signal_logs
    opened_at / closed_at
    symbol, timeframe, direction, regime

    # Prices
    entry_price, stop_loss, take_profit, exit_price, position_size

    # Phase 2: Broker-truth fields (actual fill data from exchange)
    filled_price     # Actual fill price (may differ from entry_price)
    filled_quantity  # Actual filled quantity
    broker_order_id  # Exchange order ID for cross-reference
    contract_size    # From InstrumentSpec (Gold=100, crypto=1)

    # P&L — formula: (exit-entry)*position_size*contract_size (direction-adjusted)
    pnl, pnl_pct

    exit_reason      # tp_hit, sl_hit, exchange_close, dup_cleanup
    outcome_grade    # A, B, C, D, F

    # Arena attribution
    proposing_strategy    # Which of the 6 strategies proposed this trade
    strategy_score        # Signal score at entry
    strategy_factors      # JSON: what factors aligned
    competing_proposals   # How many other strategies also proposed
```

### Why `contract_size` matters

Gold (XAUUSD) has `contract_size=100` (100 troy oz per lot). Without it, P&L is 100x wrong.
BTC/ETH have `contract_size=1`. Always use `InstrumentSpec.calculate_pnl()` or the lab.py formula:

```python
pnl = (exit_price - entry_price if LONG else entry_price - exit_price)
      * position_size * contract_size
```

### Closing trades (Phase 2 fix — C2)

Always close `TradeLog` by `trade_id` (not fuzzy symbol match), using `get_session()` context manager:

```python
with get_session() as db:
    trade = db.query(TradeLog).filter(TradeLog.id == trade_id).first()
    if not trade:
        # Fallback: latest open trade for this symbol
        trade = db.query(TradeLog).filter(
            TradeLog.symbol == symbol,
            TradeLog.exit_price.is_(None),
        ).order_by(TradeLog.id.desc()).first()
```

### Other tables

| Table | Purpose |
|-------|---------|
| `signal_logs` | Every signal evaluation (even non-trades) |
| `prediction_logs` | ML-style outcome tracking |
| `risk_state` | Persisted balance/peak across restarts |
| `performance_snapshots` | **DEPRECATED** — unused, kept for schema compat |

## Leaderboard (`data/strategy_leaderboard.json`)

JSON file, written atomically (temp file + `os.replace()` + `fsync()`). Tracks per-strategy trust scores.

**Atomic write pattern (Phase 2 fix — C7):**
```python
tmp_path = persist_path + ".tmp"
with open(tmp_path, "w") as f:
    json.dump(data, f)
    f.flush()
    os.fsync(f.fileno())
os.replace(tmp_path, persist_path)
```

If process dies mid-write, only `.tmp` is damaged — real file is untouched.

**Trust score mechanics:**
- Start: 50 (neutral)
- Win: +3 (max 100)
- Loss: -5 (asymmetric)
- < 20: SUSPENDED (no trades)
- > 80: PROVEN (lower signal threshold required)

## Migration Validation

Run `scripts/validate_migration.py` before/after deploys:
```bash
cd engine
../.venv/bin/python scripts/validate_migration.py --verbose
```

Checks:
- EventStore closed count == TradeLog closed count (detects dual-write failures)
- Orphaned open events (position never closed)
- Zero P&L on trades where price moved (regression detector)
- Leaderboard stats match TradeLog-derived stats per strategy
- Trust scores in bounds [0, 100], total_trades == wins + losses
- RiskState balance > 0, peak >= current

## Rules

- **Never access raw DB in tests** — use `:memory:` via conftest.py `use_test_db` fixture
- **Never use bare `get_db()`** — use `get_session()` context manager for proper commit/rollback
- **Leaderboard in tests** — always pass `persist_path=tmpdir/test_leaderboard.json` to avoid shared disk state
- **No SQLite in prod for scale** — PostgreSQL migration planned for Q4 2026
