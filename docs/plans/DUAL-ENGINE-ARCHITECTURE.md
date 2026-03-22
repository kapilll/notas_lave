# Notas Lave — Dual Engine Architecture Plan

**Status:** PLAN — awaiting approval before implementation
**Created:** 2026-03-22 (Session 8)
**Author:** 5-Expert Creative Team

---

## The Vision

> "Notas Lave" = "Not a Slave" — the system shouldn't limit itself.

**Two engines, one brain:**

```
                    SHARED LAYER
          (strategies, data, confluence, backtester)
                   /              \
                  /                \
    PRODUCTION ENGINE          LAB ENGINE
    (strict, real money)    (unrestricted, learning)
    - Risk gatekeeper        - No risk limits
    - 1-3 trades/day         - 50-100 trades/day
    - Proven strategies      - Wild experiments
    - Conservative sizing    - Aggressive exploration
    - Careful, precise       - Fast, curious
                  \                /
                   \              /
               FEATURE STORE + ML MODELS
              (XGBoost, pattern recognition)
                        |
                   RECOMMENDATIONS
        (Lab discoveries → Production adoption)
```

**The Lab's job:** Take 100 trades a day on demo money. Learn which strategies, parameters, time-of-day, and market conditions actually produce edge. Generate structured data that ML models can train on. Surface discoveries for Claude and the human to review.

**Production's job:** Trade carefully with proven setups. Only adopt strategies that the Lab has validated over 200+ trades with statistical significance.

---

## What Changes vs Current System

| Aspect | Current | New |
|--------|---------|-----|
| Engines | 1 (production) | 2 (production + lab) |
| Trades/day | 1-6 (restricted) | Production: 1-6, Lab: 50-100 |
| Risk rules | Always enforced | Production: enforced, Lab: disabled |
| Learning source | Production trades only | Primarily lab trades (10-100x more data) |
| ML | Claude analysis only | Claude + XGBoost + feature engineering |
| Strategy discovery | Manual | Automated (lab tests variations) |
| Database | 1 shared | 2 separate (prod + lab) |

---

## Architecture

### Layer 1: Shared Foundation (reuse as-is)

These modules work for BOTH engines without modification:

```
engine/src/strategies/          # All 14 strategies (stateless, pure functions)
engine/src/data/market_data.py  # Market data provider (shared cache)
engine/src/data/instruments.py  # Instrument specs
engine/src/data/models.py       # Candle, Signal, Direction enums
engine/src/data/economic_calendar.py  # News events
engine/src/confluence/scorer.py # Signal combination (separate state per engine)
engine/src/backtester/          # Backtester + Monte Carlo (parameterized)
engine/src/alerts/telegram.py   # Notifications (prefix with [PROD] or [LAB])
engine/src/log_config.py        # Structured logging
```

### Layer 2: Engine-Specific (one instance per engine)

Each engine gets its own instance of these:

```python
# Production Engine
prod_config = EngineConfig(mode="production", db_path="notas_lave.db")
prod_risk = RiskManager(mode="production")      # Full risk enforcement
prod_trader = PaperTrader(db=prod_db)            # Careful positions
prod_agent = AutonomousTrader(config=prod_config, risk=prod_risk, trader=prod_trader)

# Lab Engine
lab_config = EngineConfig(mode="lab", db_path="notas_lave_lab.db")
lab_risk = LabRiskManager()                      # Permissive (no blocks)
lab_trader = PaperTrader(db=lab_db)              # Aggressive positions
lab_agent = LabTrader(config=lab_config, risk=lab_risk, trader=lab_trader)
```

### Layer 3: ML & Feature Store (NEW)

```
engine/src/ml/
    feature_store.py      # Extract 50+ features per candle/signal
    feature_registry.py   # Define and version features
    xgboost_model.py      # Train/predict with gradient boosting
    pattern_detector.py   # Find recurring patterns in trade data
    strategy_evolver.py   # Generate and test strategy variations
    model_store.py        # Save/load trained models
```

### Layer 4: Lab → Production Pipeline (NEW)

```
engine/src/lab/
    lab_trader.py         # Unrestricted autonomous trader
    lab_risk.py           # Permissive risk manager (log-only, no blocks)
    lab_analyzer.py       # Analyze lab results, surface discoveries
    promotion.py          # Promote lab-validated strategies to production
    experiment.py         # Define and run structured experiments
```

---

## The Feature Store (The Brain)

This is the KEY new component. Instead of Claude analyzing each trade in prose, we extract structured features that ML can train on.

