# Session Context - Notas Lave Trading System

**PURPOSE:** Read this file at the start of every new Claude session to restore context.
**Last Updated:** 2026-03-21
**Git Branch:** feature/trading-engine-scaffold
**Last Commit:** 377d609

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

## What Needs To Be Done Next

### Priority 1: Make It Tradeable
1. **Claude API key setup** — Add ANTHROPIC_API_KEY to engine/.env (currently fallback mode)
2. **Alerts system** — Notify when high-confluence setup fires (Telegram/desktop)
3. **Economic calendar** — Detect news events, enforce 5-min blackout

### Priority 2: More Intelligence
4. **More strategies** — 15 remaining from research (Camarilla, Break & Retest, London/NY Breakout, etc.)
5. **Learning engine Phase 1** — Analyze journal: which strategies win per instrument/session/regime
6. **Claude weekly review** — AI analyzes trade journal and suggests weight adjustments

### Priority 3: Production
7. **Backtester** — Test strategies on historical data
8. **Real broker connection** — Oanda (Gold/Silver) + Alpaca (BTC/ETH) paper trading
9. **Walk-forward optimizer** — Auto-tune parameters weekly
10. **MT5 integration** — Connect to FundingPips for live trading

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
