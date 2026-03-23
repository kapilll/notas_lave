# Mode A: Fresh Review — 2026-03-23

**Reviewer:** Claude Opus 4.6 (1M context)
**Scope:** All 10 expert panels, full codebase read
**Files read:** 30+ core Python files, tests, configs, context docs
**Mode:** Fresh review — no prior issues referenced

---

## Panel 1: QUANT RESEARCHER — Fresh Findings

### Issues Found

#### QR-A01: Live/Backtest Signal Selection Mismatch [Severity: P0]
- **File:** `engine/src/backtester/engine.py:600-608` vs `engine/src/confluence/scorer.py:212-320`
- **Problem:** The backtester iterates strategies individually and takes the **first qualifying signal** (`break` on line 608: "QR-23: Take first qualifying, not best"). But the live autonomous trader calls `compute_confluence()` which runs **all** strategies, computes a weighted category score, determines consensus direction from vote counts, and adds an agreement bonus. These are fundamentally different signal selection mechanisms. Backtest results do not predict live performance.
- **Fix:** The backtester must use `compute_confluence()` as its signal source, just like the live system. Replace the individual strategy iteration in `Backtester.run()` with a call to `compute_confluence(window, symbol, timeframe)` and use the composite score/direction from the result.
- **Impact:** Every backtest metric (WR, PF, Sharpe, equity curve) is measuring a system that doesn't match what runs live. This invalidates all walk-forward validation, Monte Carlo results, and optimizer outputs.

#### QR-A02: Backtester End-of-Data Close Ignores Fees [Severity: P2]
- **File:** `engine/src/backtester/engine.py:722-731`
- **Problem:** When force-closing remaining open trades at end of data, P&L is computed without deducting trading fees (entry + exit). Normal trade closes (line 503-505) properly deduct `entry_fee + exit_fee`. This inflates end-of-data P&L for fee-bearing instruments.
- **Fix:** Add fee deduction: `entry_fee = spec.calculate_trading_fee(trade.entry_price, trade.position_size)` + `exit_fee = spec.calculate_trading_fee(trade.exit_price, trade.position_size)` before adding P&L to balance.
- **Impact:** Slightly inflated backtest results on CoinDCX instruments.

#### QR-A03: Backtester Entry Price Rounding Bias [Severity: P3]
- **File:** `engine/src/backtester/engine.py:703`
- **Problem:** Entry price is `round(entry, 2)` regardless of instrument. Crypto instruments like PEPE have `pip_size=0.00000001` — rounding to 2 decimals destroys precision. Gold at $2000 loses nothing, but DOGE at $0.15 loses meaningful precision.
- **Fix:** Use `round(entry, int(-math.log10(spec.pip_size)))` or simply don't round (the instrument spec handles precision via `lot_step`).
- **Impact:** Small systematic bias in backtest P&L for low-price instruments.

### What's Good
- Walk-forward validation with proper train/test split and OOS equity curve reconstruction
- Monte Carlo with block bootstrap preserving serial correlation
- Next-candle entry (QR-26) eliminating look-ahead bias
- Sortino/Calmar ratios alongside Sharpe
- Zero-return day filling for accurate Sharpe calculation
- Multiple-comparison deflation in optimizer (QR-17)
- Min-lot rejection when risk budget would be exceeded (QR-07)

### Verdict
**Not ready for live trading.** The live/backtest signal mismatch (QR-A01) means all validation work is measuring the wrong system.

---

## Panel 2: AI/ML SPECIALIST — Fresh Findings

### Issues Found

#### ML-A01: No Real Machine Learning — Heuristic Masquerading as Learning [Severity: P2]
- **File:** `engine/src/learning/recommendations.py:274-337`
- **Problem:** Weight adjustment uses softmax-like normalization on avg P&L per category. This is a weighted moving average, not machine learning. There's no gradient descent, no feature engineering, no model training. The system calls itself "EVOLVE" but adapts via simple binning (good category → more weight, bad → less). This is fine for early stage, but the code/docs imply more sophistication than exists.
- **Fix:** Acknowledge this is rule-based adaptation. For real ML: after 500+ trades, extract features (RSI at entry, ATR ratio, volume ratio, time of day, regime, score) and train XGBoost/logistic regression on trade outcomes. The infrastructure (grading, feature storage) is partially there.
- **Impact:** Weight adjustments may not converge to optimal values; they oscillate around noise.

