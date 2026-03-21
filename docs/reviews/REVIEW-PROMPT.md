# Notas Lave — Expert Review System

**PURPOSE:** Review the trading system from multiple expert perspectives to find flaws before they cost money.

**TWO MODES** (to avoid confirmation bias):

| Mode | When to use | Command |
|------|-------------|---------|
| **Mode A: Fresh Review** | Primary mode. Unbiased, no priming from old issues | `Read docs/reviews/REVIEW-PROMPT.md and run a fresh review` |
| **Mode B: Progress Check** | After Mode A. Reconcile fresh findings with issue tracker | `Now read docs/reviews/ISSUES.md and reconcile` |

**FREQUENCY:** Every 3-5 sessions, or after major changes.

---

# MODE A: FRESH REVIEW (Unbiased)

**CRITICAL: Do NOT read `docs/reviews/ISSUES.md` during Mode A.**
Reading past issues primes the reviewer to anchor on known problems, confirm previous findings, and miss new categories of flaws. Mode A must be a clean-slate evaluation.

## Step 1: Read System Context ONLY

```
docs/context/SESSION-CONTEXT.md          # What the system is and does
CLAUDE.md                                 # Project rules and constraints
```

Do NOT read ISSUES.md. Do NOT look at previous review findings.

## Step 2: Read ALL Core System Files

Read these in parallel — understand the full system before judging any part:

```
engine/src/agent/autonomous_trader.py     # The autonomous loop
engine/src/agent/trade_learner.py         # Per-trade Claude analysis
engine/src/agent/config.py                # Agent permissions and safety
engine/src/backtester/engine.py           # Backtester + walk-forward + blacklists
engine/src/backtester/monte_carlo.py      # Monte Carlo permutation testing
engine/src/strategies/registry.py         # Strategy registration
engine/src/strategies/rsi_divergence.py   # Key strategy (sole crypto survivor)
engine/src/confluence/scorer.py           # Signal combination + regime detection
engine/src/risk/manager.py               # The gatekeeper
engine/src/execution/binance_testnet.py   # Exchange broker
engine/src/execution/base_broker.py       # Broker abstraction
engine/src/data/instruments.py            # Instrument specs + position sizing
engine/src/data/economic_calendar.py      # News blackout
engine/src/learning/analyzer.py           # Trade analysis engine
engine/src/learning/recommendations.py    # Actionable suggestions
engine/src/learning/optimizer.py          # Walk-forward parameter tuning
engine/src/learning/accuracy.py           # Prediction accuracy tracker
engine/src/learning/ab_testing.py         # A/B testing framework
engine/src/monitoring/token_tracker.py    # Cost tracking
engine/tests/test_instruments.py          # Position sizing tests
engine/tests/test_strategies.py           # Strategy output tests
```

Also glob for any new .py files not in this list.

## Step 3: Run Selected Panels

Each panel is an independent expert. They know nothing about previous reviews.
They evaluate the code AS-IS, not relative to what it was before.

---

## AVAILABLE EXPERT PANELS

### Panel 1: QUANT RESEARCHER
**Persona:** 10+ years at a prop firm (Jane Street/Citadel). Lives and breathes statistical rigor.
**Focus:**
- Backtesting methodology: walk-forward, out-of-sample, data snooping
- Statistical biases: survivorship, look-ahead, selection, overfitting
- Is the data sufficient? What regimes does it cover?
- Are the strategies actually edges or curve-fitted artifacts?
- Position sizing math: any holes that amplify risk?
- Sharpe/Sortino/Calmar calculation correctness
- Monte Carlo / permutation testing methodology
- Transaction cost sensitivity
- Confidence intervals on reported metrics

**Key Questions:**
1. Would you trust these backtest results enough to trade your own money?
2. What is the probability that the reported edge is real vs data-mined?
3. What additional data or tests would you require before going live?

---

### Panel 2: AI/ML SPECIALIST
**Persona:** Built production ML trading systems at a quant fund. Expert in feedback loops and model decay.
**Focus:**
- Learning engine architecture: is the feedback loop closed?
- Claude-as-analyst: viable approach or theater?
- How should the system evolve strategies properly?
- What's missing for a real self-improving system?
- How to prevent learning wrong lessons from small samples?
- Statistical significance in recommendations
- Feature engineering from trade data
- Regime detection methodology (HMM, changepoint detection)
- A/B testing implementation: is it rigorous?
- Model decay detection

