# Notas Lave — Dual Engine Architecture Plan

**Status:** PLAN — awaiting approval before implementation
**Created:** 2026-03-22 (Session 8)
**Author:** 5-Expert Creative Team

---

## The Vision

> "Notas Lave" = "Not a Slave" — the system shouldn't limit itself.
> Claude IS the trader. The human is the overseer. No human in the trading loop.

**Claude is the BRAIN. Code is the BODY.**

```
                         CLAUDE (The Brain)
                    /          |           \
                   /           |            \
        DECIDES trades    DESIGNS experiments   EVOLVES strategies
        (Production)         (Lab)            (Weekly Review)
              |                |                    |
              v                v                    v
    PRODUCTION ENGINE     LAB ENGINE          STRATEGY EVOLVER
    (careful trades)    (aggressive learning)  (finds new edges)
              \                |                   /
               \               |                  /
                SHARED LAYER (strategies, data, ML, features)
```

**Zero human in the loop.** Claude makes every trade decision. ML provides the data. Strategies provide the signals. The human only watches Telegram and sets the initial boundaries.

---

## Who Does What

### Claude's 3 Roles

| Role | Where | Frequency | What Claude Does |
|------|-------|-----------|-----------------|
| **Trader** | Production | Every qualifying signal | Reviews ML prediction + strategy signals. Decides: TRADE or SKIP. Sets entry/SL/TP. |
| **Scientist** | Lab | Daily review | Designs experiments. Analyzes lab results. Asks: "What should we test next?" |
| **Architect** | Evolution | Weekly | Reviews all data. Proposes new strategies. Promotes lab discoveries to production. Adjusts weights/blacklists. |

### ML's Role (the fast layer)

Claude is smart but slow (2-5s per call, costs money). ML is dumb but fast (1ms, free).

```
Signal fires → ML scores it instantly (P(WIN), expected R-multiple)
                    |
                    v
            Score > threshold? ─── No → Skip (no Claude call needed)
                    |
                   Yes
                    v
            Claude reviews the setup ─── SKIP → Log why, learn from it
                    |
                   TRADE
                    v
              Execute on exchange
```

**ML is the filter. Claude is the final judge.** This means:
- Lab: ML-only decisions (fast, 100 trades/day, no Claude cost)
- Production: ML filters → Claude decides (1-6 trades/day, Claude reviews each one)

### What the Human Does (minimal)

- Sets initial config (.env: TRADING_MODE, BROKER, balance)
- Watches Telegram for alerts
- Adds money to exchange accounts
- That's it. No trade approvals. No strategy decisions. No manual intervention.

---

## Architecture

### The Flow (Production)

```
Every 60 seconds:
  1. Fetch candles for all instruments
  2. Run 14 strategies → signals
  3. Compute confluence score
  4. Extract 50+ features from signal context
  5. ML predicts: P(WIN) = 0.67, expected R = 1.8x
  6. If P(WIN) >= 0.55 AND score >= 5.0:
       → Send to Claude for final decision
       → Claude sees: features, ML prediction, recent trades, regime
       → Claude returns: TRADE (with reasoning) or SKIP (with why)
  7. If Claude says TRADE:
       → validate_trade() risk check
       → Execute on exchange
       → Log everything
  8. When trade closes:
       → Claude analyzes: grade, lesson, strategy adjustment
       → Features + outcome stored in feature store
       → ML retrains weekly on new data
```

### The Flow (Lab)

```
Every 30 seconds (faster scanning):
  1. Fetch candles (shared with production)
  2. Run ALL strategies (no blacklist)
  3. Compute confluence score (lower threshold: 3.0)
  4. Extract features
  5. ML predicts P(WIN)
  6. If ANY signal qualifies → TRADE immediately (no Claude, no risk check)
  7. Log everything to lab.db
  8. When trade closes:
       → Auto-grade (rule-based, not Claude — too expensive at 100/day)
       → Features + outcome → feature store
  9. Daily: Claude reviews lab results as Scientist
       → "RSI Divergence had 72% WR during London session — test with tighter SL"
       → "Momentum Breakout failed in QUIET regime — add to blacklist"
       → Designs next day's experiments
```

