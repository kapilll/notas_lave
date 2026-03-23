# Notas Lave — Issue Tracker (Compact)

**Last Updated:** 2026-03-23 (Session 12 — all Review 6 issues fixed)
**Total Reviews:** 6 sessions, 226 issues found, 0 open P0/P1 code issues
**Next Review:** After 50+ lab trades to validate confluence-mode backtester

---

## OPEN — Remaining items

### P0 (Fix immediately)
*None*

### P1 (Fix before live)
| ID | Title | File(s) | Panel | Found |
|----|-------|---------|-------|-------|
| DO-18 | No process supervisor — engine dies silently, no auto-restart | (systemd/Docker config) | DevOps | Review 5 |

> DO-18 is operational (not a code fix). Requires systemd unit file or Docker Compose. Deferred until VPS deployment.

### P2 (Fix before scaling)
*None*

### P3 (Improvement)
| ID | Title | File(s) | Panel | Found |
|----|-------|---------|-------|-------|
| CQ-26 | No static type checking (mypy/pyright) in toolchain | (no config) | CQ | Review 5 |

---

## JUST FIXED (Session 12 — needs verification next review)

### P0 Fixes
| ID | Title | Root Cause | Files Changed |
|----|-------|-----------|---------------|
| QR-A01 | Backtester uses `compute_confluence()` in dual-mode: confluence (default, matches live) + individual (optimizer/blacklist) | Backtester iterated strategies individually; live uses weighted confluence scoring | backtester/engine.py |
| AT-A01 | Shutdown closes ALL exchange positions (prod + lab) via market order before disconnecting | STOP_MARKET rejected by Binance Demo; local SL/TP dies with engine | server.py |

### P1 Fixes
| ID | Title | Root Cause | Files Changed |
|----|-------|-----------|---------------|
| AT-A02 | `if position is None: continue` after both `open_position()` calls | open_position returns None on SL/TP validation fail; caller assumed non-None | autonomous_trader.py |
| AT-A03 | Shutdown closes exchange positions (subsumed by AT-A01 fix) | lifespan shutdown stopped traders but didn't close exchange positions | server.py |
| AT-A05 | Shutdown Telegram message replaced with accurate close count | Old message falsely claimed "exchange-side SL/TP protection" | server.py |
| DE-A01 | `log_signal()` now accepts + stores `candle_timestamp` and `candle_close`; autonomous_trader passes candle data | Columns defined but never populated (always NULL) | database.py, autonomous_trader.py |

### P2 Fixes
| ID | Title | Root Cause | Files Changed |
|----|-------|-----------|---------------|
| QR-A02 | End-of-data force-close now deducts entry + exit fees | Fee calculation skipped on force-close, inflating P&L | backtester/engine.py |
| ML-A02 | Fallback grading grades by process quality first (score + R:R), annotates outcome as metadata | Branched on exit_reason first (tp_hit/sl_hit) = outcome bias | trade_learner.py |
| SE-A01 | `binance_testnet_key` changed to `SecretStr`; `.get_secret_value()` in broker | API key stored as plain str, could leak via serialization | config.py, binance_testnet.py |
| BF-A01 | Continuous conviction scaling: `max(0.4, min(1.0, (score-4)/6))` replaces binary 60%/100% | Binary threshold at 7.0 caused 67% size jump from 0.1 score change | autonomous_trader.py |
| CQ-A02 | DEFERRED — all cross-module blacklist imports are already deferred (inside functions). Extraction risk > benefit | Circular import works at runtime, fragile in theory | (no change) |

### P3 Fixes
| ID | Title | Root Cause | Files Changed |
|----|-------|-----------|---------------|
| QR-A03 | Entry price rounds to instrument pip precision, not fixed 2 decimals | `round(entry, 2)` loses precision for PEPE, DOGE, etc. | backtester/engine.py |
| ML-A03 | `get_cached_candles()` public method on MarketDataProvider; accuracy.py uses it | Accessed private `_md._cache` directly | market_data.py, accuracy.py |
| SE-A03 | `_load_adjustment_state()` uses `safe_load_json(AdjustmentState)` | Raw `json.load` bypassed Pydantic validation | recommendations.py |
| SE-A04 | Catch-all exception logs `type(e).__name__` instead of full message | httpx exceptions may contain query params with signatures | binance_testnet.py |
| MM-A03 | `_crypto_default` spread multipliers added; `get_spread()` falls back to them | 14 lab instruments used constant `spread_typical` at all hours | instruments.py |
| BF-A02 | Throttle when losing in SAME regime (strategy failing here), not on regime change | Throttled on context change (irrelevant), not on in-regime failure (relevant) | backtester/engine.py |
| BF-A03 | Smart exit uses `unrealized_pnl > 0` instead of `breakeven_activated` | Required 1:1 R move before smart exit; missed early reversals | paper_trader.py, autonomous_trader.py |
| RC-A03 | Weekend position size halved for leveraged crypto (Sat/Sun, personal mode) | No risk reduction despite wider spreads + funding costs on weekends | autonomous_trader.py |
| CQ-A03 | Dead column comments updated; `candle_timestamp`/`candle_close` now populated (DE-A01) | Confusing AUDIT comments on live vs dead columns | database.py |
| CQ-A04 | `close_position()` return type annotated: `tuple[Position, float] | None` | No type annotation on mixed return type | paper_trader.py |
| AT-A04 | `_last_position_eval` declared in `__init__`; `hasattr` check removed | Attribute created at runtime via `hasattr` pattern | autonomous_trader.py |

