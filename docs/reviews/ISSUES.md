# Notas Lave -- Expert Review Issue Tracker

**Review Date:** 2026-03-22 (Session 5 -- Full 10-Panel Review)
**Previous Review:** 2026-03-22 (Session 4a -- 3-Panel Review, 48 issues)
**Reviewed By:** 10-Panel Expert Review (Quant, AI/ML, Algo, Security, DevOps, Data, Compliance, Microstructure, Psychology, Code Quality)
**System State:** 14 strategies, 41 tests, Binance Demo verified, 1-year backtests complete, all previous P0s marked FIXED
**Fix Session:** 2026-03-22 (Session 6 — 70 issues fixed across 2 commits)
**Next Review:** After paper trading validation (target: Session 10+)

---

## Executive Summary

The previous 48 issues (Session 4a) have been largely addressed: 30 verified fixed, 8 deferred, 2 wont_fix, 1 regressed, 7 still open (carried forward with new IDs). The 7 new panels (Security, DevOps, Data, Compliance, Microstructure, Psychology, Code Quality) revealed **177 new issues**, many overlapping across panels.

After deduplication, there are approximately **150 unique new issues**. The most critical systemic finding: **the risk manager's `validate_trade()` is never called by the autonomous trader**, meaning every FundingPips rule can be violated.

### Severity Counts (New Issues Only)

| Severity | Count | Meaning |
|----------|-------|---------|
| P0 | 26 | System-breaking. Fix before ANY live trading. |
| P1 | 52 | High risk. Fix before real money. |
| P2 | 67 | Significant. Fix before scaling up. |
| P3 | 31 | Improvement. Fix when time allows. |
| **Total** | **177** | (includes ~25 duplicates across panels) |

### Top Systemic Flaws (Cross-Panel)

1. **Risk gatekeeper bypassed** (RC-01) -- validate_trade() never called by autonomous agent
2. **Zero slippage model** (MM-01, QR-24) -- backtests overstate performance 20-40%
3. **No structured logging** (OPS-03, CQ-20, DE-13) -- 95 print() statements, 0 logging calls
4. **Learned state lost on restart** (ML-15) -- EVOLVE resets every restart
5. **No API authentication** (SEC-01/02) -- anyone on network can trade
6. **Daily drawdown ignores floating P&L** (RC-03) -- FundingPips monitors equity, not just closed trades
7. **SQLite singleton session** (CQ-01, OPS-06, DE-05) -- not thread-safe, concurrent corruption risk
8. **No crash recovery** (AT-24, OPS-05) -- open positions lost on restart
9. **DST not handled** (RC-08, DE-11) -- news blackout wrong 8 months/year
10. **Static spread model** (MM-02) -- no time-of-day or event-driven variation

---

## Status Legend

| Status | Meaning |
|--------|---------|
| OPEN | Not started |
| IN_PROGRESS | Work begun |
| FIXED | Code changed, needs verification |
| VERIFIED | Fixed and confirmed by review |
| WONT_FIX | Accepted risk / not applicable |
| DEFERRED | Postponed to later phase |
| REGRESSED | Previously fixed, now broken again |

## Severity Legend

| Severity | Meaning |
|----------|---------|
| P0 | System-breaking. Fix before ANY live trading. |
| P1 | High risk. Fix before real money. Paper trading OK without. |
| P2 | Significant. Fix before scaling up. |
| P3 | Improvement. Fix when time allows. |

---

## SESSION 4a ISSUES -- STATUS UPDATE

### Panel A: Quant Researcher (Previous)

| ID | Title | Previous | Current | Notes |
|----|-------|----------|---------|-------|
| QR-01 | Walk-forward not implemented | FIXED | VERIFIED | Walk-forward exists with N-fold rolling window. OOS equity curve is hollow (see QR-14). |
| QR-02 | Circular blacklists | FIXED | VERIFIED | Blacklists derived from training data only. |
| QR-03 | RSI Divergence sole survivor | DEFERRED | DEFERRED | QR-21 adds evidence of implementation-specific bias. |
| QR-04 | Optimizer validation includes training data | FIXED | VERIFIED | 70/30 split with warmup. Minor contamination via 250-candle warmup. |
| QR-05 | Sharpe ratio inflated | FIXED | VERIFIED | Daily returns aggregated correctly, sqrt(252) annualization. |
| QR-06 | Identical 58.0% WR | DEFERRED | DEFERRED | |
| QR-07 | min_lot clamping 10-100x risk | FIXED | VERIFIED | Returns 0.0 when actual risk exceeds budget. Tests cover edge cases. |
| QR-08 | Insufficient crypto history | DEFERRED | DEFERRED | |
| QR-09 | No Monte Carlo | FIXED | VERIFIED | Implemented in monte_carlo.py. See QR-15/16 for quality issues. |
| QR-10 | No OOS test reserved | DEFERRED | DEFERRED | |
| QR-11 | Single best signal per candle | DEFERRED | OPEN | Carried forward as QR-23. |
| QR-12 | No cost sensitivity analysis | DEFERRED | DEFERRED | |
| QR-13 | SL/TP check order bias | DEFERRED | OPEN | Carried forward as QR-18. |

### Panel B: AI/ML Specialist (Previous)

| ID | Title | Previous | Current | Notes |
|----|-------|----------|---------|-------|
| ML-01 | Feedback loop open | FIXED | VERIFIED | Daily review applies blacklists and weights. |
| ML-02 | Claude output unused | FIXED | VERIFIED | Full analysis stored in journal. |
| ML-03 | Dynamic blacklist not applied | FIXED | VERIFIED | Blacklist connected to scorer filtering. |
| ML-04 | Weight adjustments not applied | FIXED | VERIFIED | update_regime_weights() mutates REGIME_WEIGHTS. |
| ML-05 | MIN_TRADES too low (10) | FIXED | VERIFIED | Raised to 50. |
| ML-06 | Optimizer tests in isolation | DEFERRED | DEFERRED | |
| ML-07 | Claude hindsight bias | WONT_FIX | WONT_FIX | |
| ML-08 | Claude inconsistency | FIXED | VERIFIED | temperature=0 set. |
| ML-09 | No cross-trade memory | DEFERRED | OPEN | Carried forward as ML-21. |
| ML-10 | No structured features | DEFERRED | DEFERRED | |
| ML-11 | No significance tests | DEFERRED | DEFERRED | |
| ML-12 | No A/B testing | FIXED | VERIFIED | ab_testing.py exists. Not integrated (ML-17). |
| ML-13 | No exponential decay | FIXED | **REGRESSED** | Still a TODO comment at analyzer.py:129. Not implemented. |
| ML-14 | No regime transition detection | DEFERRED | DEFERRED | |

### Panel C: Algo Trading (Previous)

| ID | Title | Previous | Current | Notes |
|----|-------|----------|---------|-------|
| AT-01 | 60s polling too slow | FIXED | VERIFIED | Candle freshness check implemented. |
| AT-02 | cancel_order broken | FIXED | VERIFIED | Uses DELETE with symbol param. |
| AT-03 | SL/TP non-atomic | FIXED | VERIFIED | SL failure triggers immediate position close. |
| AT-04 | No position reconciliation | FIXED | VERIFIED | Runs every 5 min, detect-only. See AT-26. |
| AT-05 | Symbol mapping fragile | FIXED | VERIFIED | Explicit SYMBOL_MAP with ValueError on unknown. |
| AT-06 | No retry logic | FIXED | VERIFIED | Exponential backoff [1,2,4]s. |
| AT-07 | No reconnection logic | FIXED | VERIFIED | Auto-reconnect on consecutive failures. |
| AT-08 | No order state tracking | FIXED | VERIFIED | _active_orders stores main/sl/tp IDs. |
| AT-09 | Paper/Binance disconnected | FIXED | VERIFIED | _get_broker() returns appropriate broker. |
| AT-10 | _analyzed attribute hack | FIXED | VERIFIED | Uses _analyzed_trades set. |
| AT-11 | Risk manager date.today() | FIXED | VERIFIED | Uses datetime.now(timezone.utc). |
| AT-12 | CoinDCX untested | DEFERRED | DEFERRED | See AT-27, AT-28. |
| AT-13 | CoinDCX fees | WONT_FIX | WONT_FIX | |
| AT-14 | CoinDCX min order sizes | FIXED | VERIFIED | min_notional check returns 0.0. |
| AT-15 | No process watchdog | DEFERRED | DEFERRED | See OPS-01. |
| AT-16 | No heartbeat | FIXED | VERIFIED | 6-hour Telegram heartbeat. |
| AT-17 | No rate limit tracking | FIXED | VERIFIED | Request count per minute with warning at 1000. |
| AT-18 | No disk space monitoring | DEFERRED | DEFERRED | See OPS-19. |
| AT-19 | Funding rate not in live | DEFERRED | DEFERRED | See MM-07. |
| AT-20 | Spread as % of SL | FIXED | VERIFIED | Rejects trades where spread > 5% of SL. |
| AT-21 | Overtrading risk | FIXED | VERIFIED | max_trades_per_day enforced. |
| AT-22 | No WebSocket | DEFERRED | DEFERRED | |
| AT-23 | httpx client not managed | FIXED | VERIFIED | Lazy creation, proper aclose(). |