### The Flow (Weekly Evolution)

```
Every Sunday:
  1. Claude reviews ALL data:
     - Production trades (small sample, high quality)
     - Lab trades (large sample, noisy)
     - ML model accuracy trends
     - Feature importance from XGBoost
  2. Claude as Architect decides:
     - Promote lab findings → production (e.g., "RSI period=9 beats period=7")
     - Adjust production weights/blacklists
     - Propose new strategy combinations to test in lab
     - Kill strategies with sustained decay
  3. Retrain ML models on latest data
  4. Update production config
  5. Send weekly report to Telegram
```

---

## What Changes vs Current System

| Aspect | Current | New |
|--------|---------|-----|
| Trade decisions | Confluence score threshold | ML filter → Claude final decision |
| Claude's role | Post-trade analysis only | Pre-trade decision + post-trade analysis + weekly evolution |
| Human role | Overseer who might intervene | Sets config once, then watches |
| Engines | 1 (production) | 2 (production + lab) |
| Trades/day | 1-6 (restricted) | Prod: 1-6, Lab: 50-100 |
| Learning data | Production trades only (slow) | Lab trades primarily (10-100x faster) |
| ML | None (Claude only) | XGBoost features + Claude judgment |
| Strategy discovery | Manual | Lab experiments → Claude reviews → promote |

---

## New Components to Build

### Layer 1: Feature Store (THE KEY PIECE)

```
engine/src/ml/
    feature_store.py       # Extract 50+ features per signal
    feature_registry.py    # Define, version, and manage features
```

Features extracted per signal:
```python
# Price Action (from candles)
atr_14, atr_ratio, body_ratio, volume_ratio, price_vs_ema50

# Strategy Signals (from all 14 strategies)
rsi_value, bb_position, stoch_k, macd_histogram, num_agreeing, composite_score

# Context
hour_utc, day_of_week, regime, spread_ratio, minutes_to_news

# Historical Performance
strategy_wr_50, strategy_wr_regime, instrument_wr_50, consecutive_losses

# Target (filled after trade closes)
outcome (WIN/LOSS), pnl_r_multiple, mfe_r_multiple, mae_r_multiple
```

### Layer 2: ML Models

```
engine/src/ml/
    xgboost_model.py       # Trade outcome predictor
    model_store.py          # Save/load/version models
```

- **XGBoost Classifier:** P(WIN) from 50+ features. Train on lab data. Retrain weekly.
- Starts simple. Add LSTM/RL in Phase 4 only after XGBoost baseline is solid.

### Layer 3: Claude Decision Engine (upgraded)

```
engine/src/claude_engine/
    trader_brain.py        # Claude makes trade decisions (not just analysis)
    lab_scientist.py       # Claude designs lab experiments
    weekly_architect.py    # Claude does weekly evolution
```

**trader_brain.py** — Claude as Production Trader:
```python
TRADER_PROMPT = """You are the autonomous trader for Notas Lave.

SETUP:
{symbol} {direction} | Score: {score}/10 | ML P(WIN): {p_win:.0%}
Entry: {entry} | SL: {sl} | TP: {tp} | R:R: {rr:.1f}
Regime: {regime} | Hour: {hour} UTC

ML FEATURES:
{top_features}

RECENT TRADES ON {symbol}:
{recent_trades}

DECIDE: TRADE or SKIP
If TRADE: confirm entry/SL/TP or adjust.
If SKIP: explain why in one sentence.

Respond as JSON: {"action": "TRADE|SKIP", "reasoning": "...", "adjustments": {}}
"""
```

**lab_scientist.py** — Claude as Lab Scientist:
```python
LAB_REVIEW_PROMPT = """You are the research scientist for Notas Lave Lab.

TODAY'S LAB RESULTS:
{lab_summary}

EXPERIMENTS RUNNING:
{active_experiments}

ML MODEL ACCURACY: {model_accuracy}
TOP FEATURES (by importance): {feature_importance}

TASKS:
1. What patterns do you see in today's lab trades?
2. What should we test tomorrow? (new params, new combinations, new filters)
3. Any strategies showing decay? Any showing unexpected strength?
4. Recommend 1-3 specific experiments for the lab.

Respond as JSON with experiments list.
"""
```

