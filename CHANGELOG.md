# Changelog

All notable changes to Notas Lave are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- System documentation (`docs/system/`) for all subsystems with Mermaid diagrams

### Changed
- CLAUDE.md rewritten as concise index pointing to system docs
- .gitignore updated to exclude runtime files (logs, WAL, coverage, data/)

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
