# Development Process — Build Features That Make Money

This is NOT a regular software project. Every code change directly affects whether the system makes or loses money. Follow this process.

## The Pipeline

```
RESEARCH → BACKTEST → BUILD → TEST → PAPER TRADE → DEPLOY → MEASURE
```

Skip a step = lose money.

## Step 1: Research

Before writing any code, understand the trading concept.

**For a new strategy:**
```
1. What edge does it exploit? (trend, mean-reversion, momentum, order flow)
2. What market conditions does it work in? (trending, ranging, volatile)
3. What instruments is it best for? (BTC, ETH, altcoins, metals)
4. What's the expected win rate and R:R?
5. What are the failure modes? (whipsaws, low volume, news events)
```

**For a system change (risk, execution, data):**
```
1. What problem does it solve? (specific, measurable)
2. What could go wrong? (blast radius)
3. How will we know it worked? (metric)
```

**Use Claude to research:** Ask for academic papers, backtesting studies, and real trader experiences. Check `docs/research/STRATEGIES-DETAILED.md` for existing research.

## Step 2: Backtest

Never trust a strategy until you've tested it on historical data.

```bash
# Run backtester on a strategy
cd engine
python -c "
from notas_lave.backtester.engine import Backtester
from notas_lave.data.market_data import market_data
# ... fetch candles, run backtest, check results
"
```

**Minimum requirements to proceed:**
- Profit Factor > 1.2 (gross profit / gross loss)
- Win Rate > 40% with R:R >= 2:1
- Max Drawdown < 10%
- Sharpe Ratio > 0.5
- At least 30 trades in the backtest
- Walk-forward validation passes (OOS profitable)
- Monte Carlo p-value < 0.05 (edge is statistically significant)

**Red flags that kill a strategy:**
- Only works on one instrument
- Only works in one regime (trending but not ranging)
- Profit Factor < 1.0 on any fold of walk-forward
- Very high win rate (>80%) with tiny R:R — likely curve-fitted

## Step 3: Build

Write the code. Follow these rules:

**Strategy code:**
- Inherit from `BaseStrategy`, implement `analyze(candles, symbol) → Signal`
- Strategies MUST be stateless — no instance variables that persist between calls
- Use `self.compute_atr()` for volatility-adaptive SL/TP
- Use `self.check_volume()` for volume confirmation (never disable it)
- Register in `strategies/registry.py`

**System code:**
- Follow existing patterns (DI Container, Protocols, Event Bus)
- No module-level singletons
- All imports from `notas_lave.X`
- Update `architecture/model.c4` if you change architecture

**Confluence integration:**
- New strategies are automatically picked up by the scorer
- Assign the right category (`scalping`, `ict`, `fibonacci`, `volume`, `breakout`)
- Category weights are auto-adjusted by the learning engine

## Step 4: Test

```bash
cd engine
../.venv/bin/python -m pytest tests/ --cov=notas_lave --cov-fail-under=34 -x -q
```

**Required:**
- All existing tests pass
- New code has tests (at minimum: doesn't crash, returns valid Signal)
- Coverage doesn't drop
- `test_startup.py` passes (no broken imports or config)

## Step 5: Paper Trade (Lab)

After merging, the Lab engine runs the strategy on Delta Exchange testnet with real market data but fake money.

**Monitor:**
- Dashboard: `http://34.100.222.148:3000` → Lab tab
- Logs: `nlvmssh` → `sudo journalctl -u notas-engine -f`
- API: `curl http://34.100.222.148:8000/api/lab/status`

**Minimum paper trading period:**
- New strategy: 1 week (at least 20 trades)
- System change: 2-3 days
- Risk rule change: 1 week

**What to watch:**
- Is the strategy generating signals? (check logs for `[LAB] Tick`)
- Is the risk manager rejecting all trades? (check for `RISK REJECT`)
- What's the win rate after 20+ trades?
- Is the P&L positive?

## Step 6: Deploy & Measure

```bash
notas-release v1.X.0
```

**After deployment:**
1. Check `/health` shows correct version
2. Check `/api/broker/status` shows connected
3. Check Lab is scanning (`[LAB] Tick` in logs)
4. Wait for first trade, verify in dashboard

**Ongoing measurement:**
- Learning engine analyzes every trade automatically
- Weekly: check `/api/learning/recommendations`
- Monthly: run expert review (`docs/reviews/REVIEW-PROMPT.md`)

## Quality Gates

| Gate | What it checks | When |
|------|---------------|------|
| **PR Check** | Tests pass, coverage gate, version bumped | Before merge |
| **Backtest** | Profit factor, win rate, drawdown, walk-forward | Before building |
| **Risk Manager** | Every trade validated against rules | Every trade |
| **Volume Analysis** | Signal confirmed by volume (0.6x-1.5x multiplier) | Every signal |
| **Learning Engine** | Strategy blacklisted if WR < 35% over 30+ trades | Continuous |
| **Expert Review** | 10-panel code review with specific fixes | Every 3-5 sessions |
| **Pre-deploy Check** | Broker config valid on VM | Every deploy |
| **Health Check** | Engine responds, version matches tag | Every deploy |

## What Makes Money vs What Doesn't

**Makes money:**
- High R:R trades (2:1+) with volume confirmation
- Trading with the higher timeframe trend (HTF filter)
- Cutting losers fast (tight SL via ATR)
- Letting winners run (trailing breakeven after 1:1)
- Adapting to regime (different weights for trending vs ranging)
- Learning from every trade (blacklist losers, boost winners)

**Loses money:**
- Trading without volume confirmation (fake breakouts)
- Counter-trend trading without strong confluence
- Curve-fitting strategies to historical data (passes backtest, fails live)
- Overtrading in quiet markets (forcing setups)
- Ignoring the risk manager (the #1 lesson from v1.0.0)
- Not measuring results (flying blind)

## Session Checklist

Start every Claude session with:
```
1. Read CLAUDE.md (quick reference)
2. Check /health and /api/lab/status (is it running? any trades?)
3. Check /api/learning/recommendations (what should we improve?)
4. Read the relevant docs/system/ file for what you're working on
```

End every session with:
```
1. All changes in PRs (never push to main)
2. Version bumped in pyproject.toml
3. CHANGELOG.md updated
4. Relevant docs/system/ doc updated with new rules
5. architecture/model.c4 updated if architecture changed
```
