# Notas Lave — Issue Tracker (Compact)

**Last Updated:** 2026-03-22 (Session 8 — 60+ fixes applied across 6 lanes)
**Total Reviews:** 4 sessions, 177 issues found, ~130 fixed/verified, ~13 deferred
**Next Review:** After paper trading produces 50+ trades

---

## JUST FIXED (Session 8 — needs verification next review)

### P0 Fixes
| ID | Title | Files Changed |
|----|-------|---------------|
| AT-F01 | Exchange-side SL/TP fill detection | autonomous_trader.py |
| ML-13 | get_trade_weight() wired into _compute_stats() (3rd fix!) | analyzer.py |
| ML-16 | Optimizer results wired into weekly review | autonomous_trader.py |
| TP-01 | Lucky win detection breaks self-confirming loop | trade_learner.py |
| OPS-03 | 125 print() → structured logging (0 remaining) | ALL 18 source files + log_config.py |

### P1 Fixes
| ID | Title | Files Changed |
|----|-------|---------------|
| ML-18 | resolve_pending_predictions now resolves from cache | accuracy.py |
| RC-06/RC-13 | Config aligned, risk_manager = sole enforcer | agent/config.py |
| RC-09 | Fill deviation check (slippage protection) | manager.py |
| MM-F01 | Backtester uses session-adjusted spread | backtester/engine.py |
| QR-17 | Bonferroni deflation for optimizer | optimizer.py |
| CQ-F02 | Optimizer monkey-patching eliminated | optimizer.py |
| CQ-12 | Claude API wrapped in asyncio.to_thread() | trade_learner.py |
| CQ-01 | get_session() context manager for safe DB access | database.py |
| TP-05 | Conviction scaling (60% size for score < 7) | autonomous_trader.py |
| TP-06 | Strategy rehabilitation in recommendations | recommendations.py |
| MM-07 | Dynamic funding rate (ATR-based) | backtester/engine.py |
| SEC-07 | Error logs sanitized (no more resp.text) | binance_testnet.py |
| SEC-03 | .env permission check at startup | config.py |
| SEC-04 | HMAC constant-time verify helper | binance_testnet.py |
| SEC-13 | Agent mode change requires API key | api/server.py |
| CQ-07 | Critical exception handlers now log properly | 5+ files |

### P2 Fixes
| ID | Title | Files Changed |
|----|-------|---------------|
| RC-F05 | Consistency rule warns on potential wins | manager.py |
| RC-F07 | Daily halt includes unrealized P&L | manager.py |
| RC-11 | Inactivity tracking (30-day rule) | manager.py |
| AT-F06 | _analyzed_trades set pruned | autonomous_trader.py |
| AT-33 | Paper trader SL applies slippage | paper_trader.py |
| QR-18 | SL/TP same-candle distance-from-open heuristic | backtester/engine.py |
| QR-23 | First qualifying signal (matches live) | backtester/engine.py |
| QR-15 | Block bootstrap in Monte Carlo | monte_carlo.py |
| QR-16 | Permutation p-value + 95% CI | monte_carlo.py |
| QR-21 | Symmetric forming swing detection | rsi_divergence.py |
| TP-10 | Optimizer uses live safety rails | optimizer.py |
| TP-13 | Per-regime performance warnings | recommendations.py |
| ML-21 | Cross-trade memory in Claude prompt | trade_learner.py |
| DE-14 | Cache LRU eviction (max 50) | market_data.py |
| DE-16 | Rate limit state persists across restarts | market_data.py |
| DE-22 | CCXT async lock | market_data.py |
| DE-23 | Data source health tracking | market_data.py |
| MM-10 | Real bid/ask from Binance ticker | market_data.py |
| SEC-14 | Telegram URL logging suppressed | telegram.py |
| SEC-18 | Rate limit helper for API | api/server.py |

