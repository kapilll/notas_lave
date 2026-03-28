# Notas Lave - AI Trading System

## System Documentation

**Read `docs/system/` for detailed subsystem docs.** Each file describes current code state, rules, and known issues.

| Doc | When to read |
|-----|-------------|
| [docs/system/ARCHITECTURE.md](docs/system/ARCHITECTURE.md) | Starting any session — system map, data flow, patterns |
| [docs/system/CI-CD.md](docs/system/CI-CD.md) | Changing workflows, deploying, releasing |
| [docs/system/ENGINE.md](docs/system/ENGINE.md) | Working on Python engine code |
| [docs/system/INFRASTRUCTURE.md](docs/system/INFRASTRUCTURE.md) | VM, systemd, networking, env vars |
| [docs/system/DATABASE.md](docs/system/DATABASE.md) | Storage, schemas, journal systems |
| [docs/system/EXECUTION.md](docs/system/EXECUTION.md) | Broker integration, order flow |
| [docs/system/DATA-PIPELINE.md](docs/system/DATA-PIPELINE.md) | Market data, caching, instruments |
| [docs/system/RISK.md](docs/system/RISK.md) | Risk rules, position sizing, compliance |
| [docs/system/LEARNING.md](docs/system/LEARNING.md) | Analyzer, recommendations, optimizer |
| [docs/system/TESTING.md](docs/system/TESTING.md) | Test structure, CI gates, fixtures |
| [docs/system/DASHBOARD.md](docs/system/DASHBOARD.md) | Next.js frontend |

**When you fix something, add a rule to the relevant doc so future sessions know.**

## Project Overview

AI-powered autonomous trading system for crypto (BTC, ETH, SOL + 15 more). Two modes:
- **Personal mode:** Trade on Delta Exchange with leverage (primary)
- **Prop mode:** Pass FundingPips challenges with strict prop firm rules

## Current State (2026-03-28)

- **81 files, ~15K lines**, 247 tests, 36% coverage
- **Active broker:** Delta Exchange testnet
- **12 strategies** across 4 categories (scalping, ICT, fibonacci, breakout)
- **18 instruments** (crypto)
- Engine live on GCP VM, dashboard at `http://34.79.66.229:3000`

## FundingPips Rules (MUST ENFORCE)

- Max daily drawdown: 5%
- Max total drawdown: 10% (static from original balance)
- Consistency rule: No single day > 45% of total profits (funded accounts)
- News blackout: No trades 5 min before/after high-impact news (funded)
- No hedging, no HFT, no arbitrage
- Inactivity limit: 30 days

## Git & Release Workflow

- **Branch:** Feature branches from `main` (e.g., `feat/remove-binance`)
- **PR:** Open PR → `pr-check.yml` runs tests → merge to main
- **Release:** Create GitHub Release with semver tag → `deploy.yml` deploys to VM
- **No Docker** — systemd services on GCP VM
- **Rollback:** Automatic on failed health check
- **Notifications:** Telegram alerts on deploy
- Git remote uses `github-kapilll` SSH alias

## Development Rules

- All math is deterministic code — Claude handles analysis/explanation only
- Every trade must pass Risk Manager before execution
- **PR-based workflow** — feature branches → PRs → merge to main → release → deploy
- Log EVERYTHING for learning system
- FundingPips trades SPOT/CFD instruments, NOT futures
- All imports: `from notas_lave.X import Y`
- No hardcoded values — use env vars or derive from runtime state

## Key API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Engine health check |
| `GET /api/system/health` | Component status |
| `GET /api/broker/status` | Balance, positions |
| `GET /api/risk/status` | P&L, drawdown |
| `GET /api/lab/summary` | Lab performance |
| `GET /api/learning/state` | Complete system memory |
| `GET /api/learning/recommendations` | Actionable suggestions |
| `GET /api/prices` | Current prices |
| `GET /api/scan/all` | Confluence scan |

## Expert Review System

- **Review prompt:** `docs/reviews/REVIEW-PROMPT.md`
- **Mode A:** Fresh review (unbiased, no priming from old issues)
- **Mode B:** Progress check (reconcile with `docs/reviews/ISSUES.md`)
- **Frequency:** Every 3-5 sessions or after major changes
