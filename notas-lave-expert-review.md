# NOTAS LAVE — Expert Panel System Review
## All 5 Panels Researching 9 Critical Questions
### Date: 2026-03-23

---

## PANEL MEMBERS
- **The Strategist** (Quant + Market Structure) — "Would I bet my money on this?"
- **The Architect** (Systems + Code Quality) — "Can a sleep-deprived dev understand this at 3am?"
- **The Guardian** (Risk + Compliance + Security) — "How could this lose ALL the money?"
- **The Scientist** (AI/ML + Learning Systems) — "Is the system actually LEARNING?"
- **The Operator** (DevOps + Data + Reliability) — "What happens when this runs for 30 days unattended?"

---

# Q3. DATABASE SEPARATION (CRITICAL — Read First)

> "I have been having issues at many places regarding DB. The separation between lab and its endpoints and UI is not very separate from command."

## Findings

The system uses TWO SQLite databases: `notas_lave.db` (production) and `notas_lave_lab.db` (lab), switched via a `ContextVar`-based mechanism in `engine/src/journal/database.py`.

### CONFIRMED BUGS (Data Contamination Risk)

| Bug | File:Line | Impact |
|-----|-----------|--------|
| `/api/journal/signals` missing `use_db("default")` | `server.py:444` | Could return lab signals in production tab |
| `/api/journal/trades` missing `use_db("default")` | `server.py:450` | Could return lab trades in production tab |
| `/api/journal/performance` missing `use_db("default")` | `server.py:456` | Strategy leaderboard could show lab data |
| `paper_trader._reload_open_positions()` no `use_db()` | `paper_trader.py:690` | Works by accident (called before lab starts) |
| Lab tab "Close Position" calls production endpoint | `page.tsx:1159` | Closing lab positions closes PRODUCTION ones |
| Lab tab strategy leaderboard fetches from production DB | `page.tsx:1117` | Lab tab shows production strategy stats |

### THE CORE PROBLEM

**The Architect says:** The ContextVar switching mechanism is clever but fragile. Production endpoints ASSUME they're in the default context but never assert it. The pattern should be: **every endpoint explicitly declares which DB it reads from**. No implicit defaults.

**The Guardian says:** This is a **money-at-risk bug**. If a production endpoint accidentally reads lab data, it could make trading decisions based on lab trades (different risk parameters, different instruments). The "close position" mismatch in the UI is the most dangerous — user thinks they're closing a lab position but actually closes production.

### How Lab vs Production DB Switching Works

```
database.py:
  _active_db_key = ContextVar("_active_db_key", default="default")  # line 245

  use_db("lab")    → sets ContextVar to "lab"     → get_db() returns lab session
  use_db("default") → sets ContextVar to "default" → get_db() returns production session
  get_db()         → reads ContextVar, returns corresponding session
```

**Lab endpoints:** ALL correctly call `use_db("lab")` before DB access
**Production endpoints:** NONE call `use_db("default")` — they rely on the default

### Frontend-Backend DB Confusion Map

```
LAB TAB:
  /api/lab/risk          → Lab DB    (correct)
  /api/lab/positions     → Lab DB    (correct)
  /api/lab/trades        → Lab DB    (correct)
  /api/lab/strategies    → Lab DB    (correct)
  /api/lab/markets       → No DB     (correct)
  /api/journal/performance → PRODUCTION DB (WRONG — shows prod stats in lab tab)
  POST /api/trade/close  → PRODUCTION     (WRONG — closes prod position, not lab)

COMMAND TAB:
  /api/risk/status       → Production (correct)
  /api/trade/positions   → Production (correct)
  /api/evaluate/{sym}    → Production (correct)

EVOLUTION TAB:
  /api/learning/analysis → AUTO-SWITCHES to lab if lab running (confusing but intentional)
  /api/learning/review   → AUTO-SWITCHES to lab if lab running
  /api/journal/trades    → PRODUCTION (no switch — could be wrong context)
```

---

# Q2. ARE ALL FEATURES AND TOOLS WORKING?

> "Are all the features and tools that we build even working? We have claude reports that was not working?"

## Feature Audit Results