#### ML-A02: Claude Fallback Grading Has Outcome Bias Despite Comments Claiming Otherwise [Severity: P2]
- **File:** `engine/src/agent/trade_learner.py:279-330`
- **Problem:** The `_fallback_analysis()` function comments say it grades by "process quality" (confluence score + R:R). However, the first branch is `if position.exit_reason == "tp_hit"` and the second is `elif position.exit_reason == "sl_hit"` — it's still **outcome-first** branching. A high-quality setup that hits SL gets C; a low-quality setup that hits TP gets B. True process grading would grade solely on setup quality (score, R:R, regime match) and be outcome-agnostic.
- **Fix:** Grade purely on process: score >= 7 AND R:R >= 2.0 → A regardless of outcome. Score < 5 OR R:R < 1.5 → D regardless of outcome. Then annotate with outcome as metadata, not as a grading input.
- **Impact:** The learning engine still learns "TP hit = good trade" which is exactly the outcome bias it claims to fix.

#### ML-A03: Prediction Accuracy Tracker Accesses Private Cache `_md._cache` [Severity: P3]
- **File:** `engine/src/learning/accuracy.py:189`
- **Problem:** `resolve_pending_predictions()` accesses `_md._cache` — a private implementation detail of the market data provider. If the cache structure changes, this silently breaks.
- **Fix:** Add a public method `market_data.get_cached_candles(symbol, timeframe)` that returns cached candles or None. Keeps the API contract stable.
- **Impact:** Fragile coupling; predictions may silently stop resolving if cache implementation changes.

### What's Good
- Exponential decay weighting (ML-13) is a sound approach for time-decaying relevance
- Process-quality grading concept is directionally correct (needs execution fix)
- Per-trade Claude analysis with cross-trade memory (last 5 trades on same symbol)
- Adjustment cooldown prevents daily churn (7 days + 10 trades minimum)
- Performance degradation detection (ML-27) creates visibility into whether adjustments help
- A/B testing framework with proper statistical testing (z-test when scipy available)

### Verdict
The learning system logs extensively but learns weakly. Rule-based adaptation with cooldowns is appropriate for the current data volume. The system should graduate to real ML after 500+ trades.

---

## Panel 3: ALGORITHMIC TRADING ADVISER — Fresh Findings

### Issues Found

#### AT-A01: Open Positions Have ZERO Stop Loss Protection When Engine Is Down [Severity: P0]
- **File:** `docs/context/SESSION-CONTEXT.md:76-77`, `engine/src/execution/binance_testnet.py:439-459`
- **Problem:** Binance Demo rejects `STOP_MARKET` orders (error -4120). SL/TP is managed locally by `paper_trader.update_positions()`. When the engine stops (crash, restart, deployment), every open position on Binance has **no stop loss**. A 10% adverse move during downtime wipes the account.
- **Fix:** Three options: (1) On graceful shutdown, close all positions via market order. (2) Implement a lightweight watchdog process that monitors positions independently. (3) Move to an exchange/mode that supports server-side stop orders. At minimum, add a shutdown hook: `signal.signal(signal.SIGTERM, lambda: close_all_positions())`.
- **Impact:** A single engine crash during a volatile move can cause total account loss.

#### AT-A02: `paper_trader.open_position()` Returns None But Caller Doesn't Check [Severity: P1]
- **File:** `engine/src/agent/autonomous_trader.py:484,511` + `engine/src/execution/paper_trader.py:483-499`
- **Problem:** `PaperTrader.open_position()` returns `None` when SL/TP validation fails (e.g., SL >= entry for LONG after spread application). Lines 484 and 511 then do `position.entry_atr = prod_atr` — this crashes with `AttributeError: 'NoneType' object has no attribute 'entry_atr'`. Although the risk manager pre-validates SL/TP, the paper_trader applies spread to entry which could push entry past SL for very tight stops.
- **Fix:** Add `if position is None: continue` after both `open_position()` calls (lines 483 and 510).
- **Impact:** Unhandled exception crashes the trading loop. The `except Exception` on line 537 catches it, but the loop continues to the next symbol without logging the specific failure.

#### AT-A03: No Graceful Shutdown — Positions Become Orphans [Severity: P1]
- **File:** `engine/src/agent/autonomous_trader.py:119-124`
- **Problem:** `stop()` cancels the asyncio task but doesn't close open positions or cancel exchange orders. If `BROKER != "paper"`, exchange positions remain open with orphaned SL/TP orders that could trigger on future unrelated positions.
- **Fix:** Before stopping, iterate `paper_trader.positions` and call `broker.close_position(symbol)` for each. Also cancel all open orders via `broker._delete("/fapi/v1/allOpenOrders")`.
- **Impact:** Orphaned exchange positions and orders after restart.

