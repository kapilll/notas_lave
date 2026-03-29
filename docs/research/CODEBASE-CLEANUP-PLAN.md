# Codebase Utilization & Integration Plan

> Created: 2026-03-29 | Base version: v1.7.9 | Commit: da812b7
> Updated: 2026-03-29 | Verified at: v1.7.13 | Commit: e05cc7f
> Policy: **Keep everything. Wire in what's useful. Document what's waiting.**
>
> **v1.7.13 delta:** Phases 1-5 complete. Backtester arena mode, trade grader, learning API endpoints,
> Claude review scheduler, alert scanner DI wiring, and composite strategy optimizer grids all wired in.
> System docs updated to v1.7.13. Stale research docs removed.

---

## Model Guide

**You must manually set the model at the start of each session: `/model <name>` then `/effort <level>`.**
Claude Code cannot auto-switch models. Follow the table below for each phase.

| Phase | Model | Effort | `/model` + `/effort` command |
|-------|-------|--------|------------------------------|
| **Phase 1** (Backtester Arena) | **Opus** | medium | `/model opus` → `/effort medium` |
| **Phase 2** (Trade Grader) | **Sonnet** | high | `/model sonnet` → `/effort high` |
| **Phase 3** (Learning API) | **Sonnet** | high | `/model sonnet` → `/effort high` |
| **Phase 4** (Claude Review + Alerts) | **Sonnet** | high | `/model sonnet` → `/effort high` |
| **Phase 5** (Optimizer + A/B) | **Sonnet** | high | `/model sonnet` → `/effort high` |
| **Phase 6** (Fix Stale Docs) | **Sonnet** | medium | `/model sonnet` → `/effort medium` |
| **Phase 7** (SQLite WAL + Cleanup) | **Haiku** | high | `/model haiku` → `/effort high` |
| **Phase 8** (Test Coverage) | **Sonnet** | high | `/model sonnet` → `/effort high` |

**Token tips:**
- Opus medium effort ≈ Sonnet high effort in quality, but cheaper on complex architectural work
- Haiku high effort is fine for mechanical edits — still very cheap
- `subagent_type: "humanlayer:codebase-locator"` for finding files (not Explore)
- `model: "haiku"` on subagents doing grep/glob only
- One PR per phase. Don't batch.
- Give Claude the exact file paths and line numbers from this plan — saves discovery tokens.

**REMINDER: Before starting each phase, run `/model` and `/effort` as shown above.**

---

## Module Inventory

Every module, its status, and its verdict.

### ACTIVE — Used in live trading loop

| Module | Lines | Used by | Status |
|--------|-------|---------|--------|
| `engine/lab.py` | 800+ | Core trading loop | ACTIVE |
| `engine/leaderboard.py` | 240 | Trust scores | ACTIVE |
| `strategies/*.py` (6 files) | ~1500 | Signal generation | ACTIVE |
| `risk/manager.py` | 400+ | Trade validation | ACTIVE |
| `execution/delta.py` | 420 | Live broker | ACTIVE |
| `execution/paper.py` | 200 | Test broker | ACTIVE |
| `data/instruments.py` | 570 | Instrument registry | ACTIVE |
| `data/market_data.py` | 800+ | Candle provider (CCXT/Binance for data) | ACTIVE |
| `journal/event_store.py` | 300+ | Append-only journal | ACTIVE |
| `journal/database.py` | 250+ | SQLAlchemy ORM | ACTIVE |
| `alerts/telegram.py` | 150 | Trade notifications | ACTIVE |
| `learning/analyzer.py` | 454 | Trade analysis (called by recommendations) | ACTIVE |
| `learning/recommendations.py` | 472 | Action suggestions (has auto-apply) | ACTIVE |

### USEFUL — Fully built, needs wiring

