# Session Context - Notas Lave Trading System

**Last Updated:** 2026-03-23 (Session 10 complete)
**Git Branch:** main (commit directly)

---

## What Is This Project?
AI-powered autonomous trading system with TWO engines:
- **Lab Engine:** Trades on **Binance Demo exchange** (real fills, not paper trading)
- **Production Engine:** Trades carefully with proven strategies (strict risk, real money ready)

## How to Run
```bash
cd engine && ../.venv/bin/python run.py    # Both engines start together
cd dashboard && npm run dev                # 4-tab dashboard + health bar
# Open: http://localhost:3000
```

## Current State
- **Lab trades on Binance Demo** — real exchange fills, local SL/TP monitoring, exchange market close
- **18 instruments:** BTC, ETH, SOL, XRP, BNB, DOGE, ADA, AVAX, LINK, DOT, LTC, NEAR, SUI, ARB, PEPE, WIF, FTM, ATOM
- **12 strategies** with volume + ATR upgrades (removed Order Blocks + Session Kill Zone)
- **Lab scans:** 15m, 1h, 4h — one position per symbol max
- **All dashboard data reads from database** — survives restarts
- **Verification endpoint:** `GET /api/lab/verify` compares everything against Binance
- **Balance syncs from Binance** every 5 min (exchange is source of truth)
- **Heartbeats every 1 hour** (reduced from 6h in Session 10)

## Session 10 — Major Infrastructure Overhaul (2026-03-23)

Used BUILD-WITH-EXPERTS.md 5-expert panel to audit 9 user concerns.
Created 27 issues across 6 categories. ALL 27 resolved in 4 commits (~2,029 lines).

### Tier 1 (`ccdd5d5`): DB Safety + Alerting
- `use_db("default")` on 3 production journal endpoints + paper_trader reload
- New `POST /api/lab/close/{id}` — lab-specific close (was hitting production)
- Frontend: close button routes by tab, leaderboard uses lab data
- `send_error_alert()` with 5-min cooldown — lab startup, Claude API, review failures
- `_validate_claude_response()` — grade/lesson/regime validation before storing
- Heartbeat 6h → 1h
- New `GET /api/learning/state` — full system memory endpoint
- New `learning/progress.py` — aggregates 9 data sections

### Tier 2 (`d8a71a0`): Learning Infrastructure
- **Trade-count triggers:** 25→stats push, 50→recs+auto-apply, 100→Claude review
- `format_recommendations_telegram()` + `apply_safe_recommendations()`
- 15 silent `except: pass` blocks fixed across 8 files
- **Optimizer feedback loop FIXED** — registry reads `optimizer_results.json` per-symbol

### Tier 3 (`b09a4d4`): Intelligence + Observability
- `analyze_strategy_combinations()` + `GET /api/learning/combinations`
- Loss streak diagnosis — 3 consecutive losses → pattern analysis + Telegram
- `journal/schemas.py` — 8 Pydantic models for all JSON files
- `GET /api/system/health` + expandable HealthBar component in dashboard

### Tier 4 (`4f335cc`): Polish + Completeness
- All 6 JSON files wired to Pydantic validation (safe_load/safe_save)
- DB column audit: 10 dead columns flagged, PerformanceSnapshot table unused
- WAL management: `checkpoint_wal()`, `backup_database()`, `run_db_maintenance()`
- Strategy rehabilitation: shadow signal tracking for blacklisted strategies
- Exploration budget: 24h dormant strategies get relaxed R:R, tagged LAB_EXPLORE
- Data freshness: alerts if candles stale > 2x timeframe interval
- API endpoints documented in CLAUDE.md

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

## Learning System (Session 10 Upgrade)
```
Trade closes → Counter increments
            → At 25: mini stats via Telegram + persist state
            → At 50: recommendations push + auto-apply (blacklists, weights)
            → At 100: full Claude review (was weekly, now data-driven)

Each trade also:
  → Claude grades A-F (validated before storing)
  → Loss streak tracked per symbol (3 losses → diagnosis + alert)
  → Strategy combination WR tracked for synergy analysis

Background (continuous):
  → Shadow signals from blacklisted strategies (rehabilitation)
  → Exploration trades for dormant strategies (24h+ idle)
  → Data freshness monitoring (stale candles → alert)
  → Optimizer results applied per-symbol when strategies created
```

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
| Heartbeat | Every 1h (Telegram) |
| Learning triggers | 25/50/100 trades |

