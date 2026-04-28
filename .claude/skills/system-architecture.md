---
name: system-architecture
description: Full system architecture, component inventory, design patterns, and known issues for Notas Lave trading engine
---

Use this skill when working on architecture, component interactions, or system-level changes.

# System Architecture

## Component Inventory

| Component | Location | Purpose |
|-----------|----------|---------|
| FastAPI app | `api/app.py` | HTTP API, DI container, API key auth |
| Lab Engine | `engine/lab.py` | Autonomous trading loop |
| Confluence Scorer | `confluence/scorer.py` | Combine strategy signals (volume-weighted) |
| Volume Analysis | `strategies/volume_analysis.py` | Delta, CVD, profile, spike detection |
| Risk Manager | `risk/manager.py` | Trade validation |
| Event Bus | `engine/event_bus.py` | Pub/sub with failure policies |
| P&L Service | `engine/pnl.py` | Balance - deposit = P&L |
| EventStore | `journal/event_store.py` | Append-only trade journal |
| Database | `journal/database.py` | SQLAlchemy ORM |
| Market Data | `data/market_data.py` | Multi-source candle provider |
| Strategies | `strategies/*.py` | 12 strategies, BaseStrategy + registry |
| Delta Broker | `execution/delta.py` | Delta Exchange API (only active broker) |
| Paper Broker | `execution/paper.py` | In-memory test broker |
| Instruments | `data/instruments.py` | InstrumentSpec (pip, spread, sizing) |
| Config | `config.py` | Pydantic settings from .env |
| Alerts | `alerts/telegram.py` | Telegram notifications |
| Learning | `learning/*.py` | Analyzer, recommendations, optimizer |
| Backtester | `backtester/engine.py` | Walk-forward backtesting |

## Design Patterns

1. **DI Container** -- `Container(broker, journal, bus, pnl)` passed to `create_app()`. No global state.
2. **Protocols** -- `IBroker`, `IStrategy`, `ITradeJournal`, `IDataProvider`, `IRiskManager` in `core/ports.py`.
3. **Broker Registry** -- `@register_broker("name")` decorator. `create_broker("name")` to instantiate.
4. **Event Bus** -- `FailurePolicy.HALT | RETRY_3X | LOG_AND_CONTINUE` per subscriber.
5. **Append-Only Journal** -- EventStore never UPDATEs, only INSERTs events.

## Architecture Diagrams

LikeC4 source files in `architecture/*.c4`. Preview: `npx likec4 dev architecture/`

Views: index (system context), vmOverview, tradingFlowView, strategiesView, storageView, learningView, dataView

## Rules

- No new globals -- use DI Container
- All models in `core/models.py`
- Protocols for all boundaries
- Imports flow inward -- `core/` imports nothing outside `core/`
- Diagrams use LikeC4 -- update `model.c4` when architecture changes
- Version is dynamic -- `/health` reads from `pyproject.toml` via `importlib.metadata`
