# Notas Lave — System Architecture

> Last verified against code: v1.0.0 (2026-03-28)

## System Overview

```mermaid
graph TB
    subgraph Internet
        Users([Users / Internet])
    end

    subgraph VM["GCP VM — 34.79.66.229"]
        subgraph Services["Systemd Services"]
            Dashboard["Dashboard<br/>(Next.js 15 :3000)"]
            Engine["Engine API<br/>(FastAPI :8000)<br/>🔑 API key auth"]
        end

        subgraph Core["Engine Core"]
            Container["DI Container<br/>(broker, journal, bus, pnl)"]
            Lab["Lab Engine<br/>(async trading loop)<br/>+ loss streak throttle<br/>+ error backoff<br/>+ DB maintenance"]
            EventBus["Event Bus<br/>(HALT / RETRY / LOG)"]
            PnL["PnL Service"]
        end

        subgraph Trading["Signal Generation"]
            Strategies["12 Strategies<br/>(scalping, ICT, fib, breakout)"]
            Confluence["Confluence Scorer<br/>(regime-weighted categories)"]
            Regime["Regime Detection<br/>(TRENDING/RANGING/VOLATILE/QUIET)"]
        end

        subgraph Risk_["Risk Management"]
            RiskMgr["Risk Manager<br/>✅ validates every Lab trade"]
        end

        subgraph Execution["Execution Layer"]
            Delta["Delta Broker<br/>(testnet, bracket orders)"]
            Paper["Paper Broker<br/>(in-memory, tests)"]
        end

        subgraph Storage["Storage Layer"]
            EventStore[("EventStore<br/>lab_v2.db<br/>(append-only)")]
            SQLA[("SQLAlchemy DB<br/>notas_lave.db<br/>(TradeLog, SignalLog...)")]
            JSON["JSON State Files<br/>(weights, blacklists, optimizer)"]
        end

        subgraph Learning["Learning Engine"]
            Analyzer["Analyzer<br/>(strategy × instrument × regime)"]
            Recs["Recommendations<br/>(blacklists, weights)"]
            Optimizer["Optimizer<br/>(walk-forward tuning)"]
            Accuracy["Accuracy Tracker"]
            Backtester["Backtester<br/>(10 risk levers, Monte Carlo)"]
        end
    end

    subgraph External["External Services"]
        DeltaAPI["Delta Exchange API<br/>(testnet)"]
        CCXT["CCXT / Binance<br/>(public data only)"]
        TwelveData["TwelveData API<br/>(metals, 800/day)"]
        Telegram["Telegram<br/>(trade + deploy alerts)"]
    end

    Users -->|"🔑 X-API-Key"| Engine
    Users --> Dashboard
    Dashboard <-->|"REST JSON<br/>(CORS restricted)"| Engine
    Engine --> Container
    Container --> Lab
    Lab --> EventBus
    Lab --> PnL
    Lab -->|candles| Strategies
    Strategies -->|signals| Confluence
    Confluence --> Regime
    Lab -->|validate_trade| RiskMgr
    RiskMgr -->|pass/reject| Lab
    Lab -->|place_order| Delta
    Lab -->|writes| EventStore
    Lab -->|alerts| Telegram
    Delta <-->|orders, positions| DeltaAPI
    Confluence -->|updates weights| JSON

    SQLA -.->|"⚠️ DISCONNECTED<br/>(ML-02)"| EventStore

    Analyzer -->|reads| SQLA
    Recs --> Analyzer
    Optimizer --> Backtester
    Recs -->|updates| JSON
    Accuracy -->|reads| SQLA

    subgraph MarketData["Market Data"]
        MktData["Provider<br/>(15s cache, CCXT lock)"]
    end
    Lab -->|get_candles| MktData
    MktData -->|crypto| CCXT
    MktData -->|metals| TwelveData

    style RiskMgr fill:#b2f2bb,stroke:#2f9e44
    style EventStore fill:#ffec99,stroke:#e67700
    style SQLA fill:#ffec99,stroke:#e67700
    style Delta fill:#a5d8ff,stroke:#1971c2
    style Lab fill:#b2f2bb,stroke:#2f9e44
    style Confluence fill:#b2f2bb,stroke:#2f9e44
    style Strategies fill:#b2f2bb,stroke:#2f9e44
    style Engine fill:#a5d8ff,stroke:#1971c2
```