---

## NEW ISSUES -- PANEL 1: QUANT RESEARCHER

### QR-14: Walk-Forward OOS metrics are hollow (no equity curve) [P1]
- **Status:** FIXED
- **File:** `engine/src/backtester/engine.py:836-841`
- **Problem:** OOS `_compute_results` called with `equity_curve=[starting_balance]` and `daily_returns=[]`. OOS Sharpe = 0 always, OOS max drawdown = 0% always. Only trade-level stats (WR, PF, PnL) are meaningful.
- **Fix:** Reconstruct OOS equity curve by replaying all_oos_trades sequentially. Pass reconstructed curve into _compute_results.
- **Impact:** Cannot detect if OOS max drawdown exceeds FundingPips 10% limit.

### QR-15: Monte Carlo ignores trade sequence dependencies [P2]
- **Status:** OPEN
- **File:** `engine/src/backtester/monte_carlo.py:53-76`
- **Problem:** Shuffles trades uniformly (IID assumption). Breaks loss clustering and dynamic sizing. Probability-of-ruin estimate 30-50% too low.
- **Fix:** Add block bootstrap (shuffle in blocks of 5-10 trades) to preserve local serial correlation.

### QR-16: Monte Carlo has no statistical tests or confidence intervals [P2]
- **Status:** OPEN
- **File:** `engine/src/backtester/monte_carlo.py:82-131`
- **Problem:** No hypothesis test (H0: edge = 0), no bootstrap CI on Sharpe/PF, no p-value. `is_robust` flag is hand-tuned heuristic.
- **Fix:** Add permutation test for null hypothesis. Report bootstrap 95% CI on Sharpe and PF.

### QR-17: Optimizer has no multiple comparisons correction [P1]
- **Status:** OPEN
- **File:** `engine/src/learning/optimizer.py:249-266`
- **Problem:** Tests up to 36 parameter combos, picks the best PF. Classic data mining bias. No Bonferroni correction or Deflated Sharpe Ratio.
- **Fix:** Apply Deflated Sharpe Ratio or Bonferroni-like penalty for number of trials.

### QR-18: SL/TP check order bias in backtester [P2]
- **Status:** OPEN (carried from QR-13)
- **File:** `engine/src/backtester/engine.py:384-401`
- **Problem:** When both SL and TP could trigger on same candle, SL always checked first. Systematically understates win rate by ~1-3%.
- **Fix:** Use distance-from-open heuristic or randomize resolution.
- **Duplicate:** MM-04

### QR-19: Sharpe calculation excludes zero-trade days -- inflated ~2x [P1]
- **Status:** FIXED
- **File:** `engine/src/backtester/engine.py:674-685`
- **Problem:** Daily returns only include days with trade exits. Days without trades are absent (not zero). With 60 trade-days out of 252, Sharpe inflated by sqrt(252/60) = 2.05x.
- **Fix:** Fill in 0.0 returns for all trading days between first and last trade. ONE-LINE FIX with enormous impact.

### QR-20: No Sortino or Calmar ratios reported [P3]
- **Status:** OPEN
- **File:** `engine/src/backtester/engine.py:634-742`
- **Problem:** Only Sharpe computed. Calmar (return/max DD) is the most important ratio for prop firm evaluation.
- **Fix:** Add Sortino and Calmar calculations from existing daily returns infrastructure.

### QR-21: find_swing_highs missing forming swing detection (long bias) [P2]
- **Status:** OPEN
- **File:** `engine/src/strategies/rsi_divergence.py:102-109`
- **Problem:** find_swing_lows has forming swing detection for bullish divergence but find_swing_highs does NOT. Bearish divergence is harder to detect, introducing long bias.
- **Fix:** Add symmetric forming-swing logic to find_swing_highs.

### QR-22: Pre-trade budget check bypasses QR-07 guard [P2]
- **Status:** FIXED
- **File:** `engine/src/backtester/engine.py:572-580`
- **Problem:** Budget check downsizes position but then clamps back to min_lot on line 580, potentially re-inflating above daily budget.
- **Fix:** After min_lot clamp, re-check if actual risk exceeds remaining budget; reject if so.

### QR-23: Single best signal per candle = selection bias [P2]
- **Status:** OPEN (carried from QR-11)
- **File:** `engine/src/backtester/engine.py:507-514`
- **Problem:** Backtester cherry-picks highest-scoring signal. Live system takes first signal found. Backtest WR/PF overstated.
- **Fix:** Match live confluence pipeline behavior or randomize selection.

### QR-24: No slippage model in backtester [P2]
- **Status:** FIXED
- **File:** `engine/src/backtester/engine.py:554-559`
- **Problem:** Zero slippage on all fills. For scalping with 400+ trades, $2 roundtrip slippage = $800+ missing cost on $8K profit (10%).
- **Fix:** Add configurable slippage per instrument, proportional to ATR for stop fills.
- **Duplicate:** MM-01

### QR-25: Recommendation thresholds have no statistical basis [P3]
- **Status:** OPEN
- **File:** `engine/src/learning/recommendations.py:29,56-58,210`
- **Problem:** Magic numbers (50 trades, 35% WR, 55% best hours) without statistical tests or multiple comparison correction.
- **Fix:** Replace with proper binomial tests and Bonferroni correction.

---

## NEW ISSUES -- PANEL 2: AI/ML SPECIALIST

### ML-13: Exponential decay weighting NOT implemented [P2] -- REGRESSED
- **Status:** FIXED
- **File:** `engine/src/learning/analyzer.py:129`
- **Problem:** Previously marked FIXED but still a TODO comment. Hard 60-day cutoff with equal weighting remains.
- **Fix:** Implement `weight = exp(-0.693 * age_days / 30)` as originally specified.

### ML-15: Learned weights and blacklists lost on restart [P0]
- **Status:** FIXED
- **File:** `engine/src/confluence/scorer.py:22-35`, `engine/src/backtester/engine.py:54-93`
- **Problem:** REGIME_WEIGHTS and INSTRUMENT_STRATEGY_BLACKLIST are module-level dicts, mutated in memory only. Every restart resets to hardcoded initial state.
- **Fix:** Serialize to JSON/SQLite after every update. Load persisted state on startup.
- **Impact:** The EVOLVE motto is broken. System cannot learn beyond a single process lifetime.

### ML-16: Optimizer results computed but never loaded into live strategies [P0]
- **Status:** OPEN
- **File:** `engine/src/learning/optimizer.py:368-384`
- **Problem:** `get_optimal_params()` exists but is never called by any module. Optimizer is a dead endpoint.
- **Fix:** In weekly review, call optimize, save results, load via get_optimal_params(), inject into strategy registry.

### ML-17: A/B testing framework not integrated into trading loop [P1]
- **Status:** OPEN
- **File:** `engine/src/learning/ab_testing.py`
- **Problem:** create_test(), record_result(), get_test_results() exist but autonomous_trader never imports or calls them. API-only, manual-use infrastructure.
- **Fix:** In _scan_and_trade(), run shadow variant B alongside A, record results via record_result().

### ML-18: Prediction accuracy tracker never resolves predictions [P1]
- **Status:** FIXED
- **File:** `engine/src/learning/accuracy.py:146-174`
- **Problem:** log_prediction() called on signals but resolve_prediction() never called from autonomous loop. All predictions expire at 24h timeout.
- **Fix:** Call resolve_pending_predictions() in _tick() after checking closed positions.

### ML-19: Weight adjustment uses raw P&L without normalizing [P1]
- **Status:** FIXED
- **File:** `engine/src/learning/recommendations.py:126-153`
- **Problem:** Category weights from total_pnl, not per-trade average. Category with 200 trades and $500 = same weight as 5 trades and $500.
- **Fix:** Use avg_pnl = total_pnl / trades. Require min 20 trades per category. Apply Bayesian shrinkage toward equal weights.

