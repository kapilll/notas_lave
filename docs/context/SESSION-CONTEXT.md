# Session Context - Notas Lave Trading System

**PURPOSE:** Read this file at the start of every new Claude session to restore context.
**Last Updated:** 2026-03-22 (Session 4 complete)
**Git Branch:** main (commit directly, no feature branches)

---

## What Is This Project?
An AI-powered trading co-pilot for scalping Gold (XAUUSD), Silver (XAGUSD), BTC, and ETH. Target: pass FundingPips prop firm challenges. Uses Claude via Vertex AI as a decision engine with 3-gate verification.

## How to Run
```bash
# Terminal 1: Start engine
cd engine && ../.venv/bin/python run.py

# Terminal 2: Start dashboard
cd dashboard && npm run dev

# Open: http://localhost:3000
```

## Git Workflow
- Commit directly to main (no feature branches, no PRs)
- Git remote is `origin` using `github-kapilll` SSH alias
- Author: Kapil Parashar (kapilll)

## What Has Been Built (Sessions 1-4)

### Session 4 — Expert Review + 30 Fixes + New Features

#### Expert Review System
- **48 issues found** across 3 expert panels (Quant, AI/ML, Algo Trading)
- **30 FIXED**, 15 DEFERRED, 2 WONT_FIX, 1 already fixed
- Reusable review prompt with **10 expert panels** for future reviews
- Files: `docs/reviews/ISSUES.md`, `docs/reviews/REVIEW-PROMPT.md`
- To run review: "Read docs/reviews/REVIEW-PROMPT.md and run the review"

#### P0 Critical Fixes (ALL 11 FIXED)
1. **Walk-forward backtesting** — N-fold rolling OOS validation (`run_walk_forward()`)
2. **Circular blacklists fixed** — blacklists derived from training data only
3. **Optimizer validation** — tests on held-out data, not training set
4. **min_lot risk check** — rejects trade if min_lot exceeds risk budget
5. **Learning feedback loop CLOSED** — blacklists & weights applied at runtime
6. **Confluence scorer filters by blacklist** — dynamic blacklist active in scanner
7. **Regime weights updated** — learning engine adjusts weights on daily review
8. **cancel_order fixed** — DELETE method with symbol parameter
9. **Atomic SL/TP** — SL failure auto-closes position, order IDs tracked
10. **Position reconciliation** — every 5 min local vs exchange check
11. **Walk-forward API** — `GET /api/backtest/walk-forward/{symbol}`

#### P1 High-Priority Fixes (8 FIXED, 4 DEFERRED)
- MIN_TRADES raised to 50 for statistical significance
- Candle-freshness check — only scans on fresh candle close
- Retry logic with exponential backoff (3 attempts)
- Auto-reconnection after 3 consecutive failures
- Order state tracking (main/SL/TP order IDs)
- Agent wired to real brokers via `_get_broker()`
- min_notional check for CoinDCX minimum order sizes
- Deferred: WebSocket feeds, process watchdog, more historical data

#### P2 Fixes (8 FIXED, 5 DEFERRED)
- Sharpe ratio computed from actual daily P&L
- Full analysis dict stored as JSON in journal
- Explicit symbol mapping (no more fragile string replace)
- Risk manager uses UTC dates throughout
- Telegram heartbeat every 6 hours
- API rate limit tracking (1000/min warning)
- Trade analysis window reduced to 60 days

#### P3/P4 Fixes (5 FIXED, 8 DEFERRED)
- `_analyzed` set replaces monkey-patched attribute
- Spread/SL ratio check — rejects if spread >5% of SL
- max_tokens increased to 512 for Claude analysis

#### New Features (Session 4)
- **Prediction Accuracy Tracker** — ML-style accuracy scoring
  - Direction accuracy, target accuracy, score calibration
  - Rolling accuracy history with trend detection
  - Per-strategy and per-regime breakdowns
  - Dashboard tab with graph
  - API: `GET /api/accuracy/score`, `GET /api/accuracy/history`
- **Token/Cost Tracker** — monitors Claude API costs
  - Runtime (trading) vs Build (Claude Code) cost tracking
  - Wired into all 3 Claude API call sites
  - Dashboard tab with breakdown and manual build cost logger
  - API: `GET /api/costs/summary`, `GET /api/costs/history`, `POST /api/costs/log-build`

### Engine (Python/FastAPI) — `engine/`

#### 14 Strategies across 5 Categories
- **Scalping (6):** EMA Crossover, RSI Divergence, Bollinger Bands, Stochastic, Camarilla Pivots, EMA 200/1000 Gold
- **Volume (1):** VWAP Scalping
- **Fibonacci (1):** Golden Zone (50-61.8%)
- **ICT/SMC (4):** Kill Zone + Asian Range, Order Blocks + FVG, London Breakout, NY Open Range
- **Breakout (2):** Break & Retest, Momentum Breakout + ATR

