# Dashboard (Frontend)

> Last verified against code: v2.0.16 (2026-03-30)

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

## Layout (v2.0.9)

The Lab tab uses a **3-column grid** that fills the full screen width (no `max-w` cap):

```
[Stats Row: Balance | Trades | Win Rate | P&L]
[Status strip + Action buttons]
┌──────────────────┬──────────────────────────┬──────────────────┐
│ Strategy         │ Trade History            │ Open Positions   │
│ Leaderboard      │ (fixed-height scrollable)│ (LIVE, always    │
│                  │                          │  visible)        │
└──────────────────┴──────────────────────────┴──────────────────┘
[Markets grid — 18 instruments]
```

On mobile (`< lg`) all columns stack to single column automatically.

## WebSocket Live Data

The dashboard uses a single WebSocket connection for all live data.

### Topics subscribed on connect

| Topic | Data | Notes |
|-------|------|-------|
| `trade.positions` | Open broker positions (enriched) | Broadcast **every tick** (v2.0.10) |
| `risk.status` | Balance, P&L, drawdown | — |
| `arena.proposals` | Active proposals + exec_log | — |
| `arena.leaderboard` | Trust scores per strategy | — |
| `lab.status` | Engine running, pace, errors | — |
| `broker.status` | Connected/disconnected | — |
| `system.health` | Health + components | — |
| `trade.executed` | Trade open/close events | — |
| `trade.rejected` | Broker rejection toasts | Includes `reason` field (v2.0.9) |

**Rule:** `trade.positions` is broadcast every tick by the engine, so P&L and `current_price` are always fresh. Do not assume positions only update on trade open/close.

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

- 🟢 **LIVE** — WebSocket connected, data is real-time
- 🟡 **RECONNECTING** — connection lost, retrying
- ⚫ **CONNECTING** — initial connection attempt

### Refresh Button

Sends `{"type": "snapshot"}` over WebSocket AND fetches non-live REST data (scan results, trade history, costs, strategies).

## Open Positions Panel (v2.0.9+)

Each position card shows:
- Symbol, direction, timeframe
- **Proposing strategy name** (e.g. "Level Confluence", "Trend Momentum")
- Progress bar: SL → entry → TP
- Current price, unrealized P&L
- **Close** button — calls `POST /api/lab/close/{trade_id}` (broker first, then journal)
- **Force** button — calls `POST /api/lab/force-close/{symbol}` — use when position is stuck on exchange with no journal entry (e.g. journal already marked closed due to old silent-fail bug)

**Field used for close:** `p.trade_id` (from enriched positions). Never `p.id` — that field does not exist in the position data.

## Trade Rejection Toasts (v2.0.9+)

When a broker rejects an order, a toast appears in the bottom-right:

```
⛔ XRPUSD Rejected
   Insufficient Margin
   Available: $2.60
   Needs: +$124.72
   Mode: isolated
```

The raw Delta JSON in `reason` is parsed by `parseRejectionReason()` in `page.tsx`. An **X button** dismisses the toast immediately (auto-dismiss after 8s).

## Live Proposals (Strategies Tab)

Each proposal card shows rank, strategy, direction, entry/SL/TP, risk/reward in USD and %, capital and margin, READY/BLOCKED status, arena score, signal score, and factors.

**READY/BLOCKED accuracy (v2.0.11+v2.0.13):** The dry-run runs both `calculate_position_size()` and `RiskManager.validate_trade()`. Uses `balance.available` (free margin) not `balance.total` — so proposals only show READY when Delta can actually accept the order given current open positions.

**MARGIN display (v2.0.13):** Shows `notional / max_leverage`, not `notional * margin_pct`. The `margin_pct` field on most alt instruments was set to 0.01 (implying 100x) while `max_leverage` is 10x, causing a 10x understatement.

### Execute Button (v2.0.10)

Each proposal card has an **Execute** button that calls `POST /api/lab/execute-proposal/{rank}`. Result shown inline:

- ✅ `Trade #42 placed on SOLUSD` — success
- ⛔ `Insufficient Margin — Available: $2.60, Needs: +$124.72` — failure with reason

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
- **Optional chaining on all WebSocket-sourced data** — snapshots may arrive with partial payloads. Always use `?.` before accessing nested fields on any state populated from WebSocket messages.
- **Close button uses `trade_id` not `id`** — enriched positions return `trade_id` from the journal. Never read `p.id`.
- **Rejection reason is parsed, not displayed raw** — always use `parseRejectionReason()` before rendering.

## Known Bugs and Post-Mortems

### v2.0.12 — TRADES card always showed 0

**Symptom:** TRADES metric card on Lab tab showed 0 despite 16+ real trades. "N TOTAL TRADES" badge in status bar was correct.

**Root cause:** `GET /api/lab/trades` returns `summary.total_trades` but the dashboard read `summary.total` — a key name mismatch. `total` was `undefined`, coerced to 0.

**Fix:** All references changed to `summary.total_trades`. Also applies to the type definition for `tradeSummary` state.

**Rule:** When the API summary shape changes, search for all usages of the old key in `page.tsx` — there are usually 3–4 (type, state init, render ×2).

### v2.0.4 — Dashboard crash: unguarded `health.components` access

**Symptom:** Dashboard showed Next.js 16's default "This page couldn't load".

**Root cause:** `health.components` was `undefined` in the first WebSocket snapshot. Accessing `health.components.lab_engine` crashed React.

**Fix:** Optional chaining on all `health.components` and `health.data_health` accesses. Error boundaries added (`error.tsx`, `global-error.tsx`).

**Debugging tip:** If the dashboard shows "This page couldn't load" with no error text, capture client-side JS errors with Playwright:
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

### v2.0.10 — Close button was a 404

**Symptom:** Clicking Close on a position silently failed (network tab showed 404).

**Root cause:** Dashboard called `POST /api/lab/close/{id}` but (a) the endpoint didn't exist, and (b) positions have `trade_id` not `id`.

**Fix:** Added `POST /api/lab/close/{trade_id}` endpoint. Dashboard reads `p.trade_id`.

### v2.0.11 — DOGE showed -$232 unrealized P&L

**Symptom:** DOGE LONG showed -$232 in dashboard, actual P&L was +$0.87 on Delta.

**Root cause:** Delta API `unrealized_pnl` field for DOGE returns the negative cost basis (`-(qty * entry_price)` = `-(2500 * 0.093)` = -$232.50) instead of actual P&L.

**Fix:** P&L now computed from first principles in `delta.py`: `(mark_price - entry_price) * qty` for LONG.

**Rule:** Never trust `unrealized_pnl` from the Delta API. Always compute from mark/entry/qty.
