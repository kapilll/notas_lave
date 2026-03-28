# Changelog

All notable changes to Notas Lave are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