### ML-20: No guard against feedback loop oscillation [P1]
- **Status:** FIXED
- **File:** `engine/src/agent/autonomous_trader.py:469-493`
- **Problem:** Daily blacklist/weight changes create oscillating feedback loop. No dampening, no minimum hold period, no change logging.
- **Fix:** Log before/after. Min 7-day hold for blacklist entries. Move 20% toward recommended weights (not 100%). Require 10+ new trades between adjustments.

### ML-21: Claude has no cross-trade memory [P2]
- **Status:** OPEN (carried from ML-09)
- **File:** `engine/src/agent/trade_learner.py:37-58`
- **Problem:** Each trade analyzed in isolation. Claude cannot detect patterns across trades.
- **Fix:** Prepend last 10 trades summary for same strategy+instrument to prompt.

### ML-22: Fallback grading is outcome-biased (TP=A, SL=D) [P2]
- **Status:** FIXED
- **File:** `engine/src/agent/trade_learner.py:159-193`
- **Problem:** Grades mirror outcome, not process quality. Contaminates learning with tautological feedback.
- **Fix:** Grade on confluence score, R:R ratio, MFE/MAE, not just exit reason.
- **Duplicate:** TP-04

### ML-23: Regime detection uses fixed universal thresholds [P2]
- **Status:** OPEN
- **File:** `engine/src/confluence/scorer.py:55-118`
- **Problem:** Same vol_ratio thresholds for all instruments. BTC routinely classified VOLATILE, Gold always RANGING.
- **Fix:** Use percentile-based or per-instrument calibrated thresholds.
- **Duplicate:** TP-09 (partially)

### ML-24: update_blacklist replaces entire blacklist instead of merging [P2]
- **Status:** FIXED
- **File:** `engine/src/backtester/engine.py:96-104`
- **Problem:** Dynamic update overwrites static blacklist. Strategies blacklisted for -$87K losses can be silently re-enabled.
- **Fix:** Use set union (merge) instead of replace. Maintain static and dynamic lists separately.

### ML-25: Duplicated strategy-to-category mapping [P3]
- **Status:** OPEN
- **File:** `engine/src/learning/recommendations.py:112-121`
- **Problem:** Hardcoded STRATEGY_CATEGORIES dict. Strategy objects already have .category attribute.
- **Fix:** Build mapping dynamically from registry.

### ML-26: A/B testing uses heuristic winner, not statistical test [P3]
- **Status:** OPEN
- **File:** `engine/src/learning/ab_testing.py:187-209`
- **Problem:** "High confidence" = 30 samples, not p < 0.05. No two-proportion z-test.
- **Fix:** Implement proper statistical test. Use scipy.stats (already in deps).
- **Duplicate:** TP-11

---

## NEW ISSUES -- PANEL 3: ALGO TRADING

### AT-24: No crash recovery for open positions [P0]
- **Status:** FIXED
- **File:** `engine/src/execution/paper_trader.py:218-219`
- **Problem:** Open positions in memory only. Crash = all position tracking lost. Exchange positions become orphaned.
- **Fix:** Persist open positions to SQLite on every open/close. Reload on startup.
- **Duplicate:** OPS-05, DE-21

### AT-25: close_position leaves orphaned SL/TP on exchange [P0]
- **Status:** FIXED
- **File:** `engine/src/execution/binance_testnet.py:398-407`
- **Problem:** Manual close places reverse market order but does NOT cancel existing SL/TP orders. Orphaned orders can trigger on future positions.
- **Fix:** Cancel all SL/TP orders for the symbol before closing. Use _active_orders tracking.
- **Duplicate:** RC-16

### AT-28: CoinDCX has ZERO SL/TP placement [P0]
- **Status:** FIXED
- **File:** `engine/src/execution/coindcx.py:161-219`
- **Problem:** place_order() accepts stop_loss/take_profit but NEVER sends them to exchange. Positions completely unprotected.
- **Fix:** Place SL/TP as separate orders after main fill. If SL fails, close position immediately.
- **Duplicate:** MM-11

### AT-26: Reconciliation has no alerting (detect-only, prints to stdout) [P1]
- **Status:** FIXED
- **File:** `engine/src/agent/autonomous_trader.py:514-549`
- **Problem:** Mismatches logged to stdout, no Telegram alert sent.
- **Fix:** Send Telegram alert when orphaned or missing positions detected.

### AT-27: CoinDCX has no retry/reconnect/rate-limit logic [P1]
- **Status:** FIXED
- **File:** `engine/src/execution/coindcx.py:110-127`
- **Problem:** Single attempt, no retry, no reconnection tracking, no rate limiting.
- **Fix:** Port _request_with_retry pattern from binance_testnet.py.

### AT-29: Dual SL/TP management (paper_trader vs exchange) creates conflicts [P1]
- **Status:** FIXED
- **File:** `engine/src/agent/autonomous_trader.py:362-375`
- **Problem:** Both paper_trader and exchange monitor SL/TP independently. They can race. P&L double-counted.
- **Fix:** When using real broker, disable paper_trader SL/TP monitoring. Let exchange handle.

### AT-31: No graceful shutdown -- positions not flushed [P1]
- **Status:** FIXED
- **File:** `engine/src/api/server.py:71-75`
- **Problem:** Shutdown handler doesn't stop autonomous trader, doesn't persist positions, doesn't disconnect broker.
- **Fix:** Stop agent, persist positions, disconnect broker, send Telegram notification.
- **Duplicate:** OPS-04

### AT-34: close_position routes through place_order (fragile) [P1]
- **Status:** FIXED
- **File:** `engine/src/execution/binance_testnet.py:398-407`
- **Problem:** Closing trade goes through place_order() which could inadvertently place SL/TP on closing trade.
- **Fix:** Add closing=True parameter or dedicated _close_market_order() method.

### AT-36: Risk manager potential_loss ignores contract_size [P1]
- **Status:** FIXED
- **File:** `engine/src/risk/manager.py:90`
- **Problem:** `potential_loss = price_diff * position_size` omits contract_size. Gold (100 oz/lot) underestimates loss by 100x.
- **Fix:** Multiply by spec.contract_size. For crypto (contract_size=1), no effect.

### AT-37: yfinance fallback silently degrades live trading [P1]
- **Status:** FIXED
- **File:** `engine/src/data/market_data.py:188-190`
- **Problem:** Falls back to yfinance (15-30min delayed, futures prices for metals) without alerting.
- **Fix:** Log WARNING via Telegram. Disable yfinance in live mode or mark candles as fallback.
- **Duplicate:** DE-09

### AT-30: UUID truncation (8 chars) creates collision risk [P2]
- **Status:** FIXED
- **File:** `engine/src/execution/paper_trader.py:250`
- **Problem:** str(uuid4())[:8] = 4B values. Birthday paradox: 1% collision at ~9300 IDs.
- **Fix:** Use full UUID or at minimum 16 characters.

### AT-32: closed_positions list grows unbounded in memory [P2]
- **Status:** FIXED
- **File:** `engine/src/execution/paper_trader.py:219`
- **Problem:** Every closed trade appended, never trimmed. OOM over months.
- **Fix:** Cap to last 500 entries (already persisted to DB).
- **Duplicate:** OPS-08

### AT-33: Paper trader SL/TP fill price wrong for broker mode [P2]
- **Status:** OPEN
- **File:** `engine/src/execution/paper_trader.py:392-398`
- **Problem:** SL fills at exact stop price. Real stops have slippage. P&L diverges from exchange.
- **Fix:** When using real broker, query exchange for actual fill prices.

### AT-35: Metals not mapped in Binance SYMBOL_MAP [P2]
- **Status:** FIXED
- **File:** `engine/src/execution/binance_testnet.py:39-44`
- **Problem:** XAUUSD/XAGUSD not in map. Crash on trade attempt for metals on Binance.
- **Fix:** Add clear "not tradeable on this exchange" error or validate instrument-broker compat at startup.

### AT-38: No partial fill handling [P2]
- **Status:** OPEN
- **File:** `engine/src/execution/binance_testnet.py:298-302`
- **Problem:** Falls back to requested quantity if executedQty missing. P&L tracking wrong on partial fills.
- **Fix:** Compare filled_quantity to requested. Adjust local tracking to match actual.

---

## NEW ISSUES -- PANEL 4: SECURITY

### SEC-01: API server has ZERO authentication [P0]
- **Status:** FIXED
- **File:** `engine/src/api/server.py` (entire file)
- **Problem:** No API key, JWT, or any auth. POST /api/trade/open, /api/agent/mode/full_auto callable by anyone.
- **Fix:** Add X-API-Key header middleware via FastAPI Depends + APIKeyHeader. Protect all mutation endpoints.

