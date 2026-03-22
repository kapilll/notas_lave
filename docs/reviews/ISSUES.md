# Notas Lave — Issue Tracker (Compact)

**Last Updated:** 2026-03-22 (Session 9 — Review 5 fixes applied, 6 parallel lanes)
**Total Reviews:** 5 sessions, 204 issues found, ~204 fixed/verified/deferred, 0 open P0/P1
**Next Review:** After 50+ lab trades during weekday active hours

---

## OPEN — Remaining items

### P0 (Fix immediately)
*None — all P0s fixed in Session 9*

### P1 (Fix before live)
| ID | Title | File(s) | Panel | Found |
|----|-------|---------|-------|-------|
| DO-18 | No process supervisor — engine dies silently, no auto-restart | (systemd/Docker config) | DevOps | Review 5 |

> DO-18 is operational (not a code fix). Requires systemd unit file or Docker Compose. Deferred until VPS deployment.

### P2 (Fix before scaling)
*None — all P2s fixed in Session 9*

### P3 (Improvement)
| ID | Title | File(s) | Panel | Found |
|----|-------|---------|-------|-------|
| CQ-26 | No static type checking (mypy/pyright) in toolchain | (no config) | CQ | Review 5 |

---

## JUST FIXED (Session 9 — needs verification next review)

### P0 Fixes
| ID | Title | Root Cause | Files Changed |
|----|-------|-----------|---------------|
| AT-39 | Lab PaperTrader decoupled from production risk_manager | Singleton contamination | paper_trader.py (track_risk flag), lab_trader.py, server.py |
| CQ-24 | use_db() race eliminated with contextvars.ContextVar | Shared global state | journal/database.py |

### Regression Fixes
| ID | Title | Root Cause | Files Changed |
|----|-------|-----------|---------------|
| QR-16 | Monte Carlo p-value: proper sign-randomization test | Invalid shuffle preserves mean | backtester/monte_carlo.py |
| QR-20 | Sortino ratio: N-1 sample variance (matches Sharpe) | Population vs sample variance | backtester/engine.py |

### P1 Fixes
| ID | Title | Root Cause | Files Changed |
|----|-------|-----------|---------------|
| QR-26 | Backtester entry at next candle open (no look-ahead) | Look-ahead bias | backtester/engine.py |
| ML-27 | Weight adjustment performance tracking (pre/post comparison) | No feedback loop | recommendations.py |
| AT-40 | Graceful shutdown with SIGTERM handler | No lifecycle management | run.py |
| AT-41 | Exchange fill detection queries actual fill price (3-tier fallback) | Approximate exit price | autonomous_trader.py, binance_testnet.py |
| SE-21 | Request params already sanitized (audited, no change needed) | N/A — already safe | binance_testnet.py |
| DE-24 | yfinance refuses metals data (returns empty, not futures) | Wrong data source | market_data.py |
| BF-01 | Production recommendations filter lab-only trades (min_score=50) | Selection bias | recommendations.py, analyzer.py |

### P2 Fixes
| ID | Title | Root Cause | Files Changed |
|----|-------|-----------|---------------|
| QR-27 | Walk-forward OOS trades filtered to test window only | Fold overlap | backtester/engine.py |
| ML-29 | Regime-aware trade weighting (1.5x boost for regime match) | Recency conflates quality | analyzer.py |
| SE-22 | API secrets use pydantic SecretStr | Plain string secrets | config.py, binance_testnet.py, coindcx.py, mt5_broker.py |
| SE-23 | SQLite databases auto-chmod 600 | World-readable DBs | config.py |
| SE-24 | RateLimitMiddleware wired into FastAPI (60 req/min mutations) | Rate limiting dead code | api/server.py |
| DO-19 | Log rotation verified (RotatingFileHandler, 10MB x 5) | Unbounded log growth | log_config.py |
| DO-20 | GET /health endpoint with uptime + component status | No health check | api/server.py |
| DE-25 | OHLC consistency validation on all data sources | No input validation | market_data.py |
| DE-26 | Cache key normalization (BTCUSDT → BTCUSD for caching) | Double API calls | market_data.py |
| RC-22 | Consistency rule requires 1% of balance in profits first | Edge case at zero P&L | manager.py |
| RC-23 | open_positions synced from DB after position reload | Count drift after restart | paper_trader.py |
| BF-02 | Lab heartbeat reduced from 2h to 6h | Notification fatigue | lab_trader.py |
| BF-03 | Leaderboard shows trade count + "(low n)" for small samples | Anchoring bias | lab_trader.py |

### P3 Fixes
| ID | Title | Root Cause | Files Changed |
|----|-------|-----------|---------------|
| ML-30 | Graduated thresholds: blacklist=30 trades, weights=50 trades | Too-high minimum | recommendations.py |
| RC-24 | Hedging warning in personal mode (log, don't block) | Prop-only check | manager.py |
| CQ-25 | Dead strategy files deleted (order_blocks, session_killzone) | Dead code | strategies/ |
| DO-21 | SIGTERM handler saves risk state + clean exit | Unclean shutdown | run.py |
| ML-28 | DEFERRED — grade calibration infrastructure exists, analysis not yet needed | Future work | (no change) |

---

## VERIFIED FIXES (confirmed working — 49 items from Session 8 + ML-13 recurring)

### P0 Verified
| ID | Title | Status |
|----|-------|--------|
| AT-F01 | Exchange-side SL/TP fill detection | VERIFIED Review 5 |
| ML-13 | get_trade_weight() wired into _compute_stats() | VERIFIED Review 5 (first time after 3 regressions!) |
| ML-16 | Optimizer results wired into weekly review | VERIFIED Review 5 |
| TP-01 | Lucky win detection breaks self-confirming loop | VERIFIED Review 5 |
| OPS-03 | 125 print() converted to structured logging | VERIFIED Review 5 |

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

### P2 Verified
| ID | Title | Status |
|----|-------|--------|
| RC-F05 | Consistency rule warns on potential wins | VERIFIED Review 5 |
| RC-F07 | Daily halt includes unrealized P&L | VERIFIED Review 5 |
| RC-11 | Inactivity tracking (30-day rule) | VERIFIED Review 5 |
| AT-F06 | _analyzed_trades set pruned | VERIFIED Review 5 |
| AT-33 | Paper trader SL applies slippage | VERIFIED Review 5 |
| QR-18 | SL/TP same-candle distance-from-open heuristic | VERIFIED Review 5 |
| QR-23 | First qualifying signal (matches live) | VERIFIED Review 5 |
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
| SEC-18 | Rate limit middleware wired + verified | VERIFIED Session 9 (SE-24 confirmed it was dead code, now fixed) |

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
| ML-13 | 3 (Sessions 4a, 5, 7) | "Write function, forget to call it" pattern | **VERIFIED FIXED** Review 5 |

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
| **Session 9** | 0 | **28** | -- | -- | -- |

### Session 9 Notes
- **28 issues fixed** across 6 parallel lanes in one session
- **Root cause approach**: 27 issues collapsed into 7 root causes, fixed with targeted changes
- **2 P0s resolved**: AT-39 (PaperTrader track_risk flag) + CQ-24 (contextvars for DB)
- **2 regressions resolved**: QR-16 (sign-randomization) + QR-20 (Sortino N-1)
- **1 issue audited and closed**: SE-21 (params already safe — no change needed)
- **1 issue deferred**: ML-28 (grade calibration — infrastructure exists)
- **47/47 tests passing** after all changes
- **0 open P0/P1 code issues** — system ready for demo trading
