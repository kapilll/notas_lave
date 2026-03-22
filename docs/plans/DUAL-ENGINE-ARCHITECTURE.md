# Notas Lave — Dual Engine Architecture

**Status:** PLAN — build in 4-5 hours
**Core Idea:** Same engine, two modes. Lab trades aggressively to learn. Production trades carefully to profit. Claude runs both.

---

## How It Actually Works

```
                        CLAUDE (runs everything)
                              |
            ┌─────────────────┼─────────────────┐
            v                 v                  v
      TRADES in Lab     USES TOOLS auto      REPORTS findings
    (aggressive, all    (backtester, optimizer  (daily summary,
     day, learns)        research, etc.)        suggestions)
            |                 |                  |
            v                 v                  v
        Lab Database     Improved Models     Telegram + Dashboard
            |                                    |
            └──── When something works ──────────┘
                  (diamond found)
                        |
                  PRODUCTION adopts it
                  (careful, real money)
```

### Who does what:

| Actor | Role | Involvement |
|-------|------|-------------|
| **Claude** | THE trader. Places trades in lab. Reviews results. Uses backtester. Researches. Reports. | 100% autonomous |
| **ML (XGBoost)** | Fast filter. Scores signals instantly. Saves Claude tokens. | Automatic |
| **Human (Kapil)** | Reads reports. Makes code changes Claude suggests. Deploys. | Minimal, on your schedule |
| **Strategies** | Generate signals. Same 14 in both engines. | Automatic |

### The Lab in plain English:

The Lab is our current engine with the leash removed. It trades on Binance Demo all day. Low score threshold (3.0 instead of 5.0), no blacklist, no drawdown limits, 1:1 R:R accepted. It takes 50-100 trades/day instead of 1-6.

Every trade gets logged with features. Claude reviews the day's results every evening and generates a report: what worked, what didn't, what to try next. When something consistently works (a "diamond"), we promote it to production.

Claude also periodically runs the backtester, optimizer, and does web research — on its own, without you asking. It sends you a Telegram with findings.

---

## What Gets Built (4-5 hour prototype)

### Hour 1: Lab Engine Core

**Files to create:**
```
engine/src/lab/
    __init__.py
    lab_config.py        # Lab-specific settings (aggressive, no limits)
    lab_risk.py          # Permissive risk manager (logs only, never blocks)
    lab_trader.py         # Autonomous trader with no restrictions
engine/lab_runner.py      # Entry point: python lab_runner.py
```

**Lab config (the key differences from production):**
```python
# Lab is aggressive — the goal is DATA, not capital preservation
min_score = 3.0              # Production: 5.0
min_rr = 1.0                 # Production: 2.0
max_trades_per_day = 100     # Production: 6
max_concurrent = 5           # Production: 1
cooldown_seconds = 60        # Production: 300
use_blacklist = False         # Production: True
skip_volatile = False         # Production: True
risk_per_trade = 0.02        # 2% of demo balance (it's fake money)
```

**Lab risk manager:**
```python
class LabRiskManager:
    """Never blocks a trade. Logs everything. That's it."""
    def validate_trade(self, setup, **kwargs):
        logger.info(f"[LAB] Trade: {setup.symbol} {setup.direction.value} score={setup.confluence_score}")
        return True, []  # Always approve
```

**Lab trader:** Copy of AutonomousTrader but:
- Uses LabRiskManager instead of RiskManager
- Uses lab.db instead of notas_lave.db
- Lower thresholds for everything
- No blacklist filtering
- Telegram messages prefixed with `[LAB]`

### Hour 2: Separate Database + Feature Extraction

**Database:** Same schema, separate file (`notas_lave_lab.db`). Just parameterize the DB path in `_init_db()`.

**Basic feature extraction** (start simple, expand later):
```
engine/src/ml/
    __init__.py
    features.py           # Extract features from signals
```

