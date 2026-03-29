# Dashboard (Frontend)

> Last verified against code: v2.0.0 (2026-03-29)

## Overview

Next.js 15 (App Router) dashboard at port 3000. Connects to engine REST API and WebSocket at port 8000.

## Tech Stack

- **Framework:** Next.js 15, React (App Router, client components)
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