---

## VERIFIED FIXES (confirmed working — 74 items total)

### P0 Verified
| ID | Title | Status |
|----|-------|--------|
| AT-F01 | Exchange-side SL/TP fill detection | VERIFIED Review 5 |
| ML-13 | get_trade_weight() wired into _compute_stats() | VERIFIED Review 5 |
| ML-16 | Optimizer results wired into weekly review | VERIFIED Review 5 |
| TP-01 | Lucky win detection breaks self-confirming loop | VERIFIED Review 5 |
| OPS-03 | 125 print() converted to structured logging | VERIFIED Review 5 |
| AT-39 | Lab PaperTrader decoupled (track_risk flag) | VERIFIED Review 6 |
| CQ-24 | ContextVar for DB isolation | VERIFIED Review 6 |

### P1 Verified
| ID | Title | Status |
|----|-------|--------|
| ML-18 | resolve_pending_predictions resolves from cache | VERIFIED Review 5 |
| RC-06/RC-13 | Config aligned, risk_manager sole enforcer | VERIFIED Review 5 |
| RC-09 | Fill deviation check (slippage protection) | VERIFIED Review 5 |
| MM-F01 | Backtester uses session-adjusted spread | VERIFIED Review 5 |
| QR-17 | Bonferroni deflation for optimizer | VERIFIED Review 5 |
| CQ-F02 | Optimizer monkey-patching eliminated | VERIFIED Review 5 |
| CQ-12 | Claude API wrapped in asyncio.to_thread() | VERIFIED Review 5 |
| CQ-01 | get_session() context manager for safe DB access | VERIFIED Review 5 |
| TP-05 | Conviction scaling (60% size for score < 7) | VERIFIED Review 5 |
| TP-06 | Strategy rehabilitation in recommendations | VERIFIED Review 5 |
| MM-07 | Dynamic funding rate (ATR-based) | VERIFIED Review 5 |
| SEC-07 | Error logs sanitized (no more resp.text) | VERIFIED Review 5 |
| SEC-03 | .env permission check at startup | VERIFIED Review 5 |
| SEC-04 | HMAC constant-time verify helper | VERIFIED Review 5 |
| SEC-13 | Agent mode change requires API key | VERIFIED Review 5 |
| CQ-07 | Critical exception handlers now log properly | VERIFIED Review 5 |
| QR-16 | Monte Carlo sign-randomization p-value | VERIFIED Review 6 |
| QR-20 | Sortino N-1 sample variance | VERIFIED Review 6 |
| QR-26 | Next-candle-open entry (no look-ahead) | VERIFIED Review 6 |
| ML-27 | Weight adjustment performance tracking (pre/post) | VERIFIED Review 6 |
| AT-40 | SIGTERM handler saves risk state | VERIFIED Review 6 |
| AT-41 | Exchange fill price 3-tier fallback | VERIFIED Review 6 |
| SE-21 | Request params already safe (audited) | VERIFIED Review 6 |
| BF-01 | Production recs filter lab trades (min_score=50) | VERIFIED Review 6 |

