# Notas Lave - AI Trading System Research

**Date:** 2026-03-20
**Status:** Research Phase
**Goal:** Build a Claude-powered trading decision engine for scalping Gold, Silver, BTC, ETH on FundingPips (MT5)

---

## 1. Platform: FundingPips

### Key Rules (Must Be Coded Into System)
| Rule | Evaluation | Funded Account |
|------|-----------|----------------|
| Daily Drawdown | 5% | 5% |
| Total Drawdown | 10% (static) | 10% (static) |
| Consistency Rule | None | 45% (no single day > 45% of total profits) |
| News Trading | Unrestricted | No trading 5 min before/after high-impact news |
| Min Trading Days | 3/phase | N/A |
| Inactivity | 30 days max | 30 days max |
| EAs/Bots | Allowed (trade/risk management) | Allowed (trade/risk management only) |
| Hedging | Forbidden | Forbidden |
| HFT/Arbitrage | Forbidden | Forbidden |

### Platform Options
- MT5 (Windows only - needs VPS/VM for Mac)
- cTrader (+$20)
- Match-Trader

### Instruments Available
- Forex: 28+ pairs
- Metals: XAUUSD (Gold), XAGUSD (Silver)
- Crypto: BTCUSD, ETHUSD
- Indices, Energies
- Total: 48+ instruments

---

## 2. Reference Project: Temple-Stuart Accounting

**GitHub:** https://github.com/Temple-Stuart/temple-stuart-accounting
**What It Is:** Financial OS for founder-traders (options-focused)
**What We Learn From It:**

### Architecture Patterns to Adopt

#### A. Convergence Pipeline (Multi-Gate Scoring)
Temple-Stuart scores stocks across 4 gates:
- Vol-Edge (25%): IV-HV spread, term structure, technicals, skew
- Quality (25%): Safety, profitability, growth, fundamental risk
- Regime (25%): Market regime detection (Goldilocks/Reflation/Stagflation/Deflation/Crisis)
- Info-Edge (25%): News sentiment, insider activity, institutional flow

**Key Innovation: Dynamic Gate Weighting**
- Weights shift based on market regime
- In CRISIS: Quality 40%, Regime 30%, Vol-Edge 15%, Info-Edge 15%
- In GOLDILOCKS: Vol-Edge 30%, Info-Edge 30%, Quality 20%, Regime 20%
- Confidence-blended: `finalWeight = blend × dynamic + (1 - blend) × static`

#### B. Outcome Tracker (Learning System)
- Logs every scan snapshot with predicted scores
- After DTE expiry, backfills actual P&L
- Enables: hit rate per gate, empirical threshold calibration, P&L attribution
- This is EXACTLY what we need for our learning system

#### C. Pre-Filter → Score → Gate → Rank Pipeline
1. Hard filters eliminate non-candidates
2. Sub-scores computed per gate
3. Convergence check (3/4 gates must score >50)
4. Rank by composite score
5. Generate trade cards with real strikes/premiums

#### D. AI Role
- Claude for analysis/explanation ONLY
- "AI handles translation, not calculation"
- All financial math is deterministic code
- AI explains entries in plain English

### Key Differences (Their System vs Ours)
| Feature | Temple-Stuart | Notas Lave |
|---------|---------------|------------|
| Asset Class | US Equities/Options | Forex/Metals/Crypto |
| Strategy | Premium selling (Iron Condors, Credit Spreads) | Scalping, ICT, Fibonacci |
| Timeframe | Days to weeks | Seconds to hours |
| Data Source | Tastytrade, Finnhub, SEC | MT5 API, TradingView |
| AI Role | Post-analysis explanation | Pre-trade decision engine |
| Execution | Manual + trade cards | Semi-automated |

---

## 3. Strategies to Implement

