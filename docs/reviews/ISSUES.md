# Notas Lave — Expert Review Issue Tracker

**Review Date:** 2026-03-22 (Session 4a)
**Reviewed By:** 3-Panel Expert Review (Quant, AI/ML, Algo Trading)
**System State:** 14 strategies, 41 tests, Binance Demo verified, 1-year backtests complete
**Next Review:** After P0 fixes are implemented (target: Session 6-7)

---

## Status Legend

| Status | Meaning |
|--------|---------|
| OPEN | Not started (37 remain) |
| IN_PROGRESS | Work begun |
| FIXED | Code changed, needs verification |
| VERIFIED | Fixed and tested |
| WONT_FIX | Accepted risk / not applicable |
| DEFERRED | Postponed to later phase |

## Severity Legend

| Severity | Meaning |
|----------|---------|
| P0 | System-breaking. Fix before ANY live trading. |
| P1 | High risk. Fix before real money. Paper trading OK without. |
| P2 | Significant. Fix before scaling up. |
| P3 | Improvement. Fix when time allows. |
| P4 | Nice-to-have. Low urgency. |

---

## PANEL A: QUANT RESEARCHER

Issues related to backtesting methodology, statistical validity, and risk math.

### QR-01: Backtesting is single in-sample pass, not walk-forward [P0]
- **Status:** FIXED
- **File:** `engine/src/backtester/engine.py`
- **Problem:** The "1-year backtest" that produced headline results (BTC: 443 trades, 58% WR, $8.2K) is a single pass through all data. Strategies were already selected, blacklists already chosen, parameters already set. This is in-sample performance, not validated out-of-sample results.
- **Fix:** Implement N-fold rolling walk-forward: split into windows (e.g., 6x2-month), train on windows 1-4, test on 5, slide forward. Report ONLY out-of-sample aggregated results.
- **Impact:** All reported backtest numbers are unreliable until this is fixed.

### QR-02: Strategy blacklists are circular / data-snooped [P0]
- **Status:** FIXED
- **File:** `engine/src/backtester/engine.py:53-92`
- **Problem:** Blacklists were derived from backtesting all 14 strategies on 1-year data, then the backtest was re-run WITH those blacklists on the SAME data. The improved results are a mirage — the blacklists were optimized on the test data.
- **Fix:** Derive blacklists from Year 1 data, test on Year 2 data. Or use walk-forward (QR-01) where blacklists are only derived from the training window.
- **Impact:** Without this, you cannot trust which strategies are "bad" vs which just had a bad year.

### QR-03: RSI Divergence sole survivor = curve-fitting risk [P1]
- **Status:** DEFERRED (needs 2+ years historical data first)
- **File:** `engine/src/strategies/rsi_divergence.py`
- **Problem:** 13/14 strategies fail on crypto, leaving RSI Divergence as the "only" profitable one. This is either a systemic implementation bug across 13 strategies, or RSI Divergence is curve-fitted to a mean-reverting regime in the test year. One year of crypto data covers roughly one market regime.
- **Fix:** (1) Test RSI Divergence on 2024 BTC bull run data. (2) Test on 2022 bear market data. If it fails in both, it's regime-specific, not an edge. (3) Investigate why 13 strategies fail — is there a common bug?
- **Impact:** Building around one strategy that may not survive regime change.

### QR-04: Optimizer validation includes training data [P0]
- **Status:** FIXED
- **File:** `engine/src/learning/optimizer.py:234`
- **Code:** `test_candles = candles  # Full data for validation (needs warmup from start)`
- **Problem:** The "validation" set is the FULL dataset including training data. Training on 70%, testing on 100% means the test includes the training set. Every "validated" parameter set is actually in-sample.
- **Fix:** `test_candles = candles[split_idx - 250:]` (prepend 250 candles of warmup from training set, but test only on unseen 30%).
- **Impact:** All optimizer results are unreliable. Optimized parameters may be overfit.

### QR-05: Sharpe ratio calculation is inflated [P2]
- **Status:** OPEN
- **File:** `engine/src/backtester/engine.py:654-659`
- **Problem:** Sharpe is computed from per-candle (5-minute) returns and annualized with `sqrt(252)`. But 5-minute bars have ~105K data points per year, not 252 trading days. Per-candle returns are much smoother than daily, inflating Sharpe.
- **Fix:** Aggregate returns to daily before computing Sharpe, OR annualize with `sqrt(252 * 288)` for 5-min bars (288 bars per day). Better: compute daily P&L returns.
- **Impact:** Reported Sharpe is unrealistically high. Misleading for strategy evaluation.

