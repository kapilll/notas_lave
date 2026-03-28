# Session Context - Notas Lave Trading System

**Last Updated:** 2026-03-28
**Git Workflow:** PR-based (feature branches → PRs → merge to main)
**Deployed:** GCP VM at `http://34.79.66.229:3000` (dashboard) / `:8000` (engine API)

---

## What Is This Project?
AI-powered autonomous trading system. Engine runs on GCP VM with systemd.
- **Lab Engine:** Trades on exchange testnets (Binance Demo, Delta Exchange Testnet)
- **Dashboard:** Next.js at `:3000`, auto-connects to engine at same hostname `:8000`

## How to Run (Local Dev)
```bash
cd engine && ../.venv/bin/python run.py    # Engine on :8000
cd dashboard && npm run dev                # Dashboard on :3000
```

## How to Run (GCP VM — already running)
```bash
# SSH into VM
gcloud compute ssh notas-lave-engine --project=notaslaveai-prod --zone=europe-west1-b

# Services managed by systemd
sudo systemctl status notas-engine notas-dashboard
sudo journalctl -u notas-engine -f     # Stream engine logs
sudo journalctl -u notas-dashboard -f  # Stream dashboard logs

# Manual deploy
~/notas_lave/deploy.sh
```

## Current State (2026-03-28)
- **v2 architecture** — fully unified under `engine/src/notas_lave/`
- **247 tests pass**, 36% coverage (CI gate at 35%, ratchet up over time)
- **5 brokers:** paper, binance_testnet, delta_testnet, coindcx, mt5
- **Active broker:** Configured via `BROKER` env var in `engine/.env`
- **12 strategies** bridged via IStrategy protocol
- **18 instruments** (BTC, ETH, SOL, XRP, BNB, DOGE, ADA, AVAX, LINK, DOT, LTC, NEAR, SUI, ARB, PEPE, WIF, FTM, ATOM)

## Architecture (v2)
```
engine/src/notas_lave/
├── core/        — models, ports (IBroker, IStrategy, etc.), events, instruments, errors
├── engine/      — event_bus, pnl, lab.py (LabEngine), scheduler
├── execution/   — registry, paper, binance, delta, coindcx, mt5
├── journal/     — event_store (append-only), projections, database.py, schemas.py
├── api/         — app.py (DI Container), system/trade/lab/learning routes
├── strategies/  — 12 strategies + base + registry + bridge
├── data/        — instruments, market_data, calendar, downloader
├── learning/    — grader, analyzer, optimizer, reviews, accuracy, recommendations
├── observability/ — structlog JSON logging
├── alerts/, risk/, confluence/, backtester/, claude_engine/, ml/, monitoring/
└── config.py, log_config.py
```

**Key Patterns:**
- DI Container: `Container(broker, journal, bus, pnl)` — no globals
- Protocols: IBroker, IStrategy, ITradeJournal, IDataProvider, IRiskManager
- Event bus: FailurePolicy.HALT / RETRY_3X / LOG_AND_CONTINUE
- Append-only journal: never UPDATE, only INSERT events
- Broker registry: `@register_broker("name")` + `create_broker("name")`
- Dashboard auto-detects engine URL via `window.location.hostname:8000`

## Deployment
| Component | Details |
|-----------|---------|
| VM | GCP `notas-lave-engine`, `europe-west1-b`, `notaslaveai-prod` project |
| IP | `34.79.66.229` |
| Engine | systemd `notas-engine.service`, binds `0.0.0.0:8000` |
| Dashboard | systemd `notas-dashboard.service`, port `3000` |
| CI/CD | `.github/workflows/deploy.yml` — test → SSH deploy → health check → rollback → Telegram |
| PR checks | `.github/workflows/pr-check.yml` — tests on PRs, no deploy |
| gcloud config | `notas-personal` (account: `kapilparash01@gmail.com`) |
| Python (VM) | 3.12, venv at `~/.venv-notas` |
| Node (VM) | 20, dashboard at `~/notas_lave/dashboard` |

**Deploy flow:** Push/merge to main → GitHub Actions runs tests (247 tests + coverage gate) → SSH to VM → `git pull` → `pip install` → `npm build` → `systemctl restart` → health check → Telegram notification. Auto-rollback on failure.

**GitHub Secrets:** VPS_HOST, VPS_USER, VPS_SSH_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

## Testing
- **247 tests** across unit/, integration/, invariant/, and root domain tests
- **Coverage:** 36% (CI gate at 35%), 9 modules still untested
- **Dev deps:** pytest-cov, hypothesis (property-based), mutmut (mutation testing)
- **Testing strategy:** Human writes invariants/property tests, Claude writes unit tests
- **Research:** `docs/research/TESTING-AI-CODE.md`
- **CI enforcement:** Coverage gate, skip detection (>3 skips = failure)

## Key API Endpoints
| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Engine health check |
| `GET /api/system/health` | Component status, background tasks |
| `GET /api/learning/state` | Complete system memory |
| `GET /api/lab/summary` | Lab performance summary |
| `GET /api/lab/verify` | Data integrity check |
| `GET /api/lab/strategies` | Per-strategy performance |
| `GET /api/learning/recommendations` | Actionable recommendations |
| `GET /api/prices` | Current prices for all instruments |
| `GET /api/scan/all` | Confluence scan all symbols |
| `GET /api/broker/status` | Broker connection, balance, positions |
| `GET /api/risk/status` | P&L, drawdown, trading capacity |

## Key Decisions
- **No Docker** — systemd is simpler, deploys in ~10s vs ~5min with Docker
- **SQLite for now** — single-server, <1000 writes/day. PostgreSQL later.
- **PR workflow** — feature branches, PRs, versioning (changed 2026-03-28)
- **CORS allow all** — engine accessible from any origin (dashboard uses dynamic hostname)

## Delta Exchange Integration (2026-03-26)
- **Testnet URL:** `https://cdn-ind.testnet.deltaex.org`
- **IP whitelist required** — ISP IP changes break auth (401). Whitelist at testnet.delta.exchange
- **Symbols:** Delta uses `BTCUSD`, `ETHUSD`, `SOLUSD` (NOT `BTCUSDT`) — settling in USD
- **Product IDs:** BTCUSD=84, ETHUSD=1699, SOLUSD=92572 (cached on connect via `/v2/products`)
- **Bracket orders:** Server-side SL/TP via `/v2/orders/bracket` — auto-cancels opposing order on fill
- **Balance caching:** `get_balance()` caches last known good value — transient API failures return cache, not 0
- **`run.py` is dynamic:** Broker selected via `BROKER` env var, deposit fetched from broker on startup
- **Positions endpoint:** Uses `/v2/positions/margined` (not `/v2/positions` which requires product_id)

## Environment
- **Delta Exchange Testnet:** cdn-ind.testnet.deltaex.org (IP whitelist required)
- **Binance Demo:** demo-fapi.binance.com (still configured, not active)
- **Vertex AI** for Claude (gcloud auth application-default login)
- **Telegram** for [LAB], [PROD], and [DEPLOY] notifications
- **Firewall:** `notas-lave-access` opens ports 3000, 8000

## What To Do Next
1. Write Hypothesis property tests for critical trading math (position sizing, P&L, risk)
2. Fill test gaps in 9 untested modules (confluence scorer, alerts, backtester, learning/*)
3. Run mutmut to verify existing test quality
4. Set up Cloudflare Tunnel + Access for secure dashboard access (currently open HTTP)
5. Ratchet coverage gate up as tests are added (35% → 50% → 70%)