## Trading Loop (Data Flow)

```mermaid
sequenceDiagram
    participant MD as Market Data
    participant S as Strategies (12x)
    participant C as Confluence Scorer
    participant L as Lab Engine
    participant R as Risk Manager
    participant B as Delta Broker
    participant J as EventStore
    participant T as Telegram

    loop Every 30-60s (pace-dependent)
        L->>MD: get_candles(symbol, timeframe)
        MD-->>L: Candle[]

        L->>S: analyze(candles, symbol)
        S-->>L: Signal[]

        L->>C: compute_confluence(candles, symbol, tf)
        C-->>L: ConfluenceResult (score, direction)

        alt Score >= threshold AND R:R >= min
            Note over L: InstrumentSpec.calculate_position_size()
            Note over L: Loss streak? → halve risk
            L->>R: validate_trade(setup)
            R-->>L: (pass, []) or (fail, rejections)

            alt Risk passed
                L->>B: place_order(TradeSetup)
                B-->>L: OrderResult

                alt Order success
                    L->>J: record_signal() + record_open()
                    L->>T: [LAB] OPENED ...
                end
            else Risk rejected
                Note over L: Log rejections, skip trade
            end
        end

        Note over L: Monitor open positions
        L->>B: get_positions()
        L->>MD: get_candles(symbol, "1m")
        alt SL or TP hit (candle high/low)
            L->>B: close_position(symbol)
            L->>J: record_close() + record_grade()
            L->>T: [LAB] CLOSED ...
        end
    end
```

## Storage Architecture

```mermaid
graph LR
    subgraph Lab["Lab Engine"]
        LabE["Lab Engine"]
    end

    subgraph ES["EventStore (lab_v2.db)"]
        TE["trade_events<br/>(trade_id, event_type, data JSON)"]
        TS["trade_id_seq"]
    end

    subgraph SA["SQLAlchemy (notas_lave.db)"]
        SL["signal_logs"]
        TL["trade_logs"]
        PL["prediction_logs"]
        AB["ab_tests + results"]
        RS["risk_state"]
        TU["token_usage"]
    end

    subgraph JF["JSON State (engine/data/)"]
        LW["learned_state.json<br/>(regime weights)"]
        LB["learned_blacklists.json"]
        OR["optimizer_results.json"]
        RL["rate_limit_state.json"]
        AS["adjustment_state.json"]
    end

    subgraph LE["Learning Engine"]
        AN["Analyzer"]
        RE["Recommendations"]
    end

    LabE -->|"writes ✅"| ES
    LabE -.->|"does NOT write ⚠️"| SA
    AN -->|reads| SA
    RE -->|persists| JF
    RE -->|reads| AN

    style ES fill:#ffec99
    style SA fill:#ffec99
    style JF fill:#ffec99
```

## CI/CD Pipeline

```mermaid
graph LR
    Dev["Developer"] -->|push branch| PR["Pull Request"]
    PR -->|triggers| Check["pr-check.yml<br/>pytest + coverage ≥ 35%"]
    Check -->|pass| Merge["Merge to main"]
    Merge -->|"manual step"| Release["Create GitHub Release<br/>(v1.0.0, v1.1.0...)"]
    Release -->|triggers| Deploy["deploy.yml"]

    subgraph Deploy_["deploy.yml (on release)"]
        Test2["Test"] --> SSH["SSH Deploy<br/>git checkout tag<br/>pip install → npm build<br/>systemctl restart"]
        SSH --> Health["Health Check<br/>GET /health (30s)"]
        Health -->|fail| Rollback["Rollback<br/>git checkout prev SHA"]
        Health -->|pass| Done["✅ Deployed"]
    end

    Deploy_ --> Notify["Telegram<br/>(v1.0.0 deployed ✅)"]

    style Rollback fill:#ffc9c9
    style Done fill:#b2f2bb
    style Release fill:#d0bfff
```

## Module Dependency Graph

