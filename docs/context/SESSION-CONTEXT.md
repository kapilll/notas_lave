# Session Context - Notas Lave Trading System

**PURPOSE:** Read this file at the start of every new Claude session to restore context.
**Last Updated:** 2026-03-21
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
- Git remote uses `github-kapilll` SSH alias
- Author: Kapil Parashar (kapilll)

## What Has Been Built (Session 1 — COMPLETE)

### Engine (Python/FastAPI) — `engine/`
- **14 strategies across 5 categories:**
  - Scalping (6): EMA Crossover, RSI Divergence, Bollinger Bands, Stochastic, Camarilla Pivots, EMA 200/1000 Gold
  - Volume (1): VWAP Scalping
  - Fibonacci (1): Golden Zone (50-61.8%)
  - ICT/SMC (4): Kill Zone + Asian Range, Order Blocks + FVG, London Breakout, NY Open Range
  - Breakout (2): Break & Retest, Momentum Breakout + ATR
- **Confluence Scorer:** Per-category weighted scoring (5 categories), regime-adaptive weights, multi-timeframe HTF trend filter (40% penalty for counter-trend)
- **Claude Decision Engine:** 3-gate verification. Supports Vertex AI (project: gcia-dev-app-wsky, region: us-east5) and direct Anthropic API
- **Risk Manager:** FundingPips rules enforced. Proper position sizing via instruments.py (contract_size, pip_value, lot_step). State persisted to SQLite
- **Paper Trading Executor:** Spread on entry, SL/TP checked against candle high/low, true breakeven (entry + spread), P&L uses contract_size
- **Trade Journal:** SQLite (signal_logs, trade_logs, performance_snapshots, risk_state)
- **Data Layer:** Twelve Data (spot XAUUSD/XAGUSD), CCXT/Binance (BTCUSD/ETHUSD), yfinance fallback
- **Backtester:** Walk-forward engine, realistic spread, per-strategy breakdown, Sharpe/drawdown/profit factor
- **Telegram Alerts:** Auto-scanner every 60s, alerts on score >= 5, 15-min cooldown, trade open/close notifications
- **Instrument Specs:** instruments.py with pip_size, contract_size, spread, lot constraints

### Dashboard (Next.js) — `dashboard/`
- Market cards with live prices and confluence scores
- Strategy signals panel with ? info tooltips on every strategy
- AI Decision panel: Evaluate Trade + Take Trade buttons, 3-gate status
- Open Positions panel with live P&L and close buttons
- Performance summary
- **Tools Panel:** Backtest, Signal Journal, Trade History, Strategy Performance, Strategy Guide, Test Telegram, Scan Now, Alert Status
- Regime info with best/worst strategy recommendations
- Candlestick charts (Lightweight Charts v5)
- Risk status panel

### 10 Critical Fixes — ALL APPLIED
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

### Backtester Results (BTC 5M, Jan-Mar 2026)
- 2,385 trades, 40.1% win rate, $479K net P&L, 1.25 profit factor
- RSI Divergence: star (66% WR, $337K). Order Block FVG: most trades (1,924)
- Max drawdown 13.3% — needs tighter risk for prop firm (10% limit)

## Environment (.env — NOT committed)
```
TWELVEDATA_API_KEY=<set>
CLAUDE_PROVIDER=vertex
GOOGLE_CLOUD_PROJECT=gcia-dev-app-wsky
GOOGLE_CLOUD_REGION=us-east5
TELEGRAM_BOT_TOKEN=<set>
TELEGRAM_CHAT_ID=<set>
```

## What Needs To Be Done Next

### Priority 1: More Strategies + Tuning — PARTIALLY DONE
1. ~~**Add 5-7 more strategies**~~ **DONE** — Added 6: Camarilla Pivots, EMA 200/1000 Gold, London Breakout, NY Open Range, Break & Retest, Momentum Breakout + ATR. Now 14 strategies across 5 categories.
2. **Parameter tuning per instrument** — Gold needs different settings than BTC
3. **Tighten backtester risk** — Max DD was 13.3%, must be < 10%

### Priority 2: Intelligence
4. **Economic calendar + news blackout** — Block trades 5 min around high-impact news
5. **Learning engine Phase 1** — Analyze journal: best strategy per instrument/session/regime
6. **Claude weekly review** — AI analyzes trade journal, suggests weight adjustments

### Priority 3: Production
7. **Walk-forward optimizer** — Auto-tune parameters weekly
8. **Real broker API** — Actual paper trading with real fills
9. **MT5 integration** — Connect to FundingPips for live trading

## Key Files
| File | Purpose |
|------|---------|
| `CLAUDE.md` | Project overview, rules, tech stack |
| `docs/context/SESSION-CONTEXT.md` | THIS FILE — read first in new sessions |
| `docs/research/TRADING-SYSTEM-RESEARCH.md` | Full research |
| `docs/research/STRATEGIES-DETAILED.md` | 23+ strategies with exact rules |
| `docs/plans/CRITICAL-FIXES.md` | 10 critical issues (ALL FIXED) |
| `engine/src/data/instruments.py` | Instrument specs |
| `engine/src/backtester/engine.py` | Backtester |
| `engine/src/alerts/scanner.py` | Auto-scanner + Telegram alerts |
| `dashboard/lib/strategy-info.ts` | Strategy descriptions for UI |

## Technical Notes
- Python 3.13 via /opt/homebrew/bin/python3.13 (3.14 incompatible)
- Venv at project root: .venv/
- FastAPI route order: specific routes before parameterized
- Lightweight Charts v5: chart.addSeries(CandlestickSeries, opts)
- Twelve Data: XAU/USD format, free 800 calls/day
- CCXT: Binance BTC/USDT, no API key for public data
- Vertex AI: gcloud auth application-default login
- Git: commit directly to main, push via github-kapilll SSH alias
- FundingPips trades SPOT (CFD), not futures

## User Preferences
- Day trading: 1m/5m/15m/30m/1h entries, 4h/1d context
- Uses external charting (TradingView/GoCharting), not our charts
- Wants to understand all code (educational comments)
- Co-pilot mode: system alerts via Telegram, user decides
- Based in India (Oanda unavailable, using Twelve Data + CCXT)
- Commit directly to main, no feature branches
