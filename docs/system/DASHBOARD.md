# Dashboard (Frontend)

> Last verified against code: v2.0.6 (2026-03-30)

## Overview

Next.js 16.2.0 (App Router, Turbopack) dashboard at port 3000. Connects to engine REST API and WebSocket at port 8000.

## Tech Stack

- **Framework:** Next.js 16.2.0, React 19.2.4 (App Router, client components)
- **Styling:** TailwindCSS + PostCSS
- **Charting:** CandlestickChart component (TradingView Lightweight Charts v5)
- **Language:** TypeScript
- **Package manager:** npm

## Structure

```
dashboard/
├── app/
│   ├── layout.tsx           # Root layout
│   ├── page.tsx             # Main dashboard (Lab, Strategies, Command, Evolution tabs)
│   ├── error.tsx            # Page-level error boundary (shows crash details + retry)
│   ├── global-error.tsx     # Root layout error boundary (must include <html>/<body>)
│   ├── globals.css          # TailwindCSS
│   └── favicon.ico
├── components/
│   └── CandlestickChart.tsx # OHLCV chart using /api/candles endpoint
├── hooks/
│   └── useWebSocket.ts      # Core WS hook: auto-connect, reconnect, heartbeat
├── lib/
│   ├── api.ts               # REST API client (fetch from engine)
│   └── strategy-info.ts     # Strategy metadata for display
├── next.config.ts
├── package.json
├── tsconfig.json
├── postcss.config.mjs
└── eslint.config.mjs
```

## Engine Connection

```typescript
// Auto-detects engine URL from browser hostname
const ENGINE = `http://${window.location.hostname}:8000`

// WebSocket URL derived from REST URL
const WS_URL = ENGINE.replace(/^https?/, "ws") + "/ws"
```

No build-time env var needed. Works on localhost and GCP VM.

## WebSocket Live Data

The dashboard uses a single WebSocket connection for all live data. Polling has been replaced.

### Topics subscribed on connect

| Topic | Data | Replaces |
|-------|------|---------|
| `trade.positions` | Open broker positions | 30s polling of `/api/lab/positions` |
| `risk.status` | Balance, P&L, drawdown | 30s polling of `/api/risk/status` |
| `arena.proposals` | Active proposals + exec_log | 10s polling of `/api/lab/arena` |
| `arena.leaderboard` | Trust scores per strategy | 10s polling |
| `lab.status` | Engine running, pace, errors | 30s polling of `/api/lab/status` |
| `broker.status` | Connected/disconnected | 30s polling |
| `system.health` | Health + components | 30s polling of `/api/system/health` |
| `trade.executed` | Trade open/close events | N/A (new) |
| `trade.rejected` | Broker rejection toasts | N/A (new) |

### useWebSocket hook (`hooks/useWebSocket.ts`)

```typescript
const { status, lastConnected, send, requestSnapshot } = useWebSocket({
  url: WS_URL,
  topics: ["trade.positions", "risk.status", ...],
  onMessage: (msg) => { /* update state */ },
})
```

- `status`: `"connecting" | "connected" | "reconnecting"`
- Heartbeat: auto-pong to server pings (15s interval)
- Reconnect: exponential backoff (1s → 2s → 4s → ... → 30s max)
- On connect: server sends full snapshot for all subscribed topics

### Connection Status UI

Replaces the 30s countdown progress bar:
- 🟢 **LIVE** — WebSocket connected, data is real-time
- 🟡 **RECONNECTING** — connection lost, retrying
- ⚫ **CONNECTING** — initial connection attempt

### Refresh Button

Sends `{"type": "snapshot"}` over WebSocket (triggers server snapshot for all topics) AND fetches non-live REST data (scan results, trade history, costs, strategies).

## Build & Deploy

```bash
# Local dev
cd dashboard && npm run dev    # :3000 with hot reload

# Production build (on VM)
cd dashboard && npm install --silent && npm run build
# Served by systemd notas-dashboard.service via `next start`
```

## Rules

- **No build-time environment variables** for engine URL — auto-detect from hostname.
- **Dashboard is rebuilt on every deploy** — `npm run build` runs on VM.
- **CORS** must include dashboard origin in `CORS_ORIGINS` env on engine.
- **No polling** — all live data via WebSocket. REST used only for initial load and static/historical data.
- **WebSocket auth** — if `API_KEY` env set on engine, connect with `?api_key=<key>` query param.
- **Stale data**: WebSocket disconnect dims live sections until reconnected.
- **Optional chaining on all WebSocket-sourced data** — WebSocket snapshots may arrive with partial payloads (e.g. `health.components` may be undefined even when `health` is truthy). Always use `?.` before accessing nested fields on any state populated from WebSocket messages. See v2.0.4 crash below.

## Known Bugs and Post-Mortems

### v2.0.4 — Dashboard crash: unguarded `health.components` access (2026-03-30)

**Symptom:** Dashboard showed Next.js 16's default "This page couldn't load" with no visible error.

**Root cause:** `HealthBar` and `LabTab` in `page.tsx` accessed `health.components.lab_engine` and `health.components.broker` without null guards. The WebSocket `system.health` snapshot sets `engineOnline = true` and triggers `health` state update, but `health.components` was `undefined` in the first snapshot. React threw `TypeError: Cannot read properties of undefined (reading 'lab_engine')`, crashed the entire page, and Next.js 16's error boundary showed the generic error page (no stack visible to users).

**Fix:** Added optional chaining on every `health.components` and `health.data_health` sub-field access in `page.tsx`. Changed component guards from `if (!health)` to `if (!health?.components)`. Changed all inline renders of `{health && health.components.X}` to `{health?.components?.X && ...}`.

**Error boundaries added:** `app/error.tsx` (page-level) and `app/global-error.tsx` (root layout). Any future crash now shows the actual error message and stack in the browser instead of a generic page, making diagnosis instant without needing `gcloud ssh` or Playwright.

**Debugging tip:** If the dashboard shows "This page couldn't load" with no error text, the error boundary isn't catching it — this means a React hydration error or a server component crash. Use Python Playwright to capture client-side JS errors:
```python
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://34.100.222.148:3000")
    page.wait_for_timeout(5000)
    print(errors)
    browser.close()
```
