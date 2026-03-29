# Changelog

All notable changes to Notas Lave are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.7.14] — 2026-03-29

### Changed
- **Documentation update to v1.7.13** — synchronized all 11 system docs (`docs/system/*.md`) to
  reflect current architecture: 6 composite strategies (Arena v3), 536 tests at 50% coverage,
  corrected GCP zone and IP, arena_score formula, Binance clarification (broker removed, data
  source remains), ML-02 bridge status.
- **SQLite WAL mode enabled** — EventStore and Database now use Write-Ahead Logging for concurrent
  read/write performance. Enables background maintenance without blocking live queries.

### Removed
- **Unused imports cleanup** — removed `detect_regime` from `lab.py` (line 287), was never called.
- **Stale research docs** — deleted `TEST-REVAMP-PLAN.md`, `TESTING-STANDARDS.md`,
  `TOKEN-OPTIMIZATION.md`, `TRADING-SYSTEM-RESEARCH.md` (all superseded by implementation or
  `docs/system/TESTING.md`). Preserved `ELITE-SCALPER-STRATEGIES.md` for reference.

## [1.7.13] — 2026-03-29

### Fixed
- **Dashboard build failure** — `t.timeframe` and `p.timeframe` are `unknown` type from API
  response. TypeScript rejects `{unknown && JSX}` as ReactNode. Cast to `String()` before
  conditional rendering.

## [1.7.12] — 2026-03-29

### Fixed
- **Skip duplicate symbol trades** — if a symbol already has an open position, skip any new
  proposals for that symbol. Previously, a second strategy could try to open another trade on
  the same coin, getting blocked at broker level. Now logged as "already_open" and skipped early.
- **Leaderboard always showed "unknown" strategy** — `record_open` in EventStore didn't store
  `proposing_strategy` or `timeframe`. When trades closed, `_reconcile` couldn't find which
  strategy placed the trade, so everything went to "unknown". Now context is stored in the
  opened event and the leaderboard rebuilds from journal on startup.
- **Removed misplaced "No Signal" cards** — dark greyed-out strategy cards were showing in the
  Live Proposals section instead of below in the dashboard. Removed from proposals grid.

### Added
- **Enriched trade history** — each trade now shows entry/exit prices, SL/TP levels, position
  size, strategy score, strategy name, timeframe, grade, and timestamps. Max height increased
  from 320px to 480px. API returns `opened_at`, `closed_at`, and a `summary` with totals.
- **Single source of truth for trade data** — EventStore `record_open` now stores full context
  (proposing_strategy, timeframe, strategy_score, competing_proposals). `get_closed_trades()`
  returns consistent field names (`proposing_strategy`, `outcome_grade`, `lessons_learned`)
  with timestamps. No more scattered data across EventStore/JSON/SQLAlchemy.
- **Leaderboard startup sync** — on engine start, rebuilds leaderboard stats from journal
  history. If "unknown" entries exist, re-attributes them using strategy data from signal events.
- **Composite strategy info** — added display names and descriptions for all 6 Arena v3 strategies
  plus "Unknown" for legacy trades. Shows properly in leaderboard and tooltips.
- **Migration script** — `scripts/migrate_unknown_strategy.py` removes the "unknown" strategy
  entry from leaderboard JSON (9 legacy trades before proposing_strategy tracking).

### Changed
- **Risk per trade now controlled by pace preset** — aggressive (5%), balanced (3%), conservative (2%).
  Previously hardcoded at 5% globally. Now when you select "aggressive" you accept larger positions
  with fewer concurrent trades (1-2 on small balance). "Balanced" gives medium positions (3-4 concurrent),
  "conservative" gives smaller positions (5-6 concurrent).

## [1.7.11] — 2026-03-29

### Fixed
- **Pydantic Signal type crash** — `signals_snapshot=[signal]` crashed every tick because
  strategies return `data.models.Signal` but `TradeSetup` expects `core.models.Signal`.
  This killed the entire execution loop silently — proposals showed READY but no trade
  ever executed.
- **No leverage on lab instruments** — all 6 instruments had `max_leverage=1.0` (default),
  causing position sizing to skip margin check. Result: $1,300 positions on $100 account,
  Delta rejected with `insufficient_margin`. Set `max_leverage=10.0` for all lab instruments.
- **Subtler refresh blur** — changed from `blur-sm opacity-50` to `blur-[1px] opacity-80`.

### Added
- **Inactive strategies visible** — strategies with no current signal now show as greyed-out
  cards ("No signal") instead of disappearing. All 6 strategies always visible.

