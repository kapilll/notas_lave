# Session Context - Notas Lave Trading System

**PURPOSE:** Read this file at the start of every new Claude session to restore context.
**Last Updated:** 2026-03-22 (Session 6 complete — engine running live on Binance Demo)
**Git Branch:** main (commit directly, no feature branches)

---

## What Is This Project?
An AI-powered autonomous trading system for Gold (XAUUSD), Silver (XAGUSD), BTC, and ETH. Supports TWO modes:
- **Personal mode:** Trade your own money on CoinDCX/Binance with leverage (primary, current)
- **Prop mode:** Pass FundingPips challenges with strict prop firm rules

Uses Claude via Vertex AI as a decision engine. The system EVOLVES — every trade teaches, weights adapt, blacklists update.

## How to Run
```bash
# Terminal 1: Start engine (connects to Binance Demo)
cd engine && ../.venv/bin/python run.py

# Terminal 2: Start dashboard
cd dashboard && npm run dev

# Open: http://localhost:3000
# API: http://127.0.0.1:8000/api/health
```

## Current State (Session 6)
- **Engine is LIVE on Binance Demo** — auto-scanning BTCUSDT/ETHUSDT every 60s
- **47 unit tests passing**
- **~70 expert review issues FIXED** out of 177 found
- **All P0 issues resolved** — risk gatekeeper wired, data validation, security, persistence
- **Broker balance:** 4999.98 USDT on demo-fapi.binance.com
- **Mode:** Personal / Full Auto
- **No trades yet** — waiting for qualifying signals (system correctly being patient)

## Git Workflow
- Commit directly to main (no feature branches, no PRs)
- Git remote is `origin` using `github-kapilll` SSH alias

## What Has Been Built (Sessions 1-6)

### Session 5-6 — Expert Review + 70 Fixes + Engine Live

#### 10-Panel Expert Review (Session 5)
- **177 issues found** across 10 expert panels
- Panels: Quant, AI/ML, Algo, Security, DevOps, Data, Compliance, Microstructure, Psychology, Code Quality
- Review prompt: `docs/reviews/REVIEW-PROMPT.md`
- Build-with-experts: `docs/reviews/BUILD-WITH-EXPERTS.md`

#### Session 6 — Massive Fix Sprint (~70 issues fixed)
Root-cause analysis collapsed 177 issues into 13 groups. Fixed via 6 parallel agent lanes:

**Risk Manager Overhaul (Lane A):**
- RC-01: validate_trade() now called before EVERY autonomous trade
- RC-02: Consistency rule is hard block at 45% (was just warning)
- RC-03: Daily drawdown includes unrealized P&L (FundingPips monitors equity)
- RC-04: Total drawdown uses original_starting_balance (static, never drifts)
- RC-05: Hedging detection for prop mode
- AT-36: contract_size in potential_loss (Gold was 100x understated)

**Execution Safety (Lane B):**
- AT-24: Open positions persist to DB, reload on startup (crash recovery)
- AT-25: Cancel orphaned SL/TP on close
- AT-28: CoinDCX now places SL/TP orders
- MM-03: Tick size validation on order prices
- AT-27: CoinDCX retry with exponential backoff

