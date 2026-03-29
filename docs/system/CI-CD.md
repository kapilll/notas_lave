# CI/CD & Release Workflow

> Last verified against code: v2.0.4 (2026-03-30)

## Pipeline Overview

```
Developer
  |
  | git push (feature branch)
  v
GitHub PR --> pr-check.yml (tests + coverage)
  |
  | Merge to main (after PR approval)
  v
Create GitHub Release (vX.Y.Z tag)
  |
  | release published
  v
deploy.yml --> test --> validate broker config --> SSH deploy --> health check --> Telegram
  |
  | On failure: auto-rollback to previous SHA
  v
GCP VM (systemd restart)
```

## Workflow

**Deploys are gated by GitHub Releases.** Merging a PR to main does NOT deploy — only publishing a Release with a semver tag triggers deployment.

## Workflows

### `.github/workflows/pr-check.yml` — PR Validation
- **Trigger:** `pull_request` to `main`
- **Purpose:** Gate PRs on test pass + coverage
- **Steps:**
  1. Checkout + Python 3.13 setup
  2. `pip install -e ".[dev]"` from `engine/`
  3. `pytest tests/ --cov --cov-fail-under=49`
  4. Skip detection: fail if > 3 tests skipped

### `.github/workflows/deploy.yml` — Deploy to VM
- **Trigger:** `release` published (semver tag like `v1.0.0`)
- **Steps:**
  1. **Test** — same as pr-check (redundant safety net)
  2. **Pre-deploy validation** — checks broker config is valid before restarting services
  3. **Deploy** — SSH to VM, `git pull`, `pip install`, run `scripts/migrate_schema.py`, `npm build`, `systemctl restart`
  4. **Health check** — polls `http://127.0.0.1:8000/health` (engine) and `http://127.0.0.1:3000` (dashboard) for 30s
  5. **Rollback** — on failure, `git checkout` to saved SHA, restart services
  6. **Notify** — Telegram message with result

### Deploy Script on VM
```bash
cd ~/notas_lave
git pull origin main
source ~/.venv-notas/bin/activate
cd engine && pip install -q .
../.venv/bin/python scripts/migrate_schema.py   # explicit schema migration (v2.0.3)
cd ../dashboard && npm install --silent && npm run build
sudo systemctl restart notas-engine
sudo systemctl restart notas-dashboard
# Health check: engine on :8000, dashboard on :3000
```

## GitHub Secrets

| Secret | Purpose |
|--------|---------|
| `VPS_HOST` | GCP VM external IP |
| `VPS_USER` | SSH username |
| `VPS_SSH_KEY` | SSH private key for deploy |
| `TELEGRAM_BOT_TOKEN` | Deploy notifications |
| `TELEGRAM_CHAT_ID` | Target chat for notifications |

## Versioning

- Semver tags (`v0.1.0`, `v1.0.0`, etc.) created via GitHub Releases
- `CHANGELOG.md` at repo root documents every release
- `pyproject.toml` version should match the latest release tag

### How to release
1. Update `CHANGELOG.md` — move items from `[Unreleased]` to a new version section
2. Update `version` in `engine/pyproject.toml` to match
3. Merge the version bump PR to main
4. Create a GitHub Release with tag `vX.Y.Z` pointing to main
5. `deploy.yml` triggers automatically — tests, deploys, notifies

## Coverage Gate

- **Threshold:** 49% (in `pyproject.toml` and workflow)
- **Ratchet plan:** Increase as tests are added (49% → 60% → 70%)
- **Skip detection:** > 3 skipped tests = CI failure

## Rules

- **Never deploy from main push.** Only deploy from tagged releases.
- **Every PR must pass `pr-check.yml`** before merge.
- **Version in `pyproject.toml`** must match the release tag.
- **`CHANGELOG.md`** must be updated in the PR that bumps the version.
- **No `--no-verify`** on git hooks.
- **Rollback is automatic** on health check failure — do not add `--force` flags.
- **Telegram notifications** on every deploy (success or failure).
- **Dashboard is rebuilt on deploy** — `npm run build` runs on VM, not in CI.
- **Schema migration runs before engine restart** — `scripts/migrate_schema.py` is an explicit deploy step (v2.0.3). Never rely on engine startup to auto-migrate a production database.
- **Dashboard health check is mandatory** — deploy fails if port 3000 doesn't return HTTP 200 after rebuild. A blank dashboard is a deploy failure, not a post-deploy issue.