### Category 1: ICT / Smart Money Concepts
1. **Order Blocks** - Last opposite candle before impulse move
2. **Fair Value Gaps (FVG)** - 3-candle imbalance gap
3. **Liquidity Sweeps** - Stop hunt reversals
4. **Optimal Trade Entry (OTE)** - 61.8%-78.6% Fibonacci retracement
5. **Kill Zones** - London (2-5AM EST), NY (8-11AM EST)
6. **Break of Structure (BOS)** - Trend continuation signal
7. **Change of Character (ChoCH)** - Trend reversal signal
8. **Premium/Discount Zones** - Buy in discount (<50%), sell in premium (>50%)
9. **Displacement** - Strong candle >= 1.5x ATR, body >= 70% range
10. **Inducement** - False breakout to trap retail

### Category 2: Order Flow Analysis
11. **DOM/Depth of Market** - Bid/ask imbalance
12. **Footprint Charts** - Volume delta at each price level
13. **Absorption** - Large orders absorbed without price movement
14. **Iceberg Detection** - Hidden large orders
15. **Volume Delta** - Aggressive buyers vs sellers

### Category 3: Fibonacci
16. **Retracement Levels** - 23.6%, 38.2%, 50%, 61.8%, 78.6%
17. **Extension Levels** - 127.2%, 161.8%, 261.8% (take profit targets)
18. **Fibonacci Confluence Zones** - Multiple timeframe fib levels aligning
19. **Fibonacci Time Zones** - Time-based cyclical analysis

### Category 4: Volume Analysis
20. **VWAP** - Volume-Weighted Average Price (institutional benchmark)
21. **Volume Profile** - Point of Control (POC), Value Area High/Low
22. **On-Balance Volume (OBV)** - Cumulative volume flow
23. **Accumulation/Distribution** - Money flow into/out of asset
24. **Volume Spread Analysis (VSA)** - Wyckoff-based volume analysis

### Category 5: Scalping Indicators
25. **EMA Crossovers** - 9/21, 5/13, 8/34 periods
26. **RSI** - Oversold/overbought with divergence
27. **Bollinger Bands** - Mean reversion and breakout
28. **Stochastic** - Momentum oscillator
29. **ATR** - Volatility-based stop loss and take profit

### Category 6: Price Action
30. **Support/Resistance** - Key levels detection
31. **Trendlines** - Auto-drawn from swing points
32. **Chart Patterns** - Head & Shoulders, Double Top/Bottom, Flags
33. **Candlestick Patterns** - Engulfing, Hammer, Doji, Morning/Evening Star

### Category 7: Advanced/Institutional
34. **Wyckoff Method** - Accumulation/Distribution phases
35. **Elliott Wave** - 5-3 wave structure detection
36. **Market Microstructure** - Spread analysis, tick patterns
37. **Regime Detection** - Trending vs ranging vs volatile
38. **Cross-Asset Correlation** - DXY vs Gold, BTC vs ETH, Yields vs Gold

### Category 8: News & Sentiment
39. **Economic Calendar** - NFP, CPI, FOMC, etc.
40. **News Sentiment** - RSS/API headline analysis via Claude
41. **Social Sentiment** - Reddit, X/Twitter, Fear & Greed Index
42. **COT Report** - Commitment of Traders (institutional positioning)

---

## 4. Architecture

### System Design: Multi-Strategy Confluence Engine