#### AT-A04: `_last_position_eval` Uses hasattr Instead of __init__ [Severity: P3]
- **File:** `engine/src/agent/autonomous_trader.py:167`
- **Problem:** `not hasattr(self, '_last_position_eval')` — this attribute is created at runtime instead of being declared in `__init__`. This is a fragile pattern; if the check passes before the first assignment, `self._last_position_eval is None` is redundant.
- **Fix:** Add `self._last_position_eval: datetime | None = None` to `__init__`.
- **Impact:** Minor fragility; works but violates clean initialization patterns.

### What's Good
- Position reconciliation every 5 min with Telegram alerts on mismatch
- Auto-reconnect after consecutive broker failures (AT-07)
- Exchange fill detection (`_detect_exchange_fills`) syncs local state with exchange
- Fill deviation monitoring (MM-08) catches bad fills
- Symbol mapping with clear error for unmapped/metal symbols
- Rate limit tracking for Binance API
- Exponential backoff retry with no-retry on client errors (400/401/403)

### Verdict
The system handles the happy path well but lacks crash resilience. The zero-SL-on-downtime issue (AT-A01) is the single biggest risk to real money.

---

## Panel 4: SECURITY ENGINEER — Fresh Findings

### Issues Found

#### SE-A01: API Key Sent in Plaintext HTTP Header (Binance) [Severity: P2]
- **File:** `engine/src/execution/binance_testnet.py:200-201`
- **Problem:** The Binance API key is sent in the `X-MBX-APIKEY` header on every request. This is Binance's required auth mechanism, so it can't be changed. However, the key is stored as a plain `str` in config (`binance_testnet_key`), not as `SecretStr`. If the config object is ever serialized or logged, the key is exposed.
- **Fix:** Change `binance_testnet_key` to `SecretStr` in `config.py` and use `.get_secret_value()` in the header. The secret (`binance_testnet_secret`) already uses `SecretStr` — the key should too.
- **Impact:** Key exposure if config object is logged/serialized (e.g., in error messages).

#### SE-A02: Local API Has No Authentication [Severity: P2]
- **File:** `engine/src/config.py:112`
- **Problem:** `api_key` is defined but the review doesn't show any middleware enforcing it. The comment says "If empty, auth is disabled (dev mode)." If the API is exposed (even on localhost), any local process can place trades, close positions, or trigger clean-slate resets.
- **Fix:** Add API key validation middleware for all mutation endpoints (`POST`, `DELETE`). Already binding to `127.0.0.1` (SEC-02), which helps, but isn't sufficient if other local services are compromised.
- **Impact:** Any local process can manipulate trades/positions without authentication.

#### SE-A03: `_load_adjustment_state()` Uses Raw json.load Instead of Pydantic Schema [Severity: P3]
- **File:** `engine/src/learning/recommendations.py:53-61`
- **Problem:** `AdjustmentState` Pydantic schema exists in `schemas.py` but `_load_adjustment_state()` uses raw `json.load()`. If the file is malformed or contains unexpected types, this silently returns bad data. All other JSON files use `safe_load_json()`.
- **Fix:** Replace with `safe_load_json(_ADJUSTMENT_STATE_FILE, AdjustmentState)` and convert the result to dict, or change the function to return an `AdjustmentState` instance.
- **Impact:** Minor inconsistency; raw json.load won't crash but bypasses validation.

#### SE-A04: Secrets Could Leak via Exception Tracebacks [Severity: P3]
- **File:** `engine/src/execution/binance_testnet.py:293-298`
- **Problem:** The `except Exception as e` block logs `e` which could contain request parameters including timestamps and signatures. While signatures alone aren't secrets, they reveal the HMAC pattern. Error response sanitization (SEC-07) only applies to response bodies, not to exception messages from httpx which may include the full URL with query parameters.
- **Fix:** In the catch-all exception handler, log `type(e).__name__` instead of the full exception message, or sanitize the message to remove query parameters.
- **Impact:** Low risk — signatures expire quickly, but defense-in-depth suggests sanitizing.

### What's Good
- `SecretStr` for API secrets (Binance secret, CoinDCX secret, MT5 password)
- `.env` file permission checking (SEC-03) with warning on world-readable
- DB permission checking (SE-23) with auto-fix to 0o600
- HMAC SHA256 signing for Binance with `hmac.compare_digest()` for constant-time comparison (SEC-04)
- `safe_float()` for exchange response parsing (SEC-05) — handles NaN/Inf
- Explicit HTTP method dispatch instead of `getattr` (SEC-06)
- Error response sanitization — extracts code/msg instead of raw body (SEC-07)
- Server binds to localhost by default (SEC-02)

### Verdict
Good security posture for a personal trading system. The localhost binding is the most important control. API key protection for mutations should be enforced before any remote access.