### P3 Fixes
| ID | Title | Files Changed |
|----|-------|---------------|
| QR-20 | Sortino + Calmar ratios | backtester/engine.py |
| RC-18 | Unrealized carried at day rollover | manager.py |
| RC-19 | HFT detection (min trade duration) | manager.py |
| RC-21 | Weight guardrail constants | manager.py |
| CQ-15 | Agent config safety clamping | agent/config.py |
| ML-25 | Dynamic strategy-to-category mapping | recommendations.py |
| ML-26 | Statistical z-test for A/B testing | ab_testing.py |
| QR-25 | Statistical basis documented for thresholds | recommendations.py |
| CQ-23 | Anthropic client cached | trade_learner.py |
| DE-19 | Column projection in analyzer | analyzer.py |
| DE-F06 | Index on exit_price | database.py |
| SEC-15 | Key age check | config.py |
| SEC-19 | Missing deps added to pyproject.toml | pyproject.toml |
| SEC-09 | Dependencies pinned with upper bounds | pyproject.toml |
| CQ-16 | .env path absolute (from __file__) | config.py |

---

## DEFERRED (not needed until deployment/scaling)

| ID | Title | Why Deferred |
|----|-------|-------------|
| OPS-01 | Docker containerization | Running locally, not on VPS yet |
| OPS-02 | CI/CD pipeline | Tests run manually, no team collaboration |
| CQ-03 | Dependency injection | Large architectural refactor, system works without it |
| CQ-10 | Alembic migrations | create_all() works for current schema stability |
| CQ-14 | Integration tests | Unit tests cover core logic; integration tests need mock design |
| CQ-17 | Backtester.run() refactor (300 lines) | Works correctly, cosmetic improvement |
| CQ-18 | API server lazy imports | Works fine, minor startup optimization |
| OPS-07 | Secondary alert channel | Telegram works, add email/webhook later |
| OPS-11 | Database backup strategy | Add cron job when running 24/7 on VPS |
| OPS-17 | Zero-downtime deployment | Needs Docker first |
| ML-17 | A/B testing integration into trading loop | Needs design work, not just code |
| TP-14 | Market quality check ("should I trade today?") | Nice-to-have after 500+ trades |
| OPS-08 | Resource monitoring | Not needed at current scale |

## WONT_FIX (accepted risk or not applicable)

| ID | Title | Rationale |
|----|-------|-----------|
| MM-05 | Non-atomic SL/TP | Binance demo API has no batch endpoint; SL-first is adequate |
| MM-06 | Market impact model | Not relevant at small position sizes ($5-50 trades) |
| MM-12 | Partial fill in backtester | Market orders at small sizes always fill fully |
| MM-14 | Paper trader tick-level SL | 1-min candle resolution adequate for paper trading |
| RC-15 | Binance Demo = futures not spot | Acceptable for demo phase, documented |
| SEC-08 | TLS certificate pinning | Default TLS verification is fine for demo |
| MM-09 | BTCUSD venue-specific spread | Would need InstrumentSpec refactor, minor impact |
| MM-15/16 | News spread widening + Silver disabling | Handled by volatile regime 2.5x multiplier |
| RC-10/20 | FOMC/CPI exact dates | Algorithmic approximation is acceptable |
| TP-15 | Human intervention protocol | Procedural, not code |
| SEC-16 | Exchange API key permissions | Documentation task, not code |
| SEC-20 | Sensitive config in status endpoint | Minor P3, localhost-only access |
| AT-38 | Partial fill handling | Binance demo always fills fully at small sizes |

## RECURRING (watch list — issues that keep coming back)

| ID | Times Found | Root Cause | Status |
|----|-------------|-----------|--------|
| ML-13 | 3 (Sessions 4a, 5, 7) | "Write function, forget to call it" pattern | Fixed Session 8 — VERIFY next review |

---

## REVIEW HISTORY

| Session | Issues Found | Fixed | Verified | Regressed |
|---------|-------------|-------|----------|-----------|
| 4a | 48 | 30 | — | — |
| 5 | 177 | — | 30 | 1 (ML-13) |
| 6 | 0 | ~70 | — | — |
| 7 | 7 new | — | 96 | 3 (ML-13, ML-18, CQ-01) |
| 8 | 0 | ~60 | — | — |