| Module | Lines | What it does | Verdict |
|--------|-------|-------------|---------|
| `backtester/engine.py` | 1000+ | Walk-forward backtesting | **WIRE IN** (Phase 1) |
| `backtester/monte_carlo.py` | 167 | Permutation robustness test | **WIRE IN** (Phase 1) |
| `learning/trade_grader.py` | 210 | Grade trades A-F + lessons | **WIRE IN** (Phase 2) |
| `learning/accuracy.py` | 359 | Prediction accuracy tracking | **WIRE IN** (Phase 3) |
| `learning/progress.py` | 233 | Learning state aggregator | **WIRE IN** (Phase 3) |
| `learning/claude_review.py` | 290 | Weekly Claude review via Telegram | **WIRE IN** (Phase 4) |
| `alerts/scanner.py` | 194 | Background Telegram alerts | **WIRE IN** (Phase 4) |
| `monitoring/token_tracker.py` | 215 | Claude API cost tracking | **WIRE IN** (Phase 4) |

### WAITING — Future broker/ML work

| Module | Lines | What it does | Verdict |
|--------|-------|-------------|---------|
| `execution/coindcx.py` | 203 | CoinDCX broker (India) | **KEEP** — activate when ready |
| `execution/mt5.py` | 166 | MT5 broker (FundingPips) | **KEEP** — activate when ready |
| `learning/optimizer.py` | 386 | Walk-forward parameter tuning | **KEEP** — needs composite strategy param grids (Phase 5) |
| `learning/ab_testing.py` | 247 | Shadow-mode A/B testing | **KEEP** — wire after optimizer works |
| `ml/features.py` | 177 | ML feature extraction | **KEEP** — future ML pipeline |
| `claude_engine/decision.py` | 323 | Claude trade gating | **KEEP** — expensive but useful for high-conviction mode |

### DEMOTED — Still used, role changed

| Module | Lines | Old role | Current role | Verdict |
|--------|-------|----------|-------------|---------|
| `confluence/scorer.py` | 326 | Primary signal aggregation | `detect_regime()` used by lab; `compute_confluence()` used by scan endpoints + backtester | **KEEP as-is** — not redundant, serves different purpose than Arena |

**Confluence Scorer vs Arena — they're complementary, not competing:**
- Arena asks: "Which single strategy has the best setup right now?"
- Confluence asks: "What do all strategies collectively agree on?"
- `detect_regime()` classifies market conditions — Arena could use this for regime-aware filtering
- `compute_confluence()` powers `/api/scan/all` for manual analysis — still valuable
- Backtester currently depends on it — removing it breaks backtesting

---

## Phase 1: Backtester Arena Mode + Trust Seeding

> **Set model first:** `/model opus` → `/effort medium`

**PR: `feat: backtester arena mode + trust score seeding`**
**Priority: HIGH — this is what you've been wanting**

The backtester has two modes: confluence (old) and individual strategy. Neither matches how Arena v3 actually trades. Need a third mode.

### What to build

**1. Arena mode in `backtester/engine.py`**

Add parameter `arena_mode: bool = False` to constructor. When True:

```
For each candle window:
  Run all 6 composite strategies independently
  Each returns Signal with score
  Compute arena_score = 40% signal + 25% R:R + 20% trust + 15% WR
  Highest arena_score wins (same as live lab.py:304-311)
  Execute winner, track which strategy proposed it
  On close: update leaderboard (win +3, loss -5)
```

Key files to read:
- `backtester/engine.py:605-677` — existing two modes (add third)
- `engine/lab.py:299-311` — arena_score formula to replicate
- `engine/leaderboard.py:154-208` — record_win/record_loss to call

**2. Per-strategy stats in BacktestResult**

Currently `strategy_stats` (line 885-900) only has wins/losses/pnl/win_rate.
Add: `profit_factor`, `expectancy`, `avg_win`, `avg_loss`, `max_drawdown_pct`.

**3. Trust score seeding in `leaderboard.py`**

New method `seed_from_backtest(backtest_result)`:
```python
trust = win_rate  # base 0-100
if profit_factor > 2.0: trust += 10
elif profit_factor > 1.5: trust += 5
if total_trades >= 50: trust += 5
if net_pnl < 0: trust -= 20
# Clamp 0-100, save
```

**4. API route `POST /api/backtest/arena/{symbol}`**