---

## Panel 5: DEVOPS / SRE ENGINEER — Fresh Findings

### Issues Found

#### DO-A01: No Process Manager — Engine Runs as Bare Python Process [Severity: P1]
- **File:** `docs/context/SESSION-CONTEXT.md:14-16`
- **Problem:** The engine runs as `cd engine && python -m uvicorn ...` with no process manager (systemd, supervisord, Docker). If the process crashes (OOM, unhandled exception, segfault), it stays dead. Combined with AT-A01 (no SL when down), this is catastrophic.
- **Fix:** Create a `systemd` service file or `supervisord` config with `restart=always` and `startretries=3`. Docker would also work. At minimum: `while true; do python run.py; sleep 5; done` in a tmux session.
- **Impact:** Unattended crashes leave positions unprotected indefinitely.

#### DO-A02: WAL Checkpoint and Backup Not Scheduled [Severity: P2]
- **File:** `engine/src/journal/database.py:571-632`
- **Problem:** `checkpoint_wal()` and `backup_database()` functions exist, and `run_db_maintenance()` calls both. But nothing schedules this — no cron job, no periodic task in the engine loop, no mention of it running automatically.
- **Fix:** Add a periodic call in the autonomous trader's tick (e.g., every 6 hours) or document a cron job: `0 */6 * * * cd /path && .venv/bin/python -c "from engine.src.journal.database import run_db_maintenance; run_db_maintenance()"`.
- **Impact:** WAL file grows unbounded; no backups exist for disaster recovery.

#### DO-A03: No Resource Monitoring (Memory, Disk, CPU) [Severity: P2]
- **File:** N/A (missing)
- **Problem:** The system runs 24/7 with in-memory position tracking, market data caching, and SQLite writes. No monitoring for memory usage, disk space (WAL growth, log rotation), or CPU. A memory leak or full disk would cause silent failure.
- **Fix:** Add a periodic health check that logs memory usage (`psutil.Process().memory_info().rss`), disk free space, and open file descriptors. Alert via Telegram if thresholds are breached.
- **Impact:** Silent degradation — system appears running but is failing.

#### DO-A04: Log Rotation Config Not Visible [Severity: P3]
- **File:** `docs/context/SESSION-CONTEXT.md:151`
- **Problem:** Context doc mentions "rotating, 10MB x 5" but I don't see the logging configuration in the files reviewed. If it's not actually configured, logs grow unbounded.
- **Fix:** Verify logging config exists (likely in `run.py` or a logging config file). If not, add `RotatingFileHandler(maxBytes=10*1024*1024, backupCount=5)`.
- **Impact:** Disk space exhaustion on long-running deployments.

### What's Good
- Health endpoint (`GET /health`) with uptime tracking
- Heartbeat every 1 hour via Telegram — operator knows the system is alive
- Error alerts with 5-minute cooldown to prevent spam
- Database WAL mode for concurrent read/write
- Data directory structure (`engine/data/`) with backup support
- Positions survive restart via DB reload (`_reload_open_positions`)

### Verdict
The system is designed for a developer watching it, not for unattended operation. Process management is the critical gap.

---

## Panel 6: DATA ENGINEER — Fresh Findings

### Issues Found

#### DE-A01: Data Lineage Is Broken — candle_timestamp Always NULL [Severity: P1]
- **File:** `engine/src/journal/database.py:64-65`
- **Problem:** `SignalLog` has `candle_timestamp` and `candle_close` columns marked "AUDIT: never written, never read (always NULL)". The DE-03 fix comment exists but was never implemented. You cannot trace a trade decision back to the specific candle that triggered it. This breaks the audit trail and makes post-hoc analysis unreliable.
- **Fix:** In `log_signal()`, accept `candle_timestamp` and `candle_close` parameters. In `autonomous_trader._scan_and_trade()`, pass `candles[-1].timestamp` and `candles[-1].close` to `log_signal()`.
- **Impact:** Cannot reconstruct why a trade was taken or verify signal correctness against historical data.

#### DE-A02: No OHLC Validation on Incoming Candle Data [Severity: P2]
- **File:** `engine/src/data/market_data.py` (not in review list but imported everywhere)
- **Problem:** Candle data from Binance/TwelveData is consumed without validation. If an exchange returns `high < low`, `close > high`, or `volume < 0`, the strategies compute garbage signals. The `Candle` dataclass in `models.py` is a plain dataclass with no validation.
- **Fix:** Add validation to `Candle.__post_init__()`: `assert self.low <= self.close <= self.high or self.low <= self.open <= self.high`. Log and discard invalid candles.
- **Impact:** Garbage-in-garbage-out: one bad candle can trigger a false signal across all strategies.