| Feature | Status | Called From | Feedback Loop? |
|---------|--------|-------------|----------------|
| Trailing Stop + Dynamic TP | WORKING | Every tick (10s) | Yes (adaptive) |
| Per-Trade Claude Analysis | WORKING | After each close | Yes (journal) |
| Claude Weekly Reports | WORKING | Sundays only | No |
| Lab 15-min Check-ins | WORKING | Every 15 min | No (data saved, never analyzed) |
| Lab Auto-Backtest | WORKING | Every 6 hours | No |
| Strategy Weight Evolution | PARTIAL | Sundays only | Yes (persisted) |
| Walk-Forward Analysis | WORKING | Manual only | No |
| Monte Carlo Simulation | WORKING | Manual only | No |
| Parameter Optimizer | DEAD CODE | Runs but results NEVER APPLIED | No |
| ML Model Training (XGBoost) | NOT BUILT | Never | N/A |

### DETAILS ON KEY ISSUES

**Claude Reports — WORKING but not daily:**
- File: `engine/src/learning/claude_review.py`
- Triggered: Only Sundays via `autonomous_trader._run_weekly_review()` (autonomous_trader.py:210-213)
- Also triggerable: `POST /api/learning/review` (manual)
- **The Scientist says:** You may have expected daily reports. It's weekly by design (config.py:101-102). If you want daily, change `weekly_optimizer` logic or add a daily trigger.

**Parameter Optimizer — DEAD CODE (most concerning):**
- File: `engine/src/learning/optimizer.py`
- **What happens:** Optimizer runs every 12 hours in lab (lab_trader.py:1063-1085), finds better params, saves to `data/optimizer_results.json`
- **What doesn't happen:** Strategies NEVER reload with optimized params. `autonomous_trader._run_weekly_review()` loads results (line 692) and clears cache (line 695), but the registry doesn't check `optimizer_results.json` when recreating strategies.
- **The Strategist says:** This is the classic "we computed the answer but never used it" pattern. The optimizer is essentially a very expensive log file.

**Walk-Forward + Monte Carlo — Manual only:**
- Both are fully implemented and available via API
- Neither is scheduled or automated
- Results don't feed back into strategy weights or risk parameters
- **The Scientist says:** These are diagnostic tools, not learning tools. They tell you IF a strategy works, but the system never acts on that information automatically.

**15-Min Check-ins — Data collected, never analyzed:**
- File: `lab_trader.py:887-989`
- Saves comprehensive stats to `data/lab_checkin_reports.json` every 15 min
- NEVER sent to Claude for analysis (saved tokens by design)
- **Opportunity:** This is a goldmine of unanalyzed data

---

# Q1. CLAUDE UTILIZATION — ARE WE USING AI ENOUGH?

> "I think we are not utilizing Claude more at more places. Claude should be helpful in improving process. We can get maybe insights from data."

## Current Claude Usage (3 places)

1. **Trade Gatekeeper** (`claude_engine/decision.py:169-281`) — Evaluates confluence signals, accepts/rejects
2. **Per-Trade Learning** (`agent/trade_learner.py:87-203`) — Grades every closed trade A-F, extracts lesson
3. **Weekly Review** (`learning/claude_review.py:153-240`) — Synthesizes stats into readable report

## Untapped Opportunities (The Scientist's recommendations)

**Don't force it — only where it genuinely helps:**

### HIGH VALUE:
| Opportunity | Data Already Exists? | What Claude Would Do |
|-------------|---------------------|---------------------|
| **Strategy Combination Analysis** | Yes — `strategies_agreed` column in every trade | "When RSI + Stochastic agree → 68% WR. When RSI alone → 52%." Find synergies. |
| **Loss Streak Diagnosis** | Yes — recent trades per symbol | After 3 consecutive losses: "All in VOLATILE regime, all used Fibonacci — stop using Fib on BTC in VOLATILE for 24h" |
| **Check-in Analysis** (every 4h) | Yes — `lab_checkin_reports.json` | "Signal rate 22% but conversion 36% — lower score threshold from 3.0→2.5 on 1h only" |

### MEDIUM VALUE:
| Opportunity | Data Already Exists? | What Claude Would Do |
|-------------|---------------------|---------------------|
| **Regime Transition Detection** | Yes — regime + timestamps in every trade | "After RANGING→TRENDING transition, first 5 trades have 61% WR, next 10 have 73%. Wait 1h after transition." |
| **Drawdown Forensics** | Yes — equity curve + trades | "8.7% DD on Dec 15-18: 7/8 losses used Camarilla, all on Gold in VOLATILE. Avoid metals in VOLATILE pre-holidays." |