Per signal, extract ~20 features:
```python
def extract_features(candles, signal, regime, symbol) -> dict:
    return {
        # Price action
        "atr_14": ...,
        "volume_ratio": ...,
        "body_ratio": ...,
        # Signal
        "score": signal.score,
        "rsi_value": signal.metadata.get("rsi_current"),
        "num_agreeing": ...,
        # Context
        "hour_utc": candles[-1].timestamp.hour,
        "day_of_week": candles[-1].timestamp.weekday(),
        "regime": regime.value,
        # Outcome (filled later)
        "outcome": None,
        "pnl": None,
    }
```

Store in a `feature_store` table in the DB. When a trade closes, update the outcome.

### Hour 3: Claude Auto-Tools + Daily Review

**Claude auto-tools:** The lab trader runs the backtester and optimizer on a schedule, WITHOUT human asking:

```python
# In lab_trader.py — scheduled tasks
async def _run_auto_research(self):
    """Claude uses tools autonomously. No human needed."""

    # Every 6 hours: run backtester on recent data
    if should_run_backtest():
        for symbol in config.active_instruments:
            candles = await market_data.get_candles(symbol, "5m", limit=5000)
            result = backtester.run(candles, symbol, "5m")
            logger.info(f"[LAB] Auto-backtest {symbol}: WR={result.win_rate}% PF={result.profit_factor}")

    # Every 12 hours: run optimizer
    if should_run_optimizer():
        for symbol in config.active_instruments:
            results = optimize_all_strategies(candles, symbol)
            save_results(symbol, results)

    # Daily at 22:00 UTC: Claude reviews the day
    if should_run_daily_review():
        await self._claude_daily_review()
```

**Claude daily review** — generates a report:

```python
async def _claude_daily_review(self):
    """Claude reviews lab results and generates actionable report."""
    # Gather today's data
    lab_trades = get_todays_trades(db=lab_db)
    feature_summary = get_feature_importance()
    strategy_breakdown = analyze_strategy_performance()

    prompt = f"""You are the research scientist for Notas Lave trading system.

TODAY'S LAB RESULTS ({len(lab_trades)} trades):
{format_trades(lab_trades)}

STRATEGY BREAKDOWN:
{strategy_breakdown}

TASKS:
1. What patterns do you see? Which strategies/times/regimes worked?
2. Any "diamonds" — strategies with >60% WR over 20+ trades?
3. Suggest 1-3 code improvements I should make (be specific: file, function, change).
4. What should the lab test differently tomorrow?
5. Should any lab finding be promoted to production?

Be concise. Focus on actionable insights."""

    response = await claude_call(prompt)
    await send_telegram(f"*[LAB] Daily Report*\n\n{response}")
    save_report(response)  # Store for dashboard
```

### Hour 4: Token Tracking in Dashboard + Telegram Reports

**Token tracking is already built** (`token_tracker.py`). Just expose it:

- Dashboard shows: daily cost, cumulative cost, cost per trade, cost breakdown
- Add to heartbeat Telegram: "Cost today: $0.45 (8 Claude calls)"

**Telegram reports format:**
```
[LAB] Daily Report — 2026-03-23

Trades: 67 | WR: 54% | Best: RSI Divergence (68% WR)
Top hours: 14-16 UTC (London/NY overlap)
Diamond candidate: RSI Divergence on ETHUSDT in TRENDING

Suggestions:
1. Lower RSI threshold from 30 to 25 for ETHUSDT
2. Momentum Breakout decaying — WR dropped 8% this week
3. Consider adding VWAP filter to Bollinger Bands entries

Cost: $0.52 today | $3.40 this week
```

### Hour 5: Integration Testing + Polish

- Run both engines simultaneously
- Verify lab.db separate from notas_lave.db
- Verify lab trades appear on demo.binance.com
- Verify daily report generates and sends to Telegram
- Fix any bugs
- Token tracking visible in dashboard

---

## What We Reuse (a LOT)

