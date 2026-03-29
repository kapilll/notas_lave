# Trading Engine

> Last verified against code: v2.0.6 (2026-03-30)

## Overview

The engine is a Python 3.12+ FastAPI application at `engine/src/notas_lave/`. It runs the Lab trading loop, serves the REST API, manages WebSocket connections, and handles all trading logic.

## Directory Structure

```
engine/src/notas_lave/
├── api/              # FastAPI routes + WebSocket
│   ├── app.py        # App factory + DI Container
│   ├── system_routes.py    # /health, /api/system/health, /api/prices, /api/candles, /api/broker/status, /api/risk/status, /api/scan/*
│   ├── trade_routes.py     # /api/trade/*
│   ├── lab_routes.py       # /api/lab/*
│   ├── learning_routes.py  # /api/learning/*
│   ├── backtest_routes.py  # /api/backtest/*
│   ├── ws_manager.py       # WebSocket ConnectionManager singleton (topic pub/sub)
│   └── ws_routes.py        # GET /ws WebSocket endpoint
├── core/             # Domain models, ports, events, errors
│   ├── models.py     # Canonical Pydantic models (Signal, TradeSetup, Candle, etc.)
│   ├── ports.py      # Protocol interfaces (IBroker, IStrategy, etc.)
│   ├── events.py     # Frozen domain events (TradeOpened, TradeClosed, etc.)
│   └── errors.py     # Domain exceptions (RiskRejected, BrokerError, etc.)
├── execution/        # Broker adapters
│   ├── registry.py   # @register_broker decorator + create_broker()
│   ├── delta.py      # Delta Exchange testnet (ACTIVE)
│   ├── paper.py      # In-memory test broker
│   └── ...           # coindcx.py, mt5.py (future)
├── strategies/       # 6 composite strategies
│   ├── base.py       # BaseStrategy ABC with shared helpers (ATR, volume check)
│   ├── registry.py   # Strategy list + optimizer param loading
│   └── *.py          # trend_momentum, mean_reversion, level_confluence, breakout, williams, order_flow
├── engine/
│   ├── lab.py        # Lab Engine — autonomous trading loop (Strategy Arena v3)
│   ├── leaderboard.py # StrategyLeaderboard — trust scores, dynamic thresholds, win/loss
│   ├── event_bus.py  # Pub/sub with failure policies (LOG_AND_CONTINUE, RETRY_3X, HALT)
│   └── pnl.py        # P&L = current_balance - original_deposit (broker truth)
├── risk/
│   └── manager.py    # RiskManager — validates every Lab trade
├── data/
│   ├── instruments.py     # InstrumentSpec (pip values, spreads, position sizing, contract_size)
│   ├── market_data.py     # Multi-source candle provider (CCXT, TwelveData, yfinance)
│   └── models.py          # Candle + ConfluenceResult
├── journal/
│   ├── event_store.py     # Append-only SQLite journal (ITradeJournal)
│   ├── database.py        # SQLAlchemy ORM tables (Learning engine + API)
│   └── projections.py     # Query helpers
├── learning/
│   ├── analyzer.py        # Multi-dimensional trade analysis
│   ├── recommendations.py # Actionable suggestions
│   ├── optimizer.py       # Walk-forward parameter tuning
│   ├── trade_grader.py    # A/B/C/D/F trade quality grading
│   └── claude_review.py   # Weekly Claude review
└── backtester/
    └── engine.py          # BacktestEngine — arena and walk-forward modes
```

## Key Architecture Rules

- **Broker = source of truth for LIVE state** (positions, balance)
- **EventStore = source of truth for HISTORY** (closed trades, audit log)
- **TradeLog = source of truth for LEARNING** (structured ORM, strategy attribution)
- **Leaderboard = source of truth for STRATEGY TRUST** (who earns the right to trade)
- **P&L formula:** `(exit - entry) * position_size * contract_size` (direction-adjusted)
- **No hardcoded values** — env vars or runtime state only
- **No module-level singletons** in application code — use DI Container

