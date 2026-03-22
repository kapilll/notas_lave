# Notas Lave — Revised Architecture Plan

**Status:** PLAN — awaiting approval
**Created:** 2026-03-22 (Session 8)
**Key Insight:** Fix the strategies BEFORE building the Lab. Garbage in = garbage out.

---

## The Brutal Truth (from research)

- **95% of crypto bots lose money within 90 days**
- Our backtests show 58% WR but real bots perform **20-40% worse** than backtests
- **10 of our 14 strategies ignore volume** — the single most important confirmation
- **13 of 14 are single-timeframe** — proven to fail in retail
- **2 strategies are catastrophic losers** (Order Blocks: -$87K, Session Kill Zone: -$5.9K)
- RSI Divergence (our "sole crypto survivor") **underperforms buy-and-hold by 35%** per academic research
- Our RSI + Stochastic signals are CORRELATED (both momentum oscillators = counting the same thing twice)

**If we build a Lab on broken strategies, the Lab learns wrong lessons.**

---

## Critical Discovery: Timeframe Matters More Than Strategy

Backtesting across timeframes revealed:

| TF | BTC WR | BTC PF | BTC P&L | Verdict |
|----|--------|--------|---------|---------|
| 5m | 13% | 0.29 | -$8,181 | DISASTER — too noisy |
| 15m | 0% | 0.00 | -$349 | Too few signals |
| **1h** | **43%** | **1.78** | **+$756** | **PROFITABLE** |
| 4h | 20% | 0.95 | -$57 | Near break-even |

**The same strategies that LOSE on 5m MAKE MONEY on 1h.**

### Multi-Timeframe Architecture

```
4H candles → detect_regime() + trend direction
                    ↓
1H candles → run strategies → signals (THIS is where the edge lives)
                    ↓
15m/5m → optional entry timing refinement (tighter stops)
```

The Lab tests ALL timeframes. Production only uses what the Lab validates.

---

## The Real Architecture: 3 Phases

### Phase 0: Fix the Foundation (DONE)
### Phase 1: Build the Lab Engine
### Phase 2: ML + Evolution

---

## Phase 0: Fix the Foundation

### Strategy Overhaul

**REMOVE (2 strategies):**
- `order_blocks.py` — -$87K on Gold, -$3.7K crypto. ICT concepts don't work on derivatives.
- `session_killzone.py` — -$5.9K on BTC, fragile session logic, no volume.

**REWORK ALL remaining 12 strategies with 3 mandatory upgrades:**

#### Upgrade 1: Volume Confirmation (currently 10/14 ignore volume)
Every strategy must check: `volume > 1.5x 20-period average` before firing a signal.
```python
# Add to BaseStrategy or each strategy's analyze():
vol_avg = sum(c.volume for c in candles[-20:]) / 20
if candles[-1].volume < vol_avg * 1.5:
    return self._no_signal("Volume too low")
```

#### Upgrade 2: Multi-Timeframe Trend Filter (currently 13/14 single-TF)
No trade against the 1H trend. Period. Research shows this cuts false signals by 50-60%.
```python
# The confluence scorer already has get_htf_bias() — but it's OPTIONAL.
# Make it MANDATORY: if HTF bias disagrees, score = 0 (not just -40%).
```

#### Upgrade 3: ATR-Based SL/TP (currently using magic percentages)
Replace all hardcoded "SL = price - 20%" with ATR-relative stops:
```python
atr = calculate_atr(candles, 14)
stop_loss = entry - (atr * 1.5)  # 1.5 ATR stop
take_profit = entry + (atr * 3.0)  # 2:1 R:R with ATR
```
Only `momentum_breakout.py` does this correctly. Copy its approach to all strategies.

**The 4 Non-Correlated Signal Types We Need:**