New file `api/backtest_routes.py`:
- `POST /api/backtest/arena/{symbol}` — run arena backtest, optionally seed trust
- `POST /api/backtest/walk-forward/{symbol}` — N-fold walk-forward validation
- `GET /api/backtest/leaderboard` — show seeded vs default trust scores

**5. Monte Carlo validation**

Before seeding trust, run `monte_carlo.run_monte_carlo(result.trades)`.
Only seed if `is_robust=True` AND `edge_significant=True`.

### What to clear

The `INSTRUMENT_STRATEGY_BLACKLIST` in `backtester/engine.py:57-91` references old strategy names (`break_retest`, `fibonacci_golden_zone`, etc.). These don't apply to composites. Clear and re-derive from arena backtests.

### Prompt for Sonnet

```
Read backtester/engine.py, engine/lab.py:299-336, engine/leaderboard.py.

Add arena_mode=True parameter to Backtester. When enabled:
1. Run all 6 strategies via get_all_strategies() on each window
2. Compute arena_score matching lab.py:304-311 formula
3. Select highest arena_score as winner
4. Track strategy_name per trade in BacktestTrade
5. On trade close, call leaderboard.record_win/loss

Add seed_from_backtest() to StrategyLeaderboard.
Add POST /api/backtest/arena/{symbol} route.
Run monte_carlo before seeding — only seed if robust.
Clear INSTRUMENT_STRATEGY_BLACKLIST (old strategy names).
```

---

## Phase 2: Wire In Trade Grader

> **Set model first:** `/model sonnet` → `/effort high`

**PR: `feat: auto-grade closed trades with lessons`**
**Priority: HIGH — low-hanging fruit, 210 lines already working**

### Current state

Lab engine at `lab.py:769-772` does a **simple hardcoded grade** (A/B/C/D based on P&L sign).
`trade_grader.py` has a **proper grader**: R-multiple based A-F grading + pattern-based lesson generation (exit quality, MFE/MAE analysis, regime fit, duration insights).
DB columns `TradeLog.outcome_grade` and `TradeLog.lessons_learned` already exist but are barely populated.

### What to do

1. Replace the simple grade at `lab.py:769-772` with `grade_and_learn()` from `trade_grader.py`
2. Store grade + lesson in `TradeLog` (columns exist)
3. Expose grades in `/api/lab/arena/{strategy_name}` response
4. Add test: closed trade gets proper grade

### Prompt for Sonnet

```
Read learning/trade_grader.py and engine/lab.py (search for outcome_grade).
Replace the hardcoded grade logic with trade_grader.grade_and_learn().
Store both grade and lesson in the TradeLog. Write a unit test.
```

---

## Phase 3: Wire In Learning API Endpoints

> **Set model first:** `/model sonnet` → `/effort high`

**PR: `feat: expose learning engine via API`**
**Priority: MEDIUM — all the plumbing exists, just needs routes**

### Current state

`api/learning_routes.py` has 3 stub endpoints returning basic journal queries.
7 learning modules are fully implemented but have zero API exposure.

### What to add to `learning_routes.py`

| Endpoint | Calls | What it returns |
|----------|-------|-----------------|
| `GET /api/learning/analysis` | `analyzer.run_full_analysis()` | Strategy × instrument matrix, regime analysis, hourly breakdown |
| `GET /api/learning/recommendations` | `recommendations.generate_all_recommendations()` | Blacklist suggestions, weight adjustments, score thresholds |
| `POST /api/learning/apply` | `recommendations.apply_safe_recommendations()` | Apply recommendations (gated by cooldown: 7 days + 10 trades) |
| `GET /api/learning/accuracy` | `accuracy.get_accuracy_report()` | Direction/target accuracy per strategy (empty until Phase 3b) |
| `GET /api/learning/state` | `progress.get_learning_state()` | One-stop aggregation of all learning data |

### Phase 3b: Wire prediction logging

For `accuracy.py` to have data, add `log_prediction()` call when a proposal is accepted in `lab.py` (~line 497, after risk validation passes). Also add `resolve_pending_predictions()` call in the tick loop to check outcomes.

