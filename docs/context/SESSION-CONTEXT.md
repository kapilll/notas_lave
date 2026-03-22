# Session Context - Notas Lave Trading System

**Last Updated:** 2026-03-22 (Session 8 — Dual Engine Architecture)
**Git Branch:** main (commit directly)

---

## What Is This Project?
AI-powered autonomous trading system with TWO engines:
- **Lab Engine:** Trades aggressively on Binance Demo to LEARN (no risk limits, all timeframes)
- **Production Engine:** Trades carefully with proven strategies (strict risk, real money ready)

Claude is the brain. Code is the body. Zero human in the trading loop.

## How to Run
```bash
# Terminal 1: Engine (BOTH Lab + Production start together)
cd engine && ../.venv/bin/python run.py

# Terminal 2: Dashboard (3-tab UI)
cd dashboard && npm run dev

# Open: http://localhost:3000 (Lab tab is default)
# API: http://127.0.0.1:8000/api/health
```

## Current State (Session 8)
- **Dual Engine Architecture** — Lab + Production in one process
- **Lab Engine LIVE** on Binance Demo: BTCUSDT/ETHUSDT, all timeframes (5m/15m/1h/4h)
- **12 strategies** (removed 2 catastrophic losers: Order Blocks, Session Kill Zone)
- **All strategies upgraded:** volume confirmation + ATR-based SL/TP
- **47 tests passing**, structured logging (0 print statements)
- **Dashboard:** 3 tabs (Lab/Command Center/Evolution), gradient theme
- **Key discovery:** Strategies LOSE on 5m but MAKE MONEY on 1h

## Lab Engine Settings
| Setting | Value |
|---------|-------|
| Min score | 3.0 (production: 5.0) |
| Min R:R | 1.0 (production: 2.0) |
| Max trades/day | 100 |
| Max concurrent | 5 |
| Cooldown | 60s |
| Blacklist | OFF |
| Timeframes | ALL (5m, 15m, 1h, 4h) |
| Auto-backtest | Every 6h |
| Auto-optimize | Every 12h |
| Claude review | Daily at 22:00 UTC |
| 15-min check-in | Saves feedback stats to JSON |
| Telegram | [LAB] prefix on all messages |

## What Runs Automatically
- Lab scans every 30s, takes every qualifying signal
- Backtester runs on 1h/4h every 6 hours
- Optimizer runs every 12 hours
- 15-min feedback check-in (scan stats, rejection reasons, per-TF performance)
- Hourly Telegram summary
- Daily Claude report with strategy leaderboard

## Persistent Storage
| Data | Location |
|------|----------|
| Lab trades | `notas_lave_lab.db` |
| Production trades | `notas_lave.db` |
| Lab risk state | `data/lab_risk_state.json` |
| Check-in reports | `data/lab_checkin_reports.json` |
| Learned weights | `data/learned_state.json` |
| Optimizer results | `data/optimizer_results.json` |
| Logs | `data/notas_lave.log` (rotating 10MB) |

## Environment (.env at engine/.env)
```
CLAUDE_PROVIDER=vertex, GOOGLE_CLOUD_PROJECT=gcia-dev-app-wsky
BROKER=binance_testnet, TRADING_MODE=personal
TWELVEDATA_API_KEY, BINANCE_TESTNET_KEY/SECRET, TELEGRAM_BOT_TOKEN/CHAT_ID
```

## Key Files
| File | Purpose |
|------|---------|
| `engine/run.py` | Production + Lab engine entry point |
| `engine/src/lab/lab_trader.py` | Lab autonomous trader (aggressive) |
| `engine/src/lab/lab_config.py` | Lab settings |
| `engine/src/lab/lab_risk.py` | Permissive risk manager |
| `engine/src/ml/features.py` | 25+ feature extraction per signal |
| `engine/src/agent/autonomous_trader.py` | Production trader |
| `engine/src/risk/manager.py` | Production risk gatekeeper |
| `dashboard/app/page.tsx` | 3-tab dashboard |
| `docs/plans/DUAL-ENGINE-ARCHITECTURE.md` | Architecture plan |

## What To Do Next
1. Watch Lab generate trades on Binance Demo
2. Check Telegram for [LAB] reports
3. After 500+ lab trades: train XGBoost on features (Phase 2)
4. Review Claude daily reports for strategy improvements
5. When lab finds a "diamond" (>60% WR over 50+ trades): promote to production