| Type | Purpose | Strategies | Weight |
|------|---------|-----------|--------|
| **Structure** | WHERE to trade (levels) | Fibonacci, Camarilla, Break & Retest | 0.30 |
| **Trend** | WHICH direction | EMA Crossover, EMA Gold, London Breakout | 0.25 |
| **Momentum** | WHEN to enter (timing) | RSI Divergence OR Stochastic (NOT both) | 0.20 |
| **Volume** | CONFIRMATION | Momentum Breakout, VWAP (crypto version) | 0.25 |

**Key change:** Pick ONE momentum oscillator per instrument, not two. RSI and Stochastic are correlated — using both is counting the same evidence twice.

### Backtester Fixes

- Already done: session-adjusted spread (MM-F01), slippage model, block bootstrap
- Add: **realistic fee model** for high-frequency scenarios (0.04% taker × 2 = 0.08% round trip)
- Add: **regime-aware strategy selection** (only run range strategies in ranging, trend strategies in trending)

### Estimated Time: 3-4 hours
- 1h: Remove 2 strategies, add volume check to BaseStrategy
- 1h: Make HTF filter mandatory in scorer, fix category weights
- 1h: Convert magic-number SL/TP to ATR-based across 10 strategies
- 30m: Update backtester with realistic fee model + regime filtering
- 30m: Run backtests, validate improvements

---

## Phase 1: Build the Lab Engine

**Only AFTER Phase 0 strategies are fixed and backtested.**

### What the Lab Does

The Lab is our SAME engine with restrictions removed. It trades aggressively on Binance Demo to generate learning data. Claude runs it autonomously.

```
Lab Engine (aggressive)              Production Engine (careful)
├── Same 12 fixed strategies         ├── Same 12 fixed strategies
├── Score threshold: 3.0             ├── Score threshold: 5.0
├── Min R:R: 1.0                     ├── Min R:R: 2.0
├── Max trades/day: 50               ├── Max trades/day: 6
├── Max concurrent: 5                ├── Max concurrent: 1
├── No blacklist                     ├── Blacklist active
├── No risk limits                   ├── Full risk enforcement
├── Lab database (lab.db)            ├── Production database
├── ML-only decisions (fast)         ├── ML filter → Claude decision
└── Telegram: [LAB] prefix           └── Telegram: [PROD] prefix
```

### What Claude Does (fully autonomous)

```
EVERY 30 SECONDS (Lab):
  → Scan markets
  → If signal qualifies (score >= 3.0) → TRADE immediately
  → Log trade + features to lab.db

EVERY 6 HOURS:
  → Run backtester on active instruments (auto, no human)
  → Run optimizer on top strategies (auto, no human)
  → Store results

EVERY EVENING (22:00 UTC):
  → Claude reviews lab trades → generates report
  → "RSI Divergence: 67% WR in TRENDING, 41% WR in RANGING"
  → "Momentum Breakout best during 14-16 UTC (London/NY overlap)"
  → "Suggestion: lower RSI period to 5 for ETHUSDT"
  → Sends report to Telegram

EVERY SUNDAY:
  → Claude full weekly review
  → Promote lab findings to production
  → Kill decaying strategies
  → Suggest code changes for Kapil to implement
  → Retrain ML models

PRODUCTION (1-6 trades/day):
  → Signal fires → ML scores P(WIN) → if > 55%: Claude reviews → TRADE/SKIP
  → Claude sees: ML prediction, features, recent lab data, regime
  → Claude makes final call autonomously (no human)
```

### What You Do

- Read Telegram reports (daily lab summary, weekly evolution report)
- Make code changes Claude suggests in reports
- Watch dashboard for costs and accuracy
- That's it. Zero involvement in trading decisions.

### Files to Build

```
engine/src/lab/
    __init__.py
    lab_config.py          # Aggressive settings
    lab_risk.py            # Permissive (log-only, never blocks)
    lab_trader.py          # Unrestricted autonomous trader
engine/src/ml/
    __init__.py
    features.py            # Extract features per signal
engine/src/claude_engine/
    trader_brain.py        # Claude pre-trade decisions (production)
    lab_scientist.py       # Claude daily lab review
    weekly_architect.py    # Claude weekly evolution
engine/lab_runner.py       # Entry point
```

