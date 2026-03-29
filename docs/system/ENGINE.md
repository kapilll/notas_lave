# Trading Engine

> Last verified against code: v1.7.8 (2026-03-29)

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
│   └── instruments.py # Thin re-export of data/instruments.py (QR-03 merged)
├── execution/        # Broker adapters
│   ├── registry.py   # @register_broker decorator + create_broker()
│   ├── delta.py      # Delta Exchange testnet (ACTIVE)
│   ├── paper.py      # In-memory test broker
│   ├── coindcx.py    # CoinDCX (future)
│   └── mt5.py        # MetaTrader 5 (future)
├── strategies/       # 6 composite strategies (replaced 12 single-indicator strategies in v1.7.0)
│   ├── base.py       # BaseStrategy ABC with shared helpers (ATR, volume check)
│   ├── registry.py   # Strategy list + optimizer param loading
│   ├── volume_analysis.py # Volume delta, CVD, profile, spike detection
│   └── *.py          # trend_momentum, mean_reversion, level_confluence, breakout, williams, order_flow
├── engine/
│   ├── lab.py        # Lab Engine — autonomous trading loop (Strategy Arena v3)
│   ├── leaderboard.py # StrategyLeaderboard — trust scores, dynamic thresholds, win/loss
│   ├── event_bus.py  # Pub/sub with failure policies
│   ├── pnl.py        # P&L = current_balance - original_deposit
│   └── scheduler.py  # APScheduler wrapper
├── confluence/
│   └── scorer.py     # Legacy confluence scorer (not used by Lab Engine since v1.7.0)
├── risk/
│   └── manager.py    # RiskManager — validates every Lab trade
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

The main trading loop. Runs as an asyncio background task. Uses **Strategy Arena** architecture since v1.7.0.

**Pace presets:**
| Pace | Entry TFs | Min R:R | Max Concurrent | Scan Interval |
|------|-----------|---------|----------------|---------------|
| conservative | 1h | 3.0 | 3 | 60s |
| balanced | 15m, 1h | 2.0 | 5 | 45s |
| aggressive | 15m, 30m, 1h | 2.0 | 8 | 30s |

**Tick cycle (Strategy Arena):**
1. Fetch `balance` once per tick (reused across all proposals)
2. For each instrument × timeframe: run each of the 6 strategies independently
3. Each strategy returns a `Signal` (entry, SL, TP, score, factors)
4. Each signal becomes a `TradeProposal` with:
   - `arena_score = 40% signal + 25% R:R + 20% trust + 15% win_rate`
   - Dry-run: check broker symbol mapping → if unmapped, `will_execute=False, block_reason=...`
   - Dry-run: position size check → if too small, `will_execute=False, block_reason=...`
   - `notional_usd` and `margin_usd` computed and stored
5. Proposals cached (expire after 2× scan_interval, filtered on `/api/lab/proposals`)
6. Best proposal per tick: highest `arena_score` that `will_execute=True`
7. `RiskManager.validate_trade()` → Execute via broker → Log trade
8. Strategy Leaderboard updated: win → trust +3, loss → trust -5
9. Monitor open positions: check SL/TP against 1m candle highs/lows
10. Reconcile journal with broker (detect exchange-side closes)

**Key constants in lab.py:**
- `RISK_PER_TRADE = 0.05` (5%) — must match `max_risk_per_trade_pct` in config.py
- Position sizing: always `leverage=spec.max_leverage` (BTCUSD/ETHUSD = 15×, FundingPips = 1×)
- All 11 LAB_INSTRUMENTS have `exchange_symbols["delta"]` — matches Delta testnet product list

**Strategy Leaderboard (engine/leaderboard.py):**
- Per-strategy trust score (0–100, starts at 50)
- Win: +3 points, Loss: -5 points (asymmetric — losses hurt more)
- Trust < 20: strategy SUSPENDED (won't propose)
- Trust > 70: dynamic threshold lowers (more opportunities as reward)
- Default signal threshold: 65/100

**Features:**
- Calls `RiskManager.validate_trade()` before every trade
- Loss streak throttle: halves risk after 3 consecutive losses
- Error backoff: 10 consecutive tick errors triggers 5-minute pause + Telegram alert
- Graceful shutdown: `stop()` is async, logs all open positions before stopping
- Writes to BOTH EventStore and SQLAlchemy TradeLog (ML-02 bridge)
- TradeLog records: `proposing_strategy`, `strategy_score`, `strategy_factors`, `competing_proposals`

## Entry Point (run.py)

```python
# 1. Import all brokers (registers them)
import notas_lave.execution.paper
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
| GET | `/api/lab/risk` | Lab risk state (balance, drawdown, can_trade, max_concurrent) |
| GET | `/api/lab/pace` | Current pace config (entry_tfs, min_rr, max_concurrent) |
| GET | `/api/lab/arena` | Strategy arena status (all 6 strategies with metrics) |
| GET | `/api/lab/arena/leaderboard` | Strategies sorted by trust score / P&L |
| GET | `/api/lab/arena/{strategy_name}` | Single strategy detail + recent trades |
| GET | `/api/lab/proposals` | Current pending proposals (filtered: non-stale only) |
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
- **Volume is always checked** (never disabled) — uses last completed candle, not the forming one.
- **Never `UPDATE` the EventStore** — only `INSERT` new events. State is reconstructed by replay.
- **`data/instruments.py` is the single instrument registry** — `core/instruments.py` is a thin re-export.
- **Position sizing always passes `leverage=spec.max_leverage`** — never default 1.0 for leveraged instruments.
