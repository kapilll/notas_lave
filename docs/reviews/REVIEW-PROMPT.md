# Notas Lave — Reusable Expert Review Prompt

**PURPOSE:** Run this prompt every few sessions to review the system from multiple expert perspectives. Claude reads the codebase, then role-plays each panel, finding issues and tracking fixes.

**HOW TO USE:**
1. Start a new session
2. Say: "Read docs/reviews/REVIEW-PROMPT.md and run the review"
3. Claude will read the core files, check previous issues, and produce an updated review
4. New issues get added to docs/reviews/ISSUES.md
5. Fixed issues get marked VERIFIED

**FREQUENCY:** Every 3-5 sessions, or after major changes.

---

## STEP 1: Read Context

Read these files first (in this order):
```
docs/context/SESSION-CONTEXT.md          # Current state
docs/reviews/ISSUES.md                    # Previous issues
CLAUDE.md                                 # Project rules
```

## STEP 2: Read Core System Files

```
engine/src/agent/autonomous_trader.py     # The autonomous loop
engine/src/agent/trade_learner.py         # Per-trade Claude analysis
engine/src/agent/config.py                # Agent permissions and safety
engine/src/backtester/engine.py           # Backtester + risk levers + blacklists
engine/src/strategies/registry.py         # Strategy registration
engine/src/strategies/rsi_divergence.py   # Key strategy (sole crypto survivor)
engine/src/confluence/scorer.py           # Signal combination + regime detection
engine/src/risk/manager.py               # The gatekeeper
engine/src/execution/binance_testnet.py   # Exchange broker
engine/src/data/instruments.py            # Instrument specs + position sizing
engine/src/data/economic_calendar.py      # News blackout
engine/src/learning/analyzer.py           # Trade analysis engine
engine/src/learning/recommendations.py    # Actionable suggestions
engine/src/learning/optimizer.py          # Walk-forward parameter tuning
engine/tests/test_instruments.py          # Position sizing tests
engine/tests/test_strategies.py           # Strategy output tests
```

Also check any new files not in this list (use glob for new .py files).

## STEP 3: Run Selected Panels

Pick which panels to run based on what changed since last review.
Each panel has a specific focus and produces structured findings.

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
- Monte Carlo / permutation testing
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
- A/B testing and experiment design
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

## STEP 4: Produce Output

For EACH panel run, produce:

### New Issues Found
```
### XX-NN: Short title [Severity]
- **Status:** OPEN
- **File:** path/to/file.py:line
- **Problem:** What's wrong and why it matters
- **Fix:** Specific, actionable fix
- **Impact:** What happens if not fixed
```

### Previously Fixed Issues
For each issue in ISSUES.md that has been fixed:
```
### XX-NN: Mark as VERIFIED
- **Evidence:** What test/code confirms the fix
```

### Regressions
Any previously fixed issues that have regressed.

### Summary Table Update
Update the summary counts in ISSUES.md.

---

## STEP 5: Update Files

1. Append new issues to `docs/reviews/ISSUES.md`
2. Update status of fixed issues to VERIFIED
3. Update the REVIEW HISTORY table at the bottom
4. Update `docs/context/SESSION-CONTEXT.md` with review findings if significant

---

## PANEL SELECTION GUIDE

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

## NOTES FOR CLAUDE

- Be BRUTALLY honest. The user wants truth, not comfort.
- Reference specific file paths and line numbers.
- Every issue must have a concrete fix, not just "consider improving X."
- Check if previous issues (ISSUES.md) have been fixed — don't re-report them.
- Severity must be actionable: P0 = fix now, P1 = fix before live, etc.
- The user's goal: pass FundingPips challenge + trade on CoinDCX with small capital.
- The motto is EVOLVE: the system must actually learn and adapt, not just log.
- Keep the review focused: 48 issues last time was comprehensive. Future reviews should be shorter unless major changes happened.
- Cross-reference with previous review to show progress.