### Removed
- **5 no-data instruments** — PAXGUSD, ONDOUSD, NVDAXUSD, 1000SHIBUSD, COAIUSD removed from
  LAB_INSTRUMENTS (no CCXT/Binance market data available).

## [1.7.10] — 2026-03-29

### Fixed
- **Delta contract size conversion** — Delta API expects contract count (e.g., 10 contracts
  of 0.001 BTC = 0.01 BTC), but we sent raw asset quantity (0.01). Orders for BTC, ETH, DOGE
  were rejected silently. Now converts via `contract_value` fetched from `/v2/products`.

### Added
- **`GET /api/lab/debug/execution`** — diagnostic endpoint showing broker connection status,
  contract values, position sizing checks, and last execution attempt result. No more guessing
  from logs.
- **Execution logging** — lab engine now logs every execution attempt with result (placed,
  broker_rejected, pos_size=0, risk_reject) visible in `_last_exec_log`.

## [1.7.9] — 2026-03-29

### Fixed
- **BLOCKED proposals — missing Delta symbol mappings** for XRPUSD, DOGEUSD, ADAUSD.
  These exist on Delta testnet but had no `exchange_symbols["delta"]` entry in instruments.py.

### Changed
- **LAB_INSTRUMENTS trimmed to Delta testnet reality** — from 18 instruments down to the
  11 that actually exist as perpetual futures on Delta testnet. Eliminates wasted compute
  scanning instruments that can never execute.

### Added
- **5 new Delta testnet instruments:** PAXGUSD (tokenized gold), ONDOUSD (Ondo Finance),
  NVDAXUSD (NVIDIA stock CFD), 1000SHIBUSD (Shiba Inu), COAIUSD (CoAI).

## [1.7.8] — 2026-03-29

### Added
- **Engine status strip in Lab tab** — pill row below the 4 stat cards showing metrics
  previously only visible in code: ENGINE RUNNING/STOPPED, broker connection + type,
  CAN TRADE/HALTED, open positions (N/max), drawdown %, scanning timeframes, min R:R,
  markets tracked, total trades in DB.
- **Proposal card blur on refresh** — Arena proposal cards briefly blur + dim when the
  10-second poll returns fresh data, then fade back to sharp — makes data changes visible.

## [1.7.7] — 2026-03-29

### Fixed
- **READY proposals not executing — two root causes:**
  1. **Risk Manager blocking all arena trades (prop mode)** — `max_risk_per_trade_pct` was 1%
     but `RISK_PER_TRADE` in lab.py is 5%. Every trade was rejected with "POSITION TOO LARGE:
     Risk $5.00 exceeds 1.0% limit ($1.00)". Raised to 5% to match lab.py's actual risk target.
  2. **Most instruments showed READY but silently failed at broker** — dry-run only checked
     position sizing, not broker availability. Only BTCUSD, ETHUSD, SOLUSD have Delta exchange
     symbol mappings — SUIUSD, NEARUSD, XRPUSD etc. always failed at `place_order()` with
     "Unknown Delta product". Now checks broker mapping first; unmapped instruments show
     BLOCKED instead of READY.

## [1.7.6] — 2026-03-29

### Fixed
- **Leverage not applied in position sizing** — `calculate_position_size()` was called with
  default `leverage=1.0` in both the dry-run block (proposal visibility) and the execution loop.
  For leveraged instruments (BTCUSDT, ETHUSDT — `max_leverage=15.0`), this caused the margin
  constraint to be calculated as if no leverage was in use, producing wrong `will_execute`/
  `block_reason` values and potentially wrong lot sizes at execution. Now passes
  `leverage=spec.max_leverage` in both locations. FundingPips instruments have
  `max_leverage=1.0` so are unaffected.

## [1.7.5] — 2026-03-29

### Fixed
- **Stale proposals no longer shown in arena** — `get_arena_status()` now filters out proposals
  past their `expires_at` timestamp. Previously a crash or long pause left old proposals visible
  indefinitely; now they drop off after 2× scan_interval (90–120s).

### Added
- **`will_execute` + `block_reason`** — each proposal now includes a dry-run position-size check.
  If the account is too small for the min lot on that instrument, `will_execute=false` and
  `block_reason` explains exactly how much risk budget is needed vs available. Dashboard shows
  a red "BLOCKED" or green "READY" banner on every card.
- **`notional_usd` + `margin_usd`** — proposals now carry the actual capital being traded
  (position_size × entry_price) and the margin required (notional × margin_pct). Dashboard shows
  "Capital trading $X" row so you can see what's actually being put on the line.

