# Notas Lave - AI Trading System

## Project Overview
Notas Lave is a Claude-powered trading decision engine for scalping Gold (XAUUSD), Silver (XAGUSD), Bitcoin (BTCUSD), and Ethereum (ETHUSD). Target platform: FundingPips (MT5/cTrader).

## Project Status
- **Phase:** Research & Planning (as of 2026-03-20)
- **Current Focus:** Architecture design, strategy research
- **Next Step:** Project scaffolding and Phase 1 build

## Key Files
- `docs/research/TRADING-SYSTEM-RESEARCH.md` — Full research document (architecture, platform, learning engine)
- `docs/research/STRATEGIES-DETAILED.md` — 23+ strategies with exact algorithmic rules & parameters
- `docs/context/SESSION-CONTEXT.md` — Session handoff context (READ THIS FIRST in new sessions)

## Architecture Summary
Multi-strategy confluence engine:
1. **Data Layer** — MT5 API / Oanda / Alpaca / Free APIs
2. **Strategy Engine** — 40+ strategies across 8 categories (ICT, Scalping, Fibonacci, Volume, Price Action, Order Flow, Advanced, News)
3. **Confluence Scorer** — Dynamic weights per market regime (inspired by Temple-Stuart's convergence pipeline)
4. **Claude Decision Engine** — Contextual trade evaluation
5. **Risk Manager** — FundingPips rule compliance (hard rules, never overridden)
6. **Execution Layer** — Paper trading first, then MT5 live
7. **Learning Engine** — Every trade logged, analyzed, weights adjusted

## FundingPips Rules (MUST ENFORCE)
- Max daily drawdown: 5%
- Max total drawdown: 10% (static)
- Consistency rule: No single day > 45% of total profits (funded accounts)
- News blackout: No trades 5 min before/after high-impact news (funded)
- No hedging, no HFT, no arbitrage
- Inactivity limit: 30 days

## Tech Stack
- **Frontend:** Next.js 15 (App Router, React Server Components, TailwindCSS)
  - Built in stages: Stage 1 = basic dashboard, Stage 2 = charts, Stage 3 = trade management
- **Backend/Engine:** Python 3.11+ (FastAPI for API, WebSocket for real-time)
- Core: anthropic, fastapi, pydantic
- Data: MetaTrader5 (Windows), oandapyV20, alpaca-trade-api, ccxt
- Analysis: pandas, numpy, pandas-ta, ta-lib, scipy, scikit-learn
- Storage: SQLite/PostgreSQL, Redis
- Communication: Python backend ↔ Next.js frontend via REST API + WebSocket

## Development Rules
- All math is deterministic code — Claude handles analysis/explanation only
- Every trade must pass Risk Manager before execution
- Backtest every strategy before paper trading
- Paper trade every strategy before live trading
- Log EVERYTHING for learning system
- Strategy weights adapt based on recent performance + market regime

## User Preferences
- Platform: macOS (Darwin) — MT5 needs Windows VPS
- Starting instruments: Gold, Silver, BTC, ETH
- Strategy focus: Scalping, ICT, multiple approaches
- Goal: Consistent profitability on prop firm