```
┌─────────────────────────────────────────────────────────────────┐
│                    DATA LAYER (Real-Time)                       │
│  ┌──────────┐ ┌──────────────┐ ┌────────────┐ ┌─────────────┐ │
│  │ MT5 API  │ │ Free APIs    │ │ News RSS   │ │ Econ Cal    │ │
│  │ (live)   │ │ (Yahoo/CG)   │ │ (sentiment)│ │ (events)    │ │
│  └────┬─────┘ └──────┬───────┘ └─────┬──────┘ └──────┬──────┘ │
│       └──────────────┼───────────────┼───────────────┘         │
│                      ▼                                          │
│              ┌───────────────┐                                  │
│              │ Data Pipeline │                                  │
│              │ OHLCV + Tick  │                                  │
│              └───────┬───────┘                                  │
└──────────────────────┼──────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────────┐
│              STRATEGY ENGINE (Deterministic)                     │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Pre-Filter: Kill Zone + Regime + Spread Check           │    │
│  └───────────────────────┬─────────────────────────────────┘    │
│                          ▼                                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │ ICT/SMC  │ │ Scalping │ │ Fibonacci│ │ Volume   │          │
│  │ Gate     │ │ Gate     │ │ Gate     │ │ Gate     │          │
│  │ (0-100)  │ │ (0-100)  │ │ (0-100)  │ │ (0-100)  │          │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘          │
│       └─────────────┼───────────┼─────────────┘                │
│                     ▼                                           │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Confluence Scorer (Dynamic Weights per Regime)           │    │
│  │ Composite = w1*ICT + w2*Scalp + w3*Fib + w4*Volume     │    │
│  │ + News Modifier + Correlation Modifier                   │    │
│  └───────────────────────┬─────────────────────────────────┘    │
└──────────────────────────┼──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│              CLAUDE DECISION ENGINE                              │
│                                                                  │
│  Input: Confluence score + raw signals + news + context          │
│  Claude evaluates:                                               │
│  1. Does the setup make sense in current market context?         │
│  2. Any conflicting signals Claude can detect?                   │
│  3. Optimal position size given recent performance?              │
│  4. Confidence level (1-10)                                      │
│  Output: { action, entry, sl, tp, size, confidence, reasoning }  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│              RISK MANAGER (Hard Rules - Never Override)          │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Prop Firm Guard                                          │    │
│  │ - Daily drawdown < 5%                                    │    │
│  │ - Total drawdown < 10%                                   │    │
│  │ - Consistency rule (no day > 45% of total)               │    │
│  │ - News blackout (5 min before/after high impact)         │    │
│  │ - Max concurrent positions                               │    │
│  │ - Max daily loss reached → STOP trading                  │    │
│  └─────────────────────────────────────────────────────────┘    │
│  IF passes all checks → Execute                                 │
│  IF fails any check → BLOCK (no override possible)              │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│              EXECUTION LAYER                                     │
│                                                                  │
│  Paper Trading:                                                  │
│  - Oanda Practice API (Gold, Silver)                            │
│  - Alpaca Paper (BTC, ETH)                                      │
│  - Internal simulator                                            │
│                                                                  │
│  Live Trading:                                                   │
│  - MT5 Python API → FundingPips                                 │
│  - TradingView Webhooks (alerts)                                │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│              LEARNING ENGINE (Post-Trade)                        │
│                                                                  │
│  1. Trade Logger: Every trade with full context snapshot         │
│  2. Outcome Tracker: Backfill actual P&L after trade closes     │
│  3. Strategy Grader: Which strategies performed best?            │
│  4. Parameter Optimizer: Walk-forward optimization               │
│  5. Regime Detector: What market conditions favor which strategy?│
│  6. Claude Review: Weekly AI analysis of trade journal           │
│  7. Weight Adjuster: Shift strategy weights based on performance │
│                                                                  │
│  Storage: SQLite/PostgreSQL trade journal                        │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ trade_log:                                               │    │
│  │   id, timestamp, symbol, direction, entry, exit,         │    │
│  │   sl, tp, size, pnl, duration,                          │    │
│  │   strategy_signals (JSON), confluence_score,             │    │
│  │   claude_confidence, claude_reasoning,                   │    │
│  │   market_regime, news_context,                           │    │
│  │   outcome_grade (A/B/C/D/F),                            │    │
│  │   lessons_learned (Claude analysis)                      │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. Learning & Improvement System

### How the System Gets Smarter

#### A. Trade-Level Learning
Every trade is logged with:
- All strategy signals at entry
- Claude's reasoning and confidence
- Market regime at time of trade
- News/events context
- Actual outcome (P&L, duration, max adverse excursion)
- Post-trade Claude analysis (what went right/wrong)

#### B. Strategy Performance Tracking
- Win rate per strategy per instrument per session
- Average R:R per strategy
- Sharpe ratio per strategy (rolling 30-day)
- Drawdown contribution per strategy
- Best/worst performing conditions for each strategy

#### C. Adaptive Weight System (Inspired by Temple-Stuart)
```python
# Strategy weights adapt based on recent performance
# Similar to Temple-Stuart's regime-dependent gate weighting
REGIME_WEIGHTS = {
    "trending": {"ict": 0.35, "scalping": 0.15, "fibonacci": 0.30, "volume": 0.20},
    "ranging":  {"ict": 0.20, "scalping": 0.35, "fibonacci": 0.25, "volume": 0.20},
    "volatile": {"ict": 0.25, "scalping": 0.10, "fibonacci": 0.25, "volume": 0.40},
    "quiet":    {"ict": 0.20, "scalping": 0.40, "fibonacci": 0.20, "volume": 0.20},
}
```

#### D. Walk-Forward Optimization
- Every week: backtest last 4 weeks of data
- Optimize parameters (RSI period, EMA lengths, FVG thresholds)
- Validate on most recent week (out-of-sample)
- Only adopt new params if they improve Sharpe ratio

#### E. Claude Weekly Review
Every Sunday, Claude analyzes:
- All trades from the past week
- Which strategies contributed most to P&L
- Common patterns in losing trades
- Suggested adjustments for next week
- Market regime assessment for upcoming week

---

## 6. Tech Stack

```
Python 3.11+
├── Core
│   ├── anthropic           # Claude API
│   ├── fastapi             # Webhook server + dashboard API
│   ├── uvicorn             # ASGI server
│   └── pydantic            # Data validation
├── Data
│   ├── MetaTrader5         # MT5 API (Windows/VPS)
│   ├── oandapyV20          # Oanda practice account
│   ├── alpaca-trade-api    # Alpaca paper trading
│   ├── yfinance            # Historical data
│   ├── ccxt                # Crypto exchange data
│   └── websockets          # Real-time streaming
├── Analysis
│   ├── pandas / numpy      # Data manipulation
│   ├── pandas-ta           # Technical indicators
│   ├── ta-lib              # Advanced TA (C-based, fast)
│   ├── scipy               # Statistical analysis
│   └── scikit-learn        # ML for regime detection
├── Storage
│   ├── sqlite3 / sqlalchemy # Trade journal
│   └── redis               # Real-time cache
├── Visualization
│   ├── plotly               # Charts
│   └── streamlit            # Dashboard
└── Scheduling
    └── apscheduler          # Task scheduling