## [1.7.4] — 2026-03-29

### Added
- **Dollar amounts in proposal cards** — each strategy card now shows `risk_usd` (how much $ you
  risk) and `profit_usd` (target profit in $), computed from `balance × RISK_PER_TRADE × R:R`.
  Displayed prominently alongside existing % values.
- **Proposal ranking** — all proposals are now sorted by `arena_score` descending before caching.
  Each proposal carries a `rank` field (1 = highest score). Rank #1 gets a gold badge and
  "NEXT TO EXECUTE" banner in the dashboard.
- **Multiple trades on same coin** — removed the per-symbol open-position gate that blocked
  scanning a symbol already in broker positions. Strategies can now independently propose (and
  execute) trades on the same coin simultaneously, up to `max_concurrent` total positions.
- **Balance fetched once per tick** — a single `get_balance()` call at proposal-cache time is
  reused across all execution iterations in the same tick (was N separate calls).

## [1.7.3] — 2026-03-29

### Fixed
- **Arena: no trades being placed** — `RISK_PER_TRADE` raised from 1% → 5%. On a $100 balance,
  1% ($1 budget) was always below the minimum lot risk for BTC/ETH, so position sizer returned 0.
- **Position sizing: floor rounding** — changed `round()` → `math.floor()` so lot size never
  rounds up past the risk budget (which caused the sizer to reject the position).
- **Personal mode risk limits too tight** — raised config defaults: `personal_risk_per_trade_pct`
  2% → 10%, `personal_max_daily_dd_pct` 6% → 20%, `personal_max_total_dd_pct` 20% → 50%.
  Demo account limits were blocking valid trades even after sizer calculated a non-zero lot size.

### Added
- **Proposal expiry** — proposals now include `generated_at` (ISO timestamp) and `expires_at`
  (unix timestamp = now + 2×scan_interval). The `/api/lab/proposals` endpoint adds `is_stale: bool`
  so the dashboard can visually flag stale setups rather than showing stale data as live.

## [1.7.2] — 2026-03-29

### Changed
- **Test suite recalibrated** for v1.7 arena architecture (536 tests, 50.4% coverage)
- Deleted `test_strategy_signals.py` — tested 12 deleted single-indicator strategies (dead code)
- Fixed `test_schemas.py` LabRiskState default: $5000 (Delta testnet balance, not $100K)
- Fixed `test_strategy_bridge.py` for 6 composite strategies (was checking for `ema_crossover`)

### Added
- **`test_leaderboard.py`** (43 tests) — full coverage of arena trust scoring, suspension,
  win/loss streaks, persistence, `can_trade()` threshold tiers
- **`test_indicators.py`** (25 tests) — EMA, RSI (Wilder), Stochastic, VWAP shared helpers
- **`test_risk_manager.py`** complete rewrite — SL/TP validation, hedging, fill deviation,
  inactivity (RC-11), HFT detection (RC-19), all personal recommendation branches
- Coverage gate raised: 34% → 50% in both `pyproject.toml` and CI
- Added property-based and invariant test steps to `pr-check.yml`

## [1.7.0] — 2026-03-29

### Added
- **Strategy Arena** — Lab engine v3. Strategies compete independently instead of
  confluence averaging. Each strategy proposes trades, best score wins. Trust scores
  evolve: winners earn more opportunities, losers get suspended.
- **6 composite strategies** replacing 12 single-indicator strategies:
  - Trend Momentum System (EMA stack + RSI + MACD + Stochastic + volume)
  - Mean Reversion System (Bollinger + RSI + Z-score + volume profile)
  - Level Confluence System (Fibonacci + VWAP + Camarilla + volume profile)
  - Breakout System (S/R + compression + volume + session + ATR + retest)
  - Williams System (Larry Williams: %R + Smash Day + compression + MACD)
  - Order Flow System (order book + real delta + funding + absorption + CVD)
- **Order flow data pipeline (Phase 0)** — 5 new methods on MarketDataProvider:
  `get_orderbook_imbalance()`, `get_real_delta()`, `get_funding_rate()`,
  `get_open_interest()`, `get_order_flow_snapshot()`. All FREE via CCXT.
- **OrderFlowSnapshot** model for real-time market microstructure data
- **StrategyLeaderboard** — per-strategy trust scores, dynamic thresholds, win/loss tracking
- **Arena API endpoints** — `/api/lab/arena`, `/api/lab/arena/leaderboard`,
  `/api/lab/arena/{strategy_name}`, `/api/lab/proposals`