### Estimated Time: 3-4 hours
- 1h: Lab core (config, risk, trader, runner)
- 1h: Feature extraction + separate lab.db
- 1h: Claude decision engine (trader_brain for production, lab_scientist for daily review)
- 30m: Token tracking in dashboard
- 30m: Testing both engines running simultaneously

---

## Phase 2: ML + Evolution (After Lab generates 500+ trades)

### XGBoost Trade Predictor
- Train on lab feature store (500+ trades with features)
- Predict P(WIN) from 20+ features
- Use as filter in production: only send P(WIN) > 55% setups to Claude

### Strategy Evolution
- Lab auto-tests parameter variations
- Decay detection: alert when strategy WR drops over 50-trade window
- Promotion pipeline: lab diamond → production adoption

### Claude Weekly Reports Include:
```
WEEKLY EVOLUTION REPORT — Notas Lave

Lab Performance: 342 trades, 57% WR, PF 1.34
Production Performance: 8 trades, 62% WR, PF 1.89

Diamonds Found:
  1. RSI Divergence (period=5) on ETH: 71% WR over 45 trades in TRENDING
  2. Break & Retest with volume > 2x: 68% WR across all instruments

Decaying:
  1. Bollinger Bands: WR dropped from 61% to 48% over last 100 trades

Recommendations for Code Changes:
  1. In rsi_divergence.py: change default rsi_period from 7 to 5
  2. In confluence/scorer.py: increase breakout weight from 0.20 to 0.25
  3. Consider adding ADX > 25 filter for trend strategies

Cost This Week: $1.40 (28 Claude calls)
```

### Estimated Time: 2-3 hours (after 1-2 weeks of lab data)

---

## Realistic Expectations

| Metric | Garbage Bot | Our Target | Elite Bot |
|--------|-------------|------------|-----------|
| Win Rate | 40-50% | **55-65%** | 70-80% |
| Profit Factor | < 1.5 | **1.5-2.0** | > 2.0 |
| Monthly Return | -5% to +2% | **3-6%** | 6-10% |
| Max Drawdown | > 20% | **< 10%** | < 5% |
| Live vs Backtest | 50% worse | **20-30% worse** | 10% worse |

**What separates us from the 95% that fail:**
1. Volume confirmation on every signal (most bots ignore it)
2. Multi-timeframe alignment (most bots are single-TF)
3. Non-correlated signal types (not double-counting)
4. Regime-aware strategy selection (not one-size-fits-all)
5. Lab generating 10-100x more learning data than production alone
6. Claude reviewing and evolving the system weekly

---

## Dashboard UI Design (Fun, Not Boring)

The current dashboard is solid (dark theme, status bar, market cards, tools). But it needs:
1. **Dual engine view** — see both Production and Lab side-by-side
2. **Claude's brain visible** — see what Claude is thinking, deciding, suggesting
3. **Gamification** — make it satisfying to watch the system evolve
4. **Cost tracking** — token usage visible at all times

### Layout: 3-Tab Navigation

```
[COMMAND CENTER]  [LAB]  [EVOLUTION]
```

### Tab 1: COMMAND CENTER (Production)
What's there now + upgrades:

```
┌─────────────────────────────────────────────────────────┐
│  NOTAS LAVE                              [$0.12 today]  │
│  ● LIVE  Balance: $5,000  Daily: +$23  DD: 2%          │
├─────────────────────────────────────────────────────────┤
│  LIVE TRADES                                            │
│  ┌─────────────────────────────────────────────┐        │
│  │ ETHUSDT LONG  +$12.40  ██████████░░ 68%     │        │
│  │ Entry: 2154  SL: 2130  TP: 2200  Score: 7.2 │        │
│  └─────────────────────────────────────────────┘        │
│                                                         │
│  MARKETS          BTCUSDT 7.2▲   ETHUSDT 5.4~          │
│                                                         │
│  CLAUDE'S LATEST DECISION                               │
│  ┌─────────────────────────────────────────────┐        │
│  │ "TRADE — RSI divergence at 28.4 with volume │        │
│  │  confirmation. ML P(WIN): 62%. Regime:       │        │
│  │  TRENDING matches strategy strength."        │        │
│  └─────────────────────────────────────────────┘        │
│                                                         │
│  TOOLS  [Backtest] [Walk-Forward] [Monte Carlo] ...     │
└─────────────────────────────────────────────────────────┘
```

