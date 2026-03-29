# Notas Lave — AI Trading System

## Quick Reference

| What | Where |
|------|-------|
| **System docs** | `docs/system/*.md` — read the one for the subsystem you're working on |
| **Architecture diagrams** | `architecture/*.c4` — LikeC4 source. Preview: `npx likec4 dev architecture/` |
| **Strategy research** | `docs/research/STRATEGIES-DETAILED.md` |
| **Dev process** | `docs/DEVELOPMENT-PROCESS.md` — research → backtest → build → test → deploy → measure |
| **Expert review** | `docs/reviews/REVIEW-PROMPT.md` (Mode A: fresh, Mode B: reconcile) |
| **Changelog** | `CHANGELOG.md` |

## Current State

- **Version:** check `engine/pyproject.toml` and `/health` endpoint
- **VM:** GCP Mumbai (`asia-south1-b`), IP `34.100.222.148`
- **Broker:** Delta Exchange testnet (only broker, Binance removed)
- **Dashboard:** `http://34.100.222.148:3000`
- **Engine:** `http://34.100.222.148:8000`
- **Currency:** USD only (no INR)

## Workflow

```
feature branch → PR (tests run) → merge → notas-release vX.Y.Z → deploy
```

- **Never push to main.** Always use PRs.
- **Bump `engine/pyproject.toml` version** in every PR. CI fails if version already has a tag.
- **Update `CHANGELOG.md`** with what changed.
- **Update `docs/system/`** when you fix something — add a rule so it can't regress.
- **Update `architecture/model.c4`** when architecture changes.
- Release alias: `notas-release v1.5.0` (creates GitHub Release, triggers deploy)
- SSH alias: `nlvmssh` (connects to Mumbai VM)

## Trading Rules

- Every trade MUST pass `RiskManager.validate_trade()` before execution
- Volume analysis is integrated into composite strategies (each strategy checks volume internally)
- Position sizing via `InstrumentSpec.calculate_position_size()` (never naive formulas)
- Loss streak throttle: halves risk after 3 consecutive losses
- FundingPips (prop mode): 5% daily DD, 10% total DD (static), 45% consistency, news blackout

## Architecture (key flows)

```
Market Data (CCXT/TwelveData)
  → Candles (15s cache) + Order Flow (order book, trades, funding, OI)
  → 6 Composite Strategies (each runs independently)
    [Trend Momentum | Mean Reversion | Level Confluence |
     Breakout | Williams System | Order Flow System]
  → Strategy Arena (best proposal wins, trust scores evolve)
  → Risk Manager (validate)
  → Delta Broker (place_order)
  → EventStore + SQLAlchemy (dual write, includes proposing_strategy)
  → Strategy Leaderboard (win/loss → trust score → dynamic threshold)
  → Telegram alert
  → Learning Engine (analyze → recommend → evolve)
```

## Code Rules

- All imports: `from notas_lave.X import Y`
- No hardcoded values — env vars or runtime state
- No module-level singletons (use DI Container)
- `data/instruments.py` is the single instrument registry
- Volume is always checked (never disabled) — uses last completed candle, not forming
- `/health` version comes from `importlib.metadata` (reads `pyproject.toml`)

## Key API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Version + status |
| `GET /api/broker/status` | Balance, positions from Delta |
| `GET /api/risk/status` | P&L, drawdown, capacity |
| `GET /api/lab/status` | Lab engine state |
| `GET /api/scan/all` | Confluence scan all instruments |
| **Backtesting** | |
| `POST /api/backtest/arena/{symbol}` | Run arena backtest (strategies compete) |
| `POST /api/backtest/walk-forward/{symbol}` | Walk-forward validation backtest |
| `GET /api/backtest/leaderboard` | Strategy performance leaderboard |
| **Learning & Analysis** | |
| `GET /api/learning/summary` | Learning system state |
| `GET /api/learning/strategies` | Per-strategy metrics |
| `GET /api/learning/recommendations` | Actionable suggestions |
| `GET /api/learning/trade-grades` | Trade quality scores |
| `GET /api/learning/patterns` | Detected patterns |
| `GET /api/learning/accuracy` | Prediction accuracy |
| `POST /api/learning/analyze-now` | Trigger immediate analysis |
| `POST /api/learning/review` | Request Claude review |
| `POST /api/learning/optimize/{symbol}` | Optimize strategy parameters |
| **Journal** | |
| `GET /api/journal/trades` | Trade history |
| `GET /api/journal/performance` | Performance metrics |
| `GET /api/costs/summary` | Trading costs breakdown |