- **Arena dashboard** — Strategies tab shows leaderboard with trust bars,
  live proposals, expandable per-strategy stats
- **TradeLog schema** — new columns: `proposing_strategy`, `strategy_score`,
  `strategy_factors`, `competing_proposals`
- **Research doc** — `docs/research/ELITE-SCALPER-STRATEGIES.md` with accuracy
  ratings, honest assessments, and data source expansion plan

### Changed
- Lab engine no longer uses `compute_confluence()` — each strategy is independent
- Strategies reduced from 12 singles to 6 multi-factor composites
- Each composite requires 3+ factor alignment before generating a signal

### Removed
- Single-indicator strategies (EMA Crossover, RSI Divergence, Bollinger Bands,
  Stochastic, Camarilla, EMA Gold, VWAP, Fibonacci, London Breakout, NY Open Range,
  Break & Retest, Momentum Breakout) — replaced by composite systems

## [1.6.0] — 2026-03-29

### Added
- **Property-based tests** (LOCKED tier): Hypothesis tests for position sizing (7 tests),
  P&L invariants (5 tests), and risk manager properties (4 tests). These are mathematical
  proofs that critical safety properties hold across all possible inputs.
- **Confluence scorer tests** (14 tests): regime detection, compute_confluence,
  REGIME_WEIGHTS validation, HTF bias, symbol support
- **Risk manager expansion** (37 tests total, up from 10): fill deviation (RC-09),
  inactivity check (RC-11), HFT detection (RC-19), hedging (RC-05), all SL/TP
  validation paths, unrealized P&L, acceptance paths, state invariants
- **Schema tests** (13 tests): safe_load_json, safe_save_json, validate_json_file
  round-trip and error handling
- **Instrument tests expansion**: spread sessions (MM-02), breakeven price,
  exchange symbol mapping, pip conversions
- **API tests expansion**: broker status, 404 handling, journal/trades, costs/summary
- **Hypothesis config** added to pyproject.toml: max_examples=200, deadline=2000
- **CI**: separate property-based and invariant test steps in pr-check.yml

### Changed
- Coverage gate raised from 34% to 42% (250 → 370 tests, 34% → 43% coverage)
- Moved `tests/test_trade_grader.py` → `tests/unit/test_trade_grader.py` (correct tier)

### Fixed
- `test_lab_engine.py`: tightened P&L assertion from `abs=1.0` to `abs=0.01`
  (was allowing $1 tolerance on a $75 financial value)
- `test_observability.py`: added real assertion on structured log output
  (was asserting nothing — just "didn't crash")

## [1.5.0] — 2026-03-28

### Fixed
- **Volume check bug**: was comparing the CURRENT forming candle (always partial
  volume ~6%) against completed candle averages — every signal was rejected as
  "Volume too low". Now compares last COMPLETED candle instead.
- Volume checks are always enabled — removed the `set_volume_check(False)` hack
  that disabled volume entirely in Lab mode

### Changed
- Coverage gate temporarily lowered to 34% (was 35%) due to dead code removal.
  Will be raised back in a follow-up session with more tests.

### TODO (next session)
- Research proper volume usage in scalping: delta, order flow, accumulation/distribution
- Implement volume as a signal quality factor, not just a threshold gate

## [1.4.0] — 2026-03-28

### Added
- PR check: fails if `pyproject.toml` version already has a release tag (prevents forgotten version bumps)
- Deploy: post-deploy version check warns if running version doesn't match release tag

### Changed
- Deploy no longer runs tests (removed in v1.3.1, now in deploy.yml)

### Fixed
- Version mismatch: v1.3.1 was released but pyproject.toml still said 1.3.0

## [1.3.0] — 2026-03-28

### Added
- LikeC4 architecture diagrams — 7 views from single model (`architecture/*.c4`)
- Dashboard shows engine version in header (e.g. `v1.2.0`)
- Dashboard architecture link button (🏗️ ARCH)
- `/health` returns version from `pyproject.toml` dynamically (no hardcoded strings)

### Changed
- VM moved from Europe (`europe-west1-b`) to Mumbai (`asia-south1-b`) — lower latency
- VM IP changed from `34.79.66.229` to `34.100.222.148`
- Removed Mermaid diagrams from ARCHITECTURE.md (LikeC4 is source of truth)

### Infrastructure
- GitHub secrets updated for Mumbai VM (VPS_HOST, VPS_SSH_KEY)
- Old Europe VM deleted
- `nlvmssh` alias updated to Mumbai

## [1.1.0] — 2026-03-28

