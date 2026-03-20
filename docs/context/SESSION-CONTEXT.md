# Session Context - Notas Lave Trading System

**PURPOSE:** Read this file at the start of every new Claude session to restore context.
**Last Updated:** 2026-03-21
**Git Branch:** feature/trading-engine-scaffold
**Last Commit:** 939d487 (pushed to origin)

---

## What Is This Project?
An AI-powered trading co-pilot for scalping Gold, Silver, BTC, and ETH. Target: pass FundingPips prop firm challenges. Uses Claude as a decision engine with 3-gate verification.

## What Has Been Built (Session 1)

### Engine (Python/FastAPI) — `engine/`
- **8 strategies:** EMA Crossover, RSI Divergence, Bollinger Bands, Stochastic, VWAP, Fibonacci Golden Zone, ICT Kill Zone, Order Blocks + FVG
- **Confluence Scorer:** Multi-gate scoring with regime-adaptive dynamic weights
- **Claude Decision Engine:** 3-gate verification (confluence >= 6 → Claude confidence >= 7 → risk manager). Works in fallback mode without API key
- **Risk Manager:** FundingPips rules (5% daily DD, 10% total, 45% consistency, 2:1 R:R minimum)
- **Paper Trading Executor:** Open/close positions, SL/TP auto-close every 10s, breakeven at 1:1 R
- **Trade Journal:** SQLite (signal_logs, trade_logs, performance_snapshots)
- **Data Layer:** yfinance for Gold (GC=F), Silver (SI=F), BTC (BTC-USD), ETH (ETH-USD)

### Dashboard (Next.js) — `dashboard/`
- Market cards with live prices and confluence scores
- Strategy signals panel (8 strategies per instrument)
- AI Decision panel: "Evaluate Trade" button + 3-gate status + "Take Trade" button
- Open Positions panel with live P&L and close buttons
- Performance summary (win rate, W/L, total P&L)
- Candlestick charts (Lightweight Charts v5) — user prefers external charting platforms
- Risk status panel (balance, daily P&L, drawdown meters)

### Research — `docs/research/`
- `TRADING-SYSTEM-RESEARCH.md` — Architecture, platforms, learning engine
- `STRATEGIES-DETAILED.md` — 23+ strategies with exact algorithmic rules

## How to Run
```bash
# Terminal 1: Engine
cd engine && ../.venv/bin/python run.py

# Terminal 2: Dashboard
cd dashboard && npm run dev

# Open: http://localhost:3000
```

## CRITICAL FIXES REQUIRED (Before Any Trading)

**Full plan:** `docs/plans/CRITICAL-FIXES.md` — read this first in Session 2.

### Session 2: Foundation Fixes
1. **Fix #1: Replace yfinance with real-time data** — Oanda (Gold/Silver) + Alpaca (BTC/ETH). yfinance is delayed, wrong instruments, no bid/ask.
2. **Fix #2: Position sizing with pip values** — Current formula doesn't know lots vs units vs ounces. Could risk 50x intended amount.
3. **Fix #3: Paper trader realistic execution** — Add spread, slippage, check SL/TP against high/low not close.

### Session 3: Signal Quality
4. **Fix #4: Confluence weight normalization** — 4 scalping signals outweigh 1 fibonacci. Weight per-category, not per-signal.
5. **Fix #5: Multi-timeframe analysis** — 4H trend filter so we don't buy into a downtrend.
6. **Fix #6: Kill zone timezone bug** — Timestamps may be in wrong timezone, session range spans multiple days.

### Session 4: Refinement
7. **Fix #7: Order block mitigation** — OBs should expire after being touched.
8. **Fix #8: State persistence** — Engine restart loses all positions and balance.
9. **Fix #9: RSI divergence staleness** — Swing detection is always late by lookback candles.
10. **Fix #10: Regime detection improvements** — Instrument-specific thresholds, add volume.

### After Fixes: Features
11. Claude API key setup + alerts system
12. More strategies (Camarilla, Break & Retest, etc.)
13. Backtester + learning engine
14. Economic calendar + news blackout
15. MT5 integration for FundingPips

## User Action Required Before Session 2
1. Create Oanda practice account: https://www.oanda.com/apply/demo
2. Create Alpaca paper account: https://alpaca.markets
3. Save API keys in `engine/.env`
4. Optionally: buy GoCharting subscription for order flow analysis (visual only, not for our engine)

## Key Architecture Decisions
1. All math is deterministic code — Claude evaluates context only
2. 3-gate verification: Confluence → Claude → Risk Manager (any gate can block)
3. Dynamic weights shift per market regime (trending/ranging/volatile/quiet)
4. Paper trading first, real broker later
5. Every evaluation logged to SQLite for learning engine
6. Co-pilot mode: system alerts, user decides to take trade
7. Next.js dashboard (user preference, not Streamlit/CLI)
8. User uses external platforms (TradingView/MT5) for chart analysis

## Technical Notes
- Python 3.13 via /opt/homebrew/bin/python3.13 (3.14 too new for numba)
- Venv at project root: .venv/
- FastAPI route order: specific routes (/scan/all) before parameterized (/scan/{symbol})
- Lightweight Charts v5: chart.addSeries(CandlestickSeries, opts)
- yfinance tickers: XAUUSD→GC=F, XAGUSD→SI=F, BTCUSD→BTC-USD, ETHUSD→ETH-USD
- Background position monitor runs every 10s, auto-closes on SL/TP

## User Preferences
- Day trading: 1m/5m/15m/30m/1h entries, 4h/1d context
- Uses external charting (TradingView/MT5), not our charts
- Wants to understand all code (educational comments)
- Co-pilot mode: system suggests, user confirms
- Next.js dashboard from day 1