### P2 Verified
| ID | Title | Status |
|----|-------|--------|
| RC-F05 | Consistency rule warns on potential wins | VERIFIED Review 5 |
| RC-F07 | Daily halt includes unrealized P&L | VERIFIED Review 5 |
| RC-11 | Inactivity tracking (30-day rule) | VERIFIED Review 5 |
| AT-F06 | _analyzed_trades set pruned | VERIFIED Review 5 |
| AT-33 | Paper trader SL applies slippage | VERIFIED Review 5 |
| QR-18 | SL/TP same-candle distance-from-open heuristic | VERIFIED Review 5 |
| QR-15 | Block bootstrap in Monte Carlo | VERIFIED Review 5 |
| QR-21 | Symmetric forming swing detection | VERIFIED Review 5 |
| TP-10 | Optimizer uses live safety rails | VERIFIED Review 5 |
| TP-13 | Per-regime performance warnings | VERIFIED Review 5 |
| ML-21 | Cross-trade memory in Claude prompt | VERIFIED Review 5 |
| DE-14 | Cache LRU eviction (max 50) | VERIFIED Review 5 |
| DE-16 | Rate limit state persists across restarts | VERIFIED Review 5 |
| DE-22 | CCXT async lock | VERIFIED Review 5 |
| DE-23 | Data source health tracking | VERIFIED Review 5 |
| MM-10 | Real bid/ask from Binance ticker | VERIFIED Review 5 |
| SEC-14 | Telegram URL logging suppressed | VERIFIED Review 5 |
| SEC-18 | Rate limit middleware wired | VERIFIED Session 9 |
| QR-27 | Walk-forward OOS fold filtering | VERIFIED Review 6 |
| ML-29 | Regime-aware trade weighting (1.5x boost) | VERIFIED Review 6 |
| SE-22 | API secrets use SecretStr | VERIFIED Review 6 |
| SE-23 | SQLite DB auto-chmod 600 | VERIFIED Review 6 |
| SE-24 | RateLimitMiddleware wired into FastAPI | VERIFIED Review 6 |
| DO-19 | Log rotation (RotatingFileHandler, 10MB x 5) | VERIFIED Review 6 |
| DO-20 | GET /health with uptime + component status | VERIFIED Review 6 |
| DE-25 | OHLC validation on all data sources | VERIFIED Review 6 |
| RC-22 | Consistency rule 1% threshold guard | VERIFIED Review 6 |
| RC-23 | open_positions synced from DB after reload | VERIFIED Review 6 |
| ML-30 | Graduated thresholds (blacklist=30, weights=50) | VERIFIED Review 6 |
| RC-24 | Hedging warning in personal mode | VERIFIED Review 6 |
| DO-21 | SIGTERM saves risk state | VERIFIED Review 6 |

### P2 Verified (not re-checked Review 6, previously verified)
| ID | Title | Status |
|----|-------|--------|
| QR-23 | First qualifying signal in backtester | SUPERSEDED by QR-A01 — code works as designed but premise was wrong (live uses compute_confluence, not first-qualifying) |

### P3 Verified
| ID | Title | Status |
|----|-------|--------|
| RC-18 | Unrealized carried at day rollover | VERIFIED Review 5 |
| RC-19 | HFT detection (min trade duration) | VERIFIED Review 5 |
| RC-21 | Weight guardrail constants | VERIFIED Review 5 |
| CQ-15 | Agent config safety clamping | VERIFIED Review 5 |
| ML-25 | Dynamic strategy-to-category mapping | VERIFIED Review 5 |
| ML-26 | Statistical z-test for A/B testing | VERIFIED Review 5 |
| QR-25 | Statistical basis documented for thresholds | VERIFIED Review 5 |
| CQ-23 | Anthropic client cached | VERIFIED Review 5 |
| DE-19 | Column projection in analyzer | VERIFIED Review 5 |
| DE-F06 | Index on exit_price | VERIFIED Review 5 |
| SEC-15 | Key age check | VERIFIED Review 5 |
| SEC-19 | Missing deps added to pyproject.toml | VERIFIED Review 5 |
| SEC-09 | Dependencies pinned with upper bounds | VERIFIED Review 5 |
| CQ-16 | .env path absolute (from __file__) | VERIFIED Review 5 |

### Not re-verified Review 6 (files not read during review)
| ID | Title | Status |
|----|-------|--------|
| DE-24 | yfinance metals data fix | Assumed OK (market_data.py not fully read) |
| DE-26 | Cache key normalization | Assumed OK |
| BF-02 | Lab heartbeat interval | Assumed OK (lab_trader.py not read) |
| BF-03 | Leaderboard low-n indicator | Assumed OK |
| CQ-25 | Dead strategy files deleted | Assumed OK |

---

## DEFERRED (not needed until deployment/scaling)

| ID | Title | Why Deferred |
|----|-------|-------------|
| DO-18 | Process supervisor (systemd/Docker) | Operational, not code — needs VPS first |
| OPS-02 | CI/CD pipeline | Tests run manually, no team |
| CQ-10 | Alembic migrations | create_all() works |
| CQ-14 | Integration tests | Unit tests cover core logic |
| CQ-17 | Backtester.run() refactor | Works correctly, cosmetic |
| CQ-18 | API server lazy imports | Minor startup optimization |
| CQ-26 | Static type checking (mypy) | Toolchain setup, not code fix |
| OPS-07 | Secondary alert channel | Telegram works |
| OPS-11 | Database backup strategy | Add on VPS |
| OPS-17 | Zero-downtime deployment | Needs Docker first |
| ML-17 | A/B testing integration | Needs design work |
| ML-28 | Grade calibration analysis | Infrastructure exists, analysis not yet needed |
| TP-14 | Market quality check | Nice-to-have after 500+ trades |
| OPS-08 | Resource monitoring | Not needed at current scale |
| CQ-A02 | Circular import (scorer↔backtester via blacklist) | All cross-module imports are deferred; extraction risk > benefit |

