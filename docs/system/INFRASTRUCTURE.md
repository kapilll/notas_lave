# Infrastructure & Operations

> Last verified against code: 2026-03-28

## GCP VM

| Field | Value |
|-------|-------|
| Name | `notas-lave-engine` |
| Zone | `europe-west1-b` |
| Project | `notaslaveai-prod` |
| External IP | `34.79.66.229` |
| gcloud config | `notas-personal` |
| Account | `kapilparash01@gmail.com` |
| Python | 3.12, venv at `~/.venv-notas` |
| Node | 20 |

## SSH Access

```bash
# Developer access
gcloud compute ssh notas-lave-engine --project=notaslaveai-prod --zone=europe-west1-b

# CI/CD uses deploy key
# GitHub secret VPS_SSH_KEY contains the private key
# VM has the public key in ~/.ssh/authorized_keys
```

## Systemd Services

### notas-engine.service
- **Binary:** `~/.venv-notas/bin/python run.py`
- **WorkDir:** `~/notas_lave/engine`
- **Binds:** `0.0.0.0:8000` (via `API_HOST` env var)
- **Restart:** on-failure

### notas-dashboard.service
- **Binary:** `node_modules/.bin/next start`
- **WorkDir:** `~/notas_lave/dashboard`
- **Port:** `3000`
- **Restart:** on-failure

### Common operations
```bash
# Check status
sudo systemctl status notas-engine notas-dashboard

# Restart
sudo systemctl restart notas-engine
sudo systemctl restart notas-dashboard

# Logs
sudo journalctl -u notas-engine -f
sudo journalctl -u notas-dashboard -f

# Manual deploy
~/notas_lave/deploy.sh
```

## Firewall

| Rule | Ports | Source |
|------|-------|--------|
| `notas-lave-access` | 3000, 8000 | `0.0.0.0/0` |

**WARNING:** Currently open to the entire internet. No auth boundary.
**TODO:** Set up Cloudflare Tunnel + Access for secure dashboard access.

## Sudoers

`kapil.parashar` can restart notas services without password:
```
kapil.parashar ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart notas-engine, /usr/bin/systemctl restart notas-dashboard, /usr/bin/systemctl status notas-engine, /usr/bin/systemctl status notas-dashboard
```

## Environment Variables (on VM)

Stored in `~/notas_lave/engine/.env` (chmod 600):

| Variable | Purpose |
|----------|---------|
| `BROKER` | Active broker (`delta_testnet`) |
| `DELTA_TESTNET_KEY` | Delta Exchange API key |
| `DELTA_TESTNET_SECRET` | Delta Exchange API secret |
| `TELEGRAM_BOT_TOKEN` | Alert notifications |
| `TELEGRAM_CHAT_ID` | Target chat |
| `CLAUDE_PROVIDER` | `vertex` (Google Cloud) |
| `GOOGLE_CLOUD_PROJECT` | Vertex AI project |
| `API_HOST` | `0.0.0.0` |
| `API_PORT` | `8000` |

## Delta Exchange Testnet

- **URL:** `https://cdn-ind.testnet.deltaex.org`
- **IP whitelist required** — ISP IP changes break auth (401)
- **Whitelist at:** testnet.delta.exchange dashboard
- **Symbols:** `BTCUSD`, `ETHUSD`, `SOLUSD` (NOT `BTCUSDT`)
- **Product IDs:** Fetched on `connect()` via `/v2/products`

## Monitoring

| What | How | Gap |
|------|-----|-----|
| Engine health | `GET /health` | Only checks if API responds |
| Deploy status | Telegram notification | No persistent history |
| Engine logs | `journalctl -u notas-engine` | No log aggregation |
| Disk space | **NONE** | SQLite WAL can grow unbounded |
| WAL checkpoint | Code exists but never scheduled | WAL grows indefinitely |
| DB backup | Code exists but never scheduled | No automated backups |

## Rules

- **Never run Docker.** Systemd services are the deployment model.
- **Deploy via CI/CD only** — manual deploys are for emergencies.
- **SSH deploy key** lives at `~/.ssh/deploy_ed25519` on VM.
- **`.env` must be chmod 600** — the engine checks this on startup.
- **Delta IP whitelist** must be updated when ISP IP changes.
- **gcloud config** must be `notas-personal`, NOT the WellSky work account.
- **Rollback** is automatic on failed health check — saved SHA at `/tmp/notas_lave_rollback_sha`.