### Layer 4: Lab Engine

```
engine/src/lab/
    lab_trader.py          # Unrestricted autonomous trader (ML-only decisions)
    lab_risk.py            # Log-only risk manager (no blocks)
    lab_config.py          # Lab-specific settings
engine/lab_runner.py       # Entry point for lab engine
```

### Layer 5: Promotion Pipeline

```
engine/src/lab/
    promotion.py           # Lab → Production recommendation pipeline
    experiment.py          # Define structured experiments
```

---

## Implementation Phases

### Phase 1: Lab Foundation + Claude as Trader
1. Create `LabRiskManager` (permissive, log-only)
2. Parameterize database path (separate lab.db)
3. Build `LabTrader` (unrestricted, ML-only decisions)
4. Upgrade Claude decision engine: `trader_brain.py` (Claude decides trades in production)
5. Create `lab_runner.py` entry point
6. Remove human from production loop (Claude = final authority)

**Deliverable:** Two engines running. Claude makes production trade decisions. Lab trades aggressively on demo.

### Phase 2: Feature Store + XGBoost
1. Build feature extraction (50+ features per signal)
2. Create feature store table in both DBs
3. Build XGBoost trade predictor (train on lab data)
4. Wire ML predictions into production flow (ML filters → Claude judges)
5. Build `lab_scientist.py` (Claude reviews lab daily)

**Deliverable:** ML predicts P(WIN). Claude uses predictions in decisions. Lab generates training data.

### Phase 3: Strategy Evolution
1. Build `weekly_architect.py` (Claude weekly evolution)
2. Build promotion pipeline (Lab discoveries → Production)
3. Build experiment system (structured A/B tests in lab)
4. Build decay detection (strategy WR trending down)
5. Auto-generate weekly Telegram report with Claude's analysis

**Deliverable:** Self-evolving system. Lab discovers → Claude reviews → Production adopts.

### Phase 4: Advanced ML
1. LSTM for price direction prediction
2. PPO (Reinforcement Learning) for dynamic position sizing
3. Multi-model ensemble (XGBoost + LSTM vote)
4. Pattern recognition from candle sequences

**Deliverable:** Multiple ML models contribute to trade decisions alongside Claude.

---

## How to Run

```bash
# Terminal 1: Production Engine (Claude decides trades)
cd engine && ../.venv/bin/python run.py

# Terminal 2: Lab Engine (ML decides, trades aggressively)
cd engine && ../.venv/bin/python lab_runner.py

# Terminal 3: Dashboard
cd dashboard && npm run dev
```

Both engines share market data. Separate DBs. Lab generates data. Production uses it.

---

## Cost Estimate

| Component | Cost/day | Notes |
|-----------|----------|-------|
| Claude (Production) | ~$0.50 | 5-10 trade reviews/day @ $0.05-0.10 each |
| Claude (Lab Scientist) | ~$0.20 | 1 daily review |
| Claude (Weekly Architect) | ~$0.50/week | 1 deep weekly review |
| Binance Demo | Free | Demo account, no real money |
| Twelve Data | Free (800/day) | Shared between engines |
| ML Training | Free | Runs locally, scikit-learn/XGBoost |
| **Total** | **~$1/day** | Much less than a losing trade |

---

## Success Metrics

| Metric | Target | When |
|--------|--------|------|
| Lab trades/day | 50+ | Week 1 |
| Feature store rows | 5,000+ | Month 1 |
| XGBoost accuracy | >55% on held-out data | Month 1 |
| Claude decision quality | >60% WR on approved trades | Month 2 |
| Lab → Prod promotions | 1+ improvement/month | Month 2 |
| Production WR | >55% sustained | Month 3 |
| Full autonomy | 0 human interventions/week | Month 1 |

---

## The "Not a Slave" Principle

The system is NOT constrained to only do what it's told:
- **Lab proposes experiments** Claude didn't ask for
- **ML finds features** no human would think to check
- **Claude suggests strategies** outside the original 14
- **The system questions itself** — "Is this strategy still working?"

Every week, the system should be DIFFERENT from the week before. Better. Evolved. Not a slave to its initial design.
