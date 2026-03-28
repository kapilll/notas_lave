# Notas Lave — AI Trading System

## Quick Reference

| What | Where |
|------|-------|
| **System docs** | `docs/system/*.md` — read the one for the subsystem you're working on |
| **Architecture diagrams** | `architecture/*.c4` — LikeC4 source. Preview: `npx likec4 dev architecture/` |
| **Strategy research** | `docs/research/STRATEGIES-DETAILED.md` |
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
- Volume analysis multiplies confluence score (0.6x weak → 1.5x strong)
- Position sizing via `InstrumentSpec.calculate_position_size()` (never naive formulas)
- Loss streak throttle: halves risk after 3 consecutive losses
- FundingPips (prop mode): 5% daily DD, 10% total DD (static), 45% consistency, news blackout

## Architecture (key flows)

```
Market Data (CCXT/TwelveData)
  → Candles (15s cache)
  → 12 Strategies → Signals
  → Confluence Scorer (regime-weighted + volume multiplier)
  → Risk Manager (validate)
  → Delta Broker (place_order)
  → EventStore + SQLAlchemy (dual write)
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
| `GET /api/learning/recommendations` | Actionable suggestions |
