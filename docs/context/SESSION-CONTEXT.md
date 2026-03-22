# Session Context - Notas Lave Trading System

**Last Updated:** 2026-03-22 (Session 8 complete)
**Git Branch:** main (commit directly)

---

## What Is This Project?
AI-powered autonomous trading system for BTC, ETH (personal mode) and Gold, Silver (prop mode).
Uses Claude via Vertex AI. System EVOLVES — every trade teaches, weights adapt, blacklists update.

## How to Run
```bash
cd engine && ../.venv/bin/python run.py    # Engine (Binance Demo)
cd dashboard && npm run dev                # Dashboard
# API: http://127.0.0.1:8000/api/health
```

## Current State
- **LIVE on Binance Demo** — auto-scanning BTCUSDT/ETHUSDT every 60s
- **47 unit tests**, 14 strategies, structured logging throughout
- **~130 issues fixed** across 8 sessions, ~13 deferred (Docker, CI, Alembic)
- **Mode:** Personal / Full Auto / Balance: ~5000 USDT
- No trades yet — waiting for qualifying signals (correct behavior)

## Key Capabilities
- **Risk:** validate_trade() gate, mode-aware (prop vs personal), unrealized P&L in drawdown
- **Learning:** Exponential decay weighting, weekly blacklist/weight adjustments, persisted state
- **Execution:** Retry + reconnect, exchange-side fill detection, tick size validation, slippage model
- **Backtester:** Walk-forward, session-adjusted spread, Sortino/Calmar, Monte Carlo with block bootstrap

## Environment (.env at engine/.env)
```
CLAUDE_PROVIDER=vertex, GOOGLE_CLOUD_PROJECT=gcia-dev-app-wsky
BROKER=binance_testnet, TRADING_MODE=personal
TWELVEDATA_API_KEY, BINANCE_TESTNET_KEY/SECRET, TELEGRAM_BOT_TOKEN/CHAT_ID
```

## Trading Roadmap
1. Paper trade on Binance Demo — IN PROGRESS
2. CoinDCX live (2000-3000 INR) — after 50+ paper trades validated
3. FundingPips challenge (~$60) — set TRADING_MODE=prop

## What To Do Next
1. Monitor for first auto-trade via Telegram
2. Run walk-forward: `curl http://127.0.0.1:8000/api/backtest/walk-forward/BTCUSD`
3. After 50+ trades: run expert review (`docs/reviews/REVIEW-PROMPT.md`)

## Key Files
| File | Purpose |
|------|---------|
| `engine/src/agent/autonomous_trader.py` | THE CORE: 24/7 autonomous loop |
| `engine/src/risk/manager.py` | Mode-aware risk gatekeeper |
| `engine/src/backtester/engine.py` | Backtester + walk-forward |
| `engine/src/confluence/scorer.py` | Dynamic weights + persistence |
| `docs/reviews/ISSUES.md` | Issue tracker (compact) |
| `docs/reviews/REVIEW-PROMPT.md` | 10-panel expert review prompt |

## Technical Notes
- Python 3.13 (.venv/), 127.0.0.1:8000, Vertex AI: `gcloud auth application-default login`
- Tests: `.venv/bin/python -m pytest engine/tests/ -x -q`
- Expert review: every 3-5 sessions via REVIEW-PROMPT.md