#### DE-A03: Stale Data Detection Exists But Response Is Only an Alert [Severity: P2]
- **File:** `docs/context/SESSION-CONTEXT.md:63`
- **Problem:** Data freshness monitoring sends an alert if candles are stale > 2x timeframe interval. But it doesn't **halt trading**. If the data source goes down, the system trades on stale data (the last cached candles), generating signals from old prices.
- **Fix:** In `_scan_and_trade()`, check the age of `candles[-1].timestamp`. If older than 2x the timeframe interval, skip this symbol entirely. This is partially done via `_is_candle_fresh()` but only checks the latest candle's age, not whether the data source is actually alive.
- **Impact:** Trading on stale data during data source outages.

### What's Good
- Binance as source of truth for balance and position state
- 5-minute integrity verification (DB vs exchange)
- Proper timezone handling for economic calendar (US Eastern with DST)
- DB indexes on frequently queried columns (DE-06)
- `load_only()` projection in analyzer to avoid loading large text blobs (DE-19)
- Pydantic schema validation for all JSON data files
- WAL mode for concurrent access

### Verdict
The storage layer is solid. Data ingestion is the weak link — no validation, no freshness-gated trading halt.

---

## Panel 7: RISK / COMPLIANCE OFFICER — Fresh Findings

### Issues Found

#### RC-A01: DailyStats.open_positions Can Drift After Mid-Day Restart [Severity: P1]
- **File:** `engine/src/risk/manager.py:133-156`
- **Problem:** When the day rolls over, `_get_today_stats()` carries forward `yesterday_open` from the previous day's DailyStats. But if the process restarts mid-day, the in-memory DailyStats is lost. The new day's stats start with `open_positions=0` (no yesterday to carry from). Meanwhile, `paper_trader._reload_open_positions()` loads positions from DB but never updates `risk_manager._get_today_stats().open_positions`. Result: the max concurrent check passes incorrectly, allowing more positions than the limit.
- **Fix:** After `_reload_open_positions()`, sync: `risk_manager._get_today_stats().open_positions = paper_trader.open_count`. This exists for production paper_trader (line 802-804) but only runs inside `_reload_open_positions` when `_track_risk=True`. Verify it runs in all paths.
- **Impact:** Could open more than `max_concurrent_positions` after a mid-day restart.

#### RC-A02: Consistency Rule Uses `total_pnl` Which Doesn't Include Current Day [Severity: P2]
- **File:** `engine/src/risk/manager.py:295-317`
- **Problem:** The consistency rule calculates `max_single_day = self.total_pnl * config.max_single_day_profit_pct`. But `total_pnl` is only updated by `record_trade_result()` after a trade closes. If a trader has $100 total_pnl from yesterday and wins $50 today (not yet in total_pnl because it's in `today.realized_pnl`), the 45% check uses stale total_pnl. On restart, `total_pnl` is loaded from DB, so it's correct — but within a session, `today.realized_pnl` is added to `total_pnl` via `record_trade_result()`, so this is actually correct. However, the check on line 299 uses `today.realized_pnl >= max_single_day` where `max_single_day` is based on `self.total_pnl` which INCLUDES today's P&L (since it's updated on every close). So as you win more today, both numerator and denominator grow. This is subtly wrong — FundingPips calculates consistency based on TOTAL profits at end of challenge, not in real-time.
- **Fix:** This is inherently hard to check in real-time since FundingPips evaluates it retrospectively. The current implementation is a reasonable approximation. Document the limitation.
- **Impact:** Mild — the current approximation is conservative (blocks too early rather than too late).

#### RC-A03: No Weekend Position Management for Crypto [Severity: P3]
- **File:** `engine/src/agent/autonomous_trader.py:282-286`
- **Problem:** Friday after 19:00 UTC blocks metals (XAUUSD, XAGUSD) due to weekend gap risk. But crypto positions (BTC, ETH) are left open over weekends. Crypto markets are 24/7, but weekend liquidity is lower, spreads are wider (2x per the spread model), and funding rates apply every 8h. For leveraged positions, weekend holding costs compound.
- **Fix:** Add a configurable weekend risk reduction: reduce max concurrent or position size on weekends, or add a Telegram warning when positions are held over weekend with leverage.
- **Impact:** Higher costs and wider slippage on weekend positions.