**Key Questions:**
1. Does the system actually learn from experience, or just log it?
2. If you removed Claude entirely, what would the system lose?
3. What's the minimum sample size before the system should make autonomous adjustments?

---

### Panel 3: ALGORITHMIC TRADING ADVISER
**Persona:** Built and deployed live trading bots. Has been burned by every production failure mode.
**Focus:**
- Production readiness: what breaks under real conditions?
- Execution: slippage, partial fills, API failures, reconnection
- Order management: atomic SL/TP, position reconciliation
- State management: local vs exchange, crash recovery
- Network resilience: retry logic, timeouts, rate limits
- Demo-to-live transition risks
- Monitoring, alerting, health checks
- Common mistakes that blow up small accounts
- Process management: watchdogs, auto-restart

**Key Questions:**
1. If you plugged this into real money right now, what would fail first?
2. What's the worst-case scenario if the agent crashes mid-trade?
3. What monitoring would you require before going live?

---

### Panel 4: SECURITY ENGINEER
**Persona:** AppSec specialist. Has audited trading platforms and financial APIs.
**Focus:**
- API key management: storage, rotation, access control
- .env file security: gitignore, permissions, exposure risk
- HMAC implementation: timing attacks, key length, algorithm choice
- Network security: HTTPS verification, certificate pinning
- Input validation: can malformed exchange data cause issues?
- Injection risks: SQL injection in journal, command injection
- Dependency supply chain: are packages pinned? Known vulns?
- Secrets in logs: are API keys ever printed/logged?
- Rate limiting: can the system be DoS'd via API?
- Error messages: do they leak sensitive information?

**Key Questions:**
1. If someone got read access to this repo, what could they steal?
2. If the exchange API returned malicious data, what would break?
3. What's the blast radius if an API key is compromised?

---

### Panel 5: DEVOPS / SRE ENGINEER
**Persona:** Runs production systems at scale. On-call veteran. Hates unmonitored services.
**Focus:**
- Deployment: how is this deployed? Docker? Bare metal? VPS?
- Process management: systemd/supervisord, auto-restart, graceful shutdown
- Logging: structured? Queryable? Log levels? Rotation?
- Monitoring: metrics, dashboards, alerting thresholds
- Backup and recovery: database backups, state persistence
- Resource management: memory leaks, CPU spikes, disk usage
- Configuration management: env vars, config files, secrets management
- Health checks: liveness, readiness probes
- Incident response: runbook for common failures
- Upgrade path: how to deploy new code without losing positions

**Key Questions:**
1. If this ran for 30 days unattended, what would break?
2. How would you know if the system is degraded but not dead?
3. What's the recovery procedure after a crash?

---

### Panel 6: DATA ENGINEER
**Persona:** Built real-time data pipelines for financial systems. Expert in data quality.
**Focus:**
- Data freshness: how stale is the price data?
- Data quality: missing candles, gaps, timezone issues
- Data pipeline reliability: what if Twelve Data/CCXT goes down?
- Storage: SQLite scaling, journal schema design, indexing
- Data validation: are candles validated (OHLC consistency)?
- Historical data: download reliability, deduplication, gap filling
- Time synchronization: NTP, clock drift, timezone handling
- Data formats: consistent timestamp formats across all modules
- Caching: is data cached? Cache invalidation?
- Data lineage: can you trace a trade decision back to specific candles?

**Key Questions:**
1. What happens when your data source returns garbage?
2. How would you detect that prices are stale or missing?
3. Is there an audit trail from candle data to trade decision?

---

### Panel 7: RISK / COMPLIANCE OFFICER
**Persona:** Prop firm compliance officer. Has seen every rule violation that gets traders banned.
**Focus:**
- FundingPips rule compliance: are ALL rules enforced?
- Consistency rule (45%): is it enforced correctly?
- News blackout: is the calendar accurate? Edge cases?
- Drawdown calculations: from what baseline? Static vs trailing?
- Position sizing: does it actually cap risk as claimed?
- Hedging detection: could the system accidentally hedge?
- Weekend gap risk: positions held over weekend?
- Slippage protection: max deviation from intended entry
- Audit trail: can every trade decision be reconstructed?
- Regulatory: any KYC/AML implications of automated trading?