### QR-06: Identical 58.0% win rate on BTC and ETH [P3]
- **Status:** OPEN
- **File:** Backtest results in `docs/context/SESSION-CONTEXT.md:144-146`
- **Problem:** Both BTC and ETH show exactly 58.0% win rate. With different numbers of trades (443 vs 381), this is statistically unlikely to be coincidence. May indicate a rounding bug or systematic issue in win rate calculation.
- **Fix:** Investigate: run `wins / total_trades` with full precision for both. Check if there's a rounding to nearest integer before percentage.
- **Impact:** Low — may just be coincidence, but worth a 5-minute check.

### QR-07: min_lot clamping causes 10-100x intended risk [P0]
- **Status:** FIXED
- **File:** `engine/src/data/instruments.py:140-141`
- **Problem:** When calculated position size is below min_lot, it gets clamped UP to min_lot. For small accounts, this means actual risk far exceeds intended risk. Example: $100 account, 0.3% risk, Gold $5 SL → needs 0.0006 lots → clamped to 0.01 → actual risk = 5%, not 0.3%.
- **Fix:** After clamping to min_lot, check if the actual risk (min_lot * price_risk * contract_size) exceeds the risk budget. If yes, return 0.0 (reject the trade).
- **Impact:** WILL blow up small accounts. This is the #1 killer for the 2000-3000 INR CoinDCX plan.

### QR-08: Insufficient historical data for crypto [P1]
- **Status:** DEFERRED (download 2-3 years when ready)
- **File:** Historical data files
- **Problem:** 1 year of 5-minute crypto data covers roughly one market regime (2025 was range-bound BTC). Need data spanning bull markets (2024 Q4, 2021), bear markets (2022), and range (2023) to validate strategy robustness.
- **Fix:** Download 2-3 years of BTC/ETH data. Re-run backtests across multiple regime types. RSI Divergence must survive all to be trusted.
- **Impact:** Strategy selection is based on single-regime data.

### QR-09: No Monte Carlo simulation [P3]
- **Status:** OPEN
- **File:** Not yet implemented
- **Problem:** Walk-forward tells you the average outcome. Monte Carlo tells you the RANGE of outcomes. Shuffle the order of 443 trades 10,000 times, measure max drawdown distribution. What's the 95th percentile drawdown? If it's >10%, FundingPips fails.
- **Fix:** Implement Monte Carlo permutation test on backtest trade sequences. Report: P5/P50/P95 drawdown, probability of ruin.
- **Impact:** Without this, you don't know how unlucky you could get.

### QR-10: No out-of-sample test period reserved [P1]
- **Status:** DEFERRED (reserve holdout when new data arrives)
- **File:** Backtest methodology
- **Problem:** All available data was used for development (strategy selection, blacklists, parameter tuning). No clean holdout set exists for final validation.
- **Fix:** When new data arrives, reserve the most recent 20% as untouched holdout. Only run it ONCE as final validation before going live.
- **Impact:** Cannot distinguish real edge from overfitting.

### QR-11: Backtester picks single best signal per candle [P3]
- **Status:** OPEN
- **File:** `engine/src/backtester/engine.py:496-504`
- **Problem:** At each candle, the backtester runs all strategies and picks the one with the highest score. In live trading, you might see a different signal first (depending on scan order and timing). This introduces selection bias.
- **Fix:** Consider using the confluence scorer (as the live system does) instead of cherry-picking the best individual signal. Or randomize which signal is selected when multiple fire.
- **Impact:** Moderate — backtest results may be slightly optimistic.

### QR-12: No transaction cost sensitivity analysis [P3]
- **Status:** OPEN
- **File:** Not yet implemented
- **Problem:** Spread and fees are set to fixed values. In reality, spreads widen during volatile periods, fees can change, and slippage varies. No analysis of how results change with 2x or 3x spread.
- **Fix:** Run backtest with spread at 1x, 1.5x, 2x, 3x typical values. Find the "break-even spread" where the strategy becomes unprofitable. If it's close to typical, the edge is fragile.
- **Impact:** Edge may evaporate under real spread conditions.