### Prompt for Sonnet

```
Read api/learning_routes.py (current stubs) and all learning/*.py files.
Add 5 new endpoints to learning_routes.py:
  GET /api/learning/analysis → run_full_analysis()
  GET /api/learning/recommendations → generate_all_recommendations()
  POST /api/learning/apply → apply_safe_recommendations()
  GET /api/learning/accuracy → accuracy report
  GET /api/learning/state → get_learning_state()

Then add log_prediction() call in lab.py after a trade is accepted.
Add resolve_pending_predictions() call in the tick loop.
```

---

## Phase 4: Wire In Claude Review + Alert Scanner

> **Set model first:** `/model sonnet` → `/effort high`

**PR: `feat: weekly Claude review + background alerts`**
**Priority: MEDIUM**

### Claude Weekly Review

`claude_review.py` generates a weekly Telegram report using Claude API.
Cost: ~$2-5/month (4 API calls). Has fallback to non-AI report if no API key.

**Wire in:**
1. Add `POST /api/learning/review` endpoint → calls `generate_review()`
2. Schedule weekly via APScheduler (scheduler already exists at `engine/scheduler.py`)
3. Config needed: `ANTHROPIC_API_KEY` env var (falls back to text-only report without it)
4. `token_tracker.py` already tracks costs — gets called automatically by `claude_review.py`

### Alert Scanner

`alerts/scanner.py` is a background scanner sending Telegram alerts for high-confluence setups. Uses `compute_confluence()` from scorer.py.

**Wire in:**
1. Instantiate `AlertScanner` in DI Container
2. Start on app startup, stop on shutdown
3. Gate behind `ALERT_SCANNER_ENABLED=false` env var (default off)

### Prompt for Sonnet

```
Wire claude_review.py: add POST /api/learning/review endpoint,
schedule weekly via engine/scheduler.py. Needs ANTHROPIC_API_KEY env var.

Wire alerts/scanner.py: add to DI Container, start/stop with app lifecycle.
Gate behind ALERT_SCANNER_ENABLED env var (default false).
```

---

## Phase 5: Optimizer + A/B Testing for Composite Strategies

> **Set model first:** `/model sonnet` → `/effort high`

**PR: `feat: optimizer parameter grids for Arena v3 strategies`**
**Priority: LOW — waiting for backtester (Phase 1) to work first**

### Current state

`optimizer.py` has `PARAMETER_GRID` for 5 old single-indicator strategies.
The 6 composite strategies have zero tunable parameters defined.
Optimizer uses backtester internally — needs Phase 1 arena mode first.

### What to do

1. Add parameter grids for 6 composites in `PARAMETER_GRID`:
   - `trend_momentum`: ema_fast, ema_medium, rsi_period, stoch_k
   - `mean_reversion`: bb_period, bb_std, rsi_period
   - `level_confluence`: fib_min_swing_pct, vwap_proximity_pct
   - `breakout_system`: sr_lookback, compression_threshold, volume_mult
   - `williams_system`: wr_period, wr_oversold, wr_overbought
   - `order_flow_system`: minimal (microstructure constants, not indicator periods)

2. Add composite strategy constructors to optimizer's constructor mapping

3. Add `POST /api/learning/optimize/{symbol}` API route

4. After optimizer works: wire `ab_testing.py` for shadow-mode parameter comparison
   - Run both current and candidate params on each signal
   - Trade only current, log both outcomes
   - Statistical significance test (two-proportion z-test) decides winner

### Prompt for Sonnet

```
Read learning/optimizer.py:49-85 (PARAMETER_GRID) and strategies/*.py.
Add parameter grids for the 6 composite strategies.
Update constructor mapping at optimizer.py:136-162.
Add POST /api/learning/optimize/{symbol} route.
This depends on backtester arena mode (Phase 1) being done first.
```

---

## Phase 6: Fix Stale Docs

> **Set model first:** `/model sonnet` → `/effort medium`