### What's Good
- Static total drawdown from `original_starting_balance` (RC-04) — correct FundingPips implementation
- Consistency rule with 1% threshold guard to avoid blocking on noise (RC-22)
- Hedging detection with mode-appropriate response (block in prop, warn in personal)
- Equity-based daily drawdown including unrealized P&L (RC-03)
- Inactivity monitoring with 25-day warning threshold (RC-11)
- HFT duration check (RC-19)
- Audit trail logging on every validate_trade() call (RC-14)
- Fill deviation monitoring (RC-09)
- Weight and blacklist guardrails with bounds (WEIGHT_BOUNDS, MAX_BLACKLIST_GROWTH_PER_WEEK)

### Verdict
Risk management is thorough for both prop and personal modes. The open_positions drift on restart (RC-A01) should be verified fixed before live trading.

---

## Panel 8: MARKET MICROSTRUCTURE EXPERT — Fresh Findings

### Issues Found

#### MM-A01: Spread Model Is Static Per-Session, Not Order-Book Based [Severity: P2]
- **File:** `engine/src/data/instruments.py:128-154`
- **Problem:** Spreads use hardcoded multipliers per session (Asian=2.5x, London=0.8x, etc.). Real spreads vary continuously based on order book depth, recent volatility, and event proximity. A 2.5x multiplier during Asian session might be too generous (actual could be 5x during low liquidity) or too conservative (market maker activity varies).
- **Fix:** For Binance, query the order book (`/fapi/v1/depth`) periodically and compute actual spread from best bid/ask. Use the model as a fallback. This is an enhancement, not a bug — the model is a reasonable approximation.
- **Impact:** Position sizing assumes tighter spreads than reality in some sessions, slightly overstating expected returns.

#### MM-A02: Funding Rate Model in Backtester Is ATR-Based Heuristic [Severity: P2]
- **File:** `engine/src/backtester/engine.py:386-414`
- **Problem:** The funding rate model uses ATR range as a proxy (high vol = 0.1%, moderate = 0.03%, low = 0.01%). Real funding rates on Binance depend on the basis between perpetual and spot prices, not on volatility alone. A trending market with low volatility can have high funding rates. The model underestimates costs during sustained trends.
- **Fix:** Query historical funding rates from Binance API for backtest periods (`/fapi/v1/fundingRate`). Fall back to the heuristic for periods without data.
- **Impact:** Backtest P&L is slightly overstated for leveraged crypto positions during trending markets.

#### MM-A03: Lab Instruments Missing Spread Multipliers [Severity: P3]
- **File:** `engine/src/data/instruments.py:36-73`
- **Problem:** `SPREAD_MULTIPLIERS` only covers XAUUSD, XAGUSD, BTCUSD, ETHUSD, BTCUSDT, ETHUSDT. The 14 other lab instruments (SOL, XRP, BNB, DOGE, ADA, AVAX, LINK, DOT, LTC, NEAR, SUI, ARB, PEPE, WIF, FTM, ATOM) use `spread_typical` at all times. `get_spread()` returns `spread_typical` when the symbol isn't in `SPREAD_MULTIPLIERS`.
- **Fix:** Add at least crypto-generic multipliers: `"_crypto_default": {"active": 0.7, "quiet": 1.5, "weekend": 2.0}` and use it as fallback in `get_spread()`.
- **Impact:** Backtests for these 14 instruments assume constant spreads, overstating fills during low-liquidity hours.

### What's Good
- Tick size rounding for Binance orders (MM-03) — prevents PRICE_FILTER rejections
- Slippage model per instrument (`slippage_ticks`) with asymmetric application (SL worse, TP better)
- Session-based spread multipliers for primary instruments
- Volatile regime spread widening (2.5x) in backtester
- Fill deviation logging (20% of SL distance threshold)
- Dynamic funding rate model (better than flat rate)
- Breakeven price accounts for spread, not just entry price

### Verdict
The microstructure modeling is reasonable for a retail-scale system. The static spread model is the main limitation but is adequate for current instrument selection.

---

## Panel 9: BEHAVIORAL FINANCE / TRADING PSYCHOLOGY EXPERT — Fresh Findings

### Issues Found

#### BF-A01: Binary Conviction Scaling Creates Threshold Flip-Flopping [Severity: P2]
- **File:** `engine/src/agent/autonomous_trader.py:344-348`
- **Problem:** Scores below 7.0 get 60% position size; scores at or above 7.0 get 100%. This binary threshold means a score of 6.9 gets 60% size and 7.0 gets 100% — a 67% size increase from a 0.1 score change. This creates behavioral inconsistency: the system treats 6.9 and 7.0 as fundamentally different conviction levels when they're nearly identical.
- **Fix:** Use continuous scaling: `scale = max(0.4, min(1.0, (score - 4.0) / 6.0))`. This smoothly scales from 40% at score 4 to 100% at score 10, with no discontinuity.
- **Impact:** Inconsistent risk allocation around the 7.0 boundary; small score noise causes large position size changes.