### Features extracted per signal/trade:

```python
# Price Action Features (from candles)
"atr_14": 45.2,                    # Average True Range
"atr_ratio": 1.3,                  # ATR14 / ATR50 (volatility regime)
"body_ratio_last_3": 0.72,         # Average body/range ratio
"upper_wick_ratio": 0.15,          # Rejection strength
"volume_ratio": 1.8,               # Volume vs 20-period average
"price_vs_ema50": 0.012,           # Distance from EMA50 (%)

# Strategy Signal Features
"rsi_value": 28.4,                 # Raw RSI at signal time
"bb_position": -0.85,              # Position within Bollinger Bands (-1 to +1)
"stoch_k": 15.2,                   # Stochastic %K
"num_strategies_agreeing": 4,      # Confluence count
"composite_score": 7.2,            # Weighted confluence score

# Context Features
"hour_utc": 14,                    # Time of day
"day_of_week": 2,                  # Tuesday
"regime": "TRENDING",              # Market regime
"spread_ratio": 0.03,              # Spread as % of SL distance
"minutes_to_next_news": 240,       # Distance to next high-impact event

# Historical Performance Features
"strategy_wr_last_50": 0.62,       # Strategy's recent win rate
"strategy_wr_this_regime": 0.71,   # Strategy's WR in current regime
"instrument_wr_last_50": 0.58,     # Instrument's recent WR
"consecutive_losses": 0,           # Current loss streak

# Target (what we're predicting)
"outcome": "WIN",                  # WIN / LOSS / BREAKEVEN
"pnl_r_multiple": 2.1,            # P&L as multiple of risk
"mfe_r_multiple": 2.8,            # Max favorable excursion / risk
"mae_r_multiple": -0.4,           # Max adverse excursion / risk
```

### How the Feature Store works:

```
Every signal (Lab + Prod) → Extract features → Store in feature_store table
                                                        |
                                        XGBoost trains on features + outcomes
                                                        |
                                        Model predicts: P(win), expected R-multiple
                                                        |
                            Production uses predictions to filter/size trades
```

---

## The Lab Trader

The Lab runs on Binance Demo with NO restrictions:

```python
class LabTrader:
    """
    Unrestricted trader that maximizes LEARNING, not profit.

    Takes every qualifying signal (score >= 3.0 instead of 5.0).
    No risk limits — the goal is DATA, not capital preservation.
    Trades 50-100 times per day to generate training data fast.
    """

    # Lab-specific settings
    min_score = 3.0          # Much lower bar (production: 5.0)
    min_rr = 1.0             # Accept 1:1 R:R (production: 2:1)
    max_trades_per_day = 100 # Aggressive (production: 6)
    max_concurrent = 5       # Multiple positions (production: 1)
    risk_per_trade = 0.02    # 2% of demo balance (no real money)
    cooldown_seconds = 60    # 1 min cooldown (production: 5 min)

    # Experiments the Lab runs automatically:
    # 1. Test ALL strategies (no blacklist)
    # 2. Test ALL regimes (no volatile filter)
    # 3. Test ALL hours (no session filter)
    # 4. Vary parameters: RSI period 5-21, BB std 1.5-3.0, etc.
    # 5. Log EVERYTHING for ML training
```

### Lab Experiments (automated):

| Experiment | What it tests | Duration |
|-----------|---------------|----------|
| **Baseline** | All strategies, default params, no filters | Continuous |
| **Parameter Sweep** | Each strategy with 5 param variations | Weekly |
| **Regime Study** | Force-trade in each regime, measure WR | Continuous |
| **Time-of-Day** | Trade every hour, find optimal windows | 2 weeks |
| **Correlation** | Which strategy PAIRS produce best results | Monthly |
| **Decay Detection** | Track strategy WR over time, detect degradation | Continuous |

---

## ML Models

### Model 1: Trade Outcome Predictor (XGBoost)

```
Input:  50+ features from feature store
Output: P(WIN), Expected R-multiple
Use:    Production filters trades where P(WIN) < 55%
Train:  On Lab data (1000+ trades)
Retrain: Weekly with new Lab data
```

### Model 2: Regime Classifier (XGBoost or Random Forest)

```
Input:  ATR ratios, volume profiles, price action features
Output: TRENDING / RANGING / VOLATILE / QUIET + confidence
Use:    Replace current heuristic regime detection
Train:  On labeled candle data (from backtests)
```

### Model 3: Strategy Ranker (Learning to Rank)

