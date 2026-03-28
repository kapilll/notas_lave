# Notas Lave — System Architecture

> Last verified against code: 2026-03-28

## System Map

```
                          Internet
                             |
                    GCP VM (34.79.66.229)
                    Firewall: 3000, 8000
                             |
              +--------------+--------------+
              |                             |
    notas-engine.service          notas-dashboard.service
    Python 3.12, :8000            Next.js 15, :3000
    (FastAPI + Lab Engine)        (React dashboard)
              |                             |
              +-------- REST API -----------+
              |         (JSON)
              |
    +---------+---------+
    |    Engine Core     |
    |                    |
    |  DI Container      |   <-- No globals. All deps injected.
    |  (broker, journal, |
    |   bus, pnl, lab)   |
    |                    |
    +----+------+-------+
         |      |
    +----+   +--+---+
    |        |      |
Strategies  Risk   Execution
(12 strats) Mgr    (Delta, Paper)
    |        |      |
    +---+----+      |
        |           |
  Confluence   +----+----+
  Scorer       |  Delta  |
  (weighted    |  Exch.  |
   categories) |  API    |
        |      +---------+
        |           |
   Lab Engine       |
   (async loop) ----+
        |
   EventStore (SQLite)     <-- Append-only journal for lab
   notas_lave_lab_v2.db
        |
   Learning Engine         <-- Reads from database.py (TradeLog)
   (analyzer, recs,            NOT from EventStore
    optimizer, accuracy)       THIS IS A KNOWN GAP (ML-02)
        |
   notas_lave.db (SQLAlchemy)
```

## Component Inventory

| Component | Location | Purpose |
|-----------|----------|---------|
| FastAPI app | `api/app.py` | HTTP API, DI container |
| Lab Engine | `engine/lab.py` | Autonomous trading loop |
| Confluence Scorer | `confluence/scorer.py` | Combine strategy signals |
| Risk Manager | `risk/manager.py` | Trade validation (NOT used by Lab) |
| Event Bus | `engine/event_bus.py` | Pub/sub with failure policies |
| P&L Service | `engine/pnl.py` | Balance - deposit = P&L |
| EventStore | `journal/event_store.py` | Append-only trade journal (Lab uses this) |
| Database | `journal/database.py` | SQLAlchemy ORM (Learning engine uses this) |
| Market Data | `data/market_data.py` | Multi-source candle provider |
| Strategies | `strategies/*.py` | 12 strategies, `BaseStrategy` + registry |
| Delta Broker | `execution/delta.py` | Delta Exchange API |
| Paper Broker | `execution/paper.py` | In-memory test broker |
| Binance Broker | `execution/binance.py` | **DEPRECATED** — scheduled for removal |
| Instruments | `data/instruments.py` | InstrumentSpec (pip, spread, sizing) |
| Instruments (dup) | `core/instruments.py` | Instrument (exchange symbols) — **DUPLICATE, merge planned** |
| Config | `config.py` | Pydantic settings from .env |
| Alerts | `alerts/telegram.py` | Telegram notifications |
| Learning | `learning/*.py` | Analyzer, recommendations, optimizer, accuracy, A/B testing |
| Backtester | `backtester/engine.py` | Walk-forward backtesting with 10 risk levers |
| Monte Carlo | `backtester/monte_carlo.py` | Permutation test for robustness |
| Token Tracker | `monitoring/token_tracker.py` | Claude API cost tracking |

## Data Flow

```
Market Data (CCXT/TwelveData/yfinance)
  |
  v
Candles (in-memory cache, 15s TTL)
  |
  v
Strategies (12x) --> Signals
  |
  v
Confluence Scorer --> Composite Score + Direction
  |
  v
Lab Engine (checks score, R:R, cooldown, instrument stats)
  |
  v                                  MISSING: Risk Manager check
Broker.place_order()
  |
  v
EventStore.record_signal() + record_open()
  |
  v
Position Monitoring (polls 1m candles)
  |
  v
SL/TP hit --> Broker.close_position() --> EventStore.record_close()
  |
  v
Telegram notification via Event Bus
```

## Key Design Patterns

1. **DI Container** — `Container(broker, journal, bus, pnl)` passed to `create_app()`. No global state in API layer.
2. **Protocols** — `IBroker`, `IStrategy`, `ITradeJournal`, `IDataProvider`, `IRiskManager` in `core/ports.py`.
3. **Broker Registry** — `@register_broker("name")` decorator. `create_broker("name")` to instantiate.
4. **Event Bus** — `FailurePolicy.HALT | RETRY_3X | LOG_AND_CONTINUE` per subscriber.
5. **Append-Only Journal** — EventStore never UPDATEs, only INSERTs events.

## Known Architecture Issues

| ID | Issue | Impact |
|----|-------|--------|
| ML-02 | Two journal systems (EventStore vs SQLAlchemy) are disconnected | Learning engine can't see Lab trades |
| QR-01 | Lab engine bypasses Risk Manager | No risk enforcement on live trades |
| QR-03 | Two instrument registries (`core/instruments.py` + `data/instruments.py`) | Potential spec divergence |
| CQ-04 | Module-level singletons (`config`, `risk_manager`, `market_data`) | Side effects on import, hard to test |

## Rules

- **No new globals.** Use the DI Container for all dependencies.
- **All models in `core/models.py`.** Don't add models in `data/models.py` — move them to core.
- **Protocols for all boundaries.** New adapters (brokers, data sources) implement protocols from `core/ports.py`.
- **Imports flow inward.** `core/` imports nothing outside `core/`. `engine/` and `api/` import from `core/`. Adapters (`execution/`, `data/`) import from `core/`.
