# Trading Engine

> Last verified against code: v2.0.16 (2026-03-30)

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

- **Removing an instrument requires updating 4 places:** `data/instruments.py` (registry), `engine/lab.py` (`LAB_INSTRUMENTS`), `api/system_routes.py` (scan list), `api/lab_routes.py` (markets list). Missing any causes tick crashes.
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
  Filter: arena_score >= strategy's dynamic threshold (based on trust)
  If multiple proposals on same symbol → highest arena_score wins
  Risk Manager validates → Execute on broker → Journal both EventStore + TradeLog
  On close → update leaderboard (win/loss → trust score → dynamic threshold)
  Broadcast WS events for live dashboard
```

### Arena Score Formula (v2.0.9)

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

**Dollar profit** is already captured by R:R since all trades risk the same budget (`risk_pct × balance`). Higher R:R = more dollars at equal risk.

**Diversity bonus** gives underrepresented strategies (Order Flow, Mean Reversion) a fair chance. A strategy idle for 2+ hours gets a full 20-point boost.

### execute_trade() Return Signature (v2.0.10)

```python
async def execute_trade(setup, context) -> tuple[int, str]:
    # Returns (trade_id, error_reason)
    # trade_id > 0 on success; error_reason is non-empty on rejection
```

Callers unpack as `trade_id, exec_error = await self.execute_trade(...)`.

### Proposal Dry-Run Accuracy (v2.0.11 + v2.0.13)

The dry-run `will_execute` check in the proposals loop runs both:
1. `calculate_position_size()` — can we get a non-zero lot?
2. `RiskManager.validate_trade()` — does the signal pass all risk rules?

**Rule:** If either check fails, `will_execute = False` and `block_reason` shows the exact rejection. This ensures the READY/BLOCKED badge on proposals is always accurate.

**v2.0.13 fix:** Both checks now use `arena_balance.available` (free margin) instead of `arena_balance.total`. Open positions consume margin; using total caused proposals to show READY but fail execution with "Insufficient Margin" from Delta. The MARGIN display field also changed: `notional / max_leverage` (correct) instead of `notional * margin_pct` (was implying 100x for 10x instruments).

### P&L Calculation

```python
pnl = (exit_price - entry_price if LONG else entry_price - exit_price)
      * position_size * contract_size  # contract_size from InstrumentSpec
```

Gold (XAUUSD) has `contract_size=100` (100 oz/lot). Without it, P&L is 100x wrong.

### Reconciliation (C3/C4/C5)

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

### WS Broadcasts (updated v2.0.10)

| Trigger | Topics Broadcast |
|---------|-----------------|
| Trade opened | `trade.executed` (opened), `trade.positions` |
| Trade closed | `trade.executed` (closed), `trade.positions`, `risk.status`, `arena.leaderboard` |
| **Every tick** | `arena.proposals`, `lab.status`, **`trade.positions`** (enriched, fresh from broker) |
| Broker rejection | `trade.rejected` (includes `reason`, `strategy`, `direction` fields) |

**Rule:** `trade.positions` is broadcast every tick so P&L and current price never go stale between trade events. Data comes from `get_live_positions()` which includes `proposing_strategy`, `stop_loss`, `take_profit`, and fresh `unrealized_pnl`.

## Key API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Version + status |
| `GET /api/system/health` | Full component health |
| `GET /api/broker/status` | Balance, positions from Delta |
| `GET /api/risk/status` | P&L, drawdown, capacity |
| `GET /api/lab/status` | Lab engine state |
| `GET /api/lab/positions` | Open positions enriched with journal data (strategy, SL/TP) |
| `POST /api/lab/close/{trade_id}` | Manually close an open position (v2.0.10) |
| `POST /api/lab/force-close/{symbol}` | Force-close broker position by symbol, bypasses journal (v2.0.15) |
| `POST /api/lab/execute-proposal/{rank}` | Manually execute a ranked live proposal (v2.0.10) |
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