### LOW VALUE (wait for Phase 2):
| Opportunity | Depends On | What Claude Would Do |
|-------------|-----------|---------------------|
| **Feature Importance Explanation** | XGBoost model (not built yet) | Explain which features predict wins |

**The Strategist says:** The highest-value addition is **strategy combination analysis**. You already store which strategies agreed for every trade. Claude could find: "EMA + RSI = 70% WR, EMA alone = 55%, RSI alone = 53%". This directly improves confluence scoring.

---

# Q4. ARE LEARNING MECHANISMS ACTUALLY LEARNING?

> "We had implemented many learning mechanisms — are they even working? Backtesting honestly I don't know that each backtest is even learning from the previous one."

## The Scientist's Verdict

### What IS Learning:
1. **Per-trade Claude grading** — Every closed trade gets a lesson. These lessons are stored in the journal. The weekly review reads them.
2. **Strategy blacklisting** — Strategies that lose money get blacklisted per instrument. Persisted to `learned_blacklists.json`. Survives restarts.
3. **Weight evolution** — Category weights per regime adjust weekly (Sundays). Based on avg P&L per category. Persisted to `data/regime_weights.json`.

### What is NOT Learning:
1. **Backtesting** — Each backtest runs independently. It does NOT learn from previous backtests. There's no "this strategy was bad last week, let me test with adjusted params this week" loop.
2. **Walk-Forward** — Provides overfit ratio but the system never acts on it. A strategy could have 80% overfit ratio and nothing changes.
3. **Monte Carlo** — Tells you probability of ruin but doesn't adjust risk sizing accordingly.
4. **Parameter Optimizer** — Finds better params but they're NEVER applied (dead code).
5. **ML Features** — 25+ features extracted per trade but no ML model exists to train on them.

### The Learning Loop is BROKEN

```
INTENDED LOOP:
  Trade → Grade → Lesson → Weekly Review → Adjust Weights → Better Trades

ACTUAL LOOP:
  Trade → Grade → Lesson → Stored in DB → (nothing reads it systematically)

  Weekly Review → Reads stats → Adjusts weights → (weights used next week)
  BUT: No connection between individual lessons and weight adjustments

  Optimizer → Finds better params → Saves to JSON → (nothing reads JSON)

  Walk-Forward → Computes overfit ratio → Returns to API → (user reads, nothing happens)
```

**The Scientist says:** The system has the COMPONENTS of a learning system but the CONNECTIONS between them are missing. Think of it as organs without blood vessels. Each piece works in isolation but there's no feedback loop connecting them into a functioning system.

### What "Backtesting Learning" Would Actually Look Like:

```
REAL LEARNING LOOP (not built):
  1. Lab generates 500 trades
  2. Analyzer identifies: "Fib loses on BTC in VOLATILE"
  3. Optimizer adjusts Fib params for BTC
  4. Backtester validates new params with walk-forward
  5. If improved: apply new params to production
  6. If not: log as "attempted, no improvement"
  7. Repeat
```

Currently, steps 1-2 work. Steps 3-7 are disconnected.

---

# Q5 + Q8 + Q9. MONITORING, ACCOUNTABILITY, AND ALERTING

> "We have a serious problem of monitoring processes... Lot of things in background but I have no idea unless I explicitly check... Do we have proper warnings and alerting?"

## The Operator's Audit

### CRITICAL GAPS:

**1. NO ERROR ALERTING**
- Lab/production engine crashes are **SILENT**
- If lab fails to start (`server.py:107`): logged as WARNING, no Telegram alert
- Database errors: caught with `except Exception: pass` in 20+ places
- Broker disconnection: logged but not escalated
- **Zero Telegram notifications for ANY error/failure**

**2. NO PROCESS SUPERVISION**
- Lab engine can crash at 2am → stays dead until manual restart
- No watchdog, no automatic restarts (unless Docker `restart: always` configured)
- Background tasks (backtester, optimizer, daily reviews) can fail silently

**3. SILENT FAILURES EVERYWHERE**
- 20+ instances of `except Exception: pass` across the codebase
- Notable locations:
  - `lab_trader.py:444` — Feature extraction fails silently
  - `lab_trader.py:652` — Journal errors don't block trading (intentional but invisible)
  - `server.py:107` — Lab startup failure → system continues without lab

