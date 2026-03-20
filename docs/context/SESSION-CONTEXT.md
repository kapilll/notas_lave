# Session Context - Notas Lave Trading System

**PURPOSE:** Read this file at the start of every new Claude session to restore context.
**Last Updated:** 2026-03-21
**Git Branch:** main (all PRs merged)
**Last Merged PR:** feat/backtester (3a22820)

---

## What Is This Project?
An AI-powered trading co-pilot for scalping Gold, Silver, BTC, and ETH. Target: pass FundingPips prop firm challenges. Uses Claude (via Vertex AI) as a decision engine with 3-gate verification.

## What Has Been Built (Session 1 — Complete)

### Engine (Python/FastAPI) — `engine/`
- **8 strategies:** EMA Crossover, RSI Divergence, Bollinger Bands, Stochastic, VWAP, Fibonacci Golden Zone, ICT Kill Zone, Order Blocks + FVG
- **Confluence Scorer:** Per-category weighted scoring with regime-adaptive dynamic weights, multi-timeframe HTF trend filter (40% penalty for counter-trend)
- **Claude Decision Engine:** 3-gate verification (confluence >= 6 -> Claude confidence >= 7 -> risk manager). Supports Vertex AI (AnthropicVertex) and fallback mode
- **Risk Manager:** FundingPips rules. Proper position sizing with instrument specs (contract_size, pip_value, lot_step). State persisted to SQLite across restarts
- **Paper Trading Executor:** Spread on entry, SL/TP checked against candle high/low, true breakeven (entry + spread), P&L uses contract_size
- **Trade Journal:** SQLite (signal_logs, trade_logs, performance_snapshots, risk_state)
- **Data Layer:** Twelve Data (spot XAUUSD/XAGUSD), CCXT/Binance (BTCUSD/ETHUSD), yfinance fallback
- **Backtester:** Walk-forward engine with realistic spread, per-strategy breakdown, Sharpe ratio, max drawdown tracking
- **Instrument Specs:** `instruments.py` with pip_size, contract_size, spread, lot constraints per instrument

### Dashboard (Next.js) — `dashboard/`
- Market cards with live prices and confluence scores
- Strategy signals panel with ? info tooltips on every strategy
- AI Decision panel: Evaluate Trade + Take Trade buttons, 3-gate status
- Open Positions panel with live P&L and close buttons
- Performance summary (win rate, W/L, total P&L)
- **Tools Panel** with 5 buttons:
  - Backtest — run historical test on selected instrument
  - Signal Journal — past evaluations
  - Trade History — closed trades with P&L
  - Strategy Performance — per-strategy win/loss analysis
  - Strategy Guide — educational info on all 8 strategies
- Regime info displayed with best/worst strategy recommendations
- Candlestick charts (Lightweight Charts v5)
- Risk status panel

### 10 Critical Fixes — ALL DONE
1. Real-time data (Twelve Data + CCXT) replacing delayed yfinance futures
2. Position sizing with proper pip values and contract_size
3. Realistic paper trading (spread, slippage, high/low SL check)
4. Confluence weight normalization (per-category, not per-signal)
5. Multi-timeframe HTF trend filter
6. Kill zone timezone fix (UTC normalization, today-only sessions)
7. Order block mitigation (expiry after 200 candles, 5-touch limit)
8. State persistence (RiskState table, survives restarts)
9. RSI divergence forming swings (left-side-only for recent)
10. Regime detection (50-candle lookback, dynamic ATR threshold, volume)

### Backtester Results (BTC 5M, Jan-Mar 2026)
- 2,385 trades, 40.1% win rate, $479K net P&L, 1.25 profit factor
- RSI Divergence: star performer (66% WR, $337K)
- Order Block FVG: most trades (1,924) but only 35.9% WR
- Max drawdown 13.3% — needs tighter risk for prop firm (10% limit)

## How to Run
```bash
# Terminal 1: Engine
cd engine && ../.venv/bin/python run.py

# Terminal 2: Dashboard
cd dashboard && npm run dev

# Open: http://localhost:3000
```

## Environment Setup (Done)
- Python 3.13 venv at `.venv/`
- Twelve Data API key in `engine/.env`
- Vertex AI configured: project=gcia-dev-app-wsky, region=us-east5
- gcloud auth is active

## What Needs To Be Done Next

### Priority 1: Improve Signal Quality
1. **More strategies** — Camarilla Pivots, Break & Retest, London/NY Breakout (15 remaining from research)
2. **Tune backtester thresholds** — Max drawdown was 13.3%, needs to be < 10% for prop firm
3. **Strategy-specific parameters per instrument** — Gold EMA settings != BTC EMA settings

### Priority 2: Make It Useful Daily
4. **Alerts (Telegram/Discord)** — Notify when high-confluence setup fires
5. **Economic calendar** — News detection + 5-min blackout enforcement
6. **Learning engine Phase 1** — Analyze journal, find best strategy per instrument/session/regime

### Priority 3: Go Live
7. **Real broker connection** — For actual paper trading with real fills
8. **MT5 integration** — Connect to FundingPips
9. **Walk-forward optimizer** — Auto-tune parameters weekly

## Key Files
| File | Purpose |
|------|---------|
| `CLAUDE.md` | Project overview, rules, tech stack |
| `docs/research/TRADING-SYSTEM-RESEARCH.md` | Full research (architecture, learning engine) |
| `docs/research/STRATEGIES-DETAILED.md` | 23+ strategies with exact rules |
| `docs/plans/CRITICAL-FIXES.md` | 10 critical issues (ALL FIXED) |
| `docs/context/SESSION-CONTEXT.md` | THIS FILE |
| `engine/src/data/instruments.py` | Instrument specs (pip values, contract sizes, spreads) |
| `engine/src/backtester/engine.py` | Walk-forward backtester |
| `dashboard/lib/strategy-info.ts` | Strategy descriptions for UI tooltips |

## Technical Notes
- Python 3.13 via /opt/homebrew/bin/python3.13 (3.14 incompatible with numba)
- FastAPI route order: specific before parameterized
- Lightweight Charts v5: chart.addSeries(CandlestickSeries, opts)
- Twelve Data: XAU/USD format for metals, free tier 800 calls/day
- CCXT: Binance BTC/USDT and ETH/USDT, no API key needed for public data
- Vertex AI: uses gcloud auth, project gcia-dev-app-wsky
- Git remote uses github-kapilll SSH alias (not default github.com)

## User Preferences
- Day trading: 1m/5m/15m/30m/1h entries, 4h/1d context
- Uses external charting (TradingView/GoCharting), not our charts
- Wants to understand all code (educational comments)
- Co-pilot mode: system suggests, user confirms
- Dashboard with info tooltips for learning
- Based in India (Oanda not available, using Twelve Data + CCXT)
