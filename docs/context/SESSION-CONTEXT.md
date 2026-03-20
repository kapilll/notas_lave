# Session Context - Notas Lave Trading System

**PURPOSE:** Read this file at the start of every new Claude session to restore context.
**Last Updated:** 2026-03-20

---

## What Is This Project?
An AI-powered trading system that uses Claude as a decision engine for scalping Gold, Silver, BTC, and ETH. Target: pass FundingPips prop firm challenges and trade consistently on funded accounts.

## What Has Been Done

### Session 1 (2026-03-20)
- [x] Researched FundingPips platform (rules, pricing, instruments)
- [x] Researched Temple-Stuart accounting GitHub repo (convergence pipeline architecture)
- [x] Analyzed Temple-Stuart's multi-gate scoring system, dynamic weight system, outcome tracker
- [x] Researched 40+ trading strategies across 8 categories
- [x] Researched MT5 Python API, TradingView webhooks, Oanda/Alpaca APIs
- [x] Researched Claude trading bot projects (Open Prophet, Polymarket bot, Chudi.dev bot)
- [x] Created comprehensive research document: `docs/research/TRADING-SYSTEM-RESEARCH.md`
- [x] Created CLAUDE.md with project overview
- [x] Created this session context file
- [x] Researched adaptive learning systems (RL, HMM regime detection, meta-learning, walk-forward, CPCV)
- [x] Researched OpenProphet (Jake Nesler's Claude trading bot that beat market by 7%)
- [x] Researched 900+ Hours of Claude trading lessons
- [x] Updated research doc with learning engine architecture (Sections 9, 10)
- [x] Researched 23+ professional scalping/trading strategies with exact algorithmic rules
- [x] Created detailed strategy reference: `docs/research/STRATEGIES-DETAILED.md`
- [x] All research agents completed successfully
- [x] Project scaffolded (Python engine + Next.js dashboard)
- [x] Built 3 Tier 1 strategies: EMA Crossover, RSI Divergence, Bollinger Bands
- [x] Built Confluence Scorer with regime-based dynamic weights
- [x] Built Risk Manager with FundingPips rule enforcement
- [x] Built FastAPI server with endpoints: /scan, /prices, /risk/status, /candles
- [x] Built Next.js Stage 1 dashboard (market overview, signals, risk panel)
- [x] Tested full pipeline with live Gold data ($4,492, RANGING, RSI 26.9)
- [x] Python venv set up (.venv with Python 3.13)
- [x] All builds pass (Python + Next.js)
- [x] Added 4 more strategies: VWAP, Stochastic, Fibonacci Golden Zone, Session Kill Zone
- [x] Added ICT Order Blocks + Fair Value Gaps strategy (8 total strategies)
- [x] Built Claude Decision Engine (3-gate verification, structured JSON, fallback mode)
- [x] Built Trade Journal (SQLite: signal_logs, trade_logs, performance_snapshots)
- [x] Added candlestick charts (TradingView Lightweight Charts v5)
- [x] Built Paper Trading Executor (open/close positions, SL/TP monitoring, breakeven management)
- [x] Dashboard: AI Decision panel with "Evaluate Trade" + "Take Trade" buttons
- [x] Dashboard: Open Positions panel with live P&L and close buttons
- [x] Dashboard: Performance summary (win rate, W/L, total P&L)
- [x] Background position monitoring (checks prices every 10s, auto-closes on SL/TP)
- [ ] NOT YET: Any code written
- [ ] NOT YET: Strategy implementation
- [ ] NOT YET: Data connectors
- [ ] NOT YET: Paper trading setup

## What Needs To Be Done Next

### Immediate (Phase 1)
1. **Create project scaffold** — Python project structure with all modules
2. **Build data connectors** — Oanda (Gold/Silver) + Alpaca (BTC/ETH) + free data APIs
3. **Implement core strategies** — Start with ICT + Scalping indicators
4. **Build confluence scorer** — Multi-gate scoring with dynamic weights
5. **Build Claude decision engine** — Prompt templates for trade evaluation
6. **Build risk manager** — FundingPips rule enforcement
7. **Build trade logger** — SQLite database for every trade
8. **Paper trading** — Connect to Oanda/Alpaca paper accounts

### Later (Phase 2)
9. **Backtester** — Historical data testing
10. **Learning engine** — Strategy performance tracking, weight adjustment
11. **Dashboard** — Streamlit real-time monitoring
12. **MT5 integration** — For FundingPips live trading
13. **News engine** — Economic calendar + sentiment analysis
14. **Walk-forward optimizer** — Parameter tuning

## Key Architecture Decisions
1. **Deterministic math, AI for context** — All indicators/scoring is code; Claude evaluates confluence
2. **Multi-strategy approach** — No single strategy; confluence of 40+ signals
3. **Dynamic weights** — Strategy importance shifts with market regime (trending/ranging/volatile)
4. **Paper first** — Oanda + Alpaca paper trading before FundingPips
5. **Learn from every trade** — Full context snapshot logged, Claude reviews weekly
6. **Inspired by Temple-Stuart** — Convergence pipeline, outcome tracking, gate scoring

## Key Reference Files
| File | Purpose |
|------|---------|
| `CLAUDE.md` | Project overview, rules, tech stack |
| `docs/research/TRADING-SYSTEM-RESEARCH.md` | Full research (strategies, architecture, platforms) |
| `docs/context/SESSION-CONTEXT.md` | THIS FILE - session handoff |

## Important Links
- FundingPips: https://www.fundingpips.com/
- Temple-Stuart repo: https://github.com/Temple-Stuart/temple-stuart-accounting
- Reddit post: https://www.reddit.com/r/ClaudeAI/comments/1r35gpb/
- MT5 Python docs: https://www.mql5.com/en/docs/integration/python_metatrader5
- Oanda API: https://developer.oanda.com/
- Alpaca API: https://alpaca.markets/docs/

## User Notes
- Running macOS (Darwin) — MT5 needs Windows VPS for live trading
- Starting with paper trading (zero cost)
- FundingPips subscription to be purchased later
- Focus: Scalping, ICT, multi-strategy approach
- Goal: Build a tool that tracks, learns, and improves from every trade