**4. HEARTBEATS TOO INFREQUENT**
- Every 6 hours (lab: `lab_trader.py:262-290`, prod: `autonomous_trader.py:140-149`)
- If lab crashes at 00:01, next heartbeat would be at 06:00
- **6 hours of undetected downtime**

### WHAT DOES WORK:

| Component | Status | Notes |
|-----------|--------|-------|
| `/health` endpoint | Working | Returns component status, uptime |
| `/api/lab/verify` | Working | Comprehensive DB vs Binance reconciliation |
| Telegram heartbeats | Working | Every 6 hours, includes key metrics |
| Position reconciliation | Working | Every 5 min when using real broker |
| Log rotation | Working | 10MB max, 5 backups = 60MB cap |
| Graceful shutdown | Working | Saves risk state on SIGTERM |

### WHAT THE DASHBOARD SHOWS VS WHAT'S MISSING:

**Shows:** Trades, P&L, strategies, positions, balance, markets
**Missing:**
- Component health indicators (which background tasks are running?)
- Error log viewer
- Last heartbeat time
- Database size/growth
- Background task status ("when was last backtest? optimizer?")
- Candle data staleness ("is market data still updating?")
- Position sync status ("when was last reconciliation? any mismatches?")

### 11 USEFUL ENDPOINTS NEVER SHOWN IN DASHBOARD:

These exist in the backend but the UI never calls them:

1. `/api/lab/verify` — Data integrity check (most critical!)
2. `/api/lab/feedback` — Scan stats, conversion funnel
3. `/api/lab/checkin-reports` — 15-min check-in data
4. `/api/agent/start`, `/api/agent/stop` — Agent control
5. `/api/accuracy/history` — Rolling accuracy graph
6. `/api/costs/history` — Daily cost breakdown
7. `/api/learning/optimize/{symbol}` — Parameter optimization
8. `/api/learning/optimized-params` — Optimized parameters
9. `/api/risk/recommendations` — Adaptive risk suggestions
10. `/api/data/rate-limits` — API rate limit usage
11. `/api/lab/sync-balance` — Force balance sync

---

# Q6. SINGLE STRATEGY PER TRADE — IS THIS COUNTERPRODUCTIVE?

> "I know for a setup we are using a single strategy but isn't that counterproductive because some strategies might get tested less."

## How Strategy Selection Actually Works

**The Strategist explains:**

### Production/Backtester:
1. ALL 12 strategies scan the market on every tick
2. Each strategy produces a signal (or not)
3. Confluence scorer combines all signals into a composite score
4. **The BEST-scoring strategy's price levels** (entry, SL, TP) are used for execution
5. Other strategies contribute to **confidence** but not **execution levels**

```python
# autonomous_trader.py:310-314
best = max(
    (s for s in result.signals if s.direction is not None),
    key=lambda s: s.score, default=None,
)
```

### Lab Engine (Your saving grace):
The lab runs **TWO modes** that solve your concern:

**Mode 1 — Confluence** (same as production): Best signal wins
**Mode 2 — Individual** (`lab_trader.py:350-539`): Each strategy trades SOLO

```python
# lab_trader.py:400-408 — loops through EVERY strategy independently
for strategy in strategies:
    signal = strategy.analyze(candles[-250:], symbol)
    # Each strategy gets its own trade, regardless of others
```

**This means:** Every strategy IS getting tested in the lab, independently, every tick. The lab tracks per-strategy signal counts in `self._strategy_signals`.

### THE REAL PROBLEM:

**The Strategist says:** The lab's individual mode solves the testing fairness problem. But there's a deeper issue:

**No round-robin, no exploration:**
- Strategies compete purely on score
- A strategy with inherently lower scores (e.g., Camarilla in trending market) never gets tested even if it might work
- No "exploration vs exploitation" logic — the system always exploits the current best
- **TP-06** acknowledges this: `recommend_strategy_rehabilitation()` exists but requires manual action

**No strategy pair/combination testing:**
- The system knows: "RSI Divergence alone: 55% WR"
- The system doesn't know: "RSI Divergence + Stochastic together: 72% WR"
- The `strategies_agreed` column stores this data but nobody analyzes it