| Component | Reuse? | Notes |
|-----------|--------|-------|
| All 14 strategies | YES, as-is | Same code, lab just doesn't blacklist |
| Market data provider | YES, shared | Both engines share the same data feed |
| Confluence scorer | YES, as-is | Lab uses lower threshold |
| Backtester | YES, as-is | Lab runs it automatically |
| Optimizer | YES, as-is | Lab runs it automatically |
| Learning analyzer | YES, per-DB | Points at lab.db or notas_lave.db |
| Paper trader | YES, separate instance | Lab gets its own PaperTrader |
| Binance Demo broker | YES, shared | Both trade on same demo account |
| Telegram alerts | YES, with prefix | [LAB] vs [PROD] |
| Token tracker | YES, as-is | Already tracks all Claude calls |
| Structured logging | YES, as-is | Just works |
| Database schema | YES, separate file | Same tables, different .db file |

**What's actually NEW code:** ~4 files (lab_config, lab_risk, lab_trader, features.py) + lab_runner.py

---

## After the Prototype (future phases)

### Phase 2: Real ML (week 2)
- After lab generates 1000+ trades with features
- Train XGBoost on feature_store data
- Use P(WIN) to filter signals before Claude reviews
- Reduces Claude calls (and cost) in production

### Phase 3: Strategy Evolution (week 3)
- Lab auto-tests parameter variations
- Promotion pipeline: lab diamond → production
- Decay detection: alert when strategy WR drops

### Phase 4: Cloud Deployment (week 4)
- Docker compose: engine + lab + dashboard + postgres
- Free tier cloud (Railway/Render/Fly.io)
- Runs 24/7 without your laptop
- Dashboard accessible from phone

### Phase 5: Advanced ML (month 2+)
- LSTM for price direction
- RL (PPO) for dynamic sizing
- Multi-model ensemble

---

## Token Efficiency

| Action | Tokens | Cost | Frequency |
|--------|--------|------|-----------|
| Lab daily review | ~2K in, ~1K out | ~$0.02 | 1/day |
| Production trade decision | ~1K in, ~200 out | ~$0.01 | 5-10/day |
| Weekly architect review | ~5K in, ~2K out | ~$0.05 | 1/week |
| Auto-backtest (no Claude) | 0 | $0 | 4/day |
| Auto-optimizer (no Claude) | 0 | $0 | 2/day |
| **Total** | | **~$0.20/day** | |

Key savings:
- Lab trades use NO Claude calls (rule-based decisions only)
- ML filter reduces production Claude calls (skip low-probability setups)
- Backtester/optimizer are pure Python (no API calls)
- Claude only called for: production trade decisions, daily review, weekly review

---

## File Structure After Build

```
engine/
    run.py                    # Production engine entry point
    lab_runner.py             # Lab engine entry point (NEW)
    src/
        lab/                  # NEW
            __init__.py
            lab_config.py     # Aggressive settings
            lab_risk.py       # Permissive risk (never blocks)
            lab_trader.py     # Unrestricted autonomous trader
        ml/                   # NEW
            __init__.py
            features.py       # Feature extraction
        # Everything else stays the same
        strategies/           # Shared
        data/                 # Shared
        confluence/           # Shared
        backtester/           # Shared
        learning/             # Shared (per-DB)
        execution/            # Shared
        risk/                 # Production only
        agent/                # Production only
        journal/              # Shared (parameterized DB path)
        api/                  # Shared (serves both)
        alerts/               # Shared ([LAB]/[PROD] prefix)
        claude_engine/        # Shared
        monitoring/           # Shared
```

---

## Summary

**What you get in 4-5 hours:**
1. Lab engine running alongside production on Binance Demo
2. Lab takes 50-100 trades/day (vs production's 1-6)
3. Claude reviews lab results daily, sends report to Telegram
4. Backtester + optimizer run automatically (no human trigger)
5. Feature extraction stores structured data for future ML
6. Token cost visible in dashboard
7. Zero human involvement in trading/learning loop

**What Claude does autonomously:**
- Places lab trades all day
- Runs backtester every 6 hours
- Runs optimizer every 12 hours
- Reviews lab results daily (Telegram report)
- Suggests code improvements in reports
- Manages production trades (when signals qualify)

**What you do:**
- Read Telegram reports
- Make code changes Claude suggests
- Watch the system evolve