**PR: `docs: update system docs to v1.7.13`**
**Priority: MEDIUM**

9 of 12 system docs were stuck at v1.1.0. All updated as part of this phase.

| File | What's wrong |
|------|-------------|
| `ARCHITECTURE.md` | Says "12 strategies", should be 6 composites. Missing Arena description. |
| `DATA-PIPELINE.md` | v1.1.0 header. Binance is data source, not removed. |
| `DATABASE.md` | v1.1.0 header. ML-02 bridge is fixed. |
| `EXECUTION.md` | v1.1.0 header. Now 11 testnet symbols. |
| `RISK.md` | v1.1.0 header. Verify rules match code. |
| `LEARNING.md` | Says "learns from NOTHING" — WRONG, ML-02 bridge fixed in v1.1.0. |
| `TESTING.md` | Says "247 tests, 36% coverage" — check actual count at time of update. |
| `CI-CD.md` | v1.1.0 header. |
| `INFRASTRUCTURE.md` | v1.1.0 header. |

**Also clarify in docs:** "Binance removed in v1.0.0" means the **broker adapter** was removed. Binance is still used as a **data source** via CCXT for candles — 32 references in market_data.py and historical_downloader.py.

### Prompt for Sonnet

```
For each file in docs/system/ with "Last verified: v1.1.0":
1. Read the doc
2. Read the source code it describes
3. Fix factual errors (strategy count, test count, symbol count, etc.)
4. Update "Last verified" to v1.7.13
5. Do NOT rewrite sections that are still accurate
```

---

## Phase 7: Infrastructure Fixes

> **Set model first:** `/model haiku` → `/effort high`

**PR: `fix: SQLite WAL + dead import cleanup`**
**Priority: LOW**

### SQLite WAL Mode

Trading loop writes while API reads. WAL mode allows concurrent access.

1. `journal/event_store.py` — add `PRAGMA journal_mode=WAL` after connection
2. `journal/database.py` — add to engine creation

### Dead import in lab.py

`lab.py:239` imports `detect_regime` from `confluence/scorer.py` but **never calls it**.
Either remove the import or use it (regime-aware risk sizing is a future option).

### Prompt for Haiku

```
Add PRAGMA journal_mode=WAL to event_store.py and database.py SQLite connections.
Remove unused import of detect_regime from lab.py:239 (imported but never called).
```

---

## Phase 8: Test Coverage (50% → 60%)

> **Set model first:** `/model sonnet` → `/effort high`

**PR: `test: coverage push toward 60%`**
**Priority: ONGOING**

Current: 536 tests, 50% coverage. Target: 70% by Q3 2026.

Priority files: `lab.py`, `delta.py`, `risk/manager.py`, `market_data.py`, `strategies/*.py`.
Focus on error paths and edge cases, not happy paths.

**Do NOT use Haiku for test writing** — generates shallow tests.

---

## Execution Order

```
Phase 1 (backtester arena mode) ← highest value, enables trust seeding
  ↓
Phase 2 (trade grader) ← low effort, high value
  ↓
Phase 3 (learning API endpoints) ← unlocks dashboard integration
  ↓
Phase 4 (Claude review + alert scanner) ← nice-to-have automation
  ↓
Phase 5 (optimizer for composites) ← depends on Phase 1
  ↓
Phase 6 (fix stale docs) ← can be done anytime
  ↓
Phase 7 (SQLite WAL + cleanup) ← quick win, do anytime
  ↓
Phase 8 (test coverage) ← ongoing
```

---

## What This Plan Does NOT Cover

- **CoinDCX/MT5 broker implementation** — stubs exist, separate project per broker
- **PostgreSQL migration** — SQLite fine for current scale, revisit with WAL issues
- **LikeC4 architecture diagrams** — `architecture/model.c4` needs v1.7.x update
- **ML pipeline** — `ml/features.py` waits until there's training data from accuracy tracking (Phase 3)
- **Claude trade gating** — `claude_engine/decision.py` is expensive ($50-100/mo). Keep for future "high-conviction mode" where Claude validates before large trades