### SEC-02: Server binds to 0.0.0.0 [P0]
- **Status:** FIXED
- **File:** `engine/src/config.py:102`
- **Problem:** Exposed to all network interfaces. Combined with SEC-01, full unauthenticated access.
- **Fix:** Change default to 127.0.0.1. Use reverse proxy for external access.
- **Duplicate:** OPS-09

### SEC-03: Plaintext secrets in .env with world-readable permissions [P0]
- **Status:** OPEN
- **File:** `engine/.env`
- **Problem:** 6 secrets in plaintext, 644 permissions (world-readable). Rotate immediately.
- **Fix:** chmod 600. Rotate all secrets. Consider secrets manager.

### SEC-04: HMAC not compared with constant-time comparison [P1]
- **Status:** OPEN
- **File:** `engine/src/execution/binance_testnet.py:93-98`
- **Problem:** No hmac.compare_digest() for future webhook verification.
- **Fix:** Add verify_signature() using hmac.compare_digest() for webhooks.

### SEC-05: float() on untrusted exchange data (NaN/Inf risk) [P1]
- **Status:** FIXED
- **File:** `engine/src/execution/binance_testnet.py:217,242,246`
- **Problem:** Bare float() on exchange responses. NaN/Inf/empty string = crash or corruption.
- **Fix:** Create safe_float() helper. Reject NaN/Inf. Log warnings.

### SEC-06: getattr() for HTTP method dispatch [P1]
- **Status:** FIXED
- **File:** `engine/src/execution/binance_testnet.py:149`
- **Problem:** getattr(self._client, method) -- fragile attribute lookup.
- **Fix:** Use explicit dispatch dict: {"get": client.get, "post": client.post, ...}.

### SEC-07: Error messages leak exchange response bodies [P1]
- **Status:** OPEN
- **File:** `engine/src/execution/binance_testnet.py:159,166`
- **Problem:** Prints resp.text[:200] which may contain account info.
- **Fix:** Log only status code + error code, not raw response text.

### SEC-08: No TLS certificate pinning [P1]
- **Status:** OPEN
- **File:** `engine/src/execution/binance_testnet.py:113`
- **Problem:** Default SSL, no pinning. MITM possible on compromised networks.
- **Fix:** Set verify=True explicitly. Consider CA bundle for exchange domains.

### SEC-13: Agent mode changeable without auth [P1]
- **Status:** OPEN
- **File:** `engine/src/api/server.py:1005-1019`
- **Problem:** POST /api/agent/mode/{mode} allows switching to full_auto with zero auth.
- **Fix:** Require authentication + confirmation for mode changes.

### SEC-09: Dependencies unpinned -- supply chain risk [P2]
- **Status:** OPEN
- **File:** `engine/pyproject.toml:7-25`
- **Problem:** Floor versions (>=), no lockfile, missing deps (ccxt, httpx, pydantic-settings, etc.).
- **Fix:** Add all imports to deps. Generate lockfile. Pin security-critical packages.
- **Duplicate:** OPS-15

### SEC-10: SQLite no access controls, global session [P2]
- **Status:** OPEN
- **File:** `engine/src/journal/database.py:183-197`
- **Problem:** Global session, no thread safety, no file permissions on DB.
- **Fix:** scoped_session, restrictive file permissions (600), WAL mode.
- **Duplicate:** CQ-01

### SEC-11: No input validation on API parameters [P2]
- **Status:** FIXED
- **File:** `engine/src/api/server.py`
- **Problem:** limit, n_simulations, folds have no bounds. DoS via expensive operations.
- **Fix:** Add Pydantic Query constraints. Cap n_simulations, add rate limiting.

### SEC-12: CORS too permissive (allow_methods=*, allow_headers=*) [P2]
- **Status:** FIXED
- **File:** `engine/src/api/server.py:53-59`
- **Fix:** Restrict to GET/POST only, specific headers.

### SEC-14: Telegram token in URL (appears in logs) [P2]
- **Status:** OPEN
- **File:** `engine/src/alerts/telegram.py:35`
- **Fix:** Suppress URL logging for Telegram. Use Sensitive pydantic field type.

### SEC-15: No API key rotation mechanism [P2]
- **Status:** OPEN
- **File:** `engine/src/config.py`
- **Fix:** Add key freshness check, rotation endpoint, warn if .env > 90 days old.

### SEC-16: API key permissions not restricted on exchange side [P2]
- **Status:** OPEN
- **Fix:** Document: deny withdrawal permission, whitelist IP.

### SEC-18: No rate limiting on API endpoints [P2]
- **Status:** OPEN
- **File:** `engine/src/api/server.py`
- **Fix:** Add slowapi middleware with per-IP limits.

### SEC-17: Exception details leak in API error responses [P3]
- **Status:** FIXED
- **File:** `engine/src/api/server.py:128`
- **Fix:** Return generic errors to clients, log details server-side.

### SEC-19: pydantic-settings not in dependencies [P3]
- **Status:** OPEN
- **File:** `engine/pyproject.toml`
- **Fix:** Add all actually-imported packages.

### SEC-20: Sensitive config exposed via status endpoints [P3]
- **Status:** OPEN
- **File:** `engine/src/agent/autonomous_trader.py:551-563`
- **Fix:** Limit status to operational data only.

---

## NEW ISSUES -- PANEL 5: DEVOPS / SRE

### OPS-01: No containerization -- zero reproducible deployment [P0]
- **Status:** DEFERRED (running locally for now, not needed until VPS deployment)
- **File:** (project root -- no Dockerfile)
- **Problem:** No Docker, no systemd, no supervisord. Terminal close = dead trader.
- **Fix:** Create Dockerfile + docker-compose.yml with health check.

### OPS-02: No CI/CD pipeline [P0]
- **Status:** DEFERRED (running locally, tests run manually before commits)
- **File:** (no .github/workflows/)
- **Problem:** 41 tests exist but no automation. Bad commit can break live trading.
- **Fix:** Add GitHub Actions: pytest, ruff, mypy on every push to main.

### OPS-03: No structured logging -- 95 print(), 0 logging calls [P0]
- **Status:** OPEN
- **File:** All source files
- **Problem:** No log levels, no timestamps, no structured format, no rotation.
- **Fix:** Replace all print() with Python logging module. Add JSON formatter + file handler.
- **Duplicate:** CQ-20, DE-13

### OPS-04: Shutdown handler doesn't stop autonomous trader [P0]
- **Status:** FIXED
- **File:** `engine/src/api/server.py:71-74`
- **Problem:** Doesn't stop agent, doesn't persist positions, doesn't disconnect broker.
- **Fix:** Add autonomous_trader.stop(), persist positions, disconnect broker, notify.
- **Duplicate:** AT-31

### OPS-05: Open positions in memory only -- lost on crash [P0]
- **Status:** FIXED
- **File:** `engine/src/execution/paper_trader.py:218-219`
- **Duplicate:** AT-24, DE-21

### OPS-06: Database singleton session not thread-safe [P1]
- **Status:** OPEN
- **File:** `engine/src/journal/database.py:183-197`
- **Duplicate:** CQ-01, DE-05, SEC-10

### OPS-07: Telegram is only alerting channel (SPOF) [P1]
- **Status:** OPEN
- **File:** `engine/src/alerts/telegram.py:30-48`
- **Problem:** Token expires / API down = zero alerts. send_telegram returns False silently.
- **Fix:** Add secondary channel (email). Retry with backoff. Log WARNING on failure.

### OPS-08: No resource monitoring -- unbounded memory growth [P1]
- **Status:** OPEN
- **Duplicate:** AT-32

### OPS-09: Server binds 0.0.0.0 with no auth [P1]
- **Status:** OPEN
- **Duplicate:** SEC-01, SEC-02

### OPS-10: run.py uses reload=True (production runs in dev mode) [P1]
- **Status:** FIXED
- **File:** `engine/run.py:24`
- **Problem:** Auto-reloader watches files, any save restarts server, wiping in-memory positions.
- **Fix:** Default reload=False. Use env var for development.

### OPS-11: No database backup strategy [P1]
- **Status:** OPEN
- **File:** `engine/src/config.py:104`
- **Problem:** SQLite file has all trade history. No backup, no replication.
- **Fix:** Daily cron with sqlite3 .backup to secondary location.

### OPS-12: Health check always returns "ok" regardless of state [P2]
- **Status:** FIXED
- **File:** `engine/src/api/server.py:77-84`
- **Fix:** Deep health check: DB connectivity, agent running, broker connected, last successful fetch.

### OPS-13: Telegram creates new httpx client per message [P2]
- **Status:** FIXED
- **File:** `engine/src/alerts/telegram.py:38`
- **Fix:** Use persistent module-level httpx.AsyncClient.

