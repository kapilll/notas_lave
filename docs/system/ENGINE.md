# Trading Engine

> Last verified against code: 2026-03-28

## Overview

The engine is a Python 3.11+ FastAPI application at `engine/src/notas_lave/`. It runs the Lab trading loop, serves the REST API, and manages all trading logic.

## Directory Structure

```
engine/src/notas_lave/
├── api/              # FastAPI routes (system, trade, lab, learning)
│   ├── app.py        # App factory + DI Container
│   ├── system_routes.py
│   ├── trade_routes.py
│   ├── lab_routes.py
│   └── learning_routes.py
├── core/             # Domain models, ports, events, errors
│   ├── models.py     # Canonical Pydantic models (Signal, TradeSetup, Candle, etc.)
│   ├── ports.py      # Protocol interfaces (IBroker, IStrategy, etc.)
│   ├── events.py     # Frozen domain events (TradeOpened, TradeClosed, etc.)
│   ├── errors.py     # Domain exceptions (RiskRejected, BrokerError, etc.)
│   └── instruments.py # InstrumentRegistry with exchange symbol mapping (DUPLICATE — merge into data/instruments.py)
├── engine/           # Core engine components
│   ├── lab.py        # Lab Engine — autonomous trading loop
│   ├── event_bus.py  # Pub/sub with failure policies
│   ├── pnl.py        # P&L = current_balance - original_deposit
│   └── scheduler.py  # APScheduler wrapper
├── execution/        # Broker adapters
│   ├── registry.py   # @register_broker decorator + create_broker()
│   ├── delta.py      # Delta Exchange testnet (ACTIVE)
│   ├── paper.py      # In-memory test broker
│   ├── binance.py    # Binance Demo (DEPRECATED — removal planned)
│   ├── coindcx.py    # CoinDCX (future)
│   └── mt5.py        # MetaTrader 5 (future)
├── strategies/       # 12 trading strategies
│   ├── base.py       # BaseStrategy ABC with shared helpers (ATR, volume check)
│   ├── registry.py   # Strategy list + optimizer param loading
│   └── *.py          # Individual strategies (see STRATEGIES section below)
├── confluence/
│   └── scorer.py     # Combine signals → composite score (regime-weighted categories)
├── risk/
│   └── manager.py    # RiskManager — validates trades (NOT used by Lab currently)
├── data/
│   ├── instruments.py     # InstrumentSpec (pip values, spreads, position sizing)
│   ├── market_data.py     # Multi-source candle provider (CCXT, TwelveData, yfinance)
│   ├── models.py          # Re-exports core/models + adds ConfluenceResult
│   ├── economic_calendar.py # News event schedule + blackout detection
│   └── historical_downloader.py
├── journal/
│   ├── event_store.py     # Append-only SQLite journal (Lab uses this)
│   ├── database.py        # SQLAlchemy ORM tables (Learning engine uses this)
│   ├── schemas.py         # Pydantic schemas for JSON state files
│   └── projections.py     # Query helpers
├── learning/
│   ├── analyzer.py        # Multi-dimensional trade analysis
│   ├── recommendations.py # Actionable suggestions from analysis
│   ├── optimizer.py       # Walk-forward parameter tuning
│   ├── accuracy.py        # Prediction accuracy tracker
│   ├── ab_testing.py      # Shadow-mode A/B testing
│   ├── trade_grader.py    # Grade trades A-F
│   ├── claude_review.py   # Claude-based trade analysis
│   └── progress.py        # Learning progress tracking
├── backtester/
│   ├── engine.py          # Walk-forward backtester (10 risk levers)
│   └── monte_carlo.py     # Permutation test for robustness
├── alerts/
│   ├── telegram.py        # Telegram message sender
│   └── scanner.py         # Alert scanner
├── observability/
│   └── logging.py         # Structlog JSON logging setup
├── monitoring/
│   └── token_tracker.py   # Claude API cost tracking
├── claude_engine/
│   └── decision.py        # Claude trade analysis (not wired to Lab)
├── ml/
│   └── features.py        # Feature engineering (stub)
├── config.py              # Pydantic settings from .env
└── log_config.py          # Logging configuration
```

## Lab Engine (engine/lab.py)

The main trading loop. Runs as an asyncio background task.

**Pace presets:**
| Pace | Entry TFs | Min Score | Min R:R | Max Concurrent | Scan Interval |
|------|-----------|-----------|---------|----------------|---------------|
| conservative | 1h | 4.0 | 3.0 | 3 | 60s |
| balanced | 15m, 1h | 3.5 | 2.0 | 5 | 45s |
| aggressive | 15m, 30m, 1h | 2.5 | 2.0 | 8 | 30s |

**Tick cycle:**
1. For each instrument × timeframe: fetch candles, run confluence scorer
2. If score + R:R meet thresholds → place order via broker
3. Monitor open positions: check SL/TP against 1m candle highs/lows
4. Reconcile journal with broker (detect exchange-side closes)

**Known issues:**
- Does NOT call RiskManager.validate_trade()
- Does NOT have a loss streak throttle
- Position sizing uses naive formula, not InstrumentSpec.calculate_position_size()
- SL/TP monitoring is client-side polling (30-60s gap)

## Entry Point (run.py)

```python
# 1. Import all brokers (registers them)
import notas_lave.execution.paper
import notas_lave.execution.binance   # TODO: remove
import notas_lave.execution.delta

# 2. Build DI Container
broker = create_broker(os.environ.get("BROKER", "delta_testnet"))
journal = EventStore(db_path)
bus = EventBus()
# ... connect broker, fetch deposit, create PnLService

# 3. Create FastAPI app and run
app = create_app(container)
uvicorn.run(app, host="0.0.0.0", port=8000)
```

## Key API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Engine health check |
| GET | `/api/system/health` | Component status |
| GET | `/api/broker/status` | Balance, positions |
| GET | `/api/risk/status` | P&L, drawdown, capacity |
| GET | `/api/prices` | Current prices |
| GET | `/api/scan/all` | Confluence scan all symbols |
| GET | `/api/lab/summary` | Lab performance |
| GET | `/api/lab/verify` | Data integrity check |
| POST | `/api/lab/start` | Start lab engine |
| POST | `/api/lab/stop` | Stop lab engine |
| POST | `/api/lab/pace/{pace}` | Change pace |
| GET | `/api/learning/state` | Complete system memory |
| GET | `/api/learning/recommendations` | Actionable suggestions |

## Rules

- **All imports use `from notas_lave.X import Y`** — never relative to `engine/src`.
- **`pyproject.toml` sets `pythonpath = ["src"]`** for test discovery.
- **No business logic in API routes** — routes call services which call core.
- **Strategies are stateless** — `analyze(candles, symbol)` has no side effects.
- **BaseStrategy.set_volume_check(False)** is called in Lab mode — some exchanges don't report volume.
- **Never `UPDATE` the EventStore** — only `INSERT` new events. State is reconstructed by replay.