**Learning + Backtester (Lane C):**
- MM-01: Slippage model added to backtester
- QR-14: Walk-forward OOS equity curve reconstructed
- QR-19: Sharpe includes zero-trade days (was inflated ~2x)
- ML-19: Weight adjustment uses avg P&L per trade
- ML-20/TP-07: 7-day + 10-trade cooldown between adjustments
- TP-03: Loss streak throttle regime-conditional (not gambler's fallacy)

**Agent Integration (Lane D):**
- AT-29: Paper trader SL/TP disabled when using real broker
- ML-18: Prediction accuracy resolves automatically
- RC-07: Weekend gap protection for Gold/Silver
- TP-08: Neutral trade notifications (no "WIN/LOSS" panic triggers)

**Data Pipeline (Lane E):**
- DE-01: OHLC validation on Candle model
- DE-02/10: Cache never stores empty results
- MM-02: Dynamic spread with session multipliers
- DE-03: Data lineage columns in SignalLog
- DE-11/RC-08: DST handling via zoneinfo

**API/Security (Lane F):**
- SEC-01: API key auth for mutation endpoints
- SEC-02: Bind to 127.0.0.1 (was 0.0.0.0)
- OPS-20: FastAPI lifespan pattern
- SEC-11: Input validation on query params

**Architecture (Lane G):**
- CQ-01: SQLAlchemy session factory + WAL mode
- CQ-02: A/B testing consolidated into main DB
- CQ-04: Backtester accepts strategies param (thread-safe)

### Previous Sessions (1-4)
See git history for details. Key milestones:
- Session 1-3: Built 14 strategies, backtester, learning engine, Binance Demo
- Session 4: First expert review (48 issues), 30 fixed, prediction accuracy tracker

### Engine (Python/FastAPI) — `engine/`

#### Risk Controls (Mode-Aware)
- validate_trade() is the SINGLE gate for ALL trades
- Prop mode: 5% daily DD, 10% total DD, 45% consistency, no hedging, news blackout
- Personal mode: 6% daily DD, 20% total DD, no consistency rule, flexible R:R
- Unrealized P&L included in drawdown (FundingPips monitors equity)
- Weekend gap protection for metals

#### Learning Engine (CLOSED-LOOP + PERSISTENT)
- Learned weights/blacklists persist to disk (data/learned_state.json, data/learned_blacklists.json)
- Exponential decay weighting (30-day half-life)
- Blacklist merges (never replaces static blacklists)
- 7-day + 10-trade cooldown between adjustments (prevents tilt)
- Process-quality grading (not outcome-biased)

#### Broker Integrations
- **Binance Demo:** Full retry, reconnect, rate limiting, tick size validation, orphan cleanup
- **CoinDCX:** SL/TP placement, retry with backoff
- **Paper:** Position persistence to DB, crash recovery
- All brokers: safe_float(), explicit HTTP dispatch, UUID-16

### Tests
- **47 unit tests** passing
- Position sizing, risk manager, calendar, all strategies
- Run: `.venv/bin/python -m pytest engine/tests/ -x -q`

## Environment (.env — NOT committed)
```
TWELVEDATA_API_KEY=<set>
CLAUDE_PROVIDER=vertex
GOOGLE_CLOUD_PROJECT=gcia-dev-app-wsky
GOOGLE_CLOUD_REGION=us-east5
TELEGRAM_BOT_TOKEN=<set>
TELEGRAM_CHAT_ID=<set>
BINANCE_TESTNET_KEY=<set>
BINANCE_TESTNET_SECRET=<set>
BROKER=binance_testnet
TRADING_MODE=personal
```

## Trading Roadmap

### Phase 1: Paper Trading on Binance Demo (IN PROGRESS)
- Engine running, auto-scanning BTCUSDT/ETHUSDT
- Monitor trades + collect data for accuracy tracking
- Run walk-forward backtest for OOS validation
- Let it run 24-48 hours, check Telegram for trade notifications

### Phase 2: CoinDCX Live (2000-3000 INR)
- CoinDCX broker has SL/TP placement + retry logic
- Set BROKER=coindcx + keys in .env
- Verify fee calculations match actual CoinDCX invoices first

### Phase 3: FundingPips Challenge (~$60)
- Switch to TRADING_MODE=prop in .env
- MT5 connector built, requires Windows VPS

## What To Do Next

### Immediate
1. **Monitor Binance Demo trades** — watch for first auto-trade via Telegram
2. **Run walk-forward backtest** — `curl http://127.0.0.1:8000/api/backtest/walk-forward/BTCUSD`
3. **Check accuracy** — `curl http://127.0.0.1:8000/api/accuracy/score`
4. **Fix TwelveData rate limit** — metals scanning burns 800/day credits on data we can't trade in personal mode

### Remaining Issues (~100 OPEN)
See `docs/reviews/ISSUES.md`. Key remaining:
- OPS-03: Structured logging (replace 95 print() statements)
- QR-17: Optimizer multiple comparisons correction
- SEC-04/08: HMAC timing-attack resistance, TLS pinning
- MM-05/06/07: Atomic SL/TP, market impact model, funding rates
- CQ-03: Dependency injection (large refactor)

## Key Files
| File | Purpose |
|------|---------|
| `CLAUDE.md` | Project overview, rules, tech stack |
| `docs/context/SESSION-CONTEXT.md` | THIS FILE — read first |
| `docs/reviews/ISSUES.md` | Expert review issues (~70 fixed, ~100 remaining) |
| `docs/reviews/REVIEW-PROMPT.md` | 10-panel expert review prompt (reusable) |
| `docs/reviews/BUILD-WITH-EXPERTS.md` | Expert engineers as builders (not just reviewers) |
| `engine/src/agent/autonomous_trader.py` | THE CORE: 24/7 autonomous loop |
| `engine/src/risk/manager.py` | Mode-aware risk gatekeeper (prop vs personal) |
| `engine/src/backtester/engine.py` | Backtester + walk-forward + slippage model |
| `engine/src/confluence/scorer.py` | Dynamic blacklist + weight persistence |
| `engine/src/execution/binance_testnet.py` | Binance Demo broker |
| `engine/src/data/instruments.py` | Instrument specs + dynamic spread model |

## Technical Notes
- Python 3.13 via /opt/homebrew/bin/python3.13 (3.14 incompatible with numba)
- Venv at project root: .venv/
- Server binds to 127.0.0.1:8000 (localhost only for security)
- Start with DEV_MODE=true for auto-reload during development
- Twelve Data: 800 calls/day (exhausts fast scanning metals — use personal mode for crypto only)
- CCXT: Binance BTC/USDT, no API key for public data
- Vertex AI: gcloud auth application-default login
- 47 unit tests (run: `.venv/bin/python -m pytest engine/tests/ -x -q`)
- Expert review: run every 3-5 sessions via docs/reviews/REVIEW-PROMPT.md
- Agent permissions in .claude/settings.local.json (Edit, Write, Bash allowed for parallel agents)