### Fixed
- Lab trades now visible to Learning Engine — writes to both EventStore AND SQLAlchemy (ML-02)
- Merged duplicate instrument registries — data/instruments.py is single source of truth (QR-03)
- Double-close race condition prevented via closing guard set (AT-02)
- Win/loss stats bug in close_trade — instrument_stats were in wrong branches
- Config: removed all INR conversion, USD-only, no more currency confusion
- Config: broker default changed to delta_testnet, api_host to 0.0.0.0
- Risk manager singleton removed — create instances with actual broker balance (CQ-04)
- /api/risk/status: positions from broker, balance from Delta Exchange API
- Health endpoint version matches release

### Changed
- core/instruments.py is now a thin re-export from data/instruments.py
- Delta broker imports from data.instruments (not core.instruments)

## [1.0.0] — 2026-03-28

### Added
- System documentation (`docs/system/`) for all subsystems with Mermaid diagrams
- CHANGELOG.md for tracking releases
- API key authentication on all endpoints (`API_KEY` env var, SE-01)
- Lab Engine: loss streak throttle — halves risk after 3 consecutive losses (BF-01)
- Lab Engine: hourly DB maintenance (WAL checkpoint + backup, DO-01)
- Lab Engine: consecutive error backoff — 5min pause after 10 failures + Telegram alert (DO-03)
- Lab Engine: graceful shutdown logs open positions (AT-04)

### Changed
- **BREAKING:** Deploy now triggers on GitHub Release (not push to main)
- Lab Engine uses Risk Manager for trade validation (QR-01/RC-01 — was completely bypassed)
- Lab Engine uses InstrumentSpec.calculate_position_size() instead of naive formula (QR-01)
- CORS restricted to `CORS_ORIGINS` env var (was `allow_origins=["*"]`, SE-01)
- CLAUDE.md rewritten as concise index pointing to system docs
- .gitignore updated to exclude runtime files (logs, WAL, coverage, data/)
- BTC spread_typical corrected from $15 to $2 (MM-01)
- CCXT lock now covers fetch_ticker in get_bid_ask (DE-02)
- Telegram deploy notifications include release version
- VM deploy checks out release tag (not `git pull main`)

### Removed
- Binance broker (`execution/binance.py`) and its tests — Delta Exchange is the only broker
- Binance config fields (`BINANCE_TESTNET_KEY`, `BINANCE_TESTNET_SECRET`)
- Binance references from instrument registries and integration test conftest

### Fixed
- CoinDCX API key changed from plain `str` to `SecretStr` (SE-02)
- Lab Engine `stop()` is now async (was sync, couldn't read positions on shutdown)
- Dashboard balance now shows actual Delta Exchange balance (was showing wrong value due to INR conversion)
- `/api/risk/status` positions count from broker (was from journal)
- Config `api_host` defaults to `0.0.0.0` (was `127.0.0.1`, breaking deploys)
- Config `broker` defaults to `delta_testnet` (was `paper`)
- Risk manager no longer uses stale config-based balance
- Health endpoint reports correct version (1.0.0)

## [0.1.0] — 2026-03-28

Initial versioned release. Tags the working state before review fixes.

### Features
- Lab Engine with 3 pace presets (conservative/balanced/aggressive)
- 12 trading strategies across 4 categories (scalping, ICT, fibonacci, breakout)
- Confluence scorer with regime-weighted categories and HTF trend filter
- Risk Manager with prop (FundingPips) and personal (CoinDCX) modes
- Delta Exchange testnet broker with server-side bracket orders
- Paper broker for testing
- Binance Demo broker (deprecated)
- Multi-source market data (CCXT, TwelveData, yfinance fallback)
- 18 crypto instruments with full specs (pip, spread, position sizing)
- Append-only EventStore journal
- SQLAlchemy database (TradeLog, SignalLog, PredictionLog, etc.)
- Learning engine: analyzer, recommendations, optimizer, accuracy, A/B testing
- Walk-forward backtester with 10 risk levers and Monte Carlo testing
- Economic calendar with news blackout detection
- Telegram notifications on trade events
- Next.js 15 dashboard at :3000
- CI/CD: PR checks + deploy to GCP VM via SSH
- Systemd services (no Docker)
- 247 tests, 36% coverage (CI gate at 35%)

### Known Issues
- Lab Engine does NOT use Risk Manager (QR-01/RC-01)
- Two disconnected journal systems (ML-02/CQ-01)
- CORS allow_origins=["*"] on public IP (SE-01)
- Binance broker still in codebase (deprecated)
- Client-side SL/TP monitoring with polling gaps (AT-01)