**New elements:**
- Token cost badge in header (always visible)
- Claude's latest decision with reasoning (not hidden behind button)
- ML P(WIN) shown on market cards when available

### Tab 2: LAB (The Fun Part)

```
┌─────────────────────────────────────────────────────────┐
│  LAB ENGINE                    [42 trades today] ● LIVE │
├───────────────────────┬─────────────────────────────────┤
│  TODAY'S STATS        │  LIVE EXPERIMENT                │
│  Trades: 42           │  ┌─────────────────────┐        │
│  Win Rate: 57%        │  │ Testing RSI period=5 │        │
│  Best: RSI Div (68%)  │  │ vs period=7 on ETH   │        │
│  Worst: BB (38%)      │  │ Results: 23 vs 19    │        │
│  P&L: +$340 (demo)    │  │ p-value: 0.12        │        │
│                       │  └─────────────────────┘        │
├───────────────────────┴─────────────────────────────────┤
│  STRATEGY LEADERBOARD (live, updates as trades close)   │
│  ┌──────────────────────────────────────────────┐       │
│  │ #1 RSI Divergence    68% WR  ████████████    │       │
│  │ #2 Momentum Breakout 64% WR  ██████████      │       │
│  │ #3 EMA Crossover     59% WR  ████████        │       │
│  │ #4 Break & Retest    55% WR  ██████          │       │
│  │ ...                                          │       │
│  │ #10 Fibonacci        42% WR  ████ ← DECAY!  │       │
│  └──────────────────────────────────────────────┘       │
│                                                         │
│  REGIME MAP (what's working WHERE)                      │
│  ┌──────────────────────────────────────────────┐       │
│  │ TRENDING:  RSI ●●●● BB ●●   Momentum ●●●    │       │
│  │ RANGING:   BB ●●●●  RSI ●●  Fib ●●●         │       │
│  │ VOLATILE:  SKIP ✗   (all strategies struggle) │       │
│  │ QUIET:     EMA ●●●  Stoch ●● (low volume)   │       │
│  └──────────────────────────────────────────────┘       │
│                                                         │
│  RECENT LAB TRADES (scrolling feed)                     │
│  14:23 ETHUSDT LONG +$8.20 RSI Div [TRENDING] ✓        │
│  14:18 BTCUSDT SHORT -$3.10 BB [RANGING] ✗             │
│  14:12 ETHUSDT SHORT +$5.40 Momentum [TRENDING] ✓      │
└─────────────────────────────────────────────────────────┘
```

**What makes it fun:**
- Live strategy leaderboard that updates in real-time (like a sports scoreboard)
- Regime map shows what works WHERE (visual, not a table)
- Scrolling trade feed (like a live ticker)
- "DECAY!" warnings on struggling strategies (red, attention-grabbing)
- Active experiments visible with p-values

### Tab 3: EVOLUTION (Claude's Brain)