### QR-13: SL/TP check order bias in backtester [P4]
- **Status:** OPEN
- **File:** `engine/src/backtester/engine.py:372-389`
- **Problem:** For LONG trades, SL is checked before TP on the same candle. If both could trigger in the same candle (wide range), the backtester assumes SL hit first. This is conservative (biases results down), which is actually safer, but doesn't match reality where either could hit first.
- **Fix:** Use intra-candle simulation: if open is closer to SL, assume SL first; if closer to TP, assume TP first. Or flag ambiguous candles.
- **Impact:** Low — conservative bias is safer than optimistic.

---

## PANEL B: AI/ML SPECIALIST

Issues related to the learning engine, Claude integration, and system intelligence.

### ML-01: Learning feedback loop is completely open [P0]
- **Status:** FIXED
- **File:** `engine/src/agent/autonomous_trader.py:318-320`
- **Code:**
  ```python
  new_blacklist = get_dynamic_blacklist()
  if new_blacklist:
      print(f"[Agent] Daily review: updated blacklists for {list(new_blacklist.keys())}")
  ```
- **Problem:** The daily review generates new blacklists and weight recommendations, then PRINTS them and does nothing. `INSTRUMENT_STRATEGY_BLACKLIST` in `backtester/engine.py` is a module-level constant that never gets updated. `REGIME_WEIGHTS` in `scorer.py` is never modified. The system generates intelligence and throws it away.
- **Fix:** (1) Make blacklists and weights mutable (module-level dict that can be updated). (2) Apply dynamic blacklist to the scanner/confluence scorer on daily review. (3) Apply weight adjustments with a dampening factor (don't swing weights wildly). (4) Persist changes to disk so they survive restarts.
- **Impact:** The "EVOLVE" motto is broken. The system does not actually evolve.

### ML-02: Claude per-trade analysis produces unused output [P2]
- **Status:** OPEN
- **File:** `engine/src/agent/trade_learner.py:37-58, 98-101`
- **Problem:** Claude produces a grade (A-F), lesson (text), strategy_note (text), and regime_match (bool). The grade is stored in the journal but never queried. The lesson is stored but never parsed. The strategy_note and regime_match are never stored at all. No downstream system reads these values.
- **Fix:** Option A: Remove per-trade Claude analysis entirely (save API costs) and rely on the statistical analyzer. Option B: Parse Claude's structured output into actionable signals (e.g., if grade=D/F on same strategy 3x, auto-blacklist).
- **Impact:** Wasting API calls + creating false sense of learning.

### ML-03: Dynamic blacklist generated but never applied to scanner [P0]
- **Status:** FIXED
- **File:** `engine/src/learning/recommendations.py:77-94`, `engine/src/confluence/scorer.py:149`
- **Problem:** `get_dynamic_blacklist()` produces a blacklist from journal data, but the confluence scorer calls `get_all_strategies()` which returns ALL 14 strategies every time. The blacklist from recommendations is never connected to the strategy filtering in the scanner or confluence scorer.
- **Fix:** The confluence scorer should check both the static blacklist (from backtester/engine.py) AND the dynamic blacklist (from recommendations) before running strategies.
- **Impact:** Failing strategies continue to generate signals and consume confluence score.

### ML-04: Weight adjustments generated but never applied [P0]
- **Status:** FIXED
- **File:** `engine/src/learning/recommendations.py:97-153`, `engine/src/confluence/scorer.py:22-35`
- **Problem:** `recommend_weight_adjustments()` computes optimal regime weights from journal data, but `REGIME_WEIGHTS` in scorer.py is a module-level constant that never changes. The recommended weights are returned as JSON in the API but never applied.
- **Fix:** (1) Store current weights in a mutable config (file or DB). (2) On daily review, blend current weights toward recommended weights with a learning rate (e.g., 0.1 per day). (3) Log weight changes for audit trail.
- **Impact:** The system cannot adapt its scoring to market changes.

### ML-05: MIN_TRADES_FOR_RECOMMENDATION too low (10) [P1]
- **Status:** FIXED
- **File:** `engine/src/learning/recommendations.py:30`
- **Problem:** With 10 binary outcomes (win/lose), a 60% win rate has a 95% confidence interval of [26%, 88%]. This is meaningless noise. Making strategy decisions from 10 trades is statistically invalid.
- **Fix:** Raise to 50 minimum (CI narrows to [46%, 74%]) or ideally 100 (CI: [50%, 70%]). Add confidence interval calculation alongside win rate.
- **Impact:** System may blacklist good strategies or keep bad ones based on small samples.

### ML-06: Optimizer tests strategies in isolation [P2]
- **Status:** OPEN
- **File:** `engine/src/learning/optimizer.py:162-207`
- **Problem:** The optimizer runs each strategy independently with `min_score=0` and `require_strong=False`. But in the live system, strategies interact through the confluence scorer. Optimal RSI parameters in isolation may not be optimal when combined with 13 other strategies.
- **Fix:** After individual optimization, run a "system-level" backtest with ALL optimized strategies together through the confluence scorer. Verify system-level metrics don't degrade.
- **Impact:** Individually optimal parameters may be suboptimal in the ensemble.

### ML-07: Claude hindsight bias in trade analysis [P3]
- **Status:** OPEN
- **File:** `engine/src/agent/trade_learner.py:37-58`
- **Problem:** Claude sees the trade outcome (P&L, exit reason) before analyzing it. It will always construct a plausible post-hoc narrative. "RSI was at 35, which is too high for a good oversold entry" — Claude says this AFTER seeing the loss. This creates false confidence in the "lessons."
- **Fix:** If keeping Claude analysis, present the trade WITHOUT the outcome first, ask for prediction, THEN reveal outcome. Compare prediction accuracy over time. Or: accept this limitation and weight statistical analysis higher than Claude narratives.
- **Impact:** Lessons may be spurious post-hoc rationalizations.

### ML-08: Claude inconsistency across identical analyses [P3]
- **Status:** OPEN
- **File:** `engine/src/agent/trade_learner.py:104-142`
- **Problem:** Given the same trade data twice, Claude may produce different grades and lessons. There's no deterministic analysis. Temperature is not set (defaults to 1.0), and max_tokens=256 may truncate.
- **Fix:** Set temperature=0 for deterministic output. Increase max_tokens to 512. Add retry logic if JSON parsing fails.
- **Impact:** Inconsistent grading makes pattern detection across trades unreliable.

### ML-09: No cross-trade memory in Claude analysis [P3]
- **Status:** OPEN
- **File:** `engine/src/agent/trade_learner.py:62-101`
- **Problem:** Each trade is analyzed in isolation. Claude cannot say "this is the 5th time RSI Divergence failed on ETH during Asian session." Pattern detection across trades requires either (a) including recent trade history in the prompt, or (b) using the statistical analyzer instead.
- **Fix:** Option A: Include last 5-10 trades for the same strategy+instrument in the prompt context. Option B: Drop per-trade Claude analysis entirely; use weekly review only.
- **Impact:** Missing compound patterns that only emerge across many trades.

### ML-10: No structured feature extraction from trades [P2]
- **Status:** OPEN
- **File:** `engine/src/learning/analyzer.py`
- **Problem:** The analyzer does multi-dimensional breakdown but only on basic dimensions (strategy, instrument, regime, hour, score). Missing: spread at entry, volatility percentile, time-to-SL vs time-to-TP, distance from key levels, volume at entry, consecutive trade context.
- **Fix:** Extract and store structured features at trade open time (not just outcome). Analyze which features predict wins vs losses.
- **Impact:** Learning engine has limited feature space to find patterns.

### ML-11: No statistical significance tests [P2]
- **Status:** OPEN
- **File:** `engine/src/learning/recommendations.py`
- **Problem:** Recommendations are made based on raw win rate and P&L without any statistical test. A strategy with 7/10 wins (70%) and one with 70/100 wins (70%) get treated identically, but the former has massive uncertainty.
- **Fix:** Add chi-squared test for win rate differences, bootstrap confidence intervals for Sharpe/PF, and p-values alongside recommendations.
- **Impact:** Recommendations may be based on statistical noise.

### ML-12: No A/B testing framework [P3]
- **Status:** OPEN
- **File:** Not yet implemented
- **Problem:** When the optimizer suggests new parameters, there's no way to test them against the old parameters on live data. You're either using the old params or the new params, never both simultaneously.
- **Fix:** Run two parameter sets in parallel on paper (shadow mode): old params generate actual trades, new params generate virtual trades. Compare after N trades.
- **Impact:** Parameter changes are made blind — no way to know if new is actually better.

### ML-13: No exponential decay weighting [P2]
- **Status:** OPEN
- **File:** `engine/src/learning/analyzer.py:117-133`
- **Problem:** `_get_closed_trades(max_age_days=90)` uses a hard cutoff: trades from 89 days ago have full weight, trades from 91 days ago have zero weight. Market conditions change gradually.
- **Fix:** Use exponential decay: recent trades get weight 1.0, older trades decay with half-life of ~30 days. `weight = exp(-0.693 * age_days / 30)`.
- **Impact:** Stale data contaminates recent analysis. Abrupt cutoff creates artifacts.

### ML-14: No regime transition detection [P2]
- **Status:** OPEN
- **File:** `engine/src/confluence/scorer.py:40-103`
- **Problem:** Regime is classified per-candle-window (last 50 candles). There's no detection of regime TRANSITIONS (e.g., "market just shifted from RANGING to TRENDING"). Transitions are where most losses occur because strategies optimized for the old regime fail in the new one.
- **Fix:** Track regime history. When regime changes, (a) increase caution (reduce position size), (b) weight recent-regime performance higher in the scorer. Consider Hidden Markov Model for smoother regime classification.
- **Impact:** System is blindsided by regime changes.

---

## PANEL C: ALGORITHMIC TRADING ADVISER

Issues related to execution, reliability, and production readiness.

### AT-01: 60-second polling is too slow for scalping [P1]
- **Status:** FIXED (candle-freshness check + current price on entry)
- **File:** `engine/src/agent/config.py:81`
- **Problem:** Scanning every 60s means entries are always stale. BTC can move $200+ in 60 seconds. Signal says "enter at $85,000" but price is $85,200 by the time the order reaches the exchange.
- **Fix:** (1) Use WebSocket for real-time price feeds. (2) Align scanning with candle close events (scan when the 5-min candle closes, not on a timer). (3) At minimum, re-fetch current price before placing the order.
- **Impact:** Every trade enters at a worse price than backtested. Systematic slippage.

### AT-02: cancel_order is broken (wrong method, missing symbol) [P0]
- **Status:** FIXED
- **File:** `engine/src/execution/binance_testnet.py:232-234`
- **Code:**
  ```python
  async def cancel_order(self, order_id: str) -> bool:
      result = await self._post("/fapi/v1/order", {"orderId": order_id})
  ```
- **Problem:** (1) Uses POST to `/fapi/v1/order` which CREATES orders, not cancels. Should be DELETE method. (2) Missing required `symbol` parameter. This code will never successfully cancel an order.
- **Fix:** Use DELETE method: `self._delete("/fapi/v1/order", {"symbol": symbol, "orderId": order_id})`. Add `symbol` parameter to the method signature.
- **Impact:** Cannot cancel orphaned SL/TP orders. Cannot clean up failed trades.

### AT-03: SL/TP placed as separate non-atomic orders [P0]
- **Status:** FIXED
- **File:** `engine/src/execution/binance_testnet.py:206-225`
- **Problem:** After market order fills, SL and TP are placed as separate fire-and-forget requests. If SL placement fails, you have an unprotected position. If TP placement fails, you miss the exit. If both fail, position sits open indefinitely.
- **Fix:** (1) Check return value of SL/TP placement. (2) If SL fails, immediately close the position. (3) Consider using Binance OCO (One-Cancels-Other) orders for atomic SL+TP. (4) Add "unprotected position" alert.
- **Impact:** Single point of failure that leaves positions unprotected.

### AT-04: No position reconciliation (local vs exchange) [P0]
- **Status:** FIXED
- **File:** `engine/src/agent/autonomous_trader.py`
- **Problem:** The autonomous trader tracks positions in `paper_trader` (in-memory). The Binance exchange has actual positions. These states are completely independent. If: agent crashes and restarts (memory gone, exchange positions remain), SL triggers on exchange (agent doesn't know), network drops during order placement (agent thinks it placed, exchange didn't receive).
- **Fix:** Add a reconciliation loop: every 5 minutes, query exchange positions via `get_positions()`, compare with local state, alert on mismatches, sync local state from exchange as source of truth.
- **Impact:** State drift between local and exchange = phantom or orphaned positions.

### AT-05: Symbol mapping is fragile string replacement [P2]
- **Status:** OPEN
- **File:** `engine/src/execution/binance_testnet.py:176`
- **Code:** `binance_sym = symbol.replace("USD", "USDT") if not symbol.endswith("USDT") else symbol`
- **Problem:** "XAUUSD" becomes "XAUUSDT" (doesn't exist on Binance). "ETHUSD" becomes "ETHUSDT" (correct). Works by accident for crypto, breaks for metals/forex.
- **Fix:** Create an explicit symbol mapping table: `SYMBOL_MAP = {"BTCUSD": "BTCUSDT", "ETHUSD": "ETHUSDT"}`. Raise error for unmapped symbols.
- **Impact:** Any non-crypto symbol will generate invalid orders.

### AT-06: No retry logic on API calls [P1]
- **Status:** FIXED
- **File:** `engine/src/execution/binance_testnet.py:69-105`
- **Problem:** All API calls (GET and POST) have a single attempt with a 15-second timeout. HTTP 429 (rate limit), 5xx (server error), or transient network issues = immediate failure with no retry.
- **Fix:** Add exponential backoff retry: 3 attempts with delays [1s, 2s, 4s]. Distinguish between retryable (429, 5xx, timeout) and non-retryable (400, 401) errors.
- **Impact:** Transient failures cause missed trades, orphaned orders, or stuck state.

### AT-07: No reconnection logic on connection drops [P1]
- **Status:** FIXED
- **File:** `engine/src/execution/binance_testnet.py:45-49`
- **Problem:** `_connected` is set once during `connect()`. If the connection drops later (network outage, exchange maintenance), `_connected` remains True but all API calls fail silently.
- **Fix:** (1) Check connection health on every API call (via ping or successful response). (2) Auto-reconnect on failure. (3) Set `_connected = False` on consecutive failures. (4) Alert via Telegram on disconnect.
- **Impact:** Agent thinks it's connected but all orders silently fail.

### AT-08: No order state tracking (fire-and-forget SL/TP) [P1]
- **Status:** FIXED
- **File:** `engine/src/execution/binance_testnet.py:206-225`
- **Problem:** SL and TP orders are placed without checking the response or storing the order IDs. If either fails, the system doesn't know. There's no list of "orders I placed" to reconcile against.
- **Fix:** Store all order IDs (main + SL + TP) together as a "position group." Periodically verify all orders in the group still exist on the exchange.
- **Impact:** Orphaned SL/TP orders or unprotected positions go undetected.

### AT-09: Paper trader and Binance Demo are disconnected [P1]
- **Status:** FIXED (agent uses _get_broker() for real brokers, paper_trader as fallback)
- **File:** `engine/src/agent/autonomous_trader.py:38, 127, 146`
- **Problem:** The autonomous trader imports and uses `paper_trader` (internal simulation) for all position management. It was designed to be wired to the Binance Demo broker, but this wiring hasn't happened. The agent auto-trades on paper_trader, not on the exchange.
- **Fix:** Create a broker abstraction in the autonomous trader: if BROKER=binance_testnet, use BinanceTestnetBroker for orders and position tracking instead of paper_trader.
- **Impact:** Binance Demo trades are not being placed by the autonomous agent.

### AT-10: _analyzed attribute hack is fragile [P3]
- **Status:** OPEN
- **File:** `engine/src/agent/autonomous_trader.py:279-283`
- **Code:** `pos._analyzed = True`
- **Problem:** Dynamically adding `_analyzed` attribute to Position objects is fragile. If the Position class changes, or positions are serialized/deserialized, this attribute is lost. Could lead to re-analyzing the same trade multiple times.
- **Fix:** Track analyzed trade IDs in a set within AutonomousTrader: `self._analyzed_trades: set[int] = set()`.
- **Impact:** Low — but will cause bugs during refactoring.

### AT-11: Risk manager uses date.today() not UTC [P2]
- **Status:** OPEN
- **File:** `engine/src/risk/manager.py:67-68`
- **Code:** `today = date.today()`
- **Problem:** `date.today()` uses the system's local timezone (IST for India, UTC+5:30). But market data timestamps are UTC. A trade at 11:30 PM UTC is "today" in UTC but "tomorrow" in IST. Daily stats could split across incorrect boundaries.
- **Fix:** Use `datetime.now(timezone.utc).date()` everywhere.
- **Impact:** Daily P&L and trade counts may be attributed to wrong days near midnight UTC.

### AT-12: CoinDCX API is untested with autonomous agent [P2]
- **Status:** OPEN
- **File:** `engine/src/execution/coindcx.py`
- **Problem:** The CoinDCX broker exists but has never been tested with the autonomous trading loop. Different auth mechanism, different order types, different error codes. The autonomous trader would need adaptations.
- **Fix:** Before going live on CoinDCX: (1) Test all broker methods manually. (2) Run autonomous agent against CoinDCX in paper/testnet mode if available. (3) Verify fee calculations match CoinDCX invoices.
- **Impact:** Untested broker integration = guaranteed bugs on first live trade.

### AT-13: CoinDCX fees consume 27% of risk budget [P2]
- **Status:** OPEN
- **File:** `engine/src/data/instruments.py:264-265`
- **Problem:** Taker fees 0.04% on entry AND exit = 0.08% round-trip. On a trade with 0.3% risk, fees are 0.08/0.3 = 27% of risk budget consumed before any price movement. The backtester accounts for this, but verify the fee model matches CoinDCX's actual calculation.
- **Fix:** (1) Verify fee calculation against actual CoinDCX invoices. (2) Consider using limit orders (maker fee 0.02%) instead of market orders. (3) Factor fees into R:R calculation before entry.
- **Impact:** Profitability is significantly eroded by fees on small accounts.

### AT-14: CoinDCX minimum order sizes vs small account [P1]
- **Status:** FIXED
- **File:** `engine/src/data/instruments.py:253-285`
- **Problem:** CoinDCX has minimum notional value requirements that may exceed what position sizing calculates for 2000-3000 INR ($25-35) accounts. Even with 15x leverage, the minimum tradeable position may risk more than 0.3% of account.
- **Fix:** (1) Check CoinDCX minimum order sizes for BTCUSDT and ETHUSDT. (2) If min notional > risk budget, the account is too small to trade safely. (3) Calculate minimum viable account size before going live.
- **Impact:** Account may be too small to trade within risk parameters. Same as QR-07.

### AT-15: No process watchdog for crash recovery [P1]
- **Status:** DEFERRED (deployment config — add systemd/supervisord when deploying to VPS)
- **File:** Not yet implemented
- **Problem:** If the Python process crashes (OOM, unhandled exception, power outage), there's no automatic restart. Open positions on the exchange remain unmonitored. SL/TP orders are on the exchange, but trailing breakeven, timeout exits, and learning all stop.
- **Fix:** (1) Deploy with systemd or supervisord for auto-restart. (2) On startup, check for existing exchange positions and reconcile. (3) Add crash recovery to the autonomous trader: detect positions from last session.
- **Impact:** Unmonitored positions during outage. No learning from trades during downtime.

### AT-16: No heartbeat / health check mechanism [P2]
- **Status:** OPEN
- **File:** Not yet implemented
- **Problem:** No way to tell from outside whether the system is alive and functioning. No health endpoint, no heartbeat message, no monitoring.
- **Fix:** (1) Add `/api/health` endpoint (uptime, last scan, open positions, connection status). (2) Send Telegram heartbeat every N minutes (configurable). (3) Alert if heartbeat is missed (dead man's switch via external monitor).
- **Impact:** System could be silently dead for hours before anyone notices.

### AT-17: No API rate limit tracking [P2]
- **Status:** OPEN
- **File:** `engine/src/execution/binance_testnet.py`
- **Problem:** Binance has rate limits (1200 requests/minute for orders, 2400 for general). During fast markets or error-retry loops, the system could hit limits and get IP-banned temporarily.
- **Fix:** Track request counts per minute. Back off when approaching limits. Parse `X-MBX-USED-WEIGHT` headers from responses.
- **Impact:** IP ban during critical market moment = stuck positions.

### AT-18: No disk space / DB size monitoring [P4]
- **Status:** OPEN
- **File:** SQLite database
- **Problem:** Trade journal SQLite file grows indefinitely. On a small disk (VPS), this could eventually fill the disk, crashing the system.
- **Fix:** (1) Periodically log DB size. (2) Archive old data (>90 days) to separate file. (3) Alert if DB > 500MB.
- **Impact:** Low urgency — takes months to become a problem.

### AT-19: Funding rate not handled in live system [P2]
- **Status:** OPEN
- **File:** `engine/src/execution/binance_testnet.py`
- **Problem:** The backtester deducts funding rates every 8 hours (good), but the live autonomous trader doesn't account for funding rates. Positions held across funding intervals get charged 0.01% of notional, which erodes profits on longer trades.
- **Fix:** (1) Query funding rate from exchange API. (2) Factor into position P&L tracking. (3) Consider closing positions before unfavorable funding events.
- **Impact:** Profits slowly eroded on positions held >8 hours.

### AT-20: Spread as percentage of SL on tight stops [P3]
- **Status:** OPEN
- **File:** `engine/src/data/instruments.py`
- **Problem:** On tight SL trades, spread consumes a large percentage of the risk. BTC $5 spread / $300 SL = 1.7%. ETH $1 spread / $50 SL = 2%. Gold $0.30 spread / $2 SL = 15%. The system doesn't check if spread/SL ratio is acceptable.
- **Fix:** Add spread/SL ratio check: reject trades where spread > 5% of SL distance.
- **Impact:** Tight-stop trades have systematically worse R:R than calculated.

### AT-21: Overtrading risk on small accounts [P3]
- **Status:** OPEN
- **File:** `engine/src/agent/config.py:78`
- **Problem:** 6 trades/day * 0.3% risk * 30 days = 54% of account at risk per month. On a small account, even with 58% win rate, a 5-trade losing streak (probability ~1.3% per day) wipes 1.5% — hitting the daily halt. Repeated halts mean the system is often idle.
- **Fix:** (1) For small accounts, reduce max_trades_per_day to 2-3. (2) Calculate expected halt frequency at given parameters. (3) Adaptive: reduce trades/day after consecutive halts.
- **Impact:** System may be halted more often than trading on small accounts.

### AT-22: No WebSocket for real-time prices [P1]
- **Status:** DEFERRED (candle-freshness check is interim fix; full WebSocket is Phase 2)
- **File:** `engine/src/data/market_data.py` (not reviewed but referenced)
- **Problem:** Price data is fetched via REST API calls every scan interval. For crypto (24/7), this means 1440 API calls per day per symbol per timeframe. WebSocket provides real-time streaming with one connection.
- **Fix:** Implement Binance WebSocket kline streams for active symbols. Fall back to REST for non-crypto. Trigger scans on candle close events instead of polling.
- **Impact:** Stale prices, wasted API calls, missed entries.

### AT-23: httpx client not properly managed [P3]
- **Status:** OPEN
- **File:** `engine/src/execution/binance_testnet.py:49, 72`
- **Problem:** `self._client` is created lazily on first request and may not be properly closed on shutdown. If `disconnect()` isn't called, connections leak.
- **Fix:** Use async context manager pattern. Ensure disconnect is called in shutdown hook.
- **Impact:** Resource leak on long-running processes.

---

## SUMMARY

| Panel | P0 | P1 | P2 | P3 | P4 | Total |
|-------|----|----|----|----|----|----|
| Quant Researcher | 4 | 3 | 1 | 4 | 1 | 13 |
| AI/ML Specialist | 3 | 1 | 5 | 4 | 0 | 13* |
| Algo Trading | 4 | 7 | 6 | 4 | 1 | 22* |
| **Total** | **11** | **11** | **12** | **12** | **2** | **48** |

*Some issues overlap across panels (QR-07 and AT-14 are the same root cause).

### Fix Order

**Phase 1 — Fix before paper trading on Binance Demo:**
All P0 issues (11 items)

**Phase 2 — Fix before real money on CoinDCX:**
All P1 issues (11 items)

**Phase 3 — Fix before scaling up / FundingPips:**
All P2 issues (12 items)

**Phase 4 — Ongoing improvements:**
P3 + P4 (14 items)

---

## REVIEW HISTORY

| Date | Session | Panels Used | Issues Found | Issues Fixed |
|------|---------|-------------|-------------|-------------|
| 2026-03-22 | 4a | Quant, AI/ML, Algo | 48 | 0 |
| 2026-03-22 | 4a (fixes) | — | 0 | 11 (all P0s) |
| — | Next | TBD | — | — |