### CREATIVE SOLUTION (The Strategist proposes):

```
Instead of single-best-wins:

1. Shadow Trading: ALL strategies that fire get a "shadow trade"
   (tracked in DB, not executed). Compare shadow performance.

2. Exploration Budget: 10% of lab trades go to RANDOM strategy
   (not best-scoring). Like epsilon-greedy in RL.

3. Combination Analysis: Group historical trades by which
   strategies agreed. Find pairs that perform better together.
   Feed into confluence weights.
```

---

# Q7. DATA ENGINEERING — IS OUR DATA TRUSTWORTHY?

> "We need a data engineer to look at this. Although we are creating a lot of data in DB there is no verification. Claude can hallucinate and change the data."

## The Operator's Data Engineering Audit

### CURRENT STATE: WEAK

| Check | Exists? | Details |
|-------|---------|---------|
| OHLC data validation | Defined but possibly dead code | `data/models.py:64` — `validate()` method exists but grep didn't find it being called |
| DB vs Binance reconciliation | Yes (manual) | `/api/lab/verify` — comprehensive but must be called manually |
| Position reconciliation | Yes (auto) | Every 5 min when using real broker |
| SL/TP sanity check | Yes | `risk/manager.py:76` — always on |
| Journal write verification | No | Trades logged but no checksum/audit trail |
| Duplicate trade detection | No | No check if same signal processed twice |
| Market data freshness check | No | No alerts if candles stop updating |
| Balance drift detection | No | Only in manual `/api/lab/verify` |
| Schema migration tracking | No | SQLAlchemy `create_all()` — no Alembic migrations |
| Data backup | No | No automated backup of SQLite files |

### SPECIFIC DATA RISKS:

**1. Claude Can Corrupt Trade Grades**
- `trade_learner.py:87-171` sends trade to Claude, gets JSON response
- If Claude hallucinates: grade could be wrong, lesson nonsensical
- **No validation on Claude's response beyond JSON parsing**
- Mitigation: Gate 3 in `decision.py:116-175` validates Claude's trade decisions, but trade_learner has no Gate 3 equivalent

**2. No Foreign Key Enforcement**
- `database.py:74` mentions `DE-07: Add foreign key for referential integrity`
- SQLite foreign keys are OFF by default — need `PRAGMA foreign_keys = ON`
- A `trade_log` could reference a non-existent `signal_log_id`

**3. No Schema Versioning**
- Adding a column to a model changes the schema
- `Base.metadata.create_all()` doesn't ALTER existing tables
- Old data could have NULL in new columns with no migration path

**4. WAL File Growth**
- SQLite WAL mode enabled (database.py:267-271)
- WAL files (`notas_lave.db-wal`, `notas_lave_lab.db-wal`) visible in git status
- No periodic checkpointing configured — WAL could grow unbounded

**5. No Data Quality Metrics**
- No tracking of: records per day, null rates, outlier detection
- No "data health dashboard"
- No way to know if data quality is degrading over time

### THE GUARDIAN'S CONCERN:

"Every trade decision is based on data. If the data is wrong, the decisions are wrong. Right now, you're trusting that:
1. Market data is always correct (no staleness check)
2. Claude's grades are always correct (no validation)
3. DB writes always succeed (bare `except` blocks)
4. Old data is still schema-compatible (no migrations)
5. WAL files don't grow forever (no checkpointing)

**Any of these could silently corrupt your learning system.**"

### WHAT A DATA ENGINEER WOULD ADD:

```
1. Scheduled integrity checks (hourly):
   - /api/lab/verify runs automatically
   - Results sent to Telegram
   - Alerts on ANY discrepancy

2. Data quality metrics:
   - Records inserted today vs yesterday
   - Null rate per column
   - Outlier detection on P&L values

3. Write verification:
   - After DB write, read-back and confirm
   - Checksum on critical fields

4. Schema migrations:
   - Alembic for version-controlled schema changes
   - Backward-compatible column additions

5. Automated backups:
   - Copy SQLite file daily
   - Keep 7 days of backups

6. WAL management:
   - PRAGMA wal_checkpoint(TRUNCATE) on schedule
   - Monitor WAL file size
```

---

# EXPERT DEBATE — DISAGREEMENTS

Per the Build Protocol, experts MUST disagree on at least one thing.

