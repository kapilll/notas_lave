# System Documentation

Living reference for each subsystem. Updated with every release.

## For Claude Sessions

1. **Read CLAUDE.md first** — concise project overview
2. **Read the relevant system doc** for the subsystem you're working on
3. **When you fix something, add a rule** to the relevant doc

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
| [LEARNING.md](LEARNING.md) | Analyzer, recommendations, optimizer |
| [TESTING.md](TESTING.md) | Test structure, CI gates, coverage |
| [DASHBOARD.md](DASHBOARD.md) | Next.js frontend |

## Other Docs

| File | Purpose |
|------|---------|
| `architecture/*.c4` | LikeC4 diagrams (source of truth for visuals) |
| `docs/research/STRATEGIES-DETAILED.md` | Strategy algorithms and parameters |
| `docs/research/TRADING-SYSTEM-RESEARCH.md` | Original system research |
| `docs/research/TESTING-AI-CODE.md` | AI testing methodology |
| `docs/reviews/REVIEW-PROMPT.md` | Expert review system (10 panels) |
| `docs/reviews/ISSUES.md` | Review issue tracker |