```

---

## 7. Paper Trading Strategy (Phase 1)

### Start Without FundingPips
1. **Oanda Practice Account** - Free, API access, Gold + Silver
2. **Alpaca Paper** - Free, API access, BTC + ETH
3. **Internal Simulator** - Custom backtester for strategy validation

### Why Start Here
- Zero cost, zero risk
- Same strategies apply (price action is universal)
- Build confidence in the system before risking $29
- FundingPips MT5 requires Windows (Mac users need VPS)

---

## 8. Reddit Reference

### Post: "My GPT/Claude Trading Bot Evolved"
- URL: https://www.reddit.com/r/ClaudeAI/comments/1r35gpb/
- Related repo: Temple-Stuart (analyzed above)
- Key takeaway: Combines Claude for analysis with deterministic scoring pipeline
- NOT a scalping bot — it's an options analysis platform
- Our system is fundamentally different: real-time scalping vs position analysis

---

## 9. Key Learnings from Other Claude Trading Projects

### A. OpenProphet / Claude Prophet (Jake Nesler)
- **Source:** https://medium.com/@jakenesler/ + https://openprophet.io/
- Used Alpaca paper trading with $100K
- 40+ MCP tools for stock and options trading
- Multi-agent system: CEO, consultant, engineer, strategy agents
- **Results:** Beat the market (~7% vs 4.52%) over a full month
- Experienced drawdown to $93K but recovered Dec 12-17
- Notable win: +$14,578 on overnight puts when SPY dropped
- **Critical learning:** Agents vetoed chasing NVDA after 3.7% gap up, preventing ~$10K loss
- **Key insight:** "Minimal instructions worked better with Claude Code by itself" — complex multi-agent was overcomplicated
- Simple prompts like "Go trade autonomously till 4:01 PM" worked effectively
- Deprecated Claude Prophet repo in favor of OpenProphet for better agentic control

### B. "14 Sessions, 961 Tool Calls, 1 Surviving Strategy" (DEV Community)
- **Source:** https://dev.to/ji_ai/
- 27 files generated from one CLAUDE.md prompt
- 5-agent virtual review panel (Quant, Risk, Execution, Data, Ops)
- 15 strategies backtested, only 1 survived
- **Results:** Win rate 60%, but NET P&L: -$39.20
- **Root cause:** Inverted risk/reward structure (small wins, large losses)
- LESSON: Risk/reward ratios matter MORE than win rates
- LESSON: CLAUDE.md quality directly determines code quality

### C. "900+ Hours of Using Claude Code for Trading" (Medium)
- **Source:** https://medium.com/@aiintrading/
- **Most important practical lessons:**
  1. **Plan before coding** — Ask Claude to ask YOU questions before writing code
     - Example: "I want to build a mean reversion system. Ask me everything you need before we write a line of code."
  2. **Compound engineering** — Codebase gets smarter each session; by month 2 Claude knows your setup
  3. **MCP servers** — Think of them as "USB ports" connecting Claude to data (eliminates CSV workflow)
  4. **Mental model: Junior Quant** — Claude is a capable, fast junior quant that needs proper direction
  5. **Better context = better output** — Success comes from planning + specific instructions + live context + systems that remember
  6. **Cost of mistakes** — Wrong workflow = wasted hours; bad prompt = wasted afternoon; start over = wasted week

### D. "4,000-Line Production Bot" (Chudi.dev)
- **Source:** https://chudi.dev/blog/claude-code-production-trading-bot
- Built in 6 weeks with Claude Code
- API costs: $340/month -> $136/month with optimization
- Tiered context loading reduced costs 60%
- Two-gate verification (automated + manual) caught most bugs

### E. Polymarket Trading Bot (GitHub)
- 3-model ensemble: GPT-4o (40%), Claude (35%), Gemini (25%)
- 15+ independent risk checks — any failure blocks trade
- Fractional Kelly sizing for position management
- Real-time 9-tab monitoring dashboard

### Summary of Lessons for Notas Lave
| Lesson | Source | How We Apply It |
|--------|--------|-----------------|
| Minimal instructions > complex agents | OpenProphet | Keep Claude prompts focused, not overcomplicated |
| Risk/reward > win rate | 14 Sessions | Target 2:1+ R:R on every trade, never invert |
| Plan before coding | 900+ Hours | Research phase complete, scaffold next |
| CLAUDE.md quality = code quality | 14 Sessions | Our CLAUDE.md is detailed and maintained |
| Backtest everything | Multiple | No live trading without backtested proof |
| Context compounds | 900+ Hours | SESSION-CONTEXT.md preserves knowledge across sessions |
| Simple agents outperform complex ones | OpenProphet | One Claude decision engine, not 5 competing agents |
| Outcome tracking is essential | Temple-Stuart | Log every trade, backfill results, learn |

---

## 10. Learning & Adaptation System (Deep Research)

### A. Regime Detection — Hidden Markov Models (HMM)
**Best approach for detecting market conditions:**
- Use `hmmlearn` library with `GaussianHMM(n_components=3)`
- Train on daily returns to find hidden states (trending/ranging/volatile)
- HMM outperformed buy-and-hold across 2006-2023
- Switch strategy weights based on detected regime
- Features: ADX, RSI, MACD, volatility, price action

```python
from hmmlearn import hmm
model = hmm.GaussianHMM(n_components=3, covariance_type="full", n_iter=1000)
# States: 0=low-vol/ranging, 1=trending, 2=high-vol/crisis
```

### B. Reinforcement Learning — Strategy Optimization
**Key algorithms for trading:**
- **PPO** (Proximal Policy Optimization): Best for trend following, highest annual returns
- **A2C** (Advantage Actor-Critic): Good for discrete actions
- **DDPG** (Deep Deterministic Policy Gradient): Continuous action spaces
- **Self-Rewarding DRL (SRDRL)**: Integrates self-rewarding network, outperforms standard models

**Reward function design:**
- Multi-component: annualized return + downside risk + differential return + Treynor ratio
- **Differential Sharpe Ratio (DSR)** for online learning
- MDD penalty: Models with MDD reward achieve 5.03% drawdown vs 45.57% baseline
- Combined approach (RA-DRL): 3 agents trained on log returns, DSR, and MDD

**Libraries:** FinRL, Stable-Baselines3, PyTorch

### C. Meta-Learning — Strategy Selection
**How the system picks the best strategy for current conditions:**
- **Meta-LMPS**: Simulates multiple "fund managers" (strategies), dynamically allocates based on conditions
- **MetaTrader Framework**: Phase 1 learns diverse policies, Phase 2 learns meta-policy to select them
- **Dual-Head PPO**: Treats model selection as an RL problem — learns WHEN to use WHICH strategy
- Meta-learning derives initial parameters that rapidly adapt to new tasks

### D. Walk-Forward Optimization (Gold Standard)
**How parameters adapt over time:**
1. Optimize on in-sample window (e.g., 4 weeks)
2. Test on out-of-sample period (e.g., 1 week)
3. Shift window forward by test period
4. Repeat — stitched out-of-sample curve = realistic performance

**Limitations:** Susceptible to false discovery; CPCV is statistically superior but computationally heavier.

### E. Online/Incremental Learning
**Real-time adaptation options:**
| Approach | Update Frequency | Latency | Best For |
|----------|-----------------|---------|----------|
| Incremental | Continuous (per tick) | ~940ms | Fast adaptation |
| Offline-Online | Per session (daily) | ~617ms | Balanced |
| Walk-Forward | Weekly/monthly | N/A | Parameter tuning |

### F. Overfitting Prevention — CPCV
**Combinatorial Purged Cross-Validation:**
- Generates multiple chronology-respecting train-test partitions
- Purges overlapping information between train and test sets
- Embargo period prevents information leakage
- Produces DISTRIBUTION of Sharpe ratios, not single overfit estimate
- Superior to K-Fold, Purged K-Fold, and Walk-Forward for false discovery prevention
- **Risk:** Meta-overfitting if testing dozens of strategies on same dataset

### G. LLM Feedback Loop (Claude)
**How Claude improves the system over time:**
- **37% improvement per iteration** using competitive LLM approach
- Share disappointing trade results with Claude; specifically question problems
- Cross-model validation: Claude reviews strategies, proposes anti-overfitting improvements
- Multi-agent research (Bull/Bear analysts) shows significant improvements in Sharpe ratio
- **Weekly review prompt:** "Here are this week's 47 trades. Analyze patterns in winners vs losers, detect which strategies performed best in what conditions, and suggest weight adjustments."

### H. Adaptive Parameter Optimization
**How RSI period, Fibonacci levels, EMA lengths auto-tune:**
- **Bayesian Optimization**: Builds probabilistic model, learns from past results, converges faster than grid/random search
- Dynamic Fibonacci levels adjust based on recent volatility
- RSI period: test 7/14/21/28 per instrument per session
- Walk-forward validates parameter changes before adoption

### I. Implementation Plan for Learning Engine
```
Phase 1 (MVP):
├── Trade logger (every trade with full context)
├── Strategy performance tracker (win rate, R:R, Sharpe per strategy)
├── Basic regime detection (ATR + ADX based: trending/ranging/volatile)
└── Claude weekly review (manual trigger)

Phase 2 (Adaptive):
├── HMM regime detection (hmmlearn)
├── Walk-forward parameter optimization
├── Dynamic strategy weight adjustment
└── Automated Claude review (scheduled)

Phase 3 (ML):
├── RL-based strategy selection (PPO via Stable-Baselines3)
├── Incremental online learning
├── CPCV overfitting prevention
├── Bayesian parameter optimization
└── Meta-learning for strategy mixing
```

---

## 11. Open Questions

1. Should we use Mac-native APIs (Oanda/Alpaca) or set up Windows VPS for MT5?
2. What's the optimal Claude model for trading decisions? (Cost vs speed vs quality)
3. How to handle the 45% consistency rule algorithmically?
4. Should we build a web dashboard (Streamlit) or CLI-first?
5. What's the minimum viable set of strategies for Phase 1?
6. How much historical data do we need before enabling RL/meta-learning?
7. Should we start with simple regime detection (ATR/ADX) or jump to HMM?
8. How to prevent meta-overfitting when testing multiple strategy combinations?