#### Confluence Scorer (NOW WITH DYNAMIC BLACKLIST + WEIGHT UPDATES)
- Per-category weighted scoring (5 categories)
- Regime-adaptive weights — now updated by learning engine daily
- Strategy blacklist — now dynamically applied from learning engine
- Multi-timeframe HTF trend filter (40% penalty for counter-trend)

#### Risk Controls (10 Levers)
1. Risk per trade: 0.3% (conservative)
2. Max concurrent: 1 trade at a time
3. Min signal score: 60 (higher bar)
4. Signal strength: STRONG only
5. Daily loss circuit breaker: 4%
6. Total drawdown halt: 8%
7. Trade cooldown: 5 candles between trades
8. Max trades per day: 6
9. Trailing breakeven: SL moves to entry after 1:1 R:R
10. Regime filter: skip VOLATILE markets
11. Loss streak throttle: halve size after 3 consecutive losses
12. News blackout: 5 min before/after high-impact events
13. **NEW: min_lot risk check — rejects if min_lot exceeds risk budget**
14. **NEW: min_notional check — rejects if below CoinDCX minimum**
15. **NEW: Spread/SL ratio check — rejects if spread >5% of SL distance**

#### Learning Engine (NOW CLOSED-LOOP)
- Analyzer: 60-day window (was 90), multi-dimensional breakdowns
- Recommendations: MIN_TRADES = 50 (was 10) for statistical significance
- **Blacklists NOW APPLIED** to confluence scorer on daily review
- **Weights NOW ADJUSTED** in regime weights on daily review
- Claude trade analysis stores full JSON (grade + lesson + strategy_note + regime_match)
- Walk-forward optimizer validates on held-out data only

#### Prediction Accuracy Engine (NEW)
- `engine/src/learning/accuracy.py` — logs and resolves predictions
- Direction accuracy, target accuracy, score calibration, per-strategy
- Rolling accuracy history with improvement trend detection

#### Token/Cost Tracker (NEW)
- `engine/src/monitoring/token_tracker.py` — tracks API usage and costs
- Wired into trade_learner, decision engine, weekly review

#### Broker Integrations (IMPROVED)
- **Binance Demo:** Retry logic, auto-reconnect, rate limiting, explicit symbol map
- **cancel_order FIXED** — uses DELETE method with symbol parameter
- **Atomic SL/TP** — SL failure auto-closes position
- **Agent wired to brokers** — `_get_broker()` routes to correct broker
- **Position reconciliation** — every 5 min local vs exchange sync
- **Order tracking** — stores main/SL/TP order IDs per position
- **Heartbeat** — Telegram status every 6 hours

#### Autonomous Agent (MAJOR IMPROVEMENTS)
- Candle-freshness check — only scans when candle has closed
- Uses current price for entries (not stale signal price)
- Spread/SL ratio filter
- Wired to real brokers (not just paper_trader)
- Position reconciliation every 5 minutes
- Heartbeat every 6 hours via Telegram
- `_analyzed_trades` set replaces monkey-patched attribute

### Dashboard (Next.js) — `dashboard/`
- All previous panels plus:
- **Prediction Accuracy tab** — score cards, calibration chart, SVG trend graph
- **Token Costs tab** — runtime/build cost breakdown, manual build cost logger
- **Walk-Forward Backtest** — `GET /api/backtest/walk-forward/{symbol}`

### Tests
- **46 unit tests** (was 41 in Session 3, +5 new)
- Position sizing: min_lot risk rejection, min_notional rejection
- All strategies: output validation, crash resistance

## Backtester Results (CAUTION: IN-SAMPLE — use walk-forward for real validation)
**BTC 5M (1 year):** 443 trades, 58.0% WR, $8.2K profit, PF 1.15, 4.9% DD
**ETH 5M (1 year):** 381 trades, 58.0% WR, $6.4K profit, PF 1.14, 3.7% DD
**Gold 5M (60 days):** 131 trades, 58.0% WR, $8.3K profit, PF 1.61, 1.8% DD