#### BF-A02: Loss Streak Throttle Assumes Regime Change = Signal to Reduce [Severity: P3]
- **File:** `engine/src/backtester/engine.py:666-676`
- **Problem:** The regime-conditional throttle (TP-03) only halves position size if the regime changed since the last win. Rationale: "losses in a stable regime are normal noise." But a regime change doesn't necessarily mean the strategy is wrong — the new regime might be better for the strategy. And consecutive losses in the SAME regime might signal the strategy is truly broken in that regime. The logic is inverted from what behavioral evidence suggests.
- **Fix:** Track per-strategy-per-regime loss streaks. Throttle when a specific strategy has 3+ losses in the current regime (it's failing in this condition), not when the regime changes (which is a new context where past losses are less relevant).
- **Impact:** Reduces size when it shouldn't (regime changed but strategy works in new regime) and doesn't reduce when it should (strategy failing in current regime).

#### BF-A03: Smart Exit Only Triggers After Breakeven — Misses Early Reversals [Severity: P3]
- **File:** `engine/src/execution/paper_trader.py:286-291`
- **Problem:** `health_should_exit` requires `self.breakeven_activated` (position must have moved 1:1 R in favor). If a position enters and immediately reverses with high conviction (RSI flips, volume surges against), the smart exit won't trigger because breakeven hasn't been reached. The system rides it to SL.
- **Fix:** Allow smart exit before breakeven if the reversal signal is strong enough (e.g., confluence score > 7 in opposite direction). The `_evaluate_open_positions()` in autonomous_trader partially does this (line 555-558) but also requires `breakeven_activated`.
- **Impact:** Misses early exit opportunities on strong reversals, increasing average loss size.

### What's Good
- Neutral Telegram framing (no WIN/LOSS labels) — prevents human emotional interference (TP-08)
- Lucky win detection (TP-01) — downgrades trades where MFE barely exceeded TP
- Process-quality grading concept (separates luck from skill)
- MFE/MAE tracking on every position for learning
- System WR displayed in close notifications instead of individual trade outcome
- Regime-conditional loss streak handling (conceptually sound, needs per-strategy refinement)
- No "revenge trading" pattern — cooldown per symbol enforces pause after trades

### Verdict
The system avoids the worst human biases (emotional framing, revenge trading) but has a few mechanical biases (binary thresholds, inverted regime logic) that need smoothing.

---

## Panel 10: CODE QUALITY / ARCHITECTURE REVIEWER — Fresh Findings

### Issues Found

#### CQ-A01: Singleton Pattern Used Extensively — Hinders Testing [Severity: P2]
- **File:** Multiple: `autonomous_trader.py:866`, `paper_trader.py:871`, `risk/manager.py:603`, `config.py:198`
- **Problem:** Module-level singletons (`risk_manager = RiskManager()`, `paper_trader = PaperTrader()`, `config = TradingConfig()`) are created at import time. This means: (1) Tests can't inject mocks without monkey-patching. (2) Import order matters — importing `paper_trader` triggers `config`, `risk_manager`, `market_data`, etc. (3) State bleeds between test cases unless manually reset.
- **Fix:** For testing, add a `reset()` method to each singleton. For future refactoring, consider dependency injection via constructor parameters. Not urgent — the current approach works for a single-process system.
- **Impact:** Test isolation issues; import-time side effects (DB creation, .env loading, permission checks).

#### CQ-A02: Backtester/Scorer Circular Import via INSTRUMENT_STRATEGY_BLACKLIST [Severity: P2]
- **File:** `engine/src/confluence/scorer.py:226` imports from `backtester/engine.py`; `backtester/engine.py:52` imports from `confluence/scorer.py`
- **Problem:** `scorer.py` imports `INSTRUMENT_STRATEGY_BLACKLIST` from `backtester/engine.py`, and `engine.py` imports `detect_regime` from `scorer.py`. This is a circular dependency that works because Python resolves it at function-call time (not import time), but it's fragile. Refactoring either module could trigger `ImportError`.
- **Fix:** Extract `INSTRUMENT_STRATEGY_BLACKLIST` into a separate module (e.g., `data/blacklists.py`) that both can import without circularity.
- **Impact:** Fragile imports; can break during refactoring.

#### CQ-A03: Dead Database Columns and Unused Table [Severity: P3]
- **File:** `engine/src/journal/database.py:55-65,119-137`
- **Problem:** Multiple columns marked "AUDIT: never written, never read" (e.g., `SignalLog.candle_timestamp`, `SignalLog.candle_close`, `ABTestResult.symbol`, `TokenUsage.model`). The entire `PerformanceSnapshot` table is unused. These create confusion about what's live vs dead.
- **Fix:** For columns that should be populated (like `candle_timestamp`), implement them. For truly dead columns, leave them in the schema but add a `DEPRECATED` suffix to the AUDIT comment. Don't remove them — it would break SQLite migration. Drop `PerformanceSnapshot` if it's truly never used.
- **Impact:** Developer confusion; dead code masking real functionality gaps.

#### CQ-A04: paper_trader.close_position Returns Inconsistent Types [Severity: P3]
- **File:** `engine/src/execution/paper_trader.py:568,667`
- **Problem:** `close_position()` returns `None` if `pos_id` not found (line 573), but returns `(pos, final_pnl)` tuple on success (line 667). Callers must handle both cases, and there's no type annotation to document this.
- **Fix:** Add return type `tuple[Position, float] | None` and ensure all callers check for None.
- **Impact:** Potential `TypeError` if caller unpacks the return without checking.

### What's Good
- Clear module boundaries (agent, strategies, confluence, risk, execution, learning, data, monitoring)
- Pydantic models for all JSON config files (schemas.py)
- ContextVar for per-task DB context — clean async isolation
- Strategy cache with `clear_strategy_cache()` for optimizer integration
- Dataclass usage with proper fields instead of dynamic attributes
- Type hints throughout the codebase
- Educational docstrings explaining WHY, not just WHAT
- Proper error handling: catch-all exceptions in tight loops, specific exceptions in business logic
- SQLAlchemy ORM with proper indexes

### Verdict
Well-structured codebase with good documentation. The singleton pattern and circular import are the main architectural concerns, but neither is blocking for a single-process system.

---

## Summary: Critical Path to Live Trading

### P0 Issues (Fix Now)
| ID | Panel | Issue |
|----|-------|-------|
| QR-A01 | Quant | Live/backtest signal selection mismatch — backtests measure wrong system |
| AT-A01 | Algo | Zero SL protection when engine is down — total account risk |

### P1 Issues (Fix Before Live)
| ID | Panel | Issue |
|----|-------|-------|
| AT-A02 | Algo | `open_position()` returns None but caller doesn't check — crash bug |
| AT-A03 | Algo | No graceful shutdown — orphaned exchange positions |
| DE-A01 | Data | Data lineage broken — candle_timestamp always NULL |
| RC-A01 | Risk | open_positions counter can drift after mid-day restart |
| DO-A01 | DevOps | No process manager — crashes leave system dead |

### P2 Issues (Fix Before Scaling)
| ID | Panel | Issue |
|----|-------|-------|
| QR-A02 | Quant | End-of-data close ignores fees |
| ML-A01 | ML | No real ML — heuristic weight adjustment |
| ML-A02 | ML | Fallback grading still has outcome bias |
| SE-A01 | Security | Binance API key not SecretStr |
| SE-A02 | Security | Local API has no auth enforcement |
| DE-A02 | Data | No OHLC validation on incoming candles |
| DE-A03 | Data | Stale data only alerts, doesn't halt trading |
| DO-A02 | DevOps | WAL checkpoint + backup not scheduled |
| DO-A03 | DevOps | No resource monitoring |
| MM-A01 | Microstructure | Static spread model, not order-book based |
| MM-A02 | Microstructure | Funding rate heuristic, not real rates |
| BF-A01 | Psychology | Binary conviction scaling threshold |
| CQ-A01 | Code | Singletons hinder testing |
| CQ-A02 | Code | Circular import via blacklist |
| RC-A02 | Risk | Consistency rule timing subtlety |

### P3 Issues (Improvement)
| ID | Panel | Issue |
|----|-------|-------|
| QR-A03 | Quant | Entry price rounding ignores instrument precision |
| ML-A03 | ML | Private cache access in accuracy tracker |
| SE-A03 | Security | adjustment_state.json bypasses Pydantic |
| SE-A04 | Security | Secrets could leak via tracebacks |
| DO-A04 | DevOps | Log rotation config not verified |
| MM-A03 | Microstructure | 14 lab instruments missing spread multipliers |
| BF-A02 | Psychology | Regime-change throttle logic may be inverted |
| BF-A03 | Psychology | Smart exit requires breakeven first |
| RC-A03 | Risk | No weekend risk management for crypto |
| CQ-A03 | Code | Dead DB columns and unused table |
| CQ-A04 | Code | close_position inconsistent return types |
| AT-A04 | Algo | hasattr instead of __init__ for attribute |
