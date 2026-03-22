# Session Context - Notas Lave Trading System

**Last Updated:** 2026-03-22 (Session 8 complete)
**Git Branch:** main (commit directly)

---

## What Is This Project?
AI-powered autonomous trading system with TWO engines:
- **Lab Engine:** Trades aggressively to LEARN (no risk limits, 10 crypto instruments, 15m/1h/4h)
- **Production Engine:** Trades carefully with proven strategies (strict risk, real money ready)

## How to Run
```bash
cd engine && ../.venv/bin/python run.py    # Both engines start together
cd dashboard && npm run dev                # 4-tab dashboard
# Open: http://localhost:3000
```

## Current State
- **Dual Engine** running — Lab + Production in one process
- **10 instruments:** BTC, ETH, SOL, XRP, BNB, DOGE, ADA, AVAX, LINK, DOT
- **12 strategies** with volume + ATR upgrades (removed Order Blocks + Session Kill Zone)
- **Lab scans:** 15m, 1h, 4h (dropped 5m — too noisy, backtests proved it)
- **Lab volume checks DISABLED** — weekend/quiet markets kill all signals at any threshold
- **47 tests passing**, structured logging, 4-tab dashboard
- **Key finding:** Strategies don't fire in ranging weekend markets — this is CORRECT behavior, not a bug

## Known Issue: Low Signal Generation
- Strategies are designed for trending/volatile conditions
- Weekend crypto markets are quiet (RSI 38-67, no divergences, no breakouts)
- Volume is 0.28x average on weekends — even 0.8x threshold blocks everything
- Lab disables volume checks to maximize signal generation
- Need weekday active market hours to see real signals

## Lab Engine Settings
| Setting | Value |
|---------|-------|
| Instruments | 10 crypto (BTC, ETH, SOL, XRP, BNB, DOGE, ADA, AVAX, LINK, DOT) |
| Timeframes | 15m, 1h, 4h |
| Min score | 3.0 | Min R:R | 1.0 |
| Max trades/day | 100 | Max concurrent | 10 |
| Volume check | DISABLED (Lab mode) |
| Individual strategy trading | YES (each strategy trades solo) |
| Auto-backtest | Every 6h | Auto-optimize | Every 12h |

## Dashboard — 4 Tabs
| Tab | Theme | Shows |
|-----|-------|-------|
| LAB | Purple | Strategy leaderboard, live trades, open positions, markets |
| STRATEGIES | Amber | Per-strategy cards with WR, best TF, best regime, expandable details |
| COMMAND | Blue | Production signals, AI evaluation, tools |
| EVOLUTION | Green | Accuracy, Claude reports, token costs, diamonds |

## Persistent Storage
| Data | Location |
|------|----------|
| Lab trades | `notas_lave_lab.db` |
| Production trades | `notas_lave.db` |
| Lab risk state | `data/lab_risk_state.json` |
| Check-in reports | `data/lab_checkin_reports.json` |
| Logs | `data/notas_lave.log` (rotating) |

## What To Do Next
1. Let Lab run during weekday active hours — signals should fire then
2. After 50+ lab trades: review strategy performance on Strategies tab
3. After 500+ trades: train XGBoost on features (Phase 2)
4. When lab finds "diamond" (>60% WR, 50+ trades): promote to production
