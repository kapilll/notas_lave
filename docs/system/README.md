# System Documentation

Living reference for each subsystem. Updated with every release.

> Last synced: v2.0.23 (2026-03-31)

## For Claude Sessions

1. **Read CLAUDE.md first** — concise project overview
2. **Read the relevant system doc** for the subsystem you're working on
3. **When you fix something, add a rule** to the relevant doc
4. **Use `/copilot` skill** (v2.0.21+) for live engine data, proposal analysis, debugging — no API cost, uses Claude Code session

## Docs

| File | When to read |
|------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System map, components, patterns, known issues |
| [ENGINE.md](ENGINE.md) | Python engine, Lab loop, API endpoints |
| [CI-CD.md](CI-CD.md) | PR workflow, releases, deployment |
| [INFRASTRUCTURE.md](INFRASTRUCTURE.md) | GCP VM, systemd, env vars, Delta Exchange |
| [DATABASE.md](DATABASE.md) | SQLite schemas, journal systems, state files |
| [EXECUTION.md](EXECUTION.md) | Broker layer, Delta API, order flow |
| [DATA-PIPELINE.md](DATA-PIPELINE.md) | Market data, caching, instruments |
| [RISK.md](RISK.md) | Risk rules, position sizing, compliance |
| [TESTING.md](TESTING.md) | Test structure, CI gates, coverage |
| [DASHBOARD.md](DASHBOARD.md) | Next.js frontend |

## Other Docs

| File | Purpose |
|------|---------|
| `architecture/*.c4` | LikeC4 diagrams (source of truth for visuals) |
| `docs/research/STRATEGIES-DETAILED.md` | Strategy algorithms and parameters |
| `docs/research/COPILOT-DESIGN.md` | Trade autopsy + edge analysis system design (v2.0.19–20) |
| `docs/research/TESTING-AI-CODE.md` | AI testing methodology |
| `docs/reviews/REVIEW-PROMPT.md` | Expert review system (10 panels) |
| `docs/reviews/ISSUES.md` | Review issue tracker |

## Recent Additions (v2.0.23)

**PACE_PRESETS Pattern (v2.0.23):**
- Risk settings live in `PACE_PRESETS` dict, NOT module-level constant
- Anti-pattern: `RISK_PER_TRADE = 0.05` import causes 500 errors
- Always read from `lab_engine._settings.get("risk_per_trade")`

**Delta Testnet Instruments (v2.0.23):**
- Verified 11 perpetuals: BTC, ETH, SOL, XRP, ADA, DOGE (+5 exotics)
- Contract values cached from `/v2/products` API
- DOGEUSD available but not registered (100 DOGE/contract, 100x leverage)
