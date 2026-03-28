# System Documentation Index

These docs describe the **current state** of each subsystem. They are the source of truth for any Claude session working on the codebase.

## How to Use

1. **Starting a session?** Read ARCHITECTURE.md first for the big picture.
2. **Working on a subsystem?** Read that subsystem's doc for rules and current state.
3. **Fixed something?** Update the relevant doc with a new rule so future sessions know.
4. **Found a bug?** Add it to the "Known Issues" section of the relevant doc.

## Files

| File | What it covers |
|------|---------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System map, component inventory, data flow, design patterns |
| [CI-CD.md](CI-CD.md) | GitHub Actions workflows, PR process, deployment, releases, versioning |
| [ENGINE.md](ENGINE.md) | Python engine internals, Lab loop, API endpoints, run.py |
| [INFRASTRUCTURE.md](INFRASTRUCTURE.md) | GCP VM, systemd, firewall, SSH, env vars, Delta Exchange |
| [DATABASE.md](DATABASE.md) | SQLite schemas, EventStore vs SQLAlchemy, JSON state files |
| [EXECUTION.md](EXECUTION.md) | Broker layer, Delta Exchange API, order flow, symbol mapping |
| [DATA-PIPELINE.md](DATA-PIPELINE.md) | Market data sources, caching, quality checks, instruments |
| [RISK.md](RISK.md) | Risk rules (prop vs personal), position sizing, news blackout |
| [LEARNING.md](LEARNING.md) | Analyzer, recommendations, optimizer, accuracy, A/B testing |
| [TESTING.md](TESTING.md) | Test structure, CI gates, coverage, fixtures, philosophy |
| [DASHBOARD.md](DASHBOARD.md) | Next.js frontend, engine connection, build process |

## Maintenance Rules

- **Keep docs accurate to current code.** Do not document aspirational features.
- **When you fix a bug, add a rule** to the relevant doc so the bug can't recur.
- **Update "Last verified" date** when you confirm a doc matches current code.
- **Known issues go in the doc**, not in a separate tracker (the review system handles that).