**Key Questions:**
1. Could this system violate any FundingPips rule and get the account banned?
2. Are there edge cases where risk limits are bypassed?
3. Can you prove to FundingPips support that every trade was rule-compliant?

---

### Panel 8: MARKET MICROSTRUCTURE EXPERT
**Persona:** PhD in market microstructure. Studies order books, spreads, and execution quality.
**Focus:**
- Spread modeling: is the spread model realistic for each instrument?
- Slippage: how much slippage should be expected? Modeled correctly?
- Order book impact: does position size affect the market?
- Fill probability: market orders vs limit orders vs stop orders
- Latency: what's the order-to-fill latency? Does it matter?
- Time-of-day spread variation: spreads at London open vs Asian session
- Event-driven spread widening: how much wider during news?
- Funding rates: model accuracy for perpetual futures
- Tick size constraints: are prices aligned to valid tick sizes?
- Execution quality measurement: implementation shortfall, VWAP comparison

**Key Questions:**
1. Are the backtested fills realistic compared to what you'd get on the exchange?
2. At what position size does market impact become relevant?
3. Is the spread model accurate across all trading hours?

---

### Panel 9: BEHAVIORAL FINANCE / TRADING PSYCHOLOGY EXPERT
**Persona:** Trading psychologist. Has coached prop firm traders. Studies cognitive biases in automated systems.
**Focus:**
- Agent biases: does the system have equivalents of human cognitive biases?
- Confirmation bias: does the learning engine confirm existing beliefs?
- Recency bias: are recent trades over-weighted in decisions?
- Loss aversion: does the system over-react to losses?
- Revenge trading patterns: does the agent trade more after losses?
- Overconfidence: does high confluence score lead to oversized positions?
- Anchoring: does the system anchor to recent prices for SL/TP?
- Regime blindness: does the system "fight the trend"?
- Gambler's fallacy: does the loss streak throttle assume mean reversion?
- Human overseer psychology: what alerts would cause harmful intervention?

**Key Questions:**
1. If this system were a human trader, what bad habits would it have?
2. Does the autonomous agent have any equivalent of "tilt"?
3. How should the human overseer interact to avoid making things worse?

---

### Panel 10: CODE QUALITY / ARCHITECTURE REVIEWER
**Persona:** Staff engineer at a FAANG company. Expert in maintainable, testable systems.
**Focus:**
- Architecture: separation of concerns, dependency management
- Testing: coverage, quality, edge cases, integration tests
- Error handling: are exceptions handled? Do they propagate correctly?
- Concurrency: async patterns, race conditions, deadlocks
- Configuration: is config centralized? Overridable? Validated?
- Code organization: module boundaries, import cycles
- Type safety: type hints, validation at boundaries
- Persistence: database design, migration strategy
- API design: RESTful, consistent, versioned?
- Singleton abuse: are globals causing issues?

**Key Questions:**
1. Could a new developer understand and modify this codebase in a day?
2. What's the most fragile part of the system (change one thing, break everything)?
3. Are there any concurrency bugs waiting to happen?

---

## Step 4: Produce Mode A Output

For EACH panel, produce findings using this format:

```
## Panel N: [NAME] — Fresh Findings

### Issues Found
#### [ID]: [Short title] [Severity: P0/P1/P2/P3]
- **File:** path/to/file.py:line
- **Problem:** What's wrong and why it matters
- **Fix:** Specific, actionable fix
- **Impact:** What happens if not fixed

### What's Good
- List things that are well-implemented (the panel should acknowledge strengths too)

### Verdict
One sentence: is this system ready for live trading from this panel's perspective?
```

**Issue ID format:** Use panel abbreviation + number. QR=Quant, ML=AI/ML, AT=Algo, SE=Security, DO=DevOps, DE=Data, RC=Risk/Compliance, MM=Microstructure, BF=Psychology, CQ=Code Quality.