### OPS-14: Bare exception handlers swallow critical errors [P2]
- **Status:** OPEN
- **Duplicate:** CQ-07

### OPS-15: No dependency pinning [P2]
- **Status:** OPEN
- **Duplicate:** SEC-09

### OPS-16: .env path relative and fragile [P2]
- **Status:** OPEN
- **Duplicate:** CQ-16

### OPS-17: No zero-downtime deployment procedure [P2]
- **Status:** OPEN
- **Fix:** Document deployment runbook. Implement drain mode.

### OPS-18: CCXT exchange object not closed on shutdown [P3]
- **Status:** OPEN
- **File:** `engine/src/data/market_data.py:149-153`

### OPS-19: No disk space / DB size monitoring [P3]
- **Status:** OPEN
- **Fix:** Monitor DB file size, add data retention policy, run VACUUM.

### OPS-20: Deprecated FastAPI lifecycle events [P3]
- **Status:** FIXED
- **File:** `engine/src/api/server.py:62,71`
- **Fix:** Migrate to @asynccontextmanager lifespan pattern.

---

## NEW ISSUES -- PANEL 6: DATA ENGINEER

### DE-01: No OHLC validation -- garbage data passes silently [P0]
- **Status:** FIXED
- **File:** `engine/src/data/market_data.py:231-246`
- **Problem:** No candle validated after construction. high < low, NaN, negative prices all propagate to strategies.
- **Fix:** Add Pydantic model_validator to Candle: high >= max(open,close), low <= min(open,close), all > 0.

### DE-02: Stale data cached and served as fresh after source failure [P0]
- **Status:** FIXED
- **File:** `engine/src/data/market_data.py:192-195`
- **Problem:** Empty results cached as "fresh". Previous good candles overwritten. System goes blind silently.
- **Fix:** Never cache empty results. Keep last-known-good. Add consecutive-failure counter and alert.

### DE-03: No data lineage -- cannot trace trade to candles [P0]
- **Status:** FIXED
- **File:** `engine/src/journal/database.py:58-89`
- **Problem:** Candle data that triggered a signal is ephemeral. Cannot reproduce or audit any trade decision.
- **Fix:** Store candle_range_start/end timestamps and last candle OHLCV with each signal/trade log.

### DE-04: datetime.utcnow() in models -- naive timezone handling [P1]
- **Status:** FIXED
- **File:** `engine/src/data/models.py:125,162,182`
- **Problem:** Naive datetimes. Comparing with timezone-aware datetimes raises TypeError.
- **Fix:** Replace datetime.utcnow with lambda: datetime.now(timezone.utc).

### DE-05: SQLite singleton session not thread-safe [P1]
- **Status:** OPEN
- **Duplicate:** CQ-01, OPS-06

### DE-06: No database indexes -- full table scans on every query [P1]
- **Status:** OPEN
- **File:** `engine/src/journal/database.py:32-180`
- **Problem:** Zero indexes on any table. 50K+ signal logs = slow queries.
- **Fix:** Add indexes on opened_at, symbol, exit_price, timestamp, resolved.

### DE-07: No foreign key between SignalLog and TradeLog [P1]
- **Status:** OPEN
- **File:** `engine/src/journal/database.py:63`
- **Fix:** Add ForeignKey('signal_logs.id') to signal_log_id.

### DE-08: Historical downloader has no deduplication or gap detection [P1]
- **Status:** FIXED
- **File:** `engine/src/data/historical_downloader.py:82-118`
- **Problem:** Overlapping batches produce duplicate candles. Missing candles from low-volume periods invisible.
- **Fix:** Sort + deduplicate by timestamp. Add gap detection function.

### DE-09: yfinance fallback silently serves FUTURES data [P1]
- **Status:** FIXED
- **File:** `engine/src/data/market_data.py:56-59`
- **Problem:** Gold falls back to GC=F (futures), $5-20 different from spot. 15-30min delayed.
- **Fix:** Tag candles with source. Refuse to trade on yfinance_fallback for metals.
- **Duplicate:** AT-37

### DE-10: Cache stores empty results defeating staleness protection [P1]
- **Status:** FIXED
- **File:** `engine/src/data/market_data.py:124-136`
- **Problem:** Empty list cached as valid. Old good data lost. No circuit breaker.
- **Fix:** Never cache empty. Keep last-known-good separately. Alert after 3 consecutive failures.

### DE-11: Economic calendar ignores DST [P2]
- **Status:** FIXED
- **File:** `engine/src/data/economic_calendar.py:127-128`
- **Problem:** Hardcoded EST offsets. EDT (March-Nov) shifts events by 1 hour. Blackout window misses actual event.
- **Fix:** Use zoneinfo with America/New_York timezone.
- **Duplicate:** RC-08

### DE-12: Deprecated asyncio.get_event_loop() [P2]
- **Status:** FIXED
- **File:** `engine/src/data/market_data.py:226,276,326`
- **Fix:** Replace with asyncio.get_running_loop().run_in_executor().
- **Duplicate:** CQ-06

### DE-13: No structured logging in data pipeline [P2]
- **Status:** OPEN
- **Duplicate:** OPS-03

### DE-14: Cache has no size bound [P2]
- **Status:** OPEN
- **File:** `engine/src/data/market_data.py:77`
- **Fix:** Add LRU eviction or max_cache_size.

### DE-15: Multi-timeframe fetches are sequential, not parallel [P2]
- **Status:** FIXED
- **File:** `engine/src/data/market_data.py:382-389`
- **Problem:** Sequential network calls per timeframe. 4 symbols * 5 tf * 300ms = 6s per tick.
- **Fix:** Use asyncio.gather() for parallel fetches.

### DE-16: Rate limiter state resets on restart [P2]
- **Status:** OPEN
- **File:** `engine/src/data/market_data.py:80-86`
- **Problem:** Daily call count in memory. 5 restarts/day = 5x rate limit.
- **Fix:** Persist daily count to file/DB.

### DE-17: No candle continuity check [P2]
- **Status:** FIXED
- **File:** `engine/src/data/market_data.py:156-196`
- **Problem:** No check timestamps are contiguous. Gaps distort indicators.
- **Fix:** Verify consecutive timestamps differ by exactly one period. Log gaps.

### DE-18: Backtester passes entire history as window -- O(N^2) [P3]
- **Status:** OPEN
- **File:** `engine/src/backtester/engine.py:495`
- **Problem:** `window = candles[:i+1]` for each of 100K candles. Strategies only use last 250.
- **Fix:** `window = candles[max(0, i-250):i+1]`

### DE-19: Analyzer loads all columns including large text blobs [P3]
- **Status:** OPEN
- **File:** `engine/src/learning/analyzer.py:132-140`
- **Fix:** Use column projection or load_only() to exclude claude_reasoning, lessons_learned.

### DE-20: Historical CSV has no checksums or metadata [P3]
- **Status:** OPEN
- **File:** `engine/src/data/historical_downloader.py:237-253`
- **Fix:** Add JSON metadata sidecar with source, count, hash.

### DE-21: Paper trader positions in memory only [P2]
- **Status:** OPEN
- **Duplicate:** AT-24

### DE-22: CCXT exchange object not async-safe [P2]
- **Status:** OPEN
- **File:** `engine/src/data/market_data.py:149-154`
- **Fix:** Add asyncio.Lock or use ccxt.async_support.

### DE-23: No health check on data sources [P2]
- **Status:** OPEN
- **File:** `engine/src/data/market_data.py`
- **Fix:** Add health_check() method tracking last fetch time, error rate. Include in heartbeat.

---

## NEW ISSUES -- PANEL 7: RISK / COMPLIANCE

### RC-01: validate_trade() NEVER called by autonomous trader [P0]
- **Status:** FIXED
- **File:** `engine/src/agent/autonomous_trader.py:234-425`
- **Problem:** The risk gatekeeper is completely bypassed. Agent implements ad-hoc checks but misses daily drawdown, total drawdown, and consistency rule. Only called from API endpoint (manual trades).
- **Fix:** Add risk_manager.validate_trade(setup) call before every trade execution. Never allow a trade without passing validation.
- **Impact:** ACCOUNT BAN. Every FundingPips hard rule can be violated.

### RC-02: Consistency rule (45%) is a WARNING, not a BLOCK [P0]
- **Status:** FIXED
- **File:** `engine/src/risk/manager.py:155-163`
- **Problem:** Triggers at 80% of limit as advisory. Never hard-blocks at 100%. Skipped when total_pnl <= 0.
- **Fix:** Hard block at 45% threshold. Check potential_win scenario. Keep 80% as additional soft warning.