```
┌─────────────────────────────────────────────────────────┐
│  SYSTEM EVOLUTION                          Week 3       │
├─────────────────────────────────────────────────────────┤
│  CLAUDE'S LATEST REPORT                                 │
│  ┌─────────────────────────────────────────────┐        │
│  │ "This week the lab discovered that RSI      │        │
│  │  period=5 outperforms period=7 on ETH by    │        │
│  │  11pp. Promoting to production.              │        │
│  │                                              │        │
│  │  Fibonacci is decaying — WR dropped from    │        │
│  │  61% to 42% over 200 trades. Recommend      │        │
│  │  adding volume filter or disabling.          │        │
│  │                                              │        │
│  │  Code suggestion: In rsi_divergence.py,     │        │
│  │  line 127, change rsi_period=7 to 5."       │        │
│  └─────────────────────────────────────────────┘        │
│                                                         │
│  DIAMONDS FOUND (lab-validated improvements)            │
│  ┌──────────────────────────────────────────────┐       │
│  │ 💎 RSI period=5 on ETH: 71% WR (45 trades)  │       │
│  │ 💎 Volume > 2x filter: +8pp WR improvement   │       │
│  │ 🔬 Testing: Bollinger + EMA combo            │       │
│  └──────────────────────────────────────────────┘       │
│                                                         │
│  ACCURACY OVER TIME (line chart)                        │
│  Week 1: 52% ───── Week 2: 56% ───── Week 3: 61%      │
│                                                         │
│  TOKEN COSTS                                            │
│  Today: $0.12 | This Week: $0.84 | Total: $3.40        │
│  ┌──────────────────────────────────────────────┐       │
│  │ Trade decisions:  $0.05  (5 calls)           │       │
│  │ Lab daily review: $0.02  (1 call)            │       │
│  │ Weekly evolution:  $0.05  (1 call)            │       │
│  └──────────────────────────────────────────────┘       │
│                                                         │
│  EVOLUTION TIMELINE                                     │
│  ● Week 1: System started. 14 strategies. 52% WR.      │
│  ● Week 2: Removed Order Blocks. Added volume. 56% WR. │
│  ● Week 3: RSI tuned. Fibonacci flagged. 61% WR.       │
│  ○ Week 4: (pending...)                                 │
└─────────────────────────────────────────────────────────┘
```

**What makes it fun:**
- Claude's reports in natural language (not JSON dumps)
- Diamond emojis for validated discoveries
- Accuracy trend line showing improvement over time
- Evolution timeline (seeing the system grow week by week)
- Token costs always visible (transparency)

### UI Tech Stack
- Keep existing: Next.js 16 + React 19 + TailwindCSS 4
- Add: `recharts` for charts (lightweight, React-native)
- Keep: `lightweight-charts` for candlestick (already installed)
- The current page.tsx is 842 lines — split into components per tab

### UI Build Plan
- Phase 0: No UI changes (focus on strategy fixes)
- Phase 1: Add Lab tab + split page.tsx into components
- Phase 2: Add Evolution tab + Claude report display + cost tracking
- Phase 3: Add charts (accuracy trend, strategy leaderboard animation)

---

## Build Order

```
PHASE 0: Fix Foundation (3-4 hours) ← DO THIS FIRST
  ├── Remove 2 broken strategies
  ├── Add volume confirmation to all strategies
  ├── Make HTF filter mandatory
  ├── Convert to ATR-based SL/TP
  └── Re-run backtests, validate improvement

PHASE 1: Lab Engine (3-4 hours) ← AFTER Phase 0 validated
  ├── Lab runner + permissive risk
  ├── Feature extraction
  ├── Claude decision engine
  ├── Daily report system
  └── Test both engines simultaneously

PHASE 2: ML + Evolution (2-3 hours) ← AFTER Lab generates 500+ trades
  ├── XGBoost trade predictor
  ├── Strategy decay detection
  ├── Promotion pipeline
  └── Weekly evolution reports

PHASE 3: Cloud Deploy ← AFTER system is profitable on demo
  ├── Docker compose
  ├── Free cloud (Railway/Fly.io)
  └── Runs 24/7 without laptop
```

**Total: ~10-12 hours across 3-4 sessions. Phase 0 is the priority.**

---

## Token Efficiency

| Action | Cost | Frequency |
|--------|------|-----------|
| Lab trades (ML-only, no Claude) | $0 | 50/day |
| Production trade review | ~$0.01 | 5-10/day |
| Lab daily report | ~$0.02 | 1/day |
| Weekly evolution | ~$0.05 | 1/week |
| Auto-backtest/optimize (pure Python) | $0 | 4/day |
| **Total** | **~$0.15/day** | |

Dashboard shows: daily/weekly cost, cost per trade, Claude call count.