```
Input:  Strategy features + market context
Output: Ranked list of strategies most likely to profit NOW
Use:    Production selects top-ranked strategy instead of first/best
Train:  On Lab trade outcomes per strategy per context
```

---

## What We Reuse vs Build New

### Reuse (0 changes needed)
- All 14 strategies
- Market data provider
- Instrument specs
- Economic calendar
- Backtester + Monte Carlo
- Telegram alerts
- Logging infrastructure

### Refactor (small changes)
- `config.py` — add `lab` mode
- `risk/manager.py` — add `LabRiskManager` subclass
- `journal/database.py` — parameterize DB path
- `confluence/scorer.py` — separate state files per engine

### Build New
- `engine/src/lab/lab_trader.py` — unrestricted autonomous trader
- `engine/src/lab/lab_risk.py` — permissive risk manager
- `engine/src/lab/lab_analyzer.py` — Lab-specific analysis
- `engine/src/lab/promotion.py` — Lab → Prod recommendation pipeline
- `engine/src/ml/feature_store.py` — structured feature extraction
- `engine/src/ml/xgboost_model.py` — gradient boosted trade predictor
- `engine/src/ml/pattern_detector.py` — recurring pattern discovery
- `engine/src/ml/strategy_evolver.py` — automated parameter exploration
- `engine/lab_runner.py` — Lab engine entry point

---

## Implementation Phases

### Phase 1: Lab Foundation (build first)
1. Create `LabRiskManager` (permissive, log-only)
2. Parameterize database path (separate lab.db)
3. Build `LabTrader` (unrestricted autonomous trader)
4. Create `lab_runner.py` entry point
5. Test: Lab runs alongside Production on Binance Demo

**Deliverable:** Two engines running simultaneously, separate DBs, shared market data.

### Phase 2: Feature Store + ML
1. Build feature extraction (50+ features per signal)
2. Create feature store table in lab.db
3. Build XGBoost trade predictor (train on 500+ lab trades)
4. Build accuracy/calibration dashboard
5. Test: Model predicts with >55% accuracy on held-out data

**Deliverable:** ML model that predicts trade outcomes from structured features.

### Phase 3: Strategy Evolution
1. Build parameter sweep experiments
2. Build strategy combination testing
3. Build decay detection (WR trending down over time)
4. Build promotion pipeline (Lab → Prod)
5. Test: Lab discovers a parameter improvement, promotes to Production

**Deliverable:** Automated strategy improvement pipeline.

### Phase 4: Advanced ML
1. Add LSTM for price direction prediction
2. Reinforcement learning for dynamic position sizing (PPO)
3. Pattern recognition (CNN on candle charts — stretch goal)
4. Multi-model ensemble

**Deliverable:** Production uses ML predictions to filter and size trades.

---

## How to Run (after implementation)

```bash
# Terminal 1: Production Engine (careful, real-money-ready)
cd engine && ../.venv/bin/python run.py

# Terminal 2: Lab Engine (aggressive, learning-focused)
cd engine && ../.venv/bin/python lab_runner.py

# Terminal 3: Dashboard
cd dashboard && npm run dev

# Both engines share market data, use separate DBs
# Lab: notas_lave_lab.db, Prod: notas_lave.db
# Lab trades appear on demo.binance.com alongside prod trades
```

---

## Success Metrics

| Metric | Target | How Measured |
|--------|--------|-------------|
| Lab trades/day | 50+ | Count from lab.db |
| Feature store rows | 10,000+ in first month | feature_store table |
| XGBoost accuracy | >55% on held-out data | Walk-forward validation |
| Lab → Prod promotions | 1+ strategy improvement/month | promotion.py logs |
| Production WR improvement | +5pp after ML integration | Before/after comparison |
| Time to learn | 10x faster than prod-only | Trades needed for significance |

---

## Key Decision: Why NOT a Separate Codebase

The Lab is NOT a fork or copy. It's the same engine with different configuration:

1. **Maintenance:** One codebase, not two diverging copies
2. **Consistency:** Lab uses identical strategy code as production
3. **Portability:** Lab discoveries translate 1:1 to production (same strategies, same features)
4. **Simplicity:** `python run.py` for prod, `python lab_runner.py` for lab

The only truly separate things are:
- Database file (lab.db vs notas_lave.db)
- Risk manager instance (permissive vs strict)
- Learned state files (lab_weights.json vs learned_state.json)
- Agent configuration (aggressive vs conservative)

Everything else is shared code with different parameters.
