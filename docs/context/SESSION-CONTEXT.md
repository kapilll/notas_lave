# Session Context - Notas Lave Trading System

**PURPOSE:** Read this file at the start of every new Claude session to restore context.
**Last Updated:** 2026-03-21 (Session 2 complete)
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

## What Has Been Built (Session 1 + Session 2)

### Engine (Python/FastAPI) — `engine/`

#### 14 Strategies across 5 Categories
- **Scalping (6):** EMA Crossover, RSI Divergence, Bollinger Bands, Stochastic, Camarilla Pivots, EMA 200/1000 Gold
- **Volume (1):** VWAP Scalping
- **Fibonacci (1):** Golden Zone (50-61.8%)
- **ICT/SMC (4):** Kill Zone + Asian Range, Order Blocks + FVG, London Breakout, NY Open Range
- **Breakout (2):** Break & Retest, Momentum Breakout + ATR

Session 2 added: Camarilla Pivots, EMA 200/1000 Gold, London Breakout, NY Open Range, Break & Retest, Momentum Breakout

#### Confluence Scorer
- Per-category weighted scoring (5 categories: scalping, ict, fibonacci, volume, breakout)
- Regime-adaptive weights (TRENDING/RANGING/VOLATILE/QUIET)
- Multi-timeframe HTF trend filter (40% penalty for counter-trend)

#### Risk Controls (10 Levers — Session 2)
1. Risk per trade: 0.3% (conservative)
2. Max concurrent: 1 trade at a time
3. Min signal score: 60 (higher bar)
4. Signal strength: STRONG only
5. Daily loss circuit breaker: 4% (FundingPips = 5%)
6. Total drawdown halt: 8% (FundingPips = 10%)
7. Trade cooldown: 5 candles between trades
8. Max trades per day: 4
9. Trailing breakeven: SL moves to entry after 1:1 R:R
10. Regime filter: skip VOLATILE markets
11. Loss streak throttle: halve size after 3 consecutive losses
12. News blackout: 5 min before/after high-impact events

#### Per-Instrument Strategy Blacklists
- **XAUUSD:** order_block_fvg (-$87K), fibonacci_golden_zone (-$15K), vwap_scalping (-$15K)
- **BTCUSD:** break_retest (-$16K), fibonacci_golden_zone (-$1K), order_block_fvg (-$3K)
- Defined in `engine/src/backtester/engine.py` → INSTRUMENT_STRATEGY_BLACKLIST

#### Economic Calendar + News Blackout (Session 2)
- Static schedule: NFP (1st Friday), CPI (~13th), FOMC (8/year), GDP (last Thu)
- `engine/src/data/economic_calendar.py` — generates dates programmatically
- `is_in_blackout(timestamp, minutes)` — used by risk manager, scanner, backtester
- API: `/api/calendar/status`, `/api/calendar/upcoming`

#### Learning Engine (Session 2)
- **Analyzer** (`engine/src/learning/analyzer.py`):
  - Strategy × Instrument performance matrix
  - Strategy × Regime performance matrix
  - Time-of-day analysis (best/worst trading hours)
  - Score threshold analysis (optimal min score)
  - Exit reason breakdown (TP vs SL vs timeout)
  - MFE/MAE tracking
- **Recommendations** (`engine/src/learning/recommendations.py`):
  - Strategy blacklist suggestions per instrument
  - Confluence weight adjustments per regime (from actual P&L data)
  - Optimal score threshold recommendation
  - Best/worst trading hours
- Requires 10+ closed trades in journal
- API: `/api/learning/analysis`, `/api/learning/recommendations`

#### Claude Weekly Review (Session 2)
- `engine/src/learning/claude_review.py` — AI analyzes journal, sends Telegram report
- Covers: top/worst strategies, regime insights, actionable recommendations
- Fallback text report when Claude API unavailable
- API: `POST /api/learning/review`

#### Walk-Forward Optimizer (Session 2)
- `engine/src/learning/optimizer.py` — parameter grid search via backtester
- 8 strategies, 154 parameter combinations
- Saves best params per instrument to `data/optimizer_results.json`
- API: `POST /api/learning/optimize/{symbol}`, `GET /api/learning/optimized-params`

#### Broker Integrations (Session 2)
- **Abstraction:** `engine/src/execution/base_broker.py` — unified interface
- **CoinDCX:** `engine/src/execution/coindcx.py` — HMAC auth, orders, balance, positions
- **MT5:** `engine/src/execution/mt5_broker.py` — FundingPips, Windows-only, graceful fallback
- **Config:** `BROKER=paper|coindcx|mt5` in .env
- API: `/api/broker/status`, `/api/broker/connect`, `/api/broker/balance`, `/api/broker/positions`

