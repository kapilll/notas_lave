# Build With Experts — Expert Panels as Engineers

**THE PROBLEM:** The review system finds 177 issues AFTER code is written. That's wasteful. If the experts were building the code, most issues wouldn't exist in the first place.

**THE SOLUTION:** Before implementing a feature or fix, invoke the relevant expert panels to DESIGN the solution. They write the code with their expertise baked in.

---

## How to Use

### When starting a task, say:

```
Read docs/reviews/BUILD-WITH-EXPERTS.md

I need to [describe what you want to build].

Build this as the following experts working together:
- [Panel name] for [their specialty]
- [Panel name] for [their specialty]
```

### Example prompts:

**Building a new broker integration:**
```
Build a Bybit broker integration. Work as:
- Algo Trading Engineer: retry logic, reconnection, order management
- Security Engineer: API key handling, HMAC signing, input validation
- Code Architect: match existing broker abstraction pattern
```

**Adding a new strategy:**
```
Add a Volume Profile strategy. Work as:
- Quant Researcher: statistical validity, avoid overfitting, proper backtestability
- Market Microstructure: realistic volume modeling, exchange-specific quirks
- Code Architect: match BaseStrategy interface, add tests
```

**Fixing a risk management bug:**
```
Fix the daily drawdown calculation. Work as:
- Risk/Compliance Officer: FundingPips exact rules, edge cases
- Quant Researcher: correct math, account for unrealized P&L
- Code Architect: test coverage, no regressions
```

---

## Expert Engineer Roles

### Quant Engineer
**Invoke when:** Building strategies, backtesting, position sizing, statistical analysis
**They ensure:**
- No look-ahead bias in signal generation
- Walk-forward compatible (candle timestamps, not datetime.now())
- Statistical significance before any conclusion
- Proper Sharpe/PF/DD calculations
- Transaction costs included

### AI/ML Engineer
**Invoke when:** Building learning features, feedback loops, optimization
**They ensure:**
- Feedback loops are actually closed (not just logged)
- Minimum sample sizes before adjustments
- No confirmation bias in the learning engine
- Persistence of learned state across restarts
- A/B testing for parameter changes

### Systems Engineer (Algo Trading)
**Invoke when:** Building broker integrations, execution, order management
**They ensure:**
- Retry logic with exponential backoff on all API calls
- Atomic operations (SL/TP together, not separate)
- Position reconciliation between local and exchange state
- Graceful degradation on failures
- Rate limit awareness

### Security Engineer
**Invoke when:** Handling API keys, auth, external data, user input
**They ensure:**
- No secrets in code, logs, or error messages
- HMAC signing with proper timing-attack resistance
- Input validation on all external data
- API endpoints have authentication
- .env files have correct permissions

### DevOps Engineer
**Invoke when:** Deployment, monitoring, reliability
**They ensure:**
- Structured logging (not just print statements)
- Health checks and heartbeats
- Graceful shutdown with position safety
- State persistence across restarts
- Docker/systemd configuration

### Risk Engineer
**Invoke when:** Anything touching position sizing, drawdown, trade validation
**They ensure:**
- Mode-aware rules (prop vs personal)
- No bypass paths around risk checks
- Unrealized P&L included in drawdown
- Edge cases: weekend gaps, halts, split positions
- Audit trail for every trade decision

### Data Engineer
**Invoke when:** Data pipelines, storage, caching, historical data
**They ensure:**
- OHLC validation (high >= low, etc.)
- Timezone consistency (UTC everywhere)
- Cache invalidation handled properly
- Gap detection in candle data
- Proper indexing on database tables

### Code Architect
**Invoke when:** Any new module, refactoring, API design
**They ensure:**
- Follows existing patterns (BaseStrategy, BaseBroker, etc.)
- Tests written alongside code
- No singleton abuse or circular imports
- Error handling at boundaries
- Type hints on public interfaces

---

## The Build Protocol

When Claude is asked to build with experts, follow this protocol:

### 1. DESIGN (experts discuss)
Each expert states their requirements for the feature in 2-3 bullet points.
If experts disagree, resolve before writing code.

### 2. BUILD (write code with expertise baked in)
Write the code once, correctly, with all expert concerns addressed.
Don't write naive code and then fix it — write expert-level code from the start.

### 3. VERIFY (experts check their concerns)
Each expert confirms their requirements are met.
If any expert has an objection, fix before committing.

### 4. TEST
Write tests that cover the expert concerns (not just happy path).

---

## Quick Reference: Which Experts for What

| Task | Experts to invoke |
|------|------------------|
| New strategy | Quant + Code Architect |
| New broker | Systems + Security + Code Architect |
| Risk management | Risk + Quant |
| Learning feature | AI/ML + Quant |
| API endpoint | Code Architect + Security |
| Data pipeline | Data + Systems |
| Deployment | DevOps + Security |
| Bug fix (any) | Code Architect + domain expert for that area |
| Performance issue | Systems + Data |
| UI feature | Code Architect (frontend) |
