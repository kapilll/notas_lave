# Notas Lave — System Architecture

> Last verified against code: v1.1.0 (2026-03-28)
>
> **Diagrams:** [`architecture/`](../../architecture/) — LikeC4 source files (single source of truth).
> Preview: `npx likec4 dev architecture/` | Export PNGs: `npx likec4 export png -o docs/system/diagrams architecture/`

## Views

| View | What it shows |
|------|--------------|
| `index` | System Context — Trader, VM, Delta Exchange, CCXT, Telegram, GitHub |
| `vmOverview` | Inside the VM — Dashboard, Engine, Storage, Learning |
| `tradingFlowView` | Trading Loop — scan → strategies → confluence → risk → broker |
| `strategiesView` | All 12 strategies by category |
| `storageView` | EventStore + SQLAlchemy + JSON state (with ML-02 bridge) |
| `learningView` | Analyzer → Recommendations → Optimizer |
| `dataView` | Market data sources and caching |

## Component Inventory

| Component | Location | Purpose |
|-----------|----------|---------|
| FastAPI app | `api/app.py` | HTTP API, DI container, API key auth |
| Lab Engine | `engine/lab.py` | Autonomous trading loop |
| Confluence Scorer | `confluence/scorer.py` | Combine strategy signals (volume-weighted) |
| Volume Analysis | `strategies/volume_analysis.py` | Delta, CVD, profile, spike detection → confluence multiplier |
| Risk Manager | `risk/manager.py` | Trade validation (used by Lab since v1.0.0) |
| Event Bus | `engine/event_bus.py` | Pub/sub with failure policies |
| P&L Service | `engine/pnl.py` | Balance - deposit = P&L |
| EventStore | `journal/event_store.py` | Append-only trade journal (Lab uses this) |
| Database | `journal/database.py` | SQLAlchemy ORM (Learning engine uses this) |
| Market Data | `data/market_data.py` | Multi-source candle provider |
| Strategies | `strategies/*.py` | 12 strategies, `BaseStrategy` + registry |
| Delta Broker | `execution/delta.py` | Delta Exchange API (only active broker) |
| Paper Broker | `execution/paper.py` | In-memory test broker |
| Instruments | `data/instruments.py` | InstrumentSpec (pip, spread, sizing, exchange symbols) |
| Config | `config.py` | Pydantic settings from .env |
| Alerts | `alerts/telegram.py` | Telegram notifications |
| Learning | `learning/*.py` | Analyzer, recommendations, optimizer, accuracy, A/B testing |
| Backtester | `backtester/engine.py` | Walk-forward backtesting with 10 risk levers |
| Monte Carlo | `backtester/monte_carlo.py` | Permutation test for robustness |
| Token Tracker | `monitoring/token_tracker.py` | Claude API cost tracking |

## Key Design Patterns

1. **DI Container** — `Container(broker, journal, bus, pnl)` passed to `create_app()`. No global state in API layer.
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
| ML-02 | Two journal systems disconnected | ~Learning engine blind~ | **FIXED v1.1.0** (bridge writes to both) |
| QR-03 | Two instrument registries | ~Spec divergence~ | **FIXED v1.1.0** (merged, core re-exports) |

## Rules

- **No new globals.** Use the DI Container for all dependencies.
- **All models in `core/models.py`.** Don't add models in `data/models.py` — move them to core.
- **Protocols for all boundaries.** New adapters (brokers, data sources) implement protocols from `core/ports.py`.
- **Imports flow inward.** `core/` imports nothing outside `core/`. Adapters import from `core/`.
- **Diagrams use LikeC4.** Source of truth is `architecture/*.c4`. Update `model.c4` when architecture changes.
- **Version is dynamic.** `/health` reads version from `pyproject.toml` via `importlib.metadata`. Never hardcode version strings.