**WARNING:** These are in-sample results. Use `GET /api/backtest/walk-forward/{symbol}` for out-of-sample validation. The walk-forward endpoint derives blacklists from training data only and tests on unseen data.

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
```

## Trading Roadmap

### Phase 1: Paper Trading on Binance Demo (READY TO START)
- Agent now wired to Binance Demo broker
- Start engine → agent auto-trades on demo.binance.com
- Monitor trades + collect data for accuracy tracking
- Run walk-forward backtest to get true OOS performance numbers

### Phase 2: CoinDCX Live (2000-3000 INR)
- CoinDCX API client built, min_notional checks in place
- Set BROKER=coindcx + keys in .env
- Verify fee calculations match actual CoinDCX invoices first

### Phase 3: FundingPips Challenge (~$60)
- MT5 connector built
- Requires Windows VPS with MT5 terminal

### Phase 4: Dual Trading
- FundingPips payouts fund CoinDCX account

## Motto: EVOLVE
The system continuously evolves. Every trade teaches. Every loss makes it smarter.
Claude IS the trader. The human is the overseer.
The feedback loop is now CLOSED — blacklists and weights adapt automatically.

## What To Do Next

### Immediate (Next Session)
1. **Start engine on Binance Demo** — `cd engine && ../.venv/bin/python run.py`
2. **Run walk-forward backtest** — `GET /api/backtest/walk-forward/BTCUSD` to get true OOS numbers
3. **Monitor trades** — watch demo.binance.com + Telegram heartbeats
4. **Let it run 24-48 hours** — collect prediction accuracy data
5. **Check accuracy dashboard** — is direction accuracy >50%? Is it improving?
6. **Check cost dashboard** — how much is Claude API costing per day?

### Deferred Items (15 issues)
See `docs/reviews/ISSUES.md` for full list. Key ones:
- Download 2+ years of historical data for RSI Divergence validation
- Add WebSocket price feeds (currently using candle-freshness check)
- Add process watchdog (systemd) for deployment
- Monte Carlo simulation, A/B testing framework
- CoinDCX live testing before real money

## Key Files
| File | Purpose |
|------|---------|
| `CLAUDE.md` | Project overview, rules, tech stack |
| `docs/context/SESSION-CONTEXT.md` | THIS FILE — read first |
| `docs/reviews/ISSUES.md` | 48 expert review issues with status |
| `docs/reviews/REVIEW-PROMPT.md` | 10-panel expert review prompt (reusable) |
| `engine/src/agent/autonomous_trader.py` | THE CORE: 24/7 autonomous loop |
| `engine/src/agent/config.py` | Agent permissions and safety boundaries |
| `engine/src/backtester/engine.py` | Backtester + walk-forward + blacklists |
| `engine/src/confluence/scorer.py` | Dynamic blacklist + weight updates |
| `engine/src/learning/accuracy.py` | Prediction accuracy tracker |
| `engine/src/monitoring/token_tracker.py` | Token/cost tracker |
| `engine/src/execution/binance_testnet.py` | Binance Demo (retry, reconnect, rate limit) |
| `engine/src/data/instruments.py` | Instrument specs + min_lot/min_notional checks |

## API Endpoints Reference
| Endpoint | Purpose |
|----------|---------|
| `GET /api/scan/{symbol}` | Run all strategies, return confluence score |
| `GET /api/scan/all` | Scan all instruments |
| `GET /api/evaluate/{symbol}` | Full Claude evaluation |
| `GET /api/risk/status` | Risk manager status |
| `GET /api/backtest/{symbol}` | Run in-sample backtest |
| `GET /api/backtest/walk-forward/{symbol}` | **NEW: N-fold OOS validation** |
| `GET /api/accuracy/score` | **NEW: Prediction accuracy metrics** |
| `GET /api/accuracy/history` | **NEW: Rolling accuracy for graph** |
| `GET /api/costs/summary` | **NEW: Token usage and costs** |
| `GET /api/costs/history` | **NEW: Daily cost history** |
| `POST /api/costs/log-build` | **NEW: Log build session cost** |
| `GET /api/learning/analysis` | Full learning engine analysis |
| `GET /api/learning/recommendations` | Actionable recommendations |
| `GET /api/agent/status` | Autonomous agent status |
| `POST /api/trade/open/{symbol}` | Open paper trade |
| `POST /api/trade/close/{id}` | Close paper trade |
| `GET /api/calendar/status` | News blackout status |

## Technical Notes
- Python 3.13 via /opt/homebrew/bin/python3.13 (3.14 incompatible with numba)
- Venv at project root: .venv/
- FastAPI route order: specific routes before parameterized
- Twelve Data: XAU/USD format, free 800 calls/day
- CCXT: Binance BTC/USDT, no API key for public data
- Vertex AI: gcloud auth application-default login
- Git: commit directly to main, remote is `origin` (github-kapilll SSH alias)
- FundingPips trades SPOT (CFD), not futures
- 46 unit tests (run: `.venv/bin/python -m pytest engine/tests/ -x -q`)
- Expert review: run every 3-5 sessions via docs/reviews/REVIEW-PROMPT.md