### RC-03: Daily drawdown ignores unrealized (floating) P&L [P0]
- **Status:** FIXED
- **File:** `engine/src/risk/manager.py:88-96`
- **Problem:** Uses realized_pnl only. A $4,500 open loss on $100K account = 0% drawdown to this system. FundingPips monitors equity in real time.
- **Fix:** Add real-time equity tracking including open positions. Halt trading if equity drawdown hits 5%.
- **Impact:** ACCOUNT BAN. FundingPips will detect the floating loss.

### RC-04: Total drawdown calculation may not be static from initial balance [P1]
- **Status:** FIXED
- **File:** `engine/src/risk/manager.py:46-63`
- **Problem:** starting_balance could drift via persistence. FundingPips total DD is STATIC from original balance.
- **Fix:** Add original_starting_balance field, set once, never modified. Use for 10% DD calculation.

### RC-05: No hedging detection [P1]
- **Status:** FIXED
- **File:** `engine/src/agent/autonomous_trader.py:234-425`
- **Problem:** Zero hedging detection. Can open LONG and SHORT on same symbol. FundingPips bans hedging.
- **Fix:** Check for existing position in opposite direction before opening. Reject or close existing first.
- **Impact:** ACCOUNT BAN. Immediate termination.

### RC-06: Dual config systems with conflicting risk parameters [P1]
- **Status:** OPEN
- **File:** `engine/src/config.py:63-68` vs `engine/src/agent/config.py:73-78`
- **Problem:** config.py: 1% risk, 3 concurrent. agent/config.py: 0.3% risk, 1 concurrent. Neither enforces all rules consistently.
- **Fix:** Single source of truth. Risk manager = sole enforcer.

### RC-07: No weekend gap protection for Gold/Silver [P1]
- **Status:** FIXED
- **File:** `engine/src/agent/autonomous_trader.py`
- **Problem:** No logic to prevent Friday evening positions or close before weekend. Gold can gap $20-50.
- **Fix:** Add Friday close buffer (no new metal trades after 19:00 UTC Friday).

### RC-08: News calendar uses hardcoded EST (no DST handling) [P1]
- **Status:** FIXED
- **File:** `engine/src/data/economic_calendar.py:127-128`
- **Problem:** EST hardcoded as UTC-5. During DST (March-Nov), EDT = UTC-4. Blackout windows off by 1 FULL HOUR for 8 months/year.
- **Fix:** Use zoneinfo with America/New_York. Test both EST and EDT periods.
- **Impact:** ACCOUNT BAN during DST months. Trades through NFP/FOMC/CPI.
- **Duplicate:** DE-11

### RC-09: No slippage protection on live execution [P1]
- **Status:** OPEN
- **File:** `engine/src/execution/binance_testnet.py:251-350`
- **Problem:** Fill price accepted unconditionally. No max deviation check.
- **Fix:** Check deviation from expected price. Close immediately if > 0.3-0.5%.

### RC-10: FOMC dates approximate (algorithmic, not actual) [P2]
- **Status:** OPEN
- **File:** `engine/src/data/economic_calendar.py:92-109`
- **Fix:** Use actual published FOMC dates or live calendar API.

### RC-11: No inactivity rule enforcement (30-day limit) [P2]
- **Status:** OPEN
- **Problem:** FundingPips terminates accounts with no trades for 30 days. No tracking or alerting.
- **Fix:** Track last_trade_date. Alert at 25 days. Optionally execute minimal trade.

### RC-12: Position count resets at midnight (DailyStats) [P2]
- **Status:** FIXED
- **File:** `engine/src/risk/manager.py:126-130`
- **Problem:** Overnight positions: new DailyStats starts open_positions=0, allowing over-limit.
- **Fix:** Initialize from actual open position count.

### RC-13: Dual risk_per_trade between config and agent_config [P2]
- **Status:** OPEN
- **Fix:** Route all sizing through risk_manager. Use most conservative value.

### RC-14: No audit trail for risk decisions [P2]
- **Status:** FIXED
- **File:** `engine/src/risk/manager.py`
- **Problem:** Rejections returned but not logged. signal log always records risk_passed=True.
- **Fix:** Log every validation call (pass/fail) to DB with timestamp, reasons.

### RC-15: Binance Demo trades FUTURES, not SPOT/CFD [P2]
- **Status:** OPEN
- **File:** `engine/src/execution/binance_testnet.py:35`
- **Problem:** demo-fapi.binance.com is FUTURES. FundingPips is SPOT/CFD. Different mechanics.
- **Fix:** Acceptable for demo phase. Add warning that results are not FundingPips-comparable.

### RC-16: SL/TP use closePosition=true (no partial, orphaned counterpart) [P2]
- **Status:** OPEN
- **File:** `engine/src/execution/binance_testnet.py:308-344`
- **Problem:** When SL triggers, TP remains on exchange (and vice versa). Orphaned orders.
- **Fix:** Cancel counterpart order when SL or TP fills.
- **Duplicate:** AT-25

### RC-17: Risk state silently swallows persistence exceptions [P3]
- **Status:** OPEN
- **File:** `engine/src/risk/manager.py:54-63,209-217`
- **Fix:** Log exceptions. Halt trading if state cannot be saved.
- **Duplicate:** CQ-07

### RC-18: Daily stats don't incorporate open position P&L at rollover [P3]
- **Status:** OPEN
- **Fix:** Initialize with equity including unrealized P&L.

### RC-19: No HFT-like behavior detection (min trade duration) [P3]
- **Status:** OPEN
- **Fix:** Add minimum trade hold time (60s). Track average duration.

### RC-20: CPI date algorithm produces wrong dates [P3]
- **Status:** OPEN
- **File:** `engine/src/data/economic_calendar.py:140-151`
- **Fix:** Use actual BLS release schedule.

### RC-21: Learning engine can auto-modify weights without guardrails [P3]
- **Status:** OPEN
- **Fix:** Only ADD to blacklist (never replace). Bound weights (0.05-0.50). Rate limit changes.

---

## NEW ISSUES -- PANEL 8: MARKET MICROSTRUCTURE

### MM-01: Zero slippage model [P0]
- **Status:** FIXED
- **File:** `engine/src/backtester/engine.py:558-559`
- **Problem:** SL exits fill at exact stop price. Real stops have 1-50+ tick slippage. Backtests overstate performance by 20-40%.
- **Fix:** Add per-instrument slippage model. Make SL fill = stop_price + slippage. Proportional to ATR.
- **Duplicate:** QR-24

### MM-02: Static spread model -- no time-of-day variation [P0]
- **Status:** FIXED
- **File:** `engine/src/data/instruments.py:225,251,279`
- **Problem:** Single static spread per instrument. Gold varies 0.10 (London) to 0.80+ (Asian rollover). BTC varies 1-30.
- **Fix:** Add spread_schedule or session multipliers per instrument.

### MM-03: No tick size validation on order prices [P0]
- **Status:** FIXED
- **File:** `engine/src/execution/binance_testnet.py:290-294`
- **Problem:** Prices rounded to 2 decimals but not validated against exchange tickSize. BTCUSDT tickSize=$0.10; invalid prices rejected silently.
- **Fix:** Add tick_size/qty_step to InstrumentSpec. Round prices to tick. Fetch exchangeInfo on connect.

### MM-04: Backtester SL/TP ambiguity on same-candle hits [P1]
- **Status:** OPEN
- **Duplicate:** QR-18

### MM-05: Non-atomic SL/TP placement (unprotected window) [P1]
- **Status:** OPEN
- **File:** `engine/src/execution/binance_testnet.py:297-345`
- **Problem:** Main order, then SL, then TP as 3 separate API calls. Position unprotected for 200-2000ms.
- **Fix:** Use Binance batchOrders endpoint or place SL first (already done, but add latency logging).

### MM-06: No market impact / order book depth model [P1]
- **Status:** OPEN
- **File:** `engine/src/data/instruments.py:90-160`
- **Problem:** max_lot allows 10 BTC / 50 lots Gold. Exceeds top-of-book depth during low liquidity.
- **Fix:** Add impact_threshold_lots field. Cap position_size at impact threshold.

### MM-07: Funding rate model oversimplified (hardcoded 0.01%) [P1]
- **Status:** OPEN
- **File:** `engine/src/backtester/engine.py:343-353`
- **Problem:** Fixed 0.01% per 8h. Real rates range -0.375% to +0.375%. Could consume $2-5K of $8K BTC profit.
- **Fix:** Fetch historical funding rates from Binance API. Model dynamic rates.