#### Other Core Modules
- **Claude Decision Engine:** 3-gate verification. Vertex AI (project: gcia-dev-app-wsky, region: us-east5)
- **Risk Manager:** FundingPips rules enforced. News blackout integrated. State persisted to SQLite
- **Paper Trading Executor:** Spread on entry, SL/TP on high/low, true breakeven, leverage + fee support
- **Trade Journal:** SQLite (signal_logs, trade_logs, performance_snapshots, risk_state)
- **Data Layer:** Twelve Data (spot XAUUSD/XAGUSD), CCXT/Binance (BTCUSD/ETHUSD), yfinance fallback
- **Backtester:** Walk-forward engine with all 10 risk levers + news blackout + leverage + fees
- **Telegram Alerts:** Auto-scanner every 60s, news blackout aware, 15-min cooldown
- **Instrument Specs:** FundingPips (XAUUSD, BTCUSD) + CoinDCX (BTCUSDT, ETHUSDT with leverage/fees)

### Dashboard (Next.js) — `dashboard/`
- Market cards with live prices and confluence scores
- Strategy signals panel with ? info tooltips on all 14 strategies
- AI Decision panel: Evaluate Trade + Take Trade buttons, 3-gate status
- Open Positions panel with live P&L and close buttons
- Performance summary
- **Tools Panel:** Backtest, Signal Journal, Trade History, Strategy Performance, Strategy Guide, AI Insights, Recommendations, News Calendar, Weekly Review, Optimize, Test Telegram, Scan Now, Alert Status
- Regime info with best/worst strategy recommendations (updated for new strategies)
- Candlestick charts (Lightweight Charts v5)
- Risk status panel

### 10 Critical Fixes — ALL APPLIED (Session 1)
1. Real-time data (Twelve Data + CCXT replacing yfinance futures)
2. Position sizing with proper pip values and contract_size
3. Realistic paper trading (spread, slippage, high/low SL check)
4. Confluence weight normalization (per-category not per-signal)
5. Multi-timeframe HTF trend filter
6. Kill zone UTC timezone fix + today-only sessions
7. Order block mitigation (200-candle expiry, 5-touch limit, age decay)
8. State persistence (RiskState table, survives restarts)
9. RSI divergence forming swings (left-side-only for recent)
10. Regime detection (50-candle lookback, dynamic ATR threshold, volume)

### Session Strategy Backtest Fix (Session 2)
- London Breakout, NY Open Range, Session Kill Zone now use candle timestamp
  instead of datetime.now() — works correctly in backtesting

### Backtester Results (with all risk controls — Session 2)
**BTC 5M (Jan-Mar 2026):** 196 trades, 54.6% WR, $3.4K profit, PF 1.15, **3.0% max DD** ✓
**Gold 5M (Jan-Mar 2026):** 131 trades, 58.0% WR, $8.3K profit, PF 1.61, **1.8% max DD** ✓
Both under FundingPips 10% drawdown limit.

## Environment (.env — NOT committed)
```
TWELVEDATA_API_KEY=<set>
CLAUDE_PROVIDER=vertex
GOOGLE_CLOUD_PROJECT=gcia-dev-app-wsky
GOOGLE_CLOUD_REGION=us-east5
TELEGRAM_BOT_TOKEN=<set>
TELEGRAM_CHAT_ID=<set>
```

## Trading Roadmap (User's Plan)

### Phase 1: Paper Trading (CURRENT)
- Paper trade crypto with leverage, simulating CoinDCX conditions
- Practice day trading BTC/ETH with 15x leverage in INR
- Validate strategies work with small capital + leverage

### Phase 2: CoinDCX Live (1000 INR → 5000 INR) — INFRASTRUCTURE READY
- CoinDCX API client built (engine/src/execution/coindcx.py)
- Set BROKER=coindcx + COINDCX_API_KEY/SECRET in .env to go live
- Conservative risk management, grow to 5000 INR

### Phase 3: FundingPips Challenge (~5000 INR / ~$60) — INFRASTRUCTURE READY
- MT5 connector built (engine/src/execution/mt5_broker.py)
- Requires Windows VPS with MT5 terminal installed
- Set BROKER=mt5 + MT5_LOGIN/PASSWORD/SERVER in .env

