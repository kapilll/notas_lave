# CI/CD & Release Workflow

> Last verified against code: 2026-03-28

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
deploy.yml --> test --> SSH deploy --> health check --> Telegram
  |
  | On failure: auto-rollback to previous SHA
  v
GCP VM (systemd restart)
```

## Current State (NEEDS CHANGE)

**Problem:** `deploy.yml` triggers on every push to `main`. This means every merged PR immediately deploys. There is no release gating, no versioning, no changelog.

**Target state:** Deploy only on GitHub Releases with proper semver tags.

## Workflows

### `.github/workflows/pr-check.yml` — PR Validation
- **Trigger:** `pull_request` to `main`
- **Purpose:** Gate PRs on test pass + coverage
- **Steps:**
  1. Checkout + Python 3.13 setup
  2. `pip install -e ".[dev]"` from `engine/`
  3. `pytest tests/ --cov --cov-fail-under=35`
  4. Skip detection: fail if > 3 tests skipped

### `.github/workflows/deploy.yml` — Deploy to VM
- **Trigger:** `push` to `main` (TODO: change to `release` trigger)
- **Steps:**
  1. **Test** — same as pr-check (redundant safety net)
  2. **Deploy** — SSH to VM, `git pull`, `pip install`, `npm build`, `systemctl restart`
  3. **Health check** — polls `http://127.0.0.1:8000/health` for 30s
  4. **Rollback** — on failure, `git checkout` to saved SHA, restart services
  5. **Notify** — Telegram message with result

### Deploy Script on VM
```bash
cd ~/notas_lave
git pull origin main
source ~/.venv-notas/bin/activate
cd engine && pip install -q .
cd ../dashboard && npm install --silent && npm run build
sudo systemctl restart notas-engine
sudo systemctl restart notas-dashboard
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

- **Current:** `pyproject.toml` has `version = "0.1.0"` (never updated)
- **Target:** Semver tags (v1.0.0, v1.1.0, etc.) created via GitHub Releases
- **Changelog:** Maintained in `CHANGELOG.md` at repo root

## Coverage Gate

- **Threshold:** 35% (in `pyproject.toml` and workflow)
- **Ratchet plan:** Increase as tests are added (35% → 50% → 70%)
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
