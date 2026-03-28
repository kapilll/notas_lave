# Learning System

> Last verified against code: 2026-03-28

## Overview

The EVOLVE system: analyze trades → generate recommendations → adjust weights/blacklists → repeat.

```
Closed Trades (TradeLog)
  |
  v
Analyzer ──→ Multi-dimensional breakdowns
  |            (strategy×instrument, strategy×regime, by-hour, by-score)
  v
Recommendations ──→ Blacklist suggestions, weight adjustments
  |                   score threshold, trading hours
  v
Auto-apply (if cooldown elapsed) ──→ Update REGIME_WEIGHTS, BLACKLIST
  |
  v
Confluence Scorer (uses updated weights for next trade)
```

**CRITICAL:** Learning engine reads from `TradeLog` (SQLAlchemy). Lab writes to `EventStore`. They're disconnected. The learning engine currently learns from NOTHING.

## Components

### Analyzer (`learning/analyzer.py`)
Multi-dimensional trade analysis:
- `analyze_strategy_by_instrument()` — which strategy works on which symbol
- `analyze_strategy_by_regime()` — which strategy works in which market condition
- `analyze_by_hour()` — time-of-day patterns
- `analyze_by_score_bucket()` — optimal confluence score threshold
- `analyze_exit_reasons()` — TP/SL/timeout breakdown
- `analyze_strategy_combinations()` — best strategy pairs

**Exponential decay weighting (ML-13):**
```python
weight = exp(-0.693 * age_days / 30.0)  # Half-life = 30 days
# 30 days ago = 50%, 60 days = 25%, 90 days = 12.5%
```
Regime-matching trades get 1.5x boost (ML-29).

### Recommendations (`learning/recommendations.py`)
Turns analysis into actionable changes:
- `recommend_strategy_blacklist()` — strategies to disable per instrument
- `recommend_weight_adjustments()` — new regime weights
- `recommend_score_threshold()` — optimal min score
- `recommend_trading_hours()` — best/worst hours
- `recommend_strategy_rehabilitation()` — blacklisted strategies that may deserve re-testing

**Graduated thresholds (ML-30):**
- Blacklist: 30+ trades with < 35% WR
- Weight tuning: 50+ trades needed

**Adjustment cooldown (ML-20):**
- Minimum 7 days between adjustments
- Minimum 10 new trades between adjustments
- Performance degradation tracking (ML-27)

### Optimizer (`learning/optimizer.py`)
Walk-forward parameter tuning:
1. Define parameter grid per strategy (2-3 params each)
2. Split data 70% train / 30% validate
3. Find best params on training data
4. Verify on validation data (PF > 1.0 required)
5. Save to `optimizer_results.json`
6. Strategy registry loads optimized params on next restart

**Multiple comparison correction (QR-17):** Penalizes PF by `ln(n_tested) / (n_tested + 10)`.

### Accuracy Tracker (`learning/accuracy.py`)
Measures prediction quality separately from trade P&L:
- **Direction accuracy:** Did price move in predicted direction?
- **Target accuracy:** Did TP get hit before SL?
- **Score calibration:** Do higher-score signals have higher accuracy?
- **Rolling accuracy:** Is prediction quality improving over time?

### A/B Testing (`learning/ab_testing.py`)
Shadow-mode parameter comparison:
- Variant A (current) trades live, Variant B logged only
- Statistical significance via two-proportion z-test (ML-26)
- Minimum 5 samples per variant for any conclusion

## Strategy Blacklists

Static blacklists in `backtester/engine.py`:
```python
INSTRUMENT_STRATEGY_BLACKLIST = {
    "BTCUSD": {"break_retest", "fibonacci_golden_zone", "vwap_scalping", ...},
    "ETHUSD": {"fibonacci_golden_zone", "camarilla_pivots", ...},
    ...
}
```

Dynamic blacklists added by learning engine, merged (not replaced) via `update_blacklist()`.
Persisted in `engine/data/learned_blacklists.json`.

## Regime Weights

```python
REGIME_WEIGHTS = {
    MarketRegime.TRENDING:  {"scalping": 0.20, "ict": 0.25, ...},
    MarketRegime.RANGING:   {"scalping": 0.30, "ict": 0.15, ...},
    MarketRegime.VOLATILE:  {"scalping": 0.15, "ict": 0.20, ...},
    MarketRegime.QUIET:     {"scalping": 0.35, "ict": 0.12, ...},
}
```

Updated by learning engine via `update_regime_weights()`.
Persisted in `engine/data/learned_state.json`.

## Rules

- **Minimum sample sizes are not negotiable.** 30 trades for blacklists, 50 for weights.
- **Adjustment cooldown (7 days + 10 trades)** prevents overfitting churn.
- **Weight bounds (0.05–0.50)** prevent extreme allocations.
- **Blacklists are MERGED, not replaced** — static blacklists contain catastrophic losers.
- **Max 3 blacklists per week** — prevents the learning engine from disabling everything.
- **Use `safe_load_json` / `safe_save_json`** for all JSON state files.
- **Analyze production-quality trades only** (score >= 50) — don't bias recommendations with low-quality lab data.