## Debate 1: Should We Add More Claude Usage?

**The Strategist:** YES — strategy combination analysis is a no-brainer. The data exists, Claude just needs to analyze it.

**The Architect:** CAREFUL — every Claude call costs money and adds latency. The check-in analysis idea (every 4h) could cost $2-5/day in API calls. Is the insight worth it?

**The Scientist:** YES but MEASURABLY — add Claude insights as A/B tests. Track: did the system perform better AFTER Claude suggested "avoid BTC in VOLATILE"? If not, Claude is hallucinating patterns.

**The Operator:** NOT YET — fix the data integrity issues FIRST. Adding more Claude analysis on potentially corrupted data will amplify errors, not fix them.

**Resolution:** Fix data issues first (Q7), then add strategy combination analysis (Q1) with A/B testing to measure impact.

## Debate 2: How Urgent is the DB Separation Fix?

**The Guardian:** CRITICAL — this is a money-at-risk bug. Fix it today.

**The Architect:** MEDIUM — ContextVar isolation in asyncio mostly prevents cross-contamination. The real risk is the UI mismatch (close button, strategy leaderboard), not the ContextVar.

**The Operator:** HIGH — even if the ContextVar works today, one refactor could break it. The "works by accident" pattern in `paper_trader._reload_open_positions()` is a timebomb.

**Resolution:** Fix the UI mismatches immediately (lab close button, lab strategy leaderboard). Add explicit `use_db("default")` to all production endpoints as a safety measure.

## Debate 3: Should We Automate Walk-Forward + Monte Carlo?

**The Strategist:** YES — these should run weekly per instrument automatically.

**The Scientist:** YES but DON'T auto-apply results. Flag strategies with >50% overfit or >20% ruin probability, send Telegram alert, let human decide.

**The Architect:** NO — they're diagnostic tools. Automating them adds complexity. The user can run them when needed via the API.

**Resolution:** Automate scheduling (weekly cron), send results to Telegram, but don't auto-apply. Human reviews and decides.

---

# PRIORITY ACTION PLAN

## Tier 1: Fix Today (Data Integrity + Safety)
1. Add `use_db("default")` to all production journal endpoints
2. Fix Lab tab close button to call lab-specific endpoint
3. Fix Lab tab strategy leaderboard to use `/api/lab/strategies`
4. Add Telegram alerts for critical errors (engine crash, DB failure, broker disconnect)

## Tier 2: Fix This Week (Monitoring + Accountability)
5. Schedule `/api/lab/verify` to run hourly, alert on failure
6. Add "System Health" panel to dashboard (component status, last heartbeat, background task status)
7. Reduce heartbeat interval from 6h to 1h
8. Add `except Exception` audit — replace silent `pass` with proper logging

## Tier 3: Build Next (Learning Loop Completion)
9. Fix optimizer feedback loop — make registry use optimized params
10. Add strategy combination analysis (Claude, using existing `strategies_agreed` data)
11. Add loss streak diagnosis (Claude, triggered after 3 consecutive losses)
12. Automate walk-forward weekly, send results to Telegram

## Tier 4: Future (Data Engineering)
13. Add Alembic for schema migrations
14. Add SQLite WAL checkpointing on schedule
15. Add automated daily DB backup
16. Build ML training pipeline (Phase 2 — after 500+ lab trades)

---

# SUMMARY: EXPERT VERDICTS

| Expert | Overall Assessment |
|--------|-------------------|
| **Strategist** | System has good strategy diversity but the learning loop is broken. Strategies are tested but insights aren't applied. Strategy combination analysis is the biggest quick win. |
| **Architect** | DB separation is fragile, 11 useful endpoints aren't exposed in UI, and the parameter optimizer is dead code. The system is more complex than it needs to be for its current maturity. |
| **Guardian** | Close button mismatch is the most dangerous bug. Data integrity is assumed, not verified. No error alerting means silent failures go unnoticed. This system cannot run unattended safely. |
| **Scientist** | Features exist but the learning LOOP is missing. Each piece works in isolation but nothing connects: optimizer→registry, walk-forward→weights, lessons→adjustments. The "dead code" pattern is systemic. |
| **Operator** | The system cannot survive 30 days unattended. No process supervision, no error alerts, 6-hour heartbeat gaps, silent exception swallowing. Fix observability before adding features. |