## Lab Engine (lab.py)

### Strategy Arena v3

```
For each instrument × timeframe:
  Run ALL 6 strategies independently → collect proposals
  Filter: arena_score ≥ strategy's dynamic threshold (based on trust)
  If multiple proposals on same symbol → highest arena_score wins
  Risk Manager validates → Execute on broker → Journal both EventStore + TradeLog
  On close → update leaderboard (win/loss → trust score → dynamic threshold)
  Broadcast WS events for live dashboard
```

### P&L Calculation (Phase 2 fix)
```python
pnl = (exit_price - entry_price if LONG else entry_price - exit_price)
      * position_size * contract_size  # contract_size from InstrumentSpec
```

Gold (XAUUSD) has `contract_size=100` (100 oz/lot). Without it, P&L is 100x wrong.

### Reconciliation (Phase 2 fix — C3/C4/C5)

```python
async def _reconcile():
    # C5: Detect orphaned broker positions (broker has it, journal doesn't)
    orphaned = broker_syms - journal_syms  # logs WARNING

    # C4: 2 consecutive misses before closing (transient glitch safety)
    for trade in journal_open:
        if trade.symbol not in broker_syms:
            miss_count += 1
            if miss_count < 2: continue   # wait
            close_trade(exit_price=last_known_price)  # C3: use real price, not entry
```

### WS Broadcasts

| Trigger | Topics Broadcast |
|---------|-----------------|
| Trade opened | `trade.executed` (opened), `trade.positions` |
| Trade closed | `trade.executed` (closed), `trade.positions`, `risk.status`, `arena.leaderboard` |
| Tick completes | `arena.proposals`, `lab.status` |
| Broker rejection | `trade.rejected` |

## WebSocket Infrastructure

### ConnectionManager (`api/ws_manager.py`)

- Module-level singleton: `ws_manager = ConnectionManager()`
- Topics: `system.health`, `system.errors`, `market.prices`, `trade.executed`, `trade.positions`, `trade.rejected`, `risk.status`, `arena.proposals`, `arena.leaderboard`, `lab.status`, `broker.status`
- Heartbeat: server pings every 15s, disconnects clients that don't pong within 45s
- Snapshots: on subscribe, server sends full current state for each topic immediately
- Broadcast is no-op when no clients connected (zero overhead in tests)

### WebSocket Route (`/ws`)

```
ws://host:8000/ws[?api_key=secret]
```

- Auth: optional `?api_key=` query param (only enforced if `API_KEY` env set)
- Client sends: `{"action": "subscribe", "topics": [...]}`
- Client sends: `{"type": "pong"}` (in response to server ping)
- Client sends: `{"type": "snapshot"}` (refresh all subscriptions)

## Key API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Version + status |
| `GET /api/system/health` | Full component health |
| `GET /api/broker/status` | Balance, positions from Delta |
| `GET /api/risk/status` | P&L, drawdown, capacity |
| `GET /api/lab/status` | Lab engine state |
| `GET /api/candles/{symbol}` | OHLCV data (TradingView format) |
| `GET /api/scan/all` | Confluence scan all instruments |
| `WS  /ws` | Live data stream (all topics) |
| `POST /api/backtest/arena/{symbol}` | Run arena backtest |
| `POST /api/backtest/walk-forward/{symbol}` | Walk-forward validation |
| `GET /api/backtest/leaderboard` | Strategy performance |
| `GET /api/learning/summary` | Learning system state |
| `POST /api/learning/analyze-now` | Trigger immediate analysis |

## Dependency Injection Container

```python
@dataclass
class Container:
    broker: IBroker          # Delta Exchange or PaperBroker
    journal: ITradeJournal   # EventStore
    bus: EventBus            # Pub/sub
    pnl: PnLService          # Balance-based P&L calculation
    alerter: IAlerter | None
    lab_engine: LabEngine | None
    alert_scanner: Any | None
    config: dict
```

No module-level singletons. Every component received via DI.