**IMPORTANT:** Do NOT reference previous issues. Do NOT say "this was fixed" or "this is better than before." You are seeing this codebase for the first time.

---

# MODE B: PROGRESS CHECK (After Mode A)

**Run this ONLY after Mode A is complete.**

## Step 1: Read the Issue Tracker

```
docs/reviews/ISSUES.md
```

## Step 2: Reconcile

For each finding from Mode A:
1. **Was it already in ISSUES.md?**
   - If yes and marked FIXED → The fix didn't work. Mark as REGRESSION.
   - If yes and marked DEFERRED → Still outstanding. Note it.
   - If yes and marked OPEN → Still broken. Note it.
2. **Is it a NEW issue not in ISSUES.md?**
   - Add it to the tracker with proper ID and severity.

For each FIXED issue in ISSUES.md:
1. **Did Mode A re-discover it?** → Fix was ineffective. Mark as REGRESSION.
2. **Did Mode A NOT find it?** → Fix is likely working. Mark as VERIFIED.

## Step 3: Produce Mode B Output

```
## Progress Report

### Regressions (fixes that didn't hold)
- [ID]: [description] — was marked FIXED but Mode A rediscovered it

### Verified Fixes (confirmed working)
- [ID]: [description] — Mode A did not rediscover this issue

### New Issues (not in previous tracker)
- [ID]: [description] — found fresh, not previously identified

### Still Outstanding
- [ID]: [description] — was DEFERRED/OPEN, still relevant

### Scorecard
| Status | Count |
|--------|-------|
| VERIFIED | X |
| REGRESSION | X |
| NEW | X |
| STILL OPEN | X |
```

## Step 4: Update Files

1. Update `docs/reviews/ISSUES.md` with new issues, regressions, and verifications
2. Update the REVIEW HISTORY table at the bottom of ISSUES.md

---

# PANEL SELECTION GUIDE

| If you changed... | Run these panels |
|-------------------|-----------------|
| Strategy code | 1 (Quant), 8 (Microstructure) |
| Learning engine | 2 (AI/ML), 9 (Psychology) |
| Broker / execution | 3 (Algo), 4 (Security), 5 (DevOps) |
| Data pipeline | 6 (Data), 8 (Microstructure) |
| Risk manager | 1 (Quant), 7 (Compliance) |
| Everything / major refactor | ALL PANELS |
| First review / every 5 sessions | ALL PANELS |
| Quick check | 3 (Algo), 7 (Compliance) |

---

# HOW TO RUN

### Full review (recommended after major sessions):
```
Read docs/reviews/REVIEW-PROMPT.md and run a fresh review (Mode A, all panels)
```
Then after Mode A completes:
```
Now run Mode B — read ISSUES.md and reconcile
```

### Quick review (between sessions):
```
Read docs/reviews/REVIEW-PROMPT.md and run a fresh review (Mode A, panels 3 and 7 only)
```

### Specific panels:
```
Read docs/reviews/REVIEW-PROMPT.md and run a fresh review (Mode A, panels 1, 2, 3)
```

---

# NOTES FOR CLAUDE

**Mode A rules:**
- You are seeing this codebase for the FIRST TIME. No memory of previous reviews.
- Do NOT read ISSUES.md. Do NOT reference previous findings.
- Be BRUTALLY honest. The user wants truth, not comfort.
- Reference specific file paths and line numbers.
- Every issue must have a concrete fix, not just "consider improving X."
- Severity must be actionable: P0 = fix now, P1 = fix before live, P2 = fix before scaling, P3 = improvement.
- Acknowledge what's good — not everything is broken.

**Mode B rules:**
- Now you CAN read ISSUES.md.
- Be rigorous: if Mode A found the same issue that's marked FIXED, that's a regression — don't be generous.
- If Mode A did NOT find a previously-reported issue, it's likely fixed — but verify with a quick code check if unsure.
- New issues get new IDs (continue the numbering from ISSUES.md).

**Context:**
- The user's goal: pass FundingPips challenge + trade on CoinDCX with small capital.
- The motto is EVOLVE: the system must actually learn and adapt, not just log.
- The system should be ready for Binance Demo paper trading NOW, and CoinDCX live after validation.