### Phase 4: Dual Trading
- Trade on both FundingPips (funded) and CoinDCX (personal)
- FundingPips payouts (USD) fund the CoinDCX account
- Scale up personal trading capital from prop firm profits

## What Needs To Be Done Next

### Immediate: Leverage + CoinDCX Paper Trading
1. **Add leverage support to paper trader** — position sizing with margin
2. **Add CoinDCX instrument specs** — crypto pairs, INR fees, min orders
3. **INR-denominated P&L tracking** — small account mode (1000-5000 INR)
4. **Dual mode** — "prop" mode (FundingPips rules) vs "personal" mode (CoinDCX rules)

### Then: CoinDCX Live Integration
5. **CoinDCX API integration** — REST + WebSocket for real order execution
6. **Real-time INR price feeds** — BTC/INR, ETH/INR from CoinDCX

### Ongoing
7. **Parameter tuning per instrument** — Gold vs BTC different settings
8. ~~**Claude weekly review**~~ **DONE** — POST /api/learning/review, sends report via Telegram
9. ~~**Walk-forward optimizer**~~ **DONE** — 8 strategies, 154 param combos, saves best per instrument
10. ~~**Dashboard enhancements**~~ **DONE** — Calendar, AI Insights, Recommendations, Weekly Review, Optimize tools

## Key Files
| File | Purpose |
|------|---------|
| `CLAUDE.md` | Project overview, rules, tech stack |
| `docs/context/SESSION-CONTEXT.md` | THIS FILE — read first in new sessions |
| `docs/research/TRADING-SYSTEM-RESEARCH.md` | Full research |
| `docs/research/STRATEGIES-DETAILED.md` | 23+ strategies with exact rules |
| `docs/plans/CRITICAL-FIXES.md` | 10 critical issues (ALL FIXED) |
| `engine/src/data/instruments.py` | Instrument specs (pip values, contract sizes) |
| `engine/src/data/economic_calendar.py` | News event schedule + blackout check |
| `engine/src/backtester/engine.py` | Backtester with 10 risk levers + blacklists |
| `engine/src/alerts/scanner.py` | Auto-scanner + Telegram alerts |
| `engine/src/learning/analyzer.py` | Learning engine — trade analysis |
| `engine/src/learning/recommendations.py` | Learning engine — actionable suggestions |
| `engine/src/strategies/registry.py` | All 14 strategies registered here |
| `dashboard/lib/strategy-info.ts` | Strategy descriptions for UI (14 strategies) |

## API Endpoints Reference
| Endpoint | Purpose |
|----------|---------|
| `GET /api/scan/{symbol}` | Run all strategies, return confluence score |
| `GET /api/scan/all` | Scan all instruments |
| `GET /api/prices` | Current prices for all instruments |
| `GET /api/evaluate/{symbol}` | Full Claude evaluation |
| `GET /api/risk/status` | Risk manager status |
| `GET /api/backtest/{symbol}` | Run backtest with risk controls |
| `GET /api/calendar/status` | News blackout status + upcoming events |
| `GET /api/calendar/upcoming` | Next N economic events |
| `GET /api/learning/analysis` | Full learning engine analysis |
| `GET /api/learning/recommendations` | Actionable recommendations |
| `GET /api/alerts/status` | Scanner status |
| `POST /api/alerts/scan-now` | Trigger manual scan |
| `POST /api/trade/open/{symbol}` | Open paper trade |
| `POST /api/trade/close/{id}` | Close paper trade |

## Technical Notes
- Python 3.13 via /opt/homebrew/bin/python3.13 (3.14 incompatible with numba)
- Venv at project root: .venv/
- FastAPI route order: specific routes before parameterized
- Lightweight Charts v5: chart.addSeries(CandlestickSeries, opts)
- Twelve Data: XAU/USD format, free 800 calls/day
- CCXT: Binance BTC/USDT, no API key for public data
- Vertex AI: gcloud auth application-default login
- Git: commit directly to main, remote is `origin` (uses github-kapilll SSH alias)
- FundingPips trades SPOT (CFD), not futures
- Session strategies use candle timestamp (not datetime.now()) for backtest compatibility

## User Preferences
- Day trading: 1m/5m/15m/30m/1h entries, 4h/1d context
- Uses external charting (TradingView/GoCharting), not our charts
- Wants to understand all code (educational comments)
- Co-pilot mode: system alerts via Telegram, user decides
- Based in India (Oanda unavailable, using Twelve Data + CCXT)
- Commit directly to main, no feature branches