```mermaid
graph TD
    subgraph core["core/ (no external imports)"]
        models["models.py<br/>(Signal, TradeSetup, Candle...)"]
        ports["ports.py<br/>(IBroker, IStrategy...)"]
        events["events.py<br/>(TradeOpened, TradeClosed...)"]
        errors["errors.py<br/>(RiskRejected, BrokerError...)"]
        inst_core["instruments.py<br/>⚠️ DUPLICATE"]
    end

    subgraph engine_["engine/"]
        lab["lab.py"]
        bus["event_bus.py"]
        pnl["pnl.py"]
    end

    subgraph execution["execution/"]
        registry["registry.py"]
        delta["delta.py"]
        paper["paper.py"]
    end

    subgraph data["data/"]
        instruments["instruments.py<br/>(InstrumentSpec)"]
        market["market_data.py"]
        calendar["economic_calendar.py"]
    end

    subgraph strategies["strategies/"]
        base["base.py"]
        strat_reg["registry.py"]
        strats["12 strategy files"]
    end

    subgraph confluence_["confluence/"]
        scorer["scorer.py"]
    end

    subgraph risk_["risk/"]
        risk_mgr["manager.py"]
    end

    subgraph api["api/"]
        app["app.py<br/>(+ API key middleware)"]
        routes["routes (4 files)"]
    end

    %% Dependencies (should flow inward to core)
    lab --> models
    lab --> ports
    lab --> events
    lab --> risk_mgr
    lab --> instruments
    delta --> models
    delta --> inst_core
    paper --> models
    scorer --> models
    scorer --> strat_reg
    risk_mgr --> instruments
    risk_mgr --> calendar
    app --> ports
    app --> bus
    app --> pnl
    base --> models
    strats --> base
    strat_reg --> strats

    style inst_core fill:#ffc9c9
```

## Component Inventory

| Component | Location | Purpose |
|-----------|----------|---------|
| FastAPI app | `api/app.py` | HTTP API, DI container, API key auth |
| Lab Engine | `engine/lab.py` | Autonomous trading loop |
| Confluence Scorer | `confluence/scorer.py` | Combine strategy signals |
| Risk Manager | `risk/manager.py` | Trade validation (used by Lab since v1.0.0) |
| Event Bus | `engine/event_bus.py` | Pub/sub with failure policies |
| P&L Service | `engine/pnl.py` | Balance - deposit = P&L |
| EventStore | `journal/event_store.py` | Append-only trade journal (Lab uses this) |
| Database | `journal/database.py` | SQLAlchemy ORM (Learning engine uses this) |
| Market Data | `data/market_data.py` | Multi-source candle provider |
| Strategies | `strategies/*.py` | 12 strategies, `BaseStrategy` + registry |
| Delta Broker | `execution/delta.py` | Delta Exchange API (only active broker) |
| Paper Broker | `execution/paper.py` | In-memory test broker |
| Instruments | `data/instruments.py` | InstrumentSpec (pip, spread, sizing) |
| Instruments (dup) | `core/instruments.py` | Instrument (exchange symbols) — **DUPLICATE, merge planned** |
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
| ML-02 | Two journal systems (EventStore vs SQLAlchemy) disconnected | ~Learning engine blind~ | **FIXED v1.1.0** (bridge writes to both) |
| QR-03 | Two instrument registries (`core/instruments.py` + `data/instruments.py`) | ~Spec divergence~ | **FIXED v1.1.0** (merged, core re-exports) |
| CQ-04 | Module-level singletons (`config`, `risk_manager`, `market_data`) | Side effects on import, hard to test | OPEN |
| QR-01 | Lab engine bypasses Risk Manager | ~No risk enforcement~ | **FIXED v1.0.0** |
| SE-01 | API open to internet with no auth | ~Anyone can read trading data~ | **FIXED v1.0.0** |

## Rules

- **No new globals.** Use the DI Container for all dependencies.
- **All models in `core/models.py`.** Don't add models in `data/models.py` — move them to core.
- **Protocols for all boundaries.** New adapters (brokers, data sources) implement protocols from `core/ports.py`.
- **Imports flow inward.** `core/` imports nothing outside `core/`. `engine/` and `api/` import from `core/`. Adapters (`execution/`, `data/`) import from `core/`.
- **Diagrams use Mermaid.** No binary diagram files — keep diagrams as code in markdown so they diff, render on GitHub, and cost minimal tokens to update.
- **Update diagrams when architecture changes.** If you add/remove a component, change data flow, or fix a known issue, update the relevant Mermaid diagram in this file.