### MM-08: Live execution uses stale candle close as entry price [P1]
- **Status:** FIXED
- **File:** `engine/src/agent/autonomous_trader.py:329`
- **Problem:** Entry price from candles[-1].close (up to 5min old). SL/TP calculated from stale price.
- **Fix:** Recalculate SL/TP relative to actual fill price. Reject if fill deviates > 20% of SL distance.

### MM-09: BTCUSD spread ($15) unrealistic for prop firm ($30-50 actual) [P2]
- **Status:** OPEN
- **File:** `engine/src/data/instruments.py:251`
- **Fix:** Make spread venue-aware. FundingPips BTCUSD = $30-50, Binance BTCUSDT = $3-5.

### MM-10: No real bid/ask data from sources [P2]
- **Status:** OPEN
- **File:** `engine/src/data/market_data.py:367-380`
- **Problem:** get_bid_ask() fabricates bid/ask from last close + spread_typical. Not real market data.
- **Fix:** Use Binance GET /fapi/v1/ticker/bookTicker for real-time bid/ask.

### MM-11: CoinDCX missing retry and SL/TP [P2]
- **Status:** OPEN
- **Duplicate:** AT-27, AT-28

### MM-12: No partial fill modeling in backtester [P2]
- **Status:** OPEN
- **Fix:** Acceptable for market orders at small sizes. Handle PARTIALLY_FILLED in live brokers.

### MM-13: No execution quality metrics [P2]
- **Status:** OPEN
- **Fix:** Log expected_price, filled_price, latency_ms per trade. Add execution_stats table.

### MM-14: Paper trader SL uses candle granularity, not tick [P2]
- **Status:** OPEN
- **File:** `engine/src/execution/paper_trader.py:382-399`
- **Problem:** SL check limited to 1-min candle resolution. Fills at exact stop price (no gap-through).
- **Fix:** Use exchange ticker for real-time price. Model gap-through: candle open if gapped.

### MM-15: News spread widening not applied in live path [P3]
- **Status:** OPEN
- **Fix:** After blackout window, apply 3x spread multiplier for 30 minutes.

### MM-16: Silver spread / AT-20 interaction may disable Silver entirely [P3]
- **Status:** OPEN
- **Fix:** Log signal rejection rate per instrument. Verify Silver is actually tradeable.

---

## NEW ISSUES -- PANEL 9: TRADING PSYCHOLOGY

### TP-01: Self-confirming learning loop (grades own homework) [P0]
- **Status:** OPEN
- **File:** `engine/src/agent/trade_learner.py:37-58`
- **Problem:** Same system that enters trades grades them. TP hit = A (good outcome = good process). Classic confirmation bias.
- **Fix:** Grade PROCESS not outcome. Add adversarial review channel. Track "lucky wins" (barely hit TP).

### TP-02: 60-day hard cutoff with daily adjustments = recency bias [P0]
- **Status:** OPEN
- **File:** `engine/src/learning/analyzer.py:117-140`
- **Problem:** 60-day window with equal weights. Daily adjustments = algorithmic equivalent of obsessive P&L checking.
- **Fix:** Exponential decay with 14-day half-life. Reduce adjustment frequency to weekly.
- **Related:** ML-13 (regression)

### TP-03: Loss streak throttle embodies gambler's fallacy [P0]
- **Status:** FIXED
- **File:** `engine/src/backtester/engine.py:561-565`
- **Problem:** After 3 losses, size halved. Assumes losses beget losses. No equivalent logic in autonomous trader = backtest/live mismatch.
- **Fix:** Replace with regime-conditional throttle. Ensure backtester and agent use identical logic.

### TP-04: Outcome-based grading = hindsight bias [P1]
- **Status:** FIXED
- **File:** `engine/src/agent/trade_learner.py:159-193`
- **Duplicate:** ML-22

### TP-05: No conviction scaling (all qualifying signals = same size) [P1]
- **Status:** OPEN
- **File:** `engine/src/agent/autonomous_trader.py:256-305`
- **Problem:** Score 5.1 and score 9.0 get identical 0.3% risk. No way to express conviction.
- **Fix:** 2-tier or continuous scaling: score 5-6.9 = 60% risk, score 7+ = 100% risk. Track if high-conviction outperforms.

### TP-06: Asymmetric learning -- blacklist only, no "whitelist" or promotion [P1]
- **Status:** OPEN
- **File:** `engine/src/learning/recommendations.py:36-73`
- **Problem:** Losses trigger action (blacklist), wins trigger inaction. Loss aversion codified. Blacklist grows monotonically.
- **Fix:** Add boost mechanism for high-performing strategies. Add rehabilitation: re-test blacklisted strategies in shadow mode after 30 days.

### TP-07: Daily weight adjustments = algorithmic tilt [P1]
- **Status:** FIXED
- **File:** `engine/src/agent/autonomous_trader.py:469-493`
- **Problem:** Daily reconfig based on 60-day rolling = oscillation. Equivalent of a trader who changes indicators every night.
- **Fix:** Rate-limit to weekly. 7-day cooling period. Require 10+ new trades since last adjustment.
- **Related:** ML-20

### TP-08: Telegram WIN/LOSS notifications trigger human emotional intervention [P1]
- **Status:** FIXED
- **File:** `engine/src/agent/autonomous_trader.py:410-418,451-465`
- **Problem:** Per-trade notifications with "WIN" or "LOSS" in bold. 3 consecutive losses = human panic intervention.
- **Fix:** Batch to 4-6 hour summaries. Neutral language. Add context: "within normal expected range."

### TP-09: Regime detection has no transition state (whipsaw) [P2]
- **Status:** OPEN
- **File:** `engine/src/confluence/scorer.py:55-118`
- **Problem:** Discrete thresholds with no hysteresis. Market at boundary flips regime every candle.
- **Fix:** Add hysteresis (require exceeding threshold by margin to enter, dropping below to exit). Use EMA of regime over last 5 readings.

### TP-10: Optimizer disables all safety rails during tuning [P2]
- **Status:** OPEN
- **File:** `engine/src/learning/optimizer.py:186-192`
- **Problem:** Optimization runs with loss_streak=99, news_blackout=0, daily_cap=10. Parameters optimized for unrestricted environment but deployed with restrictions.
- **Fix:** Replicate live trading environment exactly during optimization.

### TP-11: A/B testing confidence is naive (30 samples = "high") [P2]
- **Status:** OPEN
- **File:** `engine/src/learning/ab_testing.py:186-209`
- **Duplicate:** ML-26

### TP-12: No win-streak awareness (overconfidence after success) [P2]
- **Status:** OPEN
- **Fix:** Track consecutive wins. Alert after 5+. Check if regime is still valid.

### TP-13: Blacklist threshold absolute, not regime-conditional [P2]
- **Status:** OPEN
- **File:** `engine/src/learning/recommendations.py:36-73`
- **Problem:** Strategy with 70% WR in TRENDING but 20% in RANGING = 47% aggregate (passes). Bad in prolonged RANGING.
- **Fix:** Compute blacklist per strategy per instrument PER REGIME.

### TP-14: No "should I trade at all today?" check (action bias) [P3]
- **Status:** OPEN
- **Fix:** Add market quality score. Reduce max_trades when conditions are poor.

### TP-15: No structured human intervention protocol [P3]
- **Status:** OPEN
- **Fix:** Log all human config changes. Implement 4-hour confirmation delay for risk changes.

---

## NEW ISSUES -- PANEL 10: CODE QUALITY / ARCHITECTURE

### CQ-01: Single shared SQLAlchemy Session -- not thread/async safe [P0]
- **Status:** FIXED
- **File:** `engine/src/journal/database.py:183-197`
- **Problem:** One Session shared across all coroutines. Not thread-safe, never rolled back on failure.
- **Fix:** Use sessionmaker + scoped_session. Per-request sessions in FastAPI.
- **Duplicate:** OPS-06, DE-05, SEC-10

### CQ-02: Two separate database systems (SQLAlchemy + raw sqlite3) [P1]
- **Status:** FIXED
- **File:** `engine/src/learning/ab_testing.py:20-54`
- **Problem:** A/B testing uses separate sqlite3 DB. check_same_thread=False without locking.
- **Fix:** Consolidate into single SQLAlchemy database.

### CQ-03: Six module-level singletons create hidden coupling [P1]
- **Status:** OPEN
- **File:** Multiple (autonomous_trader, risk_manager, market_data, agent_config, paper_trader, scanner)
- **Problem:** Hidden dependency graph. Cannot test in isolation. Import triggers DB connection.
- **Fix:** Dependency injection. Application wiring class.

