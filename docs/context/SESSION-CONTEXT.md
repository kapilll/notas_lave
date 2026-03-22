# Session Context - Notas Lave Trading System

**Last Updated:** 2026-03-22 (Session 9 complete)
**Git Branch:** main (commit directly)

---

## What Is This Project?
AI-powered autonomous trading system with TWO engines:
- **Lab Engine:** Trades on **Binance Demo exchange** (real fills, not paper trading)
- **Production Engine:** Trades carefully with proven strategies (strict risk, real money ready)

## How to Run
```bash
cd engine && ../.venv/bin/python run.py    # Both engines start together
cd dashboard && npm run dev                # 4-tab dashboard
# Open: http://localhost:3000
```

## Current State
- **Lab trades on Binance Demo** — real exchange fills, local SL/TP monitoring, exchange market close
- **18 instruments:** BTC, ETH, SOL, XRP, BNB, DOGE, ADA, AVAX, LINK, DOT, LTC, NEAR, SUI, ARB, PEPE, WIF, FTM, ATOM
- **12 strategies** with volume + ATR upgrades (removed Order Blocks + Session Kill Zone)
- **Lab scans:** 15m, 1h, 4h — one position per symbol max
- **47 tests passing**, structured logging, 4-tab dashboard
- **All dashboard data reads from database** — survives restarts (live feed, P&L, win rate)
- **Data verification endpoint:** `GET /api/lab/verify` compares everything against Binance
- **Balance syncs from Binance** every 5 min (exchange is source of truth)
- **Binance Demo balance:** ~$4,664 USDT (started at $5,000)

## Session 9 Accomplishments
1. **10-panel expert review** (Mode A fresh review + Mode B reconciliation)
2. **28 issues fixed** across 6 parallel lanes (2 P0, 2 regressions, 8 P1, 14 P2, 5 P3)
3. **Lab wired to Binance Demo** — no more paper trading, real exchange execution
4. **Phantom profit bug found and fixed** — P&L was using candle data, not exchange fills
5. **ADA rapid-cycling fixed** — spread-to-SL check prevents fee-burning loops
6. **Data persistence** — all dashboard data reads from SQLite, survives restarts
7. **Verification endpoint** — on-demand data integrity check against Binance
8. **SIGTERM handler** — graceful shutdown saves state
9. **Singleton contamination fixed** — Lab no longer corrupts Production risk_manager
10. **Database race condition fixed** — contextvars for async-safe DB switching

## Lab Engine Architecture (Hybrid Exchange)
```
Signal fires → MARKET order on Binance Demo (real fill price)
            → Position tracked locally (paper_trader) with SL/TP levels
            → Every tick: paper_trader monitors 1-min candle high/low vs SL/TP
            → SL/TP hit → MARKET close on Binance Demo (real exit fill)
            → P&L calculated from real entry + real exit fills
            → Journal updated with exchange prices (not candle estimates)
```

Note: Binance Demo disabled STOP_MARKET orders (-4120). SL/TP is managed locally.
When the engine is stopped, exchange positions have NO stop loss protection.

## Lab Engine Settings
| Setting | Value |
|---------|-------|
| Execution | Binance Demo (real fills) |
| Instruments | 18 crypto |
| Timeframes | 15m, 1h, 4h |
| Min score | 3.0 | Min R:R | 1.0 |
| Max trades/day | 30 | Max concurrent | 5 |
| Cooldown | 60s between trades |
| Volume check | DISABLED (Lab mode) |
| Spread filter | Skip if spread > 20% of SL distance |
| Position limit | 1 per symbol (no stacking) |
| Individual strategy trading | YES (each strategy trades solo) |
| Auto-backtest | Every 6h | Auto-optimize | Every 12h |

## Key API Endpoints
| Endpoint | Purpose |
|----------|---------|
| `GET /api/lab/verify` | Compare all data against Binance Demo |
| `POST /api/lab/sync-balance` | Force-reset balance from Binance |
| `GET /api/lab/trades` | Closed trades (from DB, survives restart) |
| `GET /api/lab/status` | Full lab status with DB-backed stats |
| `GET /health` | Engine health check with uptime |

## Dashboard — 4 Tabs
| Tab | Theme | Shows |
|-----|-------|-------|
| LAB | Purple | Strategy leaderboard, live trades, open positions, markets |
| STRATEGIES | Amber | Per-strategy cards with WR, best TF, best regime, expandable details |
| COMMAND | Blue | Production signals, AI evaluation, tools |
| EVOLUTION | Green | Accuracy, Claude reports, token costs, diamonds |

## Persistent Storage
| Data | Location | Survives restart? |
|------|----------|-------------------|
| Lab trades (open + closed) | `engine/notas_lave_lab.db` | Yes |
| Production trades | `engine/notas_lave.db` | Yes |
| Lab risk state | `engine/data/lab_risk_state.json` | Yes |
| Check-in reports | `engine/data/lab_checkin_reports.json` | Yes |
| Logs | `engine/data/notas_lave.log` (rotating, 10MB x 5) | Yes |
| Dashboard live feed | Reads from lab.db | Yes |
| Win rate / Total P&L | Reads from lab.db | Yes |

## Known Limitations
- **No exchange SL/TP:** Binance Demo rejected STOP_MARKET orders. SL/TP managed locally.
  When engine is stopped, positions on Binance have no stop loss protection.
- **Entry price gap:** Binance Demo returns avgPrice=0 for market orders. System queries
  fill price separately, falls back to candle close if unavailable (~$0.06-$0.95 gap).
- **Fees not in instrument specs:** BTCUSD/ETHUSD etc have taker_fee=0% but Binance
  charges ~0.04%. P&L is overstated by fees. Fix: add Binance fee schedule to USD instruments.

## What To Do Next
1. Let Lab run for 24-48h to accumulate real exchange trade data
2. After 50+ trades: review strategy performance, identify winners
3. Add SMC strategy suite (FVG, Liquidity, Volume Profile, Order Blocks, Market Structure)
4. After 500+ trades: train XGBoost on features (Phase 2)
5. When lab finds "diamond" (>60% WR, 50+ trades): promote to production