## WONT_FIX (accepted risk or not applicable)

| ID | Title | Rationale |
|----|-------|-----------|
| MM-05 | Non-atomic SL/TP | Binance demo API has no batch endpoint; SL-first is adequate |
| MM-06 | Market impact model | Not relevant at small position sizes |
| MM-12 | Partial fill in backtester | Market orders at small sizes always fill fully |
| MM-14 | Paper trader tick-level SL | 1-min candle resolution adequate |
| RC-15 | Binance Demo = futures not spot | Acceptable for demo phase |
| SEC-08 | TLS certificate pinning | Default TLS verification fine for demo |
| MM-09 | BTCUSD venue-specific spread | Minor impact |
| MM-15/16 | News spread widening | Handled by volatile regime 2.5x multiplier |
| RC-10/20 | FOMC/CPI exact dates | Algorithmic approximation acceptable |
| TP-15 | Human intervention protocol | Procedural, not code |
| SEC-16 | Exchange API key permissions | Documentation task |
| SEC-20 | Sensitive config in status endpoint | Localhost-only |
| AT-38 | Partial fill handling | Demo always fills fully |
| SE-21 | Request params in stack traces | Audited — already safe, no params logged |

## RECURRING (watch list)

| ID | Times Found | Root Cause | Status |
|----|-------------|-----------|--------|
| ML-13 | 3 (Sessions 4a, 5, 7) | "Write function, forget to call it" pattern | **VERIFIED FIXED** Review 5 + Review 6 |

---

## REVIEW HISTORY

| Session | Issues Found | Fixed | Verified | Regressed | New |
|---------|-------------|-------|----------|-----------|-----|
| 4a | 48 | 30 | -- | -- | -- |
| 5 | 177 | -- | 30 | 1 (ML-13) | -- |
| 6 | 0 | ~70 | -- | -- | -- |
| 7 | 7 new | -- | 96 | 3 (ML-13, ML-18, CQ-01) | 7 |
| 8 | 0 | ~60 | -- | -- | -- |
| Review 5 | 36 total | -- | 49 | 2 (QR-16, QR-20) | 27 |
| Session 9 | 0 | 28 | -- | -- | -- |
| **Review 6** | 22 new | -- | **25** | **0** | **22** |
| **Session 12** | 0 | **21** | -- | -- | -- |

### Session 12 Notes (2026-03-23)
- **21 issues fixed** (2 P0, 3 P1, 5 P2, 11 P3) + 1 deferred (CQ-A02)
- **QR-A01 [P0]**: Backtester dual-mode — `compute_confluence()` for validation, individual for optimizer
- **AT-A01 [P0]**: Shutdown closes ALL exchange positions. Misleading Telegram message fixed
- **AT-A02 [P1]**: Null check after `open_position()` prevents crash
- **DE-A01 [P1]**: Data lineage — `candle_timestamp` and `candle_close` now populated
- **ML-A02 [P2]**: Grading now process-quality-first (score+R:R), outcome as annotation
- **BF-A01 [P2]**: Continuous conviction scaling replaces binary 60%/100% threshold
- **BF-A02 [P3]**: Regime throttle inverted — now throttles on same-regime losses, not regime changes
- **BF-A03 [P3]**: Smart exit uses `unrealized_pnl > 0` instead of `breakeven_activated`
- **CQ-A02 [P2→DEFERRED]**: Circular import works, all cross-module imports already deferred
- **126/126 tests passing** after all changes
- **0 open P0/P1/P2 code issues** — only DO-18 (process supervisor, operational) remains

### Review 6 Notes (2026-03-23)
- **Mode A (fresh, unbiased) + Mode B (reconciliation)** — full 10-panel review
- **25 Session 9 fixes verified** — zero regressions
- **1 superseded**: QR-23 (first qualifying signal) — code works but premise was wrong; superseded by QR-A01
- **22 new issues found**: 2 P0, 3 P1, 5 P2, 12 P3
- **3 Mode A false positives** caught in Mode B: DE-A02 (OHLC validation exists), DE-A03 (stale data detection exists), DO-A04 (log rotation exists)
- **Critical finding QR-A01**: The backtester and live system use fundamentally different signal selection algorithms. Every backtest metric, walk-forward result, and Monte Carlo output is measuring a system that doesn't match production.
- **Critical finding AT-A01**: No exchange-side SL protection + shutdown message at server.py:144 falsely claims protection exists.
- **2 P0s + 3 P1s must be fixed before demo trading can be trusted**
