# Notas Lave — System Architecture

> Last verified against code: v2.1.3 (2026-04-01)
>
> **Diagrams:** [`architecture/`](../../architecture/) — LikeC4 source files (single source of truth).
> Preview: `npx likec4 dev architecture/` | Export PNGs: `npx likec4 export png -o docs/system/diagrams architecture/`

## Views

| View | What it shows |
|------|--------------|
| `index` | System Context — Trader, VM, Delta Exchange, CCXT, Telegram, GitHub |
| `vmOverview` | Inside the VM — Dashboard, Engine, Storage |
| `tradingFlowView` | Trading Loop — Arena strategies → risk → broker |
| `strategiesView` | 6 composite strategies (Arena v3) |
| `storageView` | EventStore + SQLAlchemy + JSON state |
| `dataView` | Market data sources and caching |

## Component Inventory

| Component | Location | Purpose |
|-----------|----------|---------|
| FastAPI app | `api/app.py` | HTTP API, DI container, API key auth |
| Lab Engine | `engine/lab.py` | Autonomous trading loop (Strategy Arena v3) |
| Strategy Arena | `engine/lab.py` | 6 strategies compete per tick, best arena_score wins |
| Strategy Leaderboard | `engine/leaderboard.py` | Trust scores 0–100, Win +3, Loss -5, suspended <20 |
| Risk Manager | `risk/manager.py` | Trade validation (used by Lab since v1.0.0) |
| WebSocket Manager | `api/ws_manager.py` | ConnectionManager: topic pub/sub, 15s heartbeat, per-subscribe snapshots |
| Event Bus | `engine/event_bus.py` | Pub/sub with failure policies |
| P&L Service | `engine/pnl.py` | Balance - deposit = P&L |
| EventStore | `journal/event_store.py` | Append-only trade journal (Lab uses this) |
| Database | `journal/database.py` | SQLAlchemy ORM (TradeLog for strategy attribution) |
| Market Data | `data/market_data.py` | Multi-source candle provider |
| Strategies | `strategies/*.py` | 6 composite strategies, `BaseStrategy` + registry |
| Delta Broker | `execution/delta.py` | Delta Exchange API (only active broker) |
| Paper Broker | `execution/paper.py` | In-memory test broker |
| Instruments | `data/instruments.py` | InstrumentSpec (pip, spread, sizing, exchange symbols) |
| Config | `config.py` | Pydantic settings from .env |
| Alerts | `alerts/telegram.py` | Telegram notifications |

## Arena Score Formula (v2.0.9)

```python
# Diversity bonus: idle strategies earn up to 20 pts (full after 2h with no trades)
idle_minutes = (now - last_strategy_exec.get(strategy.name)).total_seconds() / 60
diversity = min(idle_minutes / 120, 1.0)

arena_score = (
    (signal.score / 100) * 30 +     # signal quality (was 40 before v2.0.9)
    min(rr / 5, 1.0) * 25 +         # R:R / dollar profit potential
    (trust_score / 100) * 15 +       # strategy trust (was 20)
    (win_rate / 100) * 10 +          # historical win rate (was 15)
    diversity * 20                    # diversity rotation bonus (new in v2.0.9)
)
```

All 6 strategies run independently per tick; highest arena_score wins. Trust scores evolve with outcomes (Win +3, Loss -5, suspended when < 20). Diversity bonus gives underrepresented strategies (Order Flow, Mean Reversion) a fair chance.

**Note on Binance:** The Binance **broker adapter** was removed in v1.0.0. Binance public data (no API key) is still used as a **data source** for crypto candles via CCXT in `data/market_data.py`. "Binance removed" means the trading integration, not the market data feed.

## Key Design Patterns

1. **DI Container** — `Container(broker, journal, bus, pnl, alerter, lab_engine)` passed to `create_app()`. No global state in API layer.
2. **Protocols** — `IBroker`, `IStrategy`, `ITradeJournal`, `IDataProvider`, `IRiskManager` in `core/ports.py`.
3. **Broker Registry** — `@register_broker("name")` decorator. `create_broker("name")` to instantiate.
4. **Event Bus** — `FailurePolicy.HALT | RETRY_3X | LOG_AND_CONTINUE` per subscriber.
5. **Append-Only Journal** — EventStore never UPDATEs, only INSERTs events.

## Known Architecture Issues

| ID | Issue | Impact | Status |
|----|-------|--------|--------|
| CQ-04 | Module-level singletons (`config`, `market_data`) | Side effects on import, hard to test | PARTIAL (`risk_manager` singleton removed) |
| QR-01 | Lab engine bypasses Risk Manager | ~No risk enforcement~ | **FIXED v1.0.0** |
| SE-01 | API open to internet with no auth | ~Anyone can read trading data~ | **FIXED v1.0.0** |
| QR-03 | Two instrument registries | ~Spec divergence~ | **FIXED v1.1.0** (merged, core re-exports) |

## Rules

- **No new globals.** Use the DI Container for all dependencies.
- **All models in `core/models.py`.** Don't add models in `data/models.py` — move them to core.
- **Protocols for all boundaries.** New adapters (brokers, data sources) implement protocols from `core/ports.py`.
- **Imports flow inward.** `core/` imports nothing outside `core/`. Adapters import from `core/`.
- **Diagrams use LikeC4.** Source of truth is `architecture/*.c4`. Update `model.c4` when architecture changes.
- **Version is dynamic.** `/health` reads version from `pyproject.toml` via `importlib.metadata`. Never hardcode version strings.