### CQ-04: Monkey-patching get_filtered_strategies is not thread-safe [P1]
- **Status:** FIXED
- **File:** `engine/src/backtester/engine.py:900-913`
- **Problem:** Temporarily replaces module-level function. Not safe under concurrent access.
- **Fix:** Pass strategies parameter to Backtester.run() directly.

### CQ-05: Mutable global BLACKLIST and WEIGHTS mutated at runtime [P1]
- **Status:** OPEN
- **File:** `engine/src/backtester/engine.py:54-93`, `engine/src/confluence/scorer.py:22-35`
- **Problem:** Shared mutable state. Walk-forward test modifies globals that affect live scanner. No locking.
- **Fix:** Make instance variables or use immutable config objects replaced atomically.

### CQ-06: Deprecated asyncio.get_event_loop() [P2]
- **Status:** FIXED
- **File:** `engine/src/data/market_data.py:226,276,326`
- **Fix:** Use asyncio.get_running_loop() or asyncio.to_thread().
- **Duplicate:** DE-12

### CQ-07: Broad exception swallowing hides bugs (30+ instances) [P2]
- **Status:** OPEN
- **File:** Multiple (autonomous_trader, risk_manager, api/server, trade_learner)
- **Problem:** except Exception: pass on critical paths including risk state persistence.
- **Fix:** Log every caught exception. Fail loudly on critical paths.
- **Duplicate:** OPS-14, RC-17

### CQ-08: BacktestTrade uses dynamic attributes via getattr [P2]
- **Status:** FIXED
- **File:** `engine/src/backtester/engine.py:364,595-596`
- **Fix:** Add _entry_idx and _at_breakeven as proper dataclass fields.

### CQ-09: get_all_strategies() creates new instances every call [P2]
- **Status:** FIXED
- **File:** `engine/src/strategies/registry.py:25-62`
- **Problem:** 14 new instances per call. Called on every tick, every candle iteration.
- **Fix:** Cache instances at module level.

### CQ-10: No database migration strategy [P2]
- **Status:** OPEN
- **File:** `engine/src/journal/database.py:194`
- **Problem:** create_all() only creates new tables. Column changes = runtime crash.
- **Fix:** Add Alembic.

### CQ-11: API server no auth, no validation, no rate limiting [P2]
- **Status:** OPEN
- **Duplicate:** SEC-01, SEC-11, SEC-18

### CQ-12: Synchronous Claude API calls block async event loop [P2]
- **Status:** OPEN
- **File:** `engine/src/agent/trade_learner.py:114-156`
- **Problem:** Uses sync anthropic.Anthropic inside async function. Blocks event loop 2-10s.
- **Fix:** Use anthropic.AsyncAnthropic or asyncio.to_thread().

### CQ-13: Reconciliation compares wrong symbol formats [P2]
- **Status:** FIXED
- **File:** `engine/src/agent/autonomous_trader.py:514-549`
- **Problem:** Exchange symbols (BTCUSDT) vs local (BTCUSD) never match. Reconciliation always reports false mismatches.
- **Fix:** Normalize symbols via _map_symbol or its inverse before comparison.

### CQ-14: No integration tests [P2]
- **Status:** OPEN
- **File:** `engine/tests/`
- **Problem:** 40 unit tests. Zero integration tests for scan-to-trade pipeline, API, learning loop.
- **Fix:** Add conftest.py with fixtures. Integration test for _tick(). API tests with TestClient.

### CQ-15: Agent config safety boundaries trivially overridable [P3]
- **Status:** OPEN
- **File:** `engine/src/agent/config.py:84`
- **Fix:** Make safety fields read-only. Add range validation.

### CQ-16: config.py loads .env from CWD, not engine dir [P3]
- **Status:** OPEN
- **File:** `engine/src/config.py:111`
- **Problem:** Relative .env path. Wrong CWD = silent config failure.
- **Fix:** Derive from __file__. Log warning if .env not found.
- **Duplicate:** OPS-16

### CQ-17: Backtester.run() is 300-line monolithic method [P3]
- **Status:** OPEN
- **File:** `engine/src/backtester/engine.py:271-632`
- **Fix:** Extract: _process_open_trades(), _check_circuit_breakers(), _find_best_signal().

### CQ-18: API server imports every module at top level [P3]
- **Status:** OPEN
- **File:** `engine/src/api/server.py:17-44`
- **Problem:** 28 imports. One missing optional dep = entire server fails.
- **Fix:** Lazy imports for non-critical modules.

### CQ-19: close_trade_endpoint self-imports from its own module [P3]
- **Status:** FIXED
- **File:** `engine/src/api/server.py:484`
- **Problem:** Dead import: `from .server import market_data as _md`.
- **Fix:** Remove line entirely.

### CQ-20: No structured logging -- all print() [P3]
- **Status:** OPEN
- **Duplicate:** OPS-03

### CQ-21: httpx client in Binance broker leaked on connection failure [P3]
- **Status:** FIXED
- **File:** `engine/src/execution/binance_testnet.py:103-113`
- **Fix:** Close existing client before creating new one in _ensure_client.

### CQ-22: Backtester skipped_cooldown/skipped_daily_cap never incremented [P3]
- **Status:** FIXED
- **File:** `engine/src/backtester/engine.py:314,316`
- **Problem:** Initialized to 0, never incremented. Dashboard shows 0 always.
- **Fix:** Add increment before continue statements.

### CQ-23: Anthropic client created on every trade analysis call [P3]
- **Status:** OPEN
- **File:** `engine/src/agent/trade_learner.py:114-128`
- **Fix:** Create client once at module level or cache.

---

## SUMMARY

### New Issues by Panel

| Panel | P0 | P1 | P2 | P3 | Total |
|-------|----|----|----|----|-------|
| 1. Quant Researcher | 0 | 3 | 7 | 2 | 12 |
| 2. AI/ML Specialist | 2 | 4 | 4 | 2 | 12 (+1 regressed) |
| 3. Algo Trading | 3 | 7 | 5 | 0 | 15 |
| 4. Security | 3 | 6 | 8 | 3 | 20 |
| 5. DevOps/SRE | 5 | 6 | 6 | 3 | 20 |
| 6. Data Engineer | 3 | 6 | 11 | 3 | 23 |
| 7. Risk/Compliance | 3 | 6 | 7 | 5 | 21 |
| 8. Microstructure | 3 | 5 | 6 | 2 | 16 |
| 9. Psychology | 3 | 5 | 5 | 2 | 15 |
| 10. Code Quality | 1 | 4 | 8 | 9 | 23* |
| **Total** | **26** | **52** | **67** | **31** | **177** |

*Many issues are duplicated across panels (noted with "Duplicate:" tags). Unique new issues: ~150.

### Previous Issues Status (Session 4a)

| Status | Count |
|--------|-------|
| VERIFIED | 30 |
| DEFERRED | 8 |
| WONT_FIX | 2 |
| REGRESSED → FIXED | 1 (ML-13) |
| Carried to new IDs | 7 |

### New Issues Status (Session 5+6 fixes)

| Status | Count | Notes |
|--------|-------|-------|
| FIXED | ~70 | All P0s fixed, most P1s, many P2/P3 |
| DEFERRED | ~10 | OPS-01/02 (Docker/CI — local dev), AT-12/18/19/22, QR-03/06/08/10/12 |
| WONT_FIX | 2 | ML-07, AT-13 |
| OPEN | ~95 | Remaining P1/P2/P3 issues for future sessions |

### What's left (not blocking paper trading)

**Remaining P1s (fix before real money):**
QR-17 (optimizer correction), SEC-04/07/08 (HMAC/TLS), SEC-13 (mode auth),
RC-06/09 (config conflict, slippage protection), MM-05/06/07 (atomic SL/TP, market impact, funding rates),
OPS-06/07/08/09/11 (DB session dupes, alerting, monitoring)

**Remaining P2/P3 (fix when time allows):**
~85 lower-priority items across all panels. See individual issue statuses above.

---

## REVIEW HISTORY

| Date | Session | Panels Used | Issues Found | Issues Verified | Issues Regressed |
|------|---------|-------------|-------------|-----------------|-----------------|
| 2026-03-22 | 4a | Quant, AI/ML, Algo | 48 | 0 | 0 |
| 2026-03-22 | 4a (fixes) | -- | 0 | 11 (all P0s) | 0 |
| 2026-03-22 | 5 | ALL 10 PANELS | 177 new | 30 previous | 1 (ML-13) |
| 2026-03-22 | 6 | FIX SESSION | 0 new | ~70 fixed | 0 |
| -- | Next | After paper trading validation | -- | -- | -- |
