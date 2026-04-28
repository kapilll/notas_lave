# Notas Lave Trading Co-Pilot — Expert Design Document

**Date:** 2026-03-31
**Version:** 2.0 (Design + Trade Autopsy + Implementation Plan)
**Status:** READY FOR IMPLEMENTATION

---

## Table of Contents

1. [Panel 1: Trading Desk Analyst — Decision Framework](#panel-1-trading-desk-analyst)
2. [Panel 2: Quantitative Researcher — Statistical Analysis](#panel-2-quantitative-researcher)
3. [Panel 3: Platform Engineer — API Integration](#panel-3-platform-engineer)
4. [Panel 4: UX / Interaction Designer — Output Formats](#panel-4-ux--interaction-designer)
5. [Panel 5: Risk Management Specialist — Risk Advisory](#panel-5-risk-management-specialist)
6. [Panel 6: Debugging / Observability Expert — Health Checks](#panel-6-debugging--observability-expert)
7. [Panel 7: Trade Autopsy System — Automatic Post-Trade Reports](#panel-7-trade-autopsy-system)
8. [Implementation Plan — Phased with Model & Effort Specs](#implementation-plan)

---

## Panel 1: Trading Desk Analyst

### 1.1 Decision Framework

The co-pilot evaluates every proposal from the Strategy Arena through a **three-gate system**. A proposal must pass all three gates to receive a YES recommendation.

```
PROPOSAL IN
    │
    ▼
┌──────────────────┐
│  GATE 1: CONTEXT │  "Is the environment right?"
│  - Market regime │
│  - Volatility    │
│  - Correlation   │
│  - Time of day   │
│  - News calendar │
└────────┬─────────┘
         │ PASS
         ▼
┌──────────────────┐
│  GATE 2: QUALITY │  "Is this a good trade?"
│  - Signal score  │
│  - R:R vs ATR    │
│  - Trust earned  │
│  - Volume confirm│
│  - TF alignment  │
└────────┬─────────┘
         │ PASS
         ▼
┌──────────────────┐
│  GATE 3: RISK    │  "Can we afford it?"
│  - Drawdown room │
│  - Portfolio heat │
│  - Correlation   │
│  - Margin check  │
│  - Streak context│
└────────┬─────────┘
         │ PASS
         ▼
    YES / NO / WAIT
```

### 1.2 Proposal Scoring Rubric

For every proposal, the co-pilot runs this checklist:

#### A. Arena Score Audit

The current formula:
```
arena_score = 30% signal + 25% R:R + 15% trust + 10% WR + 20% diversity
```

**Co-pilot checks:**

| Check | Question | Red Flag |
|-------|----------|----------|
| Signal weight | Is 30% appropriate for current regime? | In VOLATILE regime, signal scores are noisy — should weight DOWN to ~20% |
| R:R weight | Does the R:R make sense given ATR? | R:R of 3.0 but SL is only 0.2 ATR away = likely to get stopped. R:R alone doesn't tell you if the trade has room to breathe |
| Trust weight | Is this strategy's trust score deserved? | Trust 65 but last 10 trades are 3W/7L = trust is lagging reality. Trust is slow-moving (±3/±5 per trade) — recent performance may diverge |
| Diversity weight | Is diversity inflating a weak signal? | Strategy idle 3h → diversity = 20 pts. If signal_score is 45, diversity alone could push it to execute. Flag proposals where diversity > signal contribution |
| Win rate weight | Is WR statistically significant? | WR of 80% on 5 trades means nothing. Need 30+ trades for WR to be meaningful (binomial confidence) |

**Regime-adaptive weight suggestions:**

| Regime | Signal | R:R | Trust | WR | Diversity | Rationale |
|--------|--------|-----|-------|----|-----------|-----------|
| TRENDING | 35% | 20% | 15% | 10% | 20% | Signals are clearer in trends, trust signal quality more |
| RANGING | 20% | 30% | 20% | 10% | 20% | R:R matters more (tight ranges), trust proven strategies |
| VOLATILE | 20% | 25% | 25% | 10% | 20% | Trust and proven track records matter most |
| QUIET | 30% | 25% | 10% | 15% | 20% | Standard, WR matters more in low-noise environments |

#### B. R:R Sanity Check

```
ATR_14 = 14-period ATR on entry timeframe
SL_distance = abs(entry - stop_loss)
TP_distance = abs(take_profit - entry)

Checks:
1. SL_distance >= 0.5 * ATR_14   → "SL has room to breathe"
2. SL_distance <= 2.0 * ATR_14   → "SL is not absurdly wide"
3. TP_distance <= 4.0 * ATR_14   → "TP is reachable within regime"
4. R:R >= 1.5                     → "Meets minimum threshold"

Red flags:
- SL < 0.3 * ATR → "This will get stopped out by noise"
- TP > 5 * ATR   → "This TP is aspirational, not realistic"
- SL == round number (e.g., 87000.0) → "Consider if S/R level, not arbitrary"
```

#### C. Trust Score Audit

```
recent_10_trades = last 10 closed trades for this strategy
recent_wr = wins / 10
expected_wr = strategy.win_rate (lifetime)

Checks:
1. |recent_wr - expected_wr| <= 20pp  → "Trust is tracking reality"
2. current_streak >= -3              → "No active losing streak"
3. trust_score > 30                  → "Not in caution zone"

Alerts:
- recent_wr < 30% AND trust > 50  → "Trust is overstated — recent performance is poor"
- recent_wr > 70% AND trust < 40  → "Trust is understated — strategy is recovering"
- 5+ consecutive losses            → "Strategy may be in regime mismatch"
```

#### D. Volume Confirmation

```
current_volume = latest completed candle volume
avg_volume_20 = 20-period SMA of volume

Checks:
1. current_volume >= 0.5 * avg_volume_20  → "Minimum participation"
2. For breakout signals: volume >= 1.5 * avg_volume_20  → "Surge confirmed"
3. For mean reversion: no requirement (can fade into low volume)

Red flags:
- Volume < 0.3 * average → "Ghost town — no liquidity to fill cleanly"
- Volume spike > 5x average → "Possible stop hunt / manipulation"
```

#### E. Timeframe Alignment

```
Fetch higher TF signal for same instrument:
- If entry on 15m, check 1h direction
- If entry on 1h, check 4h direction

Alignment check:
1. Same direction on higher TF  → +5 confidence
2. No signal on higher TF      → Neutral (0)
3. Opposing signal on higher TF → -10 confidence, flag WARNING

Red flag:
- 15m says LONG, 1h says SHORT → "Fighting the trend — needs exceptional signal"
```

### 1.3 "Should I Trade This?" Decision Tree

```
START
  │
  ├─ Is the engine healthy? (consecutive_errors == 0, broker connected)
  │   NO → WAIT ("Fix system issues first")
  │
  ├─ Is drawdown within safe zone? (daily < 4%, total < 15%)
  │   NO (daily >= 5% or total >= 18%) → NO ("Hard drawdown limit approaching")
  │   CAUTION (daily 4-5% or total 15-18%) → Flag "Reduce size by 50%"
  │
  ├─ Is proposal stale? (is_stale == true or expires_at < now)
  │   YES → WAIT ("Stale data — wait for fresh tick")
  │
  ├─ Does signal pass quality gate?
  │   signal_score < 50 → NO ("Signal too weak")
  │   signal_score 50-65 AND trust < 50 → NO ("Moderate signal + unproven strategy")
  │   signal_score >= 65 OR (signal_score >= 50 AND trust >= 65) → PASS
  │
  ├─ Does R:R pass ATR sanity check?
  │   SL < 0.3 * ATR → NO ("Will be noise-stopped")
  │   R:R < 1.5 → NO ("Insufficient reward")
  │   PASS
  │
  ├─ Portfolio impact acceptable?
  │   Would create 3+ positions in same direction → WAIT ("Directional concentration")
  │   Would exceed 60% of available margin → NO ("Over-leveraged")
  │   Correlated with existing position (BTC+ETH same direction) → Flag "Reduce size"
  │   PASS
  │
  ├─ Time of day acceptable?
  │   In "worst hours" per learning patterns → WAIT ("Historically poor hour")
  │   PASS
  │
  └─ All gates passed?
      YES → "YES — Execute. [Reasoning summary]"
      With flags → "YES with adjustments — [Reduce size / Tighten SL / etc.]"
```

### 1.4 Research Workflow

When the co-pilot wants to do deeper analysis on a proposal:

```
STEP 1: Context Gathering (parallel)
  ├─ GET /api/broker/status          → Balance, positions
  ├─ GET /api/risk/status            → P&L, drawdown
  ├─ GET /api/lab/status             → Engine health
  └─ GET /api/lab/proposals          → All active proposals

STEP 2: Instrument Deep Dive
  ├─ GET /api/scan/{symbol}?timeframe=15m  → Detailed signals
  ├─ GET /api/candles/{symbol}?timeframe=15m&limit=200  → Recent price action
  └─ GET /api/candles/{symbol}?timeframe=1h&limit=100   → Higher TF context

STEP 3: Strategy Context
  ├─ GET /api/lab/arena/leaderboard        → Trust scores
  ├─ GET /api/lab/arena/{strategy_name}    → Strategy detail + recent trades
  └─ GET /api/learning/trade-grades?limit=20  → Recent trade quality

STEP 4: Risk Assessment
  ├─ GET /api/lab/positions                → Current exposure
  ├─ GET /api/lab/risk                     → Risk capacity
  └─ GET /api/learning/patterns            → Hour/score patterns

STEP 5: Synthesize
  └─ Run decision tree with all collected data
  └─ Produce YES/NO/WAIT recommendation with reasoning
```

---

## Panel 2: Quantitative Researcher

### 2.1 Additional Analysis Beyond Platform

The platform already computes: arena scores, trust scores, trade grades, and basic learning recommendations. The co-pilot adds **meta-analysis** — analysis of the analysis.

#### A. Cross-Instrument Correlation Analysis

**Purpose:** Detect when "diversified" positions are actually one big directional bet.

```
Algorithm:
1. Fetch 1h candles for all instruments with open positions (GET /api/candles/{sym}?tf=1h&limit=100)
2. Compute rolling 20-period return correlations:
   returns_i = (close[t] - close[t-1]) / close[t-1]
   corr_matrix = pairwise_correlation(returns)
3. For each pair of open positions:
   corr = corr_matrix[sym_a][sym_b]
   same_direction = position_a.direction == position_b.direction

Alert conditions:
- corr > 0.7 AND same_direction     → "HIGH CORRELATION: {sym_a} and {sym_b} are r={corr:.2f} correlated and both {direction}. Effective exposure is 2x what it appears."
- corr > 0.7 AND opposite_direction  → "NATURAL HEDGE: {sym_a}/{sym_b} correlation {corr:.2f} with opposing directions. Positions partially offset."
- avg(all_corr) > 0.6               → "MARKET REGIME: Everything is correlated (avg r={avg:.2f}). This is a macro-driven market. Consider reducing total exposure by 30-50%."
```

**Expected correlation ranges (crypto):**

| Pair | Normal | High Alert |
|------|--------|------------|
| BTC/ETH | 0.65-0.80 | > 0.85 |
| BTC/SOL | 0.50-0.70 | > 0.80 |
| BTC/XRP | 0.40-0.60 | > 0.75 |
| ETH/SOL | 0.55-0.75 | > 0.85 |
| Any alt/Any alt | 0.30-0.60 | > 0.70 |

#### B. Regime Consistency Check

**Purpose:** Verify the platform's regime detection matches actual price behavior.

```
Algorithm:
1. Fetch platform's regime classification: from GET /api/scan/{symbol} → regime field
2. Independently compute regime from candles (GET /api/candles/{symbol}?tf=1h&limit=50):

   atr_14 = ATR(candles, 14)
   atr_50 = ATR(candles, 50)  # Long-term average ATR
   adx_14 = ADX(candles, 14)  # Average Directional Index

   if adx_14 > 25 AND close > EMA_20:
       computed_regime = TRENDING
   elif adx_14 < 20 AND atr_14 < atr_50 * 0.8:
       computed_regime = QUIET
   elif atr_14 > atr_50 * 1.5:
       computed_regime = VOLATILE
   else:
       computed_regime = RANGING

3. Compare:
   if platform_regime != computed_regime:
       alert("REGIME MISMATCH: Platform says {platform_regime}, price action suggests {computed_regime}. Strategies tuned for wrong regime.")
```

**Why this matters:** If the platform thinks it's TRENDING but price is actually RANGING, trend-following strategies will get chopped up and mean-reversion strategies will be underweighted.

#### C. Strategy Performance Attribution

**Purpose:** Distinguish skill from luck — is a strategy winning because of its signal, or because the market went up?

```
Algorithm:
1. Fetch closed trades: GET /api/lab/trades?limit=200
2. Fetch candles for same period: GET /api/candles/{symbol}?tf=1h&limit=200
3. For each strategy:

   actual_pnl = sum(trade.pnl for trade in strategy_trades)

   # Benchmark: what if you just held the asset?
   buy_hold_return = (last_close - first_close) / first_close * position_size

   # Benchmark: what if you took random entries with same R:R?
   random_baseline = num_trades * avg_risk * (0.5 * avg_rr - 0.5)  # 50/50 coin flip

   alpha = actual_pnl - buy_hold_return
   skill_ratio = actual_pnl / abs(random_baseline) if random_baseline != 0 else 0

Report:
- alpha > 0: "Strategy {name} generated ${alpha:.2f} alpha over buy-and-hold"
- alpha < 0: "Strategy {name} underperformed buy-and-hold by ${abs(alpha):.2f}"
- skill_ratio > 2.0: "Performance is 2x+ what random trading would produce — likely genuine edge"
- skill_ratio < 0.5: "Performance is worse than random — edge may not exist"
```

#### D. Drawdown Trajectory Analysis

**Purpose:** Is the current drawdown recoverable or structural?

```
Algorithm:
1. From GET /api/risk/status: get total_pnl, drawdown_pct
2. From GET /api/lab/trades?limit=100: compute equity curve

   equity_curve = [starting_balance]
   for trade in sorted_by_close_time:
       equity_curve.append(equity_curve[-1] + trade.pnl)

3. Compute drawdown characteristics:
   current_dd_pct = drawdown from peak
   dd_duration = candles since peak (how long have we been underwater?)
   recovery_rate = avg_win / avg_loss * win_rate  # Expected recovery per trade
   trades_to_recover = abs(dd_amount) / (avg_win * win_rate - avg_loss * (1 - win_rate))

Assessment:
- dd_pct < 3% AND dd_duration < 20 trades → "NORMAL: Within expected variance"
- dd_pct 3-6% AND recovery_rate > 1.2      → "RECOVERING: Drawdown is significant but edge is positive"
- dd_pct 3-6% AND recovery_rate < 1.0      → "STRUCTURAL: Drawdown + negative expectancy = broken edge"
- dd_pct > 6%                               → "CRITICAL: Approaching hard limits, recommend pause"
```

### 2.2 Statistical Checks

#### A. Win Rate Confidence

```
For each strategy:
   observed_wr = strategy.wins / strategy.total_trades
   expected_wr = 0.50  # Null hypothesis: no edge
   n = strategy.total_trades

   # Binomial test
   z = (observed_wr - expected_wr) / sqrt(expected_wr * (1 - expected_wr) / n)

   # Is the current WR within 2σ of expected?
   recent_wr = wins_last_20 / 20
   se = sqrt(observed_wr * (1 - observed_wr) / 20)
   z_recent = (recent_wr - observed_wr) / se if se > 0 else 0

Alerts:
- |z_recent| > 2.0 → "WIN RATE ANOMALY: {strategy} recent WR ({recent_wr:.0%}) deviates significantly from lifetime ({observed_wr:.0%}). z={z_recent:.1f}"
- n >= 30 AND z < 1.0 → "NO EDGE DETECTED: {strategy} has {n} trades but WR is not significantly better than chance (z={z:.1f})"
```

#### B. Sharpe Ratio Comparison

```
# Compute realized Sharpe
trade_returns = [trade.pnl / risk_per_trade for trade in recent_50_trades]
realized_sharpe = mean(trade_returns) / std(trade_returns) * sqrt(252)  # Annualized

# Compare to backtest Sharpe (if available from /api/backtest/arena/{symbol})
# If no backtest, compare to minimum acceptable (0.5)
min_sharpe = 0.5

Alerts:
- realized_sharpe < 0 → "NEGATIVE SHARPE: The system is losing money on a risk-adjusted basis"
- realized_sharpe < min_sharpe → "LOW SHARPE ({realized_sharpe:.2f}): Below minimum acceptable threshold"
- realized_sharpe < backtest_sharpe * 0.5 → "SHARPE DEGRADATION: Realized ({realized_sharpe:.2f}) is less than half of backtest ({backtest_sharpe:.2f})"
```

#### C. Streak Autocorrelation

```
# Are trade outcomes correlated? (streaks beyond what randomness predicts)
outcomes = [1 if trade.pnl > 0 else 0 for trade in last_50_trades]

# Runs test: expected runs for random sequence
n1 = sum(outcomes)  # wins
n0 = len(outcomes) - n1  # losses
expected_runs = (2 * n1 * n0) / (n1 + n0) + 1
runs_std = sqrt((2 * n1 * n0 * (2 * n1 * n0 - n1 - n0)) / ((n1 + n0)**2 * (n1 + n0 - 1)))
actual_runs = count_runs(outcomes)

z_runs = (actual_runs - expected_runs) / runs_std if runs_std > 0 else 0

Alerts:
- z_runs < -2.0 → "STREAK CLUSTERING: Outcomes are more streaky than random (z={z_runs:.1f}). Possible regime sensitivity — wins cluster in good conditions, losses cluster in bad."
- z_runs > 2.0  → "ALTERNATING PATTERN: Outcomes alternate more than random. Possible mean-reversion in P&L."
```

#### D. P&L Distribution Shift

```
# Compare first-half vs second-half of recent trades
all_trades = last_100_trades
first_half = all_trades[:50]
second_half = all_trades[50:]

mean_1 = mean(t.pnl for t in first_half)
mean_2 = mean(t.pnl for t in second_half)
std_1 = std(t.pnl for t in first_half)
std_2 = std(t.pnl for t in second_half)

# Welch's t-test for difference in means
t_stat = (mean_2 - mean_1) / sqrt(std_1**2/50 + std_2**2/50)

Alerts:
- t_stat < -2.0 → "P&L DETERIORATION: Recent trades are significantly worse than earlier trades (t={t_stat:.1f}). Edge may be decaying."
- t_stat > 2.0  → "P&L IMPROVEMENT: Recent trades are significantly better (t={t_stat:.1f}). System may be adapting well."
- std_2 > std_1 * 1.5 → "VOLATILITY INCREASE: P&L variance has increased 50%+. Risk is growing even if mean is stable."
```

### 2.3 Alert Thresholds

| Alert | Condition | Severity |
|-------|-----------|----------|
| Strategy degradation | Recent WR < lifetime WR - 2σ for 20+ trades | WARNING |
| Drawdown anomaly | Current DD > historical 95th percentile | CRITICAL |
| Concentration risk | 3+ positions correlated > 0.7, same direction | WARNING |
| Edge decay | Realized Sharpe < 50% of backtest Sharpe | WARNING |
| Structural breakdown | Negative expectancy over 30+ trades | CRITICAL |
| Streak anomaly | Runs test z < -2.5 | WARNING |
| P&L regime shift | t-stat > 2.0 (either direction) | INFO |

---

## Panel 3: Platform Engineer

### 3.1 API Endpoint Map

#### State Queries (Every Tick Cycle)

| Endpoint | Data Shape | Key Fields | Use Case |
|----------|------------|------------|----------|
| `GET /health` | `{status, version}` | `status: "ok"`, `version: "2.0.16"` | Liveness check |
| `GET /api/broker/status` | `{broker, connected, balance: {total, available, currency}, open_positions, positions: [...]}` | `connected`, `balance.available`, `open_positions` | Broker health + margin |
| `GET /api/risk/status` | `{balance, available, currency, original_deposit, total_pnl, total_pnl_pct, drawdown_from_peak, drawdown_from_peak_pct, ...}` | `total_pnl_pct`, `drawdown_from_peak_pct` | Risk state |
| `GET /api/lab/status` | `{lab_available, is_running, open_trades, closed_trades_today, win_rate, balance, available, consecutive_errors, exec_log, ...}` | `consecutive_errors`, `is_running`, `win_rate` | Engine health |
| `GET /api/lab/positions` | `{positions: [{symbol, direction, entry_price, current_price, stop_loss, take_profit, unrealized_pnl, proposing_strategy, trade_id}]}` | All position fields | Current exposure |

#### Analysis Queries (On-Demand)

| Endpoint | Data Shape | Key Fields | Use Case |
|----------|------------|------------|----------|
| `GET /api/lab/proposals` | `{proposals: [{rank, strategy, symbol, direction, entry_price, stop_loss, take_profit, position_size, risk_usd, reward_usd, rr_ratio, signal_score, arena_score, trust_score, will_execute, block_reason, factors, is_stale, expires_at}]}` | Full proposal with scoring breakdown | Proposal analysis |
| `GET /api/lab/arena` | `{leaderboard: [...], active_proposals: [...], active_strategies: [...], exec_log, consecutive_errors}` | Combined arena state | Full arena overview |
| `GET /api/lab/arena/leaderboard` | `{leaderboard: [{name, trust_score, wins, losses, total_trades, total_pnl, win_rate, profit_factor, expectancy, status, current_streak, is_active}]}` | Per-strategy performance | Strategy comparison |
| `GET /api/lab/arena/{strategy_name}` | `{strategy: {StrategyRecord}, recent_trades: [...]}` | Strategy detail + trade history | Deep dive on one strategy |
| `GET /api/scan/all?timeframe=15m` | `{results: [{symbol, price, regime, score, direction, agreeing, total, top_signal}]}` | `regime`, `score`, `direction` | Market overview |
| `GET /api/scan/{symbol}?timeframe=15m` | Full confluence analysis with per-strategy signals | Individual signal breakdowns | Instrument deep dive |
| `GET /api/candles/{symbol}?timeframe=15m&limit=200` | `{symbol, timeframe, candles: [{time, open, high, low, close, volume}], count}` | OHLCV array | Price action analysis |
| `GET /api/lab/trades?limit=50` | `{trades: [...], summary: {total_trades, wins, losses, total_pnl, win_rate}}` | Closed trade history | Performance review |
| `GET /api/lab/strategies` | `{strategies: [{strategy, wins, losses, trades, total_pnl, win_rate}]}` | Per-strategy P&L | Strategy comparison |
| `GET /api/learning/recommendations` | `{overall_performance, blacklist_suggestions, weight_adjustments, score_threshold, trading_hours, regime_warnings, adjustment_allowed, adjustment_cooldown_reason}` | Actionable ML suggestions | System tuning |
| `GET /api/learning/trade-grades?limit=50` | `{trades: [{id, symbol, direction, entry_price, exit_price, pnl, grade, lesson, exit_reason, proposing_strategy, closed_at}]}` | Grade distribution | Trade quality |
| `GET /api/learning/patterns` | `{by_hour, by_score_bucket, exit_reasons}` | Hour/score/exit patterns | Pattern analysis |
| `GET /api/learning/accuracy?days=30` | Prediction accuracy scores | Accuracy by strategy/timeframe | Signal reliability |
| `GET /api/journal/trades?limit=50` | `{trades: [...]}` | Full journal entries | Historical analysis |
| `GET /api/journal/performance` | `{strategies: [{strategy, wins, losses, total_trades, total_pnl, win_rate}]}` | Journal-based performance | Cross-check with lab |
| `GET /api/costs/summary` | `{total_runtime_cost, total_build_cost, total_cost, runtime_calls, currency}` | All 0.0 (placeholder) | Cost tracking |

#### Diagnostic Queries

| Endpoint | Data Shape | Key Fields | Use Case |
|----------|------------|------------|----------|
| `GET /api/lab/verify` | `{passed, checks: [{check, passed, diff}]}` | `passed`, individual check results | Reconciliation |
| `GET /api/lab/debug/execution` | Broker internals, balance, risk settings, sizing checks per instrument, proposals count | Sizing failures, product loading | Why trades aren't executing |
| `GET /api/lab/pace` | `{pace, entry_tfs, context_tfs, min_rr, max_concurrent, available, mode}` | Current pace settings | Configuration check |
| `GET /api/lab/markets` | `{markets: [{symbol, price, enabled, has_position, direction, pnl}]}` | All instruments with live data | Market overview |
| `GET /api/system/health` | `{timestamp, uptime_seconds, components: {lab_engine, broker, market_data}, data_health, errors_last_hour}` | Component status, error counts | System health |

#### Action Queries (User-Approved Only)

| Endpoint | Parameters | Risk Level | Use Case |
|----------|------------|------------|----------|
| `POST /api/lab/execute-proposal/{rank}` | `rank: int` | HIGH | Execute a specific proposal |
| `POST /api/lab/close/{trade_id}` | `trade_id: int` | HIGH | Close a position |
| `POST /api/lab/force-close/{symbol}` | `symbol: str` | HIGH | Force-close stuck position |
| `POST /api/lab/pace/{pace}` | `pace: str` (conservative/balanced/aggressive) | MEDIUM | Change trading pace |
| `POST /api/lab/sync-positions` | None | LOW | Force reconciliation |
| `POST /api/learning/analyze-now` | None | LOW | Trigger learning analysis |
| `POST /api/learning/review` | None | LOW | Trigger Claude review |
| `POST /api/backtest/arena/{symbol}` | `symbol, timeframe, days, seed_trust` | LOW | Run backtest |
| `POST /api/backtest/walk-forward/{symbol}` | `symbol, timeframe, days, folds` | LOW | Walk-forward validation |

### 3.2 Polling Cadence

```
TIER 1 — Every 60 seconds (Core State):
  GET /health
  GET /api/broker/status
  GET /api/risk/status
  GET /api/lab/status
  GET /api/lab/positions

TIER 2 — Every 5 minutes (Analysis):
  GET /api/lab/proposals
  GET /api/lab/arena/leaderboard
  GET /api/scan/all?timeframe=15m

TIER 3 — Every 30 minutes (Learning):
  GET /api/learning/summary
  GET /api/learning/recommendations
  GET /api/learning/trade-grades?limit=50
  GET /api/learning/patterns

TIER 4 — On Demand (User-Triggered):
  GET /api/scan/{symbol}
  GET /api/candles/{symbol}
  GET /api/lab/arena/{strategy}
  POST /api/backtest/*
  GET /api/learning/accuracy
```

### 3.3 Bug Detection Heuristics

```python
def detect_bugs(broker_status, lab_status, lab_verify, lab_positions, risk_status):
    bugs = []

    # 1. Position count mismatch
    broker_count = broker_status["open_positions"]
    journal_count = lab_status.get("open_trades", 0)
    if broker_count != journal_count:
        bugs.append({
            "severity": "HIGH",
            "bug": "POSITION_MISMATCH",
            "detail": f"Broker: {broker_count} positions, Journal: {journal_count}",
            "fix": "POST /api/lab/sync-positions to reconcile"
        })

    # 2. Verify endpoint failures
    if not lab_verify.get("passed", True):
        for check in lab_verify.get("checks", []):
            if not check["passed"]:
                bugs.append({
                    "severity": "HIGH",
                    "bug": "VERIFY_FAILED",
                    "detail": f"{check['check']}: {check['diff']}",
                    "fix": "Investigate diff, may need sync-positions or manual intervention"
                })

    # 3. P&L computation check
    for pos in lab_positions.get("positions", []):
        if pos.get("entry_price") and pos.get("current_price"):
            expected_direction = 1 if pos["direction"] == "LONG" else -1
            expected_pnl_sign = (pos["current_price"] - pos["entry_price"]) * expected_direction
            actual_pnl = pos.get("unrealized_pnl", 0)
            if (expected_pnl_sign > 0 and actual_pnl < 0) or (expected_pnl_sign < 0 and actual_pnl > 0):
                bugs.append({
                    "severity": "HIGH",
                    "bug": "PNL_SIGN_MISMATCH",
                    "detail": f"{pos['symbol']}: price suggests {'profit' if expected_pnl_sign > 0 else 'loss'} but P&L shows ${actual_pnl:.2f}",
                    "fix": "Check contract_size and P&L calculation (known issue with Delta API unrealized_pnl)"
                })

    # 4. Margin vs proposal readiness
    available = broker_status.get("balance", {}).get("available", 0)
    if available < 1.0:
        bugs.append({
            "severity": "MEDIUM",
            "bug": "NO_AVAILABLE_MARGIN",
            "detail": f"Available balance is ${available:.2f} — all proposals will show BLOCKED",
            "fix": "Close a position to free margin, or wait for trade to close"
        })

    # 5. Consecutive errors
    errors = lab_status.get("consecutive_errors", 0)
    if errors > 0:
        bugs.append({
            "severity": "HIGH" if errors >= 3 else "MEDIUM",
            "bug": "TICK_ERRORS",
            "detail": f"{errors} consecutive tick errors. exec_log: {lab_status.get('exec_log', 'N/A')}",
            "fix": "Check if an instrument was removed from registry but not from LAB_INSTRUMENTS"
        })

    # 6. All trust scores at default
    # (Would need leaderboard data)

    # 7. Stale data
    if not lab_status.get("is_running", False):
        bugs.append({
            "severity": "CRITICAL",
            "bug": "ENGINE_STOPPED",
            "detail": "Lab engine is not running",
            "fix": "Check system logs. Engine may have crashed or been stopped."
        })

    return bugs
```

---

## Panel 4: UX / Interaction Designer

### 4.1 Output Format Templates

#### Morning Brief

```
═══════════════════════════════════════════════
  NOTAS LAVE — MORNING BRIEF
  2026-03-31 09:00 UTC | Engine v2.0.16
═══════════════════════════════════════════════

ACCOUNT
  Balance: $97.42 (total) / $45.20 (available)
  P&L Today: +$2.15 (+2.2%)
  P&L Total: -$2.58 (-2.6%)
  Daily DD Used: 2.2% of 20% limit
  Total DD Used: 2.6% of 50% limit

POSITIONS (2 open)
  1. BTCUSD LONG  @ $87,250  │ P&L: +$1.85  │ SL: $86,800 │ TP: $88,150
     Strategy: trend_momentum │ Trust: 62     │ Duration: 4h
  2. ETHUSD SHORT @ $2,050   │ P&L: -$0.30  │ SL: $2,090  │ TP: $1,980
     Strategy: mean_reversion │ Trust: 48     │ Duration: 1h

MARKET REGIME
  BTC: TRENDING (score 72, bullish)
  ETH: RANGING (score 45, neutral)
  SOL: VOLATILE (score 38, bearish)

STRATEGY LEADERBOARD
  #1 trend_momentum    Trust: 62  WR: 58%  P&L: +$8.20  (12 trades)
  #2 level_confluence  Trust: 55  WR: 50%  P&L: +$1.40  (8 trades)
  #3 order_flow        Trust: 50  WR: --   P&L: $0.00   (0 trades)
  #4 breakout          Trust: 44  WR: 45%  P&L: -$3.10  (11 trades)
  #5 mean_reversion    Trust: 38  WR: 40%  P&L: -$4.50  (10 trades)
  #6 williams_system   Trust: 22  WR: 33%  P&L: -$5.20  (6 trades)  ⚠ CAUTION

OVERNIGHT ACTIVITY
  Trades executed: 3 (2W / 1L)
  Best: BTCUSD +$2.40 (trend_momentum, Grade A)
  Worst: SOLUSD -$1.80 (breakout, Grade D)

TOP OPPORTUNITIES
  1. BTCUSD — trend_momentum LONG, arena_score 68.3
     R:R 2.1, signal 72, trust 62 → READY
  2. SOLUSD — level_confluence SHORT, arena_score 55.1
     R:R 1.8, signal 58, trust 55 → READY

ISSUES: 0
═══════════════════════════════════════════════
```

#### Proposal Analysis

```
═══════════════════════════════════════════════
  PROPOSAL ANALYSIS: BTCUSD LONG
  Strategy: trend_momentum | Arena Rank: #1
═══════════════════════════════════════════════

SIGNAL
  Direction: LONG
  Entry: $87,250 | SL: $86,800 (-$450) | TP: $88,150 (+$900)
  R:R: 2.0:1
  Signal Score: 72/100
  Arena Score: 68.3/100

SCORING BREAKDOWN
  Signal (30%):    21.6 / 30  ← score 72
  R:R (25%):       10.0 / 25  ← R:R 2.0 (capped at 5.0)
  Trust (15%):      9.3 / 15  ← trust 62
  Win Rate (10%):   5.8 / 10  ← WR 58%
  Diversity (20%): 12.0 / 20  ← idle 72 min (60% of 2h cap)
                   ─────────
  Total:           68.3 / 100

QUALITY CHECKS
  ✅ Signal score 72 > threshold 65 (standard tier)
  ✅ R:R 2.0 >= minimum 1.5
  ✅ SL distance ($450) = 0.8 ATR ← healthy room
  ⚠️  Diversity contributes 12/68.3 pts (18%) — moderate inflation
  ✅ Volume: 1.2x average (confirmed)
  ✅ Higher TF (1h): also LONG (aligned)

RISK CHECKS
  ✅ Daily DD: 2.2% used, room for $17.60 more loss
  ✅ Total DD: 2.6% used, well within 50% limit
  ✅ Risk per trade: $4.50 = 4.6% of balance
  ⚠️  Portfolio: already LONG BTC — this adds to same direction
  ✅ Available margin: $45.20 sufficient
  ✅ No loss streak (current streak: +2)

RECOMMENDATION: YES ✅
  This is a clean trend continuation setup with aligned timeframes,
  healthy R:R, and volume confirmation. The strategy has earned its
  trust through 12 trades with 58% WR.

  Caveat: You already have a BTC LONG — this is adding to a winner,
  which is valid but increases BTC concentration.

COMPETING PROPOSALS (same tick)
  #2 SOLUSD SHORT by level_confluence (arena_score 55.1) — ALSO VALID
  #3 ETHUSD LONG by breakout (arena_score 42.7) — WEAK (low trust)
═══════════════════════════════════════════════
```

#### Bug Report

```
═══════════════════════════════════════════════
  BUG REPORT — 2026-03-31 14:30 UTC
═══════════════════════════════════════════════

ISSUE: Position Count Mismatch
SEVERITY: HIGH

EVIDENCE
  Broker (Delta): 2 positions
    - BTCUSD LONG (0.01 BTC)
    - ETHUSD SHORT (0.1 ETH)

  Journal: 3 open trades
    - #42 BTCUSD LONG ← matches broker
    - #43 ETHUSD SHORT ← matches broker
    - #41 SOLUSD LONG  ← NOT on broker (orphaned)

DIAGNOSIS
  Trade #41 (SOLUSD LONG) was likely closed on Delta Exchange
  (SL hit or manual close via Delta UI) but the journal was not
  updated. This is a known pattern — the reconciliation loop
  requires 2 consecutive misses before closing journal entries
  (C4 safety check).

IMPACT
  - P&L reporting includes phantom position
  - Max concurrent count is inflated (3 vs actual 2)
  - Available margin calculation may be wrong

RECOMMENDED FIX
  1. POST /api/lab/sync-positions → force reconciliation
  2. If persists, POST /api/lab/force-close/SOLUSD

  The reconciliation should detect the orphan on the next 2 ticks
  and auto-close the journal entry.
═══════════════════════════════════════════════
```

#### Performance Review

```
═══════════════════════════════════════════════
  PERFORMANCE REVIEW — Last 7 Days
  2026-03-24 to 2026-03-31
═══════════════════════════════════════════════

OVERVIEW
  Trades: 28 (16W / 12L)
  Win Rate: 57.1%
  Net P&L: +$4.20 (+4.3%)
  Profit Factor: 1.42
  Avg Winner: +$1.85 | Avg Loser: -$1.48
  Best Trade: BTCUSD +$4.50 (Grade A, trend_momentum)
  Worst Trade: SOLUSD -$3.20 (Grade F, breakout)

BY STRATEGY
  ┌────────────────────┬───────┬────┬────┬────────┬──────┬────────┐
  │ Strategy           │ Trust │ WR │ #  │ P&L    │ PF   │ Streak │
  ├────────────────────┼───────┼────┼────┼────────┼──────┼────────┤
  │ trend_momentum     │ 62    │68% │ 8  │ +$5.20 │ 2.10 │ +3     │
  │ level_confluence   │ 55    │50% │ 6  │ +$1.10 │ 1.35 │ -1     │
  │ order_flow         │ 50    │50% │ 4  │ +$0.40 │ 1.15 │ +1     │
  │ mean_reversion     │ 38    │40% │ 5  │ -$1.20 │ 0.78 │ -2     │
  │ breakout           │ 44    │33% │ 3  │ -$2.80 │ 0.45 │ -3 ⚠️  │
  │ williams_system    │ 22    │50% │ 2  │ +$1.50 │ 1.60 │ +1     │
  └────────────────────┴───────┴────┴────┴────────┴──────┴────────┘

INSIGHTS
  📈 trend_momentum is carrying the book — 68% WR with PF 2.1
  ⚠️  breakout has 3 consecutive losses — throttle is active (half risk)
  ⚠️  mean_reversion WR dropped from 55% to 40% — possible regime shift
  ℹ️  williams_system recovering from suspension — small sample (2 trades)

GRADE DISTRIBUTION
  A: 5 (18%) | B: 8 (29%) | C: 6 (21%) | D: 5 (18%) | F: 4 (14%)

PATTERN INSIGHTS
  Best hours: 08-10 UTC (WR 73%, 11 trades)
  Worst hours: 00-02 UTC (WR 30%, 7 trades)
  Best score bucket: 70-80 (WR 75%, PF 2.8)

RECOMMENDATIONS
  1. Consider pausing breakout strategy until regime changes
  2. Investigate mean_reversion recent decline
  3. Avoid trading 00-02 UTC (historically worst window)
═══════════════════════════════════════════════
```

#### Alert

```
🔴 CRITICAL ALERT — Drawdown Limit Approaching

Daily drawdown is at 4.2% of 6.0% limit.
One more loss of $1.80+ will trigger trading halt.

Current positions:
  BTCUSD LONG — unrealized: -$1.20 (SL would lose $4.50)
  ETHUSD SHORT — unrealized: +$0.30 (SL would lose $2.10)

If both SLs hit: daily DD → 7.7% → HALTED.

Recommendation: Consider closing BTCUSD to lock in the loss
and protect remaining capital for tomorrow.
```

### 4.2 Interaction Patterns

| User Says | Agent Does | API Calls |
|-----------|-----------|-----------|
| "What's going on?" | Pull status, positions, risk, recent trades → Summary | `/broker/status`, `/risk/status`, `/lab/status`, `/lab/positions`, `/lab/trades?limit=5` |
| "Should I take this BTC trade?" | Pull proposals, scan BTC, check risk → Recommendation | `/lab/proposals`, `/scan/BTCUSD`, `/risk/status`, `/lab/positions`, `/candles/BTCUSD` |
| "Why aren't we trading?" | Check engine, debug, balance, proposals → Diagnosis | `/lab/status`, `/lab/debug/execution`, `/broker/status`, `/lab/proposals` |
| "How is trend_momentum doing?" | Pull strategy detail, grades, patterns → Analysis | `/lab/arena/trend_momentum`, `/learning/trade-grades`, `/learning/patterns`, `/lab/strategies` |
| "Is anything broken?" | Run full verify, check positions vs journal → Bug report | `/lab/verify`, `/lab/positions`, `/broker/status`, `/lab/status`, `/system/health` |
| "Give me the morning brief" | Full state pull → Morning Brief format | All Tier 1 + Tier 2 endpoints |
| "Run a health check" | Sequential diagnostic chain → Health report | `/health`, `/broker/status`, `/lab/verify`, `/lab/status`, `/lab/debug/execution` |
| "Compare strategies" | Pull leaderboard + trades → Comparison table | `/lab/arena/leaderboard`, `/lab/strategies`, `/learning/strategies`, `/lab/trades?limit=200` |
| "Backtest BTC" | Run arena backtest → Results | `POST /backtest/arena/BTCUSD` |
| "What should I optimize?" | Pull recommendations → Actionable list | `/learning/recommendations`, `/learning/patterns`, `/learning/accuracy` |

### 4.3 Proactive Alerts (Background Agent Only)

These alerts would fire automatically without user prompting (Phase 3 — background agent):

| Alert | Trigger | Message |
|-------|---------|---------|
| Drawdown approaching | daily DD > 80% of limit | "Daily DD at {pct}% — {room} away from halt" |
| Strategy collapse | trust < 25 AND was > 40 within 5 trades | "{strategy} trust dropped to {trust} — was {prev} five trades ago" |
| Margin exhausted | available < $2.00 | "Available margin ${avail} — proposals will show BLOCKED" |
| Engine errors | consecutive_errors > 0 | "Engine has {n} consecutive errors — check exec_log" |
| Broker disconnect | connected == false | "Broker disconnected — no trades will execute" |
| Stale proposals | all proposals is_stale == true | "All proposals are stale — market data may be delayed" |
| Loss streak | any strategy streak <= -5 | "{strategy} has lost {n} consecutive trades" |
| No activity | no trades in 24h despite proposals | "No trades executed in 24h — execution pipeline may be stuck" |
| Win streak | any strategy streak >= 5 | "Nice! {strategy} has won {n} consecutive — verify edge, don't increase size" |

---

## Panel 5: Risk Management Specialist

### 5.1 Pre-Trade Risk Checks

The co-pilot performs these checks **before** recommending any trade, in addition to the platform's built-in `RiskManager.validate_trade()`:

```
PRE-TRADE RISK CHECKLIST

1. DRAWDOWN ROOM
   daily_dd_used = today_realized_pnl + unrealized_pnl
   daily_dd_limit = starting_balance * max_daily_dd_pct
   daily_room = daily_dd_limit - abs(daily_dd_used)

   total_dd_used = total_pnl
   total_dd_limit = original_starting_balance * max_total_dd_pct
   total_room = total_dd_limit - abs(total_dd_used)

   Zones:
   - GREEN: room > 50% of limit     → Normal trading
   - YELLOW: room 20-50% of limit   → Reduce size by 50%
   - RED: room < 20% of limit       → NO NEW TRADES

2. PORTFOLIO HEAT
   total_risk = sum(abs(entry - sl) * size * contract_size for each open position)
   heat_pct = total_risk / current_balance * 100

   - heat < 5%   → Cool (can add)
   - heat 5-10%  → Warm (selective adds only)
   - heat > 10%  → Hot (no new positions)
   - heat > 15%  → Overheated (consider closing weakest)

3. CORRELATION CHECK
   For proposed trade's instrument:
   - List all open positions
   - Check if any are in same asset or highly correlated asset
   - Same instrument, same direction → BLOCKING ("Already exposed")
   - Correlated instrument, same direction → WARNING + size reduction
   - Correlated instrument, opposite direction → INFO ("Natural hedge")

4. LOSS STREAK CONTEXT
   strategy_streak = strategy.current_streak
   portfolio_streak = count consecutive losses across all strategies

   - strategy_streak <= -3 → Platform halves risk (automatic)
   - strategy_streak <= -5 → Co-pilot recommends pausing strategy
   - portfolio_streak <= -5 → Co-pilot recommends switching to conservative pace
   - portfolio_streak <= -8 → Co-pilot recommends halting all trading

5. WIN STREAK CONTEXT
   - strategy_streak >= 5 → WARNING: "Don't increase size. Regression to mean is real."
   - portfolio_streak >= 5 → INFO: "Good run. This is when overconfidence kills."

6. AVAILABLE MARGIN CHECK
   required_margin = position_size * entry_price / leverage
   available = broker_balance.available

   if required_margin > available * 0.8:
       WARNING: "This trade uses {pct}% of available margin"
   if required_margin > available:
       BLOCK: "Insufficient margin"

7. TIME OF DAY CHECK (from learning patterns)
   current_hour = datetime.utcnow().hour
   if current_hour in worst_hours:
       WARNING: "Hour {hour} UTC historically has {wr}% win rate"
   if current_hour in best_hours:
       INFO: "Hour {hour} UTC is historically strong ({wr}% WR)"
```

### 5.2 Kill Switch Recommendations

```
PAUSE TRADING (switch to conservative pace):
  - Daily DD > 4% of 6% limit (67% used)
  - 3+ consecutive portfolio losses
  - 2+ strategies simultaneously suspended (trust < 20)
  - Broker reports unusual latency (fills taking > 5s)
  - Available margin < 20% of total balance

CLOSE ALL POSITIONS:
  - Daily DD > 5% of 6% limit (83% used)
  - Portfolio heat > 15% of balance at risk
  - Broker connection intermittent (connected flipping)
  - All proposals showing BLOCKED for > 30 min
  - Manual user override

HALT ALL TRADING (stop engine):
  - Daily DD hits limit (6% for personal, 5% for prop)
  - Total DD > 90% of limit
  - consecutive_errors > 5
  - Broker balance shows $0 (or negative)
  - 8+ consecutive portfolio losses
```

### 5.3 Position Management Advice

#### Move SL to Breakeven

```
WHEN:
  - Position P&L >= 1.0R (made at least 1x risk)
  - AND position has been open > 30 minutes
  - AND price has not retraced more than 30% from MFE

WHY NOT EARLIER:
  - Moving to BE too early gets you stopped on noise
  - Must give the trade room to develop

HOW:
  "Consider moving SL to breakeven (+spread) on {symbol}.
  Position is at {r_multiple:.1f}R profit. Original risk ${risk:.2f}
  is now secured."
```

#### Take Partial Profits

```
WHEN:
  - Position P&L >= 2.0R
  - AND TP is still 1.5R+ away
  - AND regime has shifted (was TRENDING, now RANGING)

SUGGESTION:
  "Consider closing 50% of {symbol} at current price.
  You've reached {r_multiple:.1f}R but the regime is shifting.
  Lock in ${partial_pnl:.2f} and let the rest run with SL at BE."
```

#### Add to Winner

```
WHEN:
  - Position P&L >= 1.5R
  - AND same strategy is generating a new signal in same direction
  - AND portfolio heat < 5%
  - AND daily DD used < 50% of limit

CAUTION:
  "New signal to add to winning {symbol} {direction}.
  Current position: {r_multiple:.1f}R profit.
  ⚠️ Adding doubles your exposure. Only proceed if:
  - Higher TF still confirms direction
  - New SL protects original entry profit
  - Total portfolio heat stays under 10%"
```

#### Cut Before SL

```
WHEN:
  - Position P&L < -0.5R AND deteriorating
  - AND the signal that generated the trade has reversed
  - AND volume confirms the reversal

SUGGESTION:
  "The signal that generated {symbol} {direction} has reversed.
  Current P&L: -${loss:.2f} (-{r_pct:.0f}% of risk).
  SL at ${sl} would lose ${max_loss:.2f}.
  Consider closing now to save ${savings:.2f}.

  Evidence: {reversal_reason}"
```

---

## Panel 6: Debugging / Observability Expert

### 6.1 Health Check Sequence

```
STEP 1: ENGINE ALIVE?
  GET /health
  Expected: {"status": "ok", "version": "X.Y.Z"}
  Fail: Engine is down. Check systemd: systemctl status notas-lave

STEP 2: BROKER CONNECTED?
  GET /api/broker/status
  Check: connected == true
  Check: balance.total > 0
  Check: balance.available > 0
  Fail: Check Delta API keys, IP whitelist, testnet vs production

STEP 3: DATA INTEGRITY?
  GET /api/lab/verify
  Check: passed == true
  Fail: Individual checks show what's mismatched
  Fix: POST /api/lab/sync-positions

STEP 4: ENGINE RUNNING?
  GET /api/lab/status
  Check: is_running == true
  Check: consecutive_errors == 0
  Fail: Read exec_log for crash reason
  Common: instrument removed from registry but still in LAB_INSTRUMENTS

STEP 5: EXECUTION PIPELINE?
  GET /api/lab/debug/execution
  Check: all instruments show valid sizing
  Check: products loaded for broker
  Fail: Sizing returns 0 for an instrument → check min_lot, min_notional, balance

STEP 6: DATA FRESHNESS?
  GET /api/system/health
  Check: market_data.last_success_by_source timestamps < 5 min ago
  Check: errors_last_hour == 0
  Fail: Market data source may be rate-limited or down
```

### 6.2 Common Failure Patterns

#### Pattern: "consecutive_errors: N"

```
DIAGNOSIS:
  1. GET /api/lab/status → read exec_log
  2. Common causes:
     a. Instrument removed from data/instruments.py but still in LAB_INSTRUMENTS (lab.py:57-59)
        → Fix: Remove from LAB_INSTRUMENTS list
     b. Market data source returning empty candles
        → Fix: Check TwelveData/CCXT rate limits
     c. Broker API timeout
        → Fix: Check Delta Exchange status page
     d. Division by zero in position sizing (ATR = 0)
        → Fix: Skip instrument with zero ATR

  3. After identifying root cause:
     - Fix the issue
     - Engine should auto-recover (consecutive_errors resets on successful tick)
```

#### Pattern: "Broker says 0 positions but journal shows N open"

```
DIAGNOSIS:
  1. GET /api/lab/verify → see specific mismatches
  2. Likely causes:
     a. Positions closed on Delta UI/API directly (not through Notas Lave)
     b. SL/TP hit on broker side but engine was down during the event
     c. Reconciliation hasn't run yet (needs 2 consecutive misses, C4 safety)

  FIX:
  1. POST /api/lab/sync-positions → triggers reconciliation
  2. Wait for 2 tick cycles (reconciliation needs 2 consecutive misses)
  3. If still mismatched: POST /api/lab/force-close/{symbol} for each orphan
```

#### Pattern: "All proposals show BLOCKED"

```
DIAGNOSIS:
  1. GET /api/broker/status → check balance.available
     - If available ≈ 0: all margin is consumed by open positions
     - Fix: close a position to free margin

  2. GET /api/lab/arena/leaderboard → check trust scores
     - If all trust < 20: all strategies suspended
     - Fix: POST /api/backtest/arena/BTCUSD?seed_trust=true to re-seed

  3. GET /api/lab/debug/execution → check sizing
     - If all show "size: 0": balance too low for minimum lot sizes
     - Fix: need more capital or reduce min_lot requirements

  4. GET /api/lab/proposals → check block_reason field
     - Common: "risk_rejected", "insufficient_margin", "max_concurrent"
```

#### Pattern: "No proposals at all"

```
DIAGNOSIS:
  1. GET /api/lab/status → is_running?
     - If false: engine not started. Check lifespan startup.

  2. GET /api/scan/all → are there any signals?
     - If all scores < 50: market is quiet, no strategies generating signals
     - This is normal — not everything is tradeable all the time

  3. Check pace settings: GET /api/lab/pace
     - conservative pace only scans 1h timeframe → fewer signals

  4. Check LAB_INSTRUMENTS in lab.py → are instruments configured?
```

#### Pattern: "Trade executed but P&L shows crazy number"

```
DIAGNOSIS:
  1. Check contract_size for the instrument
     - XAUUSD: contract_size = 100 (100 oz per lot)
     - Crypto: contract_size = 1
     - Wrong contract_size → P&L off by 100x

  2. Check if using broker's unrealized_pnl
     - Delta API unrealized_pnl returns cost basis, not actual P&L (v2.0.11 bug)
     - Platform should use: (current_price - entry_price) * size * contract_size * direction_sign

  3. Check filled_price vs entry_price in TradeLog
     - If different: slippage occurred
     - P&L should use filled_price, not signal entry_price
```

### 6.3 Diagnostic Report Format

```
═══════════════════════════════════════════════
  SYSTEM HEALTH CHECK — 2026-03-31 14:30 UTC
═══════════════════════════════════════════════

ENGINE
  Status: ✅ Running
  Version: v2.0.16
  Uptime: 48h 23m
  Consecutive Errors: 0
  Last Tick: 12s ago

BROKER
  Status: ✅ Connected (Delta testnet)
  Balance: $97.42 total / $45.20 available
  Margin Used: 53.6%

POSITIONS
  Broker: 2 open
  Journal: 2 open
  Match: ✅

  #42 BTCUSD LONG  │ Entry: $87,250 │ Current: $87,400 │ P&L: +$1.50
  #43 ETHUSD SHORT │ Entry: $2,050  │ Current: $2,045  │ P&L: +$0.50

RISK
  Daily DD: 2.2% of 20% limit (GREEN)
  Total DD: 2.6% of 50% limit (GREEN)
  Portfolio Heat: 4.8% (COOL)
  Trades Today: 3

MARKET DATA
  CCXT: ✅ (last success: 8s ago)
  TwelveData: ✅ (last success: 45s ago)

STRATEGY HEALTH
  trend_momentum:   ✅ Trust 62, active
  level_confluence:  ✅ Trust 55, active
  order_flow:        ✅ Trust 50, active
  breakout:          ⚠️ Trust 44, caution (streak: -3)
  mean_reversion:    ⚠️ Trust 38, caution (streak: -2)
  williams_system:   ⚠️ Trust 22, caution (streak: -1)

ISSUES FOUND: 0

WARNINGS: 2
  ⚠️ breakout: 3 consecutive losses, risk throttled to 50%
  ⚠️ williams_system: Trust 22, approaching suspension (< 20)
═══════════════════════════════════════════════
```

---

## Panel 7: Trade Autopsy System

### 7.1 What This Does

After every trade closes, the system automatically:
1. Gathers all context (market data, strategy state, risk state, competing proposals) — **pure Python, zero API calls**
2. Calls Claude (**Haiku**) to produce a structured post-trade report
3. Saves the report as a markdown file to `data/trade_reports/`
4. Sends a compact 2-line summary to Telegram

Later, on demand or weekly:
1. Python pre-computes a compressed summary of all accumulated reports
2. Claude (**Sonnet**) reads the summary and finds patterns, edges, and failure modes
3. Produces an edge-finding report saved to `data/trade_reports/summaries/`

### 7.2 Token Budget & Model Selection

#### Per-Trade Report: Haiku 4.5

| Component | Tokens | Cost |
|-----------|--------|------|
| System prompt (cached after first call) | ~300 | — |
| Trade context (pre-computed numbers only) | ~400 | — |
| **Total input** | **~700** | **$0.00056** |
| Structured JSON output | ~500 | **$0.002** |
| **Total per trade** | **~1,200** | **$0.0026** |

**Why Haiku:** Each report is structured analysis of known data — no deep reasoning needed. Haiku is 3.75x cheaper than Sonnet, 19x cheaper than Opus.

#### Weekly Edge Analysis: Sonnet 4.6

| Component | Tokens | Cost |
|-----------|--------|------|
| System prompt | ~400 | — |
| Pre-computed summary of 70 reports | ~2,000 | — |
| **Total input** | **~2,400** | **$0.0072** |
| Analysis output | ~1,500 | **$0.0225** |
| **Total per analysis** | **~3,900** | **$0.030** |

**Why Sonnet:** Pattern finding across 50-100 trades needs reasoning Haiku can't match. But NOT Opus — we pre-compute the stats, Claude only interprets.

#### Monthly Cost Projection

| Scenario | Trades/Month | Trade Reports (Haiku) | Edge Analysis (Sonnet) | Total |
|----------|-------------|----------------------|----------------------|-------|
| Quiet (testnet) | 50 | $0.13 | $0.12 | **$0.25** |
| Normal (10/day) | 300 | $0.78 | $0.12 | **$0.90** |
| Active (30/day) | 900 | $2.34 | $0.12 | **$2.46** |
| Very active (50/day) | 1,500 | $3.90 | $0.12 | **$4.02** |

### 7.3 Token-Saving Rules

**RULE 1: Pre-compute everything, send only numbers.**
Never send raw candles or trade lists to Claude. Always pre-compute metrics first.

```
BAD (wastes tokens — ~5,000 tokens):
  "Here are the last 200 candles for BTCUSD: [{time: ..., open: ..., ...}, ...]"

GOOD (cheap — ~50 tokens):
  "ATR_14=320, regime=TRENDING, RSI=38, EMA_aligned=bullish, volume=1.2x"
```

**RULE 2: Structured JSON output with max_tokens cap.**
Force fixed JSON structure. Cap at `max_tokens=512` for Haiku, `max_tokens=1500` for Sonnet.

**RULE 3: Reuse system prompts.**
Same system prompt for every trade report → Anthropic prompt caching kicks in after first call.

**RULE 4: Skip Claude when unnecessary.**
- Grade C (breakeven) → nothing to learn, skip
- Duration < 60 seconds → noise, skip
- Duplicate symbol within 5 minutes → skip

**RULE 5: Compress for batch analysis.**
For weekly edge analysis, don't send 70 full reports (35,000 tokens). Pre-compute a summary in Python (2,000 tokens):
```
WEEK SUMMARY (70 trades):
By strategy: trend_momentum 15W/5L +$12, mean_reversion 8W/12L -$8
By regime: TRENDING 20W/8L, RANGING 5W/15L
By hour: 08-10 UTC best (73% WR), 00-02 worst (30% WR)
Common verdicts: [extracted from reports]
Common edge_signals: [extracted from reports]
```

### 7.4 Architecture

#### Hook Point

Subscribe to `TradeClosed` event in `run.py`, same pattern as Telegram alerts:

```python
# In engine/run.py build_container():
bus.subscribe(TradeClosed, _notify_telegram, FailurePolicy.LOG_AND_CONTINUE)    # existing
bus.subscribe(TradeClosed, _generate_trade_report, FailurePolicy.LOG_AND_CONTINUE)  # NEW
```

#### Data Flow

```
TradeClosed event
    │
    ▼
gather_trade_context()              ← Pure Python, reads from memory only
    │  Reads: TradeLog (SQLAlchemy), leaderboard, risk state
    │  Computes: ATR ratio, regime, volume ratio, R-multiple, streak
    │  Output: ~400 token context string
    │
    ▼
should_generate_report()            ← Skip check (grade C, <60s, duplicate)
    │
    ▼
call_haiku(system_prompt, context)  ← ~700 input, ~500 output, $0.0026
    │
    ▼
save_report(trade_id, report)       ← Write to data/trade_reports/YYYY-MM/
    │
    ▼
send_telegram_summary(report)       ← 2-line summary from report
```

#### File Storage

```
data/trade_reports/
├── 2026-03/
│   ├── trade_0041_BTCUSD_LONG_20260330.md
│   ├── trade_0042_ETHUSD_SHORT_20260331.md
│   └── ...
├── 2026-04/
│   └── ...
└── summaries/
    ├── week_2026-W13.md           ← weekly edge analysis (Sonnet)
    ├── week_2026-W14.md
    └── edge_findings.md           ← cumulative edge document
```

### 7.5 Report Formats

#### Individual Trade Report (Haiku output, saved to disk)

```markdown
# Trade #42 — ETHUSD SHORT

**Date:** 2026-03-31 14:30 UTC
**Strategy:** mean_reversion | **Trust:** 48 | **Arena Score:** 55.1
**Grade:** D | **P&L:** -$1.80 | **R-Multiple:** -0.9R
**Duration:** 45 min | **Exit:** sl_hit

## Context at Entry
- Regime: RANGING | ATR(14): $28.50 | RSI: 62
- Signal score: 58 | Volume: 0.8x average
- SL distance: 0.6 ATR | TP distance: 1.8 ATR
- Higher TF (1h): LONG (opposing)
- Competing proposals: trend_momentum LONG (arena 62.3), breakout LONG (arena 48.1)
- Portfolio: 1 other position (BTCUSD LONG)
- Daily DD at entry: 1.8% of 20%

## Claude Analysis
- **Verdict:** COUNTER_TREND_FAILURE
- **What worked:** Entry near Bollinger upper band was technically valid
- **What failed:** Shorted against a 1h uptrend — mean reversion into a trend is low-probability
- **Edge signal:** Mean reversion SHORT only works when higher TF is also ranging or bearish
- **Improvement:** Add higher TF direction filter — skip shorts when 1h is bullish
- **Confidence:** 8/10

## Raw Data
- Entry: $2,050.00 | Exit: $2,075.50 | SL: $2,090.00 | TP: $1,980.00
- Position size: 0.1 | Risk: $4.00 | Contract size: 1
- Streak before: -1 | Streak after: -2
- Trust before: 51 | Trust after: 46
```

#### Telegram Summary (from report)

```
❌ #42 ETHUSD SHORT -$1.80 (D) — COUNTER_TREND_FAILURE
→ Skip mean reversion shorts when 1h is bullish
```

#### Weekly Edge Analysis (Sonnet output, saved to disk)

```markdown
# Edge Analysis — Week 2026-W13

**Period:** 2026-03-24 to 2026-03-31
**Trades analyzed:** 28 | **Model:** Sonnet | **Cost:** $0.030

## Edges Found

### Edge 1: RSI < 40 + EMA Alignment in TRENDING regime
- Strategy: trend_momentum | WR: 78% (14/18) | Avg R: +1.4R
- Action: Trust this pattern. Consider widening TP when present.

### Edge 2 (ANTI-EDGE): Mean Reversion against higher TF trend
- WR: 22% (2/9) | Avg R: -0.8R
- Action: Add higher TF direction check. Skip when opposing.

## Recurring Failures
1. SL too tight in VOLATILE regime — 5 trades hit within 0.3 ATR
2. Diversity bonus inflating weak signals — 3 trades with signal < 55
```

### 7.6 Claude Prompts

#### Haiku System Prompt (trade reports, ~300 tokens)

```
You are a trading post-mortem analyst. Given a closed trade's pre-computed data,
produce a structured JSON analysis. Be specific about what signal or condition
caused success or failure. Identify one repeatable edge or anti-pattern.

Output ONLY valid JSON with these exact keys:
- verdict: one of CLEAN_WIN, TREND_CONTINUATION, COUNTER_TREND_FAILURE,
  NOISE_STOPPED, SL_TOO_TIGHT, REGIME_MISMATCH, GOOD_ENTRY_EARLY_EXIT,
  DIVERSITY_INFLATION, EDGE_TRADE, RANDOM_LOSS
- what_worked: 1 sentence, specific (name indicators/conditions)
- what_failed: 1 sentence, specific (name what went wrong)
- edge_signal: the condition pattern that led to this outcome
- improvement: 1 concrete actionable change
- confidence: 1-10 how certain you are about the verdict
```

#### Sonnet System Prompt (weekly analysis, ~400 tokens)

```
You are a quantitative trading researcher. Given a week's pre-computed trade
summary (NOT raw trades — already aggregated), identify:

1. Repeatable edges: conditions that consistently lead to profitable trades.
   Rank by sample size and win rate. Name exact indicators, regimes, strategies.
2. Anti-patterns: conditions that consistently lose. Same specificity.
3. Recurring failures: common themes in what_failed across trades.
4. Actionable recommendations: specific config or code changes.

Format as markdown. Be concise. Focus on statistical significance —
patterns with 5+ trades are interesting, 10+ are actionable.
```

### 7.7 Module Design: `engine/src/notas_lave/learning/trade_autopsy.py`

#### Key Functions

| Function | Purpose | Claude? |
|----------|---------|---------|
| `gather_trade_context(event)` | Read TradeLog, leaderboard, risk → dict | No |
| `should_generate_report(ctx)` | Skip grade C, <60s, duplicates | No |
| `build_prompt(ctx)` | Dict → ~400 token prompt string | No |
| `call_claude_haiku(prompt)` | Haiku API call, 512 max tokens | Yes (Haiku) |
| `save_report(id, ctx, analysis)` | Write markdown to disk | No |
| `format_telegram_summary(ctx, analysis)` | 2-line summary | No |
| `handle_trade_closed(event)` | Orchestrator (async entry point) | — |
| `compile_weekly_summary(dir, week)` | Read all reports → 2,000 token summary | No |
| `analyze_edges(summary)` | Sonnet API call, 1500 max tokens | Yes (Sonnet) |

#### Config Additions (`config.py`)

```python
autopsy_enabled: bool = True          # AUTOPSY_ENABLED
autopsy_model: str = "claude-haiku-4-5-20251001"  # AUTOPSY_MODEL
autopsy_max_tokens: int = 512         # AUTOPSY_MAX_TOKENS
edge_analysis_model: str = "claude-sonnet-4-6"     # EDGE_ANALYSIS_MODEL
edge_analysis_max_tokens: int = 1500  # EDGE_ANALYSIS_MAX_TOKENS
```

#### API Endpoints (add to `learning_routes.py`)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/learning/reports?limit=20` | List recent reports (metadata only) |
| `GET /api/learning/reports/{trade_id}` | Full report content |
| `GET /api/learning/edge-analysis?week=2026-W13` | Weekly edge analysis |
| `POST /api/learning/analyze-edges` | Trigger on-demand edge analysis |

#### Fallback

If no Claude API key: fall back to existing `grade_and_learn()` output. Save simpler report with rule-based lesson only (no Claude analysis section). Weekly edge analysis skips.

---

## Implementation Plan

### Model & Effort Reference

When implementing from this document, use these models and effort levels:

| Task Type | Claude Code Model | Effort | Rationale |
|-----------|------------------|--------|-----------|
| Writing skill files (markdown) | **Sonnet** | Normal | Template work, no deep reasoning |
| Writing Python modules | **Sonnet** | Normal | Standard code, patterns exist in codebase |
| Writing tests | **Sonnet** | Normal | Follow existing test patterns |
| Debugging API integration | **Sonnet** | Normal | Read errors, fix code |
| Architecture decisions | **Opus** | Normal | Only when stuck on design tradeoffs |
| Code review before PR | **Sonnet** | Normal | Check quality, no deep analysis |

**Default: Sonnet for everything.** Only escalate to Opus if implementation hits a design ambiguity not covered in this doc.

### Token-Saving Instructions for Implementation Sessions

```
IMPORTANT FOR IMPLEMENTING SESSIONS:

1. Read this design doc ONCE at start. Don't re-read sections repeatedly.
2. Use Sonnet (not Opus) for all implementation work.
3. Use the Explore agent (not manual grep chains) for finding code patterns.
4. Don't ask clarifying questions covered in this doc — it's comprehensive.
5. Implement in order. Each phase builds on the previous.
6. Run tests after each step, not at the end.
7. Keep PRs small — one phase per PR.
8. Bump version in pyproject.toml per PR.
9. Update CHANGELOG.md per PR.
```

---

### Phase 1: Trade Autopsy Core — `trade_autopsy.py`

**Model:** Sonnet | **Effort:** Normal | **PR:** 1 PR, bump to v2.0.17
**Estimated tokens:** ~50K (reading existing patterns + writing new module)

#### Step 1.1: Create the module

**File:** `engine/src/notas_lave/learning/trade_autopsy.py`

Implement these functions (pure Python, no Claude calls yet):
- `gather_trade_context(event: TradeClosed) -> dict` — reads TradeLog, leaderboard state, risk state from in-memory objects. Pattern: follow how `close_trade()` in `lab.py:971-1135` accesses these.
- `should_generate_report(context: dict) -> bool` — skip grade C, duration < 60s, duplicate symbol within 5 min.
- `build_prompt(context: dict) -> str` — convert dict to compact prompt string (~400 tokens).
- `save_report(trade_id: int, context: dict, analysis: dict) -> Path` — write markdown to `data/trade_reports/YYYY-MM/trade_{id}_{symbol}_{direction}_{date}.md`.
- `format_telegram_summary(context: dict, analysis: dict) -> str` — 2 lines, < 200 chars each.

**Key patterns to follow:**
- Client init: copy from `claude_engine/decision.py:206-216`
- Token tracking: copy from `claude_engine/decision.py:228-239`
- Telegram sending: use `alerts/telegram.py:send_telegram()`

#### Step 1.2: Add Claude integration

Add to `trade_autopsy.py`:
- `call_claude_haiku(system_prompt: str, user_prompt: str) -> dict` — call Haiku, parse JSON, track tokens. Use `autopsy_model` and `autopsy_max_tokens` from config. Fallback to `grade_and_learn()` if no API key.

Add to `config.py`:
- `autopsy_enabled`, `autopsy_model`, `autopsy_max_tokens` fields.

#### Step 1.3: Wire event bus

In `engine/run.py`, add:
```python
from notas_lave.learning.trade_autopsy import handle_trade_closed
bus.subscribe(TradeClosed, handle_trade_closed, FailurePolicy.LOG_AND_CONTINUE)
```

`handle_trade_closed` is the async orchestrator: gather → should_generate → build → call_haiku → save → telegram → track_tokens.

#### Step 1.4: Tests

**File:** `tests/unit/test_trade_autopsy.py`

| Test | What |
|------|------|
| `test_gather_context_all_fields` | Mock TradeLog + leaderboard, verify all dict fields present |
| `test_should_skip_grade_c` | Grade C → False |
| `test_should_skip_short_duration` | 30s → False |
| `test_should_skip_duplicate` | Same symbol within 5 min → False |
| `test_build_prompt_compact` | Assert < 500 tokens (count words * 1.3) |
| `test_save_report_file_created` | Check file exists, correct name pattern, valid markdown |
| `test_telegram_summary_length` | Assert < 200 chars per line |
| `test_fallback_no_api_key` | No key → saves rule-based report, no Claude call |
| `test_handle_trade_closed_e2e` | Mock everything, verify full flow |

---

### Phase 2: Weekly Edge Analysis

**Model:** Sonnet | **Effort:** Normal | **PR:** 1 PR, bump to v2.0.18
**Estimated tokens:** ~30K

#### Step 2.1: Summary compiler

Add to `trade_autopsy.py`:
- `compile_weekly_summary(reports_dir: Path, week: str) -> str` — read all markdown reports for the week, extract verdict/edge_signal/what_failed, aggregate by strategy/regime/hour. Output: ~2,000 token summary string. **Pure Python, no Claude.**

#### Step 2.2: Edge analyzer

Add to `trade_autopsy.py`:
- `analyze_edges(summary: str) -> str` — call Sonnet with the compressed summary. Use `edge_analysis_model` and `edge_analysis_max_tokens` from config. Save result to `data/trade_reports/summaries/week_{week}.md`.

Add to `config.py`:
- `edge_analysis_model`, `edge_analysis_max_tokens` fields.

#### Step 2.3: API endpoints

Add to `learning_routes.py`:
- `GET /api/learning/reports?limit=20` — list report metadata (read filenames, parse header)
- `GET /api/learning/reports/{trade_id}` — read full report from disk
- `GET /api/learning/edge-analysis?week=2026-W13` — read weekly analysis from disk
- `POST /api/learning/analyze-edges` — trigger on-demand edge analysis

#### Step 2.4: Tests

| Test | What |
|------|------|
| `test_compile_weekly_summary` | 10 fake report files → verify aggregation, < 2500 tokens |
| `test_analyze_edges_output` | Mock Sonnet response → verify markdown saved |
| `test_reports_list_endpoint` | Create 3 files → GET returns 3 entries |
| `test_report_detail_endpoint` | Create file → GET returns content |

---

### Phase 3: Copilot Skill (`/copilot`)

**Model:** Sonnet | **Effort:** Normal | **PR:** 1 PR, bump to v2.0.19
**Estimated tokens:** ~40K

#### Step 3.1: Create skill file

**File:** `.claude/skills/copilot.md`

This is a markdown file that defines the Claude Code skill. It contains:
- System prompt (trading desk analyst persona from Panel 1)
- Sub-command routing logic
- API endpoint reference (compact version of Panel 3)
- Output templates (from Panel 4)
- Decision framework reference (from Panel 1)
- Risk check reference (from Panel 5)
- Bug detection heuristics (from Panel 6)

**Sub-commands:**

| Command | Description | Endpoints Hit |
|---------|-------------|---------------|
| `/copilot` or `/copilot status` | Full status summary | Tier 1 (5 calls) |
| `/copilot analyze {symbol}` | Deep proposal analysis with YES/NO/WAIT | 8 calls |
| `/copilot brief` | Morning brief format | All Tier 1 + 2 (8 calls) |
| `/copilot review` | Performance review | 6 calls |
| `/copilot risk` | Portfolio risk assessment | 4 calls |
| `/copilot leaderboard` | Strategy comparison | 3 calls |
| `/copilot reports` | Show recent trade autopsy reports | 2 calls |
| `/copilot edges` | Show latest edge analysis | 1 call |
| **Debugging commands** | | |
| `/copilot health` | Full 6-step health check (Panel 6.1) | 6 calls sequential |
| `/copilot bugs` | Run bug detection heuristics (Panel 6/3.3) | 5 calls |
| `/copilot debug {topic}` | Deep dive: `execution`, `positions`, `proposals`, `data`, `errors` | varies |
| `/copilot why-no-trades` | Diagnose why nothing is executing (Panel 6.2 patterns) | 5 calls |
| `/copilot verify` | Broker vs journal reconciliation check | 3 calls |
| `/copilot fix {issue}` | Guided fix: `sync`, `force-close {sym}`, `reseed-trust`, `set-pace {p}` | 1 action call |

**Debugging sub-command details:**

`/copilot health` runs the 6-step diagnostic sequence from Panel 6.1:
1. `GET /health` → engine alive?
2. `GET /api/broker/status` → broker connected? balance > 0?
3. `GET /api/lab/verify` → broker/journal match?
4. `GET /api/lab/status` → running? errors?
5. `GET /api/lab/debug/execution` → sizing valid? products loaded?
6. `GET /api/system/health` → data freshness? errors last hour?
Outputs the diagnostic report format from Panel 6.3.

`/copilot debug execution` deep dives into why trades aren't executing:
- Checks `GET /api/lab/debug/execution` for sizing failures per instrument
- Checks `GET /api/broker/status` for margin availability
- Checks `GET /api/lab/proposals` for block reasons
- Cross-references with Panel 6.2 failure patterns

`/copilot debug positions` investigates position mismatches:
- `GET /api/lab/verify` for broker vs journal diff
- `GET /api/lab/positions` for journal view
- `GET /api/broker/status` for broker view
- Identifies orphans and recommends sync/force-close

`/copilot debug proposals` investigates why proposals are BLOCKED or missing:
- `GET /api/lab/proposals` with block_reason analysis
- `GET /api/lab/arena/leaderboard` for trust score check (all suspended?)
- `GET /api/broker/status` for balance check
- `GET /api/lab/pace` for pace configuration

`/copilot debug data` checks market data health:
- `GET /api/system/health` → market_data component, last_success timestamps
- `GET /api/prices` → which instruments have stale prices
- Flags any source with last_success > 5 minutes ago

`/copilot debug errors` investigates engine errors:
- `GET /api/lab/status` → consecutive_errors, exec_log
- Maps to known failure patterns from Panel 6.2
- Suggests specific fixes based on error content

`/copilot fix` performs guided remediation actions (each requires user confirmation):
- `fix sync` → `POST /api/lab/sync-positions`
- `fix force-close SOLUSD` → `POST /api/lab/force-close/SOLUSD`
- `fix reseed-trust` → `POST /api/backtest/arena/BTCUSD?seed_trust=true` (repeats for ETH, SOL)
- `fix set-pace conservative` → `POST /api/lab/pace/conservative`

**The skill uses `WebFetch`** to call `http://34.100.222.148:8000/api/*` endpoints. All analysis and debugging logic is in the skill prompt — Claude Code does the reasoning, no additional Claude API calls needed.

#### Step 3.2: Test manually

- Run `/copilot status` against live engine
- Run `/copilot analyze BTCUSD` with active proposals
- Run `/copilot bugs` and verify it catches known issues
- Run `/copilot reports` to view autopsy reports

---

### Phase 4: MCP Server (Optional, Future)

**Model:** Sonnet | **Effort:** Normal | **PR:** 1 PR, bump to v2.0.20
**Estimated tokens:** ~60K

**Only implement if Phase 3 skill proves too limited** (e.g., too many WebFetch calls, needs persistent state).

#### Step 4.1: MCP server module

**File:** `engine/src/notas_lave/mcp/server.py`

Wrap platform APIs as MCP tools. Each tool is a thin wrapper around an HTTP call to the engine:

| Tool | Type | Description |
|------|------|-------------|
| `get_status` | Read | Combined status (broker + risk + lab + positions) |
| `get_proposals` | Read | Active proposals with scoring |
| `get_positions` | Read | Enriched positions |
| `get_risk` | Read | Risk metrics + portfolio heat |
| `scan_instrument` | Read | Full confluence scan |
| `get_leaderboard` | Read | Trust scores sorted |
| `get_trades` | Read | Recent closed trades + summary |
| `get_reports` | Read | Trade autopsy reports |
| `get_edge_analysis` | Read | Latest edge findings |
| `run_health_check` | Computed | Full 6-step diagnostic |
| `analyze_proposal` | Computed | Decision tree YES/NO/WAIT |
| `execute_proposal` | Action | Execute ranked proposal (confirm) |
| `close_position` | Action | Close a position (confirm) |
| `set_pace` | Action | Change trading pace (confirm) |

#### Step 4.2: Register in Claude Code

Add MCP server config to `.claude/settings.json` or project settings.

#### Step 4.3: Tests

Standard MCP tool tests — mock HTTP responses, verify tool output format.

---

### Phase 5: Background Agent (Optional, Future)

**Model:** N/A (uses Haiku/Sonnet for reports only) | **Effort:** Normal | **PR:** 1 PR
**Estimated tokens:** ~50K

**Only implement after Phases 1-3 are proven and running.**

#### Components

1. **Poller** — async loop, polls Tier 1 endpoints every 60s
2. **Alert Engine** — evaluates thresholds from Panel 4.3, deduplicates (5-min cooldown per alert type)
3. **Morning Brief** — scheduled daily at 08:00 UTC, sends to Telegram
4. **Weekly Review** — scheduled Sundays, triggers edge analysis + sends summary

**Architecture:**
```
Background Agent (Python, systemd on VM)
  ├── Poller (async, configurable cadence)
  ├── Alert Engine (threshold evaluation + cooldown tracking)
  ├── Telegram Notifier (reuses existing send_telegram())
  └── Config (env vars: AGENT_ENABLED, AGENT_POLL_INTERVAL, etc.)
```

---

### Phase Summary

| Phase | What | Model | Effort | Monthly Runtime Cost | PR |
|-------|------|-------|--------|---------------------|-----|
| **1** | Trade Autopsy Core | Sonnet (impl) + Haiku (runtime) | Normal | $0.90 at 10 trades/day | v2.0.17 |
| **2** | Weekly Edge Analysis | Sonnet (impl) + Sonnet (runtime) | Normal | $0.12 (4 analyses) | v2.0.18 |
| **3** | Copilot Skill | Sonnet (impl) | Normal | $0 (uses Claude Code session) | v2.0.19 |
| **4** | MCP Server (optional) | Sonnet (impl) | Normal | $0 (wraps existing APIs) | v2.0.20 |
| **5** | Background Agent (optional) | Sonnet (impl) | Normal | same as Phase 1+2 | future |
| | **Total runtime** | | | **~$1.02/month** at 10 trades/day | |

### Implementation Order Rationale

1. **Phase 1 first** because it generates data (reports). Everything else consumes this data.
2. **Phase 2 second** because edge analysis needs accumulated reports from Phase 1.
3. **Phase 3 third** because the skill can now show reports AND edge findings.
4. **Phases 4-5 optional** — only if the skill proves too limiting or you want proactive alerts.

---

## Appendix A: Key Platform Constants

| Constant | Value | Source |
|----------|-------|--------|
| Arena weights | 30/25/15/10/20 | `lab.py:402-408` |
| Trust win boost | +3.0 | `leaderboard.py:26` |
| Trust loss penalty | -5.0 | `leaderboard.py:27` |
| Trust suspend threshold | < 20 | `leaderboard.py:30` |
| Trust start | 50 | `leaderboard.py` StrategyRecord default |
| Signal threshold (proven) | 55 | `leaderboard.py:34` |
| Signal threshold (standard) | 65 | `leaderboard.py:35` |
| Signal threshold (caution) | 75 | `leaderboard.py:36` |
| Loss streak throttle | -3 (halves risk) | `lab.py:576-580` |
| Reconciliation safety | 2 consecutive misses | `lab.py:726-731` |
| Learning cooldown | 7 days + 10 trades | `recommendations.py:86-133` |
| Blacklist threshold | 30 trades, < 35% WR | `recommendations.py:202-251` |
| Weight adjustment min trades | 50 | `recommendations.py:274-337` |
| Trade weight half-life | 30 days | `analyzer.py:172-212` |
| Personal DD limits | 20% daily, 50% total | `config.py:75-77` |
| Personal risk/trade | 10% | `config.py:75` |
| Prop DD limits | 5% daily, 10% total | `config.py:64-65` |
| Prop consistency | 45% | `config.py:66` |
| Pace presets | conservative/balanced/aggressive | `lab.py:63-82` |

## Appendix B: Existing Code Patterns to Follow

| Pattern | Where | What to Copy |
|---------|-------|-------------|
| Claude API client init | `claude_engine/decision.py:206-216` | Vertex vs direct, config-driven |
| Token tracking | `claude_engine/decision.py:228-239` | `log_token_usage()` call |
| Event bus subscription | `run.py:95-96` | `bus.subscribe(TradeClosed, handler, LOG_AND_CONTINUE)` |
| Telegram sending | `alerts/telegram.py:61-79` | `send_telegram(message)` |
| Trade grading | `learning/trade_grader.py:163-209` | `grade_and_learn(trade_data)` |
| Fallback when no Claude | `claude_engine/decision.py:197-202` | `_fallback_decision()` pattern |
| Config fields | `config.py:29-38` | `Field(default=..., alias="ENV_VAR")` |
| API route | `learning_routes.py:21-26` | `@router.get("/path")` |

## Appendix C: Model Pricing Reference

| Model | Input $/1M | Output $/1M | Use For |
|-------|-----------|------------|---------|
| `claude-haiku-4-5-20251001` | $0.80 | $4.00 | Trade reports (per-trade, high volume) |
| `claude-sonnet-4-6` | $3.00 | $15.00 | Edge analysis (weekly, low volume) |
| `claude-opus-4-6` | $15.00 | $75.00 | **Never used in runtime.** Only for Claude Code implementation sessions when stuck. |

---

*This document is self-contained. Hand it to a new Claude Code session with the instruction "Implement Phase N" and it has everything needed: architecture, code patterns, file locations, model selections, and test specs.*