## Key API Endpoints
| Endpoint | Purpose |
|----------|---------|
| `GET /api/learning/state` | **START HERE** — complete system memory |
| `GET /api/system/health` | Component status, background tasks, data health |
| `GET /api/learning/combinations` | Strategy combination performance |
| `GET /api/learning/recommendations` | Actionable recommendations |
| `GET /api/lab/verify` | Compare all data against Binance Demo |
| `GET /api/lab/summary` | Lab performance summary |
| `GET /api/lab/strategies` | Per-strategy performance from lab |
| `GET /api/lab/trades` | Closed trades (from DB, survives restart) |
| `POST /api/lab/close/{id}` | Close a lab position (+ exchange) |
| `POST /api/lab/sync-balance` | Force-reset balance from Binance |
| `GET /health` | Engine health check with uptime |

## Dashboard — 4 Tabs + Health Bar
| Component | Theme | Shows |
|-----------|-------|-------|
| HEALTH BAR | Top bar | Component status dots, uptime, last heartbeat, task times (expandable) |
| LAB | Purple | Strategy leaderboard (lab data), live trades, open positions, 18 markets |
| STRATEGIES | Amber | Per-strategy cards with WR, best TF, best regime, expandable details |
| COMMAND | Blue | Production signals, AI evaluation, backtest/walk-forward/Monte Carlo tools |
| EVOLUTION | Green | Accuracy, Claude reports, token costs, diamonds (>60% WR strategies) |

## Persistent Storage
| Data | Location | Survives restart? |
|------|----------|-------------------|
| Lab trades (open + closed) | `engine/notas_lave_lab.db` | Yes |
| Production trades | `engine/notas_lave.db` | Yes |
| Lab risk state | `engine/data/lab_risk_state.json` (Pydantic validated) | Yes |
| Check-in reports | `engine/data/lab_checkin_reports.json` | Yes |
| System state | `engine/data/system_state.json` | Yes |
| Learned weights | `engine/data/learned_state.json` (Pydantic validated) | Yes |
| Blacklists | `engine/data/learned_blacklists.json` (Pydantic validated) | Yes |
| Optimizer results | `engine/data/optimizer_results.json` (Pydantic validated) | Yes |
| DB backups | `engine/data/backups/` (7-day retention) | Yes |
| Logs | `engine/data/notas_lave.log` (rotating, 10MB x 5) | Yes |

## Key Files Added in Session 10
| File | Purpose |
|------|---------|
| `engine/src/learning/progress.py` | `get_learning_state()` + `save_learning_state()` |
| `engine/src/journal/schemas.py` | 8 Pydantic models + `safe_load_json`/`safe_save_json` |

## Known Limitations
- **No exchange SL/TP:** Binance Demo rejected STOP_MARKET orders. SL/TP managed locally.
  When engine is stopped, positions on Binance have no stop loss protection.
- **Entry price gap:** Binance Demo returns avgPrice=0 for market orders. System queries
  fill price separately, falls back to candle close if unavailable (~$0.06-$0.95 gap).
- **Fees not in instrument specs:** USD instruments have taker_fee=0% but Binance
  charges ~0.04%. P&L is overstated by fees. Fix: add Binance fee schedule.
- **PerformanceSnapshot table unused:** Flagged in DB audit but not removed.
- **10 dead DB columns:** Flagged with AUDIT comments, not removed (would break schema).

## What To Do Next
1. Monitor Lab — verify trade-count triggers fire at 25/50/100 trades
2. Schedule `run_db_maintenance()` via cron or engine tick (WAL checkpoint + backup)
3. After 500+ lab trades: train XGBoost on features (Phase 2)
4. When lab finds "diamond" (>60% WR, 50+ trades): promote to production
5. Phase 3: Cloud deploy (Docker + free tier)
